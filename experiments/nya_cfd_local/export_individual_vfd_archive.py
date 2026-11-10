"""Export a compact, checked VFD comparison for the Streamlit decision sheet."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

CASES = (
    ("qa_original_reference20_dt05", "20 × 100 %", (), 100, "individual"),
    ("qa_vfd_rf17_80_dt05", "RF-17 al 80 % · otras 19 al 100 %", (17,), 80, "individual"),
    ("qa_vfd_rf17_60_dt05", "RF-17 al 60 % · otras 19 al 100 %", (17,), 60, "individual"),
    ("qa_original_narrow3_q80_consistent_dt05",
     "RF-16/17/18 · caudal impuesto al 80 %", (16, 17, 18), None, "individual"),
    ("qa_vfd_rf2_3_4_80_dt05", "RF-2/3/4 al 80 % · otras 17 al 100 %",
     (2, 3, 4), 80, "rf234"),
)


def main() -> None:
    comparisons = {
        "individual": json.loads((HERE / "individual_vfd_comparison.json").read_text()),
        "rf234": json.loads((HERE / "vfd_rf234_comparison.json").read_text()),
    }
    reference = comparisons["individual"]
    candidate = comparisons["rf234"]
    for key in ("common_mesh_cells", "common_physical_time_s", "common_mask_rule"):
        if reference[key] != candidate[key]:
            raise ValueError(f"Incompatible VFD comparisons: {key}")
    original = json.loads((ROOT / "assets" / "decision_original_cfd.json").read_text())
    baseline = json.loads((HERE / CASES[0][0] / "metadata.json").read_text())
    source_flow = baseline["aggregate_seven_port_discharge_m3_s"] * 3600
    rows = []
    for name, label, affected, pct, comparison_key in CASES:
        report = json.loads((HERE / name / "stability_recheck_report.json").read_text())
        if (report["physical_seconds_completed"] < 1199 or
                report["max_courant_observed"] >= .2 or
                any(x["negative_10m_section_medians"] for x in report["last_three"])):
            raise ValueError(f"Case failed final numerical gates: {name}")
        end_medians = [x["median_longitudinal_cell_m_s"] for x in report["last_three"]]
        if max(end_medians) - min(end_medians) > .005:
            raise ValueError(f"Case not steady enough for screening: {name}")
        data = comparisons[comparison_key]["cases"][name]
        metadata = json.loads((HERE / name / "metadata.json").read_text())
        if metadata["source_dxf_sha256"] != baseline["source_dxf_sha256"]:
            raise ValueError(f"DXF differs for {name}")
        operations = metadata.get("vfd_operations", {})
        if name == CASES[0][0]:
            factor = 1.0
        elif operations:
            factors = [operations[str(pump)]["source_flow_fraction"] for pump in affected]
            if max(factors) - min(factors) > 1e-6:
                raise ValueError(f"Affected pumps have different duty points: {name}")
            factor = factors[0]
        else:
            factor = metadata["reduced_pump_flow_fraction"]
        rows.append({
            "id": name,
            "label": label,
            "affected_pumps": list(affected),
            "vfd_pct": pct,
            "adjusted_cfd_flow_per_pump_m3_h": source_flow * factor,
            "flow_basis": ("caudal documental al 100 %" if not affected else
                           "afinidad + circuito supuesto" if operations else
                           "80 % directo del caudal documental"),
            "projected_hydraulic_lap_min": data["projected_hydraulic_lap_min"],
            "wide_passage_slow_volume_fraction": data["regions"]["wide_passage_away"][
                "volume_fraction_below_0_15"],
            "narrow_passage_p95_m_s": data["regions"]["narrow_passage_away"]["p95_m_s"],
            "beach_median_m_s": data["regions"]["main_beach_away"]["median_m_s"],
            "reverse_volume_fraction": data["reverse_volume_fraction"],
            "max_courant_observed": report["max_courant_observed"],
        })
    archive = {
        "schema": 2,
        "source_dxf_sha256": original["source_dxf_sha256"],
        "source_comparisons": [
            "experiments/nya_cfd_local/individual_vfd_comparison.json",
            "experiments/nya_cfd_local/vfd_rf234_comparison.json",
        ],
        "mesh_cells": reference["common_mesh_cells"],
        "physical_time_s": reference["common_physical_time_s"],
        "mask_rule": reference["common_mask_rule"],
        "reference_flow_m3_h_per_pump": source_flow,
        "status": "uncalibrated VFD affinity + prescribed-flow CFD screening",
        "cases": rows,
    }
    (ROOT / "assets" / "decision_vfd_original.json").write_text(
        json.dumps(archive, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for row in rows:
        print(row["label"], round(row["projected_hydraulic_lap_min"], 2),
              round(100 * row["wide_passage_slow_volume_fraction"], 1))


if __name__ == "__main__":
    main()
