"""Planning-only gap diagnostics for a closed Riverflow loop.

These limits are user-selected layout constraints, not measured jet reach.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence


@dataclass(frozen=True)
class GapCheck:
    start_m: float
    end_m: float
    length_m: float
    kind: str
    limit_m: float
    exceeds_limit: bool


@dataclass(frozen=True)
class LayoutSite:
    chainage_m: float
    bank: str
    purpose: str


def _circular_distance(a: float, b: float, length: float) -> float:
    delta = abs(a - b) % length
    return min(delta, length - delta)


def zone_aware_sites(stations: Sequence[dict], zones: Sequence[str], count: int,
                     curves: Sequence[object],
                     wide_runs: Sequence[tuple[float, float]],
                     *, minimum_spacing_m: float = 12.0) -> tuple[LayoutSite, ...]:
    """Allocate a planning layout: bend approaches, passage bays, then gaps.

    The chosen positions and banks are geometric candidates only. No assumed
    jet travel distance, local current or hydraulic benefit is inferred.
    """
    if len(stations) != len(zones) or len(stations) < 2 or count < 1:
        raise ValueError("Secciones, zonas o cantidad de bombas inválidas.")
    length = float(stations[-1]["chainage_m"])
    eligible = tuple(float(s["chainage_m"]) for s, zone in
                     zip(stations[:-1], zones[:-1]) if zone == "current")
    if length <= 0 or len(eligible) < count or minimum_spacing_m <= 0:
        raise ValueError("No hay suficientes ubicaciones elegibles en el recorrido.")
    selected: list[LayoutSite] = []

    def downstream_bank(target: float) -> str:
        if not curves:
            return "Exterior"
        return min(curves, key=lambda c: (c.apex_m - target) % length).preferred_bank

    def add_near(target: float, bank: str, purpose: str,
                 interval: tuple[float, float] | None = None,
                 max_offset_m: float | None = None,
                 opposed_pair: bool = False) -> bool:
        choices = (p for p in eligible if interval is None or
                   interval[0] <= p < interval[1])
        for point in sorted(choices, key=lambda p: _circular_distance(
                p, target % length, length)):
            if (max_offset_m is not None and
                    _circular_distance(point, target % length, length) > max_offset_m):
                break
            if all((opposed_pair and point == site.chainage_m and
                    bank != site.bank and
                    site.purpose.startswith("Par opuesto")) or
                   _circular_distance(point, site.chainage_m, length)
                   >= minimum_spacing_m for site in selected):
                selected.append(LayoutSite(point, bank, purpose))
                return True
        return False

    # Reserve a bilateral current proposal in each wide PASSAGE bay, never in
    # the main beach. Both outlets point downstream; "opposed" describes their
    # banks, not jets firing at one another. It is a geometric trial, not a
    # manufacturer rule or proof of velocity across the width.
    for start, end in wide_runs:
        if len(selected) + 2 > count:
            break
        candidates = [p for p in eligible if start <= p < end]
        if not candidates:
            continue
        target = start + .35 * (end - start)
        point = min(candidates, key=lambda p: abs(p - target))
        if add_near(point, "Interior", f"Par opuesto · ampliación {start:.0f}–{end:.0f} m",
                    (start, end), max_offset_m=1.0):
            if not add_near(point, "Exterior",
                            f"Par opuesto · ampliación {start:.0f}–{end:.0f} m",
                            (start, end), max_offset_m=1.0, opposed_pair=True):
                selected.pop()

    # Give bend approaches the remaining positions. A bank means the *outside
    # of that particular bend*, not always the DXF's globally outer wall.
    for curve in sorted(curves, key=lambda c: abs(c.turn_deg), reverse=True):
        if len(selected) >= count:
            break
        add_near(curve.candidate_m, curve.preferred_bank,
                 f"Aproximación a curva {curve.apex_m:.0f} m",
                 max_offset_m=6.0)

    # Fill the longest uncovered reaches, without treating high Manning loss
    # in a narrow section as proof that more pumps belong there.
    while len(selected) < count:
        ordered = sorted(site.chainage_m for site in selected)
        if not ordered:
            target = length / 2
            gaps = [(len(eligible), target)]
        else:
            gaps = []
            for start, end in zip(ordered, ordered[1:] + ordered[:1]):
                span = (end - start) % length
                current_points = sorted(
                    (p for p in eligible if 0 < (p - start) % length < span),
                    key=lambda p: (p - start) % length)
                if current_points:
                    gaps.append((len(current_points),
                                 current_points[len(current_points) // 2]))
        added = False
        for _, target in sorted(gaps, reverse=True):
            if add_near(target, downstream_bank(target), "Equilibrio de tramos"):
                added = True
                break
        if not added:
            raise ValueError("No caben más bombas con la separación geométrica elegida.")
    return tuple(sorted(selected, key=lambda site: site.chainage_m))


def classify_beach_core(stations: Sequence[dict], beach_indices: Sequence[int],
                        wide_threshold_m: float) -> tuple[str, ...]:
    """Only the DXF's principal beach core is calm; other bays stay passage."""
    if wide_threshold_m <= 0 or not stations:
        raise ValueError("El ancho de playa debe ser positivo.")
    beach_set = set(beach_indices)
    return tuple("calm" if i in beach_set and float(station["width_m"]) >= wide_threshold_m
                 else "current" for i, station in enumerate(stations))


