"""Constrained local comparison of pump sites, never an engineering design.

Uses the uncalibrated depth-averaged pilot. The curl of its horizontal velocity
is only a rotation indicator; it is NOT a turbulence intensity or a 3D eddy
prediction. A proposed move is kept only if a full-duration rerun improves the
screening indicators without sacrificing forward current in the wide passages.
"""

from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
import sys

import numpy as np
from scipy.ndimage import binary_erosion

from experiments.splishsplash_nya_pilot.depth2d_flow import Flow2DInputs, solve
from experiments.splishsplash_nya_pilot.full_loop_2d import load_nya


def indicators(result: dict) -> dict:
    grid = result["grid"]
    wet = grid["wet"]
    core = binary_erosion(wet)
    u, v = result["u"], result["v"]
    d = result["settings"].cell_m
    rotation = np.gradient(v, d, axis=1) - np.gradient(u, d, axis=0)
    along = u * grid["tangent_x"] + v * grid["tangent_y"]
    widths = []
    for start, end in result["reference"]["wide_passage_runs_m"]:
        section = wet & (grid["chainage"] >= start) & (grid["chainage"] < end)
        if section.any():
            widths.append(float(np.mean(along[section])))
    return {
        "reverse_area_fraction": float(np.mean(along[wet] < -.005)),
        "core_rotation_rms_s_1": float(np.sqrt(np.mean(rotation[core] ** 2))),
        "forward_mean_m_s": float(np.mean(along[wet])),
        "wide_passage_forward_m_s": widths,
        "slow_area_fraction": float(np.mean(np.hypot(u[wet], v[wet]) < .005)),
    }


def screening_score(metrics: dict, baseline: dict) -> float:
    """Relative score subject to no-reversal/no-wide-passage loss gates."""
    forward = metrics["forward_mean_m_s"]
    base_forward = baseline["forward_mean_m_s"]
    if forward < .98 * base_forward:
        return float("inf")
    for current, base in zip(metrics["wide_passage_forward_m_s"],
                             baseline["wide_passage_forward_m_s"]):
        if current < max(0.0, base * .95):
            return float("inf")
    reverse = metrics["reverse_area_fraction"] / max(baseline["reverse_area_fraction"], .001)
    rotation = metrics["core_rotation_rms_s_1"] / max(baseline["core_rotation_rms_s_1"], 1e-8)
    slow = metrics["slow_area_fraction"] / max(baseline["slow_area_fraction"], .001)
    return .45 * reverse + .4 * rotation + .15 * slow


def _valid_move(index: int, chainage: float, bank: str, sites: list[dict],
                eligible: np.ndarray, minimum_spacing_m: float = 12.0) -> bool:
    if not np.min(np.abs(eligible - chainage)) < 1.1:
        return False
    for n, site in enumerate(sites):
        if n == index:
            continue
        delta = abs(chainage - site["chainage_m"])
        delta = min(delta, 536 - delta)
        if delta < minimum_spacing_m:
            # The existing opposite-bank pairs in passage bays are preserved;
            # no new closely opposed installation is created by this search.
            return False
    return True


