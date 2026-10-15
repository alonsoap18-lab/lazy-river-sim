"""Inverse, no-calibration screening of a CF104 layout against a lap-time band.

This deliberately returns required fractions of *ideal gross* nozzle momentum,
not a predicted ride time.  Local suction, bend losses and jet mixing are not
known, so the fractions must never be interpreted as measured efficiencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, isfinite, radians, sqrt
from typing import Sequence

from core.riverflow_jet_momentum import NOZZLE_12X7_OPEN_AREA_M2


RHO_KG_M3 = 998.0
G_M_S2 = 9.81


@dataclass(frozen=True)
class LapRequirement:
    lap_min: float
    required_channel_flow_m3_h: float
    effective_speed_m_s: float
    required_drag_n: float
    fraction_of_gross_nozzle_momentum: float


@dataclass(frozen=True)
class NozzleScreen:
    gross_nozzle_momentum_n: float
    nozzle_exit_speeds_m_s: tuple[float, ...]
    nozzle_velocity_heads_ft: tuple[float, ...]
    channel_drag_coefficient: float
    requirements: tuple[LapRequirement, ...]
    optimistic_shortest_lap_min: float


def count_sensitivity(screen: NozzleScreen, reference_active_modules: int,
                      counts: Sequence[int]) -> tuple[tuple[int, tuple[float, ...]], ...]:
    """Scale gross momentum by count for identical copies of the *average* unit.

    This deliberately says nothing about bank, spacing, suction interactions
    or whether the same local H-Q operating point can be built for each unit.
    """
    if reference_active_modules < 1 or any(count < 1 for count in counts):
        raise ValueError("Las cantidades de bombas deben ser positivas.")
    return tuple((count, tuple(row.fraction_of_gross_nozzle_momentum *
                               reference_active_modules / count
                               for row in screen.requirements))
                 for count in counts)


def screen_lap_band(stations: Sequence[dict], plan,
                    wetted_perimeters_m: Sequence[float], *,
                    lap_minutes: Sequence[float] = (30.0, 35.0, 40.0),
                    nozzle_area_m2: float = NOZZLE_12X7_OPEN_AREA_M2,
                    roughness_scale: float = 1.0) -> NozzleScreen:
    """Compute nozzle upper bound and the drag demanded by each target lap.

    ``plan.transfer_fraction`` and ``plan.equivalent_channel_flow_m3_h`` are
    intentionally not read.  Pump Q is its *local* flow, never loop flow.
    ``roughness_scale`` is a sensitivity on all section Manning values, not a
    new measured material property.
    """
    n = len(stations)
    if (n < 2 or any(len(values) != n for values in
                    (wetted_perimeters_m, plan.station_areas_m2,
                     plan.station_manning_n))):
        raise ValueError("Las secciones, áreas, perímetros y Manning deben corresponder.")
    if (not isfinite(nozzle_area_m2) or nozzle_area_m2 <= 0 or
            not isfinite(roughness_scale) or roughness_scale <= 0 or
            not lap_minutes or any(not isfinite(t) or t <= 0 for t in lap_minutes)):
        raise ValueError("Área, rugosidad y tiempos deben ser positivos y finitos.")
    if (len(plan.module_flows_full_speed_m3_h) != plan.active_modules or
            len(plan.module_angles_deg) != plan.active_modules):
        raise ValueError("Faltan caudales o ángulos de unidades activas.")
    pump_q = tuple(q * plan.speed_fraction / 3600
                   for q in plan.module_flows_full_speed_m3_h)
    if any(not isfinite(q) or q <= 0 for q in pump_q):
        raise ValueError("Los caudales de bomba deben ser positivos y finitos.")
    speeds = tuple(q / nozzle_area_m2 for q in pump_q)
    gross = RHO_KG_M3 * sum(
        q * v * max(0.0, cos(radians(angle)))
        for q, v, angle in zip(pump_q, speeds, plan.module_angles_deg))
    if gross <= 0:
        raise ValueError("No hay impulso de boquilla en el sentido del recorrido.")
    drag_coefficient = 0.0
    for i in range(n - 1):
        ds = float(stations[i + 1]["chainage_m"]) - float(stations[i]["chainage_m"])
        area = (plan.station_areas_m2[i] + plan.station_areas_m2[i + 1]) / 2
        perimeter = (wetted_perimeters_m[i] + wetted_perimeters_m[i + 1]) / 2
        manning = (plan.station_manning_n[i] + plan.station_manning_n[i + 1]) / 2
        if any(not isfinite(x) or x <= 0 for x in (ds, area, perimeter, manning)):
            raise ValueError("Geometría y rugosidad deben ser positivas y finitas.")
        radius = area / perimeter
        drag_coefficient += ds * (roughness_scale * manning) ** 2 / (
            area * radius ** (4 / 3))
    if not isfinite(drag_coefficient) or drag_coefficient <= 0:
        raise ValueError("La resistencia integrada del canal es inválida.")
    requirements = []
    for lap_min in lap_minutes:
        q = plan.volume_m3 / (lap_min * 60)
        drag = RHO_KG_M3 * G_M_S2 * drag_coefficient * q * q
        requirements.append(LapRequirement(
            lap_min=float(lap_min), required_channel_flow_m3_h=q * 3600,
            effective_speed_m_s=plan.length_m / (lap_min * 60),
            required_drag_n=drag,
            fraction_of_gross_nozzle_momentum=drag / gross))
    ideal_q = sqrt(gross / (RHO_KG_M3 * G_M_S2 * drag_coefficient))
    return NozzleScreen(
        gross_nozzle_momentum_n=gross,
        nozzle_exit_speeds_m_s=speeds,
        nozzle_velocity_heads_ft=tuple(v * v / (2 * G_M_S2 * .3048) for v in speeds),
        channel_drag_coefficient=drag_coefficient,
        requirements=tuple(requirements),
        optimistic_shortest_lap_min=plan.volume_m3 / (ideal_q * 60),
    )
