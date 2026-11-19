"""Prepare the widened-DXF CFD case with banks read from Riverflow blue lines."""

from __future__ import annotations

import json
from pathlib import Path

import prepare_supplier20_approx_cases as preparer


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PHOTO = ROOT / "assets" / "cfd_supplier_photo" / "layout.json"
SOURCE = HERE / "qa_supplier20_widepair_ampliado_vfd70_dt05"
DESTINATION = HERE / "qa_supplier20_pdf_banks_ampliado_vfd70_dt05"


def main() -> None:
    data = json.loads(PHOTO.read_text(encoding="utf-8"))
    source = json.loads((SOURCE / "metadata.json").read_text(encoding="utf-8"))
    if source["source_dxf_sha256"] != data["wide_sha"]:
        raise ValueError("El DXF del CFD y el PDF interpretado no coinciden")
    layout = tuple((item["supplier_number"], item["chainage_m_approx"], item["bank"])
                   for item in data["positions"])
    preparer.SOURCES["ampliado"] = SOURCE
    output = preparer.prepare("ampliado", layout=layout, destination=DESTINATION)
    metadata_path = output / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["status"] = "prepared; Riverflow PDF line starts mapped to bank, angles tangential assumption"
    metadata["qa_change"] = "20 Riverflow PDF line-start sectors and inferred banks; 2 suctions and aggregate 7-port jet per station"
    metadata["banks_inferred_from_numbered_blue_line_starts"] = True
    metadata["jet_angles_measured_from_pdf"] = False
    metadata["supplier_photo_does_not_define_banks_or_angles"] = False
    metadata["uncertainty_note"] = "bank read from blue line start; chainage approx +/-20 m; jet angle tangential hypothesis"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
