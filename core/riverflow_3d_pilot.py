"""Energy/continuity pilot behind a DXF-shaped 3D Riverflow view.

This is a one-dimensional, steady closed-loop balance drawn in 3D, not CFD.
Pump discharge is local recirculation; it is never added to loop through-flow.
The unmeasured coupling fraction remains an explicit scenario assumption.
"""

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class LoopPilotResult:
    chainages_m: np.ndarray
    section_area_m2: np.ndarray
    section_speed_m_s: np.ndarray
    section_friction_head_m: np.ndarray
    cumulative_time_s: np.ndarray
    loop_flow_m3_h: float
    lap_min: float
    mean_lap_speed_m_s: float
    resistance_s2_m5: float
    total_useful_drive_m4_s: float
    placement_scores: tuple[float, ...]
    max_unpowered_friction_gap_m: float
    max_module_spacing_m: float


@dataclass(frozen=True)
class SpeedBandAssessment:
    selected_length_m: float
    current_coverage_fraction: float
    best_possible_coverage_fraction: float
    best_possible_flow_m3_h: float
    all_sections_feasible: bool
    required_flow_lower_m3_h: float
    required_flow_upper_m3_h: float
    selected_speed_min_m_s: float
    selected_speed_max_m_s: float


def assess_speed_band(chainages_m: Sequence[float], section_area_m2: Sequence[float],
                      widths_m: Sequence[float], loop_flow_m3_h: float,
                      *, narrow_width_m: float = 8.0,
                      speed_min_m_s: float = .25,
                      speed_max_m_s: float = .30) -> SpeedBandAssessment:
    """Length-weighted Q/A target coverage; no pump or CFD claims.

    In a closed, unbranched channel the same longitudinal Q crosses every
    section. This detects when varying wetted areas make a tight speed band
    impossible for *any* pump count or VFD setting under the 1D assumption.
    """
    s = np.asarray(chainages_m, dtype=float)
    area = np.asarray(section_area_m2, dtype=float)
    widths = np.asarray(widths_m, dtype=float)
    if (len(s) < 3 or len(s) != len(area) or len(s) != len(widths)
            or not all(np.all(np.isfinite(v)) for v in (s, area, widths))
            or np.any(np.diff(s) <= 0) or np.any(area <= 0) or np.any(widths <= 0)
            or not all(isfinite(v) and v > 0 for v in
                       (loop_flow_m3_h, narrow_width_m, speed_min_m_s, speed_max_m_s))
            or speed_min_m_s >= speed_max_m_s):
        raise ValueError("Secciones o banda de velocidad inválidas.")
    ds = np.diff(s)
    mid_area = (area[:-1] + area[1:]) / 2
    mid_width = (widths[:-1] + widths[1:]) / 2
    selected = mid_width <= narrow_width_m
    if not np.any(selected):
        raise ValueError("No hay longitud con ese límite de ancho angosto.")
    weights = ds[selected]
    selected_area = mid_area[selected]
    current_speed = loop_flow_m3_h / 3600 / selected_area
    current_fraction = float(np.sum(weights * (
        (current_speed >= speed_min_m_s) &
        (current_speed <= speed_max_m_s))) / np.sum(weights))
    lower = speed_min_m_s * selected_area
    upper = speed_max_m_s * selected_area
    required_lower = float(np.max(lower))
    required_upper = float(np.min(upper))
    events = sorted([(float(q), float(w)) for q, w in zip(lower, weights)] +
                    [(float(q), -float(w)) for q, w in zip(upper, weights)])
    active = 0.0
    best_weight = -1.0
    best_q = 0.0
    for index, (point, change) in enumerate(events[:-1]):
        active += change
        next_point = events[index + 1][0]
        if next_point > point and active > best_weight:
            best_weight = active
            best_q = (point + next_point) / 2
    return SpeedBandAssessment(
        selected_length_m=float(np.sum(weights)),
        current_coverage_fraction=current_fraction,
        best_possible_coverage_fraction=max(0.0, best_weight / np.sum(weights)),
        best_possible_flow_m3_h=best_q * 3600,
        all_sections_feasible=required_lower <= required_upper,
        required_flow_lower_m3_h=required_lower * 3600,
        required_flow_upper_m3_h=required_upper * 3600,
        selected_speed_min_m_s=float(np.min(current_speed)),
        selected_speed_max_m_s=float(np.max(current_speed)),
    )


