"""Decision summary for completed, fixed NYA CFD trials.

The comparison is bound to exact DXF bytes and never recalculates OpenFOAM
when Streamlit controls change. Its tests concern progress through the trial,
not passenger safety or equipment certification.
"""

from __future__ import annotations

import json
from pathlib import Path


COMPARISON_FILE = (Path(__file__).resolve().parents[1] / "assets" / "cfd_uploaded" /
                   "47154b381560" / "decision_comparison.json")


def load_fixed_comparison(dxf_sha256: str) -> dict | None:
    if not COMPARISON_FILE.is_file():
        return None
    comparison = json.loads(COMPARISON_FILE.read_text(encoding="utf-8"))
    if comparison.get("schema") != 1 or comparison.get("source_dxf_sha256") != dxf_sha256:
        return None
    if (comparison.get("active_pumps") != 20 or comparison.get("mesh_cells") != 5352 or
            len(comparison.get("cases", [])) != 3):
        raise ValueError("Comparación CFD guardada incompleta.")
    return comparison


def trial_status(case: dict) -> str:
    """Describe the trial only; zero negative section medians is a necessary gate."""
    if case["returning_10m_bins"]:
        return "No pasa continuidad · tramos en retorno"
    if case["median_forward_m_s"] <= 0:
        return "No pasa continuidad · avance mediano no positivo"
    return "Sin tramos en retorno · falta validación"


def comparison_rows(comparison: dict) -> list[dict]:
    return [{
        "Distribución ensayada": case["label"],
        "Avance mediano (m/s)": round(case["median_forward_m_s"], 3),
        "Celdas en retorno (%)": round(100 * case["reverse_cell_fraction"], 1),
        "Celdas <0,15 m/s (%)": round(100 * case["slow_cell_fraction"], 1),
        "Tramos de 10 m en retorno": len(case["returning_10m_bins"]),
        "Estado del ensayo": trial_status(case),
    } for case in comparison["cases"]]
