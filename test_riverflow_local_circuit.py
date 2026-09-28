"""Checks for the editable, non-certified Riverflow local-circuit scenario."""

from dataclasses import replace
from math import isclose

from core.riverflow_local_circuit import LocalCircuit, circuit_head, solve_local_circuit
from core.riverflow_model import compute_riverflow_plan
from test_riverflow_model import geometry


def test_intersection_and_losses_balance():
    circuit = LocalCircuit(8, .30, 8, .30, 1, 1, 3)
    point = solve_local_circuit(circuit)
    assert 277 < point.flow_m3_h < 554.3
    assert isclose(point.pump_head_ft, point.system_head_ft, rel_tol=1e-10)
    assert isclose(point.system_head_ft * .3048,
                   point.suction_friction_m + point.discharge_friction_m +
                   point.fittings_m + point.outlet_m + circuit.static_head_m)
    assert point.suction_velocity_m_s > 0


def test_circuit_edits_propagate_to_river_scenario():
    base = LocalCircuit(8, .30, 8, .30, 1, 1, 3)
    restrictive = replace(base, suction_length_m=25, discharge_length_m=25,
                          suction_diameter_m=.25, discharge_diameter_m=.25)
    first = solve_local_circuit(base)
    second = solve_local_circuit(restrictive)
    assert second.flow_m3_h < first.flow_m3_h
    stations = geometry()
    plans = [compute_riverflow_plan(stations, depth_m=1.2, target_lap_min=40,
                                   active_modules=19, module_head_full_speed_ft=p.pump_head_ft,
                                   module_flow_full_speed_override_m3_h=p.flow_m3_h)
             for p in (first, second)]
    assert plans[1].installed_operating_flow_m3_h < plans[0].installed_operating_flow_m3_h
    assert plans[1].estimated_lap_min > plans[0].estimated_lap_min
    assert plans[1].velocity_equivalent_m_s < plans[0].velocity_equivalent_m_s
    assert plans[1].filtration_flow_m3_h == plans[0].filtration_flow_m3_h


def test_variable_speed_and_out_of_range_are_explicit():
    circuit = LocalCircuit(8, .30, 8, .30, 1, 1, 3)
    full = solve_local_circuit(circuit)
    half = solve_local_circuit(circuit, speed_fraction=.5)
    # Darcy friction factor also changes with Reynolds number, so affinity
    # scaling of the operating point is approximate even in this simple loop.
    assert isclose(half.flow_m3_h, full.flow_m3_h / 2, rel_tol=.01)
    assert isclose(half.pump_head_ft, full.pump_head_ft / 4, rel_tol=.01)
    try:
        solve_local_circuit(replace(circuit, outlet_k=0, suction_k=0,
                                    discharge_k=0, suction_length_m=0,
                                    discharge_length_m=0))
    except ValueError as exc:
        assert "no cruza" in str(exc)
    else:
        raise AssertionError("No debe extrapolar más allá de la curva disponible")


if __name__ == "__main__":
    test_intersection_and_losses_balance()
    test_circuit_edits_propagate_to_river_scenario()
    test_variable_speed_and_out_of_range_are_explicit()
    print("Riverflow local circuit: OK")
