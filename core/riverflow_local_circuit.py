"""Scenario-only local Riverflow circuit and bounded pump-curve intersection.

The manufacturer's reference drawing suggests 12-inch PVC and dual suction,
but does not supply the installed lengths, internal diameters or loss factors
for NYA. Every such quantity remains an explicit scenario input.
"""

from dataclasses import dataclass
from math import isfinite, log10, pi

from core.riverflow_model import (RIVERFLOW_CURVE_POINTS,
                                  US_GPM_TO_M3_H, riverflow_flow_at_head_ft)

G = 9.81
FT_TO_M = 0.3048
# Westlake's published 12-inch Sch 40 ID is 11.938 in. Other suppliers may vary.
PVC_12_SCH40_REFERENCE_ID_M = 11.938 * .0254


@dataclass(frozen=True)
class LocalCircuit:
    suction_length_m: float
    suction_diameter_m: float
    discharge_length_m: float
    discharge_diameter_m: float
    suction_k: float
    discharge_k: float
    outlet_k: float
    static_head_m: float = 0.0
    roughness_mm: float = 0.0015  # smooth-PVC scenario, not a NYA measurement
    water_nu_m2_s: float = 0.000000893


@dataclass(frozen=True)
class CircuitOperatingPoint:
    flow_m3_h: float
    pump_head_ft: float
    system_head_ft: float
    suction_friction_m: float
    discharge_friction_m: float
    fittings_m: float
    outlet_m: float
    suction_velocity_m_s: float
    discharge_velocity_m_s: float


def _pipe_loss(q_m3_s: float, length_m: float, diameter_m: float,
               roughness_mm: float, nu_m2_s: float) -> tuple[float, float]:
    velocity = 4 * q_m3_s / (pi * diameter_m ** 2)
    if q_m3_s == 0:
        return 0.0, 0.0
    reynolds = velocity * diameter_m / nu_m2_s
    if reynolds < 2300:
        friction = 64 / reynolds
    else:
        # Explicit Haaland approximation to turbulent Darcy friction factor.
        friction = (-1.8 * log10(((roughness_mm / 1000 / diameter_m) / 3.7) ** 1.11
                                  + 6.9 / reynolds)) ** -2
    return friction * length_m / diameter_m * velocity ** 2 / (2 * G), velocity


def circuit_head(q_m3_h: float, circuit: LocalCircuit) -> CircuitOperatingPoint:
    values = (q_m3_h, circuit.suction_length_m, circuit.suction_diameter_m,
              circuit.discharge_length_m, circuit.discharge_diameter_m,
              circuit.suction_k, circuit.discharge_k, circuit.outlet_k,
              circuit.static_head_m, circuit.roughness_mm, circuit.water_nu_m2_s)
    if any(not isfinite(v) for v in values) or q_m3_h < 0 or any(v < 0 for v in
            (circuit.suction_length_m, circuit.discharge_length_m,
             circuit.suction_k, circuit.discharge_k, circuit.outlet_k,
             circuit.static_head_m, circuit.roughness_mm)) or any(v <= 0 for v in
            (circuit.suction_diameter_m, circuit.discharge_diameter_m,
             circuit.water_nu_m2_s)):
        raise ValueError("Los datos del circuito deben ser finitos; diámetros y viscosidad positivos.")
    q = q_m3_h / 3600
    suction, vs = _pipe_loss(q, circuit.suction_length_m,
                             circuit.suction_diameter_m, circuit.roughness_mm,
                             circuit.water_nu_m2_s)
    discharge, vd = _pipe_loss(q, circuit.discharge_length_m,
                               circuit.discharge_diameter_m, circuit.roughness_mm,
                               circuit.water_nu_m2_s)
    fittings = (circuit.suction_k * vs ** 2 +
                circuit.discharge_k * vd ** 2) / (2 * G)
    outlet = circuit.outlet_k * vd ** 2 / (2 * G)
    head_m = circuit.static_head_m + suction + discharge + fittings + outlet
    return CircuitOperatingPoint(q_m3_h, 0.0, head_m / FT_TO_M, suction,
                                 discharge, fittings, outlet, vs, vd)


def _pump_head_at_flow_ft(q_full_m3_h: float, curve_mode: str) -> float:
    lo, hi = RIVERFLOW_CURVE_POINTS[0][0], RIVERFLOW_CURVE_POINTS[-1][0]
    for _ in range(55):
        mid = (lo + hi) / 2
        if riverflow_flow_at_head_ft(mid, curve_mode) > q_full_m3_h:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def solve_local_circuit(circuit: LocalCircuit, *, speed_fraction: float = 1.0,
                        curve_mode: str = "photo") -> CircuitOperatingPoint:
    """Intersect the speed-scaled H-Q curve with the assumed system curve.

    Returns no point rather than extrapolating beyond the supplied 4–10 ft
    full-speed curve. Affinity scaling below full speed is only a hypothesis.
    """
    if not isfinite(speed_fraction) or not 0 < speed_fraction <= 1:
        raise ValueError("La fracción del variador debe estar entre 0 y 1.")
    q_low = riverflow_flow_at_head_ft(10, curve_mode) * speed_fraction
    q_high = riverflow_flow_at_head_ft(4, curve_mode) * speed_fraction

    def residual(q: float) -> float:
        pump_head = _pump_head_at_flow_ft(q / speed_fraction, curve_mode) * speed_fraction ** 2
        return pump_head - circuit_head(q, circuit).system_head_ft

    if residual(q_low) < 0 or residual(q_high) > 0:
        raise ValueError("El circuito supuesto no cruza la curva Riverflow dentro del intervalo publicado "
                         "(4–10 ft a plena velocidad). Revise longitudes, pérdidas y velocidad; "
                         "no se extrapola una selección de bomba.")
    for _ in range(55):
        q_mid = (q_low + q_high) / 2
        if residual(q_mid) > 0:
            q_low = q_mid
        else:
            q_high = q_mid
    q = (q_low + q_high) / 2
    point = circuit_head(q, circuit)
    head = _pump_head_at_flow_ft(q / speed_fraction, curve_mode) * speed_fraction ** 2
    return CircuitOperatingPoint(point.flow_m3_h, head, point.system_head_ft,
                                 point.suction_friction_m, point.discharge_friction_m,
                                 point.fittings_m, point.outlet_m,
                                 point.suction_velocity_m_s, point.discharge_velocity_m_s)
