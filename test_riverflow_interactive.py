"""Checks for the separate Riverflow guidance, treatment, and fast playback."""

from math import isclose

from streamlit.testing.v1 import AppTest

from core.orchestrator import LazyRiverModel
from core.riverflow_model import compute_riverflow_plan
from riverflow_app import make_fast_simulation, simulated_positions


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
    assert isclose(plan.estimated_lap_min, plan.volume_m3 * 60 /
                   plan.equivalent_channel_flow_m3_h)


def test_separate_views_and_treatment_recalculate():
    app = AppTest.from_file("app.py", default_timeout=60).run()
    assert not app.exception and len(app.tabs) == 10
    next(item for item in app.radio if item.label == "Seleccionar modelo").set_value(
        "Riverflow · módulos locales")
    app.run()
    assert not app.exception and len(app.tabs) == 7
    assert next(item for item in app.selectbox if item.label ==
                "Acabado propuesto de paredes").value == "Piedra local impermeabilizada"
    assert next(item for item in app.selectbox if item.label ==
                "Lectura de curva H–Q").value.startswith("Puntos visibles")
    friction_before = next(item for item in app.metric if item.label ==
                           "Pérdida canal · escenario").value
    next(item for item in app.selectbox if item.label ==
         "Acabado propuesto de paredes").set_value("Concreto texturizado tipo piedra")
    app.run()
    assert not app.exception
    friction_after = next(item for item in app.metric if item.label ==
                          "Pérdida canal · escenario").value
    assert float(friction_after.split()[0]) < float(friction_before.split()[0])
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
    next(item for item in app.radio if item.label == "Seleccionar modelo").set_value(
        "Modelo original · bombas y jets")
    app.run()
    assert not app.exception and len(app.tabs) == 10


if __name__ == "__main__":
    test_clockwise_fast_playback_is_kinematic_only()
    test_separate_views_and_treatment_recalculate()
    print("Riverflow interactive checks passed")
