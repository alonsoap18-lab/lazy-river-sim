"""Numerical smoke checks for the local-only 2D preview, not physical validation."""

import numpy as np

from core.orchestrator import LazyRiverModel
from core.riverflow_cfd_preview import compute_cfd_preview
from core.riverflow_model import compute_riverflow_plan


def test_local_preview_conserves_water_and_reacts_to_impulse():
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    plan = compute_riverflow_plan(model.stations, depth_m=1.2,
                                  target_lap_min=40, active_modules=19)
    still = compute_cfd_preview(model, plan, duration_s=20, impulse_fraction=0)
    low = compute_cfd_preview(model, plan, duration_s=20, impulse_fraction=.1)
    high = compute_cfd_preview(model, plan, duration_s=20, impulse_fraction=.2)
    assert np.max(still.speed_m_s) == 0
    assert low.wet_cell_count > 500
    assert low.water_balance_error_m3 < 1e-6
    assert high.water_balance_error_m3 < 1e-6
    assert high.max_courant < .9
    assert np.mean(high.speed_m_s[high.wet]) > np.mean(low.speed_m_s[low.wet]) > 0
    assert len(high.module_x_dxf) == plan.active_modules
    alternate_energy = compute_riverflow_plan(
        model.stations, depth_m=1.2, target_lap_min=40,
        active_modules=19, transfer_fraction=.08)
    independent = compute_cfd_preview(model, alternate_energy,
                                      duration_s=20, impulse_fraction=.1)
    assert not np.isclose(plan.equivalent_channel_flow_m3_h,
                          alternate_energy.equivalent_channel_flow_m3_h)
    assert np.allclose(low.speed_m_s, independent.speed_m_s)


if __name__ == "__main__":
    test_local_preview_conserves_water_and_reacts_to_impulse()
    print("Local 2D preview checks passed")
