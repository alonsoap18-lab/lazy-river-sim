"""Transparent Phase-1 Riverflow planning calculations from DXF cross sections.

Riverflow modules recirculate water locally. Their combined pump discharge is
therefore not automatically the through-flow of every channel cross section.
The longitudinal transfer fraction is an explicit, uncalibrated scenario input.
The supplied manufacturer curve provides two labelled H-Q anchors. A local
design-head scenario is interpolated between them; the installed system-curve
intersection, electrical demand, and CFD result remain unverified.
"""

from dataclasses import dataclass
from math import ceil, inf, isfinite, sqrt
from typing import Optional, Sequence


US_GPM_TO_M3_H = 0.22712470704
RIVERFLOW_RATED_GPM = 2440.0
RIVERFLOW_RATED_M3_H = RIVERFLOW_RATED_GPM * US_GPM_TO_M3_H
RIVERFLOW_MOTOR_HP = 10.0
RIVERFLOW_CURVE_POINTS = ((4.0, 2440.0), (10.0, 1220.0))  # ft head, US gpm
# Approximate points read from the supplied raster plot (not manufacturer data).
# The two labelled end points above take precedence over the plotted pixels.
RIVERFLOW_DIGITIZED_POINTS = (
    (4.0, 2440.0), (4.5, 2270.0), (5.35, 2145.0),
    (6.3, 2050.0), (7.0, 1920.0), (7.3, 1720.0),
    (8.0, 1550.0), (9.5, 1380.0), (10.0, 1220.0),
)
GRAVITY_M_S2 = 9.81


def riverflow_flow_at_head_ft(head_ft: float, curve_mode: str = "photo") -> float:
    """Interpolate within the photo trace or between the two labelled anchors."""
    if curve_mode not in {"photo", "anchors"}:
        raise ValueError("Método de curva Riverflow no reconocido.")
    points = RIVERFLOW_DIGITIZED_POINTS if curve_mode == "photo" else RIVERFLOW_CURVE_POINTS
    if not isfinite(head_ft) or not points[0][0] <= head_ft <= points[-1][0]:
        raise ValueError("La TDH local debe estar entre 4 y 10 ft; fuera de la curva anclada no se extrapola.")
    for low, high in zip(points[:-1], points[1:]):
        if low[0] <= head_ft <= high[0]:
            gpm = low[1] + (head_ft - low[0]) * (high[1] - low[1]) / (high[0] - low[0])
            return gpm * US_GPM_TO_M3_H
    return points[-1][1] * US_GPM_TO_M3_H


def composite_manning_n(width_m: float, depth_m: float, floor_n: float, wall_n: float) -> float:
    """HEC-RAS wetted-perimeter composite n for a rectangular section."""
    if any(not isfinite(value) or value <= 0 for value in
           (width_m, depth_m, floor_n, wall_n)):
        raise ValueError("Ancho, profundidad y rugosidades deben ser positivos y finitos.")
    wetted_perimeter = width_m + 2 * depth_m
    return ((width_m * floor_n ** 1.5 + 2 * depth_m * wall_n ** 1.5)
            / wetted_perimeter) ** (2 / 3)


@dataclass(frozen=True)
class RiverflowPlan:
    length_m: float
    volume_m3: float
    current_zone_length_m: float
    calm_zone_length_m: float
    target_lap_min: float
    target_equivalent_flow_m3_h: float
    active_modules: int
    standby_modules: int
    module_head_full_speed_ft: float
    module_flow_full_speed_m3_h: float
    curve_mode: str
    speed_fraction: float
    transfer_fraction: float
    installed_operating_flow_m3_h: float
    equivalent_channel_flow_m3_h: float
    estimated_lap_min: float
    velocity_lap_m_s: float
    velocity_equivalent_m_s: float
    velocity_min_m_s: float
    velocity_max_m_s: float
    current_velocity_min_m_s: float
    current_velocity_max_m_s: float
    filtration_flow_m3_h: float
    manning_n_current: float
    manning_n_calm: float
    station_manning_n: tuple[float, ...]
    channel_friction_head_m: float
    target_channel_friction_head_m: float
    current_lap_min: float
    calm_lap_min: float
    max_froude: float
    cumulative_friction_head_m: tuple[float, ...]
    required_active_modules: int
    active_motor_nameplate_hp: float
    total_motor_nameplate_hp: float
    module_chainages_m: tuple[float, ...]
    max_current_distance_to_module_m: float
    station_velocities_m_s: tuple[float, ...]
    station_zones: tuple[str, ...]


