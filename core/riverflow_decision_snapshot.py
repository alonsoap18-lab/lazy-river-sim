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
            or len(snapshot.get("reference20_layout", [])) != 20
            or any("separated_volume_regions" not in case for case in snapshot["cases"])):
        raise ValueError("Resumen CFD del DXF original incompleto")
    return snapshot


def original_snapshot_rows(snapshot: dict) -> list[dict]:
    rows = []
    for case in snapshot["cases"]:
        regions = case["separated_volume_regions"]
        rows.append({
            "Escenario guardado": case["label"],
            "Vuelta hidráulica extrapolada (min)": round(case["projected_lap_min"], 1),
            "Volumen lento en bahías de paso (%)": round(
                100 * regions["wide_passage_away"]["volume_fraction_below_0_15"], 1),
            "P95 en pasos <10 m (m/s)": round(
                regions["narrow_passage_away"]["p95_m_s"], 3),
            "Mediana en playa (m/s)": round(
                regions["main_beach_away"]["median_m_s"], 3),
            "Volumen en retorno fuera de playa (%)": round(
                100 * regions["all_passage_away"][
                    "volume_fraction_reverse_below_minus_0_02"], 1),
        })
    return rows


def reference_layout_matches(snapshot: dict, chainages_m, banks) -> bool:
    saved = snapshot["reference20_layout"]
    length = snapshot["length_m"]
    return (len(chainages_m) == len(saved) == len(banks) and all(
        min((position - item["chainage_m"]) % length,
            (item["chainage_m"] - position) % length) <= 1.0
        and bank == item["bank"]
        for position, bank, item in zip(chainages_m, banks, saved)
    ))
