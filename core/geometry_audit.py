"""Read-only checks for DXF-derived channel sections.

The operating model keeps its established station grid.  These checks expose
where a nearest-wall width may not represent a section normal to the route.
"""

from dataclasses import dataclass
from math import hypot, isfinite
from typing import Sequence

from shapely.geometry import LineString, Point


@dataclass(frozen=True)
class SectionCheck:
    chainage_m: float
    x: float
    y: float
    model_width_m: float
    normal_width_m: float | None
    status: str


def _intersection_points(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Point":
        return [geometry]
    if geometry.geom_type in ("MultiPoint", "GeometryCollection"):
        return [point for part in geometry.geoms for point in _intersection_points(part)]
    if geometry.geom_type in ("LineString", "LinearRing"):
        return [Point(geometry.coords[0]), Point(geometry.coords[-1])]
    if hasattr(geometry, "geoms"):
        return [point for part in geometry.geoms for point in _intersection_points(part)]
    return []


def normal_section_width(station: dict, outer_wall: LineString,
                         inner_wall: LineString, scale_m_per_unit: float):
    """Return a normal width only if the nearest walls bracket the station."""
    x, y = float(station["x"]), float(station["y"])
    nx, ny = float(station["normal_x"]), float(station["normal_y"])
    norm = hypot(nx, ny)
    if norm <= 0 or scale_m_per_unit <= 0:
        return None
    nx, ny = nx / norm, ny / norm
    reach = max(outer_wall.bounds[2] - outer_wall.bounds[0],
                outer_wall.bounds[3] - outer_wall.bounds[1]) * 2 + 1
    cut = LineString([(x - reach * nx, y - reach * ny),
                      (x + reach * nx, y + reach * ny)])
    hits = []
    for wall_name, wall in (("outer", outer_wall), ("inner", inner_wall)):
        for point in _intersection_points(cut.intersection(wall)):
            signed = (point.x - x) * nx + (point.y - y) * ny
            if abs(signed) > 1e-8:
                hits.append((signed, wall_name))
    positive = sorted((hit for hit in hits if hit[0] > 0), key=lambda hit: hit[0])
    negative = sorted((hit for hit in hits if hit[0] < 0), key=lambda hit: -hit[0])
    if not positive or not negative or positive[0][1] == negative[0][1]:
        return None
    return (positive[0][0] - negative[0][0]) * scale_m_per_unit


def audit_geometry(stations: Sequence[dict], outer_wall: LineString,
                   inner_wall: LineString, scale_m_per_unit: float,
                   polygon_area_m2: float, spacing_m: float = 5.0):
    """Sample normal cuts and compare integrated model area with the CAD domain."""
    if spacing_m <= 0 or not isfinite(spacing_m):
        raise ValueError("El intervalo de auditoría debe ser positivo y finito.")
    if len(stations) < 2:
        raise ValueError("Se necesitan al menos dos estaciones para auditar el DXF.")
    selected = [stations[0]]
    last = 0.0
    for station in stations[1:-1]:
        chainage = float(station["chainage_m"])
        if chainage - last >= spacing_m:
            selected.append(station)
            last = chainage
    # A closed route repeats its first coordinate at the last chainage.  Its
    # tangent there may be degenerate, so the first section represents both.
    checks = []
    for station in selected:
        model_width = float(station["width_m"])
        normal_width = normal_section_width(station, outer_wall, inner_wall,
                                            scale_m_per_unit)
        if normal_width is None:
            status = "Sección perpendicular ambigua"
        elif abs(normal_width - model_width) > max(0.5, 0.15 * normal_width):
            status = "Diferencia de ancho: revisar DXF"
        else:
            status = "Consistente"
        checks.append(SectionCheck(float(station["chainage_m"]),
                                   float(station["x"]), float(station["y"]),
                                   model_width, normal_width, status))
    integrated_area = sum((float(b["chainage_m"]) - float(a["chainage_m"]))
                          * (float(a["width_m"]) + float(b["width_m"])) / 2
                          for a, b in zip(stations, stations[1:]))
    area_difference = ((integrated_area / polygon_area_m2 - 1)
                       if polygon_area_m2 > 0 else None)
    return checks, integrated_area, area_difference
