"""Rotate two aggregate NYA jet vectors toward the centre of the first bay.

This is a numerical sensitivity on the saved coarse mesh, not a seven-port
Riverflow installation angle or a prediction calibrated to the manufacturer.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from core.orchestrator import LazyRiverModel  # noqa: E402

SOURCE = HERE / "qa_original_reference20_dt05"
DESTINATION = HERE / "qa_bay05_06_inward15_dt05"
PUMPS = (5, 6)
ANGLE_DEG = 15.0


def main() -> None:
    if DESTINATION.exists():
        raise FileExistsError(DESTINATION)
    metadata = json.loads((SOURCE / "metadata.json").read_text(encoding="utf-8"))
    if metadata["active_pumps"] != 20 or metadata["length_m"] != 536:
        raise ValueError("Expected the saved original 20-pump case")
    model = LazyRiverModel()
    if model.load_dxf(str(SOURCE / "source.dxf")):
        raise ValueError("Cannot load source DXF")
    model.build_centerline(target_length_m=536)
    origin = np.asarray(model.loader.outer_polygon.centroid.coords[0])
    scale = model.geometry.scale_m_per_unit
    stations = model.stations[:-1]
    chainage = np.asarray([s["chainage_m"] for s in stations])
    axis = (np.asarray([[s["x"], s["y"]] for s in stations]) - origin) * scale

    for folder in ("0", "constant", "system"):
        shutil.copytree(SOURCE / folder, DESTINATION / folder)
    shutil.copyfile(SOURCE / "source.dxf", DESTINATION / "source.dxf")
    velocity_file = DESTINATION / "0" / "U"
    content = velocity_file.read_text(encoding="ascii")
    details = {}
    for pump_id in PUMPS:
        station = metadata["stations"][pump_id - 1]
        middle = axis[int(np.argmin(abs(chainage - station["chainage_m"])))]
        jet = np.asarray(station["zones"]["jet"]["cell_xy_m"])
        tangent = np.asarray(station["jet_tangent_xy"], dtype=float)
        tangent /= np.linalg.norm(tangent)
        inward = middle - jet
        inward -= np.dot(inward, tangent) * tangent
        if np.linalg.norm(inward) < .5:
            raise ValueError(f"Unclear centre-facing direction for RF-{pump_id}")
        inward /= np.linalg.norm(inward)
        zone = f"p{pump_id:02d}jet"
        pattern = (rf"({zone}\s*\{{\s*type uniformFixedValue;\s*uniformValue \()"
                   rf"([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)"
                   rf"(\);\s*\}})")
        match = re.search(pattern, content)
        if match is None:
            raise ValueError(f"Missing {zone} velocity")
        original = np.asarray([float(match.group(i)) for i in (2, 3, 4)])
        speed = float(np.linalg.norm(original))
        if np.dot(original[:2] / speed, tangent) < .999:
            raise ValueError(f"Original {zone} is not aligned with local tangent")
        angle = math.radians(ANGLE_DEG)
        new = speed * (math.cos(angle) * tangent + math.sin(angle) * inward)
        replacement = f"{match.group(1)}{new[0]:.12g} {new[1]:.12g} 0{match.group(5)}"
        content = content[:match.start()] + replacement + content[match.end():]
        details[str(pump_id)] = {
            "chainage_m": station["chainage_m"],
            "bank": station["bank"],
            "jet_cell_xy_m": jet.tolist(),
            "centreline_xy_m": middle.tolist(),
            "original_velocity_xy_m_s": original[:2].tolist(),
            "rotated_velocity_xy_m_s": new.tolist(),
            "inward_angle_deg": ANGLE_DEG,
            "unchanged_exit_speed_m_s": speed,
        }
    velocity_file.write_text(content, encoding="ascii")
    if (SOURCE / "constant" / "fvModels").read_bytes() != (DESTINATION / "constant" / "fvModels").read_bytes():
        raise ValueError("Pump flow sources changed unexpectedly")
    metadata.update({
        "status": "prepared aggregate-jet orientation hypothesis, not physical port geometry",
        "qa_source_case": SOURCE.name,
        "qa_change": "rotate only RF-5 and RF-6 aggregate jet velocity 15 degrees inward",
        "orientation_trial": details,
        "source_dxf_sha256": hashlib.sha256((DESTINATION / "source.dxf").read_bytes()).hexdigest(),
        "physical_seconds_requested": 1200,
    })
    (DESTINATION / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(details, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
