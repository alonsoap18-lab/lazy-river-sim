"""Preliminary cross-section geometry for the DXF's widest beach entry.

Only the two wall contours are present in the DXF; the submerged beach edge
is not surveyed. This model treats the extra width beyond the typical channel
as a *single-side* beach and keeps its two horizontal portions in a 1:2 ratio.
The profile contracts with the local DXF width. Narrower parts of the bay end
underwater rather than inventing a zero-depth exit outside the drawn boundary.
"""

from dataclasses import dataclass
from math import hypot, isfinite
from statistics import median
from typing import Sequence


@dataclass(frozen=True)
class BeachGeometry:
    area_m2: tuple[float, ...]
    wetted_perimeter_m: tuple[float, ...]
    floor_perimeter_m: tuple[float, ...]
    wall_perimeter_m: tuple[float, ...]
    wet_width_m: tuple[float, ...]
    beach_indices: tuple[int, ...]
    beach_start_m: float
    beach_end_m: float
    channel_reference_width_m: float
    beach_max_extra_width_m: float
    first_slope: float
    ramp_slope: float
    beach_end_depth_at_widest_m: float
    profile_fits_slope_limit: bool
    flat_entry_width_m: float | None = None


def _wide_runs(stations: Sequence[dict], threshold_m: float) -> list[list[int]]:
    runs: list[list[int]] = []
    current: list[int] = []
    for index, station in enumerate(stations):
        if float(station["width_m"]) >= threshold_m:
            current.append(index)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _sloped_area(start_depth: float, length: float, slope: float) -> tuple[float, float, float]:
    """Area, wetted floor length and final depth for one linear floor segment."""
    wet_length = min(length, max(0.0, start_depth / slope)) if slope > 0 else length
    area = start_depth * wet_length - slope * wet_length * wet_length / 2
    end_depth = max(0.0, start_depth - slope * length)
    return area, hypot(wet_length, wet_length * slope), end_depth


