"""Guard fixed CFD evidence against accidental use with another DXF."""

from pathlib import Path
from hashlib import sha256

from core.riverflow_decision_gate import comparison_rows, load_fixed_comparison


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
