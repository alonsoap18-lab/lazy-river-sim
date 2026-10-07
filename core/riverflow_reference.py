"""Published example operating points for a dual-suction Riverflow lazy river.

These are reference installations, not a measured or approved NYA circuit.
The consultant reports approximate intersections at full speed. Scaling a
reference point below full speed is an affinity-law scenario only.
"""

from dataclasses import dataclass
from math import isfinite

from core.riverflow_model import US_GPM_TO_M3_H


@dataclass(frozen=True)
class ReferenceSystem:
    label: str
    flow_gpm: float
    head_ft: float
    exit_velocity_ft_s: float
    source: str


@dataclass(frozen=True)
class ReferenceOperatingPoint:
    flow_m3_h: float
    pump_head_ft: float
    system_head_ft: float
    exit_velocity_m_s: float


# C.T. Brannon Corporation, "Riverflow Flow Rates", 9 December 2025,
# Dual Suction Lazy River Arrangement. These points are approximate and
# conditional on the letter's specified pipework, fittings and 12 x 7 outlet.
LAZY_RIVER_REFERENCES = (
    ReferenceSystem("Referencia Lazy River · PVC Sch 40", 2014.0, 6.5, 15.5,
                    "RiverFlow Flow Rates.pdf · 09/12/2025"),
    ReferenceSystem("Referencia Lazy River · PVC Sch 80", 1988.0, 6.7, 15.3,
                    "RiverFlow Flow Rates.pdf · 09/12/2025"),
)


def reference_operating_point(reference: ReferenceSystem,
                              speed_fraction: float = 1.0) -> ReferenceOperatingPoint:
    """Scale the documented point on a quadratic *reference* system curve.

    Q~RPM, H~RPM² and nozzle velocity~RPM are hypotheses for reduced speed,
    not manufacturer VFD performance data or a curve for the NYA installation.
    """
    if not isfinite(speed_fraction) or not 0 < speed_fraction <= 1:
        raise ValueError("La velocidad relativa debe estar entre 0 y 1.")
    if any(not isfinite(v) or v <= 0 for v in
           (reference.flow_gpm, reference.head_ft, reference.exit_velocity_ft_s)):
        raise ValueError("El punto de referencia debe ser positivo y finito.")
    flow = reference.flow_gpm * US_GPM_TO_M3_H * speed_fraction
    head = reference.head_ft * speed_fraction ** 2
    return ReferenceOperatingPoint(flow, head, head,
                                   reference.exit_velocity_ft_s * 0.3048 * speed_fraction)
