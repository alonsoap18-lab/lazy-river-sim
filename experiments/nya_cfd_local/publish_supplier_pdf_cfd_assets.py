"""Pack the completed, corrected Riverflow CFD comparison for the Streamlit sheet."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent
ASSETS = HERE.parents[1] / "assets" / "cfd_supplier_photo"
CASES = {
    "tangent": "qa_supplier20_pdf_banks_ampliado_vfd70_dt05",
    "angle20": "qa_supplier20_pdf_banks_angle20_ampliado_vfd70_dt05",
}


def main() -> None:
    report = HERE / "supplier_pdf_banks_vs_current_cfd.json"
    data = json.loads(report.read_text(encoding="utf-8"))
    for case_name in CASES.values():
        if case_name not in data["result"]["cases"]:
            raise ValueError(f"Missing comparison result: {case_name}")
    for label, case_name in CASES.items():
        case = HERE / case_name
        audit = json.loads((case / "stability_recheck_report.json").read_text(encoding="utf-8"))
        if audit["physical_seconds_completed"] < 1799.9:
            raise ValueError(f"Incomplete CFD: {case_name}")
        for view in ("2d", "3d"):
            source = case / f"nya_flujo_transitorio_{view}.html"
            target = ASSETS / f"flow_{label}_{view}.html.gz"
            with target.open("wb") as output:
                with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0,
                                   compresslevel=9) as zipped:
                    zipped.write(source.read_bytes())
            print(target.name, target.stat().st_size)
    shutil.copyfile(report, ASSETS / "cfd_comparison.json")
    print("cfd_comparison.json", (ASSETS / "cfd_comparison.json").stat().st_size)


if __name__ == "__main__":
    main()
