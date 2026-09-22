"""Professional centerline computation for closed-loop channels."""
import numpy as np
from shapely.geometry import LineString, Point, Polygon
from typing import List, Tuple, Optional
from scipy.signal import savgol_filter


def signed_centerline_area(stations) -> float:
    """CAD x/y signed area: negative means clockwise for a closed loop."""
    return 0.5 * sum(float(a["x"]) * float(b["y"]) - float(b["x"]) * float(a["y"])
                     for a, b in zip(stations, stations[1:]))


def orient_stations_clockwise(stations) -> list[dict]:
    """Keep the DXF origin but reverse chainage if the closed path is CCW."""
    if len(stations) < 3:
        raise ValueError("El recorrido DXF necesita al menos tres estaciones.")
    if signed_centerline_area(stations) < 0:
        return list(stations)
    length = float(stations[-1]["chainage_m"])
    ordered = [dict(stations[0]), *(dict(s) for s in reversed(stations[1:-1])),
               dict(stations[-1])]
    for index, station in enumerate(ordered):
        station["station_id"] = index
        station["chainage_m"] = (0.0 if index == 0 else length if index == len(ordered) - 1
                                 else length - float(station["chainage_m"]))
        for key in ("tangent_x", "tangent_y", "normal_x", "normal_y", "curvature_1_m"):
            if key in station:
                station[key] = -station[key]
    return ordered


class CenterlineBuilder:
    """Builds a smooth, properly-closed centerline between two walls."""

    def __init__(self, outer_wall: LineString, inner_wall: LineString,
                 resolution_m: float = 0.5, target_length_m: float = None):
        self.outer_wall = outer_wall
        self.inner_wall = inner_wall
        self.resolution_m = resolution_m
        self.target_length_m = target_length_m
        self.centerline: Optional[LineString] = None
        self.tangents: List[Tuple[float, float]] = []
        self.normals: List[Tuple[float, float]] = []
        self.widths: List[float] = []
        self.curvatures: List[float] = []
        self.chainages: List[float] = []

    def build(self) -> LineString:
        avg_length = (self.outer_wall.length + self.inner_wall.length) / 2.0
        n_samples = max(200, int(avg_length / self.resolution_m))

        # Resample outer wall and project each point onto inner wall
        outer_pts = self._resample_closed(self.outer_wall, n_samples)
        inner_pts = []

        for ox, oy in outer_pts:
            p = Point(ox, oy)
            proj_dist = self.inner_wall.project(p)
            nearest = self.inner_wall.interpolate(proj_dist)
            inner_pts.append((nearest.x, nearest.y))

        center_pts = []
        for o, i in zip(outer_pts, inner_pts):
            cx = (o[0] + i[0]) / 2.0
            cy = (o[1] + i[1]) / 2.0
            center_pts.append((cx, cy))

        # Close the loop
        if center_pts[0] != center_pts[-1]:
            center_pts.append(center_pts[0])

        cleaned = [center_pts[0]]
        for pt in center_pts[1:]:
            if pt != cleaned[-1]:
                cleaned.append(pt)

        self.centerline = LineString(cleaned)
        self._compute_tangents_normals()
        self._compute_widths_by_projection()
        self._compute_curvatures()
        self._compute_chainages()
        return self.centerline

    def _resample_closed(self, line: LineString, n: int) -> List[tuple]:
        total = line.length
        pts = []
        for i in range(n):
            d = (i / n) * total
            p = line.interpolate(d)
            pts.append((p.x, p.y))
        return pts

    def _compute_tangents_normals(self):
        coords = list(self.centerline.coords)
        n = len(coords)
        self.tangents = []
        self.normals = []

        for i in range(n):
            if i < n - 1:
                dx = coords[i + 1][0] - coords[i][0]
                dy = coords[i + 1][1] - coords[i][1]
            else:
                dx = coords[0][0] - coords[i][0]
                dy = coords[0][1] - coords[i][1]

            mag = np.sqrt(dx ** 2 + dy ** 2)
            if mag > 0:
                tx, ty = dx / mag, dy / mag
            else:
                tx, ty = 1.0, 0.0

            self.tangents.append((tx, ty))
            self.normals.append((-ty, tx))

    def _compute_widths_by_projection(self):
        """Compute local width by projecting centerline points onto both walls."""
        coords = list(self.centerline.coords)
        self.widths = []

        for cx, cy in coords:
            p = Point(cx, cy)
            d_outer = self.outer_wall.project(p)
            nearest_outer = self.outer_wall.interpolate(d_outer)
            dist_outer = p.distance(nearest_outer)

            d_inner = self.inner_wall.project(p)
            nearest_inner = self.inner_wall.interpolate(d_inner)
            dist_inner = p.distance(nearest_inner)

            w = dist_outer + dist_inner
            self.widths.append(max(w, 0.5))

    def _compute_curvatures(self):
        coords = list(self.centerline.coords)
        n = len(coords)
        self.curvatures = []

        for i in range(n):
            i_prev = (i - 1) % n
            i_next = (i + 1) % n

            x1, y1 = coords[i_prev]
            x2, y2 = coords[i]
            x3, y3 = coords[i_next]

            area2 = abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1))
            d1 = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            d2 = np.sqrt((x3 - x2) ** 2 + (y3 - y2) ** 2)
            d3 = np.sqrt((x3 - x1) ** 2 + (y3 - y1) ** 2)

            if d1 * d2 * d3 > 0:
                k = area2 / (d1 * d2 * d3)
            else:
                k = 0.0

            self.curvatures.append(k)

    def _compute_chainages(self):
        coords = list(self.centerline.coords)
        n = len(coords)
        self.chainages = [0.0]

        for i in range(1, n):
            dx = coords[i][0] - coords[i - 1][0]
            dy = coords[i][1] - coords[i - 1][1]
            ds = np.sqrt(dx ** 2 + dy ** 2)
            self.chainages.append(self.chainages[-1] + ds)

    def get_station_data(self) -> List[dict]:
        coords = list(self.centerline.coords)
        n = len(coords)
        stations = []

        for i in range(n):
            r = 1.0 / self.curvatures[i] if self.curvatures[i] > 1e-10 else float('inf')
            stations.append({
                'station_id': i,
                'chainage_m': self.chainages[i],
                'x': coords[i][0],
                'y': coords[i][1],
                'tangent_x': self.tangents[i][0],
                'tangent_y': self.tangents[i][1],
                'normal_x': self.normals[i][0],
                'normal_y': self.normals[i][1],
                'width_m': self.widths[i],
                'curvature_radius_m': r,
                'curvature_1_m': self.curvatures[i],
            })

        return stations
