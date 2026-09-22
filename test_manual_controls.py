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


def test_target_lap_time_drives_flow_and_returns_the_requested_time():
    base = base_model()
    _, short_lap = calculate(base, target_lap_time_min=15.0, pump_flow_m3_h=None)
    _, long_lap = calculate(base, target_lap_time_min=30.0, pump_flow_m3_h=None)
    assert abs(short_lap.lap_time_min - 15.0) < 0.02
    assert abs(long_lap.lap_time_min - 30.0) < 0.02
    assert short_lap.total_flow_m3_h > long_lap.total_flow_m3_h
    assert short_lap.velocity_equivalent_m_s > long_lap.velocity_equivalent_m_s
    assert abs(short_lap.velocity_lap_m_s - base.geometry.channel_length_m / (short_lap.lap_time_min * 60.0)) < 1e-12


def test_wide_dxf_sections_are_editable_calm_zones_and_volume_is_positive():
    base = base_model()
    model, result = calculate(base, calm_zone_width_m=15.0)
    zones = [station.zone_type for station in result.stations]
    assert "current" in zones and "calm" in zones
    assert result.calm_zone_length_m > 0
    assert result.current_zone_length_m > 0
    assert result.water_volume_m3 > 0
    alerts = model.safety.evaluate(result.stations)
    minimum_alert = next(alert for alert in alerts if alert.parameter == "Velocidad minima")
    current_min = min(station.velocity_m_s for station in result.stations if station.zone_type == "current")
    assert minimum_alert.value == current_min


def test_automatic_jets_avoid_calm_zones_and_manual_layout_is_honored():
    base = base_model()
    automatic_model, automatic = calculate(base, calm_zone_width_m=15.0, n_jets=8)
    assert all(
        next(station.zone_type for station in automatic.stations
             if abs(station.chainage_m - jet.station_m) < 0.3) == "current"
        for jet in automatic_model.propulsion.get_active_jets()
    )
    manual_model, _ = calculate(
        base, calm_zone_width_m=15.0,
        pump_room_chainages=[100.0, 300.0], jet_chainages=[50.0, 150.0, 350.0], n_jets=3,
    )
    assert [round(jet.station_m) for jet in manual_model.propulsion.get_active_jets()] == [50, 150, 350]
    _, distributed = calculate(base, calm_zone_width_m=15.0, pump_room_chainages=[67.0, 201.0, 335.0, 469.0])
    _, centralized = calculate(base, calm_zone_width_m=15.0, pump_room_chainages=[268.0])
    assert distributed.pipe_friction_m != centralized.pipe_friction_m


if __name__ == "__main__":
    test_controls_propagate_to_their_respective_outputs()
    test_manual_width_isolated_from_the_cached_base_geometry()
    test_target_lap_time_drives_flow_and_returns_the_requested_time()
    test_wide_dxf_sections_are_editable_calm_zones_and_volume_is_positive()
    test_automatic_jets_avoid_calm_zones_and_manual_layout_is_honored()
    print("Manual-control regression checks passed")
