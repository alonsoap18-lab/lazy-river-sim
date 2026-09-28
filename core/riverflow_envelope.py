"""Bounded Riverflow sensitivity matrix; not a pump procurement selector.

All viable rows use the same DXF, beach volume, Manning resistance and
depth-averaged 2D field as the interactive Riverflow model. Pump points come
only from the supplied 4–10 ft full-speed curve (with explicitly approximate
affinity scaling for other speeds). Rows outside that curve stay unavailable.
"""

from dataclasses import dataclass, replace
from typing import Optional, Sequence

from core.beach_geometry import BeachGeometry
from core.riverflow_2d import compute_field_2d
from core.riverflow_local_circuit import LocalCircuit, solve_local_circuit
from core.riverflow_model import (RIVERFLOW_MOTOR_HP, compute_riverflow_plan,
                                  scenario_channel_flow_m3_h)


@dataclass(frozen=True)
class EnvelopeRow:
    modules: int
    speed_pct: int
    k_factor: float
    status: str
    module_flow_m3_h: Optional[float] = None
    module_head_ft: Optional[float] = None
    pump_hydraulic_kw_per_unit: Optional[float] = None
    channel_flow_m3_h: Optional[float] = None
    volumetric_lap_min: Optional[float] = None
    slow_lane_lap_min: Optional[float] = None


def evaluate_envelope(
    stations: Sequence[dict], circuit: LocalCircuit, *, depth_m: float,
    target_lap_min: float, module_counts: Sequence[int],
    speeds_pct: Sequence[int], k_factors: Sequence[float],
    transfer_fraction: float, curve_mode: str, calm_zone_width_m: float,
    floor_manning_n: float, wall_manning_n_current: float,
    wall_manning_n_calm: float, beach_geometry: Optional[BeachGeometry],
    scale_m_per_unit: float = 1.0,
    current_modules: Optional[int] = None,
    current_positions_m: Optional[Sequence[float]] = None,
    current_angles_deg: Optional[Sequence[float]] = None,
) -> tuple[EnvelopeRow, ...]:
    if not module_counts or not speeds_pct or not k_factors:
        raise ValueError("La matriz necesita unidades, velocidades y factores K.")
    if any(n < 1 for n in module_counts) or any(not 0 < s <= 100 for s in speeds_pct):
        raise ValueError("Unidades y velocidades de la matriz fuera de rango.")
    if any(k <= 0 for k in k_factors):
        raise ValueError("Los factores K deben ser positivos.")

    # Calculate geometry/placement once per count. Lane times scale as 1/Q:
    # the 2D streamfunction shape is unchanged for a fixed module layout.
    layouts = {}
    for count in dict.fromkeys(module_counts):
        preserve_manual = count == current_modules
        reference = compute_riverflow_plan(
            stations, depth_m=depth_m, target_lap_min=target_lap_min,
            active_modules=count, module_head_full_speed_ft=4.0,
            speed_fraction=1.0, transfer_fraction=transfer_fraction,
            calm_zone_width_m=calm_zone_width_m,
            floor_manning_n=floor_manning_n,
            wall_manning_n_current=wall_manning_n_current,
            wall_manning_n_calm=wall_manning_n_calm,
            curve_mode=curve_mode, beach_geometry=beach_geometry,
            module_chainages_m=(current_positions_m if preserve_manual else None),
            module_angles_deg=(current_angles_deg if preserve_manual else None),
        )
        field = compute_field_2d(stations, reference, depth_m,
                                 scale_m_per_unit=scale_m_per_unit)
        layouts[count] = (reference, max(field.lane_lap_min))

    points = {}
    for speed_pct in dict.fromkeys(speeds_pct):
        for k_factor in dict.fromkeys(k_factors):
            case = replace(circuit,
                           suction_k=circuit.suction_k * k_factor,
                           discharge_k=circuit.discharge_k * k_factor,
                           outlet_k=circuit.outlet_k * k_factor)
            try:
                points[(speed_pct, k_factor)] = solve_local_circuit(
                    case, speed_fraction=speed_pct / 100, curve_mode=curve_mode)
            except ValueError:
                points[(speed_pct, k_factor)] = None

    rows = []
    for count in module_counts:
        reference, reference_slow_lane = layouts[count]
        for speed_pct in speeds_pct:
            speed = speed_pct / 100
            for k_factor in k_factors:
                point = points[(speed_pct, k_factor)]
                if point is None:
                    rows.append(EnvelopeRow(count, speed_pct, k_factor, "Fuera de curva disponible"))
                    continue
                normalized_pump_flow = point.flow_m3_h / speed
                q_channel = scenario_channel_flow_m3_h(
                    reference.channel_resistance_s2_m5, normalized_pump_flow,
                    count, speed, transfer_fraction,
                    reference.placement_effectiveness)
                lap = reference.volume_m3 * 60 / q_channel
                slow_lane = reference_slow_lane * reference.equivalent_channel_flow_m3_h / q_channel
                hydraulic_kw = (998.0 * 9.81 * point.flow_m3_h / 3600 *
                                point.pump_head_ft * .3048 / 1000)
                status = ("Potencia hidráulica > placa; revisar" if
                          hydraulic_kw > RIVERFLOW_MOTOR_HP * .7457 else
                          "Meta en escenario" if slow_lane <= target_lap_min else
                          "No alcanza meta en escenario")
                rows.append(EnvelopeRow(
                    count, speed_pct, k_factor, status,
                    point.flow_m3_h, point.pump_head_ft, hydraulic_kw,
                    q_channel, lap, slow_lane))
    return tuple(rows)
