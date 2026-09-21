"""Jet propulsion model for Lazy River."""
import numpy as np
from typing import List, Dict, Tuple, Optional
from models.geometry_model import Jet


class PropulsionEngine:
    """Manages jet propulsors and computes thrust/flow."""

    def __init__(self, density: float = 998.0, gravity: float = 9.81):
        self.rho = density
        self.g = gravity
        self.jets: List[Jet] = []

    def add_jet(self, jet_id: int, station_m: float, x: float, y: float,
                diameter_m: float = 0.075, flow_m3_h: float = 10.0,
                angle_deg: float = 30.0) -> Jet:
        area = np.pi * (diameter_m / 2) ** 2
        flow_m3_s = flow_m3_h / 3600.0
        v_exit = flow_m3_s / area if area > 0 else 0.0
        pressure = 0.5 * self.rho * v_exit ** 2

        jet = Jet(
            jet_id=jet_id,
            station_m=station_m,
            x=x, y=y,
            flow_m3_s=flow_m3_s,
            flow_m3_h=flow_m3_h,
            pressure_pa=pressure,
            diameter_m=diameter_m,
            velocity_exit_m_s=v_exit,
            angle_deg=angle_deg,
        )
        self.jets.append(jet)
        return jet

    def remove_jet(self, jet_id: int):
        self.jets = [j for j in self.jets if j.jet_id != jet_id]

    def get_active_jets(self) -> List[Jet]:
        return [j for j in self.jets if j.active]

    def total_flow(self) -> float:
        return sum(j.flow_m3_s for j in self.get_active_jets())

    def total_flow_m3_h(self) -> float:
        return sum(j.flow_m3_h for j in self.get_active_jets())

    def thrust_force(self, jet: Jet) -> float:
        return self.rho * jet.flow_m3_s * jet.velocity_exit_m_s

    def total_thrust(self) -> float:
        return sum(self.thrust_force(j) for j in self.get_active_jets())

    def jet_power(self, jet: Jet) -> float:
        return 0.5 * self.rho * jet.flow_m3_s * jet.velocity_exit_m_s ** 2

    def total_power(self) -> float:
        return sum(self.jet_power(j) for j in self.get_active_jets())

    def jet_loss_at_station(self, jet: Jet, channel_velocity: float) -> float:
        if jet.diameter_m <= 0:
            return 0.0
        area = np.pi * (jet.diameter_m / 2) ** 2
        v_jet = jet.flow_m3_s / area if area > 0 else 0.0
        k_jet = (v_jet / channel_velocity) ** 2 if channel_velocity > 0 else 0.0
        return k_jet * (channel_velocity ** 2) / (2 * self.g)

    def total_jet_losses(self, channel_velocity: float) -> float:
        return sum(self.jet_loss_at_station(j, channel_velocity)
                   for j in self.get_active_jets())

    def auto_place_jets(self, stations: List[dict], n_jets: int = 8,
                        flow_m3_h: float = 10.0, diameter_m: float = 0.075) -> List[Jet]:
        self.jets = []
        if not stations or n_jets <= 0:
            return self.jets

        total_length = stations[-1]['chainage_m']
        spacing = total_length / n_jets

        for i in range(n_jets):
            target_chainage = i * spacing
            closest = min(stations, key=lambda s: abs(s['chainage_m'] - target_chainage))

            jet = self.add_jet(
                jet_id=i + 1,
                station_m=closest['chainage_m'],
                x=closest['x'],
                y=closest['y'],
                diameter_m=diameter_m,
                flow_m3_h=flow_m3_h,
                angle_deg=30.0,
            )

        return self.jets

    def auto_place_jets_smart(self, stations: List[dict], n_jets: int = 8,
                               flow_m3_h: float = 10.0, diameter_m: float = 0.075,
                               velocities: List[float] = None,
                               critical_ratio: float = 0.85) -> List[Jet]:
        """Place jets prioritizing low-velocity (critical) zones.

        Strategy:
        1. If velocities provided, find critical zones (V < critical_ratio * V_avg)
        2. Place 50% of jets in critical zones (closest station to each zone center)
        3. Distribute remaining jets evenly in non-critical areas
        """
        self.jets = []
        if not stations or n_jets <= 0:
            return self.jets

        total_length = stations[-1]['chainage_m']
        chainages = [s['chainage_m'] for s in stations]

        if velocities and len(velocities) == len(stations):
            v_avg = sum(velocities) / len(velocities)
            threshold = v_avg * critical_ratio

            # Find critical zones (contiguous low-velocity regions)
            critical_zones = []
            in_zone = False
            zone_start = 0
            for i, v in enumerate(velocities):
                if v < threshold and not in_zone:
                    in_zone = True
                    zone_start = i
                elif (v >= threshold or i == len(velocities) - 1) and in_zone:
                    in_zone = False
                    mid = (zone_start + i) // 2
                    critical_zones.append({
                        'chainage': chainages[mid],
                        'index': mid,
                        'velocity': velocities[mid],
                    })

            # Sort critical zones by velocity (worst first)
            critical_zones.sort(key=lambda z: z['velocity'])

            # Allocate jets: 50% to critical zones (min 1 if any zones exist)
            n_critical = int(max(1, min(len(critical_zones), n_jets // 2))) if critical_zones else 0
            n_even = int(n_jets - n_critical)

            # Place jets in critical zones
            used_chainages = []
            for i in range(n_critical):
                cz = critical_zones[i]
                closest = min(stations, key=lambda s: abs(s['chainage_m'] - cz['chainage']))
                jet = self.add_jet(
                    jet_id=i + 1,
                    station_m=closest['chainage_m'],
                    x=closest['x'],
                    y=closest['y'],
                    diameter_m=diameter_m,
                    flow_m3_h=flow_m3_h,
                    angle_deg=30.0,
                )
                used_chainages.append(closest['chainage_m'])

            # Place remaining jets evenly, avoiding proximity to critical-zone jets
            min_spacing = total_length / (n_jets * 2)  # Minimum distance between jets
            even_spacing = total_length / (n_even + 1) if n_even > 0 else total_length
            jet_id = n_critical + 1

            for i in range(n_even):
                target = (i + 1) * even_spacing
                # Find closest station not too close to existing jets
                best = None
                best_dist = float('inf')
                fallback = None
                fallback_dist = float('inf')
                for s in stations:
                    sc = s['chainage_m']
                    # Check distance to all placed jets
                    too_close = any(
                        min(abs(sc - uc), total_length - abs(sc - uc)) < min_spacing
                        for uc in used_chainages
                    )
                    dist = abs(sc - target)
                    if too_close:
                        # Keep as fallback if spacing constraint can't be met
                        if dist < fallback_dist:
                            fallback_dist = dist
                            fallback = s
                        continue
                    if dist < best_dist:
                        best_dist = dist
                        best = s

                # Use fallback if no station meets spacing constraint
                if not best and fallback:
                    best = fallback

                if best:
                    jet = self.add_jet(
                        jet_id=jet_id,
                        station_m=best['chainage_m'],
                        x=best['x'],
                        y=best['y'],
                        diameter_m=diameter_m,
                        flow_m3_h=flow_m3_h,
                        angle_deg=30.0,
                    )
                    used_chainages.append(best['chainage_m'])
                    jet_id += 1
        else:
            # Fallback: uniform distribution
            return self.auto_place_jets(stations, n_jets, flow_m3_h, diameter_m)

        return self.jets

    def get_jet_at_station(self, chainage_m: float,
                            tolerance_m: float = 2.0) -> Optional[Jet]:
        for jet in self.get_active_jets():
            if abs(jet.station_m - chainage_m) <= tolerance_m:
                return jet
        return None

    def velocity_contribution(self, jet: Jet, station: dict,
                               channel_velocity: float) -> float:
        dist = np.sqrt((jet.x - station['x']) ** 2 + (jet.y - station['y']) ** 2)
        if dist > 20.0:
            return 0.0

        angle_rad = np.radians(jet.angle_deg)
        tx, ty = station['tangent_x'], station['tangent_y']
        jx = np.cos(angle_rad)
        jy = np.sin(angle_rad)
        dot = jx * tx + jy * ty

        area = np.pi * (jet.diameter_m / 2) ** 2
        v_jet = jet.flow_m3_s / area if area > 0 else 0.0

        decay = np.exp(-dist / 10.0)
        return v_jet * abs(dot) * decay

    def jet_mixing_zone(self, jet: Jet, distance_m: float, jet_diameter_m: float = None) -> dict:
        """Model velocity in the jet mixing zone.

        Three zones:
        - Core zone (0-5D): Jet velocity dominates, V ~ V_exit
        - Transition zone (5-15D): Mixing occurs, velocity decays
        - Fully developed (>15D): Channel velocity dominates

        Args:
            jet: Jet object
            distance_m: distance from jet along flow direction
            jet_diameter_m: jet diameter (uses jet.diameter_m if None)

        Returns:
            dict with zone, velocity_ratio, description
        """
        D = jet_diameter_m or jet.diameter_m
        if D <= 0:
            return {"zone": "unknown", "velocity_ratio": 1.0, "description": "Invalid jet diameter"}

        # Distance in jet diameters
        x_D = distance_m / D

        area = np.pi * (D / 2) ** 2
        v_jet = jet.flow_m3_s / area if area > 0 else 0.0

        if x_D < 0:
            return {"zone": "upstream", "velocity_ratio": 1.0, "description": "Upstream of jet"}

        elif x_D <= 5:
            # Core zone: jet velocity dominates
            # V = V_exit * (1 - 0.1 * x/D) (linear decay in core)
            v_ratio = max(0.5, 1.0 - 0.1 * x_D)
            return {
                "zone": "core",
                "velocity_ratio": v_ratio,
                "velocity_m_s": v_jet * v_ratio,
                "description": f"Zona nucleo (0-5D). V ~ {v_jet * v_ratio:.2f} m/s. ZONA DE EXCLUSION para usuarios.",
            }

        elif x_D <= 15:
            # Transition zone: mixing occurs
            # V decays from core velocity to channel velocity
            # Using exponential decay: V = V_core * exp(-0.15 * (x/D - 5))
            v_core = v_jet * 0.5  # Velocity at end of core zone
            decay = np.exp(-0.15 * (x_D - 5))
            v_local = v_core * decay
            v_ratio = v_local / v_jet if v_jet > 0 else 0
            return {
                "zone": "transition",
                "velocity_ratio": v_ratio,
                "velocity_m_s": v_local,
                "description": f"Zona transicion (5-15D). V ~ {v_local:.2f} m/s. Mezcla activa.",
            }

        else:
            # Fully developed: channel velocity dominates
            return {
                "zone": "developed",
                "velocity_ratio": 0.0,
                "velocity_m_s": 0.0,  # Will be overwritten with channel velocity
                "description": "Zona desarrollada. Velocidad del canal domina.",
            }

    def get_jet_exclusion_zones(self, stations: list, channel_velocity: float = 0.5) -> list:
        """Identify exclusion zones near jets where velocity is dangerously high.

        Returns list of dicts with jet_id, center, radius, max_velocity
        """
        exclusion_zones = []
        for jet in self.get_active_jets():
            D = jet.diameter_m
            if D <= 0:
                continue

            # Exclusion zone radius: 5D from jet
            exclusion_radius = 5 * D

            # Find stations within exclusion zone
            for s in stations:
                dist = np.sqrt((jet.x - s['x']) ** 2 + (jet.y - s['y']) ** 2)
                if dist <= exclusion_radius:
                    mixing = self.jet_mixing_zone(jet, dist, D)
                    v_local = mixing.get("velocity_m_s", channel_velocity)
                    if v_local > channel_velocity * 1.5:  # 50% above channel average
                        exclusion_zones.append({
                            "jet_id": jet.jet_id,
                            "x": jet.x,
                            "y": jet.y,
                            "chainage_m": jet.station_m,
                            "radius_m": exclusion_radius,
                            "max_velocity_m_s": v_local,
                            "channel_velocity_m_s": channel_velocity,
                        })
                        break  # One zone per jet

        return exclusion_zones

    def secondary_current_superelevation(self, velocity: float, width: float,
                                          curvature_radius: float) -> float:
        """Compute water surface superelevation in bends (P6).

        In curved sections, centrifugal force creates a transverse water surface slope:
            Δh = V² × W / (g × R)

        This affects the effective cross-section and velocity distribution.

        Args:
            velocity: channel velocity (m/s)
            width: channel width (m)
            curvature_radius: radius of curvature (m)

        Returns:
            superelevation Δh (m)
        """
        if curvature_radius <= 0 or curvature_radius == float('inf'):
            return 0.0
        return (velocity ** 2 * width) / (self.g * curvature_radius)

    def air_entrainment_ratio(self, jet_velocity: float, submergence_depth: float,
                                jet_diameter: float) -> float:
        """Compute air entrainment ratio at jets (P9).

        Jets entrain air at a rate that depends on:
        - Jet velocity (higher V → more entrainment)
        - Submergence depth (deeper → more entrainment)
        - Jet diameter (larger D → more entrainment)

        Typical ratio: 1-3× the jet flow (Q_air / Q_jet)

        Returns:
            entrainment ratio (Q_air / Q_jet)
        """
        if jet_velocity <= 0 or submergence_depth <= 0 or jet_diameter <= 0:
            return 0.0

        # Empirical correlation (adapted from hydraulic jump literature)
        # Q_air/Q_jet = 0.04 * (V_jet / sqrt(g*D))^0.5 * (h/D)^0.3
        froude_jet = jet_velocity / np.sqrt(self.g * jet_diameter)
        h_d_ratio = submergence_depth / jet_diameter

        ratio = 0.04 * (froude_jet ** 0.5) * (h_d_ratio ** 0.3)

        # Cap at reasonable range
        return min(max(ratio, 0.1), 5.0)

    def effective_jet_density(self, jet_velocity: float, submergence_depth: float,
                               jet_diameter: float, water_density: float = 998.0) -> float:
        """Compute effective density of jet plume with entrained air (P9).

        Returns:
            effective density (kg/m³)
        """
        entrainment = self.air_entrainment_ratio(jet_velocity, submergence_depth, jet_diameter)
        # Volume fraction of air
        air_fraction = entrainment / (1 + entrainment)
        # Effective density: mix of water and air
        rho_air = 1.2  # kg/m³
        return water_density * (1 - air_fraction) + rho_air * air_fraction
