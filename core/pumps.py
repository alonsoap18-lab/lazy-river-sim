"""Pump model for Lazy River system."""
import numpy as np
from typing import List, Optional
from models.geometry_model import Pump


class PumpModel:
    """Models pump selection and operation."""

    def __init__(self, density: float = 998.0, gravity: float = 9.81):
        self.rho = density
        self.g = gravity
        self.pumps: List[Pump] = []

    def add_pump(self, pump_id: int, flow_m3_h: float = 0, head_m: float = 0,
                 efficiency: float = 0.70, motor_kw: float = 0,
                 model_name: str = "Generic") -> Pump:
        p = Pump(
            pump_id=pump_id,
            model=model_name,
            flow_m3_h=flow_m3_h,
            head_m=head_m,
            efficiency=efficiency,
            motor_kw=motor_kw,
        )
        self.pumps.append(p)
        return p

    def remove_pump(self, pump_id: int):
        self.pumps = [p for p in self.pumps if p.pump_id != pump_id]

    def get_active_pumps(self) -> List[Pump]:
        return [p for p in self.pumps if not p.standby]

    def total_flow(self) -> float:
        return sum(p.flow_m3_h for p in self.get_active_pumps())

    def hydraulic_power_kw(self, flow_m3_h: float, head_m: float) -> float:
        """P_hyd = rho * g * Q * H"""
        q_m3s = flow_m3_h / 3600.0
        return self.rho * self.g * q_m3s * head_m / 1000.0

    def motor_power_kw(self, hydraulic_power_kw: float, efficiency: float) -> float:
        """P_motor = P_hyd / efficiency"""
        if efficiency <= 0:
            return 0.0
        return hydraulic_power_kw / efficiency

    def power_kw(self, flow_m3_h: float, head_m: float, efficiency: float) -> dict:
        p_hyd = self.hydraulic_power_kw(flow_m3_h, head_m)
        p_motor = self.motor_power_kw(p_hyd, efficiency)
        p_hp = p_motor * 1.341  # kW to HP
        return {
            'hydraulic_kw': p_hyd,
            'motor_kw': p_motor,
            'motor_hp': p_hp,
            'efficiency': efficiency,
        }

    def auto_select_pumps(self, required_flow_m3_h: float, tdh_m: float,
                           n_pumps: int = 2, efficiency: float = 0.70,
                           service_factor: float = 1.15) -> List[Pump]:
        """Auto-select pumps to meet required flow and head."""
        self.pumps = []
        n_pumps = int(n_pumps)

        flow_per_pump = required_flow_m3_h / n_pumps if n_pumps > 0 else 0
        head = tdh_m * service_factor
        p = self.power_kw(flow_per_pump, head, efficiency)

        for i in range(n_pumps):
            pump = self.add_pump(
                pump_id=i + 1,
                flow_m3_h=flow_per_pump,
                head_m=head,
                efficiency=efficiency,
                motor_kw=p['motor_kw'],
                model_name=f"Auto-selected P-{i+1}",
            )

        return self.pumps

    def get_pump_curve(self, pump: Pump, n_points: int = 20) -> dict:
        """Generate a generic pump curve for visualization."""
        q_max = pump.flow_m3_h * 1.5
        q = np.linspace(0, q_max, n_points)
        # Generic curve: H = H0 - k*Q^2
        h0 = pump.head_m * 1.2
        k = h0 / (q_max ** 2) if q_max > 0 else 0
        h = h0 - k * q ** 2
        h = np.maximum(h, 0)

        # Efficiency curve (generic parabola)
        q_bep = pump.flow_m3_h
        eff_max = pump.efficiency
        eff = eff_max * (1 - ((q - q_bep) / q_bep) ** 2)
        eff = np.clip(eff, 0, 1)

        return {
            'q_m3h': q.tolist(),
            'head_m': h.tolist(),
            'efficiency': eff.tolist(),
            'q_bep': q_bep,
            'h_bep': pump.head_m,
        }

    def get_combined_pump_curve(self, n_points: int = 30) -> dict:
        """Generate combined pump curve for parallel operation.
        For N identical pumps in parallel: Q_combined = N * Q_single at same H.
        """
        active = self.get_active_pumps()
        if not active:
            return {'q_m3h': [], 'head_m': [], 'efficiency': []}

        # Use first pump as reference
        ref_pump = active[0]
        single_curve = self.get_pump_curve(ref_pump, n_points)

        q_single = np.array(single_curve['q_m3h'])
        h_single = np.array(single_curve['head_m'])
        eff_single = np.array(single_curve['efficiency'])

        # Parallel: flows add at same head
        n_pumps = len(active)
        q_combined = q_single * n_pumps

        return {
            'q_m3h': q_combined.tolist(),
            'head_m': h_single.tolist(),
            'efficiency': eff_single.tolist(),
            'q_bep': ref_pump.flow_m3_h * n_pumps,
            'h_bep': ref_pump.head_m,
            'n_pumps': n_pumps,
        }

    def find_operating_point(self, system_curve_func, q_range: tuple = None) -> dict:
        """Find operating point where pump curve intersects system curve.
        Uses bisection method to find Q where H_pump(Q) = H_system(Q).

        Args:
            system_curve_func: function(Q_m3h) -> H_m (system curve)
            q_range: (Q_min, Q_max) search range in m3/h

        Returns:
            dict with q_operating, h_operating, efficiency
        """
        active = self.get_active_pumps()
        if not active:
            return {'q_operating': 0, 'h_operating': 0, 'efficiency': 0}

        # Get combined pump curve
        pump_curve = self.get_combined_pump_curve(100)
        q_pump = np.array(pump_curve['q_m3h'])
        h_pump = np.array(pump_curve['head_m'])
        eff_pump = np.array(pump_curve['efficiency'])

        # Default search range
        if q_range is None:
            q_range = (0, q_pump[-1])

        # Bisection to find intersection
        q_low, q_high = q_range
        for _ in range(100):
            q_mid = (q_low + q_high) / 2
            h_p = np.interp(q_mid, q_pump, h_pump)
            h_s = system_curve_func(q_mid)

            if h_p > h_s:
                q_low = q_mid
            else:
                q_high = q_mid

            if abs(q_high - q_low) < 0.1:
                break

        q_operating = (q_low + q_high) / 2
        h_operating = np.interp(q_operating, q_pump, h_pump)
        eff_operating = np.interp(q_operating, q_pump, eff_pump)

        return {
            'q_operating': q_operating,
            'h_operating': h_operating,
            'efficiency': eff_operating,
        }

    def get_system_summary(self) -> dict:
        active = self.get_active_pumps()
        total_flow = self.total_flow()
        total_power = sum(p.motor_kw for p in active)
        avg_eff = np.mean([p.efficiency for p in active]) if active else 0

        return {
            'n_pumps': len(self.pumps),
            'n_active': len(active),
            'n_standby': len(self.pumps) - len(active),
            'total_flow_m3h': total_flow,
            'total_power_kw': total_power,
            'total_power_hp': total_power * 1.341,
            'avg_efficiency': avg_eff,
        }
