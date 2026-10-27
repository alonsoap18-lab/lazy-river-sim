"""Package the fixed NYA CFD mesh and DXF outline used by all saved scenarios."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import numpy as np
from scipy.spatial import ConvexHull, cKDTree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "assets" / "cfd_nya_1200"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE.parent / "openfoam_nya_pilot"))

from core.orchestrator import LazyRiverModel  # noqa: E402
from visualize_result import read_vtk  # noqa: E402


def main() -> None:
    source = HERE / "manning_ablation_20_width_4m_600s_xy" / "VTK"
    frame = next(source.glob("*_3007.vtk"))
    centres, _, cell_points, connectivity = read_vtk(frame)
    if len(centres) != 4056 or connectivity.shape[1] != 6:
        raise ValueError("Unexpected CFD cell mesh")
    if np.max(np.ptp(centres.reshape(-1, 4, 3)[:, :, :2], axis=1)) > .02:
        raise ValueError("Four vertical layers do not share the expected XY location")
    model = LazyRiverModel()
    if model.load_dxf(str(ROOT / "RECORRIDO.dxf")):
        raise ValueError("NYA DXF unavailable")
    model.build_centerline(target_length_m=536)
    origin = np.asarray(model.loader.outer_polygon.centroid.coords[0])
    scale = model.geometry.scale_m_per_unit
    stations = model.stations[:-1]
    axis = (np.asarray([[s["x"], s["y"]] for s in stations])-origin)*scale
    nearest = cKDTree(axis).query(centres[:, :2])[1]
    data = {
        "centres_xyz_m": centres.astype(np.float32),
        "cell_chainage_m": np.asarray([stations[i]["chainage_m"] for i in nearest], dtype=np.float32),
        "cell_tangent_xy": np.asarray([[stations[i]["tangent_x"], stations[i]["tangent_y"]]
                                       for i in nearest], dtype=np.float32),
        "cell_volume_m3": np.asarray([ConvexHull(cell_points[cell]).volume
                                       for cell in connectivity], dtype=np.float32),
    }
    for key, ring in (("outer_xy_m", model.loader.outer_polygon.exterior.coords),
                      ("inner_xy_m", model.loader.inner_polygon.exterior.coords)):
        data[key] = ((np.asarray(ring)-origin)*scale).astype(np.float32)
    for name in ("floor", "innerWall", "outerWall", "lid"):
        path = next((source / name).glob(f"{name}_0.vtk"))
        _, _, points, faces = read_vtk(path)
        if faces.shape[1] == 4:
            triangles = np.concatenate((faces[:, [0, 1, 2]], faces[:, [0, 2, 3]]))
        elif faces.shape[1] == 3:
            triangles = faces
        else:
            raise ValueError(f"Unexpected {name} patch faces")
        data[f"{name}_xyz_m"] = points.astype(np.float32)
        data[f"{name}_triangles"] = triangles.astype(np.int32)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "geometry.npz"
    np.savez_compressed(path, **data)
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    manifest["geometry_bundle"] = path.name
    manifest["mesh_vertical_layers"] = 4
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    shutil.copyfile(HERE / "extended_16_19_20_21_comparison.json", OUT / "results.json")
    print(path, path.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
