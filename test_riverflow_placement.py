"""Placement diagnostics must conserve the same Manning resistance as the app."""

from math import isclose

from core.beach_geometry import compute_beach_geometry
from core.riverflow_model import compute_riverflow_plan
from core.riverflow_placement import (cumulative_manning_resistance,
                                      curve_candidates,
                                      placement_gaps,
                                      suggest_friction_balanced_positions,
                                      suggest_width_aware_positions)
from test_riverflow_model import geometry


def test_uniform_loop_has_equal_friction_gaps():
    stations = [{"chainage_m": float(s)} for s in (0, 10, 20, 30, 40)]
    cumulative = cumulative_manning_resistance(stations, (10.0,) * 5,
                                                (12.0,) * 5, (.02,) * 5)
    gaps = placement_gaps(stations, cumulative, (5.0, 15.0, 25.0, 35.0))
    assert isclose(gaps.max_gap_m, 10.0)
    assert isclose(gaps.max_friction_share, .25)
    assert isclose(gaps.friction_imbalance, 1.0)


def test_dxf_resistance_and_recommendation_are_consistent():
    stations = geometry()
    beach = compute_beach_geometry(stations, 1.2)
    plan = compute_riverflow_plan(stations, depth_m=1.2, target_lap_min=40,
                                  active_modules=19, floor_manning_n=.013,
                                  wall_manning_n_current=.025,
                                  wall_manning_n_calm=.025,
                                  beach_geometry=beach)
    cumulative = cumulative_manning_resistance(
        stations, plan.station_areas_m2, beach.wetted_perimeter_m,
        plan.station_manning_n)
    assert isclose(cumulative[-1], plan.channel_resistance_s2_m5, rel_tol=1e-12)
    proposal = suggest_friction_balanced_positions(
        stations, cumulative, plan.station_zones, plan.active_modules)
    assert len(proposal) == plan.active_modules
    assert len(set(proposal)) == plan.active_modules
    eligible = {float(station["chainage_m"]) for station, zone in
                zip(stations, plan.station_zones) if zone == "current"}
    assert set(proposal) <= eligible
    assert placement_gaps(stations, cumulative, proposal).max_friction_share > 0


def test_width_aware_layout_covers_passing_bays_without_pumps_on_main_beach():
    stations = geometry()
    beach = compute_beach_geometry(stations, 1.2)
    plan = compute_riverflow_plan(stations, depth_m=1.2, target_lap_min=40,
                                  active_modules=19, floor_manning_n=.013,
                                  wall_manning_n_current=.025,
                                  wall_manning_n_calm=.025, beach_geometry=beach)
    resistance = cumulative_manning_resistance(
        stations, plan.station_areas_m2, beach.wetted_perimeter_m,
        plan.station_manning_n)
    bends = curve_candidates(stations, plan.station_zones, 1.0)
    positions, banks = suggest_width_aware_positions(
        stations, resistance, plan.station_zones, 19, bends)
    assert len(positions) == len(set(positions)) == 19
    assert tuple(sorted(positions)) == positions
    for start, end in ((138, 172), (211, 229), (312, 329)):
        in_bay = [bank for position, bank in zip(positions, banks)
                  if start <= position < end]
        assert "Interior" in in_bay and "Exterior" in in_bay
    for position in positions:
        index = min(range(len(stations)), key=lambda i:
                    abs(float(stations[i]["chainage_m"]) - position))
        assert plan.station_zones[index] == "current"
    assert placement_gaps(stations, resistance, positions).max_gap_m < 160


def test_relocation_does_not_invent_longitudinal_flow_or_flatten_area_speeds():
    stations = geometry()
    beach = compute_beach_geometry(stations, 1.2)
    base = compute_riverflow_plan(stations, depth_m=1.2, target_lap_min=40,
                                  active_modules=19, beach_geometry=beach)
    moved = compute_riverflow_plan(
        stations, depth_m=1.2, target_lap_min=40, active_modules=19,
        beach_geometry=beach,
        module_chainages_m=(146, 164, 215, 225, 316, 322, 42, 74, 92, 110,
                            128, 189, 247, 270, 293, 352, 382, 406, 430))
    assert isclose(base.equivalent_channel_flow_m3_h,
                   moved.equivalent_channel_flow_m3_h, rel_tol=1e-12)
    assert isclose(base.estimated_lap_min, moved.estimated_lap_min, rel_tol=1e-12)
    assert moved.velocity_max_m_s > moved.velocity_min_m_s


def test_narrow_beach_approach_stays_active_and_last_pump_is_near_widening():
    stations = geometry()
    beach = compute_beach_geometry(stations, 1.2, 15.0, first_share=.62,
                                   flat_ramp_slope=.065)
    plan = compute_riverflow_plan(stations, depth_m=1.2, target_lap_min=40,
                                  active_modules=19, beach_geometry=beach,
                                  calm_zone_width_m=15.0)
    no_profile = compute_riverflow_plan(stations, depth_m=1.2,
                                        target_lap_min=40, active_modules=19,
                                        calm_zone_width_m=15.0)

    def zone_at(result, chainage):
        i = min(range(len(stations)), key=lambda j:
                abs(float(stations[j]["chainage_m"]) - chainage))
        return result.station_zones[i]

    for result in (plan, no_profile):
        assert zone_at(result, 430) == "current"
        assert zone_at(result, 497) == "current"
        assert zone_at(result, 507) == "calm"
        assert zone_at(result, 150) == "current"  # other wide passage
    resistance = cumulative_manning_resistance(
        stations, plan.station_areas_m2, beach.wetted_perimeter_m,
        plan.station_manning_n)
    positions, _ = suggest_width_aware_positions(
        stations, resistance, plan.station_zones, 19,
        curve_candidates(stations, plan.station_zones, 1.0))
    calm_start = min(float(stations[i]["chainage_m"])
                     for i in range(1, len(stations) - 1)
                     if plan.station_zones[i] == "calm" and
                     plan.station_zones[i - 1] == "current")
    assert 5 <= calm_start - positions[-1] <= 15
    assert zone_at(plan, positions[-1]) == "current"


if __name__ == "__main__":
    test_uniform_loop_has_equal_friction_gaps()
    test_dxf_resistance_and_recommendation_are_consistent()
    print("Riverflow placement checks passed")