def solve_loop_pilot(
    chainages_m: Sequence[float], section_area_m2: Sequence[float],
    wetted_perimeter_m: Sequence[float], station_manning_n: Sequence[float],
    module_positions_m: Sequence[float], module_angles_deg: Sequence[float],
    *, module_flow_m3_h: float, module_head_m: float,
    useful_coupling_fraction: float, current_reference_width_m: float,
    section_width_m: Sequence[float],
) -> LoopPilotResult:
    s = np.asarray(chainages_m, dtype=float)
    area = np.asarray(section_area_m2, dtype=float)
    perimeter = np.asarray(wetted_perimeter_m, dtype=float)
    manning = np.asarray(station_manning_n, dtype=float)
    widths = np.asarray(section_width_m, dtype=float)
    positions = np.asarray(module_positions_m, dtype=float)
    angles = np.asarray(module_angles_deg, dtype=float)
    if (len(s) < 3 or any(len(v) != len(s) for v in (area, perimeter, manning, widths))
            or len(positions) == 0 or len(positions) != len(angles)
            or any(not np.all(np.isfinite(v)) for v in
                   (s, area, perimeter, manning, widths, positions, angles))
            or np.any(np.diff(s) <= 0) or s[0] != 0
            or np.any(area <= 0) or np.any(perimeter <= 0)
            or np.any(manning <= 0) or np.any(widths <= 0)
            or np.any(positions < 0) or np.any(positions >= s[-1])
            or np.any(np.abs(angles) > 75)
            or not all(isfinite(v) and v > 0 for v in
                       (module_flow_m3_h, module_head_m, useful_coupling_fraction,
                        current_reference_width_m))
            or useful_coupling_fraction > 1):
        raise ValueError("Geometría, rugosidad, ubicación o bomba del escenario inválidas.")

    radius = area / perimeter
    loss_coefficient = (manning / (area * radius ** (2 / 3))) ** 2
    ds = np.diff(s)
    resistance = float(np.sum(ds * (loss_coefficient[:-1] + loss_coefficient[1:]) / 2))
    if resistance <= 0:
        raise ValueError("La resistencia del circuito debe ser positiva.")

    local_widths = np.interp(positions, s, widths)
    # Scenario-only steering penalty, not a supplier efficiency or CFD result.
    scores = np.minimum(1.0, np.sqrt(current_reference_width_m / local_widths)) * \
        np.cos(np.deg2rad(angles)) ** 2
    drive_each = (module_flow_m3_h / 3600 * module_head_m *
                  useful_coupling_fraction * scores)
    drive = float(np.sum(drive_each))
    q = (drive / resistance) ** (1 / 3)
    speed = q / area
    segment_time = ds * (area[:-1] + area[1:]) / (2 * q)
    time = np.r_[0.0, np.cumsum(segment_time)]
    friction_head = loss_coefficient * q ** 2
    cumulative_loss = np.r_[0.0, np.cumsum(
        ds * (friction_head[:-1] + friction_head[1:]) / 2)]
    sorted_positions = np.sort(positions)
    cyclic_positions = np.r_[sorted_positions, sorted_positions[0] + s[-1]]
    spacing = np.diff(cyclic_positions)
    cumulative_at_modules = np.interp(sorted_positions, s, cumulative_loss)
    cyclic_loss = np.r_[cumulative_at_modules,
                        cumulative_at_modules[0] + cumulative_loss[-1]]
    unpowered_gaps = np.diff(cyclic_loss)
    return LoopPilotResult(
        chainages_m=s, section_area_m2=area, section_speed_m_s=speed,
        section_friction_head_m=friction_head, cumulative_time_s=time,
        loop_flow_m3_h=q * 3600, lap_min=float(time[-1] / 60),
        mean_lap_speed_m_s=float(s[-1] / time[-1]),
        resistance_s2_m5=resistance, total_useful_drive_m4_s=drive,
        placement_scores=tuple(float(v) for v in scores),
        max_unpowered_friction_gap_m=float(np.max(unpowered_gaps)),
        max_module_spacing_m=float(np.max(spacing)),
    )
