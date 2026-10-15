"""Conservative reporting checks for experimental SPH section diagnostics."""

from __future__ import annotations

import numpy as np


def conditional_lap(frames: list[dict], length_m: float = 536.0) -> dict:
    """Estimate section travel time only after basic coverage/stability gates.

    This is not the travel time of a floating guest. It merely integrates
    inverse mean longitudinal water speeds in one experimental run.
    """
    if len(frames) < 3:
        return {"lap_min": None, "reason": "Faltan tres ventanas temporales."}
    recent = frames[-3:]
    speeds = [np.asarray(f["section_mean_along_m_s"], dtype=float) for f in recent]
    counts = [np.asarray(f["section_particle_count"], dtype=int) for f in recent]
    if any(np.any(c < 5) for c in counts):
        return {"lap_min": None, "reason": "Hay secciones con menos de cinco partículas."}
    if any(np.any(~np.isfinite(v)) or np.any(v <= .02) for v in speeds):
        return {"lap_min": None, "reason": "Hay secciones detenidas o con retorno."}
    current = speeds[-1]
    changes = [np.abs(current - old) / np.maximum(current, .02) for old in speeds[:-1]]
    median_drift = max(float(np.median(change)) for change in changes)
    p90_drift = max(float(np.quantile(change, .9)) for change in changes)
    if median_drift > .1 or p90_drift > .15:
        return {"lap_min": None,
                "reason": "La corriente aún cambia demasiado entre los cuadros finales "
                          "(mediana >10 % o percentil 90 >15 %).",
                "median_relative_drift": median_drift,
                "p90_relative_drift": p90_drift}
    lap = float(np.sum(length_m / len(current) / current) / 60)
    return {"lap_min": lap,
            "reason": "Estimación condicional por velocidades medias de secciones; "
                      "no persona ni flotador validados.",
            "median_relative_drift": median_drift,
            "p90_relative_drift": p90_drift,
            "in_30_to_40_min_band": 30 <= lap <= 40}
