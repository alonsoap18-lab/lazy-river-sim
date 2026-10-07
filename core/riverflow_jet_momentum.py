"""Screen Riverflow jet thrust against channel drag without the energy 2%.

This is a steady, depth-averaged *comparison*, not CFD or a calibrated NYA
prediction. The unknown transfer fraction includes mixing, suction momentum,
wall interaction and bend effects that cannot be inferred from pump Q-H alone.
"""

from dataclasses import dataclass
from math import cos, isfinite, pi, radians, sqrt
from typing import Sequence

from core.riverflow_model import RiverflowPlan


FT2_TO_M2 = 0.09290304
NOZZLE_12X7_OPEN_AREA_M2 = 0.2892 * FT2_TO_M2
WATER_DENSITY_KG_M3 = 998.0
GRAVITY_M_S2 = 9.81


@dataclass(frozen=True)
class JetMomentumResult:
    per_unit_flow_m3_h: tuple[float, ...]
    per_unit_exit_speed_m_s: tuple[float, ...]
    gross_directed_thrust_n: float
    assumed_transfer_fraction: float
    applied_thrust_n: float
    drag_coefficient: float
    channel_flow_m3_h: float
    lap_min: float
    target_required_transfer_fraction: float
    target_drag_n: float
    section_speed_m_s: tuple[float, ...]
    current_length_in_speed_band_fraction: float


def nozzle_outlet_k(pipe_diameter_m: float, nozzle_open_area_m2: float,
                    discharge_coefficient: float) -> float:
    """Equivalent outlet K on the pipe velocity, replacing generic outlet K.

    Cd is not in the Riverflow drawings. This is an editable hypothesis, not a
    manufacturer-calibrated nozzle loss or a measured NYA installation.
    """
    if (not all(isfinite(x) for x in (pipe_diameter_m, nozzle_open_area_m2,
                                      discharge_coefficient))
            or pipe_diameter_m <= 0 or nozzle_open_area_m2 <= 0
            or not 0 < discharge_coefficient <= 1):
        raise ValueError("Diámetro, área abierta y Cd deben ser positivos y finitos.")
    pipe_area = pi * pipe_diameter_m ** 2 / 4
    return (pipe_area / (discharge_coefficient * nozzle_open_area_m2)) ** 2


def solve_jet_momentum(stations: Sequence[dict], plan: RiverflowPlan,
                       section_perimeters_m: Sequence[float], *,
                       nozzle_open_area_m2: float = NOZZLE_12X7_OPEN_AREA_M2,
                       transfer_fraction: float = 0.10,
                       speed_band_m_s: tuple[float, float] = (0.25, 0.30)) -> JetMomentumResult:
    """Compare nozzle momentum with integrated Manning drag in a closed loop.

    Total bulk Q is constant around this unbranched loop; Q/A changes by
    section. Relocating a pump cannot increase Q in this model without a
    calibrated position-dependent momentum-transfer law. Placement is screened
    separately by gaps and local resistance, never given a fabricated gain.
    """
    if (len(stations) < 2 or
            any(len(values) != len(stations) for values in
                (section_perimeters_m, plan.station_areas_m2,
                 plan.station_manning_n, plan.station_zones))):
        raise ValueError("Las secciones, áreas, Manning y perímetros deben corresponder.")
    if (not isfinite(nozzle_open_area_m2) or nozzle_open_area_m2 <= 0
            or not isfinite(transfer_fraction) or not 0 < transfer_fraction <= 1
            or not 0 < speed_band_m_s[0] < speed_band_m_s[1]):
        raise ValueError("Área, transferencia y banda de velocidad inválidas.")
    if (len(plan.module_flows_full_speed_m3_h) != plan.active_modules or
            len(plan.module_angles_deg) != plan.active_modules):
        raise ValueError("Los caudales y ángulos deben corresponder a cada unidad.")

    per_unit_q = tuple(q * plan.speed_fraction / 3600
                       for q in plan.module_flows_full_speed_m3_h)
    if any(not isfinite(q) or q <= 0 for q in per_unit_q):
        raise ValueError("El caudal de cada bomba debe ser positivo.")
    exit_speeds = tuple(q / nozzle_open_area_m2 for q in per_unit_q)
    gross_thrust = WATER_DENSITY_KG_M3 * sum(
        q * speed * max(0.0, cos(radians(angle)))
        for q, speed, angle in zip(per_unit_q, exit_speeds,
                                   plan.module_angles_deg))
    if gross_thrust <= 0:
        raise ValueError("Las descargas deben aportar impulso en el sentido del río.")

    drag_coefficient = 0.0
    band_length_m = current_length_m = 0.0
    chainages = [float(station["chainage_m"]) for station in stations]
    for i in range(len(stations) - 1):
        ds = chainages[i + 1] - chainages[i]
        area = (plan.station_areas_m2[i] + plan.station_areas_m2[i + 1]) / 2
        perimeter = (float(section_perimeters_m[i]) +
                     float(section_perimeters_m[i + 1])) / 2
        manning = (plan.station_manning_n[i] + plan.station_manning_n[i + 1]) / 2
        if not all(isfinite(x) and x > 0 for x in (ds, area, perimeter, manning)):
            raise ValueError("Las áreas, perímetros, Manning y progresivas deben ser positivos.")
        radius = area / perimeter
        drag_coefficient += ds * manning ** 2 / (area * radius ** (4 / 3))
    if drag_coefficient <= 0:
        raise ValueError("La resistencia longitudinal debe ser positiva.")

    applied_thrust = transfer_fraction * gross_thrust
    loop_q_m3_s = sqrt(applied_thrust /
                       (WATER_DENSITY_KG_M3 * GRAVITY_M_S2 * drag_coefficient))
    section_speeds = tuple(loop_q_m3_s / area for area in plan.station_areas_m2)
    for i in range(len(stations) - 1):
        if plan.station_zones[i] == "current":
            ds = chainages[i + 1] - chainages[i]
            area = (plan.station_areas_m2[i] + plan.station_areas_m2[i + 1]) / 2
            current_length_m += ds
            if speed_band_m_s[0] <= loop_q_m3_s / area <= speed_band_m_s[1]:
                band_length_m += ds
    target_q_m3_s = plan.volume_m3 / (plan.target_lap_min * 60)
    target_drag = (WATER_DENSITY_KG_M3 * GRAVITY_M_S2 * drag_coefficient
                   * target_q_m3_s ** 2)
    return JetMomentumResult(
        per_unit_flow_m3_h=tuple(q * 3600 for q in per_unit_q),
        per_unit_exit_speed_m_s=exit_speeds,
        gross_directed_thrust_n=gross_thrust,
        assumed_transfer_fraction=transfer_fraction,
        applied_thrust_n=applied_thrust,
        drag_coefficient=drag_coefficient,
        channel_flow_m3_h=loop_q_m3_s * 3600,
        lap_min=plan.volume_m3 / (loop_q_m3_s * 60),
        target_required_transfer_fraction=target_drag / gross_thrust,
        target_drag_n=target_drag,
        section_speed_m_s=section_speeds,
        current_length_in_speed_band_fraction=(
            band_length_m / current_length_m if current_length_m else 0.0),
    )
