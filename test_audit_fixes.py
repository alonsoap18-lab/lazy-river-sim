"""Regression checks for audit findings in the published default configuration."""
from core.orchestrator import LazyRiverModel


def build_default_model(pump_head_m=5.0):
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536.0)
    result = model.compute_hydraulics(
        depth_m=1.2, manning_n=0.015, pump_flow_m3_h=17600.0,
        n_jets=16, jet_diameter_m=0.45, pump_efficiency=0.75,
        n_pumps=4, safety_factor=1.15, n_pump_rooms=4,
        water_temp_c=25.0, pump_head_available_m=pump_head_m,
    )
    return model, result


def test_equivalent_velocity_is_q_over_average_area():
    model, result = build_default_model()
    expected = result.total_flow_m3_s / (model.geometry.channel_width_avg_m * 1.2)
    assert abs(result.velocity_equivalent_m_s - expected) < 1e-12
    assert result.velocity_equivalent_m_s != result.velocity_avg_m_s


def test_insufficient_nominal_head_is_reported_without_faking_an_operating_point():
    _, result = build_default_model(pump_head_m=3.0)
    assert result.pump_head_margin_m < 0
    assert any("TDH nominal insuficiente" in warning for warning in result.warnings)


if __name__ == "__main__":
    test_equivalent_velocity_is_q_over_average_area()
    test_insufficient_nominal_head_is_reported_without_faking_an_operating_point()
    print("Audit regression checks passed")
