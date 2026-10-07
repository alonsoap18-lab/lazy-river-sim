"""Checks for the separate, uncalibrated jet-momentum comparison."""

from math import isclose

from streamlit.testing.v1 import AppTest

from core.beach_geometry import compute_beach_geometry
from core.orchestrator import LazyRiverModel
from core.riverflow_jet_momentum import (NOZZLE_12X7_OPEN_AREA_M2,
                                         nozzle_outlet_k, solve_jet_momentum)
from core.riverflow_local_circuit import (LocalCircuit,
                                          PVC_12_SCH40_REFERENCE_ID_M,
                                          solve_local_circuit)
from core.riverflow_model import compute_riverflow_plan
from core.riverflow_reference import LAZY_RIVER_REFERENCES, reference_operating_point


def geometry():
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    beach = compute_beach_geometry(model.stations, 1.2, 15, .62,
                                   flat_ramp_slope=.065)
    return model, beach


def test_documented_open_area_reproduces_exit_speed():
    point = reference_operating_point(LAZY_RIVER_REFERENCES[0])
    speed = point.flow_m3_h / 3600 / NOZZLE_12X7_OPEN_AREA_M2
    assert isclose(speed, point.exit_velocity_m_s, rel_tol=.002)
    assert 4.6 < speed < 4.8


def test_local_nozzle_loss_is_substituted_not_added():
    diameter = PVC_12_SCH40_REFERENCE_ID_M
    outlet_k = nozzle_outlet_k(diameter, NOZZLE_12X7_OPEN_AREA_M2, .85)
    assert 9 < outlet_k < 11
    circuit = LocalCircuit(8, diameter, 8, diameter, 1, 1, outlet_k)
    point = solve_local_circuit(circuit)
    assert 4 < point.pump_head_ft < 10
    assert 400 < point.flow_m3_h < 500


def test_more_pumps_reduce_required_transfer_but_location_does_not_create_flow():
    model, beach = geometry()
    q = reference_operating_point(LAZY_RIVER_REFERENCES[0]).flow_m3_h
    perimeter = beach.wetted_perimeter_m
    plans = [compute_riverflow_plan(
        model.stations, depth_m=1.2, target_lap_min=40,
        active_modules=count, beach_geometry=beach,
        module_flow_full_speed_override_m3_h=q)
        for count in (16, 19)]
    results = [solve_jet_momentum(model.stations, plan, perimeter)
               for plan in plans]
    low_transfer = solve_jet_momentum(model.stations, plans[1], perimeter,
                                      transfer_fraction=.05)
    high_transfer = solve_jet_momentum(model.stations, plans[1], perimeter,
                                       transfer_fraction=.20)
    assert isclose(high_transfer.channel_flow_m3_h,
                   2 * low_transfer.channel_flow_m3_h, rel_tol=1e-12)
    assert isclose(low_transfer.lap_min, 2 * high_transfer.lap_min,
                   rel_tol=1e-12)
    assert results[1].target_required_transfer_fraction < (
        results[0].target_required_transfer_fraction)
    assert results[1].lap_min < results[0].lap_min
    assert isclose(results[1].channel_flow_m3_h * results[1].lap_min / 60,
                   plans[1].volume_m3, rel_tol=1e-12)
    moved = compute_riverflow_plan(
        model.stations, depth_m=1.2, target_lap_min=40,
        active_modules=19, beach_geometry=beach,
        module_flow_full_speed_override_m3_h=q,
        module_chainages_m=tuple(reversed(plans[1].module_chainages_m)),
        module_banks=["Interior"] * 19)
    relocated = solve_jet_momentum(model.stations, moved, perimeter)
    assert isclose(relocated.channel_flow_m3_h, results[1].channel_flow_m3_h,
                   rel_tol=1e-12)


def test_ui_nozzle_cd_changes_pump_flow_and_impulse_is_independent():
    app = AppTest.from_file("app.py", default_timeout=90).run()
    assert not app.exception
    pump_before = next(item.value for item in app.metric
                       if item.label.startswith("Punto de operación"))
    jet_before = next(item.value for item in app.metric
                      if item.label == "V salida por unidad")
    lap_before = next(item.value for item in app.metric
                      if item.label == "Vuelta media V/Q")
    next(item for item in app.slider if item.label.startswith("Cd supuesto")).set_value(.95)
    app.run()
    assert not app.exception
    assert pump_before != next(item.value for item in app.metric
                               if item.label.startswith("Punto de operación"))
    assert jet_before != next(item.value for item in app.metric
                              if item.label == "V salida por unidad")
    lap_after_cd = next(item.value for item in app.metric
                        if item.label == "Vuelta media V/Q")
    assert lap_before != lap_after_cd
    next(item for item in app.slider
         if item.label.startswith("Fracción de impulso que mueve")).set_value(20)
    app.run()
    assert not app.exception
    assert next(item.value for item in app.metric
                if item.label == "Vuelta media V/Q") == lap_after_cd


if __name__ == "__main__":
    test_documented_open_area_reproduces_exit_speed()
    test_local_nozzle_loss_is_substituted_not_added()
    test_more_pumps_reduce_required_transfer_but_location_does_not_create_flow()
    test_ui_nozzle_cd_changes_pump_flow_and_impulse_is_independent()
    print("Riverflow jet-momentum comparison checks passed")
