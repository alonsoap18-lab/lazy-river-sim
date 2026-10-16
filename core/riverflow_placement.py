"""Auditable placement diagnostics for the closed NYA channel.

Friction between pumps is a spacing *proxy*, not a prediction of local jet
reach or a substitute for a momentum/CFD solution. No new river flow is
created by moving a pump along a closed, unbranched channel.
"""

from bisect import bisect_left
from dataclasses import dataclass
from math import isclose, isfinite
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class PlacementGap:
    max_gap_m: float
    max_friction_share: float
    friction_imbalance: float
    gap_start_m: float
    gap_end_m: float


@dataclass(frozen=True)
class CurveCandidate:
    apex_m: float
    turn_deg: float
    preferred_bank: str
    candidate_m: float
    width_m: float


def curve_candidates(stations: Sequence[dict], zones: Sequence[str],
                     scale_m_per_unit: float, *, window_m: float = 10.0,
                     minimum_turn_deg: float = 20.0,
                     minimum_spacing_m: float = 18.0) -> tuple[CurveCandidate, ...]:
    """Screen bend approaches from scaled DXF geometry, not hydraulic performance.

    The exterior of a *bend* alternates between the DXF's inner and outer
    banks. The normal points toward the DXF outer bank on the CCW route.
    """
    if len(stations) != len(zones) or len(stations) < 4 or scale_m_per_unit <= 0:
        raise ValueError("Geometría y zonas inválidas para revisar curvas.")
    chain = np.asarray([float(s["chainage_m"]) for s in stations])
    if np.any(np.diff(chain) <= 0):
        raise ValueError("Las progresivas de las curvas deben estar ordenadas.")
    length = chain[-1]
    x = np.asarray([float(s["x"]) for s in stations]) * scale_m_per_unit
    y = np.asarray([float(s["y"]) for s in stations]) * scale_m_per_unit
    samples = np.arange(0.0, length, 1.0)
    interp_x = lambda values: np.interp(np.mod(values, length), chain, x)
    interp_y = lambda values: np.interp(np.mod(values, length), chain, y)
    ax, ay = interp_x(samples) - interp_x(samples - window_m), interp_y(samples) - interp_y(samples - window_m)
    bx, by = interp_x(samples + window_m) - interp_x(samples), interp_y(samples + window_m) - interp_y(samples)
    turn = np.degrees(np.arctan2(ax * by - ay * bx, ax * bx + ay * by))
    ranked = sorted(range(len(samples)), key=lambda i: abs(turn[i]), reverse=True)
    selected: list[CurveCandidate] = []
    for i in ranked:
        apex = float(samples[i])
        if abs(turn[i]) < minimum_turn_deg:
            break
        if any(min(abs(apex - c.apex_m), length - abs(apex - c.apex_m)) < minimum_spacing_m
               for c in selected):
            continue
        nearest_apex = min(range(len(chain) - 1), key=lambda j: abs(chain[j] - apex))
        if zones[nearest_apex] != "current":
            continue
        upstream = (apex - min(window_m / 2, 5.0)) % length
        eligible = [j for j, zone in enumerate(zones[:-1]) if zone == "current"]
        j = min(eligible, key=lambda k: min(abs(chain[k] - upstream),
                                             length - abs(chain[k] - upstream)))
        selected.append(CurveCandidate(apex, float(turn[i]),
                                       "Exterior" if turn[i] > 0 else "Interior",
                                       float(chain[j]), float(stations[nearest_apex]["width_m"])))
    return tuple(sorted(selected, key=lambda c: c.apex_m))


