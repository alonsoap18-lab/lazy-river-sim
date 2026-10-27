"""Auditable diagnostics from fixed NYA OpenFOAM fields.

These functions describe saved simulations; they never predict the effect of
editing a Riverflow unit in the Streamlit controls.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.optimize import linear_sum_assignment

from core.riverflow_cfd_saved import (COUNTS, NAMES, load_geometry,
                                       load_metadata, load_scenario)
from core.riverflow_model import US_GPM_TO_M3_H

SLOW_M_S = 0.15
FAST_M_S = 0.50
SECTION_M = 8.0


def _circular_distance(a: np.ndarray, b: np.ndarray, length: float) -> np.ndarray:
    gap = np.abs(a[:, None] - b[None, :])
    return np.minimum(gap, length-gap)


def compare_editable_to_saved(plan, scenario: int, floor_n: float,
                              wall_n_current: float, wall_n_calm: float,
                              depth_m: float, uploaded_dxf: bool,
                              source_matches: bool, nozzle_type: str,
                              beach_flat_m: float | None,
                              beach_ramp_pct: float) -> tuple[list[dict], dict]:
    manifest, _ = load_metadata()
    saved = manifest["scenarios"][str(scenario)]["pumps"]
    current_q = plan.installed_operating_flow_m3_h / plan.active_modules
    saved_q = manifest["reference_flow_us_gpm_per_cf104"] * US_GPM_TO_M3_H
    current_pos = np.asarray(plan.module_chainages_m, dtype=float)
    saved_pos = np.asarray([unit["chainage_m"] for unit in saved], dtype=float)
    position_gap = None
    bank_mismatches = None
    if len(current_pos) == len(saved_pos):
        distance = _circular_distance(current_pos, saved_pos, manifest["length_m"])
        current_banks = np.asarray(plan.module_banks)
        saved_banks = np.asarray([unit["bank"] for unit in saved])
        # Compare one-to-one by location; report bank separately from distance.
        row, col = linear_sum_assignment(distance)
        position_gap = float(np.max(distance[row, col]))
        bank_mismatches = int(np.count_nonzero(current_banks[row] != saved_banks[col]))
    geometry_ok = (not uploaded_dxf and source_matches and
                   abs(plan.length_m-manifest["length_m"]) < .01 and
                   abs(depth_m-1.2) < .001)
    rows = [
        {"Dato": "Bombas activas", "Editable": str(plan.active_modules),
         "CFD guardado": str(scenario),
         "Coincide": plan.active_modules == scenario},
        {"Dato": "Caudal por bomba", "Editable": f"{current_q:.1f} m³/h",
         "CFD guardado": f"{saved_q:.1f} m³/h",
         "Coincide": abs(current_q-saved_q)/saved_q < .01},
        {"Dato": "Variador", "Editable": f"{plan.speed_fraction:.0%}",
         "CFD guardado": "100 % nominal · Q fijo",
         "Coincide": abs(plan.speed_fraction-1) < .001},
        {"Dato": "Longitud / profundidad", "Editable":
         f"{plan.length_m:.0f} m / {depth_m:.2f} m",
         "CFD guardado": "536 m / 1,20 m", "Coincide": geometry_ok},
        {"Dato": "Playa principal", "Editable":
         (f"{beach_flat_m:.1f} m planos; {beach_ramp_pct:.1f} %" if beach_flat_m is not None
          else "Perfil desactivado"),
         "CFD guardado": "16 m planos; rampa 6,5 %",
         "Coincide": (beach_flat_m is not None and abs(beach_flat_m-16) < .1 and
                      abs(beach_ramp_pct-6.5) < .01)},
        {"Dato": "Manning piso / paredes", "Editable":
         f"{floor_n:.3f} / {wall_n_current:.3f} / {wall_n_calm:.3f}",
         "CFD guardado": f"{manifest['floor_manning_n']:.3f} / "
         f"{manifest['wall_manning_n']:.3f}",
         "Coincide": (abs(floor_n-manifest["floor_manning_n"]) < .0005 and
                      abs(wall_n_current-manifest["wall_manning_n"]) < .0005 and
                      abs(wall_n_calm-manifest["wall_manning_n"]) < .0005)},
        {"Dato": "Salida", "Editable": nozzle_type,
         "CFD guardado": "7 puertos equivalentes",
         "Coincide": nozzle_type == "7 puertos"},
        {"Dato": "Posición y orilla", "Editable":
         (f"Máx. desplazamiento {position_gap:.1f} m; "
          f"{bank_mismatches} orillas distintas" if position_gap is not None
          else "Cantidad distinta"),
         "CFD guardado": f"{scenario} posiciones fijas",
         "Coincide": (position_gap is not None and position_gap < 1.0 and
                      bank_mismatches == 0)},
    ]
    return rows, {"geometry_ok": geometry_ok,
                  "positions_match": rows[-1]["Coincide"],
                  "all_match": all(row["Coincide"] for row in rows)}


@lru_cache(maxsize=4)
def section_profile(count: int) -> tuple[dict, ...]:
    geometry = load_geometry()
    field = load_scenario(count)["u"][-1]
    s = geometry["cell_chainage_m"].astype(float)
    width = geometry["cell_width_m"].astype(float)
    eta = geometry["cell_lateral_eta"].astype(float)
    volume = geometry["cell_volume_m3"].astype(float)
    tangent = geometry["cell_tangent_xy"].astype(float)
    forward = np.einsum("ij,ij->i", field[:, :2], tangent)
    manifest, _ = load_metadata()
    length = manifest["length_m"]
    bins = int(round(length/SECTION_M))
    index = np.minimum((s/SECTION_M).astype(int), bins-1)
    pumps = manifest["scenarios"][str(count)]["pumps"]
    pump_pos = np.asarray([unit["chainage_m"] for unit in pumps])
    rows = []
    for i in range(bins):
        mask = index == i
        if not np.any(mask):
            raise ValueError(f"Sección CFD vacía: {i}")
        section_speed = float(np.average(forward[mask], weights=volume[mask]))
        section_width = float(np.median(width[mask]))
        centre = (i+.5)*SECTION_M
        beach = centre < 27 or centre >= 507
        zone = ("Playa principal" if beach else
                "Paso ancho" if section_width >= 15 else
                "Paso angosto" if section_width < 10 else "Paso intermedio")
        sides = []
        for side in (eta < 0, eta >= 0):
            side_mask = mask & side
            sides.append(float(np.average(forward[side_mask], weights=volume[side_mask]))
                         if np.any(side_mask) else float("nan"))
        gap = _circular_distance(np.asarray([centre]), pump_pos, length)[0]
        closest = int(np.argmin(gap))
        rows.append({
            "inicio_m": i*SECTION_M, "fin_m": (i+1)*SECTION_M,
            "zona": zone, "ancho_m": section_width,
            "avance_m_s": section_speed,
            "interior_m_s": sides[0], "exterior_m_s": sides[1],
            "celdas_lentas_pct": float(np.mean(forward[mask] < SLOW_M_S)*100),
            "celdas_rapidas_pct": float(np.mean(forward[mask] > FAST_M_S)*100),
            "bomba_cercana": f"RF-{pumps[closest]['number']:02d}",
            "distancia_bomba_m": float(gap[closest]),
            "bombas_16m": int(np.count_nonzero(gap <= 16)),
        })
    return tuple(rows)


def section_comparison_figure(selected: int) -> go.Figure:
    profiles = {count: section_profile(count) for count in COUNTS}
    x = np.asarray([(row["inicio_m"]+row["fin_m"])/2
                    for row in profiles[selected]])
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[.72, .28], vertical_spacing=.07)
    palette = {16: "#8264bd", 19: "#2475b4", 20: "#db6b24", 21: "#26865e"}
    for count in COUNTS:
        profile = profiles[count]
        fig.add_trace(go.Scatter(x=x, y=[row["avance_m_s"] for row in profile],
            mode="lines+markers", name=f"{count} bombas",
            line=dict(color=palette[count], width=3 if count == selected else 1.7),
            marker=dict(size=5 if count == selected else 3),
            hovertemplate="%{x:.0f} m · %{y:.3f} m/s<extra>"+NAMES[count]+"</extra>"),
            row=1, col=1)
    fig.add_hline(y=SLOW_M_S, row=1, col=1,
                  line=dict(color="#2355a3", dash="dot"))
    fig.add_hline(y=FAST_M_S, row=1, col=1,
                  line=dict(color="#b54c24", dash="dot"))
    fig.add_trace(go.Bar(x=x, y=[row["ancho_m"] for row in profiles[selected]],
        width=SECTION_M*.85, marker_color="#7eb7c3", name="Ancho DXF (m)",
        hovertemplate="%{x:.0f} m · ancho %{y:.1f} m<extra></extra>"), row=2, col=1)
    manifest, _ = load_metadata()
    pump_pos = [unit["chainage_m"] for unit in
                manifest["scenarios"][str(selected)]["pumps"]]
    fig.add_trace(go.Scatter(x=pump_pos, y=np.full(len(pump_pos), -.7),
        mode="markers", marker=dict(symbol="diamond", size=9, color="#ff921b"),
        name="Descargas CFD guardadas", hovertemplate="Descarga · %{x:.0f} m<extra></extra>"),
        row=2, col=1)
    for left, right in ((0, 27), (507, 536)):
        fig.add_vrect(x0=left, x1=right, fillcolor="#f2dabe", opacity=.35,
                      line_width=0, row=1, col=1)
    fig.update_yaxes(title_text="Avance medio (m/s)", row=1, col=1)
    fig.update_yaxes(title_text="Ancho (m)", row=2, col=1, range=[-2, 33])
    fig.update_xaxes(title_text="Progresiva desde la playa (m)", row=2, col=1,
                     range=[0, 536])
    fig.update_layout(height=650, hovermode="x unified",
                      title="Avance por sección de 8 m · cuatro corridas fijas",
                      legend=dict(orientation="h", y=1.08),
                      margin=dict(l=20, r=20, t=105, b=40))
    return fig


def attention_rows(count: int) -> list[dict]:
    rows = []
    for item in section_profile(count):
        zone = item["zona"]
        speed = item["avance_m_s"]
        slower_side_speed = min(item["interior_m_s"], item["exterior_m_s"])
        if zone == "Paso ancho" and (slower_side_speed < SLOW_M_S or
                                      item["celdas_lentas_pct"] >= 25):
            reason = "Paso ancho · carril lento"
            severity = max(0, (SLOW_M_S-slower_side_speed)/SLOW_M_S,
                           item["celdas_lentas_pct"]/100)
        elif zone == "Paso angosto" and speed > FAST_M_S:
            reason = "Paso angosto · avance alto"
            severity = (speed-FAST_M_S)/FAST_M_S
        else:
            continue
        slower_side = ("Interior" if item["interior_m_s"] < item["exterior_m_s"]
                       else "Exterior")
        rows.append({
            "Tramo": f"{item['inicio_m']:.0f}–{item['fin_m']:.0f} m",
            "Observación": reason, "Ancho DXF": round(item["ancho_m"], 1),
            "Avance medio": round(speed, 3),
            "Interior / exterior":
                f"{item['interior_m_s']:.2f} / {item['exterior_m_s']:.2f}",
            "Orilla más lenta": slower_side,
            "Celdas <0,15 (%)": round(item["celdas_lentas_pct"], 1),
            "Bomba más próxima": item["bomba_cercana"],
            "Distancia": round(item["distancia_bomba_m"], 1),
            "severidad": severity,
        })
    rows.sort(key=lambda item: item["severidad"], reverse=True)
    return rows
