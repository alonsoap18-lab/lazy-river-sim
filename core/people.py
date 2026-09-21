"""People/occupancy resistance model."""
import numpy as np
from typing import List, Dict


class PeopleModel:
    """Computes drag and blockage from people and floaters in the channel.

    For a pumped lazy river with constant Q:
    - People physically occupy space → reduces effective area → increases V (blockage)
    - People create drag → slows water down (resistance)
    - Net effect depends on pump behavior:
      * Constant Q pump: blockage > drag → V increases slightly
      * Real pump (with curve): Q decreases → V decreases

    This model computes both effects and returns the net velocity change.
    """

    def __init__(self, density: float = 998.0):
        self.rho = density

    def people_drag_force(self, n_people: int, velocity: float,
                           body_area: float = 0.5, body_cd: float = 1.0) -> float:
        """Total drag force from people (N)."""
        return 0.5 * self.rho * body_cd * body_area * velocity ** 2 * n_people

    def floater_drag_force(self, n_floaters: int, velocity: float,
                            floater_area: float = 0.3, floater_cd: float = 0.8) -> float:
        """Total drag force from floaters (N)."""
        return 0.5 * self.rho * floater_cd * floater_area * velocity ** 2 * n_floaters

    def total_drag(self, n_people: int, velocity: float,
                    n_floaters: int = 0,
                    body_area: float = 0.5, body_cd: float = 1.0,
                    floater_area: float = 0.3, floater_cd: float = 0.8) -> float:
        return (self.people_drag_force(n_people, velocity, body_area, body_cd) +
                self.floater_drag_force(n_floaters, velocity, floater_area, floater_cd))

    def velocity_with_people(self, base_velocity: float, n_people: int,
                              channel_width: float, channel_depth: float,
                              channel_length: float,
                              body_area: float = 0.5, body_cd: float = 1.0,
                              n_floaters: int = 0,
                              floater_area: float = 0.3,
                              floater_cd: float = 0.8,
                              pump_type: str = "constant_flow") -> float:
        """Compute velocity with people in the channel.

        Two competing effects:
        1. BLOCKAGE: People occupy space → less area → V increases (continuity)
        2. DRAG: People create resistance → V decreases

        For constant-flow pumps: blockage dominates → V increases
        For real pumps (with curve): Q drops → V decreases

        Args:
            base_velocity: velocity without people
            n_people: number of people in channel
            channel_width: average channel width (m)
            channel_depth: water depth (m)
            channel_length: circuit length (m)
            body_area: frontal area per person (m²)
            body_cd: drag coefficient per person
            n_floaters: number of people with floaters
            floater_area: frontal area per floater (m²)
            floater_cd: drag coefficient per floater
            pump_type: "constant_flow" or "curve" (default: constant_flow)

        Returns:
            adjusted velocity (m/s)
        """
        if n_people <= 0:
            return base_velocity

        channel_area = channel_width * channel_depth
        if channel_area <= 0 or channel_length <= 0:
            return base_velocity

        # People density along channel (people per meter)
        people_per_meter = n_people / channel_length

        # === EFFECT 1: BLOCKAGE (reduces effective area) ===
        # People occupy space in the cross-section
        # Effective area = channel_area - (people_per_length * body_area * length)
        # But people are distributed, so at any cross-section:
        # blocked_area = people_per_meter * body_area (m² per meter of channel)
        # blocked_fraction = blocked_area / channel_area
        total_body_area_per_m = people_per_meter * (body_area + n_floaters * floater_area)
        blocked_fraction = total_body_area_per_m / channel_area

        # Cap blockage at 40% (physically, people would be shoulder-to-shoulder)
        blocked_fraction = min(blocked_fraction, 0.40)

        # Blockage effect on velocity: V = Q / A_eff = Q / (A * (1 - blocked))
        # V_new = V_base / (1 - blocked) → velocity INCREASES
        if blocked_fraction < 1.0:
            v_blockage = base_velocity / (1.0 - blocked_fraction)
        else:
            v_blockage = base_velocity * 2.0  # Cap at 2x

        # === EFFECT 2: DRAG (resistance from people) ===
        # Drag force = 0.5 * rho * Cd * A * V² * n_people
        # This creates additional head loss
        # For a pumped system, this would reduce Q if pump has a curve
        # For constant Q, drag is overcome by the pump (no velocity reduction)

        if pump_type == "curve":
            # Real pump behavior: increased resistance → lower Q → lower V
            # Approximate: drag reduces effective pump head
            # ΔH_drag = F_drag / (rho * g * A_channel)
            drag_force = self.total_drag(n_people, base_velocity, n_floaters,
                                          body_area, body_cd, floater_area, floater_cd)
            # Convert drag force to head loss
            delta_h = drag_force / (self.rho * 9.81 * channel_area) if channel_area > 0 else 0
            # Approximate velocity reduction from head loss
            # V_new ≈ V_base * (1 - delta_h / (2 * V²/2g))
            v_head = base_velocity ** 2 / (2 * 9.81)
            if v_head > 0:
                drag_reduction = min(delta_h / (2 * v_head), 0.30)  # Cap at 30%
            else:
                drag_reduction = 0
            v_drag = v_blockage * (1 - drag_reduction)
        else:
            # Constant flow pump: drag doesn't reduce velocity
            # (pump maintains same Q regardless of resistance)
            v_drag = v_blockage

        # === NET EFFECT ===
        # For constant Q: V increases due to blockage
        # For real pump: V may decrease if drag > blockage
        return max(v_drag, 0.05)

    def velocity_reduction(self, base_velocity: float, n_people: int,
                            channel_width: float, channel_depth: float,
                            channel_length: float,
                            body_area: float = 0.5, body_cd: float = 1.0,
                            n_floaters: int = 0,
                            floater_area: float = 0.3,
                            floater_cd: float = 0.8) -> float:
        """Estimate velocity with people (backward compatibility).

        Uses constant_flow pump model by default.
        """
        return self.velocity_with_people(
            base_velocity, n_people, channel_width, channel_depth,
            channel_length, body_area, body_cd, n_floaters,
            floater_area, floater_cd, pump_type="constant_flow")

    def occupancy_factor(self, n_people: int, max_capacity: int) -> float:
        if max_capacity <= 0:
            return 1.0
        ratio = n_people / max_capacity
        return max(0.3, 1.0 - 0.5 * ratio)

    def people_density(self, n_people: int, channel_area_m2: float) -> float:
        if channel_area_m2 <= 0:
            return 0.0
        return n_people / channel_area_m2