def _module_positions(stations: Sequence[dict], count: int,
                      zones: Sequence[str], manual_chainages: Optional[Sequence[float]]) -> tuple[float, ...]:
    length = float(stations[-1]["chainage_m"])
    if manual_chainages is not None:
        if len(manual_chainages) != count:
            raise ValueError("La cantidad de posiciones debe coincidir con las unidades activas.")
        positions = tuple(float(value) for value in manual_chainages)
        if any(not 0 <= value <= length for value in positions):
            raise ValueError("Las posiciones deben estar dentro de la longitud del DXF.")
        return positions

    eligible = [float(station["chainage_m"]) for station, zone in zip(stations, zones)
                if zone == "current"]
    if len(eligible) < count:
        raise ValueError("No hay suficientes estaciones de corriente para ubicar las unidades.")
    return tuple(eligible[round((i + 0.5) * (len(eligible) - 1) / count)]
                 for i in range(count))


def compute_riverflow_plan(
    stations: Sequence[dict], *, depth_m: float, target_lap_min: float,
    active_modules: int, standby_modules: int = 0,
    module_head_full_speed_ft: float = 4.0,
    speed_fraction: float = 1.0, transfer_fraction: float = 1.0,
    calm_zone_width_m: float = 15.0, filtration_turnover_h: float = 4.0,
    manning_n_current: float = 0.015, manning_n_calm: float = 0.015,
    floor_manning_n: Optional[float] = None,
    wall_manning_n_current: Optional[float] = None,
    wall_manning_n_calm: Optional[float] = None,
    curve_mode: str = "photo",
    module_chainages_m: Optional[Sequence[float]] = None,
) -> RiverflowPlan:
    if len(stations) < 2:
        raise ValueError("El DXF debe producir al menos dos secciones de canal.")
    if any(not isfinite(value) or value <= 0 for value in (depth_m, target_lap_min,
                filtration_turnover_h, manning_n_current, manning_n_calm, calm_zone_width_m)):
        raise ValueError("Profundidad, tiempo, recambio, Manning y ancho de zonas deben ser positivos y finitos.")
    surface_values = (floor_manning_n, wall_manning_n_current, wall_manning_n_calm)
    if any(value is not None for value in surface_values):
        if any(value is None or not isfinite(value) or value <= 0 for value in surface_values):
            raise ValueError("Indique rugosidades positivas para piso y ambas zonas de pared.")
    module_flow_full_speed_m3_h = riverflow_flow_at_head_ft(module_head_full_speed_ft, curve_mode)
    if active_modules < 1 or standby_modules < 0:
        raise ValueError("Debe existir al menos una unidad activa.")
    if not 0 < speed_fraction <= 1 or not 0 < transfer_fraction <= 1:
        raise ValueError("Las fracciones de velocidad y transferencia deben estar entre 0 y 1.")

    zones = tuple("calm" if float(s["width_m"]) >= calm_zone_width_m else "current"
                  for s in stations)
    if any(not isfinite(float(s["width_m"])) or float(s["width_m"]) <= 0 for s in stations):
        raise ValueError("Todas las secciones del DXF deben tener un ancho positivo y finito.")
    station_manning = tuple(
        composite_manning_n(float(station["width_m"]), depth_m, floor_manning_n,
                            wall_manning_n_calm if zone == "calm" else wall_manning_n_current)
        if floor_manning_n is not None else
        (manning_n_calm if zone == "calm" else manning_n_current)
        for station, zone in zip(stations, zones)
    )
    length_m = float(stations[-1]["chainage_m"])
    volume_m3 = 0.0
    calm_length_m = 0.0
    for previous, current, zone in zip(stations[:-1], stations[1:], zones[:-1]):
        ds = float(current["chainage_m"]) - float(previous["chainage_m"])
        if ds < 0:
            raise ValueError("Las estaciones del DXF deben estar ordenadas por recorrido.")
        volume_m3 += ds * (float(previous["width_m"]) + float(current["width_m"])) * depth_m / 2
        if zone == "calm":
            calm_length_m += ds

    # Affinity-law scaling is an estimate; the real flow at each speed depends
    # on the manufacturer H-Q curve and the installed local hydraulic network.
    operating_flow_m3_h = active_modules * module_flow_full_speed_m3_h * speed_fraction
    equivalent_flow_m3_h = operating_flow_m3_h * transfer_fraction
    target_flow_m3_h = volume_m3 * 60 / target_lap_min
    estimated_lap_min = volume_m3 * 60 / equivalent_flow_m3_h if equivalent_flow_m3_h > 0 else inf
    current_lap_min = 0.0
    calm_lap_min = 0.0
    channel_friction_head_m = 0.0
    target_channel_friction_head_m = 0.0
    cumulative_friction = [0.0]
    for previous, current, zone in zip(stations[:-1], stations[1:], zones[:-1]):
        ds = float(current["chainage_m"]) - float(previous["chainage_m"])
        width = (float(previous["width_m"]) + float(current["width_m"])) / 2
        area = width * depth_m
        radius = area / (width + 2 * depth_m)
        n = (station_manning[len(cumulative_friction) - 1] +
             station_manning[len(cumulative_friction)]) / 2
        # Manning friction slope Sf = (n Q / (A R^(2/3)))^2, Q in m³/s.
        friction = ds * (n * equivalent_flow_m3_h / 3600 / (area * radius ** (2 / 3))) ** 2
        target_friction = ds * (n * target_flow_m3_h / 3600 / (area * radius ** (2 / 3))) ** 2
        channel_friction_head_m += friction
        target_channel_friction_head_m += target_friction
        cumulative_friction.append(channel_friction_head_m)
        passage_min = area * ds * 60 / equivalent_flow_m3_h
        if zone == "calm":
            calm_lap_min += passage_min
        else:
            current_lap_min += passage_min
    station_velocities = tuple(equivalent_flow_m3_h / 3600 / (float(s["width_m"]) * depth_m)
                               if float(s["width_m"]) > 0 else 0.0 for s in stations)
    current_velocities = [velocity for velocity, zone in zip(station_velocities, zones)
                          if zone == "current"]
    average_width = volume_m3 / (length_m * depth_m) if length_m > 0 else 0.0
    equivalent_velocity = (equivalent_flow_m3_h / 3600 / (average_width * depth_m)
                           if average_width > 0 else 0.0)
    module_capacity = module_flow_full_speed_m3_h * speed_fraction * transfer_fraction
    required_modules = ceil(target_flow_m3_h / module_capacity) if module_capacity > 0 else 0
    positions = _module_positions(stations, active_modules, zones, module_chainages_m)
    current_distances = [min(min(abs(float(station["chainage_m"]) - position),
                                 length_m - abs(float(station["chainage_m"]) - position))
                             for position in positions)
                         for station, zone in zip(stations, zones) if zone == "current"]

    return RiverflowPlan(
        length_m=length_m, volume_m3=volume_m3,
        current_zone_length_m=length_m - calm_length_m, calm_zone_length_m=calm_length_m,
        target_lap_min=target_lap_min, target_equivalent_flow_m3_h=target_flow_m3_h,
        active_modules=active_modules, standby_modules=standby_modules,
        module_head_full_speed_ft=module_head_full_speed_ft,
        module_flow_full_speed_m3_h=module_flow_full_speed_m3_h,
        curve_mode=curve_mode,
        speed_fraction=speed_fraction, transfer_fraction=transfer_fraction,
        installed_operating_flow_m3_h=operating_flow_m3_h,
        equivalent_channel_flow_m3_h=equivalent_flow_m3_h,
        estimated_lap_min=estimated_lap_min,
        velocity_lap_m_s=length_m / (estimated_lap_min * 60) if estimated_lap_min > 0 else 0.0,
        velocity_equivalent_m_s=equivalent_velocity,
        velocity_min_m_s=min(station_velocities), velocity_max_m_s=max(station_velocities),
        current_velocity_min_m_s=min(current_velocities) if current_velocities else 0.0,
        current_velocity_max_m_s=max(current_velocities) if current_velocities else 0.0,
        filtration_flow_m3_h=volume_m3 / filtration_turnover_h,
        manning_n_current=manning_n_current, manning_n_calm=manning_n_calm,
        station_manning_n=station_manning,
        channel_friction_head_m=channel_friction_head_m,
        target_channel_friction_head_m=target_channel_friction_head_m,
        current_lap_min=current_lap_min, calm_lap_min=calm_lap_min,
        max_froude=max(station_velocities) / sqrt(GRAVITY_M_S2 * depth_m),
        cumulative_friction_head_m=tuple(cumulative_friction),
        required_active_modules=required_modules,
        active_motor_nameplate_hp=active_modules * RIVERFLOW_MOTOR_HP,
        total_motor_nameplate_hp=(active_modules + standby_modules) * RIVERFLOW_MOTOR_HP,
        module_chainages_m=positions, station_velocities_m_s=station_velocities,
        max_current_distance_to_module_m=max(current_distances) if current_distances else 0.0,
        station_zones=zones,
    )
