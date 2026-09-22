"""Data models for Lazy River hydraulic system."""
from dataclasses import dataclass, field
from typing import List, Optional, Dict
import numpy as np


@dataclass
class Station:
    """Hydraulic station along the centerline."""
    station_id: int
    chainage_m: float
    x: float
    y: float
    tangent_x: float
    tangent_y: float
    normal_x: float
    normal_y: float
    width_m: float = 0.0
    depth_m: float = 0.0
    area_m2: float = 0.0
    hydraulic_radius_m: float = 0.0
    curvature_radius_m: float = 0.0
    curvature_1_m: float = 0.0
    velocity_m_s: float = 0.0
    flow_m3_s: float = 0.0
    energy_m: float = 0.0
    froude_number: float = 0.0
    reynolds_number: float = 0.0


@dataclass
class Jet:
    """Jet propulsor definition."""
    jet_id: int
    station_m: float
    x: float = 0.0
    y: float = 0.0
    flow_m3_s: float = 0.0
    flow_m3_h: float = 0.0
    pressure_pa: float = 0.0
    diameter_m: float = 0.075
    velocity_exit_m_s: float = 0.0
    angle_deg: float = 30.0
    orientation: str = "tangential"
    elevation_m: float = 0.0
    active: bool = True
    vfd: bool = False


@dataclass
class Pump:
    """Pump definition."""
    pump_id: int
    manufacturer: str = ""
    model: str = ""
    flow_m3_h: float = 0.0
    head_m: float = 0.0
    efficiency: float = 0.70
    motor_kw: float = 0.0
    rpm: int = 0
    impeller_mm: float = 0.0
    npshr_m: float = 0.0
    vfd: bool = False
    duty: str = "duty"
    standby: bool = False


@dataclass
class LossComponent:
    """A single loss component."""
    name: str
    type: str  # "friction", "minor", "curve", "jet", "static"
    value_m: float = 0.0
    source: str = "MODEL"
    k_factor: float = 0.0


@dataclass
class Scenario:
    """Operating scenario definition."""
    scenario_id: str
    name: str
    description: str = ""
    people_count: int = 0
    active_jets: List[int] = field(default_factory=list)
    active_pumps: List[int] = field(default_factory=list)
    notes: str = ""


@dataclass
class FieldMeasurement:
    """A single field measurement."""
    timestamp: str = ""
    station_id: int = 0
    chainage_m: float = 0.0
    velocity_m_s: float = 0.0
    depth_m: float = 0.0
    temperature_c: float = 0.0
    flow_m3_h: float = 0.0
    pressure_pa: float = 0.0
    pump_id: int = 0
    jet_state: str = "on"
    people_count: int = 0
    notes: str = ""


@dataclass
class GeometryData:
    """Processed geometry from DXF."""
    outer_wall_coords: List[tuple] = field(default_factory=list)
    inner_wall_coords: List[tuple] = field(default_factory=list)
    centerline_coords: List[tuple] = field(default_factory=list)
    channel_length_m: float = 0.0
    channel_width_avg_m: float = 0.0
    channel_width_min_m: float = 0.0
    channel_width_max_m: float = 0.0
    scale_m_per_unit: float = 1.0
    is_closed: bool = True
    domain_area_m2: float = 0.0


@dataclass
class HydraulicResults:
    """Results from hydraulic analysis."""
    stations: List[Station] = field(default_factory=list)
    velocity_avg_m_s: float = 0.0
    # Distinct from velocity_avg_m_s, which is the spatial arithmetic mean
    # of local station velocities.
    velocity_equivalent_m_s: float = 0.0
    # Design/reporting velocity, exactly linked to the integrated lap time.
    velocity_lap_m_s: float = 0.0
    velocity_min_m_s: float = 0.0
    velocity_max_m_s: float = 0.0
    total_flow_m3_s: float = 0.0
    total_flow_m3_h: float = 0.0
    tdh_m: float = 0.0
    manning_velocity_m_s: float = 0.0
    model_velocity_m_s: float = 0.0
    lap_time_min: float = 0.0
    power_hydraulic_kw: float = 0.0
    power_motor_kw: float = 0.0
    losses: List[LossComponent] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # Commercial power fields
    total_system_tdh_m: float = 0.0
    nozzle_loss_m: float = 0.0
    pipe_friction_m: float = 0.0
    canal_friction_m: float = 0.0
    total_power_watts: float = 0.0
    total_hp: float = 0.0
    pump_hp: float = 0.0
    theoretical_kw: float = 0.0
    pump_head_available_m: float = 0.0
    pump_head_margin_m: float = 0.0


@dataclass
class AlertItem:
    """Safety/alert item."""
    parameter: str
    value: float
    limit: float
    source: str
    status: str  # "NORMAL", "REVIEW", "CRITICAL"
    unit: str = ""
