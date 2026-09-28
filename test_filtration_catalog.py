"""Commercial-family screening must never turn a published max into a duty point."""

from core.filtration_catalog import PUMP_FAMILIES, screen_pump_families


def test_six_pump_scenario_excludes_small_family_only():
    candidates = screen_pump_families(6833 / 4, 6)
    assert len(candidates) == len(PUMP_FAMILIES) == 3
    assert "Descartada" in candidates[0]["screening"]
    assert all("Revisar curva" in item["screening"] for item in candidates[1:])


def test_more_pumps_change_screen_without_claiming_purchase_approval():
    candidates = screen_pump_families(6833 / 4, 12)
    assert "Revisar curva" in candidates[0]["screening"]
    assert all("aprobada" not in item["screening"].lower() for item in candidates)
