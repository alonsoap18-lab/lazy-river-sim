"""Preliminary seven-port Riverflow outlet scenario, not a jet CFD model.

Three larger ports are horizontal per the manufacturer's installation detail.
Individual bore diameters, discharge coefficient and NYA plumbing are not
provided by that drawing; they remain explicit scenario assumptions here.
All seven outlets share one plenum pressure and one discharge coefficient,
so their *exit speed* is equal while their *flows* scale with bore area.
"""

from dataclasses import dataclass
from math import isfinite, pi

from core.riverflow_local_circuit import (
    G, LocalCircuit, PVC_12_SCH40_REFERENCE_ID_M, solve_local_circuit,
)


@dataclass(frozen=True)
class SevenPortScenario:
    large_bore_m: float = .100  # hypothesis, NOT a Riverflow dimension
    small_bore_m: float = .075  # hypothesis, NOT a Riverflow dimension
    discharge_coefficient: float = .85  # sensitivity input, NOT measured
    speed_fraction: float = 1.0
    suction_length_m: float = 8.0
    discharge_length_m: float = 8.0
    suction_k: float = 1.0
    discharge_k: float = 1.0


@dataclass(frozen=True)
class SevenPortResult:
    module_flow_m3_h: float
    pump_head_ft: float
    nozzle_required_head_m: float
    nozzle_kinetic_head_m: float
    exit_speed_m_s: float
    large_port_flow_m3_h: float
    small_port_flow_m3_h: float
    total_open_area_m2: float
    equivalent_nozzle_k: float


def solve_seven_port(scenario: SevenPortScenario) -> SevenPortResult:
    inputs = (scenario.large_bore_m, scenario.small_bore_m,
              scenario.discharge_coefficient, scenario.speed_fraction,
              scenario.suction_length_m, scenario.discharge_length_m,
              scenario.suction_k, scenario.discharge_k)
    if (any(not isfinite(value) for value in inputs)
            or not 0 < scenario.small_bore_m <= scenario.large_bore_m < .2
            or not 0 < scenario.discharge_coefficient <= 1
            or not 0 < scenario.speed_fraction <= 1
            or min(scenario.suction_length_m, scenario.discharge_length_m,
                   scenario.suction_k, scenario.discharge_k) < 0):
        raise ValueError("Diámetros, Cd, VFD, longitudes o pérdidas del escenario inválidos.")
    large_area = pi * scenario.large_bore_m ** 2 / 4
    small_area = pi * scenario.small_bore_m ** 2 / 4
    total_area = 3 * large_area + 4 * small_area
    pipe_area = pi * PVC_12_SCH40_REFERENCE_ID_M ** 2 / 4
    # Common pressure across parallel ports: Q = Cd * A_total * sqrt(2*g*H).
    # The equivalent K replaces, rather than adds to, the generic outlet K.
    nozzle_k = (pipe_area / (scenario.discharge_coefficient * total_area)) ** 2
    circuit = LocalCircuit(
        scenario.suction_length_m, PVC_12_SCH40_REFERENCE_ID_M,
        scenario.discharge_length_m, PVC_12_SCH40_REFERENCE_ID_M,
        scenario.suction_k, scenario.discharge_k, nozzle_k)
    operating = solve_local_circuit(
        circuit, speed_fraction=scenario.speed_fraction, curve_mode="photo")
    q_m3_s = operating.flow_m3_h / 3600
    speed = q_m3_s / total_area
    return SevenPortResult(
        module_flow_m3_h=operating.flow_m3_h,
        pump_head_ft=operating.pump_head_ft,
        nozzle_required_head_m=operating.outlet_m,
        nozzle_kinetic_head_m=speed ** 2 / (2 * G),
        exit_speed_m_s=speed,
        large_port_flow_m3_h=operating.flow_m3_h * large_area / total_area,
        small_port_flow_m3_h=operating.flow_m3_h * small_area / total_area,
        total_open_area_m2=total_area,
        equivalent_nozzle_k=nozzle_k)
