"""Checks that the optional momentum pilot inherits, not replaces, plan flow."""

import numpy as np
from dataclasses import replace

from core.beach_geometry import compute_beach_geometry
from core.orchestrator import LazyRiverModel
from core.riverflow_model import compute_riverflow_plan
from core.riverflow_momentum_pilot import compute_momentum_pilot
from core.riverflow_jet_momentum import NOZZLE_12X7_OPEN_AREA_M2


def test_pilot_conserves_plan_flow_and_responds_to_assumptions():
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    beach = compute_beach_geometry(model.stations, 1.2)
    plan = compute_riverflow_plan(model.stations, depth_m=1.2,
                                  target_lap_min=40, active_modules=19,
                                  beach_geometry=beach)
    base = compute_momentum_pilot(model.stations, plan, 1.2,
                                  model.geometry.scale_m_per_unit,
                                  beach_geometry=beach, jet_acceleration_m_s2=0)
    driven = compute_momentum_pilot(model.stations, plan, 1.2,
                                    model.geometry.scale_m_per_unit,
                                    beach_geometry=beach)
    opposite = compute_momentum_pilot(model.stations, plan, 1.2,
                                      model.geometry.scale_m_per_unit,
                                      beach_geometry=beach, beach_bank="Interior")
    expected_q = plan.equivalent_channel_flow_m3_h / 3600
    for result in (base, driven, opposite):
        assert result.flow_residual_fraction < 1e-10
        assert result.momentum_residual_m_s2 < 1e-9
        assert np.allclose(result.section_flow_m3_s, expected_q)
        assert np.allclose(np.mean(result.depth_m, axis=1) *
                           np.interp(result.chainages_m,
                                     [s["chainage_m"] for s in model.stations],
                                     [s["width_m"] for s in model.stations]),
                           np.interp(result.chainages_m,
                                     [s["chainage_m"] for s in model.stations],
                                     plan.station_areas_m2))
    assert np.max(np.abs(driven.longitudinal_m_s - base.longitudinal_m_s)) > 0.01
    assert np.max(np.abs(opposite.depth_m - driven.depth_m)) > 0.05
    assert all(np.isfinite(driven.lane_lap_min))


def test_pilot_inherits_manning_driven_flow_change():
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    options = dict(depth_m=1.2, target_lap_min=40, active_modules=19)
    smooth = compute_riverflow_plan(model.stations, floor_manning_n=0.012,
                                     wall_manning_n_current=0.016,
                                     wall_manning_n_calm=0.016, **options)
    rough = compute_riverflow_plan(model.stations, floor_manning_n=0.022,
                                    wall_manning_n_current=0.04,
                                    wall_manning_n_calm=0.04, **options)
    assert rough.equivalent_channel_flow_m3_h < smooth.equivalent_channel_flow_m3_h
    runs = [compute_momentum_pilot(model.stations, p, 1.2,
                                   model.geometry.scale_m_per_unit,
                                   jet_acceleration_m_s2=0)
            for p in (smooth, rough)]
    assert runs[1].section_flow_m3_s.mean() < runs[0].section_flow_m3_s.mean()
    assert runs[1].lane_lap_min[1] > runs[0].lane_lap_min[1]


def test_documented_nozzle_momentum_responds_to_opposed_banks():
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    plan = compute_riverflow_plan(
        model.stations, depth_m=1.2, target_lap_min=40, active_modules=2,
        module_chainages_m=(150.0, 150.0),
        module_banks=("Interior", "Exterior"))
    paired = compute_momentum_pilot(
        model.stations, plan, 1.2, model.geometry.scale_m_per_unit,
        nozzle_transfer_fraction=.10, longitudinal_cells=64, lateral_cells=9)
    one_side = compute_momentum_pilot(
        model.stations, replace(plan, module_banks=("Interior", "Interior")),
        1.2, model.geometry.scale_m_per_unit,
        nozzle_transfer_fraction=.10, longitudinal_cells=64, lateral_cells=9)
    expected_exit = plan.module_flows_full_speed_m3_h[0] / 3600 / NOZZLE_12X7_OPEN_AREA_M2
    assert np.isclose(paired.nozzle_exit_speed_m_s[0], expected_exit)
    assert paired.applied_nozzle_thrust_n > 0
    assert paired.flow_residual_fraction < 1e-10
    assert one_side.flow_residual_fraction < 1e-10
    assert np.max(np.abs(paired.longitudinal_m_s - one_side.longitudinal_m_s)) > .001
    assert np.allclose(paired.section_flow_m3_s, one_side.section_flow_m3_s)
