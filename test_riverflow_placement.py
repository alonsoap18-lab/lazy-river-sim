"""Placement diagnostics must conserve the same Manning resistance as the app."""

from math import isclose

from core.beach_geometry import compute_beach_geometry
from core.riverflow_model import compute_riverflow_plan
from core.riverflow_placement import (cumulative_manning_resistance,
                                      placement_gaps,
                                      suggest_friction_balanced_positions)
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


if __name__ == "__main__":
    test_uniform_loop_has_equal_friction_gaps()
    test_dxf_resistance_and_recommendation_are_consistent()
    print("Riverflow placement checks passed")
