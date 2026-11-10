"""Read exact, saved per-pump VFD CFD sensitivities for the original NYA DXF."""

from __future__ import annotations

import json
from pathlib import Path


ARCHIVE_FILE = Path(__file__).resolve().parents[1] / "assets" / "decision_vfd_original.json"


def load_vfd_archive(dxf_sha256: str) -> dict | None:
    if not ARCHIVE_FILE.is_file():
        return None
    archive = json.loads(ARCHIVE_FILE.read_text(encoding="utf-8"))
    if archive.get("schema") != 2 or archive.get("source_dxf_sha256") != dxf_sha256:
        return None
    if (archive.get("mesh_cells") != 4056 or archive.get("physical_time_s") != 1200
            or len(archive.get("cases", [])) != 5
            or len({case.get("id") for case in archive["cases"]}) != 5):
        raise ValueError("Archivo VFD del DXF original incompleto")
    return archive


def vfd_archive_rows(archive: dict) -> list[dict]:
    return [{
        "Configuración guardada": case["label"],
        "Ajuste": (f"VFD {case['vfd_pct']} %" if case["vfd_pct"] is not None
                   else "Q impuesto al 80 %"),
        "Q impuesto por bomba ajustada (m³/h)": round(
            case["adjusted_cfd_flow_per_pump_m3_h"], 1),
        "Vuelta hidráulica (min)": (
            round(case["projected_hydraulic_lap_min"], 2)
            if case["projected_hydraulic_lap_min"] is not None else None),
        "Volumen lento en bahías (%)": round(
            100 * case["wide_passage_slow_volume_fraction"], 1),
        "P95 pasos angostos (m/s)": round(case["narrow_passage_p95_m_s"], 3),
        "Volumen en retorno (%)": round(100 * case["reverse_volume_fraction"], 1),
    } for case in archive["cases"]]
