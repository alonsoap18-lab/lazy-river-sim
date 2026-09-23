"""Conservation and scenario sensitivity for the reduced-order 2D preview."""

from math import isclose

import numpy as np

from core.orchestrator import LazyRiverModel
from core.riverflow_2d import compute_field_2d
from core.riverflow_model import compute_riverflow_plan


def test_conservation_and_grid_refinement():
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    plan = compute_riverflow_plan(model.stations, depth_m=1.2,
                                  target_lap_min=40, active_modules=19)
    coarse = compute_field_2d(model.stations, plan, 1.2,
                              model.geometry.scale_m_per_unit, 80, 9)
    fine = compute_field_2d(model.stations, plan, 1.2,
                            model.geometry.scale_m_per_unit, 240, 15)
    for field in (coarse, fine):
        assert field.volume_residual_fraction < 0.005
        assert np.all(field.longitudinal_m_s > 0)
        assert np.allclose(field.section_flow_m3_s,
                           plan.equivalent_channel_flow_m3_h / 3600, rtol=0.005)
        assert field.lane_lap_min[0] != field.lane_lap_min[1]
    assert abs(coarse.lane_lap_min[1] - fine.lane_lap_min[1]) / fine.lane_lap_min[1] < 0.02


def test_positions_angles_and_manning_change_linked_outputs():
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    base = compute_riverflow_plan(model.stations, depth_m=1.2,
                                   target_lap_min=40, active_modules=19)
    positions = list(base.module_chainages_m)
    positions[0] = max(model.stations, key=lambda p: p["width_m"])["chainage_m"]
    beach = compute_riverflow_plan(model.stations, depth_m=1.2,
                                    target_lap_min=40, active_modules=19,
                                    module_chainages_m=positions)
    angled = compute_riverflow_plan(model.stations, depth_m=1.2,
                                     target_lap_min=40, active_modules=19,
                                     module_angles_deg=[60] * 19)
    rough = compute_riverflow_plan(model.stations, depth_m=1.2,
                                   target_lap_min=40, active_modules=19,
                                   manning_n_current=.03, manning_n_calm=.03)
    assert beach.placement_effectiveness < base.placement_effectiveness
    assert angled.placement_effectiveness < base.placement_effectiveness
    assert base.estimated_lap_min < beach.estimated_lap_min < angled.estimated_lap_min
    assert rough.estimated_lap_min > base.estimated_lap_min
    base_field = compute_field_2d(model.stations, base, 1.2, model.geometry.scale_m_per_unit)
    beach_field = compute_field_2d(model.stations, beach, 1.2, model.geometry.scale_m_per_unit)
    rough_field = compute_field_2d(model.stations, rough, 1.2, model.geometry.scale_m_per_unit)
    assert beach_field.lane_lap_min[1] > base_field.lane_lap_min[1]
    assert rough_field.lane_lap_min[1] > base_field.lane_lap_min[1]
    assert not np.allclose(base_field.speed_m_s, beach_field.speed_m_s)
    assert isclose(base.filtration_flow_m3_h, beach.filtration_flow_m3_h)


if __name__ == "__main__":
    test_conservation_and_grid_refinement()
    test_positions_angles_and_manning_change_linked_outputs()
    print("Riverflow 2D checks passed")
