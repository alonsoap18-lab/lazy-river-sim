"""Main orchestrator - ties all modules together."""
import numpy as np
from typing import List, Dict, Tuple, Optional

from core.dxf_loader import DXFLoader
from core.centerline import CenterlineBuilder
from core.hydraulics import HydraulicEngine
from core.propulsion import PropulsionEngine
from core.pumps import PumpModel
from core.people import PeopleModel
from core.scenarios import ScenarioEngine
from core.validation import ValidationEngine
from core.safety import SafetyEngine
from core.field_data import FieldDataLoader
from models.geometry_model import (
    GeometryData, HydraulicResults, Station, Jet, Pump,
    LossComponent, AlertItem, FieldMeasurement
)


class LazyRiverModel:
    """Selvatura NYA - Lazy River Hydraulic Digital Model."""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.geometry: Optional[GeometryData] = None
        self.loader: Optional[DXFLoader] = None
        self.centerline_builder: Optional[CenterlineBuilder] = None
        self.hydraulics: Optional[HydraulicEngine] = None
        self.propulsion: Optional[PropulsionEngine] = None
        self.pumps: Optional[PumpModel] = None
        self.people: Optional[PeopleModel] = None
        self.scenarios: Optional[ScenarioEngine] = None
        self.validation: Optional[ValidationEngine] = None
        self.safety: Optional[SafetyEngine] = None
        self.field_loader: Optional[FieldDataLoader] = None

        self.stations: List[dict] = []
        self.hydraulic_stations: List[Station] = []
        self.results: Optional[HydraulicResults] = None

        self._init_modules()

    def _init_modules(self):
        self.propulsion = PropulsionEngine()
        self.pumps = PumpModel()
        self.people = PeopleModel()
        self.scenarios = ScenarioEngine()
        self.validation = ValidationEngine()
        self.safety = SafetyEngine()
        self.field_loader = FieldDataLoader()

    def load_dxf(self, path: str = None, content: bytes = None) -> List[str]:
        issues = []
        self.loader = DXFLoader(dxf_path=path, dxf_content=content)

        if self.loader.errors:
            return self.loader.errors

        issues.extend(self.loader.warnings)
        issues.extend(self.loader.validate())

        self.geometry = GeometryData(
            outer_wall_coords=self.loader.get_outer_coords(),
            inner_wall_coords=self.loader.get_inner_coords(),
            is_closed=True,
        )

        return issues

    def build_centerline(self, resolution_m: float = 0.5,
                          target_length_m: float = None) -> float:
        """Build centerline from DXF geometry.

        Width always comes from the DXF (isotropic scaling).
        To override width, scale stations['width_m'] after calling this method.
        """
        if not self.loader or not self.loader.outer_wall:
            return 0.0

        self.centerline_builder = CenterlineBuilder(
            self.loader.outer_wall,
            self.loader.inner_wall,
            resolution_m=resolution_m,
        )

        self.centerline_builder.build()
        self.stations = self.centerline_builder.get_station_data()

        # Raw DXF-unit dimensions
        raw_length = self.stations[-1]['chainage_m'] if self.stations else 0

        # Scale factor: isotropic (same for length and width)
        # Width always comes from DXF geometry, never from a user-typed number
        length_scale = 1.0
        if target_length_m and raw_length > 0:
            length_scale = target_length_m / raw_length

        # Apply scale to stations (isotropic — preserves DXF width ratios)
        for s in self.stations:
            s['chainage_m'] *= length_scale
            s['width_m'] *= length_scale

        self.geometry.centerline_coords = [
            (s['x'], s['y']) for s in self.stations
        ]
        self.geometry.channel_length_m = self.stations[-1]['chainage_m'] if self.stations else 0
        self.geometry.channel_width_avg_m = np.mean([s['width_m'] for s in self.stations]) if self.stations else 0
        self.geometry.channel_width_min_m = min([s['width_m'] for s in self.stations]) if self.stations else 0
        self.geometry.channel_width_max_m = max([s['width_m'] for s in self.stations]) if self.stations else 0
        self.geometry.scale_m_per_unit = length_scale

        if self.loader.domain_polygon:
            self.geometry.domain_area_m2 = self.loader.domain_polygon.area * (length_scale ** 2)

        return self.geometry.channel_length_m

    def compute_hydraulics(self, depth_m: float = 1.20, manning_n: float = 0.015,
                            target_velocity: float = None,
                            target_lap_time_min: float = None,
                            pump_flow_m3_h: float = None,
                            n_jets: int = 8, jet_diameter_m: float = 0.075,
                            pump_efficiency: float = 0.70,
                            n_pumps: int = 2,
                            safety_factor: float = 1.15,
                            n_pump_rooms: int = 1,
                            water_temp_c: float = 25.0,
                            pump_head_available_m: float = None) -> HydraulicResults:
        if not self.stations:
            self.results = HydraulicResults()
            return self.results

        self.hydraulics = HydraulicEngine(
            self.stations,
            depth_m=depth_m,
            manning_n=manning_n,
            temperature_c=water_temp_c,
        )

        # === STEP 1: Determine velocity from pump flow ===
        # V = Q_pump / A_channel
        # This is the fundamental relationship: pump flow drives velocity
        channel_area = self.geometry.channel_width_avg_m * depth_m

        if target_lap_time_min and target_lap_time_min > 0:
            # Q is selected to meet the requested full-lap transit time.
            # With continuity, dt = A(s) ds / Q, so integrating the actual
            # DXF-derived section area is more accurate than L / (Q/A_avg).
            volume_per_lap_m3 = 0.0
            for i in range(1, len(self.stations)):
                ds = self.stations[i]['chainage_m'] - self.stations[i - 1]['chainage_m']
                area_0 = self.stations[i - 1]['width_m'] * depth_m
                area_1 = self.stations[i]['width_m'] * depth_m
                volume_per_lap_m3 += max(0.0, ds) * (area_0 + area_1) / 2
            target_seconds = target_lap_time_min * 60.0
            Q_m3s = volume_per_lap_m3 / target_seconds if target_seconds > 0 else 0.0
            velocity = Q_m3s / channel_area if channel_area > 0 else 0.3
        elif pump_flow_m3_h and pump_flow_m3_h > 0:
            # Velocity is DRIVEN by pump flow
            Q_m3s = pump_flow_m3_h / 3600.0
            velocity = Q_m3s / channel_area if channel_area > 0 else 0.3
        elif target_velocity:
            # Fallback: use target velocity to calculate required flow
            velocity = target_velocity
        else:
            # Fallback: Manning velocity (gravity-driven, not realistic for lazy river)
            avg_rh = np.mean([
                s['width_m'] * depth_m / (s['width_m'] + 2 * depth_m)
                if (s['width_m'] + 2 * depth_m) > 0 else 0
                for s in self.stations
            ])
            velocity = self.hydraulics.manning_velocity(avg_rh)

        # Total flow in the channel
        Q_required_m3s = velocity * channel_area
        Q_required_m3h = Q_required_m3s * 3600

        total_length = self.stations[-1]['chainage_m'] if self.stations else 1.0

        # === STEP 1.5: Pre-calculate pipe parameters for jet model ===
        # These are needed for individual jet pressure calculations
        n_pipes = max(n_pumps, 2)
        pipe_length_factor = 0.20 / n_pump_rooms
        pipe_suction = 30.0 / n_pump_rooms
        pipe_length_estimate = total_length * pipe_length_factor + pipe_suction
        pipe_length_estimate = min(pipe_length_estimate, 300.0)
        Q_per_pipe_m3s = Q_required_m3s / n_pipes
        v_target_pipe = 2.5
        pipe_diameter_m = np.sqrt(4 * Q_per_pipe_m3s / (np.pi * v_target_pipe))
        pipe_diameter_m = max(0.300, min(pipe_diameter_m, 0.800))
        pipe_area = np.pi * (pipe_diameter_m / 2) ** 2
        v_pipe = Q_per_pipe_m3s / pipe_area if pipe_area > 0 else 0
        pipe_roughness = 0.0000015
        pipe_Re = v_pipe * pipe_diameter_m / self.hydraulics.nu if pipe_diameter_m > 0 else 0
        pipe_friction_factor = self.hydraulics.friction_factor_colebrook(pipe_Re, pipe_roughness, pipe_diameter_m)
        pipe_friction_factor = max(pipe_friction_factor, 0.010)
        jet_efficiency = 0.65  # Nozzle discharge coefficient

        # === STEP 1.5: Preliminary velocity field for smart jet placement ===
        # Compute local velocities (continuity) to find critical (low-velocity) zones
        preliminary_velocities = []
        for s in self.stations:
            w_local = s['width_m']
            A_local = w_local * depth_m
            v_local = Q_required_m3s / A_local if A_local > 0 else velocity
            preliminary_velocities.append(max(v_local, 0.05))

        # === STEP 2: Place jets (smart placement if critical zones exist) ===
        # Use smart placement: prioritize jets in low-velocity zones
        active_jets = self.propulsion.get_active_jets()
        if not active_jets or len(active_jets) != n_jets:
            # Smart placement: 50% in critical zones, 50% evenly distributed
            self.propulsion.auto_place_jets_smart(
                self.stations, n_jets=n_jets,
                flow_m3_h=Q_required_m3h / n_jets,
                diameter_m=jet_diameter_m,
                velocities=preliminary_velocities,
                critical_ratio=0.85,
            )
            active_jets = self.propulsion.get_active_jets()
        n_active_jets = len(active_jets) if active_jets else n_jets

        # === STEP 3: Individual jet pressure and flow ===
        # Each jet has a different distance from the pump manifold.
        # Jets closer to the pump: higher pressure → more flow → higher V_exit
        # Jets farther from the pump: lower pressure → less flow → lower V_exit
        if n_active_jets > 0 and pipe_length_estimate > 0:
            # Find pump manifold location (center of pump room)
            manifold_chainage = total_length / 2

            # Calculate pipe friction to each jet
            pipe_area_jet = np.pi * (pipe_diameter_m / 2) ** 2
            nozzle_area_jet = np.pi * (jet_diameter_m / 2) ** 2

            # Target flow per jet (from pump capacity)
            Q_target_per_jet_m3s = Q_required_m3s / n_active_jets

            # Calculate what pressure is needed to achieve target flow
            # Q = Cd * A * sqrt(2g*H)  →  H = (Q / (Cd * A))^2 / (2g)
            Cd_nozzle = jet_efficiency
            if Cd_nozzle > 0 and nozzle_area_jet > 0:
                H_required = (Q_target_per_jet_m3s / (Cd_nozzle * nozzle_area_jet)) ** 2 / (2 * 9.81)
            else:
                H_required = 3.0  # Default

            # This is the pressure the pump must provide at the manifold
            avg_tdh_estimate = H_required

            for j in active_jets:
                # Distance from manifold to jet (along the circuit)
                dist_to_jet = abs(j.station_m - manifold_chainage)
                # Account for circular circuit
                dist_to_jet = min(dist_to_jet, total_length - dist_to_jet)

                # Add pipe run from manifold to jet (with some routing factor)
                pipe_to_jet = dist_to_jet * 1.3  # 30% routing factor

                # Friction loss in pipe to this jet
                if pipe_diameter_m > 0:
                    # Use target flow per jet for pipe velocity
                    v_pipe_jet = Q_target_per_jet_m3s / pipe_area_jet if pipe_area_jet > 0 else 0

                    # Darcy-Weisbach friction loss
                    f_jet = pipe_friction_factor
                    h_friction_jet = f_jet * (pipe_to_jet / pipe_diameter_m) * (v_pipe_jet ** 2) / (2 * 9.81)

                    # Minor losses (elbows, tees, etc. along the run)
                    n_fittings_jet = max(2, int(pipe_to_jet / 10))  # ~1 fitting per 10m
                    k_per_fitting = 0.3
                    h_minor_jet = n_fittings_jet * k_per_fitting * (v_pipe_jet ** 2) / (2 * 9.81)

                    # Total loss to this jet
                    h_loss_jet = h_friction_jet + h_minor_jet
                else:
                    h_loss_jet = 0

                # Available pressure at jet nozzle
                # Pump provides H_required at manifold
                # Jet nozzle gets H_required minus friction losses in pipe
                h_available = max(H_required - h_loss_jet, 0.5)  # Minimum 0.5m

                # Flow through this jet: Q = Cd * A * sqrt(2*g*h_available)
                Q_jet_m3s = Cd_nozzle * nozzle_area_jet * np.sqrt(2 * 9.81 * h_available)
                Q_jet_m3h = Q_jet_m3s * 3600

                # Exit velocity
                v_exit_jet = Q_jet_m3s / nozzle_area_jet if nozzle_area_jet > 0 else 0

                # Update jet properties
                j.flow_m3_h = Q_jet_m3h
                j.flow_m3_s = Q_jet_m3s
                j.diameter_m = jet_diameter_m
                j.area = nozzle_area_jet
                j.velocity_exit_m_s = v_exit_jet

            # Recalculate total flow from jets
            Q_jets_total_m3s = sum(j.flow_m3_s for j in active_jets)
            Q_jets_total_m3h = Q_jets_total_m3s * 3600

            # Enforce continuity with the selected pump/design flow.  Individual
            # jet losses distribute pressure, but must not silently alter the
            # total Q used by velocity, lap-time, TDH and power calculations.
            # A manufacturer H-Q curve is still required to validate whether a
            # real pump can sustain this operating point.
            if Q_jets_total_m3s > 0:
                scale_factor = Q_required_m3s / Q_jets_total_m3s
                for j in active_jets:
                    j.flow_m3_s *= scale_factor
                    j.flow_m3_h *= scale_factor
                    j.velocity_exit_m_s = j.flow_m3_s / j.area if j.area > 0 else 0
                Q_jets_total_m3s = sum(j.flow_m3_s for j in active_jets)
                Q_jets_total_m3h = Q_jets_total_m3s * 3600

            # Q_required remains the input/design flow by continuity.

        elif n_active_jets > 0:
            # Fallback: uniform flow (no pipe model)
            Q_per_jet_m3h = Q_required_m3h / n_active_jets
            Q_per_jet_m3s = Q_per_jet_m3h / 3600.0
            nozzle_area = np.pi * (jet_diameter_m / 2) ** 2

            for j in active_jets:
                j.flow_m3_h = Q_per_jet_m3h
                j.flow_m3_s = Q_per_jet_m3s
                j.diameter_m = jet_diameter_m
                j.area = nozzle_area
                j.velocity_exit_m_s = Q_per_jet_m3s / nozzle_area if nozzle_area > 0 else 0

        # === STEP 4: Compute LOCAL velocity at each station ===
        # In a closed-loop pumped channel, flow continuity MUST be enforced:
        #   Q = V(s) × W(s) × D  →  V(s) = Q / (W(s) × D)
        # This is the ONLY source of velocity variation along the circuit.
        #
        # Energy losses (curvature, friction, jets) affect the TDH that pumps
        # must overcome, NOT the velocity at individual stations. The pump
        # delivers a fixed Q; the velocity adapts to the local cross-section.

        # Calculate jet positions for TDH computation (not for velocity modification)
        jet_positions = [j.station_m for j in active_jets]

        self.hydraulic_stations = []
        for s in self.stations:
            w_local = s['width_m']
            A_local = w_local * depth_m

            # Continuity: V = Q / A — this is the physics
            v_local = Q_required_m3s / A_local if A_local > 0 else velocity

            # Ensure minimum velocity (physical floor for numerical stability)
            v_local = max(v_local, 0.05)

            hs = self.hydraulics.compute_at_station(s, v_local)
            self.hydraulic_stations.append(hs)

        # === STEP 5: Compute DYNAMIC SYSTEM TDH ===
        # System TDH = canal friction + nozzle losses + pipe friction
        # This is what the pumps must actually overcome

        # 5a. Canal friction (Manning-based Darcy-Weisbach)
        canal_friction, losses = self.hydraulics.compute_total_losses(
            self.hydraulic_stations)

        # 5b. Nozzle loss (velocity head at jet nozzle)
        # Nozzles are in PARALLEL — all at the same pump pressure.
        # The pressure drop the pump must overcome = V_exit²/(2g) for ONE nozzle.
        # Cd (discharge coefficient) already reduced the actual Q through the nozzle,
        # so V_exit is the ACTUAL velocity. The loss is pure velocity head.
        nozzle_loss = 0.0
        v_exit = 0.0
        if active_jets:
            v_exit = active_jets[0].velocity_exit_m_s
            nozzle_loss = (v_exit ** 2) / (2 * 9.81)
            losses.append(LossComponent("Nozzles (velocity head)", "jet",
                                         nozzle_loss,
                                         f"n={len(active_jets)} jets (parallel), V_exit={v_exit:.1f}m/s", 0))

        # 5c. Pipe friction (Darcy-Weisbach for piping system)
        # Using pre-calculated pipe parameters from Step 1.5
        pipe_friction = pipe_friction_factor * (pipe_length_estimate / pipe_diameter_m) * (v_pipe ** 2) / (2 * 9.81)
        losses.append(LossComponent("Pipe friction (Darcy-Weisbach)", "friction",
                                     pipe_friction,
                                     f"{n_pump_rooms}cuartos, {n_pipes}pipes x {pipe_diameter_m*1000:.0f}mm HDPE, L={pipe_length_estimate:.0f}m, V={v_pipe:.1f}m/s, f={pipe_friction_factor:.4f}", 0))

        # 5d. Minor losses (valves, fittings, bends, strainers, check valves)
        # Using fitting K-factor database for accurate calculation
        from core.reference import calculate_total_k
        k_total_minor, fitting_breakdown = calculate_total_k()
        minor_losses = k_total_minor * (v_pipe ** 2) / (2 * 9.81)
        fitting_desc = ", ".join([f"{f['fitting']}x{f['quantity']}" for f in fitting_breakdown[:3]]) + "..."
        losses.append(LossComponent("Minor losses (valves, fittings)", "minor",
                                     minor_losses,
                                     f"K_total={k_total_minor:.2f}, V={v_pipe:.1f}m/s ({fitting_desc})", 0))

        # 5e. Diffuser/nozzle transition loss
        # Energy loss at the transition from pipe to jet nozzle
        # Typically 0.1-0.3m for well-designed systems
        diffuser_loss = 0.2  # Conservative estimate
        losses.append(LossComponent("Diffuser transition", "minor",
                                     diffuser_loss,
                                     "Pipe-to-nozzle transition", 0))

        # 5f. TOTAL SYSTEM TDH
        total_system_tdh = canal_friction + nozzle_loss + pipe_friction + minor_losses + diffuser_loss

        # Capacity check only. A real operating point requires a manufacturer
        # H-Q curve, so never silently reduce the configured flow here.
        pump_head_margin_m = None
        if pump_head_available_m is not None:
            pump_head_margin_m = pump_head_available_m - total_system_tdh

        # === STEP 6: Calculate COMMERCIAL POWER ===
        # P_hyd = rho × g × Q × TDH  (hydraulic power to move water)
        # P_motor = P_hyd / efficiency  (motor must provide more due to losses)
        # P_commercial = P_motor × safety_factor  (sizing margin for motor selection)
        # Safety factor accounts for: motor losses (5%), service conditions (5%), aging (5%)
        rho = 998  # kg/m³
        g = 9.81   # m/s²
        efficiency = pump_efficiency

        # Hydraulic power (useful work moving water)
        hydraulic_power_watts = rho * g * Q_required_m3s * total_system_tdh
        hydraulic_power_kw = hydraulic_power_watts / 1000

        # Motor power (must overcome pump inefficiency)
        motor_power_watts = hydraulic_power_watts / efficiency
        motor_hp = motor_power_watts / 745.7

        # Commercial power (with safety factor for motor sizing)
        # SF is applied to motor power for conservative motor selection
        total_power_watts = motor_power_watts * safety_factor
        total_hp = total_power_watts / 745.7
        pump_hp = total_hp / n_pumps if n_pumps > 0 else total_hp

        # Theoretical power (kW) for reference
        theoretical_kw = total_power_watts / 1000

        # === STEP 7: Size pumps ===
        self.pumps.auto_select_pumps(
            required_flow_m3_h=Q_required_m3h,
            tdh_m=total_system_tdh,
            n_pumps=n_pumps,
            efficiency=efficiency,
            service_factor=safety_factor,
        )

        # Update pump fields with computed values
        for p in self.pumps.pumps:
            p.motor_kw = pump_hp * 745.7 / 1000  # Per-pump HP to kW
            p.head_m = total_system_tdh * safety_factor  # TDH with safety factor
            p.flow_m3_h = Q_required_m3h / n_pumps  # Flow per pump

        # === STEP 8: NPSH verification ===
        # NPSHa = Patm/ρg - Hs - Hf_suction - Pv/ρg
        # Where: Patm = 101325 Pa, Pv = vapor pressure at temperature
        Patm = 101325.0  # Pa (standard atmosphere)
        # Vapor pressure using Antoine equation (NIST coefficients, valid 1-100°C)
        # P_mmHg = 10^(A - B/(C+T)), Pv_pa = P_mmHg * 133.322
        T = getattr(self.hydraulics, 'temperature_c', 20.0)
        Antoine_A, Antoine_B, Antoine_C = 8.07131, 1730.63, 233.426
        P_mmHg = 10 ** (Antoine_A - Antoine_B / (Antoine_C + T))
        Pv = P_mmHg * 133.322  # Convert mmHg to Pa
        Hs = 0.0  # Suction head (assume pump at water level)
        Hf_suction = pipe_friction * 0.3  # ~30% of pipe friction is on suction side
        NPSHa = Patm / (rho * g) - Hs - Hf_suction - Pv / (rho * g)
        # Typical NPSHr for centrifugal pumps: 2-5m
        NPSHr = 3.0  # Conservative estimate
        npsh_margin = NPSHa - NPSHr
        npsh_status = "OK" if npsh_margin > 1.0 else "REVISAR" if npsh_margin > 0.5 else "CRITICO"

        # === STEP 8: Other calculations ===
        # Lap time: integrate dt = ds / V(s) along the circuit
        # This accounts for varying velocity at each station (narrow = fast, wide = slow)
        if self.hydraulic_stations and len(self.hydraulic_stations) > 1:
            lap_time_s = 0.0
            for i in range(1, len(self.hydraulic_stations)):
                ds = self.hydraulic_stations[i].chainage_m - self.hydraulic_stations[i-1].chainage_m
                v_avg_seg = (self.hydraulic_stations[i].velocity_m_s + self.hydraulic_stations[i-1].velocity_m_s) / 2
                if v_avg_seg > 0:
                    lap_time_s += ds / v_avg_seg
            # Close the loop: last station back to first
            ds_close = total_length - self.hydraulic_stations[-1].chainage_m
            v_close = (self.hydraulic_stations[-1].velocity_m_s + self.hydraulic_stations[0].velocity_m_s) / 2
            if v_close > 0:
                lap_time_s += ds_close / v_close
            lap_time = lap_time_s / 60.0
        else:
            lap_time = self.geometry.channel_length_m / velocity / 60 if velocity > 0 else 0

        velocity_lap = (self.geometry.channel_length_m / (lap_time * 60)
                        if lap_time > 0 else 0.0)

        alerts = self.safety.evaluate(self.hydraulic_stations)
        warnings = [f"{a.parameter}: {a.value:.2f} {a.unit} ({a.status})" for a in alerts]
        if pump_head_margin_m is not None and pump_head_margin_m < 0:
            warnings.append(
                f"TDH nominal insuficiente: disponible={pump_head_available_m:.2f} m, "
                f"requerido={total_system_tdh:.2f} m. Verificar el punto H-Q con la curva del fabricante."
            )
        velocity_equivalent = Q_required_m3s / channel_area if channel_area > 0 else 0.0

        self.results = HydraulicResults(
            stations=self.hydraulic_stations,
            velocity_avg_m_s=np.mean([s.velocity_m_s for s in self.hydraulic_stations]),
            velocity_equivalent_m_s=velocity_equivalent,
            velocity_lap_m_s=velocity_lap,
            velocity_min_m_s=min([s.velocity_m_s for s in self.hydraulic_stations]),
            velocity_max_m_s=max([s.velocity_m_s for s in self.hydraulic_stations]),
            total_flow_m3_s=Q_required_m3s,
            total_flow_m3_h=Q_required_m3h,
            tdh_m=total_system_tdh,
            manning_velocity_m_s=self.hydraulics.manning_velocity(channel_area / (self.geometry.channel_width_avg_m + 2 * depth_m)),
            model_velocity_m_s=velocity,
            lap_time_min=lap_time,
            power_hydraulic_kw=hydraulic_power_kw,
            power_motor_kw=total_hp * 745.7 / 1000,  # HP to kW
            losses=losses,
            warnings=warnings,
            # Commercial power fields
            total_system_tdh_m=total_system_tdh,
            nozzle_loss_m=nozzle_loss,
            pipe_friction_m=pipe_friction,
            canal_friction_m=canal_friction,
            total_power_watts=total_power_watts,
            total_hp=total_hp,
            pump_hp=pump_hp,
            theoretical_kw=theoretical_kw,
            pump_head_available_m=pump_head_available_m or 0.0,
            pump_head_margin_m=pump_head_margin_m if pump_head_margin_m is not None else 0.0,
        )

        return self.results

    def run_scenario(self, scenario_id: str, **kwargs) -> dict:
        scenario = self.scenarios.get_scenario(scenario_id)
        if not scenario:
            return {'error': f'Scenario {scenario_id} not found'}

        n_people = scenario.people_count
        result = self.compute_hydraulics(**kwargs)

        user_velocity_estimated = result.velocity_avg_m_s
        if n_people > 0:
            user_velocity_estimated = self.people.velocity_reduction(
                result.velocity_avg_m_s, n_people,
                self.geometry.channel_width_avg_m,
                result.stations[0].depth_m if result.stations else 1.2,
                self.geometry.channel_length_m,
            )

        result_dict = {
            'scenario_id': scenario_id,
            'name': scenario.name,
            'people_count': n_people,
            'velocity_avg': result.velocity_lap_m_s,
            'user_velocity_estimated': user_velocity_estimated,
            'lap_time': result.lap_time_min,
            'total_flow': result.total_flow_m3_h,
            'tdh': result.tdh_m,
            'power': result.power_motor_kw,
        }

        self.scenarios.store_result(scenario_id, result_dict)
        return result_dict

    def validate_model(self) -> List[str]:
        issues = []
        if not self.geometry:
            issues.append("No geometry loaded")
        if not self.stations:
            issues.append("No stations computed")
        if self.geometry:
            if self.geometry.channel_length_m <= 0:
                issues.append("Channel length is zero")
            if self.geometry.channel_width_avg_m <= 0:
                issues.append("Average channel width is zero")
        if self.hydraulic_stations:
            for s in self.hydraulic_stations:
                if s.velocity_m_s < 0:
                    issues.append(f"Negative velocity at station {s.station_id}")
                if s.area_m2 <= 0:
                    issues.append(f"Zero area at station {s.station_id}")
        if not self.validation.field_data:
            issues.append("No field measurements loaded: the model has not been calibrated")
        if self.results and self.results.total_flow_m3_s > 0 and self.hydraulic_stations:
            max_flow_error = max(
                abs(s.flow_m3_s - self.results.total_flow_m3_s)
                for s in self.hydraulic_stations
            )
            if max_flow_error > self.results.total_flow_m3_s * 1e-6:
                issues.append("Flow continuity check failed across hydraulic stations")
        return issues

    def export_stations_csv(self) -> str:
        lines = [
            "station_id,chainage_m,x,y,width_m,depth_m,area_m2,"
            "hydraulic_radius_m,curvature_radius_m,curvature_1_m,"
            "velocity_m_s,flow_m3_s,energy_m"
        ]
        for s in self.hydraulic_stations:
            lines.append(
                f"{s.station_id},{s.chainage_m:.3f},{s.x:.3f},{s.y:.3f},"
                f"{s.width_m:.3f},{s.depth_m:.3f},{s.area_m2:.4f},"
                f"{s.hydraulic_radius_m:.4f},{s.curvature_radius_m:.2f},"
                f"{s.curvature_1_m:.6f},{s.velocity_m_s:.4f},"
                f"{s.flow_m3_s:.5f},{s.energy_m:.4f}"
            )
        return "\n".join(lines)

    def get_summary(self) -> dict:
        r = self.results
        return {
            'longitud_m': self.geometry.channel_length_m if self.geometry else 0,
            'ancho_promedio_m': self.geometry.channel_width_avg_m if self.geometry else 0,
            'ancho_min_m': self.geometry.channel_width_min_m if self.geometry else 0,
            'ancho_max_m': self.geometry.channel_width_max_m if self.geometry else 0,
            'profundidad_m': r.stations[0].depth_m if r and r.stations else 0,
            'velocidad_media': r.velocity_lap_m_s if r else 0,
            'velocidad_min': r.velocity_min_m_s if r else 0,
            'velocidad_max': r.velocity_max_m_s if r else 0,
            'tiempo_vuelta_min': r.lap_time_min if r else 0,
            'caudal_m3_h': r.total_flow_m3_h if r else 0,
            'tdh_m': r.tdh_m if r else 0,
            'potencia_kw': r.power_motor_kw if r else 0,
        }

    def sensitivity_analysis(self, base_params: dict, variation_pct: float = 20.0) -> list:
        """Perform sensitivity analysis by varying one parameter at a time.

        Args:
            base_params: dict with keys: depth_m, manning_n, n_jets, jet_diameter_m,
                        pump_flow_m3_h, n_pumps, safety_factor, n_pump_rooms
            variation_pct: percentage to vary each parameter (default 20%)

        Returns:
            list of dicts with parameter, baseline, varied, delta_velocity, delta_tdh, delta_power
        """
        import copy

        # Run baseline
        baseline = self.compute_hydraulics(**base_params)
        base_v = baseline.velocity_lap_m_s
        base_tdh = baseline.total_system_tdh_m
        base_power = baseline.power_motor_kw

        # Parameters to vary
        param_configs = [
            ("depth_m", 0.5, 2.0),
            ("manning_n", 0.010, 0.025),
            ("n_jets", 2, 20),
            ("jet_diameter_m", 0.100, 0.800),
            ("pump_flow_m3_h", 1000, 30000),
            ("n_pumps", 1, 4),
            ("safety_factor", 1.0, 2.0),
        ]

        results = []
        for param_name, param_min, param_max in param_configs:
            if param_name not in base_params:
                continue

            base_val = base_params[param_name]

            # Vary up
            params_up = copy.deepcopy(base_params)
            val_up = base_val * (1 + variation_pct / 100)
            val_up = min(val_up, param_max)
            params_up[param_name] = val_up
            result_up = self.compute_hydraulics(**params_up)

            # Vary down
            params_down = copy.deepcopy(base_params)
            val_down = base_val * (1 - variation_pct / 100)
            val_down = max(val_down, param_min)
            params_down[param_name] = val_down
            result_down = self.compute_hydraulics(**params_down)

            # Calculate deltas
            dv_up = (result_up.velocity_lap_m_s - base_v) / base_v * 100 if base_v > 0 else 0
            dv_down = (result_down.velocity_lap_m_s - base_v) / base_v * 100 if base_v > 0 else 0
            dtdh_up = (result_up.total_system_tdh_m - base_tdh) / base_tdh * 100 if base_tdh > 0 else 0
            dtdh_down = (result_down.total_system_tdh_m - base_tdh) / base_tdh * 100 if base_tdh > 0 else 0
            dpower_up = (result_up.power_motor_kw - base_power) / base_power * 100 if base_power > 0 else 0
            dpower_down = (result_down.power_motor_kw - base_power) / base_power * 100 if base_power > 0 else 0

            results.append({
                "parameter": param_name,
                "baseline": base_val,
                "varied_up": val_up,
                "varied_down": val_down,
                "delta_velocity_up": dv_up,
                "delta_velocity_down": dv_down,
                "delta_tdh_up": dtdh_up,
                "delta_tdh_down": dtdh_down,
                "delta_power_up": dpower_up,
                "delta_power_down": dpower_down,
                "velocity_range": abs(dv_up) + abs(dv_down),
                "power_range": abs(dpower_up) + abs(dpower_down),
            })

        # Sort by velocity range (most sensitive first)
        results.sort(key=lambda r: r["velocity_range"], reverse=True)
        return results

    def uncertainty_analysis(self, base_params: dict, n_samples: int = 100) -> dict:
        """Monte Carlo uncertainty quantification.
        Varies parameters within uncertainty ranges and computes output distributions.

        Args:
            base_params: baseline parameters
            n_samples: number of Monte Carlo samples

        Returns:
            dict with statistics for velocity, TDH, power
        """
        import copy

        # Parameter uncertainty ranges (±%)
        uncertainty = {
            "depth_m": 0.10,        # ±10%
            "manning_n": 0.15,      # ±15%
            "jet_diameter_m": 0.05, # ±5%
            "pump_flow_m3_h": 0.05, # ±5%
        }

        rng = np.random.RandomState(42)
        v_samples = []
        tdh_samples = []
        power_samples = []

        for _ in range(n_samples):
            params = copy.deepcopy(base_params)

            # Vary parameters within uncertainty
            for param, pct in uncertainty.items():
                if param in params:
                    factor = rng.normal(1.0, pct)
                    params[param] = params[param] * factor

            # Run model
            try:
                result = self.compute_hydraulics(**params)
                v_samples.append(result.velocity_lap_m_s)
                tdh_samples.append(result.total_system_tdh_m)
                power_samples.append(result.power_motor_kw)
            except:
                continue

        if not v_samples:
            return {"error": "No valid samples"}

        def stats(samples):
            arr = np.array(samples)
            return {
                "mean": float(np.mean(arr)),
                "std": float(np.std(arr)),
                "min": float(np.min(arr)),
                "max": float(np.max(arr)),
                "p5": float(np.percentile(arr, 5)),
                "p25": float(np.percentile(arr, 25)),
                "p50": float(np.percentile(arr, 50)),
                "p75": float(np.percentile(arr, 75)),
                "p95": float(np.percentile(arr, 95)),
                "ci_95": [float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))],
            }

        return {
            "n_samples": len(v_samples),
            "velocity": stats(v_samples),
            "tdh": stats(tdh_samples),
            "power": stats(power_samples),
        }
