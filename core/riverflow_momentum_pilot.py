"""Constrained, reduced-order longitudinal-momentum experiment.

This is deliberately separate from the purchasing/flow model. It solves a
linearized steady advection--lateral-diffusion--Manning-drag balance on an
unwrapped, periodic channel. A section pressure multiplier enforces the same
through-flow as RiverflowPlan. It is NOT the two-dimensional shallow-water
equations: lateral momentum, free-surface changes and turbulence are absent.
"""

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve


@dataclass(frozen=True)
class MomentumPilot:
    chainages_m: np.ndarray
    lateral_fraction: np.ndarray
    x: np.ndarray
    y: np.ndarray
    depth_m: np.ndarray
    longitudinal_m_s: np.ndarray
    section_flow_m3_s: np.ndarray
    lane_lap_min: tuple[float, float, float]
    flow_residual_fraction: float
    momentum_residual_m_s2: float


def compute_momentum_pilot(stations: Sequence[dict], plan, depth_m: float,
                           scale_m_per_unit: float = 1.0, beach_geometry=None,
                           beach_bank: str = "Exterior", eddy_viscosity_m2_s: float = 0.08,
                           jet_acceleration_m_s2: float = 0.002,
                           jet_spread_m: float = 12.0,
                           beach_first_share: float = 1 / 3,
                           longitudinal_cells: int = 96,
                           lateral_cells: int = 13) -> MomentumPilot:
    """Run one bounded scenario with the plan's Q; do not infer a new pump Q.

    Jet acceleration, spread and lateral eddy viscosity are user hypotheses,
    not manufacturer properties. The bathymetry is rescaled per section to
    preserve the existing plan area/volume, including the assumed beach.
    """
    if (depth_m <= 0 or scale_m_per_unit <= 0 or eddy_viscosity_m2_s <= 0 or
            jet_acceleration_m_s2 < 0 or jet_spread_m <= 0 or
            longitudinal_cells < 32 or lateral_cells < 5 or
            beach_bank not in ("Interior", "Exterior") or
            not 0 < beach_first_share < 1):
        raise ValueError("Parámetros de malla o del piloto 2D inválidos.")
    source_s = np.asarray([float(p["chainage_m"]) for p in stations])
    if len(source_s) < 2 or np.any(np.diff(source_s) <= 0):
        raise ValueError("Las estaciones del DXF deben estar ordenadas.")
    length = source_s[-1]
    ns, ny = longitudinal_cells, lateral_cells
    ds = length / ns
    eta = (np.arange(ny) + 0.5) / ny
    s = (np.arange(ns) + 0.5) * ds
    widths = np.interp(s, source_s, [float(p["width_m"]) for p in stations])
    areas = np.interp(s, source_s, plan.station_areas_m2)
    manning = np.interp(s, source_s, plan.station_manning_n)
    if np.any(widths <= 0) or np.any(areas <= 0) or np.any(manning <= 0):
        raise ValueError("Área, ancho y Manning deben ser positivos.")
    q = plan.equivalent_channel_flow_m3_h / 3600
    if q <= 0:
        raise ValueError("El caudal de escenario debe ser positivo.")
    center_x = np.interp(s, source_s, [float(p["x"]) for p in stations])
    center_y = np.interp(s, source_s, [float(p["y"]) for p in stations])
    normal_x = np.interp(s, source_s, [float(p["normal_x"]) for p in stations])
    normal_y = np.interp(s, source_s, [float(p["normal_y"]) for p in stations])
    normal_size = np.hypot(normal_x, normal_y)
    normal_x, normal_y = normal_x / normal_size, normal_y / normal_size
    x = center_x[:, None] + normal_x[:, None] * widths[:, None] * (eta - 0.5) / scale_m_per_unit
    y = center_y[:, None] + normal_y[:, None] * widths[:, None] * (eta - 0.5) / scale_m_per_unit

    depths = np.broadcast_to((areas / widths)[:, None], (ns, ny)).copy()
    if beach_geometry is not None:
        reference = beach_geometry.channel_reference_width_m
        extra = np.maximum(0.0, widths - reference)
        # The DXF has no submerged beach edge; this single-bank profile is an
        # assumption. eta=0 is the interior bank in either traversal direction.
        if beach_geometry.beach_start_m <= beach_geometry.beach_end_m:
            in_beach = ((s >= beach_geometry.beach_start_m) &
                        (s <= beach_geometry.beach_end_m))
        else:
            in_beach = ((s >= beach_geometry.beach_start_m) |
                        (s <= beach_geometry.beach_end_m))
        active = (in_beach & (extra > 0))[:, None]
        flat_entry = getattr(beach_geometry, "flat_entry_width_m", None)
        if flat_entry is None:
            distance_from_beach = (eta if beach_bank == "Interior" else 1 - eta)[None, :] * widths[:, None]
            slope_distance = np.maximum(0.0, extra[:, None] - distance_from_beach)
            first_length = extra[:, None] * beach_first_share
            rise = (np.minimum(slope_distance, first_length) * beach_geometry.first_slope +
                    np.maximum(0.0, slope_distance - first_length) * beach_geometry.ramp_slope)
            profile = np.where(active, np.maximum(0.08, depth_m - rise), depth_m)
        else:
            distance_from_deep_bank = ((eta if beach_bank == "Exterior" else 1 - eta)[None, :]
                                       * widths[:, None])
            rise = np.maximum(0.0, distance_from_deep_bank - flat_entry) * beach_geometry.ramp_slope
            profile = np.where(active, np.maximum(0.0, depth_m - rise), depth_m)
        depths = profile * (areas / (widths * profile.mean(axis=1)))[:, None]

    weights = depths * widths[:, None] / ny
    base_u = q / areas
    # Local depth increases bed friction toward the proposed beach. This is
    # only a depth-averaged closure, not a wall-resolved turbulence model.
    drag = (2 * 9.81 * manning[:, None] ** 2 * base_u[:, None] /
            np.maximum(depths, 0.08) ** (4 / 3))
    source = np.zeros((ns, ny))
    bank_eta = 0.85 if beach_bank == "Interior" else 0.15
    for position, angle in zip(plan.module_chainages_m, plan.module_angles_deg):
        distance = np.minimum(np.abs(s - position), length - np.abs(s - position))
        along = np.exp(-0.5 * (distance / jet_spread_m) ** 2)
        across = np.exp(-0.5 * ((eta - bank_eta) / 0.14) ** 2)
        source += jet_acceleration_m_s2 * max(0.0, np.cos(np.deg2rad(angle))) * along[:, None] * across[None, :]

    # Unknowns are section/lane perturbations and one pressure correction per
    # section. The latter closes the flow constraint without silently changing Q.
    count = ns * ny
    system = lil_matrix((count + ns, count + ns), dtype=float)
    rhs = np.zeros(count + ns)
    for i in range(ns):
        dy = widths[i] / ny
        diffusion = eddy_viscosity_m2_s / dy ** 2
        advection = base_u[i] / ds
        for j in range(ny):
            row = i * ny + j
            system[row, row] = advection + drag[i, j] + diffusion * (1 if j in (0, ny - 1) else 2)
            system[row, ((i - 1) % ns) * ny + j] = -advection
            if j > 0:
                system[row, row - 1] = -diffusion
            if j < ny - 1:
                system[row, row + 1] = -diffusion
            system[row, count + i] = 1
            system[count + i, row] = weights[i, j]
            rhs[row] = source[i, j]
    solution = spsolve(system.tocsr(), rhs)
    perturbation = solution[:count].reshape(ns, ny)
    velocity = base_u[:, None] + perturbation
    if not np.all(np.isfinite(velocity)):
        raise ValueError("El piloto no produjo velocidades finitas.")
    flow = np.sum(weights * velocity, axis=1)
    flow_residual = float(np.max(np.abs(flow - q)) / q)
    momentum_residual = float(np.max(np.abs(system.tocsr() @ solution - rhs)))

    laps = []
    for fraction in (0.2, 0.5, 0.8):
        lane = int(round(fraction * (ny - 1)))
        if np.any(velocity[:, lane] <= 0):
            laps.append(float("inf"))
        else:
            laps.append(float(np.sum(ds / velocity[:, lane]) / 60))
    return MomentumPilot(s, eta, x, y, depths, velocity, flow, tuple(laps),
                         flow_residual, momentum_residual)
