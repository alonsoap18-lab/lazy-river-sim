"""Guard fixed CFD evidence against accidental use with another DXF."""

from pathlib import Path
from hashlib import sha256

from core.riverflow_decision_gate import (COMPARISON_FILE, comparison_rows,
                                          load_fixed_comparison, matching_layout_cases)


def test_archived_comparison_is_bound_to_exact_dxf_and_fails_continuity():
    source = Path("C:/Users/ingal/Downloads/lazy river 28-10-26.dxf")
    if not source.is_file():
        # The app bundle has the hash even when the user's Downloads is absent.
        from json import loads
        from core.riverflow_decision_gate import COMPARISON_FILE
        fingerprint = loads(COMPARISON_FILE.read_text(encoding="utf-8"))["source_dxf_sha256"]
    else:
        fingerprint = sha256(source.read_bytes()).hexdigest()
    comparison = load_fixed_comparison(fingerprint)
    assert comparison is not None
    assert load_fixed_comparison("0" * 64) is None
    rows = comparison_rows(comparison)
    assert len(rows) == 3
    assert all(row["Tramos de 10 m en retorno"] > 0 for row in rows)
    assert all(row["Estado del ensayo"].startswith("No pasa") for row in rows)
    assert rows[2]["Celdas en retorno (%)"] < rows[0]["Celdas en retorno (%)"]


def test_archived_layout_match_checks_positions_and_banks():
    from json import loads

    comparison = loads(COMPARISON_FILE.read_text(encoding="utf-8"))
    reference = loads((COMPARISON_FILE.parent / "reference20" / "metadata.json")
                      .read_text(encoding="utf-8"))["stations"]
    positions = tuple(station["chainage_m"] for station in reference)
    banks = tuple(station["bank"] for station in reference)
    assert "reference20" in matching_layout_cases(comparison, positions, banks)
    moved = list(positions)
    moved[5] = 138.0
    assert "move6" in matching_layout_cases(comparison, moved, banks)
    automatic = loads((COMPARISON_FILE.parent / "automatic" / "metadata.json")
                      .read_text(encoding="utf-8"))["stations"]
    assert "automatic" in matching_layout_cases(
        comparison,
        tuple(station["chainage_m"] for station in automatic),
        tuple(station["bank"] for station in automatic))
    changed_banks = list(banks)
    changed_banks[0] = "Interior" if banks[0] == "Exterior" else "Exterior"
    assert matching_layout_cases(comparison, positions, changed_banks) == []
