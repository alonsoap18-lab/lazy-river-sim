"""Checks for the separate Riverflow guidance, treatment, and fast playback."""

from math import isclose

from streamlit.testing.v1 import AppTest

from core.orchestrator import LazyRiverModel
from core.riverflow_2d import compute_field_2d
from core.riverflow_model import compute_riverflow_plan
from riverflow_app import make_fast_simulation, make_map, simulated_positions


def test_clockwise_fast_playback_is_kinematic_only():
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    plan = compute_riverflow_plan(model.stations, depth_m=1.2,
                                  target_lap_min=40, active_modules=19)
    xs, ys = simulated_positions(model.stations, 1.0, [0, 0.25, 1.0])
    assert isclose(xs[0], xs[2]) and isclose(ys[0], ys[2])
    assert not (isclose(xs[0], xs[1]) and isclose(ys[0], ys[1]))
    slow = make_fast_simulation(model, plan, 60)
    fast = make_fast_simulation(model, plan, 600)
    assert len(slow.frames) == len(fast.frames) == 72
    assert slow.layout.updatemenus[0].buttons[0].args[1]["frame"]["duration"] > fast.layout.updatemenus[0].buttons[0].args[1]["frame"]["duration"]
    assert any(trace.name == "Velocidad Q/A · mapa" for trace in fast.data)
    assert all(frame.traces == (len(fast.data) - 1,) for frame in fast.frames)
    heatmap = make_map(model, plan)
    plain = make_map(model, plan, show_velocity_heatmap=False)
    assert len(heatmap.data) > len(plain.data)
    field = compute_field_2d(model.stations, plan, 1.2, model.geometry.scale_m_per_unit)
    field_map = make_map(model, plan, field=field)
    field_simulation = make_fast_simulation(model, plan, 300, field)
    assert any(trace.name == "Velocidad 2D · escenario" for trace in field_map.data)
    assert any(trace.name == "Velocidad 2D · escenario" for trace in field_simulation.data)
    assert field_simulation.layout.updatemenus[0].buttons[0].args[1]["frame"]["duration"] == max(
        30, round(field.lane_lap_min[1] * 60_000 / (300 * 72)))
    assert isclose(plan.estimated_lap_min, plan.volume_m3 * 60 /
                   plan.equivalent_channel_flow_m3_h)


def test_scenario_maps_use_one_velocity_scale():
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    plans = [compute_riverflow_plan(model.stations, depth_m=1.2,
                                    target_lap_min=40, active_modules=count)
             for count in (19, 18)]
    fields = [compute_field_2d(model.stations, plan, 1.2,
                               model.geometry.scale_m_per_unit) for plan in plans]
    common_range = (min(float(field.speed_m_s.min()) for field in fields),
                    max(float(field.speed_m_s.max()) for field in fields))
    figures = [make_map(model, plan, field=field, color_range=common_range)
               for plan, field in zip(plans, fields)]
    scales = [[trace.marker for trace in figure.data
               if getattr(trace.marker, "showscale", False)] for figure in figures]
    assert len(scales[0]) == len(scales[1]) == 1
    assert scales[0][0].cmin == scales[1][0].cmin == common_range[0]
    assert scales[0][0].cmax == scales[1][0].cmax == common_range[1]


def test_separate_views_and_treatment_recalculate():
    app = AppTest.from_file("app.py", default_timeout=60).run()
    assert not app.exception and len(app.tabs) == 10


    next(item for item in app.radio if item.label == "Seleccionar modelo").set_value(
        "Riverflow · módulos locales")
    app.run()
    assert not app.exception and len(app.tabs) == 11
    assert any(tab.label == "Hoja de decisión" for tab in app.tabs)
    assert any(item.label == "Q requerido por filtros" for item in app.metric)
    assert next(item for item in app.selectbox if item.label ==
                "Acabado propuesto de paredes").value == "Piedra local impermeabilizada"
    assert next(item for item in app.selectbox if item.label ==
                "Lectura de curva H–Q").value.startswith("Puntos visibles")
    friction_before = next(item for item in app.metric if item.label ==
                           "Pérdida canal · escenario").value
    lap_before = next(item for item in app.metric if item.label ==
                      "Vuelta media V/Q").value
    next(item for item in app.selectbox if item.label ==
         "Acabado propuesto de paredes").set_value("Concreto texturizado tipo piedra")
    app.run()
    assert not app.exception
    friction_after = next(item for item in app.metric if item.label ==
                          "Pérdida canal · escenario").value
    assert float(friction_after.split()[0]) < float(friction_before.split()[0])
    lap_after = next(item for item in app.metric if item.label ==
                     "Vuelta media V/Q").value
    assert float(lap_after.split()[0]) < float(lap_before.split()[0])
    next(item for item in app.slider if item.label ==
         "Ángulo de descarga respecto al recorrido (°)").set_value(45)
    app.run()
    assert not app.exception
    lap_angled = next(item for item in app.metric if item.label ==
                      "Vuelta media V/Q").value
    assert float(lap_angled.split()[0]) > float(lap_after.split()[0])
    filter_flow_before = next(item for item in app.metric if item.label ==
                              "Q requerido por filtros").value
    next(item for item in app.slider if item.label ==
         "Energía útil para mover el río (%)").set_value(4.0)
    app.run()
    assert not app.exception
    lap_more_energy = next(item for item in app.metric if item.label ==
                           "Vuelta media V/Q").value
    assert float(lap_more_energy.split()[0]) < float(lap_angled.split()[0])
    assert next(item for item in app.metric if item.label ==
                "Q requerido por filtros").value == filter_flow_before
    next(item for item in app.number_input if item.label ==
         "Recirculación de filtración (h)").set_value(6.0)
    app.run()
    assert not app.exception
    assert next(item for item in app.metric if item.label ==
                "Vuelta media V/Q").value == lap_more_energy
    assert float(next(item for item in app.metric if item.label ==
                      "Q requerido por filtros").value.split()[0].replace(",", "")) < float(
                          filter_flow_before.split()[0].replace(",", ""))
    area_before = next(item for item in app.metric if item.label ==
                       "Área total de filtración · hipótesis").value
    next(item for item in app.number_input if item.label ==
         "Tasa de filtración de prueba (m/h)").set_value(10.0)
    app.run()
    assert not app.exception
    area_after = next(item for item in app.metric if item.label ==
                      "Área total de filtración · hipótesis").value
    assert float(area_after.split()[0].replace(",", "")) > float(
        area_before.split()[0].replace(",", ""))
    next(item for item in app.number_input if item.label ==
         "Bombas de filtración activas para comparar").set_value(12)
    app.run()
    assert not app.exception
    assert next(item for item in app.metric if item.label ==
                "Bombas activas · escenario").value == "12"
    assert any("Con 12 bombas activas" in item.value for item in app.info)
    next(item for item in app.radio if item.label == "Seleccionar modelo").set_value(
        "Modelo original · bombas y jets")
    app.run()
    assert not app.exception and len(app.tabs) == 10


if __name__ == "__main__":
    test_clockwise_fast_playback_is_kinematic_only()
    test_separate_views_and_treatment_recalculate()
    print("Riverflow interactive checks passed")
