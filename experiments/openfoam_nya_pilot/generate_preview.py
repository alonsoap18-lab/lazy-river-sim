"""Generate a DXF-derived 3D geometry preview for a future OpenFOAM pilot.

This is geometry only. It does not solve Navier–Stokes or predict velocity.
Run from the repository root with ``python experiments/openfoam_nya_pilot/generate_preview.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import plotly.graph_objects as go
from shapely.geometry import LineString, Point

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.beach_geometry import compute_beach_geometry  # noqa: E402
from core.orchestrator import LazyRiverModel  # noqa: E402


START_M = 180.0
END_M = 220.0
DEPTH_M = 1.20
N_LATERAL = 25
OUTPUT = Path(__file__).resolve().parent


def wall_on_normal(wall: LineString, station: dict, side: int) -> Point:
    """Intersect the station normal with a wall; avoid repeated nearest vertices.

    The original app width uses nearest-point projection. For a CFD sweep,
    that can pin consecutive sections to the same wall vertex and collapse
    cells. This normal cut is a separate, explicitly labelled geometry step.
    """
    centre = np.array([station["x"], station["y"]], dtype=float)
    normal = np.array([station["normal_x"], station["normal_y"]], dtype=float)
    cut = LineString([centre - 100 * normal, centre + 100 * normal])
    crossing = wall.intersection(cut)
    candidates = []

    def collect(geometry):
        if geometry.is_empty:
            return
        if geometry.geom_type == "Point":
            candidates.append(geometry)
        elif geometry.geom_type in {"LineString", "LinearRing"}:
            candidates.extend((Point(geometry.coords[0]), Point(geometry.coords[-1])))
        elif hasattr(geometry, "geoms"):
            for part in geometry.geoms:
                collect(part)

    collect(crossing)
    signed = [(float(np.dot(np.array([point.x, point.y]) - centre, normal)), point)
              for point in candidates]
    eligible = [(abs(distance), point) for distance, point in signed
                if distance * side > 1e-6]
    if not eligible:
        raise ValueError("No se pudo cortar el muro DXF con la normal de la estación.")
    return min(eligible, key=lambda item: item[0])[1]


def section_depth(offset_m: float, width_m: float, reference_m: float,
                  first_slope: float, ramp_slope: float) -> float:
    """Illustrative one-bank beach profile; inner bank remains deep."""
    extra = max(0.0, width_m - reference_m)
    deep_width = width_m - extra
    if offset_m <= deep_width:
        return DEPTH_M
    beach_offset = offset_m - deep_width
    first = extra / 3.0
    rise = first_slope * min(beach_offset, first)
    rise += ramp_slope * max(0.0, beach_offset - first)
    return max(0.0, DEPTH_M - rise)


def build_geometry(start_m: float = START_M, end_m: float = END_M,
                   method: str = "nearest"):
    model = LazyRiverModel()
    issues = model.load_dxf(str(ROOT / "RECORRIDO.dxf"))
    if issues:
        raise ValueError(f"DXF no válido: {issues}")
    model.build_centerline(target_length_m=536)
    stations = model.stations
    beach = compute_beach_geometry(stations, DEPTH_M)
    scale = model.geometry.scale_m_per_unit
    selected = [s for s in stations if start_m <= s["chainage_m"] <= end_m]
    if len(selected) < 3:
        raise ValueError("El tramo elegido no contiene suficientes estaciones.")

    xy = np.zeros((len(selected), N_LATERAL, 2))
    depth = np.zeros((len(selected), N_LATERAL))
    chainages = []
    widths = []
    for i, station in enumerate(selected):
        if method == "normal":
            inner = wall_on_normal(model.loader.inner_wall, station, -1)
            outer = wall_on_normal(model.loader.outer_wall, station, 1)
        elif method == "nearest":
            p = Point(station["x"], station["y"])
            inner = model.loader.inner_wall.interpolate(model.loader.inner_wall.project(p))
            outer = model.loader.outer_wall.interpolate(model.loader.outer_wall.project(p))
        else:
            raise ValueError("Método de sección no reconocido.")
        # The supplied DXF units are uniformly scaled to its agreed 536 m loop.
        inner_xy = np.array([inner.x, inner.y]) * scale
        outer_xy = np.array([outer.x, outer.y]) * scale
        actual_width = float(np.linalg.norm(outer_xy - inner_xy))
        if actual_width <= 0:
            raise ValueError("Sección degenerada del DXF.")
        for j, fraction in enumerate(np.linspace(0, 1, N_LATERAL)):
            xy[i, j] = inner_xy + fraction * (outer_xy - inner_xy)
            depth[i, j] = section_depth(
                fraction * actual_width, actual_width,
                beach.channel_reference_width_m,
                beach.first_slope, beach.ramp_slope)
        chainages.append(float(station["chainage_m"]))
        widths.append(actual_width)

    # A local origin reduces 3D rendering precision problems.
    origin = xy[0, 0].copy()
    xy -= origin
    return xy, depth, np.array(chainages), np.array(widths), beach, origin


def main():
    xy, depth, chainages, widths, beach, origin = build_geometry()
    x, y = xy[:, :, 0], xy[:, :, 1]
    fig = go.Figure()
    fig.add_trace(go.Surface(
        x=x, y=y, z=-depth, surfacecolor=depth,
        colorscale=[[0, "#f8df9a"], [.35, "#bbd7c9"], [1, "#1f6f88"]],
        cmin=0, cmax=DEPTH_M, colorbar=dict(title="Profundidad<br>hipotética (m)"),
        name="Fondo supuesto", opacity=.95))
    fig.add_trace(go.Surface(
        x=x, y=y, z=np.zeros_like(depth),
        colorscale=[[0, "#4cb8e8"], [1, "#4cb8e8"]], showscale=False,
        opacity=.22, name="Lámina de agua"))
    for edge, label in ((0, "Borde interior DXF"), (-1, "Borde exterior DXF")):
        fig.add_trace(go.Scatter3d(
            x=x[:, edge], y=y[:, edge], z=np.zeros(len(x)),
            mode="lines", line=dict(width=7, color="#152f42"), name=label))
    fig.add_trace(go.Scatter3d(
        x=x[:, 0], y=y[:, 0], z=np.full(len(x), .12),
        mode="lines", line=dict(width=6, color="#ef7b45"),
        name="Sentido antihorario (cadena creciente)"))
    mid = len(chainages) // 2
    fig.add_trace(go.Scatter3d(
        x=[x[mid, 0]], y=[y[mid, 0]], z=[.2], mode="markers+text",
        marker=dict(size=6, color="#c72c41"),
        text=["Riverflow: posición conceptual, NO plano de instalación"],
        textposition="top center", name="Ubicación por comprobar"))
    fig.update_layout(
        title=f"NYA · tramo DXF {chainages[0]:.1f}–{chainages[-1]:.1f} m · geometría preliminar",
        scene=dict(xaxis_title="Este local (m)", yaxis_title="Norte local (m)",
                   zaxis_title="Cota relativa (m)", aspectmode="data"),
        annotations=[dict(
            text="VISTA GEOMÉTRICA, NO RESULTADO CFD · sin velocidad calculada",
            x=.01, y=.01, xref="paper", yref="paper", showarrow=False,
            bgcolor="#fff4d6", font=dict(color="#5a3f05"))],
        legend=dict(orientation="h", y=-.05), height=750)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fig.write_html(OUTPUT / "vista_3d_preliminar.html", include_plotlyjs=True)
    metadata = {
        "source": "RECORRIDO.dxf, capa PAREDES; DXF original sin modificar",
        "status": "geometry_preview_only_not_CFD",
        "direction": "counterclockwise",
        "chainage_start_m": float(chainages[0]),
        "chainage_end_m": float(chainages[-1]),
        "width_min_m": float(widths.min()),
        "width_max_m": float(widths.max()),
        "nominal_depth_m": DEPTH_M,
        "beach_side_assumption": "outer DXF contour",
        "beach_reference_channel_width_m": beach.channel_reference_width_m,
        "beach_first_slope": beach.first_slope,
        "beach_ramp_slope": beach.ramp_slope,
        "local_xy_origin_dxf_scaled_m": origin.tolist(),
        "riverflow_marker": "illustrative only; no surveyed intake, discharge or elevation",
        "not_yet_modelled": ["jet and suction geometry", "surveyed elevations",
                              "pump boundary conditions", "wall roughness calibration",
                              "free surface motion", "turbulence", "people"],
    }
    (OUTPUT / "geometry_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metadata, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
