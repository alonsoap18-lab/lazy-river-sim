"""Publish the already computed, finer-time-step NYA DXF diagnostic runs.

This packages saved OpenFOAM outputs. It does not execute or change the solver.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "experiments" / "nya_cfd_local"
DIGEST = "47154b381560b10b58d2729f9e2ae79dc90ff1f24af8a7640d36a41b15f68060"
DEST = ROOT / "assets" / "cfd_uploaded" / DIGEST[:12]
CASES = {
    "reference20": ("qa_new_reference20_dt05",
                    "20 CF104 · posiciones de referencia · paso fino"),
    "automatic": ("qa_new_automatic20_dt05",
                  "20 CF104 · distribución automática · paso fino"),
}


def package() -> Path:
    evidence = {}
    for key, (name, label) in CASES.items():
        folder = SOURCE / name
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        report = json.loads((folder / "transient_report.json").read_text(encoding="utf-8"))
        audit = json.loads((folder / "stability_recheck_report.json").read_text(encoding="utf-8"))
        actual_digest = hashlib.sha256((folder / "source.dxf").read_bytes()).hexdigest()
        final = report["time_profile"][-1]
        audit_final = audit["time_profile"][-1]
        if not (actual_digest == metadata["source_dxf_sha256"] ==
                report["source_dxf_sha256"] == DIGEST):
            raise ValueError(f"DXF mismatch: {name}")
        if (metadata["mesh_cells"] != 5352 or metadata["active_pumps"] != 20 or
                report["mesh_cells"] != 5352 or
                not 1199 <= final["physical_time_s"] <= 1201 or
                report["max_courant_observed"] > .2):
            raise ValueError(f"Numerical diagnostic gate failed: {name}")
        if (abs(final["median_longitudinal_cell_m_s"] -
                audit_final["median_longitudinal_cell_m_s"]) > 1e-9 or
                abs(final["fraction_cell_reverse_below_minus_0_02"] -
                    audit_final["reverse_cell_fraction_below_minus_0_02"]) > 1e-9):
            raise ValueError(f"Independent audit differs: {name}")
        if ("Mesh OK." not in (folder / "checkMesh.log").read_text(encoding="utf-8") or
                "End\n" not in (folder / "foamRun.log").read_text(encoding="utf-8")):
            raise ValueError(f"Mesh or solver did not finish: {name}")
        # The preparation-stage metadata still says "unrun". The completed
        # solver log and independent audit above justify correcting the copy
        # published with the app; the raw experiment file remains untouched.
        metadata["status"] = "completed time-step QA; diagnostic only, not validated design"
        for view in ("2d", "3d"):
            if not (folder / f"nya_flujo_transitorio_{view}.html").is_file():
                raise FileNotFoundError(f"Missing {view} visualization for {name}")
        evidence[key] = (folder, metadata, report, audit, label)

    DEST.mkdir(parents=True, exist_ok=True)
    for key, (folder, metadata, report, audit, _) in evidence.items():
        target = DEST / key
        target.mkdir(exist_ok=True)
        for view in ("2d", "3d"):
            with (folder / f"nya_flujo_transitorio_{view}.html").open("rb") as source:
                with gzip.open(target / f"flow_{view}.html.gz", "wb", compresslevel=9) as output:
                    shutil.copyfileobj(source, output)
        for filename, payload in (("metadata.json", metadata),
                                  ("transient_report.json", report),
                                  ("stability_recheck_report.json", audit)):
            (target / filename).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    extension = json.loads((SOURCE / "time_extension_comparison.json").read_text(
        encoding="utf-8"))["cases"]["qa_new_reference20_dt05"]
    if abs(extension["at_1200_s"]["median_longitudinal_cell_m_s"] -
           evidence["reference20"][2]["time_profile"][-1][
               "median_longitudinal_cell_m_s"]) > 1e-9:
        raise ValueError("The extended reference is not the packaged 1200 s run")
    manifest = {
        "schema": 2,
        "source_dxf_sha256": DIGEST,
        "run_family": "qa_dt05_stability_recheck",
        "status": "diagnostic_only_not_purchase_or_lap",
        "display_range_m_s": [-0.6, 0.6],
        "reference_extension_1800_s": extension["at_1800_s"],
        "scenarios": {key: item[4] for key, item in evidence.items()},
        "quality_gate": {
            "mesh_check": True,
            "solver_completed": True,
            "courant_under_0_2": True,
            "independent_audit_matched": True,
            "full_loop_momentum_calibrated": False,
            "mesh_convergence": False,
            "seven_ports_individual": False,
            "rough_wall_boundary_calibrated": False,
            "free_surface_resolved": False,
            "physical_validation": False,
        },
    }
    (DEST / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return DEST


if __name__ == "__main__":
    print(package())
