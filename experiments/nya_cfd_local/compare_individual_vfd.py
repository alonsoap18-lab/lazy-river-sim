"""Compare saved full-loop CFD fields for a per-pump VFD trial."""

from __future__ import annotations

import argparse
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
from compare_narrow_flow_sensitivity import final_vtk, region_metrics  # noqa: E402
from visualize_result import read_vtk  # noqa: E402

CASES = (
    "qa_original_reference20_dt05",
    "qa_vfd_rf17_80_dt05",
    "qa_vfd_rf17_60_dt05",
    "qa_original_narrow3_q80_consistent_dt05",
)
LENGTH_M = 536
N_BINS = 67


def main(cases: tuple[str, ...] = CASES,
         output_file: str = "individual_vfd_comparison.json") -> None:
    model = LazyRiverModel()
    if model.load_dxf(str(ROOT / "RECORRIDO.dxf")):
        raise ValueError("Cannot load original DXF")
    model.build_centerline(target_length_m=LENGTH_M)
    stations = model.stations[:-1]
    origin = np.asarray(model.loader.outer_polygon.centroid.coords[0])
    scale = model.geometry.scale_m_per_unit
    axis = (np.asarray([[s["x"], s["y"]] for s in stations]) - origin) * scale
    tangent = np.asarray([[s["tangent_x"], s["tangent_y"]] for s in stations])
    chainage = np.asarray([s["chainage_m"] for s in stations])
    width = np.asarray([s["width_m"] for s in stations])
    beach_ids = set(compute_beach_geometry(model.stations, 1.2).beach_indices)
    metas = {name: json.loads((HERE / name / "metadata.json").read_text())
             for name in cases}
    if len({meta["source_dxf_sha256"] for meta in metas.values()}) != 1:
        raise ValueError("Different source DXFs")
    jets = np.asarray([station["zones"]["jet"]["cell_xy_m"]
                       for meta in metas.values() for station in meta["stations"]])
    output = {}
    base_centres = base_volumes = None
    for name in cases:
        case = HERE / name
        if "Mesh OK." not in (case / "checkMesh.log").read_text():
            raise ValueError(f"Mesh check missing: {name}")
        centres, fields, points, cells = read_vtk(final_vtk(case))
        volume = np.asarray([ConvexHull(points[cell]).volume for cell in cells])
        if base_centres is None:
            base_centres, base_volumes = centres, volume
        elif (not np.allclose(centres, base_centres, atol=1e-5) or
              not np.allclose(volume, base_volumes, atol=1e-7, rtol=1e-7)):
            raise ValueError("Case mesh differs")
        nearest = cKDTree(axis).query(centres[:, :2])[1]
        along = np.einsum("ij,ij->i", fields["U"][:, :2], tangent[nearest])
        bins = np.minimum((chainage[nearest] / LENGTH_M * N_BINS).astype(int), N_BINS - 1)
        bin_volume = np.bincount(bins, weights=volume, minlength=N_BINS)
        if np.any(bin_volume <= 0):
            raise ValueError("Empty 8-m section")
        section = np.bincount(bins, weights=volume * along,
                              minlength=N_BINS) / bin_volume
        away = cKDTree(jets).query(centres[:, :2])[0] >= 6
        beach = np.isin(nearest, list(beach_ids))
        masks = {
            "wide_passage_away": away & ~beach & (width[nearest] >= 15),
            "narrow_passage_away": away & ~beach & (width[nearest] < 10),
            "main_beach_away": away & beach,
        }
        output[name] = {
            "vfd_operations": metas[name].get("vfd_operations", {}),
            "projected_hydraulic_lap_min": (
                float(np.sum((LENGTH_M / N_BINS) / section) / 60)
                if np.all(section > 0) else None),
            "minimum_section_speed_m_s": float(np.min(section)),
            "section_speed_m_s": section.tolist(),
            "reverse_volume_fraction": float(np.sum(volume[along < -.02]) / np.sum(volume)),
            "regions": {key: region_metrics(along, volume, mask)
                        for key, mask in masks.items()},
        }
    result = {
        "status": "uncalibrated per-pump VFD sensitivity, not Riverflow RPM validation",
        "common_mesh_cells": len(base_centres),
        "common_physical_time_s": 1200,
        "common_mask_rule": "exclude 6 m around union of jets; beach separate; volume-weighted",
        "cases": output,
    }
    (HERE / output_file).write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, value in output.items():
        lap = value["projected_hydraulic_lap_min"]
        print(name, round(lap, 2) if lap is not None else None,
              round(100 * value["regions"]["wide_passage_away"]["volume_fraction_below_0_15"], 1),
              round(value["regions"]["narrow_passage_away"]["p95_m_s"], 3))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", default=CASES)
    parser.add_argument("--output", default="individual_vfd_comparison.json")
    args = parser.parse_args()
    main(tuple(args.cases), args.output)
