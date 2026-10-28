"""Exploratory depth-averaged 2D flow on the NYA DXF footprint.

Finite-volume-like Cartesian projection with a rigid lid, prescribed pump
intake/return flow, hypothetical effective jet momentum, bed drag and lateral
eddy viscosity. This is NOT a validated Riverflow CFD model or a purchase tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians, sin

import numpy as np
from scipy.sparse import coo_matrix, lil_matrix
from scipy.sparse.linalg import splu
from scipy.spatial import cKDTree
from shapely import affinity, contains_xy

from core.riverflow_jet_momentum import NOZZLE_12X7_OPEN_AREA_M2
from experiments.riverflow_layout_metrics import LayoutSite
from experiments.splishsplash_nya_pilot.full_loop_2d import (
    TrialInputs, load_nya, section_geometry, solve_case,
)

G = 9.81


@dataclass(frozen=True)
class Flow2DInputs:
    cell_m: float = 2.0
    dt_s: float = 0.25
    steps: int = 1200
    momentum_fraction: float = 0.10  # unresolved coupling; NOT a measured Riverflow efficiency
    eddy_viscosity_m2_s: float = 0.08  # uncalibrated depth-averaged mixing
    floor_manning_n: float = 0.013
    wall_manning_n: float = 0.025
    nozzle_angle_deg: float = 0.0  # positive rotates jet toward inner bank (left)
    count: int = 20
    length_m: float = 536.0
    depth_m: float = 1.2
    beach_flat_width_m: float = 16.0
    beach_ramp_slope: float = 0.065
    pump_flow_each_m3_h: float | None = None
    moved_pump_index: int | None = None
    moved_chainage_m: float | None = None
    moved_bank: str | None = None
    site_overrides: tuple[tuple[int, float, str], ...] = ()
    # Local VFD sensitivity only: Q and nozzle speed scale with rotational speed
    # for the reference H∝Q² circuit. NYA's installed system curve is unknown.
    pump_speed_overrides: tuple[tuple[int, float], ...] = ()

    def validate(self) -> None:
        if (not all(np.isfinite(v) for v in (self.length_m, self.depth_m,
                self.beach_flat_width_m, self.beach_ramp_slope)) or
                self.length_m <= 0 or self.depth_m <= 0 or
                self.beach_flat_width_m <= 0 or not 0 < self.beach_ramp_slope < .2):
            raise ValueError("Longitud, profundidad y perfil de playa inválidos.")
        if (self.pump_flow_each_m3_h is not None and
                (not np.isfinite(self.pump_flow_each_m3_h) or
                 self.pump_flow_each_m3_h <= 0)):
            raise ValueError("El caudal local por bomba debe ser positivo.")
        if not 0.75 <= self.cell_m <= 4 or not 0 < self.dt_s <= 1:
            raise ValueError("Celda o paso temporal fuera del ensayo.")
        if not 1 <= self.steps <= 10000 or not 0 < self.momentum_fraction <= 1:
            raise ValueError("Pasos o fracción de momento inválidos.")
        if not 0 < self.eddy_viscosity_m2_s <= 1 or not -45 <= self.nozzle_angle_deg <= 45:
            raise ValueError("Mezcla o ángulo fuera del ensayo.")
        if not 0 < self.floor_manning_n <= .1 or not 0 < self.wall_manning_n <= .1:
            raise ValueError("Rugosidad de piso o paredes fuera del ensayo.")
        if not 1 <= self.count <= 50:
            raise ValueError("Cantidad de bombas inválida.")
        if self.moved_pump_index is not None:
            if not 0 <= self.moved_pump_index < self.count:
                raise ValueError("Índice de bomba inválido.")
            if self.moved_chainage_m is None or not 0 <= self.moved_chainage_m < self.length_m:
                raise ValueError("Progresiva de bomba inválida.")
            if self.moved_bank not in ("Interior", "Exterior"):
                raise ValueError("Orilla inválida.")
        indices = [site[0] for site in self.site_overrides]
        if len(indices) != len(set(indices)) or self.moved_pump_index in indices:
            raise ValueError("Una bomba no puede tener dos posiciones nuevas.")
        for index, chainage, bank in self.site_overrides:
            if not 0 <= index < self.count or not 0 <= chainage < self.length_m or bank not in ("Interior", "Exterior"):
                raise ValueError("Ubicación de bomba inválida.")
        speed_indices = [index for index, _ in self.pump_speed_overrides]
        if len(speed_indices) != len(set(speed_indices)):
            raise ValueError("Una bomba no puede tener dos ajustes de variador.")
        for index, fraction in self.pump_speed_overrides:
            if not 0 <= index < self.count or not np.isfinite(fraction) or not 0 < fraction <= 1:
                raise ValueError("Ajuste de variador por bomba inválido.")


def _stations_at(model, s_values: np.ndarray) -> dict[str, np.ndarray]:
    stations = model.stations
    s = np.asarray([float(p["chainage_m"]) for p in stations])
    scale = float(model.geometry.scale_m_per_unit)
    out = {}
    for name, key in (("x", "x"), ("y", "y"), ("nx", "normal_x"),
                      ("ny", "normal_y"), ("width", "width_m")):
        out[name] = np.interp(s_values, s, [float(p[key]) for p in stations])
    out["x"] *= scale
    out["y"] *= scale
    norm = np.hypot(out["nx"], out["ny"])
    out["nx"] /= norm
    out["ny"] /= norm
    return out


def build_geometry(model, beach_indices, cell_m: float,
                   floor_manning_n: float = .013,
                   wall_manning_n: float = .025,
                   depth_m: float = 1.2,
                   beach_flat_width_m: float = 16.0,
                   beach_ramp_slope: float = .065) -> dict:
    scale = float(model.geometry.scale_m_per_unit)
    polygon = affinity.scale(model.loader.domain_polygon, xfact=scale,
                             yfact=scale, origin=(0, 0))
    minx, miny, maxx, maxy = polygon.bounds
    x = np.arange(minx - cell_m, maxx + 2 * cell_m, cell_m)
    y = np.arange(miny - cell_m, maxy + 2 * cell_m, cell_m)
    xx, yy = np.meshgrid(x, y)
    wet = contains_xy(polygon, xx, yy)
    if wet.sum() < 500:
        raise ValueError("La malla no resuelve suficientemente el canal.")
    source = _stations_at(model, np.asarray(
        [float(p["chainage_m"]) for p in model.stations]))
    station_xy = np.c_[source["x"], source["y"]]
    nearest = cKDTree(station_xy).query(np.c_[xx[wet], yy[wet]])[1]
    beach_set = np.zeros(len(model.stations), dtype=bool)
    beach_set[list(beach_indices)] = True
    dxp = xx[wet] - source["x"][nearest]
    dyp = yy[wet] - source["y"][nearest]
    lateral = dxp * source["nx"][nearest] + dyp * source["ny"][nearest]
    from_inner = lateral + source["width"][nearest] / 2
    depth_values = np.full(len(nearest), depth_m)
    ramp = beach_set[nearest] & (from_inner > beach_flat_width_m)
    depth_values[ramp] = np.maximum(.05, depth_m - beach_ramp_slope *
                                    (from_inner[ramp] - beach_flat_width_m))
    depth = np.zeros_like(xx)
    depth[wet] = depth_values
    chain = np.full_like(xx, np.nan)
    chain[wet] = [float(model.stations[k]["chainage_m"]) for k in nearest]
    tangent_x = np.zeros_like(xx)
    tangent_y = np.zeros_like(xx)
    tangent_x[wet] = -source["ny"][nearest]
    tangent_y[wet] = source["nx"][nearest]
    # Use the same wetted cross-section and composite floor/wall Manning
    # resistance as the 1D reference. This is a depth-averaged wall-drag
    # approximation, not a resolved near-wall boundary layer.
    section = section_geometry(model.stations, beach_indices,
                               TrialInputs(depth_m=depth_m,
                                           beach_flat_width_m=beach_flat_width_m,
                                           beach_ramp_slope=beach_ramp_slope,
                                           floor_manning_n=floor_manning_n,
                                           wall_manning_n=wall_manning_n))
    radius = np.zeros_like(xx)
    radius[wet] = (section["area"][nearest] /
                   section["perimeter"][nearest])
    manning = np.zeros_like(xx)
    manning[wet] = section["manning"][nearest]
    return {"x": x, "y": y, "wet": wet, "depth": depth,
            "chainage": chain, "tangent_x": tangent_x,
            "tangent_y": tangent_y, "polygon": polygon,
            "hydraulic_radius": radius, "effective_manning": manning}


def _poisson_matrix(wet: np.ndarray, depth: np.ndarray, cell_m: float):
    ny, nx = wet.shape
    ids = np.full((ny, nx), -1, dtype=int)
    ids[wet] = np.arange(int(wet.sum()))
    rows, cols, vals = [], [], []
    for j, i in zip(*np.nonzero(wet)):
        k = ids[j, i]
        diag = 0.0
        for dj, di in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            jj, ii = j + dj, i + di
            if 0 <= jj < ny and 0 <= ii < nx and wet[jj, ii]:
                a = (depth[j, i] + depth[jj, ii]) / (2 * cell_m ** 2)
                rows.append(k); cols.append(ids[jj, ii]); vals.append(-a)
                diag += a
        rows.append(k); cols.append(k); vals.append(diag)
    matrix = coo_matrix((vals, (rows, cols)), shape=(int(wet.sum()),) * 2).tolil()
    # The closed channel has arbitrary pressure datum. Removing one equation
    # preserves all other cell balances; the omitted balance follows from
    # zero net mass source and no-flux outer boundary.
    matrix[0, :] = 0
    matrix[0, 0] = 1
    return ids, splu(matrix.tocsc())


def _distribute(grid: dict, x0: float, y0: float, radius: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    wet = grid["wet"]
    xx, yy = np.meshgrid(grid["x"], grid["y"])
    d2 = (xx - x0) ** 2 + (yy - y0) ** 2
    chosen = wet & (d2 <= radius ** 2)
    if not chosen.any():
        chosen[np.unravel_index(np.where(wet, d2, np.inf).argmin(), wet.shape)] = True
    j, i = np.nonzero(chosen)
    weights = np.exp(-d2[j, i] / max(radius ** 2, .1))
    weights /= weights.sum()
    return j, i, weights


def _sources(model, grid: dict, pump_sites: list[dict], q_each: float,
             nozzle_speed: float, settings: Flow2DInputs):
    source = np.zeros_like(grid["depth"])
    fx = np.zeros_like(source)
    fy = np.zeros_like(source)
    area = settings.cell_m ** 2
    speeds = dict(settings.pump_speed_overrides)
    for index, pump in enumerate(pump_sites):
        speed_fraction = speeds.get(index, 1.0)
        # Affinity-law sensitivity for the reference local circuit; each pump
        # removes and returns its own flow, so a VFD change preserves mass.
        pump_q = q_each * speed_fraction
        pump_nozzle_speed = nozzle_speed * speed_fraction
        for kind, s, fraction in (("out", pump["chainage_m"], 1.0),
                                  ("in", pump["intake_chainage_m"] - 1.0, -.5),
                                  ("in", pump["intake_chainage_m"] + 1.0, -.5)):
            s = s % model.geometry.channel_length_m
            point = _stations_at(model, np.array([s]))
            sign = -1 if pump["bank"] == "Interior" else 1
            offset = max(0.5, point["width"][0] / 2 - 1.0)
            px = point["x"][0] + sign * point["nx"][0] * offset
            py = point["y"][0] + sign * point["ny"][0] * offset
            j, i, weight = _distribute(grid, px, py, settings.cell_m * 1.6)
            source[j, i] += pump_q * fraction * weight / area
            if kind == "out":
                # Station normal is right of travel. A positive angle rotates
                # the tangent left, toward the channel's inner bank.
                tx, ty = -point["ny"][0], point["nx"][0]
                angle = radians(settings.nozzle_angle_deg)
                jx = cos(angle) * tx - sin(angle) * ty
                jy = sin(angle) * tx + cos(angle) * ty
                impulse = settings.momentum_fraction * pump_q * pump_nozzle_speed
                accel = impulse * weight / (area * grid["depth"][j, i])
                fx[j, i] += accel * jx
                fy[j, i] += accel * jy
    if abs(source.sum() * area) > 1e-10:
        raise AssertionError("Tomas y descargas no conservan caudal.")
    return source, fx, fy


def _neighbors(values: np.ndarray, wet: np.ndarray):
    # Ghost values at solid cells enforce zero velocity at the banks.
    left = np.zeros_like(values); left[:, 1:] = values[:, :-1]
    right = np.zeros_like(values); right[:, :-1] = values[:, 1:]
    down = np.zeros_like(values); down[1:, :] = values[:-1, :]
    up = np.zeros_like(values); up[:-1, :] = values[1:, :]
    return left, right, down, up


def solve(settings: Flow2DInputs, *, model=None, beach=None) -> dict:
    settings.validate()
    if model is None or beach is None:
        model, beach = load_nya()
    if abs(model.geometry.channel_length_m - settings.length_m) > .05:
        raise ValueError("La longitud del ensayo 2D no coincide con el DXF activo.")
    reference = solve_case(model, beach,
                           TrialInputs(depth_m=settings.depth_m,
                                       beach_flat_width_m=settings.beach_flat_width_m,
                                       beach_ramp_slope=settings.beach_ramp_slope,
                                       floor_manning_n=settings.floor_manning_n,
                                       wall_manning_n=settings.wall_manning_n),
                           settings.count)
    if settings.pump_flow_each_m3_h is not None:
        # The saved 1D reference still supplies only the proposed sites. The
        # active app's local CF104 point drives the 2D intake/jet sources.
        reference = dict(reference)
        reference["pump_flow_each_m3_h"] = settings.pump_flow_each_m3_h
        reference["aggregate_nozzle_exit_speed_m_s"] = (
            settings.pump_flow_each_m3_h / 3600 / NOZZLE_12X7_OPEN_AREA_M2)
    sites = [dict(p) for p in reference["pump_sites"]]
    moves = list(settings.site_overrides)
    if settings.moved_pump_index is not None:
        moves.append((settings.moved_pump_index, settings.moved_chainage_m,
                      settings.moved_bank))
    for index, chainage, bank in moves:
        p = sites[index]
        p["chainage_m"] = chainage
        p["intake_chainage_m"] = (chainage - 5) % settings.length_m
        p["bank"] = bank
    grid = build_geometry(model, beach, settings.cell_m,
                          settings.floor_manning_n,
                          settings.wall_manning_n, settings.depth_m,
                          settings.beach_flat_width_m, settings.beach_ramp_slope)
    wet, h = grid["wet"], grid["depth"]
    ny, nx = wet.shape
    ids, pressure_solve = _poisson_matrix(wet, h, settings.cell_m)
    src, jet_ax, jet_ay = _sources(model, grid, sites,
                                  reference["pump_flow_each_m3_h"] / 3600,
                                  reference["aggregate_nozzle_exit_speed_m_s"],
                                  settings)
    # Positive x/y face fluxes, zero on solid edges.
    hx = np.zeros((ny, nx + 1)); hy = np.zeros((ny + 1, nx))
    valid_x = wet[:, :-1] & wet[:, 1:]
    valid_y = wet[:-1, :] & wet[1:, :]
    hx[:, 1:-1][valid_x] = (h[:, :-1][valid_x] + h[:, 1:][valid_x]) / 2
    hy[1:-1, :][valid_y] = (h[:-1, :][valid_y] + h[1:, :][valid_y]) / 2
    u = np.zeros_like(hx); v = np.zeros_like(hy)
    d = settings.cell_m
    history = []
    for step in range(settings.steps):
        uc = (u[:, :-1] + u[:, 1:]) / 2
        vc = (v[:-1, :] + v[1:, :]) / 2
        speed = np.hypot(uc, vc)
        drag = np.zeros_like(h)
        drag[wet] = (G * grid["effective_manning"][wet] ** 2 * speed[wet] /
                     grid["hydraulic_radius"][wet] ** (4 / 3))
        ul, ur, ud, uu = _neighbors(uc, wet)
        vl, vr, vd, vu = _neighbors(vc, wet)
        lap_u = (ul + ur + ud + uu - 4 * uc) / d ** 2
        lap_v = (vl + vr + vd + vu - 4 * vc) / d ** 2
        dudx = np.where(uc >= 0, (uc - ul) / d, (ur - uc) / d)
        dudy = np.where(vc >= 0, (uc - ud) / d, (uu - uc) / d)
        dvdx = np.where(uc >= 0, (vc - vl) / d, (vr - vc) / d)
        dvdy = np.where(vc >= 0, (vc - vd) / d, (vu - vc) / d)
        accel_u = jet_ax - uc * dudx - vc * dudy + settings.eddy_viscosity_m2_s * lap_u - drag * uc
        accel_v = jet_ay - uc * dvdx - vc * dvdy + settings.eddy_viscosity_m2_s * lap_v - drag * vc
        if not np.isfinite(accel_u[wet]).all() or not np.isfinite(accel_v[wet]).all():
            raise ValueError("El esquema 2D se volvió inestable.")
        # Update the face velocities in place. Reconstructing the faces from
        # cell-centered averages each step would create enormous artificial
        # diffusion and incorrectly suppress circulation in this closed loop.
        u[:, 1:-1] += settings.dt_s * np.where(
            valid_x, (accel_u[:, :-1] + accel_u[:, 1:]) / 2, 0)
        v[1:-1, :] += settings.dt_s * np.where(
            valid_y, (accel_v[:-1, :] + accel_v[1:, :]) / 2, 0)
        div = ((hx[:, 1:] * u[:, 1:] - hx[:, :-1] * u[:, :-1]) +
               (hy[1:, :] * v[1:, :] - hy[:-1, :] * v[:-1, :])) / d
        rhs = (src[wet] - div[wet]) / settings.dt_s
        rhs[0] = 0
        p = np.zeros_like(h)
        p[wet] = pressure_solve.solve(rhs)
        u[:, 1:-1][valid_x] -= settings.dt_s * (p[:, 1:][valid_x] -
                                                  p[:, :-1][valid_x]) / d
        v[1:-1, :][valid_y] -= settings.dt_s * (p[1:, :][valid_y] -
                                                  p[:-1, :][valid_y]) / d
        if step % 100 == 0 or step == settings.steps - 1:
            residual = ((hx[:, 1:] * u[:, 1:] - hx[:, :-1] * u[:, :-1]) +
                        (hy[1:, :] * v[1:, :] - hy[:-1, :] * v[:-1, :])) / d - src
            center_speed = np.hypot((u[:, :-1] + u[:, 1:]) / 2,
                                    (v[:-1, :] + v[1:, :]) / 2)
            history.append({"step": step + 1, "max_mass_residual_m_s":
                            float(np.max(np.abs(residual[wet]))),
                            "max_speed_m_s": float(np.max(center_speed[wet])),
                            "mean_speed_m_s": float(np.mean(center_speed[wet]))})
            if history[-1]["max_speed_m_s"] > 8:
                raise ValueError("Velocidad numérica inestable (>8 m/s).")
    uc = (u[:, :-1] + u[:, 1:]) / 2
    vc = (v[:-1, :] + v[1:, :]) / 2
    along = uc * grid["tangent_x"] + vc * grid["tangent_y"]
    return {"settings": settings, "grid": grid, "u": uc, "v": vc,
            "source": src, "pump_sites": sites, "history": history,
            "reference": reference,
            "diagnostics": {"wet_cells": int(wet.sum()),
                            "total_local_pump_flow_m3_h": float(
                                reference["pump_flow_each_m3_h"] * sum(
                                    dict(settings.pump_speed_overrides).get(i, 1.0)
                                    for i in range(settings.count))),
                            "volume_m3_raster": float(np.sum(h[wet]) * d ** 2),
                            "net_pump_source_m3_s": float(src.sum() * d ** 2),
                            "mass_error_max_m3_s_per_cell":
                            history[-1]["max_mass_residual_m_s"] * d ** 2,
                            "max_speed_m_s": history[-1]["max_speed_m_s"],
                            "mean_speed_m_s": history[-1]["mean_speed_m_s"],
                            "mean_along_channel_m_s": float(np.mean(along[wet])),
                            "area_fraction_reverse_flow": float(np.mean(along[wet] < -.005))}}
