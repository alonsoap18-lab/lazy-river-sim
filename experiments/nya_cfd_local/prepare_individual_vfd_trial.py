"""Prepare a per-CF104 VFD sensitivity from the saved original-NYA case.

The reduced-speed H-Q curve follows affinity laws and the editable local
circuit is assumed, not measured. This prepares a CFD scenario, not a VFD
setpoint recommendation or an installed Riverflow duty-point prediction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from core.riverflow_jet_momentum import NOZZLE_12X7_OPEN_AREA_M2, nozzle_outlet_k  # noqa: E402
from core.riverflow_local_circuit import LocalCircuit, solve_local_circuit  # noqa: E402

SOURCE = HERE / "qa_original_reference20_dt05"


def _circuit() -> LocalCircuit:
    diameter = .303
    return LocalCircuit(
        suction_length_m=8, suction_diameter_m=diameter,
        discharge_length_m=8, discharge_diameter_m=diameter,
        suction_k=1, discharge_k=1,
        outlet_k=nozzle_outlet_k(diameter, NOZZLE_12X7_OPEN_AREA_M2, .85),
        static_head_m=0,
    )


def prepare(case_name: str, vfd_by_pump: dict[int, float]) -> Path:
    if not re.fullmatch(r"qa_[a-zA-Z0-9_-]+", case_name):
        raise ValueError("Case name must begin qa_ and contain only letters/digits/_/-")
    if not vfd_by_pump or any(not 1 <= pump <= 20 or not .5 <= speed <= 1
                               for pump, speed in vfd_by_pump.items()):
        raise ValueError("Specify pumps 1–20 and VFD fractions between .5 and 1")
    destination = HERE / case_name
    if destination.exists():
        raise FileExistsError(destination)
    metadata = json.loads((SOURCE / "metadata.json").read_text(encoding="utf-8"))
    if metadata["active_pumps"] != 20 or metadata["length_m"] != 536:
        raise ValueError("Expected the original 20-pump NYA case")
    circuit = _circuit()
    reference = solve_local_circuit(circuit)
    operations = {}
    for pump_id, speed in sorted(vfd_by_pump.items()):
        point = solve_local_circuit(circuit, speed_fraction=speed)
        operations[pump_id] = {
            "vfd_fraction": speed,
            "flow_m3_h": point.flow_m3_h,
            "head_ft": point.system_head_ft,
            "source_flow_fraction": point.flow_m3_h / reference.flow_m3_h,
        }
    for folder in ("0", "constant", "system"):
        shutil.copytree(SOURCE / folder, destination / folder)
    shutil.copyfile(SOURCE / "source.dxf", destination / "source.dxf")

    models = destination / "constant" / "fvModels"
    content = models.read_text(encoding="ascii")
    velocity_file = destination / "0" / "U"
    velocity_content = velocity_file.read_text(encoding="ascii")
    for pump_id, op in operations.items():
        fraction = op["source_flow_fraction"]
        for suffix in ("sA", "sB", "jet"):
            zone = f"p{pump_id:02d}{suffix}"
            pattern = rf"({zone}\s*\{{[^{{}}]*?volumetricFlowRate\s+)(-?\d+(?:\.\d+)?)(;)"
            content, count = re.subn(
                pattern,
                lambda m: f"{m.group(1)}{float(m.group(2))*fraction:.12g}{m.group(3)}",
                content, flags=re.DOTALL)
            if count != 1:
                raise ValueError(f"Expected one source for {zone}; found {count}")
        zone = f"p{pump_id:02d}jet"
        pattern = rf"({zone}\s*\{{\s*type uniformFixedValue;\s*uniformValue \()([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)(\);\s*\}})"
        velocity_content, count = re.subn(
            pattern,
            lambda m: (f"{m.group(1)}{float(m.group(2))*fraction:.12g} "
                       f"{float(m.group(3))*fraction:.12g} "
                       f"{float(m.group(4))*fraction:.12g}{m.group(5)}"),
            velocity_content)
        if count != 1:
            raise ValueError(f"Expected one outlet vector for {zone}; found {count}")
    rates = [float(x) for x in re.findall(
        r"volumetricFlowRate\s+(-?\d+(?:\.\d+)?);", content)]
    if len(rates) != 60 or abs(sum(rates)) > 1e-8:
        raise ValueError("Source count or global mass balance failed")
    models.write_text(content, encoding="ascii")
    velocity_file.write_text(velocity_content, encoding="ascii")
    metadata.update({
        "status": "prepared per-pump VFD hypothesis; no measured reduced-speed curves",
        "qa_source_case": SOURCE.name,
        "qa_change": "per-pump H-Q/system intersection and matching aggregate seven-port exit velocity",
        "vfd_operations": {str(k): v for k, v in operations.items()},
        "vfd_reference_circuit": {
            "suction_m": 8, "discharge_m": 8, "pipe_id_m": .303,
            "suction_k": 1, "discharge_k": 1, "outlet_cd_assumed": .85,
            "static_head_m": 0, "curve_mode": "photo",
            "full_speed_flow_m3_h": reference.flow_m3_h,
        },
        "source_dxf_sha256": hashlib.sha256((destination / "source.dxf").read_bytes()).hexdigest(),
        "net_source_flow_m3_s": sum(rates),
        "physical_seconds_requested": 1200,
    })
    (destination / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_name")
    parser.add_argument("settings", nargs="+", help="PUMP=VFD_PERCENT, e.g. 17=80")
    args = parser.parse_args()
    settings = {}
    for setting in args.settings:
        pump, pct = setting.split("=", 1)
        settings[int(pump)] = float(pct) / 100
    print(prepare(args.case_name, settings))
