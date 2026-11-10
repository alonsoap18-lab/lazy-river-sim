"""Reanalyse four saved 1200 s fields with common passage/beach masks.

This script reads existing VTK outputs. It does not run or alter OpenFOAM.
"""

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

from core.beach_geometry import compute_beach_geometry  # noqa: E402
from core.orchestrator import LazyRiverModel  # noqa: E402
from visualize_result import read_vtk  # noqa: E402

CASES = {
    "16_removed_four": "manning_ablation_16_width_4m_600s_xy",
    "19_removed": "manning_incremental_19_removed_600s_xy",
    "20_original": "manning_ablation_20_width_4m_600s_xy",
    "21_added_downstream": "manning_downstream_21_added_600s_xy",
}


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    return float(values[order[np.searchsorted(np.cumsum(weights[order]),
                                             q * np.sum(weights))]])


def summarize(along: np.ndarray, volume: np.ndarray, mask: np.ndarray) -> dict:
    if not np.any(mask):
        raise ValueError("Empty comparison region")
    v, w = along[mask], volume[mask]
    total = np.sum(w)
    return {
        "cells": int(np.count_nonzero(mask)),
        "volume_m3": float(total),
        "median_m_s": weighted_quantile(v, w, .5),
        "p95_m_s": weighted_quantile(v, w, .95),
        "volume_fraction_below_0_15": float(np.sum(w[v < .15]) / total),
        "volume_fraction_reverse_below_minus_0_02": float(
            np.sum(w[v < -.02]) / total),
    }


def main() -> None:
    model = LazyRiverModel()
    if model.load_dxf(str(ROOT / "RECORRIDO.dxf")):
        raise ValueError("Cannot load original DXF")
    model.build_centerline(target_length_m=536)
    stations = model.stations[:-1]
    origin = np.asarray(model.loader.outer_polygon.centroid.coords[0])
    scale = model.geometry.scale_m_per_unit
    axis = (np.asarray([[s["x"], s["y"]] for s in stations]) - origin) * scale
    tangent = np.asarray([[s["tangent_x"], s["tangent_y"]] for s in stations])
    width = np.asarray([s["width_m"] for s in stations])
    beach_ids = set(compute_beach_geometry(model.stations, 1.2).beach_indices)
    jet_xy = []
    for name in CASES.values():
        metadata = json.loads((HERE / name / "metadata.json").read_text())
        jet_xy.extend(s["zones"]["jet"]["cell_xy_m"] for s in metadata["stations"])
    jet_xy = np.asarray(jet_xy)

    outputs = {}
    base_centres = base_volume = None
    for key, name in CASES.items():
        centres, fields, points, cells = read_vtk(
            HERE / f"manning_k_epsilon_{key.split('_')[0]}_1200s.vtk")
        volume = np.asarray([ConvexHull(points[cell]).volume for cell in cells])
        if base_centres is None:
            base_centres, base_volume = centres, volume
        elif (not np.allclose(centres, base_centres, atol=1e-5) or
              not np.allclose(volume, base_volume, atol=1e-7, rtol=1e-7)):
            raise ValueError("Compared fields do not share the same mesh")
        nearest = cKDTree(axis).query(centres[:, :2])[1]
        along = np.einsum("ij,ij->i", fields["U"][:, :2], tangent[nearest])
        away = cKDTree(jet_xy).query(centres[:, :2])[0] >= 6
        beach = np.isin(nearest, list(beach_ids))
        masks = {
            "wide_passage_away": away & ~beach & (width[nearest] >= 15),
            "narrow_passage_away": away & ~beach & (width[nearest] < 10),
            "main_beach_away": away & beach,
            "all_passage_away": away & ~beach,
        }
        outputs[key] = {region: summarize(along, volume, mask)
                        for region, mask in masks.items()}
    result = {
        "status": "saved-field comparison, not physical validation",
        "source_dxf": "RECORRIDO.dxf",
        "physical_time_s": 1200,
        "mesh_cells": len(base_centres),
        "mask": "same cells for all cases; exclude 6 m around union of tested jets",
        "regions": outputs,
    }
    (HERE / "saved_count_regions_1200s.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for key, regions in outputs.items():
        print(key, {name: (round(data["median_m_s"], 3),
                          round(100 * data["volume_fraction_below_0_15"], 1))
                    for name, data in regions.items()})


if __name__ == "__main__":
    main()
