"""Compare first-bay left/right flow on identical full-loop CFD meshes."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
from scipy.spatial import ConvexHull, cKDTree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE.parent / "openfoam_nya_pilot"))
from core.orchestrator import LazyRiverModel  # noqa: E402
from compare_narrow_flow_sensitivity import final_vtk, region_metrics  # noqa: E402
from visualize_result import read_vtk  # noqa: E402

CASES = ("qa_original_reference20_dt05", "qa_bay05_06_inward15_dt05")


def main() -> None:
    model = LazyRiverModel()
    if model.load_dxf(str(HERE / CASES[0] / "source.dxf")):
        raise ValueError("Cannot load original DXF")
    model.build_centerline(target_length_m=536)
    stations = model.stations[:-1]
    origin = np.asarray(model.loader.outer_polygon.centroid.coords[0])
    scale = model.geometry.scale_m_per_unit
    axis = (np.asarray([[s["x"], s["y"]] for s in stations]) - origin) * scale
    tangent = np.asarray([[s["tangent_x"], s["tangent_y"]] for s in stations])
    chainage = np.asarray([s["chainage_m"] for s in stations])
    metadata = [json.loads((HERE / name / "metadata.json").read_text()) for name in CASES]
    if metadata[0]["source_dxf_sha256"] != metadata[1]["source_dxf_sha256"]:
        raise ValueError("Different source DXFs")
    jet_xy = np.asarray([station["zones"]["jet"]["cell_xy_m"]
                         for meta in metadata for station in meta["stations"]])
    out = {}
    reference_centres = reference_volumes = None
    for name in CASES:
        case = HERE / name
        if "Mesh OK." not in (case / "checkMesh.log").read_text():
            raise ValueError(f"Mesh not validated: {name}")
        centres, fields, points, cells = read_vtk(final_vtk(case))
        volumes = np.asarray([ConvexHull(points[cell]).volume for cell in cells])
        if reference_centres is None:
            reference_centres, reference_volumes = centres, volumes
        elif (not np.allclose(centres, reference_centres, atol=1e-5) or
              not np.allclose(volumes, reference_volumes, atol=1e-7, rtol=1e-7)):
            raise ValueError("Mesh differs between cases")
        nearest = cKDTree(axis).query(centres[:, :2])[1]
        along = np.einsum("ij,ij->i", fields["U"][:, :2], tangent[nearest])
        relative = centres[:, :2] - axis[nearest]
        signed_side = tangent[nearest, 0] * relative[:, 1] - tangent[nearest, 1] * relative[:, 0]
        away = cKDTree(jet_xy).query(centres[:, :2])[0] >= 6
        bay = away & (chainage[nearest] >= 135) & (chainage[nearest] < 178)
        masks = {"whole_bay": bay, "left_half": bay & (signed_side >= 0),
                 "right_half": bay & (signed_side < 0)}
        out[name] = {key: region_metrics(along, volumes, mask)
                     for key, mask in masks.items()}
    result = {
        "status": "coarse-mesh orientation sensitivity, not a seven-port design recommendation",
        "bay_chainage_m": [135, 178],
        "same_mesh_cells": len(reference_centres),
        "mask_rule": "exclude 6 m around union of jets; split by centreline tangent",
        "cases": out,
    }
    (HERE / "bay05_06_orientation_comparison.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, regions in out.items():
        print(name, [(key, round(data["median_m_s"], 3),
                       round(100 * data["volume_fraction_below_0_15"], 1))
                      for key, data in regions.items()])


if __name__ == "__main__":
    main()
