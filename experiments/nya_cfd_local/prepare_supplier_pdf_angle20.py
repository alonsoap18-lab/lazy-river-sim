"""Sensitivity case: aim inferred PDF-bank returns 20 degrees toward channel centre."""

from __future__ import annotations

import json
from math import cos, pi, sin
from pathlib import Path
import re
import shutil


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "qa_supplier20_pdf_banks_ampliado_vfd70_dt05"
DESTINATION = HERE / "qa_supplier20_pdf_banks_angle20_ampliado_vfd70_dt05"
ANGLE = 20.0*pi/180.0


def main() -> None:
    if DESTINATION.exists():
        raise FileExistsError(DESTINATION)
    DESTINATION.mkdir()
    for folder in ("0", "constant", "system"):
        shutil.copytree(SOURCE / folder, DESTINATION / folder)
    shutil.copyfile(SOURCE / "source.dxf", DESTINATION / "source.dxf")
    meta = json.loads((SOURCE / "metadata.json").read_text(encoding="utf-8"))
    text = (DESTINATION / "0/U").read_text(encoding="ascii")
    speed = float(meta["aggregate_exit_speed_m_s"])
    for station in meta["stations"]:
        tx, ty = station["jet_tangent_xy"]
        nx, ny = ty, -tx  # right normal; model calls this Exterior
        toward_center = -1 if station["bank"] == "Exterior" else 1
        ux = speed*(cos(ANGLE)*tx + toward_center*sin(ANGLE)*nx)
        uy = speed*(cos(ANGLE)*ty + toward_center*sin(ANGLE)*ny)
        jet = station["zone_names"]["jet"]
        pattern = (rf"(?m)^ {re.escape(jet)} \{{ type uniformFixedValue;"
                   rf" uniformValue \([^\n]*\); \}}$")
        value = f" {jet} {{ type uniformFixedValue; uniformValue ({ux:.10g} {uy:.10g} 0); }}"
        text, count = re.subn(pattern, value, text, count=1)
        if count != 1:
            raise ValueError(f"Missing jet vector {jet}")
        station["jet_direction_xy"] = [ux/speed, uy/speed]
    (DESTINATION / "0/U").write_text(text, encoding="ascii")
    meta["status"] = "prepared; inferred Riverflow banks; hypothetical 20-degree inward jet angle"
    meta["qa_change"] = "same source zones and flow as PDF bank case; each jet 20 degrees toward channel centre"
    meta["assumed_cross_channel_jet_angle_deg"] = 20
    meta["jet_angles_measured_from_pdf"] = False
    (DESTINATION / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if (SOURCE / "constant/fvModels").read_bytes() != (DESTINATION / "constant/fvModels").read_bytes():
        raise ValueError("Pump flow rates changed unexpectedly")
    print(DESTINATION)


if __name__ == "__main__":
    main()
