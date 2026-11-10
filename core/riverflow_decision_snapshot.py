"""Compact, provenance-bound summary of the saved original-NYA CFD trials."""

from __future__ import annotations

import json
from pathlib import Path


SNAPSHOT_FILE = Path(__file__).resolve().parents[1] / "assets" / "decision_original_cfd.json"


def load_original_snapshot(dxf_sha256: str) -> dict | None:
    if not SNAPSHOT_FILE.is_file():
        return None
    snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    if snapshot.get("schema") != 1 or snapshot.get("source_dxf_sha256") != dxf_sha256:
        return None
    if (snapshot.get("mesh_cells") != 4056 or snapshot.get("physical_time_s") != 1200
            or len(snapshot.get("cases", [])) != 4
            or len(snapshot.get("reference20_layout", [])) != 20):
        raise ValueError("Resumen CFD del DXF original incompleto")
    return snapshot


def original_snapshot_rows(snapshot: dict) -> list[dict]:
    return [{
        "Escenario guardado": case["label"],
        "Vuelta hidráulica extrapolada (min)": round(case["projected_lap_min"], 1),
        "Celdas anchas lentas, incluye playa (%)": round(
            100 * case["wide_including_beach_slow_cell_fraction"], 1),
        "Mediana en pasos <10 m (m/s)": round(case["narrow_median_m_s"], 3),
        "Mediana en playa (m/s)": round(case["beach_median_m_s"], 3),
        "Celdas en retorno (%)": round(100 * case["reverse_cell_fraction"], 1),
    } for case in snapshot["cases"]]


def reference_layout_matches(snapshot: dict, chainages_m, banks) -> bool:
    saved = snapshot["reference20_layout"]
    length = snapshot["length_m"]
    return (len(chainages_m) == len(saved) == len(banks) and all(
        min((position - item["chainage_m"]) % length,
            (item["chainage_m"] - position) % length) <= 1.0
        and bank == item["bank"]
        for position, bank, item in zip(chainages_m, banks, saved)
    ))
