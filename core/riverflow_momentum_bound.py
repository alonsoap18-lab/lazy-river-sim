"""Optimistic momentum feasibility bound, independent of the 2% energy input.

This is deliberately not CFD. It asks whether an ideal loss-free nozzle could
overcome Manning channel drag at a requested circuit flow. Real plumbing,
jet mixing, curves and swimmers can only make the result less favorable.
"""

from dataclasses import dataclass
from math import cos, isfinite, radians, sqrt
from typing import Sequence

from core.riverflow_model import GRAVITY_M_S2, RiverflowPlan


WATER_DENSITY_KG_M3 = 998.0


@dataclass(frozen=True)
class MomentumBound:
    ideal_thrust_n: float
    target_drag_n: float
    target_fraction_of_ideal: float
    optimistic_min_lap_min: float
    ideal_exit_speed_m_s: float


def compute_momentum_bound(stations: Sequence[dict], plan: RiverflowPlan,
                           section_perimeters_m: Sequence[float]) -> MomentumBound:
    """Compare best-case pump thrust with Manning drag, without transfer_fraction.

    Assumes all operating pump head could become nozzle velocity. That is an
    intentionally optimistic ceiling, not a prediction of jet or river speed.
    """
    if len(stations) < 2 or len(section_perimeters_m) != len(stations):
        raise ValueError("El límite de impulso requiere secciones y perímetros correspondientes.")
    if len(plan.station_areas_m2) != len(stations) or len(plan.station_manning_n) != len(stations):
        raise ValueError("Las áreas y Manning deben corresponder al DXF.")
    if any(not isfinite(float(p)) or p <= 0 for p in section_perimeters_m):
        raise ValueError("Los perímetros mojados deben ser positivos y finitos.")

    # A loss-free outlet cannot exceed the ideal velocity from the local head.
    operating_head_m = plan.module_head_full_speed_ft * 0.3048 * plan.speed_fraction ** 2
    if operating_head_m <= 0:
        raise ValueError("La altura local de la bomba debe ser positiva.")
    ideal_exit_speed = sqrt(2 * GRAVITY_M_S2 * operating_head_m)
    per_module_q_m3_s = plan.module_flow_full_speed_m3_h * plan.speed_fraction / 3600
    directed_count = sum(max(0.0, cos(radians(angle))) for angle in plan.module_angles_deg)
    ideal_thrust = WATER_DENSITY_KG_M3 * per_module_q_m3_s * ideal_exit_speed * directed_count
    if ideal_thrust <= 0:
        raise ValueError("Las descargas no aportan impulso en sentido horario.")

    # Integrate rho*g*A*Sf*ds with Manning's Sf=(n*q/(A*R^(2/3)))^2.
    # The coefficient is independent of the chosen 2% energy transfer.
    drag_coefficient = 0.0
    for i, (start, end) in enumerate(zip(stations[:-1], stations[1:])):
        ds = float(end["chainage_m"]) - float(start["chainage_m"])
        if ds <= 0:
            raise ValueError("Las estaciones deben avanzar en sentido horario.")
        area = (plan.station_areas_m2[i] + plan.station_areas_m2[i + 1]) / 2
        perimeter = (float(section_perimeters_m[i]) + float(section_perimeters_m[i + 1])) / 2
        manning = (plan.station_manning_n[i] + plan.station_manning_n[i + 1]) / 2
        radius = area / perimeter
        drag_coefficient += ds * manning ** 2 / (area * radius ** (4 / 3))
    if not isfinite(drag_coefficient) or drag_coefficient <= 0:
        raise ValueError("La resistencia del canal debe ser positiva y finita.")
    target_q_m3_s = plan.volume_m3 / (plan.target_lap_min * 60)
    target_drag = WATER_DENSITY_KG_M3 * GRAVITY_M_S2 * drag_coefficient * target_q_m3_s ** 2
    optimistic_q_m3_s = sqrt(ideal_thrust /
                             (WATER_DENSITY_KG_M3 * GRAVITY_M_S2 * drag_coefficient))
    return MomentumBound(
        ideal_thrust_n=ideal_thrust,
        target_drag_n=target_drag,
        target_fraction_of_ideal=target_drag / ideal_thrust,
        optimistic_min_lap_min=plan.volume_m3 / (optimistic_q_m3_s * 60),
        ideal_exit_speed_m_s=ideal_exit_speed,
    )