def wide_passage_runs(stations: Sequence[dict], zones: Sequence[str],
                      wide_threshold_m: float) -> tuple[tuple[float, float], ...]:
    """Return non-beach widening intervals along the route, not hydraulic lanes."""
    if len(stations) != len(zones) or wide_threshold_m <= 0:
        raise ValueError("Secciones o umbral de zonas anchas inválidos.")
    runs = []
    start = None
    for station, zone in zip(stations[:-1], zones[:-1]):
        chainage = float(station["chainage_m"])
        wide_passage = zone == "current" and float(station["width_m"]) >= wide_threshold_m
        if wide_passage and start is None:
            start = chainage
        elif not wide_passage and start is not None:
            runs.append((start, chainage))
            start = None
    if start is not None:
        runs.append((start, float(stations[-1]["chainage_m"])))
    return tuple(runs)


def cover_wide_passages(positions_m: Sequence[float], banks: Sequence[str],
                        runs: Sequence[tuple[float, float]],
                        eligible_chainages_m: Sequence[float],
                        length_m: float) -> tuple[tuple[float, ...], tuple[str, ...]]:
    """Geometrically put at least one of the existing pumps in each wide bay.

    No extra pump is created, and no jet reach or velocity gain is assumed.
    """
    if len(positions_m) != len(banks) or not eligible_chainages_m or length_m <= 0:
        raise ValueError("Faltan bombas o posiciones de instalación elegibles.")
    positions = list(positions_m)
    sides = list(banks)
    reserved = set()
    protected = {i for i, position in enumerate(positions)
                 if any(start <= position < end for start, end in runs)}
    for start, end in runs:
        existing = [i for i, position in enumerate(positions)
                    if start <= position < end]
        if existing:
            reserved.add(existing[0])
            continue
        desired = start + .35 * (end - start)
        candidates = [p for p in eligible_chainages_m if start <= p < end]
        if not candidates:
            continue
        target = min(candidates, key=lambda p: abs(p - desired))
        movable = [i for i in range(len(positions))
                   if i not in reserved and i not in protected]
        if not movable:
            break
        index = min(movable, key=lambda i: min(abs(positions[i] - target),
                                               length_m - abs(positions[i] - target)))
        positions[index] = target
        reserved.add(index)
    ordered = sorted(zip(positions, sides))
    return tuple(p for p, _ in ordered), tuple(b for _, b in ordered)


def _between(start: float, end: float, point: float, length: float) -> bool:
    return (point - start) % length < (end - start) % length


def check_layout_gaps(
    positions_m: Sequence[float], *, length_m: float,
    bend_apices_m: Sequence[float], calm_chainages_m: Sequence[float],
    straight_limit_m: float, bend_limit_m: float, beach_limit_m: float,
    banks: Sequence[str] | None = None,
    wide_runs: Sequence[tuple[float, float]] = (),
) -> tuple[GapCheck, ...]:
    """Classify inter-pump reaches; mixed reaches use the stricter category.

    A reach touching a detected bend and a calm beach is labelled ``curva/playa``
    and receives the smaller limit. This does not simulate momentum decay.
    """
    values = (length_m, straight_limit_m, bend_limit_m, beach_limit_m)
    if not all(isfinite(value) and value > 0 for value in values):
        raise ValueError("La longitud y las separaciones deben ser positivas.")
    if banks is not None and len(banks) != len(positions_m):
        raise ValueError("Debe indicarse una orilla por bomba.")
    positions = sorted(float(position) for position in positions_m)
    if not positions or any(not isfinite(p) or not 0 <= p < length_m for p in positions):
        raise ValueError("Las posiciones deben quedar dentro del circuito.")
    if len(set(positions)) != len(positions):
        if banks is None:
            raise ValueError("Indique las orillas para validar bombas enfrentadas.")
        for position in set(positions):
            assigned = [bank for p, bank in zip(positions_m, banks)
                        if float(p) == position]
            if len(assigned) > 1 and (len(assigned) != 2 or
                    set(assigned) != {"Interior", "Exterior"} or
                    not any(start <= position < end for start, end in wide_runs)):
                raise ValueError("Un par coincidente solo se permite en orillas opuestas de una ampliación de paso.")
        positions = sorted(set(positions))
    if any(not 0 <= p < length_m for p in (*bend_apices_m, *calm_chainages_m)):
        raise ValueError("Las zonas y curvas deben quedar dentro del circuito.")

    rows = []
    ends = positions[1:] + positions[:1]
    for start, end in zip(positions, ends):
        span = (end - start) % length_m
        if len(positions) == 1:
            span = length_m
        touches_bend = any(_between(start, end, p, length_m) for p in bend_apices_m)
        touches_beach = any(_between(start, end, p, length_m) for p in calm_chainages_m)
        if touches_bend and touches_beach:
            kind, limit = "curva/playa", min(bend_limit_m, beach_limit_m)
        elif touches_bend:
            kind, limit = "curva", bend_limit_m
        elif touches_beach:
            kind, limit = "playa", beach_limit_m
        else:
            kind, limit = "recta", straight_limit_m
        rows.append(GapCheck(start, end, span, kind, limit, span > limit))
    return tuple(rows)


def candidate_counts(min_count: int, max_count: int) -> range:
    if min_count < 1 or max_count < min_count:
        raise ValueError("Rango de bombas inválido.")
    return range(min_count, max_count + 1)
