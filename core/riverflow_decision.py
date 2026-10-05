"""Decision-facing Riverflow sensitivity and internal-consistency checks.

The three cases are illustrative assumptions, not statistical bounds or
manufacturer performance guarantees. They all reuse the same DXF geometry.
"""

from dataclasses import dataclass
from math import isclose
from typing import Optional, Sequence

from core.beach_geometry import BeachGeometry
from core.riverflow_2d import RiverflowField2D, compute_field_2d
from core.riverflow_model import RiverflowPlan, compute_riverflow_plan


@dataclass(frozen=True)
class DecisionCase:
    name: str
    energy_factor: float
    plan: Optional[RiverflowPlan]
    field: Optional[RiverflowField2D]
    error: Optional[str] = None

    @property
    def slow_lap_min(self) -> Optional[float]:
        return max(self.field.lane_lap_min) if self.field is not None else None


@dataclass(frozen=True)
class CountOption:
    """One count/layout with illustrative half-to-double coupling sensitivity."""

    plan: RiverflowPlan
    field: RiverflowField2D
    slow_lap_low_transfer_min: float
    slow_lap_nominal_min: float
    slow_lap_high_transfer_min: float
    max_module_spacing_m: float


def evaluate_count_options(
    stations: Sequence[dict], *, counts: Sequence[int], current_plan: RiverflowPlan,
    current_field: RiverflowField2D, depth_m: float, scale_m_per_unit: float,
    calm_zone_width_m: float, floor_manning_n: float,
    wall_manning_n_current: float, wall_manning_n_calm: float,
    filtration_turnover_h: float,
    beach_geometry: Optional[BeachGeometry] = None,
) -> tuple[CountOption, ...]:
    """Compare unit counts without claiming a verified procurement quantity.

    The current row preserves manual positions and angles. Alternative counts
    use the existing automatic placement rule and aligned outlets. For a fixed
    layout, Q scales with the cube root of assumed useful-energy transfer;
    therefore all 2D lane times scale with its inverse cube root.
    """
    if not counts or any(count < 1 or count > 60 for count in counts):
        raise ValueError("Compare entre 1 y 60 unidades activas.")
    options = []
    for count in dict.fromkeys(counts):
        if count == current_plan.active_modules:
            plan, field = current_plan, current_field
        else:
            plan = compute_riverflow_plan(
                stations, depth_m=depth_m, target_lap_min=current_plan.target_lap_min,
                active_modules=count, standby_modules=current_plan.standby_modules,
                module_head_full_speed_ft=current_plan.module_head_full_speed_ft,
                module_flow_full_speed_override_m3_h=current_plan.module_flow_full_speed_m3_h,
                speed_fraction=current_plan.speed_fraction,
                transfer_fraction=current_plan.transfer_fraction,
                calm_zone_width_m=calm_zone_width_m,
                filtration_turnover_h=filtration_turnover_h,
                floor_manning_n=floor_manning_n,
                wall_manning_n_current=wall_manning_n_current,
                wall_manning_n_calm=wall_manning_n_calm,
                curve_mode=current_plan.curve_mode, beach_geometry=beach_geometry)
            field = compute_field_2d(
                stations, plan, depth_m, scale_m_per_unit=scale_m_per_unit)
        nominal = max(field.lane_lap_min)
        positions = sorted(plan.module_chainages_m)
        gaps = [b - a for a, b in zip(positions, positions[1:])]
        gaps.append(positions[0] + plan.length_m - positions[-1])
        options.append(CountOption(
            plan=plan, field=field,
            slow_lap_low_transfer_min=nominal * 2 ** (1 / 3),
            slow_lap_nominal_min=nominal,
            slow_lap_high_transfer_min=nominal / 2 ** (1 / 3),
            max_module_spacing_m=max(gaps)))
    return tuple(options)


def evaluate_decision_cases(
    stations: Sequence[dict], *, current_plan: RiverflowPlan,
    current_field: RiverflowField2D, depth_m: float, scale_m_per_unit: float,
    calm_zone_width_m: float,
    floor_manning_n: float, wall_manning_n_current: float,
    wall_manning_n_calm: float, filtration_turnover_h: float,
    beach_geometry: Optional[BeachGeometry] = None,
) -> tuple[DecisionCase, DecisionCase, DecisionCase]:
    """Hold count, RPM, local circuit, layout, DXF and treatment fixed.

    Only the unmeasured longitudinal useful-energy fraction varies. K and
    other circuit uncertainties are explored separately in Escenarios.
    """
    cases = []
    for name, energy_factor in (
        ("Conservador", 0.5),
        ("Configuración actual", 1.0),
        ("Favorable", 2.0),
    ):
        if name == "Configuración actual":
            cases.append(DecisionCase(name, energy_factor, current_plan,
                                      current_field))
            continue
        try:
            plan = compute_riverflow_plan(
                stations, depth_m=depth_m,
                target_lap_min=current_plan.target_lap_min,
                active_modules=current_plan.active_modules,
                standby_modules=current_plan.standby_modules,
                module_head_full_speed_ft=current_plan.module_head_full_speed_ft,
                module_flow_full_speed_override_m3_h=current_plan.module_flow_full_speed_m3_h,
                speed_fraction=current_plan.speed_fraction,
                transfer_fraction=current_plan.transfer_fraction * energy_factor,
                calm_zone_width_m=calm_zone_width_m,
                filtration_turnover_h=filtration_turnover_h,
                floor_manning_n=floor_manning_n,
                wall_manning_n_current=wall_manning_n_current,
                wall_manning_n_calm=wall_manning_n_calm,
                curve_mode=current_plan.curve_mode,
                module_chainages_m=current_plan.module_chainages_m,
                module_angles_deg=current_plan.module_angles_deg,
                beach_geometry=beach_geometry)
            field = compute_field_2d(
                stations, plan, depth_m, scale_m_per_unit=scale_m_per_unit)
            cases.append(DecisionCase(name, energy_factor, plan, field))
        except ValueError as exc:
            cases.append(DecisionCase(name, energy_factor, None, None, str(exc)))
    return tuple(cases)


def consistency_checks(plan: RiverflowPlan, turnover_h: float) -> tuple[tuple[str, bool], ...]:
    """Arithmetic reconciliation only; passing does not validate physical assumptions."""
    return (
        ("Descarga local = unidades × caudal por unidad × RPM relativa",
         isclose(plan.installed_operating_flow_m3_h,
                 plan.active_modules * plan.module_flow_full_speed_m3_h
                 * plan.speed_fraction, rel_tol=1e-9)),
        ("Vuelta volumétrica = volumen ÷ corriente longitudinal",
         isclose(plan.estimated_lap_min,
                 plan.volume_m3 * 60 / plan.equivalent_channel_flow_m3_h,
                 rel_tol=1e-9)),
        ("Caudal de filtración = volumen ÷ horas de recirculación",
         isclose(plan.filtration_flow_m3_h, plan.volume_m3 / turnover_h,
                 rel_tol=1e-9)),
        ("Caudal meta = volumen ÷ tiempo objetivo",
         isclose(plan.target_equivalent_flow_m3_h,
                 plan.volume_m3 * 60 / plan.target_lap_min,
                 rel_tol=1e-9)),
    )
