"""Transparent, independent treatment-train scenario calculations."""

from dataclasses import dataclass
from math import ceil, isfinite, log10, pi


@dataclass(frozen=True)
class FiltrationScenario:
    volume_m3: float
    turnover_h: float
    required_flow_m3_h: float
    active_pumps: int
    required_per_pump_m3_h: float | None
    pump_capacity_m3_h: float | None
    pump_capacity_n_minus_1_m3_h: float | None
    active_filters: int
    filter_area_m2: float | None
    actual_filter_rate_m_h: float | None
    filters_needed_at_limit: int | None
    pump_status: str
    pump_n_minus_1_status: str
    filter_status: str


def _status(available: float | None, required: float) -> str:
    if available is None:
        return "Dato requerido"
    return "Cumple hipótesis" if available >= required - 1e-9 else "No cumple hipótesis"


def evaluate_filtration(volume_m3: float, turnover_h: float, *,
                        installed_pumps: int, standby_pumps: int,
                        standby_auto_start: bool = False,
                        flow_per_pump_at_dirty_head_m3_h: float | None,
                        installed_filters: int, unavailable_filters: int,
                        area_per_filter_m2: float | None,
                        maximum_filter_rate_m_h: float | None) -> FiltrationScenario:
    """Compare deliverable capacity, never infer a pump's curve from required flow."""
    numeric = (volume_m3, turnover_h)
    if any(not isfinite(x) or x <= 0 for x in numeric):
        raise ValueError("Volumen y tiempo de recirculación deben ser positivos.")
    if installed_pumps < 1 or not 0 <= standby_pumps < installed_pumps:
        raise ValueError("La cantidad de bombas activas debe ser positiva.")
    if installed_filters < 0 or not 0 <= unavailable_filters <= installed_filters:
        raise ValueError("Revise la cantidad de filtros disponibles.")
    for value in (flow_per_pump_at_dirty_head_m3_h, area_per_filter_m2,
                  maximum_filter_rate_m_h):
        if value is not None and (not isfinite(value) or value <= 0):
            raise ValueError("Los datos conocidos de equipos deben ser positivos.")
    required = volume_m3 / turnover_h
    active_pumps = installed_pumps - standby_pumps
    active_filters = installed_filters - unavailable_filters
    pump_capacity = (active_pumps * flow_per_pump_at_dirty_head_m3_h
                     if flow_per_pump_at_dirty_head_m3_h is not None else None)
    surviving_pumps = (active_pumps if standby_pumps and standby_auto_start
                       else active_pumps - 1)
    n_minus_1_capacity = (surviving_pumps * flow_per_pump_at_dirty_head_m3_h
                          if flow_per_pump_at_dirty_head_m3_h is not None else None)
    filter_area = (active_filters * area_per_filter_m2
                   if area_per_filter_m2 is not None else None)
    filter_capacity = (filter_area * maximum_filter_rate_m_h
                       if filter_area is not None and maximum_filter_rate_m_h is not None else None)
    actual_rate = (required / filter_area if filter_area and filter_area > 0 else None)
    filter_needed = (ceil(required / (area_per_filter_m2 * maximum_filter_rate_m_h))
                     if area_per_filter_m2 and maximum_filter_rate_m_h else None)
    return FiltrationScenario(
        volume_m3, turnover_h, required, active_pumps,
        required / active_pumps if active_pumps else None,
        pump_capacity, n_minus_1_capacity, active_filters, filter_area,
        actual_rate, filter_needed, _status(pump_capacity, required),
        _status(n_minus_1_capacity, required), _status(filter_capacity, required))


@dataclass(frozen=True)
class BackwashScenario:
    flow_m3_h: float
    wash_volume_m3: float
    rinse_volume_m3: float
    total_event_volume_m3: float


def calculate_backwash(area_per_filter_m2: float, wash_rate_m_h: float,
                       wash_minutes: float, rinse_flow_m3_h: float,
                       rinse_minutes: float, simultaneous_filters: int = 1) -> BackwashScenario:
    values = (area_per_filter_m2, wash_rate_m_h, wash_minutes,
              rinse_flow_m3_h, rinse_minutes)
    if any(not isfinite(x) or x < 0 for x in values) or simultaneous_filters < 1:
        raise ValueError("Los parámetros de lavado deben ser no negativos.")
    flow = area_per_filter_m2 * wash_rate_m_h * simultaneous_filters
    wash_volume = flow * wash_minutes / 60
    rinse_volume = rinse_flow_m3_h * rinse_minutes / 60 * simultaneous_filters
    return BackwashScenario(flow, wash_volume, rinse_volume,
                            wash_volume + rinse_volume)


@dataclass(frozen=True)
class PipeLossScenario:
    velocity_m_s: float
    reynolds: float
    friction_factor: float
    straight_loss_m: float
    fittings_loss_m: float
    total_loss_m: float


def calculate_pipe_losses(flow_m3_h: float, diameter_m: float, length_m: float,
                          roughness_mm: float, fittings_k: float,
                          kinematic_viscosity_m2_s: float = 0.000001) -> PipeLossScenario:
    """Darcy–Weisbach check for one specified line, not an automatic pipe design."""
    values = (flow_m3_h, diameter_m, length_m, roughness_mm,
              fittings_k, kinematic_viscosity_m2_s)
    if any(not isfinite(x) or x < 0 for x in values) or diameter_m <= 0 or kinematic_viscosity_m2_s <= 0:
        raise ValueError("Indique caudal, diámetro y viscosidad válidos.")
    velocity = (flow_m3_h / 3600) / (pi * diameter_m ** 2 / 4)
    reynolds = velocity * diameter_m / kinematic_viscosity_m2_s
    if reynolds == 0:
        factor = 0.0
    elif reynolds < 2300:
        factor = 64 / reynolds
    else:
        turbulent = (-1.8 * log10(((roughness_mm / 1000 / diameter_m) / 3.7) ** 1.11
                                  + 6.9 / reynolds)) ** -2
        if reynolds < 4000:
            blend = (reynolds - 2300) / 1700
            factor = (1 - blend) * 64 / reynolds + blend * turbulent
        else:
            factor = turbulent
    velocity_head = velocity ** 2 / (2 * 9.81)
    straight = factor * length_m / diameter_m * velocity_head
    fittings = fittings_k * velocity_head
    return PipeLossScenario(velocity, reynolds, factor, straight, fittings,
                            straight + fittings)
