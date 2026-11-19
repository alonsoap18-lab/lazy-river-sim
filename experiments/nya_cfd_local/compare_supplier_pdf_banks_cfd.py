"""Compare corrected Riverflow PDF line-start banks against the saved local CFD."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

import summarize_supplier20_approx as metrics


HERE = Path(__file__).resolve().parent
REFERENCE = "qa_supplier20_widepair_ampliado_vfd70_dt05"
PROPOSAL = "qa_supplier20_pdf_banks_ampliado_vfd70_dt05"
ANGLE20 = "qa_supplier20_pdf_banks_angle20_ampliado_vfd70_dt05"


def main() -> None:
    layout_path = HERE.parents[1] / "assets" / "cfd_supplier_photo" / "layout.json"
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    metadata = json.loads((HERE / PROPOSAL / "metadata.json").read_text(encoding="utf-8"))
    mapped = {item["supplier_plan_number"]: item for item in metadata["stations"]}
    if (metadata["source_dxf_sha256"] != layout["wide_sha"] or
            len(mapped) != 20 or any(
                mapped[item["supplier_number"]]["chainage_m"] != item["chainage_m_approx"] or
                mapped[item["supplier_number"]]["bank"] != item["bank"]
                for item in layout["positions"])):
        raise ValueError("The CFD pump locations do not match the published PDF mapping")
    for name in (PROPOSAL, ANGLE20):
        case = HERE / name
        run_name = Path((case / "linux_run_dir.txt").read_text(encoding="utf-8").strip()).name
        vtk = metrics.final_vtk(case)
        if not vtk.name.startswith(run_name + "_"):
            raise ValueError(f"Stale VTK field in {name}: {vtk.name}")
        if not json.loads((case / "metadata.json").read_text(encoding="utf-8")).get(
                "warm_start_jet_sources_replaced"):
            raise ValueError(f"Warm-start nozzle vectors not confirmed in {name}")
    if ((HERE / PROPOSAL / "0/U").read_bytes() == (HERE / ANGLE20 / "0/U").read_bytes()):
        raise ValueError("Jet-angle sensitivity has identical direction vectors")
    original_pairs = metrics.PAIRS.copy()
    try:
        metrics.PAIRS["riverflow_pdf_banks"] = (REFERENCE, PROPOSAL)
        metrics.PAIRS["riverflow_pdf_angle20"] = (REFERENCE, ANGLE20)
        compared = metrics.summarize_pair(REFERENCE, PROPOSAL)
        angled = metrics.summarize_pair(REFERENCE, ANGLE20)
        compared["cases"].update(angled["cases"])
    finally:
        metrics.PAIRS.clear()
        metrics.PAIRS.update(original_pairs)
    report = {
        "source": "Riverflow optional counterclockwise returns PDF and lazy river 28-10-26.dxf",
        "layout_sha256": hashlib.sha256(layout_path.read_bytes()).hexdigest(),
        "method": "same DXF, mesh, 20 CF104, assumed 70% VFD and 319.9 m3/h each",
        "pdf_interpretation": "numbered blue line begins at pump side; station along DXF approximate +/-20m",
        "jet_assumption": "two sensitivity cases: tangential and 20-degree inward; blue-line angle and seven individual port vectors not resolved",
        "restart": "proposal starts from local 1200s field, continues 600s to 1800s",
        "not_rider_time": True,
        "result": compared,
    }
    out = HERE / "supplier_pdf_banks_vs_current_cfd.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, case in compared["cases"].items():
        print(name, "lap", case["projected_stationary_hydraulic_lap_min"],
              "return%", round(100*case["reverse_volume_fraction"], 2),
              "wide_slow%", round(100*case["regions"]["wide_passage"]["volume_fraction_below_0_15"], 2),
              "narrow_p95", round(case["regions"]["narrow_passage"]["p95_m_s"], 3))
    print(out)


if __name__ == "__main__":
    main()
