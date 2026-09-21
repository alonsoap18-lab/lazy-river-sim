"""Hydraulic calculations - Manning reference + Darcy-Weisbach losses."""
import numpy as np
from typing import List, Dict, Tuple
from models.geometry_model import Station, LossComponent


class HydraulicEngine:
    """Computes hydraulic properties at each station."""

    def __init__(self, stations: List[dict], depth_m: float = 1.20,
                 manning_n: float = 0.015, density: float = 998.0,
                 gravity: float = 9.81, viscosity: float = 1.004e-6,
                 temperature_c: float = 20.0):
        self.station_data = stations
        self.depth = depth_m
        self.manning_n = manning_n
        self.g = gravity
        self.temperature_c = temperature_c

        # Temperature-dependent water properties (IAPWS)
        # At 20°C: rho=998, nu=1.004e-6
        # At 30°C: rho=996, nu=0.801e-6 (typical tropical park)
        self.rho = self._density_at_temp(temperature_c)
        self.nu = self._viscosity_at_temp(temperature_c)

    def _density_at_temp(self, T: float) -> float:
        """Water density (kg/m³) at temperature T (°C)."""
        # IAPWS approximation
        return 999.83 + 0.05054 * T - 0.00743 * T**2 + 0.00004 * T**3

    def _viscosity_at_temp(self, T: float) -> float:
        """Dynamic viscosity (Pa·s) at temperature T (°C) using Vogel correlation.

        Vogel formula: mu = 2.414e-5 * 10^(247.8 / (T + 133.15))
        Verified against NIST steam tables:
            20°C: 1.002 mPa·s (table: 1.002)  error <0.1%
            25°C: 0.891 mPa·s (table: 0.890)  error <0.2%
            30°C: 0.797 mPa·s (table: 0.798)  error <0.2%
        """
        mu_pa_s = 2.414e-5 * 10 ** (247.8 / (T + 133.15))
        rho = self._density_at_temp(T)
        return mu_pa_s / rho  # kinematic viscosity (m²/s)

    def compute_at_station(self, station: dict, velocity: float = None) -> Station:
        w = station['width_m']
        d = self.depth
        s = Station(
            station_id=station['station_id'],
            chainage_m=station['chainage_m'],
            x=station['x'],
            y=station['y'],
            tangent_x=station['tangent_x'],
            tangent_y=station['tangent_y'],
            normal_x=station['normal_x'],
            normal_y=station['normal_y'],
            width_m=w,
            depth_m=d,
            curvature_radius_m=station.get('curvature_radius_m', float('inf')),
            curvature_1_m=station.get('curvature_1_m', 0.0),
        )

        s.area_m2 = w * d
        wetted_perimeter = w + 2 * d
        s.hydraulic_radius_m = s.area_m2 / wetted_perimeter if wetted_perimeter > 0 else 0

        if velocity is not None:
            s.velocity_m_s = velocity
        else:
            s.velocity_m_s = self.manning_velocity(s.hydraulic_radius_m)

        s.flow_m3_s = s.area_m2 * s.velocity_m_s
        s.energy_m = s.depth_m + (s.velocity_m_s ** 2) / (2 * self.g)

        # Froude number: Fr = V / sqrt(g * D)
        # Fr < 0.8: subcritical (safe for lazy rivers)
        # Fr = 1: critical (hydraulic jump possible)
        # Fr > 1: supercritical (dangerous, avoid)
        if d > 0:
            s.froude_number = s.velocity_m_s / np.sqrt(self.g * d)
        else:
            s.froude_number = 0.0

        # Reynolds number: Re = V * Dh / nu
        # Dh = 4 * A / P (hydraulic diameter)
        dh = 4 * s.hydraulic_radius_m if s.hydraulic_radius_m > 0 else 0
        if self.nu > 0 and dh > 0:
            s.reynolds_number = s.velocity_m_s * dh / self.nu
        else:
            s.reynolds_number = 0.0

        return s

    def manning_velocity(self, hydraulic_radius: float, slope: float = None) -> float:
        if slope is None:
            slope = 0.0001  # Near-zero for pumped (horizontal) channels
        n = self.manning_n
        if n <= 0 or hydraulic_radius <= 0:
            return 0.0
        return (1.0 / n) * (hydraulic_radius ** (2.0 / 3.0)) * (slope ** 0.5)

    def reynolds_number(self, velocity: float, hydraulic_diameter: float) -> float:
        if self.nu <= 0:
            return float('inf')
        return velocity * hydraulic_diameter / self.nu

    def friction_factor_manning(self, hydraulic_radius: float) -> float:
        n = self.manning_n
        if hydraulic_radius <= 0:
            return 0.0
        return 8 * self.g * (n ** 2) / (hydraulic_radius ** (1.0 / 3.0))

    def friction_factor_colebrook(self, reynolds: float, roughness_m: float,
                                   hydraulic_diameter: float) -> float:
        if reynolds <= 0:
            return 0.0
        if reynolds < 2300:
            return 64.0 / reynolds

        d = hydraulic_diameter
        e = roughness_m
        if d <= 0:
            return 0.02

        e_d = e / d
        f = 0.02

        for _ in range(50):
            if f <= 0:
                f = 0.01
                continue
            sqrt_f = np.sqrt(f)
            rhs = -2.0 * np.log10(e_d / 3.7 + 2.51 / (reynolds * sqrt_f))
            f_new = (1.0 / rhs) ** 2
            if abs(f_new - f) < 1e-8:
                break
            f = f_new

        return f

    def friction_loss_darcy(self, f: float, length_m: float,
                             hydraulic_diameter: float, velocity: float) -> float:
        if hydraulic_diameter <= 0:
            return 0.0
        return f * (length_m / hydraulic_diameter) * (velocity ** 2) / (2 * self.g)

    def curve_loss(self, velocity: float, curvature_radius: float,
                    width: float, k_curve: float = 0.5) -> float:
        if curvature_radius <= 0 or curvature_radius == float('inf'):
            return 0.0
        angle_rad = width / curvature_radius
        angle_deg = np.degrees(angle_rad)
        k = k_curve * (angle_deg / 90.0)
        return k * (velocity ** 2) / (2 * self.g)

    def minor_loss(self, velocity: float, k_factor: float) -> float:
        return k_factor * (velocity ** 2) / (2 * self.g)

    def compute_total_losses(self, stations: List[Station],
                              curve_k: float = 0.5,
                              inlet_k: float = 0.5,
                              outlet_k: float = 1.0) -> Tuple[float, List[LossComponent]]:
        losses = []
        total = 0.0

        if not stations:
            return 0.0, losses

        avg_v = np.mean([s.velocity_m_s for s in stations])
        total_length = stations[-1].chainage_m
        avg_rh = np.mean([s.hydraulic_radius_m for s in stations])
        dh = 4 * avg_rh

        f = self.friction_factor_manning(avg_rh)
        h_friction = self.friction_loss_darcy(f, total_length, dh, avg_v)
        losses.append(LossComponent("Friction canal", "friction", h_friction,
                                     "Darcy-Weisbach + Manning f", f))
        total += h_friction

        h_inlet = self.minor_loss(avg_v, inlet_k)
        losses.append(LossComponent("Entrada", "minor", h_inlet,
                                     f"K={inlet_k}", inlet_k))
        total += h_inlet

        h_outlet = self.minor_loss(avg_v, outlet_k)
        losses.append(LossComponent("Salida", "minor", h_outlet,
                                     f"K={outlet_k}", outlet_k))
        total += h_outlet

        h_curves = 0.0
        n_curves = 0
        for s in stations:
            if s.curvature_radius_m < 100 and s.curvature_radius_m > 0:
                h = self.curve_loss(s.velocity_m_s, s.curvature_radius_m,
                                     s.width_m, curve_k)
                h_curves += h
                n_curves += 1

        if n_curves > 0:
            losses.append(LossComponent(f"Curvas ({n_curves})", "curve",
                                         h_curves, f"K={curve_k}", curve_k))
            total += h_curves

        return total, losses

    def system_curve(self, flow_m3_h: np.ndarray, stations: List[Station],
                      curve_k: float = 0.5) -> np.ndarray:
        H = np.zeros_like(flow_m3_h)
        if not stations:
            return H

        avg_w = np.mean([s.width_m for s in stations])
        avg_rh = np.mean([s.hydraulic_radius_m for s in stations])
        total_length = stations[-1].chainage_m
        dh = 4 * avg_rh
        f = self.friction_factor_manning(avg_rh)

        for i, q in enumerate(flow_m3_h):
            q_m3s = q / 3600.0
            v = q_m3s / (avg_w * self.depth) if avg_w * self.depth > 0 else 0
            h_f = self.friction_loss_darcy(f, total_length, dh, v)
            h_in = self.minor_loss(v, 0.5)
            h_out = self.minor_loss(v, 1.0)
            H[i] = h_f + h_in + h_out

        return H

    def compute_variable_depth(self, stations: List[dict], Q_m3s: float,
                                base_depth: float = 1.20) -> List[float]:
        """Compute variable depth along the circuit using specific energy conservation.

        At transitions (width changes), depth adjusts to conserve specific energy:
            E = D + V²/(2g) = D + Q²/(2g * W² * D²)

        For subcritical flow (Fr < 1): narrowing → depth drops, widening → depth rises
        """
        depths = []
        E_prev = base_depth + (Q_m3s / (stations[0]['width_m'] * base_depth))**2 / (2 * self.g)

        for s in stations:
            w = s['width_m']
            # Solve for depth given specific energy and width
            # E = D + Q²/(2g * W² * D²)
            # Use Newton-Raphson: f(D) = D + Q²/(2g*W²*D²) - E = 0
            D = base_depth  # Initial guess
            for _ in range(20):
                if D <= 0:
                    D = 0.1
                    continue
                A = w * D
                V = Q_m3s / A if A > 0 else 0
                f_val = D + V**2 / (2 * self.g) - E_prev
                f_prime = 1.0 + Q_m3s**2 / (self.g * w**2 * D**3)
                if abs(f_prime) < 1e-10:
                    break
                D_new = D - f_val / f_prime
                if D_new <= 0:
                    D_new = D * 0.5
                if abs(D_new - D) < 1e-6:
                    break
                D = D_new

            depths.append(max(D, 0.3))  # Minimum depth 0.3m
            # Update energy for next station (with friction loss)
            V = Q_m3s / (w * D) if (w * D) > 0 else 0
            rh = (w * D) / (w + 2 * D) if (w + 2 * D) > 0 else 0
            f = self.friction_factor_manning(rh)
            ds = 0.5  # Station spacing
            dh = 4 * rh
            h_loss = self.friction_loss_darcy(f, ds, dh, V)
            E_prev = D + V**2 / (2 * self.g) - h_loss

        return depths
