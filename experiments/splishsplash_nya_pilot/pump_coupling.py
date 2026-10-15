"""Traceable, bounded Riverflow reference point for the isolated SPH trial.

The calibrated system curve represents the *published example arrangement*,
not installed NYA pipework. Seven ports are represented by their documented
aggregate open area because individual bore areas are not supplied.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite

from core.riverflow_model import US_GPM_TO_M3_H, riverflow_flow_at_head_ft

FT2_TO_M2 = 0.09290304
REFERENCE_FLOW_GPM = 2014.0
REFERENCE_HEAD_FT = 6.5
TOTAL_SEVEN_PORT_AREA_M2 = 0.2892 * FT2_TO_M2
EACH_SUCTION_BOX_AREA_M2 = 1.169 * FT2_TO_M2
REFERENCE_SUCTION_PIPE_M = 27.42 * 0.3048
REFERENCE_DISCHARGE_PIPE_M = 35.67 * 0.3048


@dataclass(frozen=True)
class CoupledPoint:
    speed_fraction: float
    reference_system_head_factor: float
    pump_flow_m3_h: float
    pump_head_ft: float
    system_head_ft: float
    aggregate_nozzle_speed_m_s: float
    each_suction_box_flow_m3_h: float
    each_suction_box_face_speed_m_s: float
    particle_volume_m3: float
    nominal_particle_transfer_interval_s: float

    def as_dict(self) -> dict:
        return asdict(self)


def solve_reference_coupling(*, speed_fraction: float = 1.0,
                             system_head_factor: float = 1.0,
                             particle_spacing_m: float = 0.5,
                             depth_m: float = 1.2) -> CoupledPoint:
    """Intersect published H-Q with a *reference-calibrated* H∝Q² curve.

    Affinity scaling for reduced VFD speed and the system-head multiplier are
    explicit hypotheses. Returns an error if the intersection falls outside
    the documented full-speed curve interval; it never extrapolates a pump.
    """
    values = (speed_fraction, system_head_factor, particle_spacing_m, depth_m)
    if not all(isfinite(x) and x > 0 for x in values) or speed_fraction > 1:
        raise ValueError("VFD, pérdidas, resolución y profundidad deben ser positivos.")
    q_ref = REFERENCE_FLOW_GPM * US_GPM_TO_M3_H
    low = riverflow_flow_at_head_ft(10, "photo") * speed_fraction
    high = riverflow_flow_at_head_ft(4, "photo") * speed_fraction

    def residual(q: float) -> float:
        full_speed_q = q / speed_fraction
        # Inverse H-Q lookup, bounded to the documented 4-10 ft range.
        head_lo, head_hi = 4.0, 10.0
        for _ in range(50):
            mid = (head_lo + head_hi) / 2
            if riverflow_flow_at_head_ft(mid, "photo") > full_speed_q:
                head_lo = mid
            else:
                head_hi = mid
        pump_head = (head_lo + head_hi) / 2 * speed_fraction ** 2
        system_head = (REFERENCE_HEAD_FT * system_head_factor *
                       (q / q_ref) ** 2)
        return pump_head - system_head

    if residual(low) < 0 or residual(high) > 0:
        raise ValueError("No hay intersección dentro de la curva H-Q documentada.")
    for _ in range(60):
        mid = (low + high) / 2
        if residual(mid) > 0:
            low = mid
        else:
            high = mid
    q = (low + high) / 2
    head = REFERENCE_HEAD_FT * system_head_factor * (q / q_ref) ** 2
    particle_volume = particle_spacing_m ** 2 * depth_m
    return CoupledPoint(
        speed_fraction=speed_fraction,
        reference_system_head_factor=system_head_factor,
        pump_flow_m3_h=q,
        pump_head_ft=head,
        system_head_ft=head,
        aggregate_nozzle_speed_m_s=(q / 3600) / TOTAL_SEVEN_PORT_AREA_M2,
        each_suction_box_flow_m3_h=q / 2,
        each_suction_box_face_speed_m_s=(q / 3600 / 2) / EACH_SUCTION_BOX_AREA_M2,
        particle_volume_m3=particle_volume,
        nominal_particle_transfer_interval_s=particle_volume / (q / 3600),
    )
