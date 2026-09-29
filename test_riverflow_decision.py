"""Regression checks for the Riverflow decision sheet and manual controls."""

from math import isclose

from core.beach_geometry import compute_beach_geometry
from core.riverflow_2d import compute_field_2d
from core.riverflow_decision import consistency_checks, evaluate_decision_cases
from core.riverflow_local_circuit import LocalCircuit, solve_local_circuit
from core.riverflow_model import compute_riverflow_plan
from test_riverflow_model import geometry


def _scenario(*, depth=1.2, floor_n=.013, transfer=.02, turnover=4.0,
              count=19, speed=1.0, circuit=None):
    stations = geometry()
    beach = compute_beach_geometry(stations, depth, 15)
    point = (solve_local_circuit(circuit, speed_fraction=speed)
             if circuit is not None else None)
    plan = compute_riverflow_plan(
        stations, depth_m=depth, target_lap_min=40, active_modules=count,
        module_head_full_speed_ft=(point.pump_head_ft / speed ** 2 if point else 4),
        module_flow_full_speed_override_m3_h=(point.flow_m3_h / speed if point else None),
        speed_fraction=speed, transfer_fraction=transfer,
        calm_zone_width_m=15, filtration_turnover_h=turnover,
        floor_manning_n=floor_n, wall_manning_n_current=.025,
        wall_manning_n_calm=.025, beach_geometry=beach)
    field = compute_field_2d(stations, plan, depth)
    cases = evaluate_decision_cases(
        stations, current_plan=plan, current_field=field, depth_m=depth,
        scale_m_per_unit=1, calm_zone_width_m=15,
        floor_manning_n=floor_n, wall_manning_n_current=.025,
        wall_manning_n_calm=.025, filtration_turnover_h=turnover,
        beach_geometry=beach)
    return plan, field, cases


def test_central_case_is_exactly_the_visible_scenario():
    plan, field, cases = _scenario()
    assert cases[1].plan is plan
    assert cases[1].field is field
    assert all(ok for _, ok in consistency_checks(plan, 4))
    assert not all(ok for _, ok in consistency_checks(plan, 6))


def test_energy_manning_geometry_and_count_reach_decision_rows():
    base, _, cases = _scenario()
    assert cases[0].slow_lap_min > cases[1].slow_lap_min > cases[2].slow_lap_min
    rough, _, rough_cases = _scenario(floor_n=.022)
    assert rough.estimated_lap_min > base.estimated_lap_min
    assert rough_cases[1].slow_lap_min > cases[1].slow_lap_min
    deep, _, deep_cases = _scenario(depth=1.4)
    assert deep.volume_m3 > base.volume_m3
    assert deep.filtration_flow_m3_h > base.filtration_flow_m3_h
    assert not isclose(deep_cases[1].slow_lap_min, cases[1].slow_lap_min)
    fewer, _, fewer_cases = _scenario(count=16)
    assert fewer.installed_operating_flow_m3_h < base.installed_operating_flow_m3_h
    assert fewer_cases[1].slow_lap_min > cases[1].slow_lap_min


def test_filter_hours_do_not_change_propulsion_decision():
    base, _, cases = _scenario(turnover=4)
    longer, _, longer_cases = _scenario(turnover=6)
    assert longer.filtration_flow_m3_h < base.filtration_flow_m3_h
    assert isclose(longer.estimated_lap_min, base.estimated_lap_min)
    assert isclose(longer_cases[1].slow_lap_min, cases[1].slow_lap_min)


def test_local_circuit_and_speed_reach_all_decision_rows():
    circuit = LocalCircuit(8, .303, 8, .303, 1, 1, 3)
    plan, _, cases = _scenario(circuit=circuit)
    assert cases[1].plan is plan
    assert all(case.plan is not None for case in cases)
    assert all(isclose(case.plan.installed_operating_flow_m3_h,
                       plan.installed_operating_flow_m3_h) for case in cases)
    for case in cases:
        assert all(ok for _, ok in consistency_checks(case.plan, 4))
    slower, _, slower_cases = _scenario(circuit=circuit, speed=.8)
    assert slower.installed_operating_flow_m3_h < plan.installed_operating_flow_m3_h
    assert slower_cases[1].slow_lap_min > cases[1].slow_lap_min


if __name__ == "__main__":
    test_central_case_is_exactly_the_visible_scenario()
    test_energy_manning_geometry_and_count_reach_decision_rows()
    test_filter_hours_do_not_change_propulsion_decision()
    test_local_circuit_and_speed_reach_all_decision_rows()
    print("Riverflow decision checks passed")
