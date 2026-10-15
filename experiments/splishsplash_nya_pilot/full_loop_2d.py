"""Mass-balanced 536 m NYA screening model, separate from the public app.

The channel flow is a *specified kinematic target*, not a prediction that
Riverflow equipment will achieve it. Pump intake/return pairs conserve mass;
Manning drag and documented aggregate pump/nozzle momentum determine the
required, still-unmeasured longitudinal transfer fraction. This 1D balance
is drawn over a 2D DXF footprint; it does not compute across-channel eddies.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from math import hypot, isfinite, sqrt
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from core.orchestrator import LazyRiverModel
from core.centerline import rotate_closed_stations
from core.beach_geometry import compute_beach_geometry
from core.riverflow_placement import curve_candidates
from experiments.riverflow_layout_metrics import (
    LayoutSite, classify_beach_core, wide_passage_runs, zone_aware_sites,
)
from experiments.splishsplash_nya_pilot.pump_coupling import (
    solve_reference_coupling,
)

USER_ACCESS_POINT_M = (2389.2, 1450.3)  # marked image, approximate
RHO = 998.0
G = 9.81


@dataclass(frozen=True)
class TrialInputs:
    target_typical_speed_m_s: float = 0.275
    depth_m: float = 1.2
    beach_flat_width_m: float = 16.0
    beach_ramp_slope: float = 0.065
    floor_manning_n: float = 0.013
    wall_manning_n: float = 0.025
    intake_upstream_m: float = 5.0  # scenario, NOT drawn pipe length
    system_head_factor: float = 1.0  # reference-system sensitivity, NOT NYA TDH
    speed_fraction: float = 1.0
    cell_length_m: float = 1.0

    def validate(self) -> None:
        values = vars(self).values()
        if not all(isfinite(v) and v > 0 for v in values):
            raise ValueError("Todos los parámetros deben ser finitos y positivos.")
        if not 0 < self.speed_fraction <= 1 or not 0 < self.beach_ramp_slope < 0.2:
            raise ValueError("Variador o pendiente de playa fuera del ensayo.")
        if not self.intake_upstream_m < 30 or not 0.25 <= self.cell_length_m <= 5:
            raise ValueError("Separación toma-descarga o tamaño de celda fuera del ensayo.")


def load_nya() -> tuple[LazyRiverModel, tuple[int, ...]]:
    model = LazyRiverModel()
    errors = model.load_dxf(str(ROOT / "RECORRIDO.dxf"))
    if errors:
        raise ValueError("; ".join(map(str, errors)))
    model.build_centerline(target_length_m=536)
    scale = float(model.geometry.scale_m_per_unit)
    anchor = min(range(len(model.stations) - 1),
                 key=lambda i: hypot(model.stations[i]["x"] * scale - USER_ACCESS_POINT_M[0],
                                     model.stations[i]["y"] * scale - USER_ACCESS_POINT_M[1]))
    mismatch = hypot(model.stations[anchor]["x"] * scale - USER_ACCESS_POINT_M[0],
                     model.stations[anchor]["y"] * scale - USER_ACCESS_POINT_M[1])
    if mismatch > 5:
        raise ValueError("El punto de entrada/salida ya no coincide con este DXF.")
    model.stations = rotate_closed_stations(model.stations, anchor)
    # Only use the existing bay detector; the cross-sectional profile below
    # is explicit and never invents dry sand beyond the drawn boundary.
    beach = compute_beach_geometry(model.stations, depth_m=1.2)
    return model, beach.beach_indices


def section_geometry(stations: list[dict], beach_indices: tuple[int, ...],
                     inputs: TrialInputs) -> dict[str, np.ndarray]:
    area, perimeter, wet_width, manning = [], [], [], []
    beach_set = set(beach_indices)
    edge_depths = []
    for i, station in enumerate(stations):
        width = float(station["width_m"])
        if i in beach_set and width > inputs.beach_flat_width_m:
            flat = inputs.beach_flat_width_m
            ramp = min(width - flat, inputs.depth_m / inputs.beach_ramp_slope)
            edge_depth = max(0.0, inputs.depth_m -
                             inputs.beach_ramp_slope * (width - flat))
            a = inputs.depth_m * flat + inputs.depth_m * ramp - \
                inputs.beach_ramp_slope * ramp ** 2 / 2
            floor = flat + ramp * sqrt(1 + inputs.beach_ramp_slope ** 2)
            wall = inputs.depth_m + edge_depth
            wet = flat + ramp
        else:
            a = width * inputs.depth_m
            floor = width
            wall = 2 * inputs.depth_m
            wet = width
            edge_depth = inputs.depth_m
        p = floor + wall
        n = ((floor * inputs.floor_manning_n ** 1.5 +
              wall * inputs.wall_manning_n ** 1.5) / p) ** (2 / 3)
        area.append(a)
        perimeter.append(p)
        wet_width.append(wet)
        manning.append(n)
        if i in beach_set:
            edge_depths.append(edge_depth)
    # The final DXF station is the same section as station 0.
    for values in (area, perimeter, wet_width, manning):
        values[-1] = values[0]
    return {"area": np.asarray(area), "perimeter": np.asarray(perimeter),
            "wet_width": np.asarray(wet_width), "manning": np.asarray(manning),
            "beach_edge_depths": np.asarray(edge_depths)}


def mass_balanced_flux(cell_mid_m: np.ndarray, length_m: float,
                       pumps: tuple, pump_q_m3_s: float,
                       upstream_m: float) -> tuple[np.ndarray, float]:
    """Local pump bypass contribution with exactly equal take and return.

    Positive flux is downstream. Its zero-mean constant is chosen so that the
    separately specified bulk target means the *length-average* channel Q.
    """
    n = len(cell_mid_m)
    event = np.zeros(n, dtype=float)
    step = length_m / n
    for pump in pumps:
        discharge = float(pump.chainage_m) % length_m
        intake = (discharge - upstream_m) % length_m
        event[min(int(discharge / step), n - 1)] += pump_q_m3_s
        event[min(int(intake / step), n - 1)] -= pump_q_m3_s
    if not np.isclose(event.sum(), 0.0, atol=1e-10):
        raise AssertionError("La toma y descarga no conservan caudal.")
    local = np.cumsum(event)
    local -= local.mean()
    return local, float(event.sum())


def solve_case(model: LazyRiverModel, beach_indices: tuple[int, ...],
               inputs: TrialInputs, count: int,
               assumed_transfer_fraction: float | None = None,
               pump_sites_override: tuple[LayoutSite, ...] | None = None) -> dict:
    inputs.validate()
    if not 1 <= count <= 50:
        raise ValueError("Cantidad de bombas fuera del ensayo.")
    stations = model.stations
    length = float(stations[-1]["chainage_m"])
    ncell = round(length / inputs.cell_length_m)
    if ncell < 20:
        raise ValueError("La malla longitudinal es demasiado gruesa.")
    edges = np.linspace(0, length, ncell + 1)
    mid = (edges[:-1] + edges[1:]) / 2
    ds = length / ncell
    s_source = np.asarray([float(s["chainage_m"]) for s in stations])
    section = section_geometry(stations, beach_indices, inputs)
    area = np.interp(mid, s_source, section["area"])
    perimeter = np.interp(mid, s_source, section["perimeter"])
    wet_width = np.interp(mid, s_source, section["wet_width"])
    manning = np.interp(mid, s_source, section["manning"])
    width = np.interp(mid, s_source,
                      [float(s["width_m"]) for s in stations])
    beach_set = set(beach_indices)
    source_zone = classify_beach_core(stations, beach_indices, 15.0)
    zone = np.asarray([source_zone[min(np.searchsorted(s_source, x, side="right") - 1,
                                      len(source_zone) - 1)] for x in mid])
    wide_runs = wide_passage_runs(stations, source_zone, 15.0)
    curves = curve_candidates(stations, source_zone,
                              model.geometry.scale_m_per_unit)
    pumps = (zone_aware_sites(stations, source_zone, count, curves, wide_runs)
             if pump_sites_override is None else tuple(pump_sites_override))
    if len(pumps) != count or any(not isfinite(p.chainage_m) or
                                  not 0 <= p.chainage_m < length or
                                  p.bank not in ("Interior", "Exterior")
                                  for p in pumps):
        raise ValueError("Ubicaciones de bombas fuera del circuito o incompletas.")
    point = solve_reference_coupling(speed_fraction=inputs.speed_fraction,
                                     system_head_factor=inputs.system_head_factor)
    pump_q = point.pump_flow_m3_h / 3600
    bypass, residual = mass_balanced_flux(mid, length, pumps, pump_q,
                                          inputs.intake_upstream_m)

    # Set a velocity target for the *median passage cross section* only. The
    # narrower/wider sections then follow continuity, not arbitrary speed caps.
    passage = zone == "current"
    target_bulk_q = inputs.target_typical_speed_m_s * float(np.median(area[passage]))
    radius = area / perimeter

    def force_balance(bulk: float) -> tuple[float, float]:
        local_q = bulk + bypass
        drag = RHO * G * float(np.sum(ds * manning ** 2 * local_q ** 2 /
                                      (area * radius ** (4 / 3))))
        speed = local_q / area
        gross = 0.0
        for pump in pumps:
            intake = (float(pump.chainage_m) - inputs.intake_upstream_m) % length
            idx = min(int(intake / ds), ncell - 1)
            gross += RHO * pump_q * max(
                0.0, point.aggregate_nozzle_speed_m_s - speed[idx])
        return drag, gross

    if assumed_transfer_fraction is None:
        bulk_q = target_bulk_q
        flow_mode = "imposed_typical_speed"
    else:
        if not isfinite(assumed_transfer_fraction) or not 0 < assumed_transfer_fraction <= 1:
            raise ValueError("La transferencia hipotética debe estar entre 0 y 1.")
        low = max(0.0, float(-bypass.min())) + 1e-6

        def residual_force(bulk: float) -> float:
            drag, gross = force_balance(bulk)
            return drag - assumed_transfer_fraction * gross

        if residual_force(low) > 0:
            raise ValueError("La transferencia supuesta no sostiene flujo positivo en todas las secciones.")
        high = max(target_bulk_q * 2, low * 2)
        while residual_force(high) < 0:
            high *= 2
            if high > target_bulk_q * 100:
                raise ValueError("No se encontró un balance físico acotado.")
        for _ in range(55):
            mid_q = (low + high) / 2
            if residual_force(mid_q) < 0:
                low = mid_q
            else:
                high = mid_q
        bulk_q = (low + high) / 2
        flow_mode = "assumed_transfer_scenario"
    q = bulk_q + bypass
    if np.any(q <= 0):
        raise ValueError("La hipótesis produce contraflujo local; no se fuerza a positivo.")
    velocity = q / area
    # Suction removes local longitudinal momentum; this is an ideal *upper*
    # bound before unknown jet spreading, wall interaction and bathers.
    drag_n, gross_thrust_n = force_balance(bulk_q)
    required_transfer = drag_n / gross_thrust_n if gross_thrust_n > 0 else float("inf")
    travel_time_s = float(np.sum(ds / velocity))
    volume = float(np.sum(area * ds))
    current_length = float(np.sum(passage) * ds)
    calm = ~passage
    # A unique speed band need not exist when the DXF width varies.
    q_band_lower = .25 * area[passage]
    q_band_upper = .30 * area[passage]
    common_band_exists = float(q_band_lower.max()) <= float(q_band_upper.min())

    def interp(values: list[float]) -> list[float]:
        return [float(x) for x in values]

    return {
        "active_pumps": count, "length_m": length,
        "volume_m3": volume, "filtration_flow_4h_m3_h": volume / 4,
        "pump_flow_each_m3_h": point.pump_flow_m3_h,
        "sum_local_pump_flows_m3_h": count * point.pump_flow_m3_h,
        "aggregate_nozzle_exit_speed_m_s": point.aggregate_nozzle_speed_m_s,
        "pump_head_ft_reference_scenario": point.pump_head_ft,
        "target_typical_passage_speed_m_s": inputs.target_typical_speed_m_s,
        "flow_mode": flow_mode,
        "assumed_transfer_fraction": assumed_transfer_fraction,
        "actual_typical_passage_speed_m_s": float(np.median(velocity[passage])),
        "bulk_channel_flow_target_m3_h": bulk_q * 3600,
        "pump_bypass_perturbation_min_max_m3_h":
            [float(bypass.min() * 3600), float(bypass.max() * 3600)],
        "mass_balance_residual_m3_s": residual,
        "drag_at_target_n": drag_n,
        "ideal_net_jet_thrust_n": gross_thrust_n,
        "required_longitudinal_transfer_fraction": required_transfer,
        "required_transfer_exceeds_ideal": bool(required_transfer > 1),
        "conditional_lap_min": travel_time_s / 60,
        "speed_min_max_m_s": [float(velocity.min()), float(velocity.max())],
        "passage_speed_min_max_m_s": [float(velocity[passage].min()),
                                      float(velocity[passage].max())],
        "beach_median_speed_m_s": float(np.median(velocity[calm])) if calm.any() else None,
        "passage_length_m": current_length,
        "passage_fraction_0_25_to_0_30": float(np.mean(
            (velocity[passage] >= .25) & (velocity[passage] <= .30))),
        "passage_fraction_above_0_45": float(np.mean(velocity[passage] > .45)),
        "single_uniform_flow_can_hold_all_passages_0_25_to_0_30": bool(common_band_exists),
        "beach_edge_depth_at_widest_dxf_m": float(section["beach_edge_depths"].min()),
        "beach_reaches_dry_sand_inside_dxf": bool(np.any(
            section["beach_edge_depths"] <= 1e-6)),
        "pump_sites": [{"chainage_m": float(p.chainage_m), "bank": p.bank,
                        "purpose": p.purpose,
                        "intake_chainage_m": float((p.chainage_m -
                                                     inputs.intake_upstream_m) % length)}
                       for p in pumps],
        "wide_passage_runs_m": [[float(a), float(b)] for a, b in wide_runs],
        "bend_apices_m": [float(c.apex_m) for c in curves],
        "chainage_mid_m": interp(mid), "area_m2": interp(area),
        "local_channel_flow_m3_h": interp(q * 3600),
        "velocity_m_s": interp(velocity), "width_dxf_m": interp(width),
        "wet_width_m": interp(wet_width), "zone": list(zone),
        "manning_n": interp(manning),
        "limits": [
            "2D footprint with 1D section-mean velocity, not CFD lateral flow.",
            "Target bulk flow is imposed; pump ability is shown only as required transfer fraction.",
            "Local pump reference plumbing/TDH does not describe installed NYA plumbing.",
            "Bank and station layout are geometric hypotheses, not validated jet reach.",
            "Beach edge remains wet where the DXF width cannot reach dry sand.",
        ],
    }


def run(inputs: TrialInputs, counts: tuple[int, ...]) -> dict:
    model, beach_indices = load_nya()
    cases = [solve_case(model, beach_indices, inputs, count) for count in counts]
    compare_count = 20 if 20 in counts else counts[0]
    target_cases = [solve_case(model, beach_indices,
                               TrialInputs(**{**vars(inputs),
                                              "target_typical_speed_m_s": target}),
                               compare_count)
                    for target in (.25, .30)]
    assumed_cases = [solve_case(model, beach_indices, inputs, count,
                                assumed_transfer_fraction=.10)
                     for count in counts]
    assumed_sensitivity = [solve_case(model, beach_indices, inputs, compare_count,
                                      assumed_transfer_fraction=fraction)
                           for fraction in (.05, .15)]

    def runs_where(case: dict, *, above: float | None = None,
                   below: float | None = None) -> list[dict]:
        v = np.asarray(case["velocity_m_s"])
        zone = np.asarray(case["zone"])
        mask = zone == "current"
        if above is not None:
            mask &= v > above
        if below is not None:
            mask &= v < below
        ends = np.r_[False, mask, False]
        start_indices = np.flatnonzero(ends[1:] & ~ends[:-1])
        end_indices = np.flatnonzero(~ends[1:] & ends[:-1])
        return [{"from_m": float(start), "to_m": float(end),
                 "extreme_speed_m_s": float(v[start:end].max() if above is not None
                                            else v[start:end].min())}
                for start, end in zip(start_indices, end_indices)
                if end - start >= 3]

    default_case = next((c for c in cases if c["active_pumps"] == compare_count), cases[0])
    output = {"name": "NYA 536 m closed-loop screening trial",
              "dxf": "RECORRIDO.dxf", "source_point_xy_m": list(USER_ACCESS_POINT_M),
              "model": "steady mass-balanced ring; kinematic target, not prediction",
              "inputs": vars(inputs), "cases": cases,
              "target_speed_cases": target_cases,
              "assumed_transfer_10pct_cases": assumed_cases,
              "transfer_sensitivity_cases": assumed_sensitivity,
              "critical_reaches_at_default_target": {
                  "passage_above_0_45_m_s": runs_where(default_case, above=.45),
                  "passage_below_0_15_m_s": runs_where(default_case, below=.15),
              }}
    result_dir = HERE / "results"
    result_dir.mkdir(exist_ok=True)
    path = result_dir / "nya_circuito_536m_balanceado.json"
    path.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(path), "cases": [
        {k: c[k] for k in ("active_pumps", "required_longitudinal_transfer_fraction",
                            "conditional_lap_min", "speed_min_max_m_s",
                            "passage_fraction_0_25_to_0_30",
                            "passage_fraction_above_0_45",
                            "mass_balance_residual_m3_s")}
        for c in cases]}, indent=2))
    return output


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--counts", nargs="+", type=int, default=[16, 20, 24, 28])
    cli.add_argument("--target-speed", type=float, default=.275)
    cli.add_argument("--intake-upstream", type=float, default=5)
    cli.add_argument("--system-head-factor", type=float, default=1)
    cli.add_argument("--cell-length", type=float, default=1)
    args = cli.parse_args()
    run(TrialInputs(target_typical_speed_m_s=args.target_speed,
                    intake_upstream_m=args.intake_upstream,
                    system_head_factor=args.system_head_factor,
                    cell_length_m=args.cell_length), tuple(args.counts))