def suggest_curve_aware_positions(stations: Sequence[dict], cumulative: Sequence[float],
                                  zones: Sequence[str], count: int,
                                  candidates: Sequence[CurveCandidate]) -> tuple[tuple[float, ...], tuple[str, ...]]:
    """Move a friction-balanced screening layout toward bend approaches.

    Keep candidate spacing and the worst friction gap bounded relative to the
    original suggestion. This is not a jet-reach or safety optimizer.
    """
    base = suggest_friction_balanced_positions(stations, cumulative, zones, count)
    limit = placement_gaps(stations, cumulative, base)
    length = float(stations[-1]["chainage_m"])
    positions = list(base)
    banks = ["Exterior"] * count
    for curve in sorted(candidates, key=lambda c: abs(c.turn_deg), reverse=True):
        k = min(range(count), key=lambda i: min(abs(positions[i] - curve.candidate_m),
                                                length - abs(positions[i] - curve.candidate_m)))
        proposal = positions.copy()
        proposal[k] = curve.candidate_m
        if len(set(proposal)) != count:
            continue
        ordered_positions = sorted(proposal)
        separations = [b - a for a, b in zip(ordered_positions, ordered_positions[1:])]
        separations.append(length - ordered_positions[-1] + ordered_positions[0])
        if min(separations) < max(12.0, 0.4 * length / count):
            continue
        gap = placement_gaps(stations, cumulative, proposal)
        if gap.max_gap_m > max(limit.max_gap_m * 1.25, length / count * 2.5):
            continue
        if gap.max_friction_share > limit.max_friction_share * 1.35:
            continue
        positions = proposal
        banks[k] = curve.preferred_bank
    # A pump already close to a bend approach needs the corresponding bend
    # bank even when moving it to the exact candidate would violate spacing.
    # Bank choice is geometric only; it does not create extra bulk flow.
    bank_window_m = max(12.0, 0.55 * length / count)
    for i, position in enumerate(positions):
        if not candidates:
            break
        nearest = min(candidates, key=lambda candidate: min(
            abs(position - candidate.candidate_m),
            length - abs(position - candidate.candidate_m)))
        distance = min(abs(position - nearest.candidate_m),
                       length - abs(position - nearest.candidate_m))
        if distance <= bank_window_m:
            banks[i] = nearest.preferred_bank
    ordered = sorted(zip(positions, banks))
    return tuple(p for p, _ in ordered), tuple(b for _, b in ordered)


