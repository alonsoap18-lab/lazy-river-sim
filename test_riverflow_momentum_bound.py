"""Checks for the optimistic, 2%-independent Riverflow impulse bound."""

from dataclasses import replace
from math import isclose

from core.beach_geometry import compute_beach_geometry
from core.orchestrator import LazyRiverModel
from core.riverflow_model import compute_riverflow_plan
from core.riverflow_momentum_bound import compute_momentum_bound


def _case(*, transfer=0.02, count=19, floor_n=0.013, angle=0):
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    beach = compute_beach_geometry(model.stations, 1.2)
    plan = compute_riverflow_plan(
        model.stations, depth_m=1.2, target_lap_min=40,
        active_modules=count, transfer_fraction=transfer,
        floor_manning_n=floor_n, wall_manning_n_current=0.025,
        wall_manning_n_calm=0.025, beach_geometry=beach,
        module_angles_deg=[angle] * count,
    )
    return plan, compute_momentum_bound(model.stations, plan,
                                         beach.wetted_perimeter_m)


def test_bound_does_not_use_unmeasured_energy_fraction():
    low_plan, low = _case(transfer=0.01)
    high_plan, high = _case(transfer=0.04)
    assert low_plan.estimated_lap_min > high_plan.estimated_lap_min
    assert low == high
    assert 0 < low.target_fraction_of_ideal < 1


def test_bound_responds_to_manning_pumps_angles_and_target():
    plan, base = _case()
    _, rough = _case(floor_n=0.025)
    _, fewer = _case(count=10)
    _, angled = _case(angle=45)
    assert rough.target_drag_n > base.target_drag_n
    assert rough.optimistic_min_lap_min > base.optimistic_min_lap_min
    assert fewer.ideal_thrust_n < base.ideal_thrust_n
    assert angled.ideal_thrust_n < base.ideal_thrust_n
    faster_target = replace(plan, target_lap_min=30)
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    beach = compute_beach_geometry(model.stations, 1.2)
    target = compute_momentum_bound(model.stations, faster_target,
                                    beach.wetted_perimeter_m)
    assert target.target_drag_n > base.target_drag_n
    assert isclose(target.optimistic_min_lap_min, base.optimistic_min_lap_min)


if __name__ == "__main__":
    test_bound_does_not_use_unmeasured_energy_fraction()
    test_bound_responds_to_manning_pumps_angles_and_target()
    print("Riverflow momentum bound checks passed")
