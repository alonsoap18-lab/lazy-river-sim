"""Regression checks: manual hydraulic controls must propagate consistently."""
from copy import deepcopy

from core.orchestrator import LazyRiverModel


BASE = dict(
    depth_m=1.2, manning_n=0.015, pump_flow_m3_h=17600.0,
    n_jets=16, jet_diameter_m=0.45, pump_efficiency=0.75,
    n_pumps=4, safety_factor=1.15, n_pump_rooms=4,
    water_temp_c=25.0, pump_head_available_m=5.0,
)


def base_model():
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536.0)
    return model


def calculate(base, **overrides):
    model = deepcopy(base)
    args = BASE | overrides
    return model, model.compute_hydraulics(**args)


def test_controls_propagate_to_their_respective_outputs():
    base = base_model()
    _, nominal = calculate(base)

    _, deeper = calculate(base, depth_m=1.4)
    assert deeper.velocity_equivalent_m_s < nominal.velocity_equivalent_m_s
    assert deeper.total_system_tdh_m != nominal.total_system_tdh_m

    _, rougher = calculate(base, manning_n=0.025)
    assert rougher.canal_friction_m > nominal.canal_friction_m
    assert rougher.total_system_tdh_m > nominal.total_system_tdh_m

    _, lower_flow = calculate(base, pump_flow_m3_h=12000.0)
    assert lower_flow.total_flow_m3_h < nominal.total_flow_m3_h
    assert lower_flow.velocity_equivalent_m_s < nominal.velocity_equivalent_m_s
    assert lower_flow.total_system_tdh_m != nominal.total_system_tdh_m

    _, lower_efficiency = calculate(base, pump_efficiency=0.60)
    assert lower_efficiency.total_power_watts > nominal.total_power_watts

    _, fewer_pumps = calculate(base, n_pumps=2)
    assert fewer_pumps.pipe_friction_m != nominal.pipe_friction_m
    assert fewer_pumps.pump_hp > nominal.pump_hp

    _, fewer_rooms = calculate(base, n_pump_rooms=1)
    assert fewer_rooms.pipe_friction_m > nominal.pipe_friction_m

    _, smaller_jets = calculate(base, jet_diameter_m=0.25)
    assert smaller_jets.nozzle_loss_m != nominal.nozzle_loss_m

    _, larger_safety_factor = calculate(base, safety_factor=1.40)
    assert larger_safety_factor.total_power_watts > nominal.total_power_watts

    _, low_head = calculate(base, pump_head_available_m=3.0)
    assert low_head.pump_head_margin_m < 0

    _, cool_water = calculate(base, water_temp_c=15.0)
    _, warm_water = calculate(base, water_temp_c=35.0)
    assert cool_water.pipe_friction_m != warm_water.pipe_friction_m


def test_manual_width_isolated_from_the_cached_base_geometry():
    base = base_model()
    original_width = base.geometry.channel_width_avg_m
    manual = deepcopy(base)
    scale = 6.0 / original_width
    for station in manual.stations:
        station["width_m"] *= scale
    manual.geometry.channel_width_avg_m = 6.0
    _, baseline = calculate(base)
    manual_result = manual.compute_hydraulics(**BASE)
    assert manual_result.velocity_equivalent_m_s > baseline.velocity_equivalent_m_s
    assert base.geometry.channel_width_avg_m == original_width


if __name__ == "__main__":
    test_controls_propagate_to_their_respective_outputs()
    test_manual_width_isolated_from_the_cached_base_geometry()
    print("Manual-control regression checks passed")
