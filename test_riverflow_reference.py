"""Checks for the documented Brannon examples used by the local app."""

from math import isclose

from core.riverflow_model import (US_GPM_TO_M3_H, compute_riverflow_plan,
                                  riverflow_flow_at_head_ft)
from core.riverflow_reference import (LAZY_RIVER_REFERENCES,
                                      reference_operating_point)
from test_riverflow_model import geometry


def test_published_points_and_nozzle_velocity_are_converted():
    sch40, sch80 = LAZY_RIVER_REFERENCES
    point40 = reference_operating_point(sch40)
    point80 = reference_operating_point(sch80)
    assert isclose(point40.flow_m3_h, 2014 * US_GPM_TO_M3_H)
    assert isclose(point40.system_head_ft, 6.5)
    assert isclose(point40.exit_velocity_m_s, 15.5 * 0.3048)
    assert point80.flow_m3_h < point40.flow_m3_h
    assert point80.system_head_ft > point40.system_head_ft
    # The raster-derived pump curve agrees to about 0.1% with the example.
    assert abs(riverflow_flow_at_head_ft(6.5) / US_GPM_TO_M3_H - 2014) < 5


def test_reduced_speed_is_explicit_affinity_scenario():
    reference = LAZY_RIVER_REFERENCES[0]
    full = reference_operating_point(reference)
    reduced = reference_operating_point(reference, 0.8)
    assert isclose(reduced.flow_m3_h, full.flow_m3_h * 0.8)
    assert isclose(reduced.pump_head_ft, full.pump_head_ft * 0.8 ** 2)
    assert isclose(reduced.exit_velocity_m_s, full.exit_velocity_m_s * 0.8)


def test_reference_changes_propulsion_but_not_filtration():
    stations = geometry()
    plans = [compute_riverflow_plan(
        stations, depth_m=1.2, target_lap_min=40, active_modules=19,
        module_head_full_speed_ft=reference.head_ft,
        module_flow_full_speed_override_m3_h=reference_operating_point(reference).flow_m3_h)
        for reference in LAZY_RIVER_REFERENCES]
    assert plans[1].installed_operating_flow_m3_h < plans[0].installed_operating_flow_m3_h
    assert plans[1].estimated_lap_min > plans[0].estimated_lap_min
    assert plans[1].filtration_flow_m3_h == plans[0].filtration_flow_m3_h


if __name__ == "__main__":
    test_published_points_and_nozzle_velocity_are_converted()
    test_reduced_speed_is_explicit_affinity_scenario()
    test_reference_changes_propulsion_but_not_filtration()
    print("Riverflow reference checks passed")