def suggest_width_aware_positions(
    stations: Sequence[dict], cumulative: Sequence[float], zones: Sequence[str],
    count: int, candidates: Sequence[CurveCandidate], *, wide_threshold_m: float = 15.0,
) -> tuple[tuple[float, ...], tuple[str, ...]]:
    """Screen sites across passing bays, bends and uncovered reaches.

    Two staggered sites on opposite banks are considered in each sufficiently
    long *circulating* widening. They are not opposing jets and do not create
    extra longitudinal flow. This is geometry-only placement, not CFD or a
    calibrated prediction of nozzle reach.
    """
    if (len(stations) != len(zones) or len(stations) != len(cumulative)
            or count < 1 or wide_threshold_m <= 0):
        raise ValueError("Secciones, zonas o cantidad de unidades inválidas.")
    length = float(stations[-1]["chainage_m"])
    eligible = [(float(s["chainage_m"]), float(s["width_m"]))
                for s, zone in zip(stations[:-1], zones[:-1]) if zone == "current"]
    if length <= 0 or cumulative[-1] <= 0 or len(eligible) < count:
        raise ValueError("No hay suficientes estaciones de corriente para ubicar unidades.")
    current_length = sum(float(b["chainage_m"]) - float(a["chainage_m"])
                         for a, b, zone in zip(stations[:-1], stations[1:], zones[:-1])
                         if zone == "current")
    spacing = min(12.0, 0.6 * current_length / count)
    chosen: list[tuple[float, str]] = []

    def distance(a: float, b: float) -> float:
        delta = abs(a - b)
        return min(delta, length - delta)

    def add_near(target: float, bank: str, interval: tuple[float, float] | None = None,
                 max_offset: float | None = None, paired: bool = False) -> bool:
        choices = (p for p, _ in eligible if interval is None or
                   interval[0] <= p < interval[1])
        for point in sorted(choices, key=lambda p: distance(p, target)):
            if max_offset is not None and distance(point, target) > max_offset:
                break
            if all(distance(point, old) >=
                   (min(spacing, 0.4 * (interval[1] - interval[0]))
                    if paired and interval is not None and
                    interval[0] <= old < interval[1] else spacing)
                   for old, _ in chosen):
                chosen.append((point, bank))
                return True
        return False

    # Only the mapped main beach is calm. Every other widening is a passage.
    runs: list[tuple[float, float]] = []
    start = None
    for station, zone in zip(stations[:-1], zones[:-1]):
        point = float(station["chainage_m"])
        if zone == "current" and float(station["width_m"]) >= wide_threshold_m:
            if start is None:
                start = point
        elif start is not None:
            runs.append((start, point))
            start = None
    if start is not None:
        runs.append((start, length))

    # Cover each bay once before adding a second unit to any bay. The second
    # location is staggered downstream to preserve unique chainages and leave
    # space for a lateral-flow hypothesis on the opposite bank.
    for second in (False, True):
        for start, end in sorted(runs, key=lambda run: run[1] - run[0], reverse=True):
            if len(chosen) >= count:
                break
            target = start + (0.78 if second else 0.22) * (end - start)
            add_near(target, "Exterior" if second else "Interior", (start, end),
                     paired=second)

    for curve in sorted(candidates, key=lambda c: abs(c.turn_deg), reverse=True):
        if len(chosen) >= count:
            break
        if any(distance(point, curve.candidate_m) < spacing for point, _ in chosen):
            continue
        add_near(curve.candidate_m, curve.preferred_bank, max_offset=6.0)

    # Fill uncovered lengths. A moderate width preference prevents the old
    # Manning-only ranking from crowding narrow reaches; it is a site priority,
    # not an invented hydraulic gain or velocity formula.
    widths = sorted(width for _, width in eligible)
    reference_width = widths[len(widths) // 2]
    while len(chosen) < count:
        options = [(min(distance(p, old) for old, _ in chosen) if chosen else length / 2,
                    p, width) for p, width in eligible
                   if all(distance(p, old) >= spacing for old, _ in chosen)]
        if not options:
            raise ValueError("No caben más unidades sin repetir posiciones elegibles.")
        _, point, _ = max(options, key=lambda item:
                          (item[0] * min(1.6, (item[2] / reference_width) ** 0.35),
                           item[0], item[1]))
        nearby = min(candidates, key=lambda c: distance(c.candidate_m, point)) if candidates else None
        bank = (nearby.preferred_bank if nearby is not None and
                distance(nearby.candidate_m, point) <= spacing else "Exterior")
        chosen.append((point, bank))
    ordered = sorted(chosen)
    return tuple(p for p, _ in ordered), tuple(b for _, b in ordered)


def cumulative_manning_resistance(stations: Sequence[dict], areas_m2: Sequence[float],
                                  perimeters_m: Sequence[float],
                                  manning_n: Sequence[float]) -> tuple[float, ...]:
    """Integrate the same section head-loss coefficient used by the base plan."""
    count = len(stations)
    if count < 2 or any(len(values) != count for values in
                        (areas_m2, perimeters_m, manning_n)):
        raise ValueError("Secciones y geometría hidráulica deben corresponder.")
    cumulative = [0.0]
    for i in range(count - 1):
        ds = float(stations[i + 1]["chainage_m"]) - float(stations[i]["chainage_m"])
        area = (areas_m2[i] + areas_m2[i + 1]) / 2
        perimeter = (perimeters_m[i] + perimeters_m[i + 1]) / 2
        n = (manning_n[i] + manning_n[i + 1]) / 2
        if not all(isfinite(v) and v > 0 for v in (ds, area, perimeter, n)):
            raise ValueError("Distancias, áreas, perímetros y Manning deben ser positivos.")
        radius = area / perimeter
        cumulative.append(cumulative[-1] + ds * (n / (area * radius ** (2 / 3))) ** 2)
    return tuple(cumulative)


def _interpolate_cumulative(chainages: Sequence[float], cumulative: Sequence[float],
                            position: float) -> float:
    i = min(max(bisect_left(chainages, position), 1), len(chainages) - 1)
    portion = (position - chainages[i - 1]) / (chainages[i] - chainages[i - 1])
    return cumulative[i - 1] + portion * (cumulative[i] - cumulative[i - 1])


def placement_gaps(stations: Sequence[dict], cumulative: Sequence[float],
                   positions_m: Sequence[float]) -> PlacementGap:
    """Find the longest distance and highest friction load between units."""
    chainages = tuple(float(s["chainage_m"]) for s in stations)
    length = chainages[-1]
    if (len(chainages) != len(cumulative) or length <= 0 or cumulative[-1] <= 0
            or not positions_m or any(not isfinite(p) or p < 0 or p >= length
                                       for p in positions_m)):
        raise ValueError("Posiciones o resistencia del circuito inválidas.")
    positions = sorted(positions_m)
    if any(isclose(a, b, abs_tol=1e-8) for a, b in zip(positions, positions[1:])):
        raise ValueError("Dos unidades no deben ocupar la misma progresiva.")
    loads = [_interpolate_cumulative(chainages, cumulative, p) for p in positions]
    gaps_m = [b - a for a, b in zip(positions, positions[1:])]
    gaps_m.append(length - positions[-1] + positions[0])
    gaps_load = [b - a for a, b in zip(loads, loads[1:])]
    gaps_load.append(cumulative[-1] - loads[-1] + loads[0])
    worst = max(range(len(gaps_load)), key=gaps_load.__getitem__)
    return PlacementGap(max(gaps_m), gaps_load[worst] / cumulative[-1],
                        len(positions) * gaps_load[worst] / cumulative[-1],
                        positions[worst], positions[(worst + 1) % len(positions)])


def suggest_friction_balanced_positions(stations: Sequence[dict],
                                        cumulative: Sequence[float],
                                        zones: Sequence[str], count: int) -> tuple[float, ...]:
    """Balance resistance and physical spacing in eligible current zones.

    This is a deterministic screening heuristic. It does not claim that the
    outlet reaches the next pump, and it does not modify the original DXF.
    """
    if len(stations) != len(zones) or len(stations) != len(cumulative) or count < 1:
        raise ValueError("Secciones, zonas y cantidad de unidades inválidas.")
    chainages = tuple(float(s["chainage_m"]) for s in stations)
    eligible_indices = [i for i, zone in enumerate(zones[:-1]) if zone == "current"]
    if len(eligible_indices) < count:
        raise ValueError("No hay suficientes estaciones de corriente para ubicar unidades.")
    total = cumulative[-1]
    best = None
    best_score = float("inf")
    for friction_weight in (0.25, 0.5, 0.75, 1.0):
        # Pure equal-friction placement may create a long unpowered reach in a
        # low-resistance beach. Blend it with length instead of hiding that risk.
        eligible = [(chainages[i],
                     friction_weight * cumulative[i] / total +
                     (1 - friction_weight) * chainages[i] / chainages[-1])
                    for i in eligible_indices]
        for phase in ((k + 0.5) / 12 for k in range(12)):
            chosen = []
            remaining = eligible.copy()
            for i in range(count):
                target = (i + phase) / count
                closest = min(range(len(remaining)),
                              key=lambda j: min(abs(remaining[j][1] - target),
                                                1 - abs(remaining[j][1] - target)))
                chosen.append(remaining.pop(closest)[0])
            positions = tuple(sorted(chosen))
            gaps = placement_gaps(stations, cumulative, positions)
            # Concentrating two units at the same beach transition can reduce
            # the friction score while leaving an avoidable unpowered reach.
            # Reject such clustering before ranking the screening layouts.
            separations = [b - a for a, b in zip(positions, positions[1:])]
            separations.append(chainages[-1] - positions[-1] + positions[0])
            if min(separations) < max(12.0, 0.4 * chainages[-1] / count):
                continue
            score = gaps.friction_imbalance + gaps.max_gap_m / (chainages[-1] / count)
            if score < best_score:
                best_score, best = score, positions
    if best is None:
        # A long intentionally unpowered beach can make every closed-loop
        # friction quantile cluster at its edges. Spread units over the
        # eligible circulation stations instead of accepting that cluster.
        eligible_chainages = [chainages[i] for i in eligible_indices]
        first, last = eligible_chainages[0], eligible_chainages[-1]
        span = last - first
        available = eligible_chainages.copy()
        chosen = []
        for i in range(count):
            target = first + (i + .5) * span / count
            nearest = min(range(len(available)),
                          key=lambda j: abs(available[j] - target))
            chosen.append(available.pop(nearest))
        best = tuple(sorted(chosen))
    return best
