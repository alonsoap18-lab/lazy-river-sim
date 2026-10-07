"""DXF-sized beach profile and linked Riverflow results."""

from math import isclose

from core.beach_geometry import compute_beach_geometry
from core.orchestrator import LazyRiverModel
from core.riverflow_2d import compute_field_2d
from core.riverflow_model import compute_riverflow_plan
from streamlit.testing.v1 import AppTest


def _stations():
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    return model


def test_main_beach_fits_dxf_and_keeps_other_bays_deep():
    model = _stations()
    profile = compute_beach_geometry(model.stations, 1.2)
    assert isclose(model.stations[0]["width_m"],
                   max(s["width_m"] for s in model.stations))
    assert profile.beach_start_m > profile.beach_end_m  # crosses 536/0 m
    assert 0 in profile.beach_indices
    assert isclose(profile.area_m2[0], profile.area_m2[-1])
    assert 22 < profile.beach_max_extra_width_m < 23
    assert isclose(profile.first_slope, 0.02665, rel_tol=0.01)
    assert isclose(profile.ramp_slope, 0.06663, rel_tol=0.01)
    assert profile.profile_fits_slope_limit
    assert profile.beach_end_depth_at_widest_m < 1e-6
    other_bay = next(i for i, s in enumerate(model.stations)
                     if 65 < float(s["chainage_m"]) < 70)
    assert isclose(profile.area_m2[other_bay],
                   float(model.stations[other_bay]["width_m"]) * 1.2)


def test_beach_volume_changes_all_derived_quantities_and_2d_conserves_flow():
    model = _stations()
    profile = compute_beach_geometry(model.stations, 1.2)
    plain = compute_riverflow_plan(model.stations, depth_m=1.2,
                                   target_lap_min=40, active_modules=19)
    beach = compute_riverflow_plan(model.stations, depth_m=1.2,
                                   target_lap_min=40, active_modules=19,
                                   beach_geometry=profile)
    assert beach.volume_m3 < plain.volume_m3
    assert beach.target_equivalent_flow_m3_h < plain.target_equivalent_flow_m3_h
    assert beach.filtration_flow_m3_h < plain.filtration_flow_m3_h
    assert beach.channel_resistance_s2_m5 != plain.channel_resistance_s2_m5
    assert beach.estimated_lap_min != plain.estimated_lap_min
    assert beach.station_velocities_m_s != plain.station_velocities_m_s
    field = compute_field_2d(model.stations, beach, 1.2,
                             model.geometry.scale_m_per_unit)
    assert field.volume_residual_fraction < 0.005


def test_manual_profile_fraction_changes_volume_and_flags_unreachable_exit():
    model = _stations()
    base = compute_beach_geometry(model.stations, 1.2, first_share=1 / 3)
    altered = compute_beach_geometry(model.stations, 1.2, first_share=0.50)
    assert altered.ramp_slope == 0.07
    assert not altered.profile_fits_slope_limit
    assert altered.beach_end_depth_at_widest_m > 0
    assert altered.area_m2 != base.area_m2


def test_app_profile_toggle_recalculates_volume_and_filtration():
    app = AppTest.from_file("app.py", default_timeout=60).run()
    assert not app.exception
    next(item for item in app.radio if item.label == "Seleccionar modelo").set_value(
        "Riverflow · NYA")
    app.run()
    assert not app.exception
    volume_with_profile = next(item for item in app.metric if item.label ==
                               "Volumen DXF + perfil").value
    filter_with_profile = next(item for item in app.metric if item.label ==
                               "Filtración separada").value
    next(item for item in app.checkbox if item.label ==
         "Aplicar cotas proporcionales al DXF").set_value(False)
    app.run()
    assert not app.exception
    volume_uniform = next(item for item in app.metric if item.label ==
                          "Volumen DXF uniforme").value
    filter_uniform = next(item for item in app.metric if item.label ==
                          "Filtración separada").value
    assert float(volume_with_profile.split()[0].replace(",", "")) < float(
        volume_uniform.split()[0].replace(",", ""))
    assert float(filter_with_profile.split()[0].replace(",", "")) < float(
        filter_uniform.split()[0].replace(",", ""))


if __name__ == "__main__":
    test_main_beach_fits_dxf_and_keeps_other_bays_deep()
    test_beach_volume_changes_all_derived_quantities_and_2d_conserves_flow()
    test_manual_profile_fraction_changes_volume_and_flags_unreachable_exit()
    test_app_profile_toggle_recalculates_volume_and_filtration()
    print("Beach geometry checks passed")
