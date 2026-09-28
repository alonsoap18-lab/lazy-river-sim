"""Regression checks for source-bounded Riverflow sensitivity scenarios."""

from math import isclose

from core.beach_geometry import compute_beach_geometry
from core.riverflow_envelope import evaluate_envelope
from core.riverflow_local_circuit import LocalCircuit, solve_local_circuit
from core.riverflow_2d import compute_field_2d
from core.riverflow_model import compute_riverflow_plan
from test_riverflow_model import geometry


def test_envelope_matches_full_integrated_model():
    stations = geometry()
    beach = compute_beach_geometry(stations, 1.2, 15)
    circuit = LocalCircuit(8, .303, 8, .303, 1, 1, 3)
    rows = evaluate_envelope(
        stations, circuit, depth_m=1.2, target_lap_min=40,
        module_counts=(19,), speeds_pct=(80, 100), k_factors=(1.0,),
        transfer_fraction=.02, curve_mode="photo", calm_zone_width_m=15,
        floor_manning_n=.013, wall_manning_n_current=.025,
        wall_manning_n_calm=.025, beach_geometry=beach,
        current_modules=19, current_angles_deg=[0] * 19)
    for row in rows:
        assert row.status != "Fuera de curva disponible"
        point = solve_local_circuit(circuit, speed_fraction=row.speed_pct / 100)
        plan = compute_riverflow_plan(
            stations, depth_m=1.2, target_lap_min=40, active_modules=19,
            module_head_full_speed_ft=point.pump_head_ft / (row.speed_pct / 100) ** 2,
            module_flow_full_speed_override_m3_h=point.flow_m3_h / (row.speed_pct / 100),
            speed_fraction=row.speed_pct / 100, transfer_fraction=.02,
            calm_zone_width_m=15, floor_manning_n=.013,
            wall_manning_n_current=.025, wall_manning_n_calm=.025,
            beach_geometry=beach, module_angles_deg=[0] * 19)
        field = compute_field_2d(stations, plan, 1.2)
        assert isclose(row.module_flow_m3_h, point.flow_m3_h, rel_tol=1e-8)
        assert isclose(row.volumetric_lap_min, plan.estimated_lap_min, rel_tol=1e-8)
        assert isclose(row.slow_lane_lap_min, max(field.lane_lap_min), rel_tol=1e-8)


def test_envelope_does_not_extrapolate_and_tracks_losses():
    stations = geometry()
    circuit = LocalCircuit(8, .303, 8, .303, 1, 1, 3)
    rows = evaluate_envelope(
        stations, circuit, depth_m=1.2, target_lap_min=40,
        module_counts=(17, 19), speeds_pct=(100,), k_factors=(.5, 1, 1.5),
        transfer_fraction=.02, curve_mode="photo", calm_zone_width_m=15,
        floor_manning_n=.013, wall_manning_n_current=.025,
        wall_manning_n_calm=.025, beach_geometry=None)
    assert any(row.status == "Fuera de curva disponible" for row in rows)
    valid = [row for row in rows if row.modules == 19 and row.module_flow_m3_h is not None]
    assert valid[0].module_flow_m3_h > valid[-1].module_flow_m3_h
    assert valid[0].slow_lane_lap_min < valid[-1].slow_lane_lap_min
    assert all(row.pump_hydraulic_kw_per_unit is None for row in rows
               if row.status == "Fuera de curva disponible")


if __name__ == "__main__":
    test_envelope_matches_full_integrated_model()
    test_envelope_does_not_extrapolate_and_tracks_losses()
    print("Riverflow envelope: OK")
