"""Particle animation engine for water flow visualization."""
import numpy as np
from typing import List, Tuple, Optional


class ParticleEngine:
    """Manages particles that follow the centerline at V(s) velocity."""

    def __init__(self, centerline_coords: List[Tuple[float, float]],
                 velocities: List[float], chainages: List[float],
                 channel_widths: List[float]):
        self.cl_coords = np.array(centerline_coords)
        self.velocities = np.array(velocities)
        self.chainages = np.array(chainages)
        self.widths = np.array(channel_widths)
        self.n_stations = len(centerline_coords)
        self.total_length = chainages[-1] if chainages else 0

        # Pre-compute tangents
        self.tangents = np.zeros((self.n_stations, 2))
        for i in range(self.n_stations):
            i_next = (i + 1) % self.n_stations
            dx = self.cl_coords[i_next, 0] - self.cl_coords[i, 0]
            dy = self.cl_coords[i_next, 1] - self.cl_coords[i, 1]
            mag = np.sqrt(dx**2 + dy**2)
            if mag > 0:
                self.tangents[i] = [dx/mag, dy/mag]

        # Particle state: chainage position of each particle
        self.n_particles = 0
        self.positions = np.array([])  # chainage values
        self.active = False

    def initialize(self, n_particles: int = 250):
        """Distribute particles evenly along the centerline."""
        self.n_particles = n_particles
        self.positions = np.linspace(0, self.total_length * 0.99, n_particles)
        self.active = True

    def step(self, dt_visual: float, speed_multiplier: float = 1.0):
        """Advance particles by one time step.

        dt_visual: real-time seconds per frame
        speed_multiplier: visual speed multiplier (not physics)
        """
        if not self.active or self.n_particles == 0:
            return

        # Interpolate velocity at each particle position
        v_at_pos = np.interp(self.positions, self.chainages, self.velocities)

        # Apply cross-channel velocity profile (power-law)
        # Particles near walls move slower, particles at center move faster
        # V(y) = V_max * (1 - (2y/W)^n) where n ~ 7 for turbulent flow
        half_w = np.interp(self.positions, self.chainages, self.widths) / 2.0
        # Use stored lateral positions to compute velocity reduction
        if hasattr(self, 'lateral_positions'):
            # Normalize lateral position: 0 = center, 1 = wall
            lateral_norm = np.abs(self.lateral_positions) / (half_w + 0.001)
            lateral_norm = np.clip(lateral_norm, 0, 1)
            # Power-law profile (n=7 for turbulent flow)
            profile_factor = 1.0 - (lateral_norm ** 7)
            v_at_pos = v_at_pos * profile_factor

        # Advance chainage
        delta = v_at_pos * dt_visual * speed_multiplier
        self.positions = (self.positions + delta) % self.total_length

    def get_xy(self) -> Tuple[np.ndarray, np.ndarray]:
        """Get current x, y positions of all particles."""
        if self.n_particles == 0:
            return np.array([]), np.array([])

        # Interpolate x, y from chainage
        x = np.interp(self.positions, self.chainages, self.cl_coords[:, 0])
        y = np.interp(self.positions, self.chainages, self.cl_coords[:, 1])

        # Add lateral offset (spread across channel width)
        half_w = np.interp(self.positions, self.chainages, self.widths) / 2.0
        # Random lateral offset per particle (deterministic, local state)
        rng = np.random.RandomState(42)
        self.lateral_positions = (rng.rand(self.n_particles) - 0.5) * half_w * 0.8

        # Normal direction (perpendicular to tangent)
        tx = np.interp(self.positions, self.chainages, self.tangents[:, 0])
        ty = np.interp(self.positions, self.chainages, self.tangents[:, 1])
        nx, ny = -ty, tx

        x = x + nx * self.lateral_positions
        y = y + ny * self.lateral_positions

        return x, y

    def get_speeds(self) -> np.ndarray:
        """Get velocity at each particle position."""
        if self.n_particles == 0:
            return np.array([])
        return np.interp(self.positions, self.chainages, self.velocities)

    def get_colors_by_velocity(self) -> list:
        """Get RGB colors for each particle based on velocity (S7).
        Blue (slow) → Green (medium) → Red (fast)
        """
        speeds = self.get_speeds()
        if len(speeds) == 0:
            return []

        v_min = np.min(speeds)
        v_max = np.max(speeds)
        v_range = v_max - v_min if v_max > v_min else 1.0

        colors = []
        for v in speeds:
            # Normalize to 0-1
            t = (v - v_min) / v_range
            # Blue → Green → Red
            if t < 0.5:
                r = 0
                g = int(255 * (2 * t))
                b = int(255 * (1 - 2 * t))
            else:
                r = int(255 * (2 * t - 1))
                g = int(255 * (2 - 2 * t))
                b = 0
            colors.append(f'rgb({r},{g},{b})')
        return colors

    def get_density_map(self, n_bins: int = 50) -> dict:
        """Compute particle density along the circuit (S4).
        High density = slow zones, low density = fast zones.

        Returns: dict with chainages and density (particles per meter)
        """
        bin_edges = np.linspace(0, self.total_length, n_bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        bin_width = self.total_length / n_bins

        density = np.zeros(n_bins)
        for pos in self.positions:
            bin_idx = int(pos / bin_width)
            if 0 <= bin_idx < n_bins:
                density[bin_idx] += 1

        # Normalize to particles per meter
        density = density / bin_width

        return {
            'chainages': bin_centers.tolist(),
            'density': density.tolist(),
            'max_density': float(np.max(density)),
            'avg_density': float(np.mean(density)),
        }

    def get_velocity_field(self, n_arrows: int = 20) -> dict:
        """Generate 2D velocity vector field data (S6).
        Returns positions and tangent vectors for quiver plot.
        """
        if self.n_particles == 0:
            return {'x': [], 'y': [], 'u': [], 'v': [], 'speeds': []}

        # Sample positions evenly
        sample_positions = np.linspace(0, self.total_length * 0.99, n_arrows)

        # Get x, y
        x = np.interp(sample_positions, self.chainages, self.cl_coords[:, 0])
        y = np.interp(sample_positions, self.chainages, self.cl_coords[:, 1])

        # Get tangent vectors (velocity direction)
        tx = np.interp(sample_positions, self.chainages, self.tangents[:, 0])
        ty = np.interp(sample_positions, self.chainages, self.tangents[:, 1])

        # Get speeds for arrow length
        speeds = np.interp(sample_positions, self.chainages, self.velocities)

        # Scale arrows by velocity
        scale = 3.0  # Visual scale factor
        u = tx * speeds * scale
        v = ty * speeds * scale

        return {
            'x': x.tolist(),
            'y': y.tolist(),
            'u': u.tolist(),
            'v': v.tolist(),
            'speeds': speeds.tolist(),
        }


class PersonTracker:
    """Tracks a person/floater moving along the centerline."""

    def __init__(self, centerline_coords, velocities, chainages):
        self.cl_coords = np.array(centerline_coords)
        self.velocities = np.array(velocities)
        self.chainages = np.array(chainages)
        self.total_length = chainages[-1] if chainages else 0
        self.position = 0.0  # chainage
        self.laps = 0
        self.time_s = 0.0

    def step(self, dt: float, speed_mult: float = 1.0):
        v = float(np.interp(self.position, self.chainages, self.velocities))
        delta = v * dt * speed_mult
        self.position += delta
        self.time_s += dt * speed_mult
        # Count laps
        if self.position >= self.total_length:
            self.laps += int(self.position / self.total_length)
            self.position = self.position % self.total_length

    def get_xy(self):
        x = float(np.interp(self.position, self.chainages, self.cl_coords[:, 0]))
        y = float(np.interp(self.position, self.chainages, self.cl_coords[:, 1]))
        return x, y

    def get_velocity(self):
        return float(np.interp(self.position, self.chainages, self.velocities))

    def get_progress(self):
        return self.position / self.total_length * 100 if self.total_length > 0 else 0

    def reset(self):
        self.position = 0.0
        self.laps = 0
        self.time_s = 0.0


class CrowdSimulator:
    """Simulates multiple people moving along the lazy river."""

    def __init__(self, centerline_coords, velocities, chainages,
                 channel_widths, n_people: int = 20):
        self.cl_coords = np.array(centerline_coords)
        self.velocities = np.array(velocities)
        self.chainages = np.array(chainages)
        self.widths = np.array(channel_widths)
        self.total_length = chainages[-1] if chainages else 0
        self.n_people = n_people

        # Initialize people at random positions
        rng = np.random.RandomState(123)
        self.positions = rng.uniform(0, self.total_length * 0.99, n_people)
        # Random lateral offsets (within channel width)
        half_w = np.interp(self.positions, self.chainages, self.widths) / 2.0
        self.lateral = (rng.rand(n_people) - 0.5) * half_w * 0.7
        # Each person has a speed modifier (some faster, some slower)
        self.speed_factors = rng.normal(1.0, 0.1, n_people)
        self.speed_factors = np.clip(self.speed_factors, 0.7, 1.3)

        # Pre-compute tangents
        self.tangents = np.zeros((len(centerline_coords), 2))
        for i in range(len(centerline_coords)):
            i_next = (i + 1) % len(centerline_coords)
            dx = self.cl_coords[i_next, 0] - self.cl_coords[i, 0]
            dy = self.cl_coords[i_next, 1] - self.cl_coords[i, 1]
            mag = np.sqrt(dx**2 + dy**2)
            if mag > 0:
                self.tangents[i] = [dx/mag, dy/mag]

        self.active = False

    def initialize(self):
        """Start the simulation."""
        self.active = True

    def step(self, dt_visual: float, speed_multiplier: float = 1.0):
        """Advance all people by one time step."""
        if not self.active or self.n_people == 0:
            return

        # Get velocity at each person's position
        v_at_pos = np.interp(self.positions, self.chainages, self.velocities)

        # Apply individual speed factors
        v_personal = v_at_pos * self.speed_factors

        # Apply cross-channel profile (people near walls move slower)
        half_w = np.interp(self.positions, self.chainages, self.widths) / 2.0
        lateral_norm = np.abs(self.lateral) / (half_w + 0.001)
        lateral_norm = np.clip(lateral_norm, 0, 1)
        profile_factor = 1.0 - (lateral_norm ** 5)  # n=5 for people (less turbulent)
        v_personal = v_personal * profile_factor

        # Advance positions
        delta = v_personal * dt_visual * speed_multiplier
        self.positions = (self.positions + delta) % self.total_length

    def get_xy(self):
        """Get x, y positions of all people."""
        if self.n_people == 0:
            return np.array([]), np.array([])

        x = np.interp(self.positions, self.chainages, self.cl_coords[:, 0])
        y = np.interp(self.positions, self.chainages, self.cl_coords[:, 1])

        # Apply lateral offset
        tx = np.interp(self.positions, self.chainages, self.tangents[:, 0])
        ty = np.interp(self.positions, self.chainages, self.tangents[:, 1])
        nx, ny = -ty, tx

        x = x + nx * self.lateral
        y = y + ny * self.lateral

        return x, y

    def get_velocities(self):
        """Get velocity of each person."""
        v_base = np.interp(self.positions, self.chainages, self.velocities)
        return v_base * self.speed_factors

    def get_density_map(self, n_bins: int = 50) -> dict:
        """Compute people density along the circuit.
        Returns: dict with chainages and density (people per meter)
        """
        bin_edges = np.linspace(0, self.total_length, n_bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        bin_width = self.total_length / n_bins

        density = np.zeros(n_bins)
        for pos in self.positions:
            bin_idx = int(pos / bin_width)
            if 0 <= bin_idx < n_bins:
                density[bin_idx] += 1

        # Normalize to people per meter
        density = density / bin_width

        return {
            'chainages': bin_centers.tolist(),
            'density': density.tolist(),
            'max_density': float(np.max(density)),
            'avg_density': float(np.mean(density)),
        }


class JetVisualizer:
    """Computes jet spray positions for visualization."""

    def __init__(self, jets: list, centerline_coords: list,
                 tangents: list, n_spray: int = 8):
        self.jets = jets
        self.cl_coords = np.array(centerline_coords) if centerline_coords else np.array([])
        self.tangents = np.array(tangents) if tangents else np.array([])
        self.n_spray = n_spray

    def get_spray_lines(self, t: float) -> list:
        """Get animated spray lines for each active jet at time t."""
        lines = []
        for jet in self.jets:
            if not jet.active:
                continue

            angle_rad = np.radians(jet.angle_deg)
            vx = np.cos(angle_rad)
            vy = np.sin(angle_rad)

            # Spray extends from jet position
            spray_len = 3.0  # DXF units
            segments = []
            for i in range(self.n_spray):
                frac = (i + 1) / self.n_spray
                # Animated phase
                phase = (t * 3.0 + i * 0.3) % 1.0
                dist = spray_len * frac * phase
                sx = jet.x + vx * dist
                sy = jet.y + vy * dist
                segments.append((sx, sy))

            if segments:
                xs = [jet.x] + [s[0] for s in segments]
                ys = [jet.y] + [s[1] for s in segments]
                lines.append({
                    'jet_id': jet.jet_id,
                    'xs': xs, 'ys': ys,
                    'active': jet.active,
                    'flow': jet.flow_m3_h,
                })

        return lines