def screen(count: int = 20, *, quick_steps: int = 500,
           full_steps: int = 1200, max_moves: int = 4) -> dict:
    model, beach = load_nya()
    inputs = Flow2DInputs(count=count, steps=quick_steps)
    baseline_result = solve(inputs, model=model, beach=beach)
    baseline = indicators(baseline_result)
    sites = baseline_result["pump_sites"]
    eligible = np.array([s for s, zone in zip(
        baseline_result["reference"]["chainage_mid_m"],
        baseline_result["reference"]["zone"]) if zone == "current"])
    evaluated = []
    for index, site in enumerate(sites):
        if site["purpose"].startswith("Par opuesto"):
            continue
        for shift in (-12, -6, 0, 6, 12):
            chain = round((site["chainage_m"] + shift) % 536, 1)
            for bank in ("Interior", "Exterior"):
                if shift == 0 and bank == site["bank"]:
                    continue
                if not _valid_move(index, chain, bank, sites, eligible):
                    continue
                settings = replace(inputs, moved_pump_index=index,
                                   moved_chainage_m=chain, moved_bank=bank)
                result = solve(settings, model=model, beach=beach)
                m = indicators(result)
                score = screening_score(m, baseline)
                if np.isfinite(score):
                    evaluated.append((score, index, chain, bank, m))
    # Retain independent improvements; the final combined case is rerun and
    # must pass its own full-duration gates. Never claim a global optimum.
    chosen = []
    for score, index, chain, bank, m in sorted(evaluated):
        if score >= screening_score(baseline, baseline) - .005:
            break
        if any(k == index for k, _, _ in chosen):
            continue
        trial_sites = [dict(p) for p in sites]
        for k, pos, side in chosen:
            trial_sites[k]["chainage_m"] = pos
            trial_sites[k]["bank"] = side
        if not _valid_move(index, chain, bank, trial_sites, eligible):
            continue
        chosen.append((index, chain, bank))
        if len(chosen) >= max_moves:
            break
    base_full = solve(replace(inputs, steps=full_steps), model=model, beach=beach)
    base_full_metrics = indicators(base_full)
    accepted = []
    current_result, current_metrics = base_full, base_full_metrics
    for move in chosen:
        proposal = accepted + [move]
        trial = solve(replace(inputs, steps=full_steps,
                              site_overrides=tuple(proposal)), model=model, beach=beach)
        m = indicators(trial)
        if screening_score(m, base_full_metrics) < screening_score(current_metrics, base_full_metrics) - .005:
            accepted.append(move)
            current_result, current_metrics = trial, m
    return {
        "warning": "Cribado 2D no calibrado: no predice turbulencia 3D ni valida obra/compra.",
        "count": count,
        "quick_steps": quick_steps,
        "full_steps": full_steps,
        "baseline": base_full_metrics,
        "proposal": current_metrics,
        "accepted_moves": [{"pump_number": i + 1,
                            "from_chainage_m": sites[i]["chainage_m"],
                            "from_bank": sites[i]["bank"],
                            "to_chainage_m": chain,
                            "to_bank": bank} for i, chain, bank in accepted],
        "tested_single_moves": len(evaluated),
        "settings": asdict(replace(inputs, steps=full_steps,
                                   site_overrides=tuple(accepted))),
    }


def robustness(report: dict) -> list[dict]:
    """Check whether the chosen geometry's advantage survives input changes."""
    model, beach = load_nya()
    moves = tuple((int(i), float(s), str(b)) for i, s, b in
                  report["settings"]["site_overrides"])
    trials = [
        (2.0, .05, .08), (2.0, .15, .08),
        (2.0, .10, .04), (2.0, .10, .16),
        (1.5, .10, .08), (2.5, .10, .08),
    ]
    rows = []
    for cell, moment, mixing in trials:
        settings = Flow2DInputs(count=report["count"], cell_m=cell,
                                momentum_fraction=moment,
                                eddy_viscosity_m2_s=mixing)
        base = indicators(solve(settings, model=model, beach=beach))
        proposed = indicators(solve(replace(settings, site_overrides=moves),
                                    model=model, beach=beach))
        rows.append({"cell_m": cell, "momentum_fraction": moment,
                     "eddy_viscosity_m2_s": mixing,
                     "baseline": base, "proposal": proposed,
                     "reverse_improves": proposed["reverse_area_fraction"] < base["reverse_area_fraction"],
                     "rotation_improves": proposed["core_rotation_rms_s_1"] < base["core_rotation_rms_s_1"],
                     "all_wide_forward_preserved": all(
                         p >= max(0.0, b * .95) for p, b in zip(
                             proposed["wide_passage_forward_m_s"],
                             base["wide_passage_forward_m_s"]))})
    return rows


if __name__ == "__main__":
    path = Path(__file__).with_name("results") / "nya_ubicacion_20_bombas_cribado_2d.json"
    if "--robustness" in sys.argv:
        report = json.loads(path.read_text(encoding="utf-8"))
        print(json.dumps(robustness(report), indent=2, ensure_ascii=False))
    else:
        report = screen()
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
