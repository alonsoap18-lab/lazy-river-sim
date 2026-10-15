"""No-2%-input screening checks for the Riverflow decision surface."""

from math import isclose

from streamlit.testing.v1 import AppTest

from core.beach_geometry import compute_beach_geometry
from core.orchestrator import LazyRiverModel
from core.riverflow_model import compute_riverflow_plan
from core.riverflow_nozzle_screen import count_sensitivity, screen_lap_band


def _case(transfer: float = .02, count: int = 24):
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    beach = compute_beach_geometry(model.stations, 1.2, 15, .62,
                                   flat_ramp_slope=.065)
    plan = compute_riverflow_plan(
        model.stations, depth_m=1.2, target_lap_min=35,
        active_modules=count, transfer_fraction=transfer,
        beach_geometry=beach, floor_manning_n=.013,
        wall_manning_n_current=.025, wall_manning_n_calm=.025,
        module_flow_full_speed_override_m3_h=450)
    return model, beach, plan


def test_lap_band_is_independent_of_legacy_two_percent():
    model, beach, low = _case(.005)
    _, _, high = _case(.20)
    first = screen_lap_band(model.stations, low, beach.wetted_perimeter_m)
    second = screen_lap_band(model.stations, high, beach.wetted_perimeter_m)
    assert first == second
    assert [row.lap_min for row in first.requirements] == [30, 35, 40]
    assert isclose(first.requirements[1].effective_speed_m_s, 536 / (35 * 60))
    assert first.requirements[0].required_channel_flow_m3_h > (
        first.requirements[2].required_channel_flow_m3_h)


def test_roughness_and_pump_count_change_physical_requirement():
    model, beach, plan = _case(count=24)
    normal = screen_lap_band(model.stations, plan, beach.wetted_perimeter_m)
    rough = screen_lap_band(model.stations, plan, beach.wetted_perimeter_m,
                                  roughness_scale=1.2)
    assert isclose(rough.requirements[1].required_drag_n /
                   normal.requirements[1].required_drag_n, 1.44)
    assert isclose(rough.requirements[1].fraction_of_gross_nozzle_momentum /
                   normal.requirements[1].fraction_of_gross_nozzle_momentum, 1.44)
    _, _, fewer = _case(count=20)
    fewer_screen = screen_lap_band(model.stations, fewer, beach.wetted_perimeter_m)
    assert fewer_screen.requirements[1].fraction_of_gross_nozzle_momentum > (
        normal.requirements[1].fraction_of_gross_nozzle_momentum)
    rows = count_sensitivity(normal, 24, (20, 24, 28))
    assert rows[0][1][1] > rows[1][1][1] > rows[2][1][1]


def test_app_band_reacts_to_manning_not_legacy_two_percent():
    app = AppTest.from_file("app.py", default_timeout=90).run()
    assert not app.exception

    def band():
        return next(table.value.copy() for table in app.dataframe
                    if "Vuelta objetivo" in table.value.columns)

    initial = band()
    next(slider for slider in app.slider
         if slider.label.startswith("Energía útil para mover el río")).set_value(10.0)
    app.run()
    assert not app.exception
    assert band().equals(initial)
    next(slider for slider in app.slider
         if slider.label.startswith("Manning n · piso liso")).set_value(.020)
    app.run()
    assert not app.exception
    assert not band().equals(initial)
