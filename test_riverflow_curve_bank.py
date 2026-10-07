"""Regression checks for per-unit circuits, bank choice, bends and NYA beach."""

from math import isclose

import numpy as np

from core.beach_geometry import compute_beach_geometry
from core.orchestrator import LazyRiverModel
from core.riverflow_2d import compute_field_2d
from core.riverflow_local_circuit import LocalCircuit, PVC_12_SCH40_REFERENCE_ID_M, solve_local_circuit
from core.riverflow_model import compute_riverflow_plan
from core.riverflow_placement import (cumulative_manning_resistance,
                                      curve_candidates, placement_gaps,
                                      suggest_curve_aware_positions)
from riverflow_app import make_map


def geometry():
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    return model


def test_flat_beach_reports_submerged_edge_and_updates_volume():
    model = geometry()
    beach = compute_beach_geometry(model.stations, 1.2, 15, .62,
                                   flat_ramp_slope=.065)
    assert isclose(beach.first_slope, 0)
    assert isclose(beach.ramp_slope, .065)
    assert beach.flat_entry_width_m is not None
    assert .60 < beach.beach_end_depth_at_widest_m < .70
    assert not beach.profile_fits_slope_limit
    plain = compute_riverflow_plan(model.stations, depth_m=1.2,
                                   target_lap_min=40, active_modules=19)
    profiled = compute_riverflow_plan(model.stations, depth_m=1.2,
                                      target_lap_min=40, active_modules=19,
                                      beach_geometry=beach)
    assert profiled.volume_m3 < plain.volume_m3
    assert profiled.filtration_flow_m3_h < plain.filtration_flow_m3_h


def test_curve_banks_alternate_and_proposal_preserves_count():
    model = geometry()
    plan = compute_riverflow_plan(model.stations, depth_m=1.2,
                                  target_lap_min=40, active_modules=19)
    bends = curve_candidates(model.stations, plan.station_zones,
                             model.geometry.scale_m_per_unit)
    assert any(b.preferred_bank == "Interior" for b in bends)
    assert any(b.preferred_bank == "Exterior" for b in bends)
    cumulative = cumulative_manning_resistance(
        model.stations, plan.station_areas_m2,
        [s["width_m"] + 2 * 1.2 for s in model.stations],
        plan.station_manning_n)
    positions, banks = suggest_curve_aware_positions(
        model.stations, cumulative, plan.station_zones, 19, bends)
    assert len(positions) == len(banks) == 19
    assert positions == tuple(sorted(positions))
    assert "Interior" in banks
    assert placement_gaps(model.stations, cumulative, positions).max_gap_m < 80


def test_bank_and_per_unit_flow_recalculate_without_inventing_more_water():
    model = geometry()
    base = compute_riverflow_plan(model.stations, depth_m=1.2,
                                  target_lap_min=40, active_modules=19)
    flows = [base.module_flow_full_speed_m3_h] * 19
    flows[0] *= .75
    changed = compute_riverflow_plan(
        model.stations, depth_m=1.2, target_lap_min=40,
        active_modules=19, module_flows_full_speed_m3_h=flows,
        module_banks=["Interior"] + ["Exterior"] * 18)
    assert isclose(changed.installed_operating_flow_m3_h, sum(flows))
    assert changed.estimated_lap_min > base.estimated_lap_min
    outer = compute_field_2d(model.stations, base, 1.2,
                             model.geometry.scale_m_per_unit)
    inner = compute_field_2d(model.stations, compute_riverflow_plan(
        model.stations, depth_m=1.2, target_lap_min=40,
        active_modules=19, module_banks=["Interior"] + ["Exterior"] * 18),
        1.2, model.geometry.scale_m_per_unit)
    assert isclose(outer.section_flow_m3_s[0], inner.section_flow_m3_s[0], rel_tol=.005)
    assert not np.allclose(outer.speed_m_s, inner.speed_m_s)


def test_map_draws_inner_and_outer_units_as_separate_groups():
    model = geometry()
    plan = compute_riverflow_plan(
        model.stations, depth_m=1.2, target_lap_min=40,
        active_modules=4,
        module_banks=["Interior", "Exterior", "Interior", "Exterior"])
    figure = make_map(model, plan, show_installation=True,
                      show_velocity_heatmap=False)
    groups = {trace.name: trace for trace in figure.data}
    assert len(groups["Riverflow · margen interior"].x) == 2
    assert len(groups["Riverflow · margen exterior"].x) == 2
    assert groups["Riverflow · margen interior"].marker.color != (
        groups["Riverflow · margen exterior"].marker.color)


def test_two_different_local_circuits_change_total_and_lap():
    model = geometry()
    d = PVC_12_SCH40_REFERENCE_ID_M
    short = solve_local_circuit(LocalCircuit(8, d, 8, d, 1, 1, 3))
    longer = solve_local_circuit(LocalCircuit(18, d, 18, d, 1, 1, 4))
    assert longer.flow_m3_h < short.flow_m3_h
    uniform = compute_riverflow_plan(
        model.stations, depth_m=1.2, target_lap_min=40, active_modules=2,
        module_flows_full_speed_m3_h=[short.flow_m3_h] * 2)
    mixed = compute_riverflow_plan(
        model.stations, depth_m=1.2, target_lap_min=40, active_modules=2,
        module_flows_full_speed_m3_h=[short.flow_m3_h, longer.flow_m3_h])
    assert isclose(mixed.installed_operating_flow_m3_h,
                   short.flow_m3_h + longer.flow_m3_h)
    assert mixed.estimated_lap_min > uniform.estimated_lap_min


if __name__ == "__main__":
    test_flat_beach_reports_submerged_edge_and_updates_volume()
    test_curve_banks_alternate_and_proposal_preserves_count()
    test_bank_and_per_unit_flow_recalculate_without_inventing_more_water()
    test_map_draws_inner_and_outer_units_as_separate_groups()
    test_two_different_local_circuits_change_total_and_lap()
    print("Riverflow curve, bank and beach checks passed")
