"""Package saved OpenFOAM U/k/epsilon fields into compact Streamlit assets.

Run on the local WSL host that still has the completed scratch cases. Nothing
in this script runs CFD or changes the DXF. Source paths document the exact
four case directories used to create the bundles.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "assets" / "cfd_nya_1200"
TIMES = tuple(range(0, 1201, 120))
SOURCE = {
    16: (Path("/var/tmp/nya-manning-ablation.V1DJXq"),
         Path("/var/tmp/nya-manning16-extended"),
         ROOT / "experiments/nya_cfd_local/manning_ablation_16_width_4m_600s_xy/metadata.json"),
    19: (Path("/var/tmp/nya-manning-incremental.9EyjBq"),
         Path("/var/tmp/nya-manning19-extended"),
         ROOT / "experiments/nya_cfd_local/manning_incremental_19_removed_600s_xy/metadata.json"),
    20: (Path("/var/tmp/nya-manning-ablation.Rtz5Xz"),
         Path("/var/tmp/nya-manning20-extended"),
         ROOT / "experiments/nya_cfd_local/manning_ablation_20_width_4m_600s_xy/metadata.json"),
    21: (Path("/var/tmp/nya-manning-incremental.hD4wzL"),
         Path("/var/tmp/nya-manning21-extended"),
         ROOT / "experiments/nya_cfd_local/manning_downstream_21_added_600s_xy/metadata.json"),
}
CELL_COUNT = 4056


def internal_field(path: Path, components: int) -> np.ndarray:
    text = path.read_text(encoding="ascii", errors="replace")
    if components == 3:
        uniform = re.search(r"internalField\s+uniform\s+\(([^)]+)\)\s*;", text)
        kind = "vector"
    else:
        uniform = re.search(r"internalField\s+uniform\s+([^;]+)\s*;", text)
        kind = "scalar"
    if uniform:
        value = np.fromstring(uniform.group(1), sep=" ", dtype=np.float64)
        if len(value) != components:
            raise ValueError(f"Invalid uniform {kind} in {path}")
        return np.broadcast_to(value, (CELL_COUNT, components)).copy()
    match = re.search(
        rf"internalField\s+nonuniform\s+List<{kind}>\s+(\d+)\s*\(\s*",
        text)
    if match is None or int(match.group(1)) != CELL_COUNT:
        raise ValueError(f"Missing or wrong internal field in {path}")
    values = np.empty((CELL_COUNT, components), dtype=np.float64)
    for i, line in enumerate(text[match.end():].splitlines()[:CELL_COUNT]):
        row = np.fromstring(line.strip("() \t"), sep=" ", dtype=np.float64)
        if len(row) != components:
            raise ValueError(f"Invalid {kind} cell {i} in {path}")
        values[i] = row
    if not np.all(np.isfinite(values)):
        raise ValueError(f"Nonfinite internal field in {path}")
    return values


def nearest_time_folder(case: Path, target: int) -> tuple[float, Path]:
    found = [(float(path.name), path) for path in case.iterdir()
             if path.is_dir() and (path / "U").exists()
             and re.fullmatch(r"\d+(?:\.\d+)?", path.name)]
    if not found:
        raise ValueError(f"No saved times: {case}")
    actual, folder = min(found, key=lambda item: abs(item[0] - target))
    if abs(actual - target) > 1.0:
        raise ValueError(f"Missing t≈{target} s in {case}; nearest={actual}")
    return actual, folder


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    dxf_sha = hashlib.sha256((ROOT / "RECORRIDO.dxf").read_bytes()).hexdigest()
    manifest = {
        "schema": 1,
        "source": "NYA local OpenFOAM 14 RANS k-epsilon; Manning equivalent drag",
        "source_dxf_sha256": dxf_sha,
        "length_m": 536.0,
        "mesh_cells": CELL_COUNT,
        "frame_targets_s": list(TIMES),
        "reference_flow_us_gpm_per_cf104": 2014.0,
        "floor_manning_n": 0.013,
        "wall_manning_n": 0.025,
        "limitations": [
            "fixed lid; no free surface",
            "aggregate seven-port discharge; individual ports unresolved",
            "pump flow is a reference input, not verified NYA duty",
            "coarse mesh and uncalibrated turbulence",
            "saved results do not update when app inputs change",
        ],
        "scenarios": {},
    }
    for count, (first_case, extended_case, metadata_file) in SOURCE.items():
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        if (metadata["active_pumps"] != count or
                metadata["mesh_cells"] != CELL_COUNT or
                metadata["reference_flow_gpm_per_pump"] != 2014):
            raise ValueError(f"Unexpected source conditions: {count}")
        fields = []
        actual_times = []
        for target in TIMES:
            case = first_case if target <= 600 else extended_case
            actual, folder = nearest_time_folder(case, target)
            fields.append(internal_field(folder / "U", 3).astype(np.float32))
            actual_times.append(actual)
        final_time, final_folder = nearest_time_folder(extended_case, 1200)
        k = internal_field(final_folder / "k", 1).ravel().astype(np.float32)
        epsilon = internal_field(final_folder / "epsilon", 1).ravel().astype(np.float32)
        if not np.all(np.diff(actual_times) > 0):
            raise ValueError(f"Non-monotonic selected frames: {count}")
        if np.any(k < 0) or np.any(epsilon <= 0):
            raise ValueError(f"Invalid turbulence fields: {count}")
        out_file = OUT / f"scenario_{count}.npz"
        np.savez_compressed(out_file, time_s=np.asarray(actual_times, dtype=np.float32),
                            u=np.stack(fields), k=k, epsilon=epsilon)
        manifest["scenarios"][str(count)] = {
            "bundle": out_file.name,
            "actual_frame_times_s": actual_times,
            "final_physical_time_s": final_time,
            "pumps": [{"number": item["station"],
                       "chainage_m": item["chainage_m"],
                       "bank": item["bank"],
                       "jet_xy_m": item["zones"]["jet"]["cell_xy_m"]}
                      for item in metadata["stations"]],
        }
        print(count, out_file.stat().st_size, "bytes")
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT / "manifest.json")


if __name__ == "__main__":
    main()
