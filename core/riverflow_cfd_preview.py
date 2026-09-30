"""Local-only, experimental depth-averaged 2D shallow-water preview.

This explicit finite-volume-like staggered-grid experiment conserves water in
the rasterized closed DXF domain. It is deliberately NOT a validated CFD
design: intakes, nozzle geometry, lateral bathymetry and turbulence are unknown.
"""

from dataclasses import dataclass
from math import ceil, sqrt

import numpy as np
from scipy.spatial import cKDTree
from shapely import contains_xy


@dataclass(frozen=True)
class CFDPreview:
    x_dxf: np.ndarray
    y_dxf: np.ndarray
    wet: np.ndarray
    depth_m: np.ndarray
    speed_m_s: np.ndarray
    along_m_s: np.ndarray
    surface_change_m: np.ndarray
    module_x_dxf: np.ndarray
    module_y_dxf: np.ndarray
    duration_s: float
    water_balance_error_m3: float
    max_courant: float
    wet_cell_count: int


def compute_cfd_preview(model, plan, *, cell_m=2.5, duration_s=120.0,
                        impulse_fraction=0.1, mixing_m2_s=0.12):
    """Run a short transient from still water; no assumed 2% energy transfer.

    Pump thrust is an ideal Q*sqrt(2*g*H) times an explicitly editable
    momentum-coupling fraction. Localized forcing is not a nozzle simulation.
    """
    if not (1.5 <= cell_m <= 5 and 10 <= duration_s <= 600 and
            0 <= impulse_fraction <= 1 and 0 <= mixing_m2_s <= 1):
        raise ValueError("Resolución, duración o hipótesis de impulso fuera de rango.")
    if model.loader.domain_polygon is None:
        raise ValueError("Se necesita el contorno cerrado del DXF.")
    scale = model.geometry.scale_m_per_unit
    dx_dxf = cell_m / scale
    xmin, ymin, xmax, ymax = model.loader.domain_polygon.bounds
    nx = ceil((xmax - xmin) / dx_dxf)
    ny = ceil((ymax - ymin) / dx_dxf)
    if nx * ny > 40000:
        raise ValueError("La malla excede el límite de esta prueba local.")
    x = xmin + (np.arange(nx) + .5) * dx_dxf
    y = ymin + (np.arange(ny) + .5) * dx_dxf
    xx, yy = np.meshgrid(x, y)
    wet = contains_xy(model.loader.domain_polygon, xx, yy)
    if np.count_nonzero(wet) < 50:
        raise ValueError("La malla es demasiado gruesa para el canal del DXF.")

    stations = model.stations
    centers = np.array([(p["x"], p["y"]) for p in stations])
    nearest = cKDTree(centers).query(np.c_[xx.ravel(), yy.ravel()])[1].reshape(ny, nx)
    widths = np.asarray([p["width_m"] for p in stations], dtype=float)
    station_depth = np.asarray(plan.station_areas_m2) / widths
    depth = np.clip(station_depth[nearest], .15, 3.0)
    roughness = np.asarray(plan.station_manning_n)[nearest]
    tangent_x = np.asarray([p["tangent_x"] for p in stations])[nearest]
    tangent_y = np.asarray([p["tangent_y"] for p in stations])[nearest]
    face_x = wet[:, :-1] & wet[:, 1:]
    face_y = wet[:-1, :] & wet[1:, :]
    hx = (depth[:, :-1] + depth[:, 1:]) / 2
    hy = (depth[:-1, :] + depth[1:, :]) / 2
    nx_rough = (roughness[:, :-1] + roughness[:, 1:]) / 2
    ny_rough = (roughness[:-1, :] + roughness[1:, :]) / 2
    fx_cell = np.zeros((ny, nx))
    fy_cell = np.zeros((ny, nx))
    mx, my = [], []
    operating_head_m = plan.module_head_full_speed_ft * .3048 * plan.speed_fraction ** 2
    q_module = plan.module_flow_full_speed_m3_h * plan.speed_fraction / 3600
    ideal_speed = sqrt(2 * 9.81 * operating_head_m)
    source_radius = max(5.0, 2 * cell_m)
    station_s = np.array([p["chainage_m"] for p in stations])
    for chainage, angle in zip(plan.module_chainages_m, plan.module_angles_deg):
        j = int(np.argmin(abs(station_s - chainage)))
        station = stations[j]
        px = station["x"] + .18 * station["width_m"] * station["normal_x"] / scale
        py = station["y"] + .18 * station["width_m"] * station["normal_y"] / scale
        radius2 = ((xx - px) * scale) ** 2 + ((yy - py) * scale) ** 2
        weight = np.exp(-radius2 / (2 * source_radius ** 2)) * wet
        if weight.sum() <= 0:
            continue
        weight /= weight.sum()
        theta = np.deg2rad(angle)
        direction_x = station["tangent_x"] * np.cos(theta) + station["normal_x"] * np.sin(theta)
        direction_y = station["tangent_y"] * np.cos(theta) + station["normal_y"] * np.sin(theta)
        acceleration = impulse_fraction * q_module * ideal_speed * weight / (depth * cell_m ** 2)
        fx_cell += acceleration * direction_x
        fy_cell += acceleration * direction_y
        mx.append(px)
        my.append(py)

    fx = (fx_cell[:, :-1] + fx_cell[:, 1:]) / 2 * face_x
    fy = (fy_cell[:-1, :] + fy_cell[1:, :]) / 2 * face_y
    u = np.zeros((ny, nx + 1))
    v = np.zeros((ny + 1, nx))
    surface = np.zeros((ny, nx))
    max_courant = 0.0
    elapsed = 0.0
    # The explicit gravity-wave CFL is deliberately conservative. This is a
    # short transient visualization, not a converged operating-point solution.
    base_dt = min(.3, .3 * cell_m / sqrt(2 * 9.81 * float(depth[wet].max())))
    steps = ceil(duration_s / base_dt)
    dt = duration_s / steps
    for _ in range(steps):
        center_u = (u[:, :-1] + u[:, 1:]) / 2
        center_v = (v[:-1, :] + v[1:, :]) / 2
        across_u = (center_v[:, :-1] + center_v[:, 1:]) / 2
        across_v = (center_u[:-1, :] + center_u[1:, :]) / 2
        du_dy, du_dx = np.gradient(u, cell_m)
        dv_dy, dv_dx = np.gradient(v, cell_m)
        u_mid = u[:, 1:-1]
        v_mid = v[1:-1, :]
        adv_u = u_mid * du_dx[:, 1:-1] + across_u * du_dy[:, 1:-1]
        adv_v = across_v * dv_dx[1:-1, :] + v_mid * dv_dy[1:-1, :]
        lap_u = ((u[:, 2:] + u[:, :-2] - 2 * u_mid) / cell_m ** 2 +
                 (np.pad(u_mid[1:], ((0, 1), (0, 0))) +
                  np.pad(u_mid[:-1], ((1, 0), (0, 0))) - 2 * u_mid) / cell_m ** 2)
        lap_v = ((v[2:, :] + v[:-2, :] - 2 * v_mid) / cell_m ** 2 +
                 (np.pad(v_mid[:, 1:], ((0, 0), (0, 1))) +
                  np.pad(v_mid[:, :-1], ((0, 0), (1, 0))) - 2 * v_mid) / cell_m ** 2)
        u[:, 1:-1] = np.where(face_x, u_mid + dt * (
            -9.81 * (surface[:, 1:] - surface[:, :-1]) / cell_m
            - adv_u - 9.81 * nx_rough ** 2 * np.hypot(u_mid, across_u) * u_mid /
            hx ** (4 / 3) + mixing_m2_s * lap_u + fx), 0)
        v[1:-1, :] = np.where(face_y, v_mid + dt * (
            -9.81 * (surface[1:, :] - surface[:-1, :]) / cell_m
            - adv_v - 9.81 * ny_rough ** 2 * np.hypot(v_mid, across_v) * v_mid /
            hy ** (4 / 3) + mixing_m2_s * lap_v + fy), 0)
        flux_x = np.zeros_like(u)
        flux_y = np.zeros_like(v)
        flux_x[:, 1:-1] = hx * u[:, 1:-1]
        flux_y[1:-1, :] = hy * v[1:-1, :]
        surface[wet] -= dt * ((flux_x[:, 1:] - flux_x[:, :-1] +
                                flux_y[1:, :] - flux_y[:-1, :]) / cell_m)[wet]
        elapsed += dt
        courant = dt * (sqrt(2 * 9.81 * float(depth[wet].max())) +
                        max(float(np.max(abs(u))), float(np.max(abs(v))))) / cell_m
        max_courant = max(max_courant, courant)
        if not np.isfinite(courant) or courant > .9:
            raise ValueError("La simulación se volvió inestable; pruebe menor impulso o malla más gruesa.")

    center_u = (u[:, :-1] + u[:, 1:]) / 2
    center_v = (v[:-1, :] + v[1:, :]) / 2
    speed = np.hypot(center_u, center_v)
    along = center_u * tangent_x + center_v * tangent_y
    return CFDPreview(x, y, wet, depth, speed, along, surface,
                      np.asarray(mx), np.asarray(my), elapsed,
                      abs(float(np.sum(surface[wet]) * cell_m ** 2)),
                      max_courant, int(np.count_nonzero(wet)))
