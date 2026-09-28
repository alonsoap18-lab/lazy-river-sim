"""Regression checks for independent treatment and DXF audit calculations."""

from math import isclose

from core.filtration import calculate_backwash, calculate_pipe_losses, evaluate_filtration
from core.geometry_audit import audit_geometry
from core.orchestrator import LazyRiverModel


def test_filtration_n_minus_one_uses_proven_remaining_capacity():
    scenario = evaluate_filtration(
        6833.0, 4.0, installed_pumps=6, standby_pumps=0,
        flow_per_pump_at_dirty_head_m3_h=300.0,
        installed_filters=18, unavailable_filters=0,
        area_per_filter_m2=5.0, maximum_filter_rate_m_h=20.0)
    assert isclose(scenario.required_flow_m3_h, 1708.25)
    assert isclose(scenario.required_per_pump_m3_h, 1708.25 / 6)
    assert scenario.pump_status == "Cumple hipótesis"
    assert scenario.pump_n_minus_1_status == "No cumple hipótesis"
    assert scenario.filter_status == "Cumple hipótesis"


def test_missing_pump_curve_does_not_create_a_pass():
    scenario = evaluate_filtration(
        6833.0, 4.0, installed_pumps=6, standby_pumps=1,
        flow_per_pump_at_dirty_head_m3_h=None,
        installed_filters=0, unavailable_filters=0,
        area_per_filter_m2=None, maximum_filter_rate_m_h=20.0)
    assert scenario.active_pumps == 5
    assert scenario.pump_status == "Dato requerido"
    assert scenario.pump_n_minus_1_status == "Dato requerido"
    assert scenario.filter_status == "Dato requerido"


def test_verified_standby_can_take_over_after_one_duty_failure():
    scenario = evaluate_filtration(
        1000.0, 4.0, installed_pumps=3, standby_pumps=1,
        standby_auto_start=True, flow_per_pump_at_dirty_head_m3_h=130.0,
        installed_filters=2, unavailable_filters=0,
        area_per_filter_m2=10.0, maximum_filter_rate_m_h=20.0)
    assert scenario.active_pumps == 2
    assert scenario.pump_capacity_m3_h == 260.0
    assert scenario.pump_capacity_n_minus_1_m3_h == 260.0


def test_three_filters_out_exceed_trial_rate():
    scenario = evaluate_filtration(
        6833.0, 4.0, installed_pumps=6, standby_pumps=0,
        flow_per_pump_at_dirty_head_m3_h=None,
        installed_filters=18, unavailable_filters=3,
        area_per_filter_m2=5.0, maximum_filter_rate_m_h=20.0)
    assert isclose(scenario.actual_filter_rate_m_h, 1708.25 / 75.0)
    assert scenario.filter_status == "No cumple hipótesis"


def test_backwash_event_is_not_daily_makeup():
    event = calculate_backwash(5.0, 36.0, 6.0, 0.0, 0.0)
    assert isclose(event.flow_m3_h, 180.0)
    assert isclose(event.wash_volume_m3, 18.0)
    assert isclose(event.total_event_volume_m3, 18.0)


def test_darcy_pipe_loss_increases_with_length():
    short = calculate_pipe_losses(300.0, 0.4, 10.0, 0.05, 2.0)
    long = calculate_pipe_losses(300.0, 0.4, 30.0, 0.05, 2.0)
    assert short.velocity_m_s > 0
    assert long.straight_loss_m > short.straight_loss_m
    assert isclose(long.fittings_loss_m, short.fittings_loss_m)


def test_current_dxf_audit_exposes_area_difference_without_mutation():
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    original_widths = [station["width_m"] for station in model.stations]
    checks, area, difference = audit_geometry(
        model.stations, model.loader.outer_wall, model.loader.inner_wall,
        model.geometry.scale_m_per_unit, model.geometry.domain_area_m2)
    assert checks and area > 0
    assert difference is not None
    assert [station["width_m"] for station in model.stations] == original_widths
    assert any(check.status != "Consistente" for check in checks)