def compute_beach_geometry(stations: Sequence[dict], depth_m: float,
                           calm_width_m: float = 15.0,
                           first_share: float = 1 / 3,
                           minimum_slope: float = 0.02,
                           maximum_slope: float = 0.07,
                           flat_ramp_slope: float | None = None) -> BeachGeometry:
    """Fit the 1:2 section to the widest DXF bay, leaving other bays deep.

    At the widest section, the first third rises by one sixth of the channel
    depth and the remaining two thirds rise by five sixths. Slopes are bounded
    to the Costa Rican 2%-7% preliminary interval. If the drawn width cannot
    reach the shoreline inside those bounds, the residual depth is reported.
    """
    if len(stations) < 2 or any(not isfinite(float(s["width_m"])) or
                                float(s["width_m"]) <= 0 for s in stations):
        raise ValueError("El perfil de playa requiere secciones DXF válidas.")
    if not all(isfinite(x) for x in (depth_m, calm_width_m, first_share,
                                    minimum_slope, maximum_slope)):
        raise ValueError("El perfil de playa requiere parámetros finitos.")
    if (depth_m <= 0 or calm_width_m <= 0 or not 0 < first_share < 1 or
            not 0 < minimum_slope <= maximum_slope):
        raise ValueError("Profundidad, proporciones y pendientes de playa inválidas.")
    if flat_ramp_slope is not None and (not isfinite(flat_ramp_slope) or flat_ramp_slope <= 0):
        raise ValueError("La pendiente de la rampa debe ser positiva.")

    widths = [float(s["width_m"]) for s in stations]
    current_widths = [w for w in widths if w < calm_width_m]
    reference_width = median(current_widths or widths)
    # The origin can lie inside the main beach. Join the wide segments on
    # either side of the 0/L seam before selecting the physical bay.
    unique_count = len(stations) - 1
    runs = _wide_runs(stations[:unique_count], calm_width_m)
    if len(runs) > 1 and runs[0][0] == 0 and runs[-1][-1] == unique_count - 1:
        runs = [runs[-1] + runs[0], *runs[1:-1]]
    if not runs:
        raise ValueError("No existe un ensanchamiento de playa en el DXF.")
    widest_run = max(runs, key=lambda run: max(widths[i] for i in run))
    first, last = widest_run[0], widest_run[-1]
    # Extend into the tapered approaches until the extra width vanishes. This
    # keeps sectional area continuous at the calm-width classification edge.
    selected = set(widest_run)
    while len(selected) < unique_count and widths[(first - 1) % unique_count] > reference_width:
        first = (first - 1) % unique_count
        selected.add(first)
    while len(selected) < unique_count and widths[(last + 1) % unique_count] > reference_width:
        last = (last + 1) % unique_count
        selected.add(last)
    indices = tuple((first + step) % unique_count
                    for step in range((last - first) % unique_count + 1))
    max_extra = max(widths[i] - reference_width for i in indices)
    first_length_max = max_extra * first_share
    ramp_length_max = max_extra * (1 - first_share)
    if first_length_max <= 0 or ramp_length_max <= 0:
        raise ValueError("La playa no tiene ancho adicional respecto al canal.")
    if flat_ramp_slope is None:
        first_required = depth_m / 6 / first_length_max
        ramp_required = depth_m * 5 / 6 / ramp_length_max
        first_slope = min(max(first_required, minimum_slope), maximum_slope)
        ramp_slope = min(max(ramp_required, minimum_slope), maximum_slope)
    else:
        first_required = 0.0
        ramp_required = depth_m / ramp_length_max
        first_slope = 0.0
        ramp_slope = flat_ramp_slope
    end_depth_max = max(0.0, depth_m - first_slope * first_length_max -
                        ramp_slope * ramp_length_max)
    fits = (first_required <= maximum_slope and ramp_required <= maximum_slope and
            end_depth_max <= 1e-6)

    areas = []
    perimeters = []
    floors = []
    walls = []
    wet_widths = []
    selected = set(indices)
    for i, width in enumerate(widths):
        if i not in selected or width <= reference_width:
            area = width * depth_m
            floor = width
            wall = 2 * depth_m
            wet_width = width
        else:
            base_width = reference_width
            extra = width - base_width
            first_length = extra * first_share
            ramp_length = extra * (1 - first_share)
            area1, floor1, depth_after_first = _sloped_area(depth_m, first_length,
                                                             first_slope)
            area2, floor2, edge_depth = _sloped_area(depth_after_first, ramp_length,
                                                      ramp_slope)
            area = base_width * depth_m + area1 + area2
            floor = base_width + floor1 + floor2
            # One wall bounds the channel; the other bounds the beach only
            # where its DXF edge remains submerged.
            wall = depth_m + edge_depth
            wet_width = base_width + min(first_length, depth_m / first_slope if first_slope else first_length) + min(
                ramp_length, depth_after_first / ramp_slope)
        areas.append(area)
        floors.append(floor)
        walls.append(wall)
        perimeters.append(floor + wall)
        wet_widths.append(wet_width)
    # Last station duplicates station zero on this closed circuit.
    areas[-1], perimeters[-1] = areas[0], perimeters[0]
    floors[-1], walls[-1], wet_widths[-1] = floors[0], walls[0], wet_widths[0]
    return BeachGeometry(
        area_m2=tuple(areas), wetted_perimeter_m=tuple(perimeters),
        floor_perimeter_m=tuple(floors), wall_perimeter_m=tuple(walls),
        wet_width_m=tuple(wet_widths), beach_indices=indices,
        beach_start_m=float(stations[first]["chainage_m"]),
        beach_end_m=float(stations[last]["chainage_m"]),
        channel_reference_width_m=reference_width,
        beach_max_extra_width_m=max_extra, first_slope=first_slope,
        ramp_slope=ramp_slope, beach_end_depth_at_widest_m=end_depth_max,
        profile_fits_slope_limit=fits,
        flat_entry_width_m=first_length_max if flat_ramp_slope is not None else None)
