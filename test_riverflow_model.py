"""Regression checks for the Riverflow planning mode and editable scenarios."""

from math import ceil, isclose

from core.orchestrator import LazyRiverModel
from core.centerline import orient_stations_clockwise, signed_centerline_area
from core.riverflow_model import (RIVERFLOW_RATED_M3_H, US_GPM_TO_M3_H,
                                  compute_riverflow_plan, riverflow_flow_at_head_ft)


def geometry():
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    return model.stations


def test_riverflow_target_and_operating_flow_are_distinct():
    stations = geometry()
    plan = compute_riverflow_plan(stations, depth_m=1.2, target_lap_min=40,
                                  active_modules=19, standby_modules=1)
    assert isclose(plan.installed_operating_flow_m3_h, 19 * RIVERFLOW_RATED_M3_H)
    assert plan.module_head_full_speed_ft == 4.0
    assert isclose(plan.target_equivalent_flow_m3_h, plan.volume_m3 * 60 / 40)
    assert isclose(plan.estimated_lap_min,
                   plan.volume_m3 * 60 / plan.equivalent_channel_flow_m3_h)
    assert isclose(plan.velocity_lap_m_s, plan.length_m / (plan.estimated_lap_min * 60))
    assert plan.required_active_modules == ceil(plan.target_equivalent_flow_m3_h / RIVERFLOW_RATED_M3_H)
    assert plan.active_motor_nameplate_hp == 190
    assert plan.total_motor_nameplate_hp == 200
    assert isclose(plan.filtration_flow_m3_h, plan.volume_m3 / 4)
    assert all(plan.station_zones[min(range(len(stations)),
               key=lambda i: abs(stations[i]["chainage_m"] - position))] == "current"
               for position in plan.module_chainages_m)


def test_manual_changes_propagate_through_scenario():
    stations = geometry()
    normal = compute_riverflow_plan(stations, depth_m=1.2, target_lap_min=40,
                                     active_modules=19, standby_modules=1)
    slower = compute_riverflow_plan(stations, depth_m=1.2, target_lap_min=40,
                                     active_modules=20, standby_modules=2,
                                     speed_fraction=0.8, transfer_fraction=0.7,
                                     filtration_turnover_h=6,
                                     module_chainages_m=[10.0 * i for i in range(20)])
    assert slower.installed_operating_flow_m3_h == 20 * RIVERFLOW_RATED_M3_H * 0.8
    assert isclose(slower.equivalent_channel_flow_m3_h,
                   slower.installed_operating_flow_m3_h * 0.7)
    assert slower.estimated_lap_min > normal.estimated_lap_min
    assert slower.velocity_lap_m_s < normal.velocity_lap_m_s
    assert slower.required_active_modules > normal.required_active_modules
    assert slower.filtration_flow_m3_h < normal.filtration_flow_m3_h
    assert slower.total_motor_nameplate_hp == 220
    assert slower.module_chainages_m[2] == 20.0
    assert slower.max_current_distance_to_module_m > normal.max_current_distance_to_module_m


def test_supplied_curve_changes_all_dependent_results():
    stations = geometry()
    assert isclose(riverflow_flow_at_head_ft(4), 2440 * US_GPM_TO_M3_H)
    assert isclose(riverflow_flow_at_head_ft(7), 1830 * US_GPM_TO_M3_H)
    assert isclose(riverflow_flow_at_head_ft(10), 1220 * US_GPM_TO_M3_H)
    at_four = compute_riverflow_plan(stations, depth_m=1.2, target_lap_min=40,
                                     active_modules=19, module_head_full_speed_ft=4)
    at_ten = compute_riverflow_plan(stations, depth_m=1.2, target_lap_min=40,
                                    active_modules=19, module_head_full_speed_ft=10)
    assert isclose(at_ten.installed_operating_flow_m3_h, at_four.installed_operating_flow_m3_h / 2)
    assert isclose(at_ten.estimated_lap_min, at_four.estimated_lap_min * 2)
    assert isclose(at_ten.velocity_equivalent_m_s, at_four.velocity_equivalent_m_s / 2)
    assert at_ten.required_active_modules == 2 * at_four.required_active_modules - 1
    assert at_ten.filtration_flow_m3_h == at_four.filtration_flow_m3_h
    for invalid in (3.9, 10.1):
        try:
            riverflow_flow_at_head_ft(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("No se debe extrapolar fuera de las anclas")


def test_geometry_and_calm_threshold_update_integrated_results():
    stations = geometry()
    shallow = compute_riverflow_plan(stations, depth_m=1.0, target_lap_min=40,
                                      active_modules=19, calm_zone_width_m=15)
    deep = compute_riverflow_plan(stations, depth_m=1.4, target_lap_min=40,
                                   active_modules=19, calm_zone_width_m=20)
    assert deep.volume_m3 > shallow.volume_m3
    assert deep.target_equivalent_flow_m3_h > shallow.target_equivalent_flow_m3_h
    assert deep.estimated_lap_min > shallow.estimated_lap_min
    assert deep.calm_zone_length_m < shallow.calm_zone_length_m


def test_clockwise_direction_and_manning_friction_are_auditable():
    stations = geometry()
    assert signed_centerline_area(stations) < 0
    length = float(stations[-1]["chainage_m"])
    ccw = [dict(stations[0]), *(dict(s) for s in reversed(stations[1:-1])),
           dict(stations[-1])]
    for i, station in enumerate(ccw):
        station["chainage_m"] = (0.0 if i == 0 else length if i == len(ccw) - 1
                                 else length - float(station["chainage_m"]))
    assert signed_centerline_area(ccw) > 0
    normalized = orient_stations_clockwise(ccw)
    assert signed_centerline_area(normalized) < 0
    assert all(a["chainage_m"] <= b["chainage_m"] for a, b in zip(normalized, normalized[1:]))
    base = compute_riverflow_plan(normalized, depth_m=1.2, target_lap_min=40,
                                  active_modules=19, manning_n_current=0.015,
                                  manning_n_calm=0.015)
    rough = compute_riverflow_plan(normalized, depth_m=1.2, target_lap_min=40,
                                   active_modules=19, manning_n_current=0.030,
                                   manning_n_calm=0.030)
    assert isclose(base.volume_m3, compute_riverflow_plan(
        stations, depth_m=1.2, target_lap_min=40, active_modules=19).volume_m3)
    assert isclose(rough.channel_friction_head_m, 4 * base.channel_friction_head_m)
    assert isclose(rough.target_channel_friction_head_m, 4 * base.target_channel_friction_head_m)
    assert isclose(rough.estimated_lap_min, base.estimated_lap_min)
    assert isclose(base.current_lap_min + base.calm_lap_min, base.estimated_lap_min)
    assert len(base.cumulative_friction_head_m) == len(normalized)
    assert isclose(base.cumulative_friction_head_m[-1], base.channel_friction_head_m)


if __name__ == "__main__":
    test_riverflow_target_and_operating_flow_are_distinct()
    test_manual_changes_propagate_through_scenario()
    test_supplied_curve_changes_all_dependent_results()
    test_geometry_and_calm_threshold_update_integrated_results()
    test_clockwise_direction_and_manning_friction_are_auditable()
    print("Riverflow planning checks passed")
