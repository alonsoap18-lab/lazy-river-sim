"""Conservative, depth-averaged 2D *scenario* field for the NYA channel.

This is a streamfunction-based reduced-order model, not a Navier--Stokes or
shallow-water CFD solver. It preserves the plan's through-flow at every
cross-section and permits longitudinal and lateral velocities to vary with
module positions. Jet coupling and lateral shape are uncalibrated hypotheses.
"""

from dataclasses import dataclass
from math import pi
from typing import Sequence

import numpy as np

from core.riverflow_model import RiverflowPlan


@dataclass(frozen=True)
class RiverflowField2D:
    chainages_m: np.ndarray
    lateral_fraction: np.ndarray
    widths_m: np.ndarray
    x: np.ndarray
    y: np.ndarray
    longitudinal_m_s: np.ndarray
    lateral_m_s: np.ndarray
    speed_m_s: np.ndarray
    section_flow_m3_s: np.ndarray
    lane_lap_min: tuple[float, float, float]
    center_lane_x: np.ndarray
    center_lane_y: np.ndarray
    center_lane_time_min: np.ndarray
    volume_residual_fraction: float


def compute_field_2d(stations: Sequence[dict], plan: RiverflowPlan,
                     depth_m: float, scale_m_per_unit: float = 1.0,
                     longitudinal_cells: int = 160,
                     lateral_cells: int = 11) -> RiverflowField2D:
    if depth_m <= 0 or scale_m_per_unit <= 0 or longitudinal_cells < 32 or lateral_cells < 5:
        raise ValueError("Profundidad y resolución de la malla 2D deben ser positivas.")
    source_s = np.array([float(p["chainage_m"]) for p in stations])
    if np.any(np.diff(source_s) <= 0):
        raise ValueError("Las estaciones 2D deben estar ordenadas y sin duplicados.")
    length = source_s[-1]
    s = np.linspace(0, length, longitudinal_cells + 1)
    eta = np.linspace(0, 1, lateral_cells + 1)
    widths = np.interp(s, source_s, [float(p["width_m"]) for p in stations])
    center_x = np.interp(s, source_s, [float(p["x"]) for p in stations])
    center_y = np.interp(s, source_s, [float(p["y"]) for p in stations])
    normal_x = np.interp(s, source_s, [float(p["normal_x"]) for p in stations])
    normal_y = np.interp(s, source_s, [float(p["normal_y"]) for p in stations])
    normal_length = np.hypot(normal_x, normal_y)
    normal_x, normal_y = normal_x / normal_length, normal_y / normal_length
    x = center_x[:, None] + normal_x[:, None] * widths[:, None] * (eta - 0.5) / scale_m_per_unit
    y = center_y[:, None] + normal_y[:, None] * widths[:, None] * (eta - 0.5) / scale_m_per_unit

    # Baseline shape has slower banks. Localized smooth perturbations represent
    # hypothesized lateral jet steering; their magnitude is NOT supplier data.
    bias = np.zeros_like(s)
    for position, angle in zip(plan.module_chainages_m, plan.module_angles_deg):
        distance = np.minimum(abs(s - position), length - abs(s - position))
        spread = max(4.0, min(12.0, length / max(2 * plan.active_modules, 1)))
        bias += (0.055 * np.cos(np.deg2rad(angle))
                 + 0.035 * np.sin(np.deg2rad(angle))) * np.exp(-0.5 * (distance / spread) ** 2)
    bias = np.clip(bias, -0.15, 0.15)
    q = plan.equivalent_channel_flow_m3_h / 3600.0
    base = eta - 0.25 * np.sin(2 * pi * eta) / (2 * pi)
    psi = q * (base[None, :] + bias[:, None] * np.sin(pi * eta)[None, :])
    # u = d(psi)/dy / h; v = -d(psi)/ds|y / h. These identities make
    # divergence(h*u,h*v)=0 and keep both banks impermeable (constant psi).
    dpsi_deta = q * (1 - 0.25 * np.cos(2 * pi * eta)[None, :]
                     + pi * bias[:, None] * np.cos(pi * eta)[None, :])
    longitudinal = dpsi_deta / (depth_m * widths[:, None])
    dpsi_ds_eta = np.gradient(psi, s, axis=0)
    width_gradient = np.gradient(widths, s)
    lateral = (-dpsi_ds_eta / depth_m
               + longitudinal * (eta - 0.5)[None, :] * width_gradient[:, None])
    speed = np.hypot(longitudinal, lateral)
    # Trapezoidal quadrature of the exact streamfunction boundary difference.
    section_flow = np.trapezoid(longitudinal * depth_m * widths[:, None], eta, axis=1)
    residual = float(np.max(np.abs(section_flow - q)) / q)

    lap_times = []
    center_lane_x = center_lane_y = center_lane_time = None
    for stream_fraction in (0.2, 0.5, 0.8):
        lane_eta = np.array([np.interp(stream_fraction, row / q, eta) for row in psi])
        lane_u = np.array([np.interp(e, eta, row) for e, row in zip(lane_eta, longitudinal)])
        segment_times = np.diff(s) * (1 / lane_u[:-1] + 1 / lane_u[1:]) / 120
        time = np.r_[0.0, np.cumsum(segment_times)]
        lap_times.append(float(time[-1]))
        if stream_fraction == 0.5:
            center_lane_x = np.array([np.interp(e, eta, row) for e, row in zip(lane_eta, x)])
            center_lane_y = np.array([np.interp(e, eta, row) for e, row in zip(lane_eta, y)])
            center_lane_time = time
    return RiverflowField2D(
        chainages_m=s, lateral_fraction=eta, widths_m=widths, x=x, y=y,
        longitudinal_m_s=longitudinal, lateral_m_s=lateral, speed_m_s=speed,
        section_flow_m3_s=section_flow, lane_lap_min=tuple(lap_times),
        center_lane_x=center_lane_x, center_lane_y=center_lane_y,
        center_lane_time_min=center_lane_time,
        volume_residual_fraction=residual)
