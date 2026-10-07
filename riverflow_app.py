"""Riverflow-focused Phase-1 Streamlit interface for the NYA DXF geometry."""

import csv
import hashlib
import io
import os
from dataclasses import replace
from math import ceil

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.colors import sample_colorscale
import streamlit as st

from core.orchestrator import LazyRiverModel
from core.beach_geometry import compute_beach_geometry
from core.centerline import signed_centerline_area
from core.filtration import calculate_backwash, calculate_pipe_losses, evaluate_filtration
from core.filtration_catalog import screen_pump_families
from core.geometry_audit import audit_geometry
from core.riverflow_2d import compute_field_2d
from core.riverflow_3d_pilot import assess_speed_band
from core.riverflow_cfd_preview import compute_cfd_preview
from core.riverflow_decision import (consistency_checks, evaluate_count_options,
                                     evaluate_decision_cases)
from core.riverflow_momentum_pilot import compute_momentum_pilot
from core.riverflow_momentum_bound import compute_momentum_bound
from core.riverflow_jet_momentum import (NOZZLE_12X7_OPEN_AREA_M2,
                                         nozzle_outlet_k, solve_jet_momentum)
from core.riverflow_envelope import evaluate_envelope
from core.riverflow_local_circuit import (LocalCircuit, PVC_12_SCH40_REFERENCE_ID_M,
                                          circuit_head, solve_local_circuit)
from core.riverflow_reference import (LAZY_RIVER_REFERENCES,
                                      reference_operating_point)
from core.riverflow_model import (
    RIVERFLOW_DIGITIZED_POINTS,
    RIVERFLOW_MOTOR_HP,
    RIVERFLOW_RATED_GPM,
    RIVERFLOW_RATED_M3_H,
    US_GPM_TO_M3_H,
    compute_riverflow_plan,
    riverflow_flow_at_head_ft,
    scenario_channel_flow_m3_h,
)
from core.riverflow_placement import (cumulative_manning_resistance,
                                      curve_candidates,
                                      placement_gaps,
                                      suggest_friction_balanced_positions,
                                      suggest_curve_aware_positions)


MODEL_VERSION = "riverflow-geometry-treatment-12-banks-flat-beach"
ASSET_DIR = os.path.join(os.path.dirname(__file__), "assets")
RIVERFLOW_4FT_PLAN_URL = (
    "https://riverflowpumps.com/wp-content/uploads/2023/06/"
    "100716-Lazy-River-4ft-depth.pdf"
)
RIVERFLOW_NOZZLE_PLAN_URL = (
    "https://riverflowpumps.com/wp-content/uploads/2023/06/"
    "Nozzle-Installation-River.pdf"
)
RIVERFLOW_ELECTRICAL_GUIDE_URL = (
    "https://riverflowpumps.com/wp-content/uploads/2023/06/"
    "RF_ElectricalInstallationOnWebsite_08262022.pdf"
)
RIVERFLOW_3FT_PLAN_URL = (
    "https://riverflowpumps.com/wp-content/uploads/2023/06/"
    "022417-Lazy-River-3ft-depth.pdf"
)
RFS_200_MAX_CERTIFIED_M3_H = 2440 * US_GPM_TO_M3_H


@st.cache_resource(show_spinner="Leyendo recorrido DXF...")
def load_geometry(dxf_bytes, target_length_m, version):
    model = LazyRiverModel()
    if dxf_bytes is None:
        path = os.path.join(os.path.dirname(__file__), "RECORRIDO.dxf")
        issues = model.load_dxf(path=path)
    else:
        issues = model.load_dxf(content=dxf_bytes)
    if model.loader.errors:
        raise ValueError("; ".join(model.loader.errors))
    geometry_issues = model.loader.validate()
    if geometry_issues:
        raise ValueError("; ".join(geometry_issues))
    model.build_centerline(resolution_m=0.5, target_length_m=target_length_m)
    if len(model.stations) < 2:
        raise ValueError("El DXF no produjo un recorrido válido en la capa PAREDES.")
    return model, issues


def parse_chainages(value, length_m):
    try:
        positions = [float(piece.strip()) for piece in value.split(",") if piece.strip()]
    except ValueError as exc:
        raise ValueError("Separe las posiciones numéricas con comas.") from exc
    if any(position < 0 or position > length_m for position in positions):
        raise ValueError(f"Cada posición debe estar entre 0 y {length_m:.0f} m.")
    return positions


def add_velocity_areas(fig, model, plan, field=None, color_range=None):
    """Color either the 2D conservative scenario or legacy Q/A strips."""
    if field is not None:
        vmin, vmax = (color_range if color_range is not None else
                      (float(np.min(field.speed_m_s)), float(np.max(field.speed_m_s))))
        bands = 12
        xs, ys, hover = [[] for _ in range(bands)], [[] for _ in range(bands)], [[] for _ in range(bands)]
        for i in range(len(field.chainages_m) - 1):
            for j in range(len(field.lateral_fraction) - 1):
                velocity = float(np.mean(field.speed_m_s[i:i+2, j:j+2]))
                band = max(0, min(bands - 1, int((velocity - vmin) / (vmax - vmin or 1) * bands)))
                corners = ((i,j),(i+1,j),(i+1,j+1),(i,j+1),(i,j))
                xs[band].extend([float(field.x[a,b]) for a,b in corners] + [None])
                ys[band].extend([float(field.y[a,b]) for a,b in corners] + [None])
                label = (f"{field.chainages_m[i]:.0f} m · margen {field.lateral_fraction[j]:.0%}–"
                         f"{field.lateral_fraction[j+1]:.0%} · {velocity:.3f} m/s (escenario 2D)")
                hover[band].extend([label] * 5 + [None])
        for band in range(bands):
            color = sample_colorscale("RdYlBu_r", (band + 0.5) / bands)[0]
            fig.add_trace(go.Scatter(x=xs[band], y=ys[band], text=hover[band], mode="lines",
                                     fill="toself", fillcolor=color,
                                     line=dict(color=color, width=0.2),
                                     name="Velocidad 2D · escenario" if band == 0 else None,
                                     showlegend=band == 0, hovertemplate="%{text}<extra></extra>"))
        fig.add_trace(go.Scatter(x=[float(field.x[0,0])], y=[float(field.y[0,0])],
                                 mode="markers", marker=dict(size=0.1, color=[vmin],
                                 cmin=vmin, cmax=max(vmax,vmin+1e-6), colorscale="RdYlBu_r",
                                 showscale=True, colorbar=dict(title="m/s",len=0.7)),
                                 showlegend=False, hoverinfo="skip"))
        return
    stations = model.stations
    scale = float(model.geometry.scale_m_per_unit) or 1.0
    vmin, vmax = min(plan.station_velocities_m_s), max(plan.station_velocities_m_s)
    bands = 12
    xs = [[] for _ in range(bands)]
    ys = [[] for _ in range(bands)]
    hover = [[] for _ in range(bands)]
    for i, (a, b) in enumerate(zip(stations[:-1], stations[1:])):
        velocity = (plan.station_velocities_m_s[i] + plan.station_velocities_m_s[i + 1]) / 2
        band = min(bands - 1, int((velocity - vmin) / (vmax - vmin or 1) * bands))
        def sides(station):
            offset = float(station["width_m"]) / (2 * scale)
            return ((station["x"] + station["normal_x"] * offset,
                     station["y"] + station["normal_y"] * offset),
                    (station["x"] - station["normal_x"] * offset,
                     station["y"] - station["normal_y"] * offset))
        a_left, a_right = sides(a)
        b_left, b_right = sides(b)
        points = [a_left, b_left, b_right, a_right, a_left]
        xs[band].extend([p[0] for p in points] + [None])
        ys[band].extend([p[1] for p in points] + [None])
        label = (f"{a['chainage_m']:.0f}–{b['chainage_m']:.0f} m · "
                 f"{velocity:.3f} m/s · ancho ≈{(a['width_m'] + b['width_m']) / 2:.1f} m")
        hover[band].extend([label] * len(points) + [None])
    for band in range(bands):
        color = sample_colorscale("RdYlBu_r", (band + 0.5) / bands)[0]
        fig.add_trace(go.Scatter(
            x=xs[band], y=ys[band], text=hover[band], mode="lines",
            fill="toself", fillcolor=color, line=dict(color=color, width=0.3),
            name="Velocidad Q/A · mapa" if band == 0 else None,
            showlegend=band == 0, hovertemplate="%{text}<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=[stations[0]["x"]], y=[stations[0]["y"]], mode="markers",
        marker=dict(size=0.1, color=[vmin], cmin=vmin,
                    cmax=max(vmax, vmin + 1e-6), colorscale="RdYlBu_r", showscale=True,
                    colorbar=dict(title="m/s", len=0.7)),
        showlegend=False, hoverinfo="skip"))


def make_map(model, plan, show_installation=True, show_velocity_heatmap=True, field=None,
             section_checks=None, color_range=None):
    fig = go.Figure()
    if show_velocity_heatmap:
        add_velocity_areas(fig, model, plan, field, color_range)
    scale = float(model.geometry.scale_m_per_unit) or 1.0
    for wall, label, color in (
        (model.loader.outer_wall, "Muro exterior DXF", "#64748b"),
        (model.loader.inner_wall, "Muro interior DXF", "#94a3b8"),
    ):
        if wall is not None:
            coordinates = list(wall.coords)
            fig.add_trace(go.Scatter(x=[p[0] for p in coordinates],
                                     y=[p[1] for p in coordinates], mode="lines",
                                     name=label, line=dict(color=color, width=2)))
    fig.add_trace(go.Scatter(
        x=[model.stations[0]["x"]], y=[model.stations[0]["y"]],
        mode="markers", name="Inicio y fin · playa principal",
        marker=dict(size=15, color="#be185d", symbol="star",
                    line=dict(color="white", width=2)),
        hovertemplate="Inicio/fin de vuelta · playa principal · 0/L<extra></extra>"))
    for zone, label, color in (("current", "Canal de corriente", "#2563eb"),
                               ("calm", "Entradas a playa / zona calma", "#86efac")) if not show_velocity_heatmap else ():
        xs, ys = [], []
        for i, station in enumerate(model.stations):
            if plan.station_zones[i] == zone:
                if i and plan.station_zones[i - 1] != zone:
                    xs.append(model.stations[i - 1]["x"])
                    ys.append(model.stations[i - 1]["y"])
                xs.append(station["x"])
                ys.append(station["y"])
            elif xs and xs[-1] is not None:
                xs.append(None)
                ys.append(None)
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=label,
                                 line=dict(color=color, width=6)))
    pump_x, pump_y, suction_x, suction_y, outlet_x, outlet_y = [], [], [], [], [], []
    pipe_x, pipe_y, flow_x, flow_y, labels = [], [], [], [], []
    for number, position in enumerate(plan.module_chainages_m, 1):
        angle = np.deg2rad(plan.module_angles_deg[number - 1])
        index = min(range(len(model.stations)),
                    key=lambda i: abs(model.stations[i]["chainage_m"] - position))
        station = model.stations[index]
        previous = model.stations[max(0, index - 1)]
        following = model.stations[min(len(model.stations) - 1, index + 1)]
        tx = following["x"] - previous["x"]
        ty = following["y"] - previous["y"]
        norm = (tx ** 2 + ty ** 2) ** 0.5 or 1.0
        tx, ty = tx / norm, ty / norm
        side = 1 if plan.module_banks[number - 1] == "Exterior" else -1
        nx, ny = station["normal_x"] * side, station["normal_y"] * side
        dx, dy = tx * np.cos(angle) + nx * np.sin(angle), ty * np.cos(angle) + ny * np.sin(angle)
        width = float(station["width_m"])
        px = station["x"] + nx * (width / 2 + 2) / scale
        py = station["y"] + ny * (width / 2 + 2) / scale
        sx = station["x"] - tx * 1.2 / scale + nx * width * 0.3 / scale
        sy = station["y"] - ty * 1.2 / scale + ny * width * 0.3 / scale
        ox = station["x"] + tx * 1.2 / scale + nx * width * 0.3 / scale
        oy = station["y"] + ty * 1.2 / scale + ny * width * 0.3 / scale
        labels.append(f"RF-{number:02d} · {position:.0f} m · {plan.module_banks[number-1]} · "
                      f"{plan.module_angles_deg[number-1]:+.0f}°")
        pump_x.append(px)
        pump_y.append(py)
        if show_installation:
            for side in (-0.6, 0.6):
                x, y = sx + tx * side / scale, sy + ty * side / scale
                suction_x.append(x)
                suction_y.append(y)
                pipe_x.extend([x, px, None])
                pipe_y.extend([y, py, None])
            outlet_x.append(ox)
            outlet_y.append(oy)
            pipe_x.extend([px, ox, None])
            pipe_y.extend([py, oy, None])
            flow_x.extend([ox, ox + dx * 3 / scale, None])
            flow_y.extend([oy, oy + dy * 3 / scale, None])
            if number == 1 or number % 4 == 0:
                fig.add_annotation(x=ox + dx * 3 / scale, y=oy + dy * 3 / scale,
                                   ax=ox, ay=oy, xref="x", yref="y", axref="x", ayref="y",
                                   text="", showarrow=True, arrowhead=3,
                                   arrowcolor="#16a34a", arrowsize=1.2)
    if show_installation:
        fig.add_trace(go.Scatter(x=pipe_x, y=pipe_y, mode="lines", name="Tubería local (esquema)",
                                 line=dict(color="#94a3b8", width=1, dash="dot"),
                                 hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=suction_x, y=suction_y, mode="markers",
                                 name="Dos tomas de succión (esquema)",
                                 marker=dict(size=6, color="#0891b2", symbol="square")))
        fig.add_trace(go.Scatter(x=outlet_x, y=outlet_y, mode="markers",
                                 name="Descarga/acelerador (esquema)",
                                 marker=dict(size=8, color="#16a34a", symbol="triangle-up")))
        fig.add_trace(go.Scatter(x=flow_x, y=flow_y, mode="lines", name="Dirección propuesta de flujo",
                                 line=dict(color="#16a34a", width=2), hoverinfo="skip"))
    if show_installation:
        marker_x, marker_y = pump_x, pump_y
    else:
        nearest = [min(model.stations,
                       key=lambda station: abs(station["chainage_m"] - position))
                   for position in plan.module_chainages_m]
        marker_x = [station["x"] for station in nearest]
        marker_y = [station["y"] for station in nearest]
    for bank, color, symbol in (("Exterior", "#ea580c", "diamond"),
                                ("Interior", "#7c3aed", "square")):
        selected = [i for i, assigned in enumerate(plan.module_banks)
                    if assigned == bank]
        if selected:
            fig.add_trace(go.Scatter(
                x=[marker_x[i] for i in selected],
                y=[marker_y[i] for i in selected],
                mode="markers", name=f"Riverflow · margen {bank.lower()}",
                marker=dict(size=12, color=color, symbol=symbol,
                            line=dict(color="white", width=1.5)),
                text=[labels[i] for i in selected],
                hovertemplate="%{text}<extra></extra>"))
    if section_checks:
        flagged = [check for check in section_checks if check.status != "Consistente"]
        if flagged:
            fig.add_trace(go.Scatter(
                x=[check.x for check in flagged], y=[check.y for check in flagged],
                mode="markers", name="Sección DXF por revisar",
                marker=dict(size=12, color="#dc2626", symbol="x"),
                text=[f"{check.chainage_m:.0f} m · {check.status}" for check in flagged],
                hovertemplate="%{text}<extra></extra>"))
    fig.update_layout(height=620, margin=dict(l=15, r=15, t=30, b=15),
                      legend=dict(orientation="h", y=-0.08),
                      xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x"))
    return fig


def make_profile(model, plan):
    chainages = [s["chainage_m"] for s in model.stations]
    widths = [s["width_m"] for s in model.stations]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=chainages, y=widths, mode="lines",
                             name="Ancho DXF", line=dict(color="#2563eb", width=2)))
    fig.add_trace(go.Scatter(x=chainages, y=plan.station_velocities_m_s,
                             mode="lines", name="Velocidad local equivalente",
                             line=dict(color="#ea580c", width=2), yaxis="y2"))
    fig.update_layout(height=340, margin=dict(l=20, r=20, t=25, b=25),
                      xaxis=dict(title="Recorrido (m)"),
                      yaxis=dict(title="Ancho (m)"),
                      yaxis2=dict(title="Velocidad equivalente (m/s)", overlaying="y",
                                  side="right", rangemode="tozero"),
                      legend=dict(orientation="h", y=1.12))
    return fig


def make_friction_profile(model, plan):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[s["chainage_m"] for s in model.stations],
                             y=plan.cumulative_friction_head_m, mode="lines",
                             name="Pérdida acumulada Manning", line=dict(color="#7c3aed", width=3)))
    fig.update_layout(height=280, margin=dict(l=20, r=20, t=20, b=25),
                      xaxis_title="Recorrido antihorario desde playa principal (m)",
                      yaxis_title="Pérdida acumulada de canal (m)")
    return fig


def make_installation_schematic():
    """Manufacturer-inspired topology; no NYA dimensions or loss coefficients."""
    fig = go.Figure()
    fig.add_shape(type="rect", x0=0, y0=0, x1=10, y1=3,
                  fillcolor="#dbeafe", line=dict(color="#60a5fa"))
    fig.add_trace(go.Scatter(x=[1.2, 3, None, 1.8, 3, None, 3, 5, 7.5],
                             y=[1.5, 2.3, None, 1.5, 2.3, None, 2.3, 3.3, 1.5],
                             mode="lines", name="Ramales → bomba → retorno",
                             line=dict(color="#64748b", width=4)))
    fig.add_trace(go.Scatter(x=[1.2, 1.8], y=[1.5, 1.5], mode="markers",
                             name="Toma doble protegida",
                             marker=dict(color="#0891b2", size=15, symbol="square")))
    fig.add_trace(go.Scatter(x=[5], y=[3.3], mode="markers", name="Bomba local Riverflow",
                             marker=dict(color="#ea580c", size=22, symbol="diamond")))
    fig.add_trace(go.Scatter(x=[7.5], y=[1.5], mode="markers",
                             name="Acelerador / descarga",
                             marker=dict(color="#16a34a", size=19, symbol="triangle-up")))
    fig.add_annotation(x=9.4, y=1.5, ax=7.8, ay=1.5, text="Corriente propuesta",
                       showarrow=True, arrowhead=3, arrowcolor="#16a34a")
    fig.add_annotation(x=1.8, y=0.9, text="2 tomas · ramales 10″ en plano 4 ft",
                       showarrow=False)
    fig.add_annotation(x=3.5, y=2.65, text="Colector · dimensiones NYA pendientes",
                       showarrow=False)
    fig.add_annotation(x=7.9, y=2.55, text="Retorno 12″ · boquilla 7 puertos",
                       showarrow=False)
    fig.add_annotation(x=5, y=4.25, text="Variador y tableros en área eléctrica protegida",
                       showarrow=False)
    fig.add_annotation(x=5, y=0.4, text="Agua del río · sin cotas de NYA",
                       showarrow=False)
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=15, b=10),
                      xaxis=dict(visible=False, range=[-0.5, 10.5]),
                      yaxis=dict(visible=False, range=[-0.5, 4.6], scaleanchor="x"),
                      legend=dict(orientation="h", y=-0.08))
    return fig


def documentation_calculation_audit(*, suction_length_m, discharge_length_m,
                                    suction_k, discharge_k, outlet_k,
                                    transfer_pct, nozzle_type, nozzle_cd=None):
    """Expose source-to-calculation gaps without changing hydraulic outputs."""
    return [
        {"Tema": "Succión doble", "Lo que se calcula": "Un conducto equivalente de succión",
         "Dato del plano": "Dos tomas y ramales nominales de 10″ hacia la bomba",
         "Pendiente para NYA": "Longitud/diámetro interior de cada ramal y reparto de caudal"},
        {"Tema": "Pérdidas del circuito", "Lo que se calcula":
         f"Longitudes {suction_length_m:g}/{discharge_length_m:g} m; K {suction_k:g}/{discharge_k:g}/{outlet_k:g}",
         "Dato del plano": "Topología y piezas de una instalación de referencia",
         "Pendiente para NYA": "Trazado real, cotas y K verificables de piezas y boquilla"},
        {"Tema": "Tipo de salida", "Lo que se calcula": (
            f"{nozzle_type}: área 0,2892 ft² y K equivalente con Cd={nozzle_cd:.2f} supuesto"
            if nozzle_type == "7 puertos" and nozzle_cd is not None else
            f"{nozzle_type}: K de salida manual, sin área hidráulica comprobada"),
         "Dato del plano": "Área abierta en carta Brannon; montaje en plano ejemplo",
         "Pendiente para NYA": "Cd y curva real de pérdidas; área/curva para 3 puertos"},
        {"Tema": "Impulso del río", "Lo que se calcula":
         f"Acoplamiento efectivo supuesto: {transfer_pct:g}%",
         "Dato del plano": "No ofrece velocidades medidas en un río comparable",
         "Pendiente para NYA": "Calibración con mediciones o CFD contrastado"},
        {"Tema": "Viabilidad de montaje", "Lo que se calcula": "No comprobada",
         "Dato del plano": "Succión inundada, nivel de bomba y dos tomas",
         "Pendiente para NYA": "Sección/cotas de cada estación y seguridad de captaciones"},
        {"Tema": "Electricidad", "Lo que se calcula": "HP nominales, no kW consumidos",
         "Dato del plano": "Motor, variador y necesidad de área protegida",
         "Pendiente para NYA": "Potencia eléctrica a operación y diseño local de alimentación"},
    ]


def make_count_chart(plan):
    counts = list(range(1, 61))
    times = [plan.volume_m3 * 60 / scenario_channel_flow_m3_h(
        plan.channel_resistance_s2_m5, plan.module_flow_full_speed_m3_h,
        count, plan.speed_fraction,
        plan.transfer_fraction, plan.placement_effectiveness) for count in counts]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=counts, y=times, mode="lines", name="Vuelta estimada",
                             line=dict(color="#2563eb", width=3)))
    fig.add_trace(go.Scatter(x=[plan.active_modules], y=[plan.estimated_lap_min],
                             mode="markers", name="Configuración actual",
                             marker=dict(size=12, color="#ea580c")))
    fig.add_hline(y=plan.target_lap_min, line_dash="dash", line_color="#16a34a",
                  annotation_text=f"Meta {plan.target_lap_min:.0f} min")
    fig.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=25),
                      xaxis_title="Unidades activas", yaxis_title="Minutos por vuelta",
                      yaxis=dict(rangemode="tozero"))
    return fig


def simulated_positions(stations, section_areas_m2, time_phases):
    """Positions along a Q/A travel-time coordinate; not a CFD particle model."""
    if np.isscalar(section_areas_m2):
        # Preserve callers that provide uniform depth rather than areas.
        section_areas_m2 = [float(s["width_m"]) * float(section_areas_m2)
                            for s in stations]
    cumulative_volume = [0.0]
    for i, (previous, current) in enumerate(zip(stations, stations[1:])):
        ds = float(current["chainage_m"] - previous["chainage_m"])
        mean_area = (section_areas_m2[i] + section_areas_m2[i + 1]) / 2
        cumulative_volume.append(cumulative_volume[-1] + ds * mean_area)
    if cumulative_volume[-1] <= 0:
        raise ValueError("No se puede animar un recorrido sin volumen positivo.")
    fractions = np.asarray(cumulative_volume) / cumulative_volume[-1]
    phases = np.mod(np.asarray(time_phases, dtype=float), 1.0)
    return (np.interp(phases, fractions, [s["x"] for s in stations]),
            np.interp(phases, fractions, [s["y"] for s in stations]))


def simulated_field_positions(field, time_phases):
    phases = np.mod(np.asarray(time_phases, dtype=float), 1.0)
    travel_fraction = field.center_lane_time_min / field.center_lane_time_min[-1]
    return (np.interp(phases, travel_fraction, field.center_lane_x),
            np.interp(phases, travel_fraction, field.center_lane_y))


def make_fast_simulation(model, plan, playback_multiplier, field=None):
    """Animate a conceptual center streamline on the same 2D scenario field."""
    frame_count = 72
    rider_count = 8
    lap_min = field.lane_lap_min[1] if field is not None else plan.estimated_lap_min
    frame_ms = max(30, round(lap_min * 60_000 /
                             (playback_multiplier * frame_count)))
    initial_phases = np.arange(rider_count) / rider_count
    position_fn = (lambda phases: simulated_field_positions(field, phases)) if field is not None else (
        lambda phases: simulated_positions(model.stations, plan.station_areas_m2, phases))
    x0, y0 = position_fn(initial_phases)
    fig = go.Figure()
    add_velocity_areas(fig, model, plan, field)
    fig.add_trace(go.Scatter(x=[s["x"] for s in model.stations],
                             y=[s["y"] for s in model.stations], mode="lines",
                             name="Centro del canal · antihorario",
                             line=dict(color="#334155", width=1)))
    fig.add_trace(go.Scatter(
        x=[model.stations[0]["x"]], y=[model.stations[0]["y"]],
        mode="markers", name="Inicio y fin · playa principal",
        marker=dict(size=16, color="#be185d", symbol="star",
                    line=dict(color="white", width=2)),
        hovertemplate="Inicio/fin de vuelta · playa principal<extra></extra>"))
    fig.add_trace(go.Scatter(x=x0, y=y0, mode="markers", name="Personas con chaleco o barra de espuma · ilustración",
                             marker=dict(size=13, color="#f97316", line=dict(color="white", width=1))))
    rider_trace = len(fig.data) - 1
    frames = []
    for frame in range(frame_count):
        phases = (initial_phases + frame / frame_count) % 1.0
        xs, ys = position_fn(phases)
        frames.append(go.Frame(name=str(frame), data=[go.Scatter(x=xs, y=ys,
                           mode="markers", marker=dict(size=13, color="#f97316",
                                                       line=dict(color="white", width=1)),
                           text=[f"Persona {i+1} · deriva pasiva supuesta" for i in range(rider_count)],
                           hovertemplate="%{text}<extra></extra>")], traces=[rider_trace]))
    fig.frames = frames
    fig.update_layout(height=540, margin=dict(l=10, r=10, t=20, b=10),
                      xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x"),
                      showlegend=True,
                      updatemenus=[dict(type="buttons", direction="left", x=0, y=1.12,
                                        buttons=[dict(label="▶ Reproducir", method="animate",
                                                      args=[None, {"frame": {"duration": frame_ms,
                                                                              "redraw": True},
                                                                   "transition": {"duration": 0},
                                                                   "fromcurrent": True}]),
                                                 dict(label="⏸ Pausar", method="animate",
                                                      args=[[None], {"mode": "immediate",
                                                                     "frame": {"duration": 0,
                                                                               "redraw": False}}])])])
    return fig


def make_csv(plan, nozzle_type):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Unidad", "Chainage_m", "Margen", "Angulo_descarga_deg",
                     "Caudal_nominal_a_velocidad_m3h", "Motor_placa_HP", "Salida", "Estado"])
    for i, chainage in enumerate(plan.module_chainages_m, 1):
        flow = plan.module_flows_full_speed_m3_h[i-1] * plan.speed_fraction
        writer.writerow([f"RF-{i:02d}", f"{chainage:.1f}", plan.module_banks[i-1],
                         f"{plan.module_angles_deg[i-1]:.1f}", f"{flow:.1f}",
                         f"{RIVERFLOW_MOTOR_HP:.0f}", nozzle_type, "Activa"])
    for i in range(plan.standby_modules):
        writer.writerow([f"RES-{i+1:02d}", "Por definir", "Por definir", "Por definir", 0,
                         f"{RIVERFLOW_MOTOR_HP:.0f}", nozzle_type, "Reserva"])
    return output.getvalue().encode("utf-8-sig")


def main():
    st.markdown("<h1 style='color:#2563eb;text-align:center'>Selvatura NYA · Lazy River / Riverflow</h1>",
                unsafe_allow_html=True)
    st.caption("Fase 1 · recorrido antihorario · geometría DXF y dimensionamiento conceptual de propulsión, filtración e infraestructura")

    st.sidebar.header("Diseño NYA desde DXF")
    uploaded = st.sidebar.file_uploader("Plano DXF (capa PAREDES)", type=["dxf"])
    target_length_m = st.sidebar.number_input(
        "Longitud de referencia para escalar DXF (m)", min_value=100.0,
        max_value=2000.0, value=536.0, step=1.0,
        help="Escala longitud y anchos con el mismo factor. Ningún ancho fijo reemplaza el DXF.")
    depth_m = st.sidebar.number_input("Profundidad de agua (m)", 0.4, 3.0, 1.2, 0.05)
    calm_width_m = st.sidebar.number_input("Zona calma desde ancho (m)", 4.0, 40.0, 15.0, 0.5,
                                           help="Las partes anchas del DXF se tratan como entradas a playa.")
    st.sidebar.subheader("Acabados y resistencia del canal")
    wall_finish = st.sidebar.selectbox(
        "Acabado propuesto de paredes",
        ["Piedra local impermeabilizada", "Concreto texturizado tipo piedra", "Personalizado"],
        help="Son escenarios de fase 1. El revestimiento final y su rugosidad deben definirse y verificarse.")
    wall_default = {"Piedra local impermeabilizada": 0.025,
                    "Concreto texturizado tipo piedra": 0.017,
                    "Personalizado": 0.020}[wall_finish]
    floor_n = st.sidebar.slider("Manning n · piso liso", 0.010, 0.035, 0.013,
                                0.001, format="%.3f",
                                help="Hipótesis para un fondo liso transitable; no certifica textura antideslizante ni seguridad.")
    wall_n_current = st.sidebar.slider(
        "Manning n · paredes de corriente", 0.010, 0.040, wall_default,
        0.001, format="%.3f", key=f"rf_wall_current_{wall_finish}",
        help="Escenario de rugosidad de pared, no un valor confirmado para el material de NYA.")
    wall_n_calm = st.sidebar.slider(
        "Manning n · paredes de playa", 0.010, 0.040, wall_default,
        0.001, format="%.3f", key=f"rf_wall_calm_{wall_finish}",
        help="Se usa en las secciones anchas identificadas desde el DXF.")

    try:
        model, issues = load_geometry(uploaded.getvalue() if uploaded else None,
                                      target_length_m, MODEL_VERSION)
    except (ValueError, OSError) as exc:
        st.error(f"No se pudo procesar el DXF: {exc}")
        st.stop()
    for issue in issues:
        st.warning(str(issue))
    if signed_centerline_area(model.stations) <= 0:
        st.error("No se pudo confirmar el sentido antihorario del recorrido.")
        st.stop()

    st.sidebar.subheader("Perfil de la playa principal · anteproyecto")
    use_beach_profile = st.sidebar.checkbox(
        "Aplicar cotas proporcionales al DXF", value=True,
        help="Solo el ensanchamiento mayor recibe esta rampa. Los demás siguen como bahías calmas profundas.")
    beach_first_share = st.sidebar.slider(
        "Fracción plana de playa (% del ancho extra DXF)", 20, 80, 62, 1,
        help="Equivale proporcionalmente a 16 m planos de un perfil de 26 m; el resto es rampa.")
    beach_ramp_pct = st.sidebar.number_input(
        "Pendiente de rampa de playa (%)", 1.0, 20.0, 6.5, 0.5,
        help="Si no alcanza profundidad cero dentro del DXF, se informa la profundidad restante.")
    try:
        beach_geometry = (compute_beach_geometry(
            model.stations, depth_m, calm_width_m, first_share=beach_first_share / 100,
            flat_ramp_slope=beach_ramp_pct / 100)
            if use_beach_profile else None)
    except ValueError as exc:
        st.error(f"No se pudo calcular el perfil de playa: {exc}")
        st.stop()

    st.sidebar.header("Unidades Riverflow")
    target_lap_min = st.sidebar.number_input("Objetivo de tiempo por vuelta (min)",
                                             5.0, 120.0, 40.0, 0.5)
    active_modules = st.sidebar.number_input("Unidades activas", 1, 60, 19, 1)
    standby_modules = st.sidebar.number_input("Unidades de reserva", 0, 10, 1, 1,
                                              help="No aportan caudal mientras están apagadas.")
    curve_choice = st.sidebar.selectbox(
        "Lectura de curva H–Q", ["Puntos visibles de la imagen · aproximados",
                                   "Solo 2 puntos rotulados · interpolación lineal"],
        help="La imagen contiene puntos intermedios sin tabla numérica. Su digitalización es aproximada; "
             "los puntos rotulados de 4 y 10 ft son exactos y no se extrapola fuera de ellos.")
    curve_mode = "photo" if curve_choice.startswith("Puntos") else "anchors"
    speed_pct = st.sidebar.slider("Velocidad del variador (%)", 50, 100, 100, 1,
                                  help="Q proporcional a RPM es una aproximación; la curva H–Q real determina el caudal.")
    use_local_circuit = st.sidebar.checkbox(
        "Resolver circuito local por unidad · escenario", value=True,
        help="Cruza la curva H–Q disponible con pérdidas de tubería y coeficientes K editables. "
             "El trazado y los K de NYA aún son hipótesis; no es una selección para compra.")
    reference_options = ("Circuito NYA editable",) + tuple(
        reference.label for reference in LAZY_RIVER_REFERENCES)
    hydraulic_source = st.sidebar.selectbox(
        "Fuente del punto de operación · prueba local", reference_options,
        disabled=not use_local_circuit,
        help="NYA editable conserva las pérdidas manuales. Las otras opciones son puntos "
             "aproximados de instalaciones ejemplo Riverflow, no mediciones de NYA.")
    selected_reference = (next((reference for reference in LAZY_RIVER_REFERENCES
                                if reference.label == hydraulic_source), None)
                          if use_local_circuit else None)
    nozzle_type = st.sidebar.selectbox(
        "Salida propuesta", ["7 puertos", "Manifold de 3 puertos"],
        help="Solo la salida 12 × 7 tiene área abierta documentada (0,2892 ft²). "
             "Para tres puertos falta el área y su curva de pérdidas: no se extrapolan las del modelo de siete.")
    if selected_reference is not None and nozzle_type != "7 puertos":
        st.sidebar.warning("La referencia Brannon incluye acelerador de 7 puertos. "
                           "Seleccionar 3 puertos no recalcula ese punto documentado.")
    with st.sidebar.expander("Circuito local · toma → bomba → descarga", expanded=use_local_circuit):
        st.caption("El plano de Riverflow muestra dos tomas, tubería PVC Sch 40 nominal de 12″ "
                   "y salida de 7 puertos. El diámetro interior inicial ≈0.303 m procede de "
                   "una ficha de tubería Sch 40 de Westlake: es una REFERENCIA de producto, "
                   "no el material elegido para NYA. Longitudes y K siguen siendo hipótesis.")
        suction_length = st.number_input("Longitud succión por unidad (m)", 0.0, 100.0, 8.0, 0.5)
        suction_diameter = st.number_input("Diámetro interior succión (m)", 0.10, 0.50,
                                          round(PVC_12_SCH40_REFERENCE_ID_M, 3), 0.001, format="%.3f")
        discharge_length = st.number_input("Longitud descarga por unidad (m)", 0.0, 100.0, 8.0, 0.5)
        discharge_diameter = st.number_input("Diámetro interior descarga (m)", 0.10, 0.50,
                                            round(PVC_12_SCH40_REFERENCE_ID_M, 3), 0.001, format="%.3f")
        suction_k = st.number_input("K agregado tomas y accesorios succión · hipótesis", 0.0, 30.0, 1.0, 0.5)
        discharge_k = st.number_input("K agregado accesorios descarga · hipótesis", 0.0, 30.0, 1.0, 0.5)
        documented_nozzle = nozzle_type == "7 puertos"
        nozzle_loss_mode = st.radio(
            "Pérdida de salida para circuito NYA",
            ["Área documentada + Cd supuesto", "K manual"],
            disabled=not documented_nozzle,
            help="El área abierta está documentada; Cd NO fue medido. El K equivalente "
                 "sustituye al K manual, nunca se suma a él.") if documented_nozzle else "K manual"
        if nozzle_loss_mode == "Área documentada + Cd supuesto":
            nozzle_cd = st.slider(
                "Cd supuesto del acelerador (no medido)", 0.50, 1.00, 0.85, 0.01,
                help="Representa de forma simplificada la contracción/pérdida del acelerador. "
                     "0,85 es una hipótesis de prueba, no un rendimiento publicado por Riverflow.")
            outlet_k = nozzle_outlet_k(discharge_diameter,
                                       NOZZLE_12X7_OPEN_AREA_M2, nozzle_cd)
            st.caption(f"Área abierta Riverflow 12 × 7: 0,2892 ft² = "
                       f"{NOZZLE_12X7_OPEN_AREA_M2:.5f} m². "
                       f"K equivalente de salida = {outlet_k:.2f} sobre la velocidad en tubería. "
                       "Cambia con el diámetro y Cd; el valor real de Cd sigue sin conocerse.")
        else:
            nozzle_cd = None
            outlet_k = st.number_input(
                "K salida/acelerador · hipótesis no medida", 0.0, 30.0, 3.0, 0.5,
                help="Se usa si la salida es de 3 puertos o se desea comparar un K manual. "
                     "No representa una pérdida medida del fabricante.")
        static_head = st.number_input("Desnivel neto del circuito (m)", 0.0, 5.0, 0.0, 0.1,
                                      help="En recirculación desde y hacia el mismo espejo de agua se usa 0; "
                                           "no representa la elevación física de la bomba ni verifica succión inundada.")
        custom_circuits = st.checkbox(
            "Editar tuberías y pérdidas por unidad", value=False,
            disabled=not use_local_circuit or selected_reference is not None,
            help="Cada RF puede tener otra longitud, diámetro interior y K. "
                 "Los valores siguen siendo hipótesis hasta definir el trazado constructivo.")
        circuit_rows = None
        if custom_circuits:
            defaults = pd.DataFrame({
                "RF": [f"RF-{i:02d}" for i in range(1, active_modules + 1)],
                "Succión m": [suction_length] * active_modules,
                "Ø succión m": [suction_diameter] * active_modules,
                "Descarga m": [discharge_length] * active_modules,
                "Ø descarga m": [discharge_diameter] * active_modules,
                "K succión": [suction_k] * active_modules,
                "K descarga": [discharge_k] * active_modules,
            })
            if nozzle_cd is None:
                defaults["K salida"] = [outlet_k] * active_modules
            else:
                st.caption("El K de salida se recalcula para cada unidad con su diámetro "
                           "de descarga y el Cd supuesto; no se edita ni se suma otro K.")
            circuit_rows = st.data_editor(
                defaults, hide_index=True, num_rows="fixed", disabled=["RF"],
                key=f"rf_circuits_{active_modules}", width="stretch")
    local_head_manual_ft = st.sidebar.number_input(
        "TDH local manual a plena velocidad (ft)", 4.0, 10.0, 4.0, 0.5,
        disabled=use_local_circuit,
        help="Solo se usa al desactivar el circuito local. Es una hipótesis entre las dos anclas de la curva.")
    circuit = LocalCircuit(suction_length, suction_diameter, discharge_length,
                           discharge_diameter, suction_k, discharge_k, outlet_k,
                           static_head)
    local_point = None
    local_points = None
    reference_point = None
    operating_flow_m3_h = None
    module_full_speed_flows = None
    try:
        if use_local_circuit:
            if selected_reference is None:
                if custom_circuits:
                    local_points = []
                    for i, row in circuit_rows.iterrows():
                        try:
                            unit_outlet_k = (nozzle_outlet_k(
                                float(row["Ø descarga m"]), NOZZLE_12X7_OPEN_AREA_M2,
                                nozzle_cd) if nozzle_cd is not None else float(row["K salida"]))
                            unit_circuit = LocalCircuit(
                                float(row["Succión m"]), float(row["Ø succión m"]),
                                float(row["Descarga m"]), float(row["Ø descarga m"]),
                                float(row["K succión"]), float(row["K descarga"]),
                                unit_outlet_k, static_head)
                            local_points.append(solve_local_circuit(
                                unit_circuit, speed_fraction=speed_pct / 100,
                                curve_mode=curve_mode))
                        except (TypeError, ValueError) as exc:
                            raise ValueError(f"RF-{i+1:02d}: {exc}") from exc
                    module_full_speed_flows = [point.flow_m3_h / (speed_pct / 100)
                                               for point in local_points]
                    operating_flow_m3_h = sum(point.flow_m3_h for point in local_points) / active_modules
                    local_head_ft = sum(point.pump_head_ft for point in local_points) / active_modules / (speed_pct / 100) ** 2
                else:
                    local_point = solve_local_circuit(circuit, speed_fraction=speed_pct / 100,
                                                      curve_mode=curve_mode)
                    operating_point = local_point
            else:
                reference_point = reference_operating_point(
                    selected_reference, speed_fraction=speed_pct / 100)
                operating_point = reference_point
            if not custom_circuits:
                local_head_ft = operating_point.pump_head_ft / (speed_pct / 100) ** 2
                operating_flow_m3_h = operating_point.flow_m3_h
        else:
            local_head_ft = local_head_manual_ft
    except ValueError as exc:
        st.error(f"Circuito local: {exc}")
        st.stop()
    transfer_pct = st.sidebar.slider(
        "Energía útil para mover el río (%)", 0.5, 20.0, 2.0, 0.5,
        help="Hipótesis NO medida: fracción de la potencia hidráulica de las bombas que termina "
             "sosteniendo la corriente longitudinal tras pérdidas locales, boquillas y mezcla. "
             "2% es solo un punto de prueba, no un dato de Riverflow.")
    placement_mode = st.sidebar.radio("Ubicación de unidades", ["Automática", "Editar por recorrido (m)"],
                                      help="La ubicación automática evita las entradas a playa.",
                                      key="riverflow_placement_mode")
    manual_positions = None
    if placement_mode == "Editar por recorrido (m)":
        eligible = [station for station in model.stations
                    if station["width_m"] < calm_width_m] or model.stations
        initial = [eligible[round((i + 0.5) * (len(eligible) - 1) / active_modules)]["chainage_m"]
                   for i in range(active_modules)]
        old_key = f"riverflow_positions_{active_modules}"
        previous_ccw_key = f"riverflow_positions_ccw_{active_modules}"
        position_key = f"riverflow_positions_beach_{active_modules}"
        origin = float(model.stations[0]["dxf_origin_chainage_m"])
        if position_key not in st.session_state and previous_ccw_key in st.session_state:
            try:
                previous_positions = parse_chainages(st.session_state[previous_ccw_key],
                                                     model.geometry.channel_length_m)
                length = model.geometry.channel_length_m
                st.session_state[position_key] = ", ".join(
                    f"{(p - origin) % length:.1f}" for p in previous_positions)
            except (ValueError, TypeError):
                pass
        if (old_key in st.session_state and position_key not in st.session_state):
            try:
                old_positions = parse_chainages(st.session_state[old_key],
                                                 model.geometry.channel_length_m)
                length = model.geometry.channel_length_m
                st.session_state[position_key] = ", ".join(
                    f"{((length - p) - origin) % length:.1f}" for p in old_positions)
            except (ValueError, TypeError):
                pass
        position_default = ({"value": ", ".join(f"{x:.0f}" for x in initial)}
                            if position_key not in st.session_state else {})
        text = st.sidebar.text_area("Posición de cada unidad, separada por coma",
                                    key=position_key, height=100, **position_default)
        try:
            manual_positions = parse_chainages(text, model.geometry.channel_length_m)
        except ValueError as exc:
            st.sidebar.error(str(exc))
            st.stop()
    angle_mode = st.sidebar.radio("Orientación de descargas",
                                  ["Todas alineadas", "Editar ángulos por unidad"],
                                  help="0° sigue el recorrido antihorario; valores positivos se inclinan hacia la margen elegida. "
                                       "La penalización por ángulo es una hipótesis de escenario.")
    if angle_mode == "Todas alineadas":
        common_angle = st.sidebar.slider("Ángulo de descarga respecto al recorrido (°)",
                                         -60, 60, 0, 5)
        module_angles = [float(common_angle)] * active_modules
    else:
        angles_text = st.sidebar.text_area("Ángulos por unidad (°), separados por coma",
                                           value=", ".join(["0"] * active_modules),
                                           key=f"riverflow_angles_{active_modules}", height=100)
        try:
            module_angles = [float(piece.strip()) for piece in angles_text.split(",") if piece.strip()]
        except ValueError:
            st.sidebar.error("Los ángulos deben ser números separados por comas.")
            st.stop()

    module_banks = ["Exterior"] * active_modules
    if placement_mode == "Editar por recorrido (m)":
        with st.sidebar.expander("Margen de cada Riverflow · esquema", expanded=False):
            st.caption("E = exterior del circuito DXF; I = interior. El exterior de una curva "
                       "puede ser E o I según el sentido del giro. Esto cambia el mapa lateral "
                       "exploratorio, no valida la velocidad real del chorro.")
            bank_key = f"riverflow_banks_{active_modules}"
            bank_default = ({"value": ", ".join(["E"] * active_modules)}
                            if bank_key not in st.session_state else {})
            bank_text = st.text_area(
                "Margen por unidad, E o I, separadas por coma",
                key=bank_key, height=100, **bank_default)
            bank_codes = [item.strip().upper() for item in bank_text.split(",") if item.strip()]
            if len(bank_codes) != active_modules or any(code not in ("E", "I") for code in bank_codes):
                st.error(f"Ingrese exactamente {active_modules} márgenes: E o I.")
                st.stop()
            module_banks = ["Exterior" if code == "E" else "Interior" for code in bank_codes]

    st.sidebar.header("Tratamiento separado")
    turnover_h = st.sidebar.number_input("Recirculación de filtración (h)",
                                         2.0, 12.0, 4.0, 0.5,
                                         help="Q filtrado = volumen / horas. 4 h es el escenario NYA, "
                                              "6 h es la referencia general de Costa Rica para vasos >0,60 m "
                                              "si aplica, y 2 h es referencia internacional MAHC para lazy rivers. "
                                              "No se suma el caudal de propulsión Riverflow.")

    try:
        plan_inputs = dict(depth_m=depth_m, target_lap_min=target_lap_min,
                           active_modules=active_modules, standby_modules=standby_modules,
                           module_head_full_speed_ft=local_head_ft,
                           speed_fraction=speed_pct / 100, transfer_fraction=transfer_pct / 100,
                           calm_zone_width_m=calm_width_m, filtration_turnover_h=turnover_h,
                           floor_manning_n=floor_n, wall_manning_n_current=wall_n_current,
                           wall_manning_n_calm=wall_n_calm, curve_mode=curve_mode,
                           module_angles_deg=module_angles, beach_geometry=beach_geometry,
                           module_flow_full_speed_override_m3_h=(
                               operating_flow_m3_h / (speed_pct / 100)
                               if operating_flow_m3_h is not None else None),
                           module_flows_full_speed_m3_h=module_full_speed_flows)
        plan = compute_riverflow_plan(model.stations,
                                      module_chainages_m=manual_positions,
                                      module_banks=module_banks, **plan_inputs)
        perimeters = (beach_geometry.wetted_perimeter_m if beach_geometry is not None else
                      tuple(float(s["width_m"]) + 2 * depth_m for s in model.stations))
        if placement_mode == "Automática":
            # Apply the same auditable bend/friction proposal that was formerly
            # available only through a manual button. No bank choice is treated
            # as a measured jet-reach or construction recommendation.
            automatic_resistance = cumulative_manning_resistance(
                model.stations, plan.station_areas_m2, perimeters,
                plan.station_manning_n)
            automatic_bends = curve_candidates(
                model.stations, plan.station_zones,
                model.geometry.scale_m_per_unit)
            automatic_positions, automatic_banks = suggest_curve_aware_positions(
                model.stations, automatic_resistance, plan.station_zones,
                active_modules, automatic_bends)
            plan = compute_riverflow_plan(
                model.stations, module_chainages_m=automatic_positions,
                module_banks=automatic_banks, **plan_inputs)
        field = compute_field_2d(model.stations, plan, depth_m,
                                 scale_m_per_unit=model.geometry.scale_m_per_unit)
        momentum_bound = compute_momentum_bound(model.stations, plan, perimeters)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    if manual_positions is not None:
        calm_positions = [i for i, position in enumerate(plan.module_chainages_m, 1)
                          if plan.station_zones[min(range(len(model.stations)),
                             key=lambda j: abs(model.stations[j]["chainage_m"] - position))] == "calm"]
        if calm_positions:
            st.warning("Unidades manuales en zonas calmas: " + ", ".join(map(str, calm_positions)) +
                       ". Compruebe que no alteren las entradas a playa.")

    if placement_mode == "Automática":
        exterior_count = plan.module_banks.count("Exterior")
        st.caption(f"Ubicación automática activa: {exterior_count} unidades en la margen "
                   f"exterior del circuito y {plan.active_modules - exterior_count} "
                   "en la interior. El criterio combina resistencia de Manning entre "
                   "descargas y aproximación a curvas del DXF; es una propuesta "
                   "geométrica, no una ubicación validada de tomas/boquillas.")

    st.info("El caudal por Riverflow proviene de la curva H–Q recibida: los dos extremos rotulados "
            "son datos exactos y los puntos intermedios leídos de la imagen son aproximados. "
            "Manning ahora interviene en la corriente y el tiempo de vuelta mediante un balance "
            "energético conceptual. La fracción de energía útil (2% inicial), longitudes, diámetros "
            "interiores y coeficientes K del circuito local NO están medidos en NYA: "
            "el resultado es sensibilidad, no desempeño garantizado.")
    if custom_circuits:
        st.warning("Los resultados del escenario ACTIVO y el listado de equipos usan el circuito "
                   "editado de cada RF. Las matrices y alternativas que cambian la cantidad de "
                   "unidades siguen suponiendo un circuito común: no use esas filas para "
                   "comparar el trazado individual de tuberías.")

    st.subheader("Resultado del escenario")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Meta de vuelta", f"{plan.target_lap_min:.1f} min")
    c2.metric("Vuelta media V/Q", f"{plan.estimated_lap_min:.1f} min")
    c3.metric("Caudal de unidades", f"{plan.installed_operating_flow_m3_h:,.0f} m³/h")
    c4.metric("Corriente longitudinal · escenario", f"{plan.equivalent_channel_flow_m3_h:,.0f} m³/h")
    c5.metric("Vuelta central 2D", f"{field.lane_lap_min[1]:.1f} min")
    slow_lane = max(field.lane_lap_min)
    if slow_lane <= plan.target_lap_min:
        st.info(f"El escenario conceptual queda bajo la meta en las tres trayectorias 2D "
                f"({min(field.lane_lap_min):.1f}–{slow_lane:.1f} min). "
                "No es una garantía de recorrido real ni una cantidad de compra.")
    else:
        st.warning(f"La trayectoria más lenta del escenario 2D tarda {slow_lane:.1f} min, "
                   f"por encima de la meta de {target_lap_min:.1f} min. "
                   f"La aritmética V/Q indica {plan.required_active_modules} unidades para la meta, "
                   "pero no dimensiona las trayectorias ni constituye una selección de compra.")

    g1, g2, g3, g4, g5 = st.columns(5)
    g1.metric("Volumen DXF + perfil" if beach_geometry else "Volumen DXF uniforme",
              f"{plan.volume_m3:,.0f} m³")
    g2.metric("Q requerido para meta", f"{plan.target_equivalent_flow_m3_h:,.0f} m³/h")
    g3.metric("Motores activos · placa", f"{plan.active_motor_nameplate_hp:.0f} HP")
    g4.metric("Filtración separada", f"{plan.filtration_flow_m3_h:,.0f} m³/h")
    g5.metric("Q medio por unidad · fuente elegida" if custom_circuits else
              "Q por unidad · fuente elegida",
              f"{plan.module_flow_full_speed_m3_h:,.0f} m³/h",
              help=f"{hydraulic_source if use_local_circuit else 'TDH manual'}: "
                   f"{local_head_ft:.1f} ft ({local_head_ft * 0.3048:.2f} m) "
                   "de TDH local equivalente a plena velocidad.")
    st.caption(f"Acoplamiento por ancho y orientación propuestos: {plan.placement_effectiveness:.0%} "
               "del escenario de referencia. Es una hipótesis, no una eficiencia certificada.")

    if "filtration_active_pumps" not in st.session_state:
        st.session_state["filtration_active_pumps"] = 6

    # Navigation follows the decisions this preliminary model can currently support.
    # Preserve the diagnostic/experimental views without presenting them as peers of
    # the decision sheet. The optional 3D view reuses the active plan rather
    # than solving a second hydraulic scenario.
    (tab_decision, tab_map, tab_hydraulic, tab_filtration, tab_scenarios,
     tab_equipment, tab_references) = st.tabs(
        ["Decisión", "Plano y recorrido 2D/3D", "Hidráulica Riverflow",
         "Filtración", "Comparar escenarios", "Equipos e instalación",
         "Fuentes y límites"])
    with tab_decision:
        decision_content = st.container()
        tab_explain = st.expander("Cómo interpretar los resultados", expanded=False)
    tab_decision = decision_content
    with tab_map:
        map_content = st.container()
        tab_fast = st.expander("Recorrido animado · ilustrativo", expanded=False)
    tab_map = map_content
    with tab_hydraulic:
        hydraulic_content = st.container()
        with st.expander("Laboratorio 2D · pruebas no aptas para compra", expanded=False):
            tab_momentum, tab_cfd = st.tabs(
                ["Sensibilidad del 2 %", "Simulación experimental"])
    tab_hydraulic = hydraulic_content
    with tab_filtration:
        tab_guided = st.container()
        tab_treatment = st.expander("Comprobaciones avanzadas de tratamiento", expanded=False)
    with tab_equipment:
        equipment_content = st.container()
        tab_plans = st.expander("Planos y detalles de instalación", expanded=False)
    tab_equipment = equipment_content

    with tab_map:
        st.info(f"Circulación antihoraria. La progresiva 0/{model.geometry.channel_length_m:.0f} m "
                "marca el inicio y fin de la vuelta "
                "en la sección más ancha de la playa principal; el DXF no se modifica. "
                "Las posiciones editables aumentan desde esa playa. Las posiciones manuales "
                "de la sesión anterior se convierten para conservar su lugar físico.")
        if beach_geometry is not None:
            st.subheader("Cotas proporcionales · playa principal")
            first_m = beach_geometry.beach_max_extra_width_m * beach_first_share / 100
            ramp_m = beach_geometry.beach_max_extra_width_m - first_m
            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Canal de referencia", f"{beach_geometry.channel_reference_width_m:.1f} m")
            b2.metric("Tramo plano a profundidad de canal", f"{first_m:.1f} m · 0 %")
            b3.metric("Rampa dibujada en DXF", f"{ramp_m:.1f} m · {beach_geometry.ramp_slope:.1%}")
            b4.metric("Profundidad al borde DXF", f"{beach_geometry.beach_end_depth_at_widest_m:.2f} m")
            section_depths = [depth_m,
                              max(0.0, depth_m - beach_geometry.first_slope * first_m),
                              beach_geometry.beach_end_depth_at_widest_m]
            section_plot = go.Figure()
            section_plot.add_trace(go.Scatter(
                x=[0, first_m, first_m + ramp_m],
                y=[-d for d in section_depths], mode="lines+markers",
                name="Fondo propuesto", line=dict(color="#2563eb", width=3)))
            section_plot.add_hline(y=0, line_dash="dash", line_color="#64748b",
                                   annotation_text="Nivel normal del agua ±0,00 m")
            section_plot.update_layout(
                height=245, margin=dict(l=25, r=20, t=18, b=25),
                xaxis_title="Distancia desde el canal hacia la playa (m)",
                yaxis_title="Cota relativa del fondo (m)", showlegend=False)
            st.plotly_chart(section_plot, width="stretch")
            beach_range = (f"{beach_geometry.beach_start_m:.0f}–"
                           f"{model.geometry.channel_length_m:.0f} m y "
                           f"0–{beach_geometry.beach_end_m:.0f} m, a ambos lados del inicio/fin"
                           if beach_geometry.beach_start_m > beach_geometry.beach_end_m else
                           f"{beach_geometry.beach_start_m:.0f}–"
                           f"{beach_geometry.beach_end_m:.0f} m")
            st.caption(f"Playa principal: progresivas {beach_range}. "
                       "El DXF solo tiene los dos contornos de pared: se supone una playa en una margen y "
                       "se reparte el ancho adicional según la proporción elegida. Las otras zonas anchas "
                       "permanecen como bahías calmas, no como salidas a la arena.")
            if not beach_geometry.profile_fits_slope_limit:
                st.warning("Este perfil NO alcanza arena seca dentro del contorno DXF. "
                           f"Quedan {beach_geometry.beach_end_depth_at_widest_m:.2f} m de agua "
                           "en la sección más ancha. Hace falta definir más ancho de playa o "
                           "revisar pendiente/cotas; el modelo no inventa una salida seca.")
            uniform_volume = sum(
                (float(b["chainage_m"]) - float(a["chainage_m"])) *
                (float(a["width_m"]) + float(b["width_m"])) * depth_m / 2
                for a, b in zip(model.stations[:-1], model.stations[1:]))
            st.caption(f"Volumen a profundidad uniforme: {uniform_volume:,.0f} m³; "
                       f"con perfil de playa: {plan.volume_m3:,.0f} m³. Esta diferencia se transmite "
                       "a la velocidad media, vuelta y filtración; no sustituye cotas topográficas.")
        show_installation = st.checkbox("Mostrar montaje conceptual: bomba, tomas y descarga", value=True)
        show_heatmap = st.checkbox("Colorear campo 2D preliminar de velocidad", value=True)
        show_section_audit = st.checkbox("Auditar secciones perpendiculares del DXF", value=True)
        section_checks = None
        if show_section_audit:
            audit_spacing_m = st.number_input("Intervalo de auditoría de secciones (m)",
                                              1.0, 20.0, 5.0, 1.0,
                                              help="Distancia entre comprobaciones, no ancho del río.")
            section_checks, integrated_area, area_difference = audit_geometry(
                model.stations, model.loader.outer_wall, model.loader.inner_wall,
                model.geometry.scale_m_per_unit, model.geometry.domain_area_m2,
                audit_spacing_m)
        inner_count = plan.module_banks.count("Interior")
        st.info(f"Distribución mostrada: {placement_mode.lower()} · "
                f"{plan.active_modules - inner_count} RF exteriores (rombo naranja) y "
                f"{inner_count} RF interiores (cuadrado morado). "
                "Exterior/interior se refiere al circuito completo; el lado exterior "
                "de cada curva puede ser cualquiera de los dos.")
        if placement_mode != "Automática":
            st.button("Activar propuesta automática de curvas y márgenes",
                      on_click=lambda: st.session_state.update(
                          riverflow_placement_mode="Automática"),
                      help="Conserva tus valores manuales para volver a ellos después.")
        st.plotly_chart(make_map(model, plan, show_installation, show_heatmap, field,
                                 section_checks), width="stretch")
        if section_checks is not None:
            flagged_checks = [check for check in section_checks if check.status != "Consistente"]
            c_a, c_b, c_c = st.columns(3)
            c_a.metric("Área por secciones", f"{integrated_area:,.0f} m²")
            c_b.metric("Área del contorno DXF", f"{model.geometry.domain_area_m2:,.0f} m²")
            c_c.metric("Diferencia de áreas", f"{area_difference:+.1%}" if area_difference is not None else "Dato requerido")
            st.caption(f"Se auditaron {len(section_checks)} secciones cada ~{audit_spacing_m:.0f} m. "
                       f"El plano se escala isotrópicamente a {target_length_m:.0f} m "
                       f"(factor {model.geometry.scale_m_per_unit:.4f}); confirmar unidades del DXF.")
            if flagged_checks:
                st.warning(f"{len(flagged_checks)} secciones requieren revisión. La auditoría "
                           "no cambia los anchos del DXF; el volumen sí incluye el perfil de playa "
                           "supuesto cuando está activado.")
            st.dataframe([{"Progresiva (m)": round(check.chainage_m, 1),
                           "Ancho modelo (m)": round(check.model_width_m, 2),
                           "Ancho perpendicular (m)": (round(check.normal_width_m, 2)
                                                        if check.normal_width_m is not None else None),
                           "Estado": check.status}
                          for check in section_checks], width="stretch", hide_index=True)
        st.caption("Mapa 2D conceptual: azul = menor, rojo = mayor. Conserva el caudal equivalente "
                   "en cada sección y muestra gradientes laterales hipotéticos por márgenes y descargas. "
                   "Usa profundidad media por sección: no muestra la pendiente lateral real de playa. "
                   "No resuelve turbulencia, remolinos reales ni velocidades de seguridad; NO es CFD validado.")
        st.caption("Rombo naranja: RF en margen exterior; cuadrado morado: RF en margen interior. "
                   "Azul: dos tomas de succión. Verde: "
                   "descarga y dirección tentativa. Las conexiones son símbolos esquemáticos; "
                   "no representan cotas, diámetros, orientación definitiva ni alcance hidráulico. "
                   "La orientación y la eficacia local siguen siendo supuestos para comparar escenarios.")
        fm1, fm2, fm3 = st.columns(3)
        fm1.metric("Campo 2D · mín–máx", f"{np.min(field.speed_m_s):.3f}–{np.max(field.speed_m_s):.3f} m/s")
        fm2.metric("Vuelta carril central 2D", f"{field.lane_lap_min[1]:.1f} min")
        fm3.metric("Residuo numérico de caudal", f"{field.volume_residual_fraction:.2%}")
        st.metric("Longitud del circuito", f"{plan.length_m:.0f} m")
        z1, z2 = st.columns(2)
        z1.metric("Canal de corriente", f"{plan.current_zone_length_m:.0f} m")
        z2.metric("Bahías y zonas calmas", f"{plan.calm_zone_length_m:.0f} m")
        st.metric("Mayor distancia de canal a una unidad", f"{plan.max_current_distance_to_module_m:.0f} m",
                  help="Distancia más larga, medida sobre el recorrido cerrado, desde una sección de corriente hasta la unidad activa más cercana. Cambia al mover unidades; no equivale a alcance hidráulico de la descarga.")
        with st.expander("Comparar ubicación de bombas · fricción y continuidad", expanded=False):
            st.caption("Se compara la disposición activa con una propuesta que reparte la "
                       "resistencia Manning y limita tramos largos sin impulsión. "
                       "Las estaciones propuestas permanecen fuera de las zonas anchas de playa. "
                       "Esto es un indicador geométrico, NO un alcance certificado del chorro.")
            evaluation_width = st.number_input(
                "Ancho máximo para evaluar 0,25–0,30 m/s (m)", 4.0,
                float(calm_width_m), min(8.0, float(calm_width_m)), 0.5,
                help="Se evalúa Q/A promedio en los tramos hasta este ancho. "
                     "La playa ancha tiene una meta menor, pero no corriente cero.")
            try:
                speed_band = assess_speed_band(
                    [float(station["chainage_m"]) for station in model.stations],
                    plan.station_areas_m2,
                    [float(station["width_m"]) for station in model.stations],
                    plan.equivalent_channel_flow_m3_h,
                    narrow_width_m=evaluation_width, speed_min_m_s=.25, speed_max_m_s=.30)
            except ValueError:
                st.info("No hay tramos suficientemente angostos con este límite de ancho; "
                        "auméntelo para evaluar la banda de velocidad.")
            else:
                band_left, band_right = st.columns(2)
                band_left.metric("Longitud en banda · Q/A",
                                 f"{speed_band.current_coverage_fraction:.0%}")
                band_right.metric("Toda la banda alcanzable con un solo Q",
                                  "Sí" if speed_band.all_sections_feasible else "No")
                if not speed_band.all_sections_feasible:
                    st.warning("Con las áreas actuales del DXF, ningún caudal longitudinal único "
                               "mantiene todas estas secciones entre 0,25 y 0,30 m/s. "
                               "Reubicar bombas por sí solo no corrige esta diferencia de áreas; "
                               "hay que aceptar bandas por zona o revisar la geometría/cotas.")
            try:
                cumulative_resistance = cumulative_manning_resistance(
                    model.stations, plan.station_areas_m2, perimeters,
                    plan.station_manning_n)
                if not np.isclose(cumulative_resistance[-1],
                                  plan.channel_resistance_s2_m5, rtol=1e-10):
                    raise ValueError("La resistencia integrada no coincide con el modelo base.")
                suggested_positions = suggest_friction_balanced_positions(
                    model.stations, cumulative_resistance, plan.station_zones,
                    plan.active_modules)
                bends = curve_candidates(model.stations, plan.station_zones,
                                         model.geometry.scale_m_per_unit)
                curve_positions, curve_banks = suggest_curve_aware_positions(
                    model.stations, cumulative_resistance, plan.station_zones,
                    plan.active_modules, bends)
                active_gaps = placement_gaps(
                    model.stations, cumulative_resistance,
                    tuple(position % plan.length_m for position in plan.module_chainages_m))
                suggested_gaps = placement_gaps(
                    model.stations, cumulative_resistance, suggested_positions)
                curve_gaps = placement_gaps(
                    model.stations, cumulative_resistance, curve_positions)
            except ValueError as exc:
                st.warning(f"No se pudo comparar la distribución de unidades: {exc}")
            else:
                st.dataframe([
                    {"Distribución": "Activa", "Mayor separación (m)": round(active_gaps.max_gap_m, 1),
                     "Mayor carga entre unidades (%)": round(active_gaps.max_friction_share * 100, 1),
                     "Desequilibrio de carga (× ideal)": round(active_gaps.friction_imbalance, 2)},
                    {"Distribución": "Propuesta · fricción + distancia",
                     "Mayor separación (m)": round(suggested_gaps.max_gap_m, 1),
                     "Mayor carga entre unidades (%)": round(suggested_gaps.max_friction_share * 100, 1),
                     "Desequilibrio de carga (× ideal)": round(suggested_gaps.friction_imbalance, 2)},
                    {"Distribución": "Propuesta · fricción + curvas",
                     "Mayor separación (m)": round(curve_gaps.max_gap_m, 1),
                     "Mayor carga entre unidades (%)": round(curve_gaps.max_friction_share * 100, 1),
                     "Desequilibrio de carga (× ideal)": round(curve_gaps.friction_imbalance, 2)},
                ], width="stretch", hide_index=True)
                st.caption("La carga es la fracción de la resistencia total de Manning entre "
                           "unidades sucesivas. 1× sería un reparto perfecto de esa carga; "
                           "no significa velocidad uniforme ni ausencia de remolinos. "
                           f"El tramo de mayor carga propuesto va de {suggested_gaps.gap_start_m:.0f} "
                           f"a {suggested_gaps.gap_end_m:.0f} m en el circuito cerrado.")
                st.code(", ".join(f"{position:.1f}" for position in suggested_positions),
                        language=None)
                if bends:
                    st.markdown("**Curvas a revisar · margen exterior de cada giro**")
                    st.dataframe([
                        {"Curva (m)": round(b.apex_m), "Giro en 20 m (°)": round(b.turn_deg, 1),
                         "Ancho DXF (m)": round(b.width_m, 1),
                         "Margen exterior del giro": b.preferred_bank,
                         "Punto previo candidato (m)": round(b.candidate_m, 1),
                         "RF activa más próxima (m)": round(min(
                             plan.module_chainages_m,
                             key=lambda p: min(abs(p-b.candidate_m),
                                               plan.length_m-abs(p-b.candidate_m))), 1)}
                        for b in bends], width="stretch", hide_index=True)
                    st.caption("Giro medido con ventanas de 10 m a cada lado, usando el DXF escalado. "
                               "Posición y margen son candidatos geométricos: no verifican que la "
                               "succión, descarga, acceso o velocidad de pared sean seguros.")

                def apply_position_proposal():
                    st.session_state["riverflow_placement_mode"] = "Editar por recorrido (m)"
                    st.session_state[f"riverflow_positions_beach_{active_modules}"] = ", ".join(
                        f"{position:.3f}" for position in suggested_positions)

                st.button("Usar estas posiciones en el escenario local",
                          on_click=apply_position_proposal,
                          help="Cambia solo las progresivas editables. Puede volver a Automática "
                               "o introducir sus propias posiciones en la barra lateral.")
                def apply_curve_proposal():
                    st.session_state["riverflow_placement_mode"] = "Editar por recorrido (m)"
                    st.session_state[f"riverflow_positions_beach_{active_modules}"] = ", ".join(
                        f"{p:.3f}" for p in curve_positions)
                    st.session_state[f"riverflow_banks_{active_modules}"] = ", ".join(
                        "E" if b == "Exterior" else "I" for b in curve_banks)

                st.button("Probar posiciones y márgenes de curvas en escenario local",
                          on_click=apply_curve_proposal,
                          help="Propuesta geométrica editable; no es plano de instalación.")
                if st.checkbox("Comparar mapas de velocidad lateral · exploratorio",
                               value=False, key="rf_compare_placement_maps"):
                    # Hold the same through-flow to isolate position effects.
                    # In a closed channel a relocation alone cannot create Q.
                    suggested_plan = replace(plan, module_chainages_m=suggested_positions)
                    suggested_field = compute_field_2d(
                        model.stations, suggested_plan, depth_m,
                        scale_m_per_unit=model.geometry.scale_m_per_unit)
                    curve_plan = replace(plan, module_chainages_m=curve_positions,
                                         module_banks=curve_banks)
                    curve_field = compute_field_2d(
                        model.stations, curve_plan, depth_m,
                        scale_m_per_unit=model.geometry.scale_m_per_unit)
                    common_range = (float(min(np.min(field.speed_m_s),
                                              np.min(suggested_field.speed_m_s),
                                              np.min(curve_field.speed_m_s))),
                                    float(max(np.max(field.speed_m_s),
                                              np.max(suggested_field.speed_m_s),
                                              np.max(curve_field.speed_m_s))))
                    current_map, proposed_map, bend_map = st.tabs(
                        ["Activa", "Fricción + distancia", "Fricción + curvas"])
                    with current_map:
                        st.plotly_chart(make_map(model, plan, True, True, field,
                                                 color_range=common_range), width="stretch",
                                        key="rf_placement_active_map")
                    with proposed_map:
                        st.plotly_chart(make_map(model, suggested_plan, True, True,
                                                 suggested_field, color_range=common_range),
                                        width="stretch", key="rf_placement_suggested_map")
                    with bend_map:
                        st.plotly_chart(make_map(model, curve_plan, True, True,
                                                 curve_field, color_range=common_range),
                                        width="stretch", key="rf_placement_curve_map")

                    def narrow_center_coverage(scenario_field):
                        ds = np.diff(scenario_field.chainages_m)
                        narrow = scenario_field.widths_m[:-1] <= evaluation_width
                        center = scenario_field.longitudinal_m_s[:,
                                                                 len(scenario_field.lateral_fraction) // 2]
                        segment_speed = (center[:-1] + center[1:]) / 2
                        return (float(np.sum(ds[narrow & (segment_speed >= .25) &
                                                (segment_speed <= .30)]) / np.sum(ds[narrow]))
                                if np.any(narrow) else None)

                    def coverage_text(scenario_field):
                        fraction = narrow_center_coverage(scenario_field)
                        return round(100 * fraction, 1) if fraction is not None else "Sin tramos"

                    st.dataframe([
                        {"Distribución": "Activa",
                         "Canal dentro de 0,25–0,30 m/s · carril central (%)":
                             coverage_text(field),
                         "Vuelta del carril más lento (min)": round(max(field.lane_lap_min), 1)},
                        {"Distribución": "Propuesta",
                         "Canal dentro de 0,25–0,30 m/s · carril central (%)":
                             coverage_text(suggested_field),
                         "Vuelta del carril más lento (min)":
                             round(max(suggested_field.lane_lap_min), 1)},
                        {"Distribución": "Curvas",
                         "Canal dentro de 0,25–0,30 m/s · carril central (%)":
                             coverage_text(curve_field),
                         "Vuelta del carril más lento (min)":
                             round(max(curve_field.lane_lap_min), 1)},
                    ], width="stretch", hide_index=True)
                    st.warning("El mapa 2D conserva el mismo Q y usa un reparto lateral "
                               "hipotético cerca de cada descarga; estas métricas no validan "
                               "velocidad real, alcance de chorros ni seguridad en playa/curvas.")
        with st.expander("Vista 3D · mismo escenario Riverflow", expanded=False):
            st.caption("Usa el DXF, profundidad, playa, unidades, posiciones, ángulos y "
                       "velocidad seccional Q/A de este escenario. El tiempo del marcador "
                       "coincide con la vuelta volumétrica indicada arriba; la vuelta de "
                       "los carriles 2D puede ser distinta. La superficie y los trazos "
                       "animados son una representación conceptual, no CFD.")
            visual_mode = st.radio(
                "Capa de velocidad 3D",
                ["Campo 2D lateral · prueba", "Q/A uniforme por sección"],
                horizontal=True, key="rf_3d_visual_mode")
            st.caption("La capa lateral proyecta el mapa 2D existente sobre la superficie. "
                       "Sus partículas siguen tres carriles con tiempos distintos. "
                       "No predice chorros reales, remolinos ni seguridad de bañistas.")
            if st.checkbox("Cargar vista 3D interactiva", value=False,
                           key="rf_show_active_3d"):
                from experiments.openfoam_nya_pilot.riverflow_3d_decision_pilot import (
                    geometry_from_active_plan, make_plot, render_animation)
                scene_xy, scene_bed, scene_s, scene_widths, scene_result = (
                    geometry_from_active_plan(
                        model, plan, depth_m, beach_geometry,
                        beach_first_share / 100))
                scene_figure, rider_index, rider_track, streak_index, streak_frames = (
                    make_plot(scene_xy, scene_bed, scene_s, scene_widths,
                              beach_geometry, scene_result, plan.module_chainages_m,
                              [], module_angles_deg=plan.module_angles_deg,
                              module_banks=plan.module_banks,
                              field=(field if visual_mode.startswith("Campo 2D")
                                     else None)))
                st.iframe(render_animation(scene_figure, rider_index, rider_track,
                                           streak_index, streak_frames), height=790)
                st.caption(f"Escenario activo: {plan.active_modules} unidades Riverflow a "
                           f"{speed_pct}% del variador; Q longitudinal equivalente "
                           f"{plan.equivalent_channel_flow_m3_h:,.0f} m³/h; "
                           f"vuelta volumétrica {plan.estimated_lap_min:.1f} min. "
                           "El color representa el campo 2D proyectado o Q/A por sección, "
                           "según la capa elegida; no predice remolinos "
                           "ni velocidad junto a tomas y boquillas.")

    with tab_explain:
        st.subheader("Cómo leer este escenario")
        st.markdown(
            f"1. **Plano y agua:** el DXF fija el recorrido antihorario de {plan.length_m:.0f} m "
            f"y los anchos variables. Con {depth_m:.2f} m en el canal "
            f"{'y una playa principal de profundidad variable' if beach_geometry else 'y profundidad uniforme'}, "
            f"el volumen aproximado "
            f"es {plan.volume_m3:,.0f} m³.\n"
            f"2. **Cada bomba:** {hydraulic_source if use_local_circuit else 'TDH manual'} "
            f"aporta {plan.module_flow_full_speed_m3_h:,.0f} m³/h por unidad "
            f"a {local_head_ft:.1f} ft de TDH local equivalente a plena velocidad.\n"
            f"3. **Movimiento del río:** {active_modules} unidades dan "
            f"{plan.installed_operating_flow_m3_h:,.0f} m³/h de descarga local estimada; "
            f"con {transfer_pct:.1f}% de energía hidráulica útil supuesta, un factor de "
            f"ubicación/orientación de {plan.placement_effectiveness:.0%} y la resistencia "
            f"Manning del DXF, la corriente longitudinal del escenario es "
            f"{plan.equivalent_channel_flow_m3_h:,.0f} m³/h.\n"
            f"4. **Tiempo de vuelta:** volumen ÷ circulación equivalente = "
            f"{plan.estimated_lap_min:.1f} minutos, frente a la meta de "
            f"{target_lap_min:.1f} minutos.\n"
            f"5. **Resistencia:** piso n={floor_n:.3f}; paredes n={wall_n_current:.3f} "
            f"en corriente y {wall_n_calm:.3f} en playa. El n compuesto cambia con el ancho "
            f"del DXF y produce {plan.channel_friction_head_m:.3f} m de pérdida calculada "
            "para el canal. Mayor rugosidad aumenta esa resistencia, baja la corriente y "
            "prolonga la vuelta; no es la TDH del circuito local de las bombas."
        )
        st.info("La simulación es un escenario de fase 1, no una predicción validada de velocidad "
                "del agua ni una certificación de seguridad. El 2% inicial de energía útil se eligió "
                "para explorar sensibilidad, NO proviene de Riverflow ni de mediciones NYA. "
                "Se usa una escala energética fija de 4 ft, mientras la TDH local seleccionada "
                "solo determina el caudal de la curva. El balance incluye fricción Manning; "
                "otras pérdidas se concentran en la fracción desconocida. Se necesitan "
                "mediciones o CFD para calibrarla.")
        st.info("**Comprobación nueva de siete puertos:** la ficha Brannon indica "
                "0,2892 ft² de área abierta. La app usa Q/área para la velocidad de salida "
                "y, si se elige, sustituye el K manual por uno equivalente con Cd editable. "
                "Cd no está medido. En Hidráulica se compara además un balance de impulso "
                "independiente; no reemplaza la vuelta ni el mapa principales porque la "
                "transferencia real del chorro al río sigue desconocida.")
        st.markdown("**Base disponible:** DXF, plano de montaje y curva H–Q en imagen. "
                    "La app explora supuestos editables sin pedir nuevas fichas a proveedores. "
                    "Para construcción siguen sin conocerse las cotas exactas, pérdidas de "
                    "succión/descarga, desempeño a velocidades parciales, acoplamiento real de "
                    "los jets y diseño sanitario definitivo.")

    with tab_hydraulic:
        st.subheader("Fricción del canal · Manning")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("n compuesto local mín–máx", f"{min(plan.station_manning_n):.3f}–{max(plan.station_manning_n):.3f}",
                  help="Piso inclinado y paredes ponderados por perímetro mojado cuando el perfil está activo.")
        m2.metric("Pérdida canal · escenario", f"{plan.channel_friction_head_m:.3f} m")
        m3.metric("Pérdida canal · meta", f"{plan.target_channel_friction_head_m:.3f} m")
        m4.metric("Froude equivalente máx.", f"{plan.max_froude:.2f}")
        st.plotly_chart(make_friction_profile(model, plan), width="stretch")
        st.caption("Se calcula la pendiente de fricción de Manning en cada tramo del DXF con "
                   "área y perímetro mojados, piso liso y paredes con el acabado propuesto. El n "
                   "compuesto se pondera por perímetro mojado según HEC-RAS. El balance "
                   "Pútil = ρg·Qcorriente·Hfricción vincula n, caudal y vuelta. Es una "
                   "sensibilidad condicionada al porcentaje de energía útil, no una solución "
                   "validada de las bombas ni del campo de velocidades.")
        st.markdown("[Base técnica del n compuesto (HEC-RAS)](https://www.hec.usace.army.mil/confluence/rasdocs/ras1dtechref/6.4/theoretical-basis-for-one-dimensional-and-two-dimensional-hydrodynamic-calculations/1d-steady-flow-water-surface-profiles/composite-manning-s-n-for-the-main-channel)")
        st.subheader("Circuito hidráulico local · por unidad Riverflow")
        if local_points is not None:
            st.dataframe([
                {"Unidad": f"RF-{i:02d}", "Q local (m³/h)": round(point.flow_m3_h, 1),
                 "TDH (ft)": round(point.system_head_ft, 2),
                 "V succión (m/s)": round(point.suction_velocity_m_s, 2),
                 "V descarga (m/s)": round(point.discharge_velocity_m_s, 2)}
                for i, point in enumerate(local_points, 1)
            ], width="stretch", hide_index=True)
            st.warning("Cada punto cruza la misma curva de bomba con un circuito local editable. "
                       "Las longitudes, diámetros y K aún no están medidos para NYA; "
                       "el 2 % de energía transferida al río continúa siendo una hipótesis común.")
        elif local_point is not None:
            lc1, lc2, lc3, lc4 = st.columns(4)
            lc1.metric("Punto de operación · hipótesis", f"{local_point.flow_m3_h:,.0f} m³/h")
            lc2.metric("TDH local calculada", f"{local_point.system_head_ft:.2f} ft")
            lc3.metric("Velocidad en succión", f"{local_point.suction_velocity_m_s:.2f} m/s")
            lc4.metric("Velocidad en descarga", f"{local_point.discharge_velocity_m_s:.2f} m/s")
            st.dataframe([
                {"Pérdida por unidad": "Tubería de succión", "m": local_point.suction_friction_m},
                {"Pérdida por unidad": "Tubería de descarga", "m": local_point.discharge_friction_m},
                {"Pérdida por unidad": "Tomas y accesorios · K supuesto", "m": local_point.fittings_m},
                {"Pérdida por unidad": "Salida/acelerador · " +
                 ("área documentada + Cd supuesto" if nozzle_cd is not None else "K manual supuesto"),
                 "m": local_point.outlet_m},
                {"Pérdida por unidad": "Desnivel neto supuesto", "m": circuit.static_head_m},
            ], width="stretch", hide_index=True)
            circuit_fig = go.Figure()
            speed_fraction = speed_pct / 100
            sampled_heads = [4 + i * 0.1 for i in range(61)]
            curve_q = [riverflow_flow_at_head_ft(h, curve_mode) * speed_fraction
                       for h in sampled_heads]
            circuit_fig.add_trace(go.Scatter(x=curve_q,
                y=[h * speed_fraction ** 2 for h in sampled_heads],
                mode="lines", name="Bomba · curva a variador supuesto"))
            circuit_fig.add_trace(go.Scatter(x=sorted(curve_q),
                y=[circuit_head(q, circuit).system_head_ft for q in sorted(curve_q)],
                mode="lines", name="Circuito local · datos editables"))
            circuit_fig.add_trace(go.Scatter(x=[local_point.flow_m3_h],
                y=[local_point.pump_head_ft], mode="markers", name="Intersección",
                marker=dict(size=12, color="#ea580c")))
            circuit_fig.update_layout(height=320, margin=dict(l=20, r=20, t=30, b=30),
                                      xaxis_title="Caudal por unidad (m³/h)",
                                      yaxis_title="Carga local (ft)")
            st.plotly_chart(circuit_fig, width="stretch")
            st.warning("Intersección calculada solo para el circuito SUPUESTO. Para 7 puertos, "
                       "el área abierta documentada cambia el K equivalente y el caudal, pero "
                       "Cd, K de tomas/accesorios, diámetro y trazado NYA no están medidos. "
                       "Para 3 puertos se conserva un K manual porque falta su área/curva. "
                       "A velocidad parcial se aplican leyes de afinidad aproximadas. "
                       "No verifica cavitación, potencia eléctrica ni seguridad de rejillas.")
            st.caption("El plano de referencia Riverflow muestra dos tomas y tubería nominal "
                       "de 12 pulgadas; no es un plano de NYA. Método de pérdidas: Darcy–Weisbach "
                       "para tramos y K·v²/(2g) para pérdidas concentradas. "
                       "[Plano de referencia Riverflow](https://riverflowpumps.com/wp-content/uploads/LAZY%20RIVER%207-PORT%20NOZZLE%20PLUMBING%20DRAWINGS/LAZY-RIVER-3-FT-DEPTH-7PN-DOUBLE-SUCTION-.pdf) · "
                       "[Referencia DOE sobre pérdidas en tuberías](https://www.energy.gov/sites/prod/files/2014/05/f16/pump.pdf)")
        elif reference_point is not None:
            rc1, rc2, rc3 = st.columns(3)
            rc1.metric("Caudal de referencia por unidad", f"{reference_point.flow_m3_h:,.0f} m³/h")
            rc2.metric("TDH de referencia", f"{reference_point.system_head_ft:.2f} ft")
            rc3.metric("Velocidad en acelerador 7 puertos", f"{reference_point.exit_velocity_m_s:.2f} m/s")
            st.info(f"**{selected_reference.label}** · {selected_reference.source}. "
                    "Punto aproximado de un circuito de ejemplo con doble succión y "
                    "acelerador 12 × 7; no son pérdidas medidas en NYA. "
                    "La velocidad de salida de la boquilla no es la velocidad del río.")
            if speed_pct < 100:
                st.warning("A menos de 100 % del variador, Q ∝ velocidad y TDH ∝ velocidad² "
                           "son extrapolaciones por afinidad del punto documentado; "
                           "Riverflow no proporcionó curvas para esa velocidad.")
            reference_curve = go.Figure()
            speed_fraction = speed_pct / 100
            sampled_heads = [4 + i * 0.1 for i in range(61)]
            reference_curve.add_trace(go.Scatter(
                x=[riverflow_flow_at_head_ft(h, curve_mode) * speed_fraction
                   for h in sampled_heads],
                y=[h * speed_fraction ** 2 for h in sampled_heads],
                mode="lines", name="Curva de bomba · aproximada"))
            max_flow = max(riverflow_flow_at_head_ft(4, curve_mode) * speed_fraction,
                           reference_point.flow_m3_h) * 1.08
            sampled_flows = np.linspace(0, max_flow, 80)
            reference_curve.add_trace(go.Scatter(
                x=sampled_flows,
                y=[reference_point.system_head_ft * (q / reference_point.flow_m3_h) ** 2
                   for q in sampled_flows],
                mode="lines", name="Curva del circuito de referencia · Q²"))
            reference_curve.add_trace(go.Scatter(
                x=[reference_point.flow_m3_h], y=[reference_point.system_head_ft],
                mode="markers", name="Punto informado",
                marker=dict(size=12, color="#ea580c")))
            reference_curve.update_layout(height=320, margin=dict(l=20, r=20, t=30, b=30),
                                          xaxis_title="Caudal por unidad (m³/h)",
                                          yaxis_title="Carga local (ft)")
            st.plotly_chart(reference_curve, width="stretch")
            st.caption("La parábola pasa por el punto informado y supone pérdidas ∝ Q². "
                       "No desglosa tomas, accesorios ni boquilla y no sustituye el "
                       "circuito editable de NYA. El 2 % de energía útil sigue sin medirse.")
        else:
            st.info("Circuito local desactivado: la TDH manual se usa para interpolar el caudal "
                    "en la curva y todas las salidas continúan enlazadas a ese caudal.")
        st.subheader("Boquilla de 7 puertos · comprobación independiente de impulso")
        if nozzle_type == "7 puertos":
            st.caption("Del documento RiverFlow Flow Rates: área abierta 0,2892 ft². "
                       "La velocidad de salida se calcula como Q de cada bomba / área; "
                       "NO es la velocidad del río. El impulso bruto es ρ·Q·v con orientación "
                       "de la descarga. Manning representa el arrastre del canal.")
            jet_transfer_pct = st.slider(
                "Fracción de impulso que mueve el río (%) · hipótesis NO medida",
                1, 100, 10, 1, key="rf_jet_transfer_pct",
                help="Incluye mezcla, succión cercana, paredes y curvas. Es distinta del "
                     "porcentaje de energía útil del escenario principal; no se pueden igualar.")
            jet_result = solve_jet_momentum(
                model.stations, plan, perimeters,
                transfer_fraction=jet_transfer_pct / 100)
            j1, j2, j3, j4 = st.columns(4)
            j1.metric("Área abierta documentada", f"{NOZZLE_12X7_OPEN_AREA_M2:.5f} m²")
            j2.metric("V salida por unidad", f"{min(jet_result.per_unit_exit_speed_m_s):.2f}–"
                      f"{max(jet_result.per_unit_exit_speed_m_s):.2f} m/s")
            j3.metric("Vuelta · ensayo de impulso", f"{jet_result.lap_min:.1f} min")
            j4.metric("Impulso requerido para meta",
                      f"{jet_result.target_required_transfer_fraction:.0%}")
            max_unit_flow = max(jet_result.per_unit_flow_m3_h)
            st.caption(f"Dos tomas RFS 200 por unidad: con reparto igual, "
                       f"≈{max_unit_flow / 2:,.0f} m³/h por rejilla; con una toma "
                       f"obstruida, hasta ≈{max_unit_flow:,.0f} m³/h por la restante, "
                       f"frente a {RFS_200_MAX_CERTIFIED_M3_H:,.0f} m³/h de capacidad "
                       "certificada por salida. Es solo comprobación de caudal nominal: "
                       "no demuestra seguridad contra atrapamiento ni pérdidas de cada ramal.")
            if max_unit_flow > RFS_200_MAX_CERTIFIED_M3_H:
                st.error("El caudal por una toma ante obstrucción superaría la capacidad "
                         "publicada de la RFS 200; este escenario requiere rediseño.")
            st.dataframe([
                {"Cálculo": "Escenario principal · balance de energía no calibrado",
                 "Caudal longitudinal (m³/h)": round(plan.equivalent_channel_flow_m3_h),
                 "Tiempo de vuelta (min)": round(plan.estimated_lap_min, 1),
                 "Parámetro desconocido": f"{transfer_pct:.1f}% energía útil"},
                {"Cálculo": "Comprobación · balance de impulso no calibrado",
                 "Caudal longitudinal (m³/h)": round(jet_result.channel_flow_m3_h),
                 "Tiempo de vuelta (min)": round(jet_result.lap_min, 1),
                 "Parámetro desconocido": f"{jet_transfer_pct}% impulso transferido"},
            ], width="stretch", hide_index=True)
            if jet_result.target_required_transfer_fraction > 1:
                st.error("La meta requeriría más del 100 % del impulso bruto calculado "
                         "en este ensayo; revise escenario, geometría y cantidad de bombas.")
            st.warning("Los porcentajes de energía e impulso describen mecanismos distintos; "
                       "ninguno está medido en NYA. Este ensayo NO modifica el mapa, el 3D "
                       "ni la cantidad sugerida por el modelo principal. Que ambos tiempos "
                       "coincidan no valida ninguno. Mover una bomba solo cambia la orientación "
                       "en este balance global: la ventaja de una posición exige CFD o ensayo físico.")
        else:
            st.info("No se calcula velocidad de salida ni impulso para el manifold de 3 puertos: "
                    "no se entregó su área abierta ni su curva de pérdidas. El K manual solo "
                    "permite comparar un circuito hipotético.")
        st.markdown("**Comparación local · misma geometría NYA y misma hipótesis de energía útil**")
        comparison_rows = []
        try:
            editable_point = solve_local_circuit(circuit, speed_fraction=speed_pct / 100,
                                                 curve_mode=curve_mode)
            comparison_points = [("NYA · circuito editable", editable_point)]
        except ValueError:
            comparison_points = []
        comparison_points.extend((reference.label,
                                  reference_operating_point(reference, speed_pct / 100))
                                 for reference in LAZY_RIVER_REFERENCES)
        for label, point in comparison_points:
            flow = scenario_channel_flow_m3_h(
                plan.channel_resistance_s2_m5,
                point.flow_m3_h / (speed_pct / 100), plan.active_modules,
                plan.speed_fraction, plan.transfer_fraction,
                plan.placement_effectiveness)
            comparison_rows.append({
                "Fuente": label,
                "Q local por unidad (m³/h)": round(point.flow_m3_h, 1),
                "TDH local (ft)": round(point.system_head_ft, 2),
                "Q longitudinal supuesto (m³/h)": round(flow),
                "Vuelta media supuesta (min)": round(plan.volume_m3 * 60 / flow, 1),
                "Q filtros (m³/h)": round(plan.filtration_flow_m3_h),
            })
        st.dataframe(comparison_rows, width="stretch", hide_index=True)
        st.caption("Cambiar la fuente altera propulsión, velocidades y vuelta en el escenario "
                   "activo; la filtración depende del volumen y las horas de recirculación, "
                   "no de la descarga local Riverflow. Los ejemplos Sch 40/80 no son NYA.")
        q1, q2 = st.columns(2)
        q1.metric("Tiempo en canal de corriente", f"{plan.current_lap_min:.1f} min")
        q2.metric("Tiempo en zonas calmas", f"{plan.calm_lap_min:.1f} min")
        st.caption("La suma coincide con la vuelta estimada; ambas partes se recalculan con el ancho DXF, "
                   "la profundidad, Manning, las unidades activas y la energía útil supuesta.")
        curve_heads = [4.0 + i * 0.1 for i in range(61)]
        curve = go.Figure()
        curve.add_trace(go.Scatter(x=[riverflow_flow_at_head_ft(h, "photo") for h in curve_heads],
                                   y=curve_heads, mode="lines", name="Imagen · lectura aproximada",
                                   line=dict(color="#2563eb", width=3)))
        curve.add_trace(go.Scatter(x=[riverflow_flow_at_head_ft(h, "anchors") for h in curve_heads],
                                   y=curve_heads, mode="lines", name="Dos anclas · recta",
                                   line=dict(color="#94a3b8", width=2, dash="dash")))
        curve.add_trace(go.Scatter(
            x=[gpm * US_GPM_TO_M3_H for _, gpm in RIVERFLOW_DIGITIZED_POINTS],
            y=[head for head, _ in RIVERFLOW_DIGITIZED_POINTS], mode="markers",
            name="Puntos leídos", marker=dict(size=6, color="#2563eb")))
        curve.add_trace(go.Scatter(x=[plan.module_flow_full_speed_m3_h], y=[local_head_ft],
                                   mode="markers", name="Escenario seleccionado",
                                   marker=dict(size=12, color="#ea580c")))
        curve.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=25),
                            xaxis_title="Caudal por unidad a plena velocidad (m³/h)",
                            yaxis_title="TDH local estimada (ft)")
        st.plotly_chart(curve, width="stretch")
        st.caption("Curva recibida: 2,440 US GPM a 4 ft y 1,220 US GPM a 10 ft son "
                   "puntos rotulados. Los puntos intermedios se estimaron visualmente del JPG, "
                   "no de una tabla certificada; se puede comparar con la recta entre anclas. "
                   "Fuera de 4–10 ft no se extrapola. "
                   "El punto de operación real requiere cruzar la curva de la bomba con la curva del circuito local.")
        st.plotly_chart(make_profile(model, plan), width="stretch")
        h1, h2, h3 = st.columns(3)
        h1.metric("V equivalente en canal de corriente", f"{plan.current_velocity_min_m_s:.3f}–{plan.current_velocity_max_m_s:.3f} m/s")
        h2.metric("V equivalente en todo el recorrido", f"{plan.velocity_min_m_s:.3f}–{plan.velocity_max_m_s:.3f} m/s")
        h3.metric("V equivalente Q/A medio", f"{plan.velocity_equivalent_m_s:.3f} m/s")
        st.caption("Velocidad de recorrido = longitud / tiempo volumétrico estimado. Los valores "
                   "Q/A son promedios por sección; el mapa 2D muestra un reparto lateral hipotético "
                   "que conserva ese mismo caudal, no un campo CFD medido.")
        st.markdown("**Tiempos de vuelta por trayectoria 2D conceptual**")
        lane_cols = st.columns(3)
        for col, label, minutes in zip(lane_cols, ("Carril 20%", "Carril central", "Carril 80%"),
                                       field.lane_lap_min):
            col.metric(label, f"{minutes:.1f} min")
        st.caption("Estas trayectorias se integran en el campo 2D y difieren del tiempo volumétrico V/Q. "
                   "La forma lateral y el acoplamiento del jet son hipótesis no calibradas.")
        st.plotly_chart(make_count_chart(plan), width="stretch")
        st.markdown("**Sensibilidad a la energía útil no medida**")
        sensitivity_rows = []
        for percent in (0.5, 1.0, 2.0, 5.0):
            q_scenario = scenario_channel_flow_m3_h(
                plan.channel_resistance_s2_m5, plan.module_flow_full_speed_m3_h,
                plan.active_modules, plan.speed_fraction, percent / 100,
                plan.placement_effectiveness)
            q_one = scenario_channel_flow_m3_h(
                plan.channel_resistance_s2_m5, plan.module_flow_full_speed_m3_h,
                1, plan.speed_fraction, percent / 100,
                plan.placement_effectiveness)
            sensitivity_rows.append({
                "Energía útil supuesta": f"{percent:.1f}%",
                "Vuelta con unidades actuales": f"{plan.volume_m3 * 60 / q_scenario:.1f} min",
                "Unidades para meta · solo aritmética":
                    ceil((plan.target_equivalent_flow_m3_h / q_one) ** 3),
            })
        st.dataframe(sensitivity_rows, width="stretch", hide_index=True)
        st.caption("El 2% inicial NO está medido. Esta amplitud muestra cuánto puede cambiar "
                   "la decisión de equipos antes de conocer la transferencia de energía real; "
                   "las cantidades no son especificaciones de compra.")
        st.markdown(
            f"**Cálculo enlazado:** resistencia Manning K={plan.channel_resistance_s2_m5:.5f} s²/m⁵; "
            f"potencia útil supuesta ≈{plan.useful_drive_power_w:,.0f} W. "
            f"Se resuelve K·Q³ = Pútil/(ρg), dando "
            f"Q longitudinal {plan.equivalent_channel_flow_m3_h:,.1f} m³/h. "
            f"Volumen {plan.volume_m3:,.1f} m³ ÷ Q = {plan.estimated_lap_min:.1f} min/vuelta. "
            "La curva local, el porcentaje de energía y las pérdidas no están calibrados."
        )
        with st.expander("Trazabilidad de datos y límites del cálculo"):
            st.dataframe([
                {"Dato editable": "DXF, longitud y profundidad", "Afecta": "Volumen, áreas, velocidades, vuelta, fricción y filtración",
                 "Estado": "Geometría derivada del plano; escala y profundidad por confirmar"},
                {"Dato editable": "Acabado y Manning de piso/paredes", "Afecta": "resistencia, corriente, velocidad, vuelta y mapa",
                 "Estado": "Acoplamiento energético de escenario, sin calibración NYA"},
                {"Dato editable": "Circuito local o TDH manual", "Afecta": "Q por bomba, Q total, vuelta, velocidades y unidades requeridas",
                 "Estado": "Curva H–Q desde JPG; dimensiones y coeficientes K son hipótesis editables"},
                {"Dato editable": "Variador y energía útil", "Afecta": "Corriente, vuelta, velocidades y fricción",
                 "Estado": "Leyes de afinidad aproximadas; energía útil no medida"},
                {"Dato editable": "Ubicación y orientación de módulos", "Afecta": "Acoplamiento supuesto, corriente, vuelta y campo 2D",
                 "Estado": "Sensibilidad geométrica sin alcance medido de chorros ni calibración lateral"},
                {"Dato editable": "Recambio de filtración", "Afecta": "Caudal de tratamiento separado",
                 "Estado": "No se suma al caudal de propulsión"},
            ], width="stretch", hide_index=True)
        st.warning("La TDH del circuito se calcula con longitudes, diámetros y pérdidas supuestas para NYA; "
                   "en modo manual se ingresa directamente. La curva a velocidad parcial "
                   "se escala por afinidad: no está verificada por el fabricante. "
                   "Para siete puertos se calcula Q/área abierta documentada, pero la "
                   "distribución por puerto y el acoplamiento al río siguen desconocidos. "
                   "Potencia eléctrica y seguridad de tomas requieren validación adicional. "
                   "La placa de 10 HP no es el consumo instantáneo. No seleccionar bombas con "
                   "la cantidad calculada hasta calibrar energía útil y pérdidas de cada instalación.")
        st.markdown("**Ruta interna de mejora:** (1) perfil de playa proporcional al DXF · implementado como hipótesis; "
                    "(2) circuitos locales editables y cruce con la curva H–Q · implementado como escenario no validado; "
                    "(3) matriz de bomba y variador dentro de la curva disponible · implementada "
                    "como sensibilidad, no como curvas RPM medidas; "
                    "(4) refinar este campo 2D y estudiar en CFD 3D solo las zonas críticas; "
                    "(5) mantener filtración, aforo y seguridad como evaluaciones separadas. "
                    "Ninguna de estas simulaciones sustituye la verificación antes de construir.")

    with tab_fast:
        st.subheader("Vuelta conceptual acelerada · sentido antihorario")
        playback = st.select_slider("Velocidad de reproducción", [60, 120, 300, 600], value=300,
                                    format_func=lambda value: f"{value}×",
                                    help="Acelera solo la animación. No cambia RPM, caudal ni tiempo físico de vuelta.")
        p1, p2, p3 = st.columns(3)
        p1.metric("Vuelta carril central · escenario 2D", f"{field.lane_lap_min[1]:.1f} min")
        p2.metric("Reproducción", f"{playback}×")
        p3.metric("Duración de un ciclo en pantalla", f"{field.lane_lap_min[1] * 60 / playback:.1f} s")
        if st.checkbox("Cargar animación rápida del recorrido", value=False,
                       key="rf_load_fast_sim"):
            st.plotly_chart(make_fast_simulation(model, plan, playback, field),
                            width="stretch")
        else:
            st.info("Active la animación cuando quiera verla. Los cálculos y los mapas "
                    "permanecen disponibles sin cargar sus fotogramas en cada cambio.")
        st.caption("Pulsa ▶ en la gráfica. Los puntos ilustran personas que se dejan llevar "
                   "con chaleco salvavidas o barra de espuma; no son flotadores independientes. "
                   "El campo 2D conceptual cambia con ancho, margen y ubicación de módulos. "
                   "No se modelan patadas, braceo, viento, interacción entre personas, "
                   "remolinos ni CFD. La reproducción acelerada no modifica los resultados.")

    with tab_momentum:
        st.subheader("Ensayo 2D de momento longitudinal · separado del diseño base")
        st.warning("Es una prueba de sensibilidad, no CFD ni una predicción calibrada. "
                   "Conserva el caudal longitudinal derivado del 2 % del escenario principal; "
                   "NO verifica ese 2 % ni calcula de nuevo "
                   "el punto de operación, la cantidad de bombas ni velocidades seguras para bañistas.")
        st.caption("Resuelve advección longitudinal, mezcla lateral y arrastre Manning linealizado "
                   "en una malla cerrada. Una corrección de presión por sección conserva Q. "
                   "No resuelve momento lateral, superficie libre, remolinos ni interacción con personas.")
        ma, mb, mc = st.columns(3)
        beach_bank = ma.selectbox("Margen supuesta de la playa", ["Exterior", "Interior"],
                                  help="El DXF contiene paredes, pero no identifica la margen de la rampa sumergida.")
        eddy = mb.slider("Mezcla lateral supuesta (m²/s)", 0.01, 0.40, 0.08, 0.01,
                         help="Viscosidad turbulenta efectiva exploratoria; no medida en NYA.")
        jet_accel = mc.slider("Impulso longitudinal local supuesto (mm/s²)",
                              0.0, 8.0, 2.0, 0.5,
                              help="Sensibilidad de la descarga, no fuerza certificada por Riverflow.")
        spread = st.slider("Longitud de influencia supuesta por unidad (m)", 4, 30, 12, 1)
        run_pilot = st.checkbox("Ejecutar y comparar el ensayo 2D", value=False,
                                key="riverflow_momentum_run")
        refine_grid = st.checkbox("Comprobar estabilidad con una malla más fina", value=False,
                                  help="Repite el ensayo con 128 × 17 celdas; puede tardar unos segundos.",
                                  key="riverflow_momentum_refine")
        if run_pilot:
            try:
                pilot = compute_momentum_pilot(
                    model.stations, plan, depth_m, model.geometry.scale_m_per_unit,
                    beach_geometry=beach_geometry, beach_bank=beach_bank,
                    eddy_viscosity_m2_s=eddy,
                    jet_acceleration_m_s2=jet_accel / 1000,
                    jet_spread_m=spread,
                    beach_first_share=beach_first_share / 100)
            except ValueError as exc:
                st.error(f"No se pudo resolver el ensayo: {exc}")
            else:
                cm1, cm2, cm3, cm4 = st.columns(4)
                cm1.metric("Q heredado del escenario", f"{plan.equivalent_channel_flow_m3_h:,.0f} m³/h")
                cm2.metric("Vuelta central · ensayo", f"{pilot.lane_lap_min[1]:.1f} min")
                cm3.metric("Vuelta central · mapa actual", f"{field.lane_lap_min[1]:.1f} min")
                cm4.metric("Error máximo de conservación Q", f"{pilot.flow_residual_fraction:.2%}")
                st.caption("La vuelta del ensayo integra un carril a fracción lateral fija; "
                           "la del mapa actual sigue una línea de corriente conceptual. "
                           "La diferencia no es una corrección validada del tiempo real.")
                if refine_grid:
                    refined = compute_momentum_pilot(
                        model.stations, plan, depth_m, model.geometry.scale_m_per_unit,
                        beach_geometry=beach_geometry, beach_bank=beach_bank,
                        eddy_viscosity_m2_s=eddy,
                        jet_acceleration_m_s2=jet_accel / 1000,
                        jet_spread_m=spread,
                        beach_first_share=beach_first_share / 100,
                        longitudinal_cells=128, lateral_cells=17)
                    grid_difference = abs(refined.lane_lap_min[1] - pilot.lane_lap_min[1])
                    st.info(f"Prueba de malla: vuelta central {pilot.lane_lap_min[1]:.2f} → "
                            f"{refined.lane_lap_min[1]:.2f} min; diferencia {grid_difference:.2f} min. "
                            "Convergencia numérica no demuestra validez física.")
                if np.min(pilot.longitudinal_m_s) <= 0:
                    st.error("El escenario genera inversión local de corriente. "
                             "No interprete sus tiempos de vuelta como trayectorias válidas.")
                common_max = max(float(np.max(field.speed_m_s)),
                                 float(np.max(pilot.longitudinal_m_s)))
                fig = go.Figure()
                fig.add_trace(go.Scattergl(
                    x=pilot.x.ravel(), y=pilot.y.ravel(), mode="markers",
                    marker=dict(size=7, color=pilot.longitudinal_m_s.ravel(),
                                cmin=0, cmax=common_max, colorscale="RdYlBu_r",
                                showscale=True, colorbar=dict(title="m/s")),
                    customdata=np.repeat(pilot.chainages_m, len(pilot.lateral_fraction)),
                    hovertemplate="Progresiva %{customdata:.0f} m<br>Velocidad %{marker.color:.3f} m/s<extra></extra>",
                    name="Momento longitudinal · ensayo"))
                for wall, label in ((model.loader.outer_wall, "Muro exterior DXF"),
                                    (model.loader.inner_wall, "Muro interior DXF")):
                    if wall is not None:
                        coordinates = list(wall.coords)
                        fig.add_trace(go.Scatter(
                            x=[p[0] for p in coordinates], y=[p[1] for p in coordinates],
                            mode="lines", line=dict(color="#334155", width=2), name=label))
                fig.update_layout(height=600, margin=dict(l=10, r=10, t=20, b=10),
                                  xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x"))
                st.plotly_chart(fig, width="stretch")
                st.caption("El color muestra velocidad longitudinal promediada en profundidad, no rapidez "
                           "total. La pendiente de playa y su margen son hipótesis; las celdas cercanas "
                           "a la orilla no sirven para evaluar seguridad ni el acceso.")
                profile = go.Figure()
                profile.add_trace(go.Scatter(x=pilot.chainages_m,
                                             y=np.mean(pilot.longitudinal_m_s, axis=1),
                                             name="Ensayo · media de carriles"))
                profile.add_trace(go.Scatter(x=field.chainages_m,
                                             y=np.mean(field.longitudinal_m_s, axis=1),
                                             name="Mapa actual · media de carriles"))
                profile.update_layout(height=270, xaxis_title="Progresiva antihoraria (m)",
                                      yaxis_title="Velocidad (m/s)",
                                      margin=dict(l=20, r=20, t=20, b=30))
                st.plotly_chart(profile, width="stretch")
                st.caption(f"Residuo de ecuaciones lineales: {pilot.momentum_residual_m_s2:.2e} m/s². "
                           "Este residuo solo comprueba la solución numérica, no valida los supuestos. "
                           "Si cambian Manning, DXF, profundidad, unidades o sus posiciones, el ensayo "
                           "se recalcula al ejecutar con los valores actuales. Para decisiones de compra "
                           "siguen siendo necesarios rangos de incertidumbre y una calibración física.")
        st.markdown("[Referencia: ecuaciones 2D completas y criterios de uso de HEC-RAS]"
                    "(https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/6.6/running-a-model-with-2d-flow-areas/2d-computation-options-and-tolerances). "
                    "Este ensayo reducido no implementa esas ecuaciones completas.")

    with tab_cfd:
        st.subheader("Simulación hidráulica 2D · prueba experimental")
        st.warning("No es CFD validado, una corriente estabilizada ni un cálculo de vuelta. "
                   "El agua parte en reposo y el mapa muestra solo los minutos de arranque elegidos. "
                   "No use estas velocidades para seguridad, construcción ni compra de unidades.")
        st.caption("Usa el contorno DXF, las áreas y Manning del escenario actual, el caudal/TDH "
                   "de la curva Riverflow y las posiciones y ángulos editados. La fracción de impulso "
                   "es una hipótesis nueva de momento, NO el 2 % de energía del modelo principal. "
                   "No se representan tomas emparejadas, boquillas reales, turbulencia ni pendiente "
                   "lateral de playa; el fondo es uniforme dentro de cada sección.")
        cx, cy, cz = st.columns(3)
        cfd_impulse_pct = cx.slider(
            "Impulso ideal que llega al agua · hipótesis (%)", 1, 100, 10, 1,
            help="Fracción de Q·sqrt(2gH) aplicada como fuerza localizada. No está medida y no equivale al 2 % de energía.",
            key="riverflow_cfd_impulse")
        cfd_duration_min = cy.slider(
            "Arranque simulado (min)", 1, 10, 5, 1,
            help="Solo tiempo transitorio desde reposo; no es tiempo de vuelta ni estado permanente.",
            key="riverflow_cfd_duration")
        cfd_cell_m = cz.select_slider(
            "Tamaño de celda (m)", [1.5, 2.0, 2.5, 3.0], value=2.5,
            help="El DXF se rasteriza; comparar dos tamaños de celda antes de interpretar el patrón.",
            key="riverflow_cfd_cell")
        cfd_mixing = st.slider(
            "Mezcla horizontal supuesta (m²/s)", 0.0, 0.5, 0.12, 0.02,
            help="Coeficiente exploratorio de difusión; no medido en NYA.",
            key="riverflow_cfd_mixing")
        cfd_signature = (
            hashlib.sha256(model.loader.domain_polygon.wkb).hexdigest(),
            model.geometry.scale_m_per_unit,
            tuple(plan.station_areas_m2), tuple(plan.station_manning_n),
            tuple(plan.module_chainages_m), tuple(plan.module_angles_deg),
            plan.module_flow_full_speed_m3_h, plan.module_head_full_speed_ft,
            plan.speed_fraction, cfd_impulse_pct, cfd_duration_min,
            cfd_cell_m, cfd_mixing)
        if st.button("Ejecutar simulación 2D experimental", key="riverflow_cfd_run"):
            try:
                with st.spinner("Calculando la malla 2D del DXF…"):
                    preview = compute_cfd_preview(
                        model, plan, cell_m=cfd_cell_m,
                        duration_s=cfd_duration_min * 60,
                        impulse_fraction=cfd_impulse_pct / 100,
                        mixing_m2_s=cfd_mixing)
                st.session_state["riverflow_cfd_result"] = preview
                st.session_state["riverflow_cfd_signature"] = cfd_signature
            except ValueError as exc:
                st.error(f"La prueba 2D no terminó: {exc}")
        preview = st.session_state.get("riverflow_cfd_result")
        if preview is None:
            st.info("Pulse «Ejecutar» para generar el mapa; el cálculo puede tardar varios segundos. "
                    "Esta prueba no altera los demás resultados.")
        elif st.session_state.get("riverflow_cfd_signature") != cfd_signature:
            st.warning("Cambió el DXF o un parámetro que afecta esta prueba. El resultado anterior "
                       "se oculta para evitar mezclar escenarios; pulse «Ejecutar» de nuevo.")
        else:
            experimental_speed = preview.speed_m_s[preview.wet]
            experimental_along = preview.along_m_s[preview.wet]
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("Rapidez media · arranque", f"{float(np.mean(experimental_speed)):.3f} m/s")
            d2.metric("Rapidez máxima de celda", f"{float(np.max(experimental_speed)):.3f} m/s")
            d3.metric("Celdas con flujo inverso", f"{float(np.mean(experimental_along < -0.005)):.1%}")
            d4.metric("Balance numérico de agua", f"{preview.water_balance_error_m3:.1e} m³")
            st.caption(f"Tiempo físico desde reposo: {preview.duration_s / 60:.0f} min; "
                       f"{preview.wet_cell_count:,} celdas mojadas; Courant máximo "
                       f"{preview.max_courant:.2f}. Un balance numérico pequeño no valida "
                       "el impulso, las boquillas ni el fondo real.")
            color_max = max(float(np.max(experimental_speed)), float(np.max(field.speed_m_s)))
            current_fig = make_map(model, plan, show_installation=False,
                                   show_velocity_heatmap=True, field=field,
                                   color_range=(0.0, color_max))
            current_fig.update_layout(height=530)
            experimental_fig = go.Figure()
            experimental_fig.add_trace(go.Heatmap(
                x=preview.x_dxf, y=preview.y_dxf,
                z=np.where(preview.wet, preview.speed_m_s, np.nan),
                colorscale="RdYlBu_r", zmin=0, zmax=color_max,
                colorbar=dict(title="m/s"),
                hovertemplate="Rapidez transitoria %{z:.3f} m/s<extra></extra>"))
            for wall, label in ((model.loader.outer_wall, "Muro exterior DXF"),
                                (model.loader.inner_wall, "Muro interior DXF")):
                coordinates = list(wall.coords)
                experimental_fig.add_trace(go.Scatter(
                    x=[point[0] for point in coordinates],
                    y=[point[1] for point in coordinates], mode="lines",
                    line=dict(color="#334155", width=2), name=label))
            experimental_fig.add_trace(go.Scatter(
                x=preview.module_x_dxf, y=preview.module_y_dxf,
                mode="markers", name="Descargas esquemáticas",
                marker=dict(size=7, color="white",
                            line=dict(color="#111827", width=1))))
            experimental_fig.update_layout(
                height=530, margin=dict(l=5, r=5, t=10, b=5),
                xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x"),
                legend=dict(orientation="h", y=-0.08))
            left_map, right_map = st.columns(2)
            with left_map:
                st.markdown("**Modelo conceptual actual · depende del 2 %**")
                st.plotly_chart(current_fig, width="stretch")
            with right_map:
                st.markdown("**Prueba 2D · arranque desde reposo**")
                st.plotly_chart(experimental_fig, width="stretch")
            st.info("Ambos mapas usan la misma escala de colores, pero representan estados y "
                    "supuestos distintos. La diferencia NO es una corrección del tiempo de vuelta. "
                    "Para avanzar: emparejar tomas y descargas, definir su geometría, comprobar "
                    "malla/tiempo y alcanzar una corriente sostenida.")

    with tab_treatment:
        st.subheader("Tratamiento de agua · circuito independiente")
        t1, t2, t3 = st.columns(3)
        t1.metric("Volumen hidráulico DXF", f"{plan.volume_m3:,.0f} m³")
        t2.metric("Recambio de filtración supuesto", f"{turnover_h:.1f} h")
        t3.metric("Q que debe atravesar filtros", f"{plan.filtration_flow_m3_h:,.0f} m³/h")
        st.info("Los módulos Riverflow impulsan la corriente, pero su descarga local no se cuenta "
                "como caudal filtrado. El recambio se calcula solo con el flujo que realmente pasa "
                "por el sistema de tratamiento: Q = volumen / horas de recambio.")
        st.caption("4 horas es una hipótesis inicial editable, no una aprobación sanitaria para Liberia. "
                   "El volumen definitivo debe incluir también el tanque de compensación si forma "
                   "parte del circuito de tratamiento. 2 h requiere el doble de caudal filtrado "
                   "que 4 h con el mismo volumen.")
        st.dataframe([{"Escenario": label, "Turnover (h)": hours,
                       "Q requerido por filtros (m³/h)": round(plan.volume_m3 / hours, 1)}
                      for label, hours in (("Costa Rica · categoría >0,60 m, por confirmar", 6.0),
                                           ("NYA · escenario editable inicial", 4.0),
                                           ("MAHC 2024 · lazy river, comparación internacional", 2.0))],
                     width="stretch", hide_index=True)
        st.caption("El [artículo 32 del Reglamento sobre Manejo de Piscinas de Costa Rica]"
                   "(https://www.imprentanacional.go.cr/pub/2009/07/02/COMP_02_07_2009.html) "
                   "indica 6 h para los demás vasos o partes de más de 0,60 m: confirmar la "
                   "clasificación del lazy river ante la autoridad. Como comparación técnica, "
                   "[MAHC 2024, tabla 4.7.1.10]"
                   "(https://www.cdc.gov/model-aquatic-health-code/media/pdfs/2024/11/5th-Ed-MAHC-Code-508.pdf) "
                   "indica 2 h o menos para lazy rivers, pero NO es ley costarricense. "
                   "Ninguno de estos caudales es consumo de agua nueva ni se suma a Riverflow.")
        candidate_rate = st.number_input("Tasa de filtración de prueba (m/h)", 1.0, 60.0,
                                          20.0, 1.0,
                                          help="Hipótesis para comparar áreas, NO una recomendación de diseño ni un límite normativo. La tasa final depende del tipo y fabricante del filtro.")
        candidate_area = st.number_input("Área efectiva por filtro candidato (m²; 0 si no se conoce)",
                                          0.0, 200.0, 0.0, 1.0)
        total_filter_area = plan.filtration_flow_m3_h / candidate_rate
        st.metric("Área total de filtración · hipótesis", f"{total_filter_area:,.1f} m²")
        if candidate_area > 0:
            st.metric("Filtros activos mínimos · aritmética", f"{ceil(total_filter_area / candidate_area)}")
        st.markdown("**Preselección automática de bombas comerciales**")
        active_filter_pumps = int(st.session_state["filtration_active_pumps"])
        per_filter_pump = plan.filtration_flow_m3_h / active_filter_pumps
        pump_options = screen_pump_families(plan.filtration_flow_m3_h, active_filter_pumps)
        eligible_for_review = [item["family"].name for item in pump_options
                               if not item["screening"].startswith("Descartada")]
        st.info(f"Con {active_filter_pumps} bombas activas, se necesitan **{per_filter_pump:,.1f} m³/h "
                "por bomba**. Familias para revisar: **"
                + ", ".join(eligible_for_review)
                + "**. Esta es una preselección por caudal máximo publicado, no una selección "
                  "aprobada a la TDH de NYA. Cambia la cantidad en «Filtración guiada».")
        st.dataframe([{
            "Familia / modelo de referencia": item["family"].name + " · " + item["family"].examples,
            "Potencia de placa": item["family"].hp_range,
            "Caudal máximo de familia (m³/h)": (round(item["family"].published_max_m3_h)
                                                  if item["family"].published_max_m3_h else None),
            "Resultado preliminar": item["screening"],
        } for item in pump_options], width="stretch", hide_index=True)
        st.caption("Fichas oficiales: " + " · ".join(
            f"[{item['family'].name}]({item['family'].curve_url})" for item in pump_options))
        st.markdown("**Prueba de capacidad y contingencias — pendiente de curva a la TDH real**")
        pc1, pc2, pc3 = st.columns(3)
        pc1.metric("Bombas activas · escenario", str(active_filter_pumps),
                   help="Se eligen en Filtración guiada; la reserva se suma aparte.")
        standby_filter_pumps = pc2.number_input("Bombas de reserva adicionales", 0, 20, 0, 1)
        installed_filter_pumps = active_filter_pumps + standby_filter_pumps
        pump_delivered_flow = pc3.number_input(
            "Caudal comprobado por bomba con filtro sucio (m³/h; 0 = desconocido)",
            0.0, 5000.0, 0.0, 10.0,
            help="Introducir solo caudal verificable a la TDH del sistema con filtro sucio.")
        standby_takeover = st.checkbox("La reserva arranca al fallar una bomba activa",
                                       value=False,
                                       help="Solo activar si la reserva tiene capacidad equivalente y "
                                            "el sistema de transferencia está previsto.")
        fc1, fc2 = st.columns(2)
        installed_filters = fc1.number_input("Filtros instalados · escenario", 0, 200, 0, 1)
        unavailable_filters = fc2.number_input("Filtros fuera de servicio", 0,
                                                 installed_filters, 0, 1)
        filtration = evaluate_filtration(
            plan.volume_m3, turnover_h,
            installed_pumps=installed_filter_pumps, standby_pumps=standby_filter_pumps,
            standby_auto_start=standby_takeover,
            flow_per_pump_at_dirty_head_m3_h=(pump_delivered_flow or None),
            installed_filters=installed_filters, unavailable_filters=unavailable_filters,
            area_per_filter_m2=(candidate_area or None),
            maximum_filter_rate_m_h=candidate_rate)
        st.dataframe([
            {"Comprobación": "Reparto requerido entre bombas activas",
             "Resultado": f"{filtration.required_per_pump_m3_h:,.1f} m³/h por bomba",
             "Estado": "Necesidad, no capacidad verificada"},
            {"Comprobación": "Bombas en operación normal",
             "Resultado": (f"{filtration.pump_capacity_m3_h:,.1f} m³/h"
                           if filtration.pump_capacity_m3_h is not None else "Dato requerido"),
             "Estado": filtration.pump_status},
            {"Comprobación": "Una bomba activa fuera (N−1)",
             "Resultado": (f"{filtration.pump_capacity_n_minus_1_m3_h:,.1f} m³/h"
                           if filtration.pump_capacity_n_minus_1_m3_h is not None else "Dato requerido"),
             "Estado": filtration.pump_n_minus_1_status},
            {"Comprobación": "Filtros disponibles",
             "Resultado": (f"{filtration.actual_filter_rate_m_h:,.1f} m/h a Q objetivo"
                           if filtration.actual_filter_rate_m_h is not None else "Dato requerido"),
             "Estado": filtration.filter_status},
        ], width="stretch", hide_index=True)
        st.caption("N−1 usa el caudal demostrado de las bombas que quedan; "
                   "solo cuenta la reserva si se activa su relevo. No supone que las restantes "
                   "aumenten automáticamente su caudal. "
                   "La tasa máxima del filtro es solo la hipótesis editable anterior.")
        st.markdown("**Retrolavado — cálculo de un evento**")
        bw1, bw2, bw3 = st.columns(3)
        wash_rate = bw1.number_input("Tasa de retrolavado (m/h; 0 = pendiente)",
                                      0.0, 100.0, 0.0, 1.0)
        wash_minutes = bw2.number_input("Duración del lavado (min; 0 = pendiente)",
                                         0.0, 60.0, 0.0, 1.0)
        wash_parallel = bw3.number_input("Filtros simultáneos en lavado", 1, 20, 1, 1)
        if candidate_area > 0 and wash_rate > 0 and wash_minutes > 0:
            bw = calculate_backwash(candidate_area, wash_rate, wash_minutes,
                                    0.0, 0.0, wash_parallel)
            st.metric("Agua por evento de lavado · sin enjuague", f"{bw.wash_volume_m3:,.1f} m³")
            st.caption(f"Caudal instantáneo de lavado: {bw.flow_m3_h:,.1f} m³/h. "
                       "Faltan enjuague, reserva operativa y destino del efluente para dimensionar "
                       "el tanque o el agua nueva diaria.")
        else:
            st.info("Para calcular retrolavado, ingrese área real del filtro, tasa y duración "
                    "según su ficha técnica. No se presupone un tanque de tamaño fijo.")
        with st.expander("Comprobar una tubería de filtración · Darcy–Weisbach"):
            st.caption("Cálculo de un tramo definido por el usuario; no calcula toda la TDH de la planta "
                       "ni selecciona automáticamente un diámetro o una bomba.")
            pipe1, pipe2, pipe3 = st.columns(3)
            pipe_flow = pipe1.number_input("Caudal en este tramo (m³/h)",
                                            0.0, 5000.0, 0.0, 10.0)
            pipe_diameter = pipe2.number_input("Diámetro interior (m; 0 = pendiente)",
                                                0.0, 2.0, 0.0, 0.01)
            pipe_length = pipe3.number_input("Longitud real del tramo (m; 0 = pendiente)",
                                              0.0, 5000.0, 0.0, 1.0)
            pipe4, pipe5 = st.columns(2)
            pipe_roughness = pipe4.number_input("Rugosidad absoluta (mm)",
                                                 0.0, 10.0, 0.0, 0.01,
                                                 help="0 representa pared hidráulicamente lisa de prueba; "
                                                      "introduzca el dato del material real.")
            pipe_k = pipe5.number_input("Suma K de accesorios del tramo", 0.0, 100.0,
                                        0.0, 0.1)
            if pipe_flow > 0 and pipe_diameter > 0 and pipe_length > 0:
                pipe = calculate_pipe_losses(pipe_flow, pipe_diameter, pipe_length,
                                             pipe_roughness, pipe_k)
                st.dataframe([
                    {"Resultado": "Velocidad", "Valor": f"{pipe.velocity_m_s:.2f} m/s"},
                    {"Resultado": "Reynolds", "Valor": f"{pipe.reynolds:,.0f}"},
                    {"Resultado": "Pérdida tramo recto", "Valor": f"{pipe.straight_loss_m:.2f} m"},
                    {"Resultado": "Pérdida accesorios", "Valor": f"{pipe.fittings_loss_m:.2f} m"},
                    {"Resultado": "Pérdida de este tramo", "Valor": f"{pipe.total_loss_m:.2f} m"},
                ], width="stretch", hide_index=True)
            else:
                st.info("Faltan caudal, diámetro interior y longitud del tramo para calcular pérdidas.")
        turnover_options = np.arange(2.0, 12.5, 0.5)
        turnover_chart = go.Figure()
        turnover_chart.add_trace(go.Scatter(x=turnover_options,
                                            y=plan.volume_m3 / turnover_options,
                                            mode="lines", name="Q filtración requerida",
                                            line=dict(color="#0891b2", width=3)))
        turnover_chart.add_trace(go.Scatter(x=[turnover_h], y=[plan.filtration_flow_m3_h],
                                            mode="markers", name="Escenario actual",
                                            marker=dict(size=12, color="#ea580c")))
        turnover_chart.update_layout(height=290, margin=dict(l=20, r=20, t=20, b=25),
                                     xaxis_title="Tiempo de recambio supuesto (h)",
                                     yaxis_title="Caudal filtrado necesario (m³/h)")
        st.plotly_chart(turnover_chart, width="stretch")
        st.markdown(f"**Equipos a prever para la hipótesis seleccionada de {turnover_h:.1f} horas**")
        st.dataframe([
            {"Componente": "Bombas de recirculación independientes",
             "Criterio de fase 1": f"Caudal conjunto filtrado ≥ {plan.filtration_flow_m3_h:,.0f} m³/h a la TDH de la planta",
             "Pendiente": "Curva H–Q, pérdidas y redundancia"},
            {"Componente": "Filtros",
             "Criterio de fase 1": f"Área total ilustrativa {total_filter_area:,.1f} m² con {candidate_rate:.0f} m/h",
             "Pendiente": "Tipo, tasa admisible y retrolavado según fabricante"},
            {"Componente": "Desinfección y control de pH",
             "Criterio de fase 1": "Dosificación y medición continuas",
             "Pendiente": "Demanda química, tecnología y diseño sanitario"},
            {"Componente": "Tanque de compensación y retornos",
             "Criterio de fase 1": "Balance, captación y distribución sin zonas muertas",
             "Pendiente": "Volumen, reboses y perfil de niveles"},
            {"Componente": "Instrumentación y descarga",
             "Criterio de fase 1": "Medidor de caudal filtrado, presiones y manejo de retrolavado",
             "Pendiente": "Destino autorizado, alarmas y operación"},
        ], width="stretch", hide_index=True)
        st.warning("La tasa de filtración de prueba no valida filtros ni permite fijar su cantidad final. "
                   "Confirmar calidad y capacidad del pozo, norma sanitaria aplicable en Liberia, "
                   "aforo máximo y diseño de la planta de tratamiento con profesionales responsables.")
        st.markdown("Como referencia internacional, el [MAHC 2024 del CDC](https://www.cdc.gov/model-aquatic-health-code/media/pdfs/2024/11/5th-Ed-MAHC-Code-508.pdf) "
                    "define el recambio por el agua que atraviesa filtración y excluye el caudal "
                    "de funciones acuáticas sin filtrar. Es guía, no norma costarricense aplicable automáticamente.")

    with tab_guided:
        st.subheader("Filtración explicada · primer vistazo sin fichas manuales")
        st.info("Este circuito limpia la misma agua del río. Es independiente de las bombas Riverflow "
                "que crean la corriente. Los números siguientes son requisitos calculados, no compras aprobadas.")
        gd1, gd2, gd3 = st.columns(3)
        gd1.metric("Agua dentro del río", f"{plan.volume_m3:,.0f} m³",
                   help="Sale del DXF escalado y de la profundidad indicada; no es consumo diario.")
        gd2.metric("Tiempo de tratamiento", f"{turnover_h:.1f} h",
                   help="Tiempo teórico para que pase por filtros un volumen equivalente al del río.")
        gd3.metric("Caudal necesario por filtros", f"{plan.filtration_flow_m3_h:,.0f} m³/h",
                   help="Volumen ÷ horas. No es caudal Riverflow ni agua nueva del pozo.")
        st.markdown(f"**¿De dónde sale?** {plan.volume_m3:,.0f} m³ ÷ {turnover_h:.1f} h = "
                    f"**{plan.filtration_flow_m3_h:,.0f} m³/h** que deben atravesar realmente "
                    "el tratamiento. El objetivo de horas se cambia en el menú lateral.")
        guided_duty = st.number_input("Bombas de filtración activas para comparar",
                                      min_value=2, max_value=50, step=1,
                                      key="filtration_active_pumps",
                                      help="La misma cantidad se usa en Filtración avanzada y en "
                                           "la comparación de familias comerciales.")
        per_duty = plan.filtration_flow_m3_h / guided_duty
        per_remaining = plan.filtration_flow_m3_h / (guided_duty - 1)
        pg1, pg2 = st.columns(2)
        pg1.metric("Cada bomba tendría que entregar", f"{per_duty:,.0f} m³/h",
                   help="Caudal filtrado total dividido entre las bombas que operan normalmente.")
        pg2.metric("Si una se detiene y no entra reserva", f"{per_remaining:,.0f} m³/h",
                   help="Necesidad por cada bomba restante. No demuestra que las bombas puedan hacerlo.")
        st.caption("Si existe una bomba de reserva que arranca automáticamente, el reparto puede "
                   "mantenerse. Esa contingencia se prueba en Filtración avanzada.")
        st.markdown("**Bombas comerciales para investigar**")
        screened = screen_pump_families(plan.filtration_flow_m3_h, guided_duty)
        pentair_limit = screened[0]["family"].published_max_m3_h
        large_speck_limit = screened[2]["family"].published_max_m3_h
        if per_duty <= pentair_limit:
            st.success("Sugerencia de búsqueda: empezar por Pentair EQ y Speck BADU Block Multi. "
                       "Ambas siguen pendientes de comprobar en su curva Q–H a la TDH de NYA.")
        elif per_duty <= large_speck_limit:
            st.success("Sugerencia de búsqueda: revisar primero Speck BADU Block Multi 125/250 "
                       "y comparar con BADU Block. Pentair EQ queda descartada con esta cantidad "
                       "de bombas por su máximo publicado; ninguna Speck está aún validada a la TDH de NYA.")
        else:
            st.warning("Con esta cantidad de bombas, incluso el máximo anunciado de las familias "
                       "con límite publicado es menor que la necesidad por unidad. Compare más "
                       "bombas en servicio u otra familia de mayor capacidad.")
        st.dataframe([{
            "Familia comercial": item["family"].name,
            "Modelos de ejemplo": item["family"].examples,
            "Motor publicado": item["family"].hp_range,
            "Velocidad": item["family"].rpm,
            "Máximo anunciado de familia (m³/h)":
                (round(item["family"].published_max_m3_h)
                 if item["family"].published_max_m3_h is not None else None),
            "Preselección": item["screening"],
        } for item in screened], width="stretch", hide_index=True)
        for item in screened:
            family = item["family"]
            st.markdown(f"- **{family.name}** ({family.hp_range}, {family.rpm}; "
                        f"{family.frequency}). {family.ports}. {family.note} "
                        f"[Ficha y curva del fabricante]({family.curve_url}).")
        st.warning("La app puede descartar una familia cuyo máximo publicado sea menor que el caudal "
                   "necesario por bomba. No puede confirmar una bomba como apta hasta conocer la TDH "
                   "de la planta y leer su caudal en esa TDH. HP no equivale a caudal garantizado. "
                   "Disponibilidad, voltaje y certificación para Costa Rica siguen pendientes.")
        st.markdown("**Filtros · ejemplo para entender escala**")
        example_filter_area = 5.0
        example_count = ceil(plan.filtration_flow_m3_h /
                             (example_filter_area * candidate_rate))
        ef1, ef2, ef3 = st.columns(3)
        ef1.metric("Filtro de ejemplo", "Waterco M5000 · 5,0 m²")
        ef2.metric("Tasa de prueba editable", f"{candidate_rate:.0f} m/h")
        ef3.metric("Filtros activos · aritmética", str(example_count))
        st.caption(f"Cálculo: {plan.filtration_flow_m3_h:,.0f} m³/h ÷ "
                   f"(5,0 m² × {candidate_rate:.0f} m/h) = {example_count} filtros activos "
                   "redondeando hacia arriba. No incluye reserva ni demuestra que la tasa de prueba "
                   "sea válida para el medio filtrante elegido. "
                   "[Área M5000 publicada por Waterco]"
                   "(https://watercocn.waterco.com/waterco/catalogues/water-treatment/"
                   "waterco_ps_cfilters.pdf).")
        with st.expander("Explicarme los números y qué falta para elegir equipos"):
            st.markdown("**Caudal por bomba:** necesidad de tratamiento ÷ bombas en marcha. "
                        "**N−1:** necesidad ÷ bombas restantes; solo es una exigencia, no la capacidad real. "
                        "**TDH:** resistencia total de tuberías, filtros sucios, accesorios y retornos. "
                        "La ficha de la bomba debe demostrar el caudal calculado a esa TDH. "
                        "**HP:** potencia nominal del motor; no se obtiene multiplicando solamente caudal "
                        "por número de bombas. **Filtros:** su cantidad depende del caudal y de la tasa "
                        "admisible del modelo, y deben considerarse lavado y reserva. "
                        "**Agua nueva:** repone pérdidas; no equivale al caudal que circula por filtros.")

    with tab_scenarios:
        st.subheader("Comparar dos escenarios sobre el mismo DXF")
        st.caption("La geometría y la profundidad permanecen iguales. Los colores usan la misma escala "
                   "en ambos planos; el campo lateral es una hipótesis 2D, no CFD validado.")
        sc1, sc2, sc3 = st.columns(3)
        alternative_modules = sc1.number_input("Unidades Riverflow activas · alternativa",
                                                1, 60, max(1, active_modules - 1), 1)
        alternative_speed_pct = sc2.slider("Variador Riverflow · alternativa (%)",
                                            50, 100, speed_pct, 1)
        alternative_turnover_h = sc3.number_input("Recirculación de filtros · alternativa (h)",
                                                  2.0, 12.0, min(12.0, turnover_h + 2), 0.5)
        alternative_filters_out = st.number_input("Filtros fuera de servicio · alternativa",
                                                   0, installed_filters, unavailable_filters, 1)
        if alternative_modules == active_modules:
            alternative_positions = manual_positions
            alternative_angles = module_angles
        else:
            alternative_positions = None
            alternative_angles = [0.0] * alternative_modules
        alternative_point = None
        if use_local_circuit:
            try:
                alternative_point = (solve_local_circuit(
                    circuit, speed_fraction=alternative_speed_pct / 100,
                    curve_mode=curve_mode) if selected_reference is None else
                    reference_operating_point(selected_reference,
                                              alternative_speed_pct / 100))
            except ValueError as exc:
                st.error(f"La alternativa no tiene punto de operación dentro de la curva disponible: {exc}")
                st.stop()
        alternative_head_ft = (alternative_point.pump_head_ft /
                               (alternative_speed_pct / 100) ** 2
                               if alternative_point else local_head_manual_ft)
        alternate_plan = compute_riverflow_plan(
            model.stations, depth_m=depth_m, target_lap_min=target_lap_min,
            active_modules=alternative_modules, standby_modules=standby_modules,
            module_head_full_speed_ft=alternative_head_ft,
            speed_fraction=alternative_speed_pct / 100,
            transfer_fraction=transfer_pct / 100,
            calm_zone_width_m=calm_width_m,
            filtration_turnover_h=alternative_turnover_h,
            floor_manning_n=floor_n, wall_manning_n_current=wall_n_current,
            wall_manning_n_calm=wall_n_calm, curve_mode=curve_mode,
            module_chainages_m=alternative_positions,
            module_angles_deg=alternative_angles,
            beach_geometry=beach_geometry,
            module_flow_full_speed_override_m3_h=(alternative_point.flow_m3_h /
                                                   (alternative_speed_pct / 100)
                                                   if alternative_point else None))
        alternate_field = compute_field_2d(model.stations, alternate_plan, depth_m,
                                           scale_m_per_unit=model.geometry.scale_m_per_unit)
        alternate_filtration = evaluate_filtration(
            alternate_plan.volume_m3, alternative_turnover_h,
            installed_pumps=installed_filter_pumps, standby_pumps=standby_filter_pumps,
            standby_auto_start=standby_takeover,
            flow_per_pump_at_dirty_head_m3_h=(pump_delivered_flow or None),
            installed_filters=installed_filters, unavailable_filters=alternative_filters_out,
            area_per_filter_m2=(candidate_area or None),
            maximum_filter_rate_m_h=candidate_rate)
        common_range = (float(min(np.min(field.speed_m_s), np.min(alternate_field.speed_m_s))),
                        float(max(np.max(field.speed_m_s), np.max(alternate_field.speed_m_s))))
        map_left, map_right = st.columns(2)
        with map_left:
            st.markdown("**Actual**")
            st.plotly_chart(make_map(model, plan, True, True, field,
                                     color_range=common_range), width="stretch")
        with map_right:
            st.markdown("**Alternativa**")
            st.plotly_chart(make_map(model, alternate_plan, True, True, alternate_field,
                                     color_range=common_range), width="stretch")
        scenario_rows = [
            {"Indicador": "Riverflow activas", "Actual": active_modules,
             "Alternativa": alternative_modules},
            {"Indicador": "Caudal por unidad (m³/h) · curva/circuito",
             "Actual": round(plan.module_flow_full_speed_m3_h * plan.speed_fraction, 1),
             "Alternativa": round(alternate_plan.module_flow_full_speed_m3_h *
                                  alternate_plan.speed_fraction, 1)},
            {"Indicador": "Tiempo de vuelta volumétrico · escenario (min)",
             "Actual": round(plan.estimated_lap_min, 1),
             "Alternativa": round(alternate_plan.estimated_lap_min, 1)},
            {"Indicador": "Vuelta carril central 2D · escenario (min)",
             "Actual": round(field.lane_lap_min[1], 1),
             "Alternativa": round(alternate_field.lane_lap_min[1], 1)},
            {"Indicador": "Caudal que debe atravesar filtros (m³/h)",
             "Actual": round(plan.filtration_flow_m3_h, 1),
             "Alternativa": round(alternate_plan.filtration_flow_m3_h, 1)},
            {"Indicador": "Estado filtros · hipótesis",
             "Actual": filtration.filter_status,
             "Alternativa": alternate_filtration.filter_status},
            {"Indicador": "Estado bombas filtración · hipótesis",
             "Actual": filtration.pump_status,
             "Alternativa": alternate_filtration.pump_status},
        ]
        st.dataframe([{key: str(value) for key, value in row.items()}
                      for row in scenario_rows], width="stretch", hide_index=True)
        profile = go.Figure()
        profile.add_trace(go.Scatter(x=[s["chainage_m"] for s in model.stations],
                                     y=plan.station_velocities_m_s, mode="lines",
                                     name="Actual · Q/A", line=dict(color="#2563eb")))
        profile.add_trace(go.Scatter(x=[s["chainage_m"] for s in model.stations],
                                     y=alternate_plan.station_velocities_m_s, mode="lines",
                                     name="Alternativa · Q/A", line=dict(color="#ea580c")))
        profile.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=25),
                              xaxis_title="Progresiva (m)", yaxis_title="Velocidad media por sección (m/s)")
        st.plotly_chart(profile, width="stretch")
        st.caption("La filtración cambia al editar el turnover, pero no se suma a la corriente "
                   "Riverflow. Si cambia el número de unidades, la alternativa las distribuye "
                   "automáticamente; no se conserva una lista manual de otra longitud.")

        st.subheader("Matriz de incertidumbre · Riverflow y 40 minutos")
        st.caption("Cruza 3 cantidades de unidades, 3 velocidades del variador y 3 hipótesis de "
                   "pérdidas concentradas K. Usa el mismo DXF, playa y Manning de arriba; "
                   "las filas fuera de la curva publicada quedan sin resultado. "
                   "La energía útil se puede cambiar aparte porque NO está medida. "
                   "No calcula consumo eléctrico ni certifica velocidad segura.")
        show_envelope = st.checkbox("Calcular matriz de sensibilidad", value=False)
        if show_envelope:
            energy_factor = st.selectbox(
                "Energía útil para matriz · hipótesis",
                (0.5, 1.0, 2.0), index=1,
                format_func=lambda factor: f"{transfer_pct * factor:.2f}% "
                    f"({factor:.1f}× el valor principal)")
            counts = tuple(dict.fromkeys((max(1, active_modules - 2), active_modules,
                                          min(60, active_modules + 2))))
            if speed_pct >= 90:
                speeds = (speed_pct - 40, speed_pct - 20, speed_pct)
            elif speed_pct <= 60:
                speeds = (speed_pct, speed_pct + 20, speed_pct + 40)
            else:
                speeds = (speed_pct - 20, speed_pct, speed_pct + 20)
            k_factors = (0.75, 1.0, 1.25)
            envelope = evaluate_envelope(
                model.stations, circuit, depth_m=depth_m,
                target_lap_min=target_lap_min, module_counts=counts,
                speeds_pct=speeds, k_factors=k_factors,
                transfer_fraction=transfer_pct * energy_factor / 100,
                curve_mode=curve_mode,
                calm_zone_width_m=calm_width_m, floor_manning_n=floor_n,
                wall_manning_n_current=wall_n_current,
                wall_manning_n_calm=wall_n_calm,
                beach_geometry=beach_geometry,
                scale_m_per_unit=model.geometry.scale_m_per_unit,
                current_modules=active_modules, current_positions_m=manual_positions,
                current_angles_deg=module_angles)
            focus_k = st.selectbox("Hipótesis K para mapa de vuelta", k_factors, index=1,
                                   format_func=lambda x: f"{x:.0%} del K ingresado")
            heat = go.Figure(go.Heatmap(
                x=list(speeds), y=list(counts),
                z=[[next((None if row.slow_lane_lap_min is None else
                          0 if row.slow_lane_lap_min <= target_lap_min else 1
                          for row in envelope
                          if row.modules == n and row.speed_pct == speed and
                          row.k_factor == focus_k), None) for speed in speeds]
                   for n in counts],
                text=[[next(("Sin curva" if row.slow_lane_lap_min is None else
                             f"{row.slow_lane_lap_min:.1f} min" for row in envelope
                             if row.modules == n and row.speed_pct == speed and
                             row.k_factor == focus_k), "") for speed in speeds]
                      for n in counts],
                texttemplate="%{text}", zmin=0, zmax=1,
                colorscale=[[0, "#047857"], [0.49, "#047857"],
                            [0.5, "#b91c1c"], [1, "#b91c1c"]],
                showscale=False,
                hovertemplate="Unidades %{y}<br>Variador %{x}%<br>%{text}<extra></extra>"))
            heat.update_layout(height=310, margin=dict(l=15, r=15, t=20, b=35),
                               xaxis_title="Variador (%), escala por afinidad aproximada",
                               yaxis_title="Unidades activas", yaxis=dict(type="category"))
            st.plotly_chart(heat, width="stretch")
            st.caption("Verde: trayectoria más lenta ≤ meta. Rojo: supera la meta. "
                       "Sin color: fuera de la curva disponible. El número en la celda "
                       "es el tiempo estimado, no una medición.")
            st.dataframe([{
                "Unidades": row.modules, "Variador (%)": row.speed_pct,
                "K relativo": f"{row.k_factor:.0%}",
                "Q unidad (m³/h)": round(row.module_flow_m3_h, 1)
                    if row.module_flow_m3_h is not None else None,
                "TDH local (ft)": round(row.module_head_ft, 2)
                    if row.module_head_ft is not None else None,
                "Vuelta lenta 2D (min)": round(row.slow_lane_lap_min, 1)
                    if row.slow_lane_lap_min is not None else None,
                "Potencia hidráulica/unidad (kW)": round(row.pump_hydraulic_kw_per_unit, 2)
                    if row.pump_hydraulic_kw_per_unit is not None else None,
                "Estado": row.status,
            } for row in envelope], width="stretch", hide_index=True)
            st.warning("El K es una hipótesis agregada; 75% y 125% NO son límites medidos. "
                       "Una celda verde significa solo que cumple los 40 min bajo estas "
                       "hipótesis, incluyendo la energía útil elegida. "
                       "La potencia hidráulica es energía transmitida al agua, "
                       "NO consumo eléctrico ni HP de placa. Sin curva de potencia y "
                       "rendimiento a cada RPM, no se calculan kWh ni costo operativo.")

    with tab_decision:
        st.subheader("Hoja de decisión · NYA / Riverflow")
        st.info("Lectura rápida: la geometría y el volumen proceden del DXF y el perfil de playa "
                "supuesto; el caudal de cada bomba usa la curva disponible y pérdidas locales "
                "editables. Velocidades y vuelta siguen dependiendo del 2 % no medido. "
                "El ensayo 2D hereda ese caudal y no lo valida.")
        st.markdown("**Preselección de cantidad y ubicación · mismo DXF y bombas Riverflow**")
        st.caption("Compare cantidades activas manteniendo la velocidad del variador, circuito "
                   "local, rugosidad, profundidad y recambio elegidos. La fila de la cantidad "
                   "actual conserva sus ubicaciones y ángulos editados; las alternativas se "
                   "reparten automáticamente en zonas de corriente con salidas alineadas.")
        cr1, cr2 = st.columns(2)
        count_limits = cr1.slider(
            "Rango de unidades activas a comparar", 1, 60,
            (max(1, active_modules - 6), min(60, active_modules + 6)),
            key=f"rf_count_range_{active_modules}")
        count_step = cr2.select_slider(
            "Salto entre cantidades", options=(1, 2, 3, 4, 5, 6, 8, 10), value=3)
        counts_to_check = list(range(count_limits[0], count_limits[1] + 1,
                                     count_step))
        if count_limits[0] <= active_modules <= count_limits[1]:
            counts_to_check.append(active_modules)
        counts_to_check = sorted(set(counts_to_check))
        if len(counts_to_check) > 15:
            st.warning("El rango produciría más de 15 diseños; aumente el salto para "
                       "mantener legible la comparación.")
        else:
            count_options = evaluate_count_options(
                model.stations, counts=counts_to_check, current_plan=plan,
                current_field=field, depth_m=depth_m,
                scale_m_per_unit=model.geometry.scale_m_per_unit,
                calm_zone_width_m=calm_width_m, floor_manning_n=floor_n,
                wall_manning_n_current=wall_n_current,
                wall_manning_n_calm=wall_n_calm,
                filtration_turnover_h=turnover_h, beach_geometry=beach_geometry)
            st.dataframe([{
                "Unidades activas": option.plan.active_modules,
                "Q local total (m³/h)": round(option.plan.installed_operating_flow_m3_h),
                "Vuelta lenta · 0,5× energía (min)": round(option.slow_lap_low_transfer_min, 1),
                "Vuelta lenta · hipótesis actual (min)": round(option.slow_lap_nominal_min, 1),
                "Vuelta lenta · 2× energía (min)": round(option.slow_lap_high_transfer_min, 1),
                "Velocidad seccional min–máx (m/s)":
                    f"{option.plan.velocity_min_m_s:.3f}–{option.plan.velocity_max_m_s:.3f}",
                "Mayor espacio entre unidades (m)": round(option.max_module_spacing_m),
            } for option in count_options], width="stretch", hide_index=True)
            current_areas = [area for area, zone in
                             zip(plan.station_areas_m2, plan.station_zones)
                             if zone == "current"]
            if current_areas:
                band_flow_lower = max(current_areas) * .25 * 3600
                band_flow_upper = min(current_areas) * .30 * 3600
                if band_flow_lower > band_flow_upper:
                    st.warning("Con las secciones de corriente del DXF, un solo caudal "
                               "longitudinal no puede mantener todas entre 0,25 y 0,30 m/s: "
                               f"haría falta Q ≥ {band_flow_lower:,.0f} y simultáneamente "
                               f"Q ≤ {band_flow_upper:,.0f} m³/h. La cantidad de bombas "
                               "por sí sola no corrige esa contradicción geométrica; "
                               "revise subzonas, secciones o la meta local antes de comprar.")
            near_target = [option.plan.active_modules for option in count_options
                           if option.slow_lap_nominal_min <= target_lap_min]
            if near_target:
                st.info("En las cantidades probadas, la primera que llega al tiempo de "
                        f"referencia de {target_lap_min:.1f} min bajo la hipótesis actual "
                        f"es **{min(near_target)} unidades activas**. No es una cantidad "
                        "aprobada para compra: compare también la fila conservadora, "
                        "velocidades locales y ubicación.")
            else:
                st.warning("Ninguna cantidad probada alcanza el tiempo de referencia bajo "
                           "la hipótesis actual. Amplíe el rango o revise geometría, "
                           "pérdidas y criterio de operación.")
            filter_duty = int(st.session_state["filtration_active_pumps"])
            st.caption(f"Tratamiento del mismo escenario: {plan.filtration_flow_m3_h:,.0f} "
                       f"m³/h deben pasar por filtros en {turnover_h:.1f} h; con "
                       f"{filter_duty} bombas activas de filtración, cada una tendría "
                       f"que entregar {plan.filtration_flow_m3_h / filter_duty:,.0f} "
                       "m³/h a la TDH con filtro sucio. Estas bombas no se suman a las "
                       "unidades Riverflow; su capacidad sigue pendiente de comprobación.")
            with st.expander("Ver posiciones y mapa de una cantidad comparada"):
                selected_count = st.selectbox(
                    "Unidades activas del mapa", counts_to_check,
                    index=counts_to_check.index(active_modules)
                    if active_modules in counts_to_check else 0)
                selected_option = next(option for option in count_options
                                       if option.plan.active_modules == selected_count)
                st.plotly_chart(make_map(model, selected_option.plan,
                                         field=selected_option.field),
                                width="stretch", key="rf_count_option_map")
                st.write("Progresivas propuestas en sentido antihorario (m): " +
                         ", ".join(f"{p:.0f}" for p in
                                   selected_option.plan.module_chainages_m))
            st.caption("0,5× y 2× son sensibilidad de una transferencia de energía no medida, "
                       "no un intervalo probable. El mapa 2D conserva caudal por sección, "
                       "pero no verifica chorros, playas ni seguridad; las posiciones "
                       "alternativas son propuestas para estudio, no planos de instalación.")
        st.markdown("**Comprobación física independiente del 2 % · límite optimista**")
        st.caption("Se compara el arrastre Manning a la vuelta objetivo con el máximo impulso "
                   "ideal de las descargas. Supone que TODA la TDH local se transforma en "
                   "velocidad de salida, sin pérdidas ni mezcla; no es CFD ni rendimiento real.")
        mb1, mb2 = st.columns(2)
        mb1.metric("Mínimo optimista de vuelta", f"{momentum_bound.optimistic_min_lap_min:.1f} min")
        mb2.metric("Parte del impulso ideal necesaria para la meta",
                   f"{momentum_bound.target_fraction_of_ideal:.1%}")
        if momentum_bound.target_fraction_of_ideal > 1:
            st.error("La meta exige más impulso que este máximo ideal bajo la geometría y "
                     "Manning elegidos: revisar la configuración antes de considerarla.")
        else:
            st.warning(f"La meta exigiría al menos {momentum_bound.target_fraction_of_ideal:.1%} "
                       "del impulso ideal. Estar por debajo de 100 % NO demuestra viabilidad: "
                       "faltan pérdidas de boquilla, mezcla, curvas y comportamiento de personas.")
        st.caption("Este límite no usa el 2 % y cambia con bombas, RPM, TDH local, ángulos, "
                   "Manning, profundidad y geometría. El porcentaje de impulso ideal NO se "
                   "compara directamente con el 2 % de energía: son magnitudes distintas. "
                   "Las velocidades junto a tomas y "
                   "descargas requieren un estudio de seguridad independiente.")
        with st.expander("Ver fuerzas y fórmula del límite optimista"):
            st.write(f"Impulso ideal de las descargas: {momentum_bound.ideal_thrust_n:,.0f} N. "
                     f"Resistencia Manning a la meta: {momentum_bound.target_drag_n:,.0f} N. "
                     "Se usa fuerza ideal por unidad = densidad × caudal de bomba × "
                     "√(2g × TDH local) × cos(ángulo); la resistencia del canal se integra "
                     "por secciones del DXF. Son fuerzas teóricas, no mediciones.")
        st.caption("Mismo DXF, profundidad, Manning, número y posición de unidades, RPM y horas de "
                   "filtración en los tres casos. Solo se varía la energía útil supuesta "
                   "(0,5× / 1× / 2×). Son pruebas ilustrativas, no límites medidos ni "
                   "probabilidades. Para variar K y RPM, use la matriz de «Escenarios».")
        cases = evaluate_decision_cases(
            model.stations, current_plan=plan, current_field=field,
            depth_m=depth_m, scale_m_per_unit=model.geometry.scale_m_per_unit,
            calm_zone_width_m=calm_width_m, floor_manning_n=floor_n,
            wall_manning_n_current=wall_n_current,
            wall_manning_n_calm=wall_n_calm, filtration_turnover_h=turnover_h,
            beach_geometry=beach_geometry)
        decision_rows = []
        for case in cases:
            if case.plan is None:
                decision_rows.append({
                    "Caso": case.name, "Energía útil supuesta (%)": round(transfer_pct * case.energy_factor, 2),
                    "Q descarga local (m³/h)": None, "Corriente longitudinal (m³/h)": None,
                    "Vuelta V/Q (min)": None, "Vuelta lenta 2D (min)": None,
                    "Lectura": "Sin punto dentro de la curva disponible"})
                continue
            slow_lap = case.slow_lap_min
            decision_rows.append({
                "Caso": case.name,
                "Energía útil supuesta (%)": round(100 * case.plan.transfer_fraction, 2),
                "Q descarga local (m³/h)": round(case.plan.installed_operating_flow_m3_h),
                "Corriente longitudinal (m³/h)": round(case.plan.equivalent_channel_flow_m3_h),
                "Vuelta V/Q (min)": round(case.plan.estimated_lap_min, 1),
                "Vuelta lenta 2D (min)": round(slow_lap, 1),
                "Lectura": ("Meta alcanzada bajo hipótesis" if slow_lap <= target_lap_min
                            else "Meta no alcanzada bajo hipótesis")})
        st.dataframe(decision_rows, width="stretch", hide_index=True)
        for case in cases:
            if case.error:
                st.warning(f"{case.name}: {case.error}")
        valid_cases = [case for case in cases if case.slow_lap_min is not None]
        if valid_cases:
            comparison = go.Figure()
            comparison.add_trace(go.Bar(
                x=[case.name for case in valid_cases],
                y=[case.slow_lap_min for case in valid_cases],
                marker_color=[{"Conservador": "#64748b", "Configuración actual": "#2563eb",
                               "Favorable": "#0d9488"}[case.name] for case in valid_cases],
                name="Trayectoria más lenta 2D"))
            comparison.add_hline(y=target_lap_min, line_dash="dash", line_color="#b91c1c",
                                 annotation_text=f"Meta {target_lap_min:.1f} min")
            comparison.update_layout(height=310, margin=dict(l=15, r=15, t=25, b=25),
                                     yaxis_title="Minutos por vuelta · escenario 2D",
                                     showlegend=False)
            st.plotly_chart(comparison, width="stretch")
        st.caption("La descarga local de las unidades NO es la corriente longitudinal del canal. "
                   "La trayectoria lenta proviene del campo 2D conceptual, no de CFD calibrado. "
                   "Una meta alcanzada aquí no autoriza comprar equipos.")

        st.markdown("**Tratamiento independiente del mismo escenario**")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Volumen calculado", f"{plan.volume_m3:,.0f} m³")
        d2.metric("Recirculación", f"{turnover_h:.1f} h")
        d3.metric("Q requerido por filtros", f"{filtration.required_flow_m3_h:,.0f} m³/h")
        d4.metric("Necesidad por bomba activa", f"{filtration.required_per_pump_m3_h:,.0f} m³/h")
        st.write("Capacidad de bombas con filtro sucio: **" + filtration.pump_status +
                 "** · contingencia N−1: **" + filtration.pump_n_minus_1_status +
                 "** · filtros: **" + filtration.filter_status + "**.")
        st.caption("'Dato requerido' significa que falta demostrar capacidad; no equivale a cero "
                   "ni a aprobación. El agua de pozo solo repone pérdidas y llenado, "
                   "no el caudal de recirculación.")

        st.markdown("**Origen de los datos y límite de uso**")
        st.dataframe([
            {"Dato": "Longitud y anchos", "Origen": "DXF cargado y escala elegida",
             "Uso": "Geometría preliminar; cotas sumergidas pendientes"},
            {"Dato": "Curva local y motor de 10 HP", "Origen": "Imagen/ficha Riverflow",
             "Uso": "Anclas publicadas; puntos intermedios y RPM parciales aproximados"},
            {"Dato": "Manning, K, longitudes y energía útil", "Origen": "Entradas e hipótesis NYA",
             "Uso": "Sensibilidad; no medición ni garantía de vuelta"},
            {"Dato": "Capacidad de filtración", "Origen": "Fichas a TDH con filtro sucio, si se ingresan",
             "Uso": "Sin curva comprobada, no cerrar selección ni N−1"},
        ], width="stretch", hide_index=True)
        st.markdown("**Comprobación de coherencia de esta configuración**")
        checks = consistency_checks(plan, turnover_h)
        st.dataframe([{"Relación": label, "Resultado": "Coincide" if ok else "Revisar cálculo"}
                      for label, ok in checks], width="stretch", hide_index=True)
        if all(ok for _, ok in checks):
            st.info("Las cuatro relaciones aritméticas coinciden para los datos actuales. "
                    "Esto comprueba consistencia interna, no exactitud física.")
        else:
            st.error("Hay una inconsistencia aritmética. No usar este escenario para decisiones.")

    with tab_equipment:
        st.subheader("Unidades de propulsión")
        rows = [{"Unidad": f"RF-{i:02d}", "Recorrido (m)": round(position, 1),
                 "Margen": plan.module_banks[i-1],
                 "Q estimado a velocidad elegida (m³/h)": round(plan.module_flows_full_speed_m3_h[i-1] * speed_pct / 100, 1),
                 "Motor de placa (HP)": RIVERFLOW_MOTOR_HP, "Salida": nozzle_type}
                for i, position in enumerate(plan.module_chainages_m, 1)]
        st.dataframe(rows, width="stretch", hide_index=True)
        st.download_button("Descargar listado CSV", make_csv(plan, nozzle_type),
                           file_name="nya_riverflow_unidades.csv", mime="text/csv")
        e1, e2, e3 = st.columns(3)
        e1.metric("Unidades activas", str(active_modules))
        e2.metric("Reserva", str(standby_modules))
        e3.metric("HP de placa adquiridos", f"{plan.total_motor_nameplate_hp:.0f} HP")
        st.markdown("**Infraestructura prevista**")
        st.markdown(
            "- **Estaciones mecánicas locales:** base o bóveda accesible para bomba y motor, "
            "dos tomas de succión protegidas según el plano de referencia, descarga, "
            "válvulas, elevación, drenaje y ventilación según Riverflow.\n"
            "- **Área eléctrica protegida:** tableros, variadores ABB, protecciones y control; "
            "alimentación y demanda por definir con el ingeniero eléctrico.\n"
            f"- **Planta de tratamiento independiente:** bombas, filtros, desinfección, "
            f"control de pH, instrumentación, retrolavado y tanque de compensación; "
            f"dimensionamiento preliminar {plan.filtration_flow_m3_h:,.0f} m³/h "
            f"para un recambio supuesto de {turnover_h:.1f} h."
        )
        st.caption("Las unidades de reserva no aportan caudal al escenario. Su ubicación de almacenamiento "
                   "o instalación queda pendiente del plan de redundancia.")
        st.caption("El plano 'Espada Amenity' recibido de Riverflow muestra como referencia una bomba vertical, "
                   "dos tomas de succión, piezas de tubería, descarga, variador y requisitos de "
                   "elevación/drenaje. Ya se aprovecha como base de componentes; es otro proyecto: "
                   "sus cotas y disposición no se transfieren a NYA sin un plano específico aprobado.")

    with tab_plans:
        st.subheader("Planos Riverflow · aplicación preliminar a NYA")
        st.info("Los documentos son instalaciones de referencia del fabricante, no planos de construcción "
                "aprobados para NYA. La geometría DXF y los resultados hidráulicos existentes no se "
                "modifican por consultar esta sección.")
        st.markdown("**1. Sistema de 4 ft (1,22 m) · referencia más próxima a la profundidad elegida**")
        st.link_button("Abrir plano original de 4 ft y 7 puertos", RIVERFLOW_4FT_PLAN_URL)
        st.plotly_chart(make_installation_schematic(), width="stretch", key="rf_plan_installation")
        st.caption("Esquema propio, sin escala: las dos ramas de toma, colector, bomba, retorno y boquilla "
                   "siguen la topología del plano. Los diámetros son nominales de esa referencia; las "
                   "longitudes, cotas y pérdidas de NYA siguen sin definirse.")
        st.markdown("**2. Boquilla de 7 puertos · orientación y montaje**")
        st.link_button("Abrir plano original de boquilla", RIVERFLOW_NOZZLE_PLAN_URL)
        st.caption("El documento ilustra orientación y posición de montaje. No publica un K hidráulico "
                   "para comparar la salida de 7 puertos con el manifold de 3 puertos. Las cotas de "
                   "montaje varían entre referencias; no se fijan automáticamente en NYA.")
        st.markdown("**3. Instalación eléctrica · motor y variador**")
        st.link_button("Abrir guía eléctrica original", RIVERFLOW_ELECTRICAL_GUIDE_URL)
        st.caption("El variador requiere ubicación protegida y ventilada. Los esquemas eléctricos del "
                   "fabricante no sustituyen la selección de alimentación, protecciones ni normativa "
                   "aplicable al emplazamiento en Costa Rica; 10 HP de placa no son consumo medido.")
        with st.expander("Comparativo: variante de 3 ft (0,91 m)"):
            st.link_button("Abrir plano original de 3 ft", RIVERFLOW_3FT_PLAN_URL)
            st.caption("Sirve para comparar disposición, no para adoptar sus cotas en el río de 1,2 m.")

        st.subheader("Auditoría de cálculos que aún faltan")
        st.dataframe(documentation_calculation_audit(
            suction_length_m=suction_length, discharge_length_m=discharge_length,
            suction_k=suction_k, discharge_k=discharge_k, outlet_k=outlet_k,
            transfer_pct=transfer_pct, nozzle_type=nozzle_type, nozzle_cd=nozzle_cd,
        ), width="stretch", hide_index=True)
        st.warning("Los planos y la carta Brannon aportan puntos de operación de referencia, "
                   "no longitudes ni pérdidas confirmadas para NYA. Elegir esa referencia sí "
                   "cambia el caudal, TDH y vuelta del escenario activo; el 2 % de energía "
                   "útil y el consumo eléctrico real continúan sin calibración.")
        st.caption("La filtración permanece como sistema separado. La prueba hidrostática publicada "
                   "por Riverflow aplica a un circuito de propulsión abierto de baja presión; "
                   "no valida la planta de tratamiento ni un circuito presurizado cerrado.")

    with tab_references:
        st.subheader("Auditoría de datos Riverflow usados en NYA")
        st.dataframe([
            {"Dato": "CF104 no reversible", "Fuente": "Registro NSF vigente",
             "Uso en el modelo": "Identificación y límite de certificación, no caudal garantizado"},
            {"Dato": "2440 US GPM a 4 ft; 1220 US GPM a 10 ft",
             "Fuente": "Curva H–Q facilitada por Riverflow",
             "Uso en el modelo": "Dos anclas; puntos intermedios del JPG son aproximados"},
            {"Dato": "2014 GPM a 6.5 ft · Sch 40; 1988 GPM a 6.7 ft · Sch 80",
             "Fuente": "C.T. Brannon, RiverFlow Flow Rates, 09/12/2025",
             "Uso en el modelo": "Referencias seleccionables de doble succión y 7 puertos; no son NYA"},
            {"Dato": "Acelerador 12 × 7: área abierta 0,2892 ft²",
             "Fuente": "C.T. Brannon, RiverFlow Flow Rates, 09/12/2025",
             "Uso en el modelo": "Q/área para velocidad de salida; K equivalente solo con Cd supuesto"},
            {"Dato": "RFS 200: 2440 US GPM por toma certificada",
             "Fuente": "NSF, Product Listing Details Suction Box, 10/2026",
             "Uso en el modelo": "Comprobación preliminar de caudal con una toma obstruida"},
            {"Dato": "Motor 10 HP y variador ABB", "Fuente": "Página de componentes Riverflow",
             "Uso en el modelo": "HP de placa, nunca kW consumidos ni curva de rendimiento"},
            {"Dato": "Dos tomas, 7 puertos, PVC Sch 40 nominal 12″",
             "Fuente": "Plano genérico Riverflow de 3 ft",
             "Uso en el modelo": "Topología de referencia; no define el trazado NYA"},
            {"Dato": "Diámetro interior 12″ Sch 40 ≈ 0.303 m",
             "Fuente": "Ficha Westlake, 11.938″",
             "Uso en el modelo": "Valor inicial editable; no fija proveedor ni diámetro NYA"},
            {"Dato": "Curvas a varias RPM, potencia eléctrica, K de boquilla y tomas",
             "Fuente": "No publicados para la instalación NYA",
             "Uso en el modelo": "Afinidad y K solo como sensibilidad; sin kWh ni compra recomendada"},
        ], width="stretch", hide_index=True)
        st.markdown("[Curva publicada por Riverflow](https://riverflowpumps.com/technical/riverflow-pump-curve/) · "
                    "[Componentes Riverflow](https://riverflowpumps.com/technical/what-the-system-includes/) · "
                    "[Plano genérico Riverflow](https://riverflowpumps.com/wp-content/uploads/LAZY%20RIVER%207-PORT%20NOZZLE%20PLUMBING%20DRAWINGS/LAZY-RIVER-3-FT-DEPTH-7PN-DOUBLE-SUCTION-.pdf) · "
                    "[Ficha de diámetro Westlake](https://www.westlakepipe.com/sites/default/files/PL-PS-025-CA-EN-0522.1_Sch40-Sch80-Pressure-Pipe.pdf) · "
                    "[Registro NSF](https://info.nsf.org/Certified/Pools/Listings.asp?TradeName=riverflow)")
        st.caption("El caudal de diseño 2440 GPM que figura para la salida de succión en NSF "
                   "NO es una segunda curva de la bomba ni debe sumarse por cada rejilla. "
                   "Además, un FAQ de Riverflow indica 80 pies en inglés y 80 metros en español "
                   "para separación de la bomba: por esa contradicción NO se usa como límite "
                   "de diseño ni sustituye la curva de pérdidas de cada circuito.")
        st.subheader("Comparación de configuraciones Riverflow")
        def units_for_head(head_ft):
            one_unit_flow = scenario_channel_flow_m3_h(
                plan.channel_resistance_s2_m5,
                riverflow_flow_at_head_ft(head_ft, plan.curve_mode),
                1, plan.speed_fraction, plan.transfer_fraction,
                plan.placement_effectiveness)
            return ceil((plan.target_equivalent_flow_m3_h / one_unit_flow) ** 3)
        st.dataframe([
            {"Escenario": "NYA · hipótesis 4 ft", "Longitud conocida": f"{plan.length_m:.0f} m desde DXF",
             "Q por unidad": "554 m³/h", "Unidades para meta":
             f"{units_for_head(4)} aprox.",
             "Alcance del dato": "Sensibilidad Manning; energía útil y TDH sin verificar"},
            {"Escenario": "NYA · hipótesis 10 ft", "Longitud conocida": f"{plan.length_m:.0f} m desde DXF",
             "Q por unidad": "277 m³/h", "Unidades para meta":
             f"{units_for_head(10)} aprox.",
             "Alcance del dato": "Sensibilidad Manning; energía útil y TDH sin verificar"},
            {"Escenario": "Espada Amenity · plano recibido", "Longitud conocida": "No indicada",
             "Q por unidad": "No indicado en el plano", "Unidades para meta": "No comparable",
             "Alcance del dato": "Detalle constructivo de otro proyecto, 3.5 ft de profundidad"},
            {"Escenario": "Gator Grounds · referencia pública", "Longitud conocida": "301 ft ≈ 92 m",
             "Q por unidad": "No publicado para ese proyecto", "Unidades para meta": "No comparable",
             "Alcance del dato": "Longitud publicada; sin cantidad ni TDH de bombas"},
            {"Escenario": "AquaNick Riviera Maya · referencia pública", "Longitud conocida": "No publicada",
             "Q por unidad": "No publicado para ese proyecto", "Unidades para meta": "No comparable",
             "Alcance del dato": "Riverflow confirma uso, sin datos hidráulicos comparables"},
            {"Escenario": "Typhoon Texas · referencia pública", "Longitud conocida": "No publicada",
             "Q por unidad": "No publicado para ese proyecto", "Unidades para meta": "No comparable",
             "Alcance del dato": "Contratista confirma uso de Riverflow; sin datos de diseño comparables"},
        ], width="stretch", hide_index=True)
        st.caption("Los conteos NYA son aritméticos bajo las hipótesis actuales, no diseños de esos "
                   "proyectos. Falta una medición de corriente y una curva de sistema para comparar desempeño.")
        st.markdown("Fuentes externas: [Gator Grounds (Riverflow)](https://riverflowpumps.com/aqua-magazine-a-fiberglass-lazy-river/) · "
                    "[AquaNick (Riverflow)](https://riverflowpumps.com/commercial-projects/) · "
                    "[Typhoon Texas (testimonio publicado por Riverflow)](https://riverflowpumps.com/testimonials/contractors/) · "
                    "[Componentes del sistema](https://riverflowpumps.com/technical/what-the-system-includes/).")
        st.caption("Para comparar de verdad con NYA se necesitan, como mínimo, longitud, perfil de anchos "
                   "y profundidad, número de módulos, TDH local, velocidad medida, tiempo de vuelta "
                   "y caudal filtrado. No se infieren estos valores de fotografías o testimonios.")
        st.subheader("Cómo se integra un módulo en el río")
        st.plotly_chart(make_installation_schematic(), width="stretch")
        st.caption("Esquema funcional, no plano de construcción: toma doble protegida → bomba local → "
                   "descarga orientada con la corriente. Se debe resolver acceso, drenaje, ventilación, "
                   "electricidad, cotas y seguridad de succión por cada estación.")
        st.subheader("Documentos recibidos")
        st.image(os.path.join(ASSET_DIR, "riverflow_pump_curve.jpg"),
                 caption="Curva H–Q facilitada por Riverflow: CF104, 2,440 US GPM a 4 ft y 1,220 US GPM a 10 ft.",
                 width="stretch")
        st.image(os.path.join(ASSET_DIR, "riverflow_espada_reference.jpeg"),
                 caption="Plano recibido: Espada Amenity, bomba #2 (hoja 3 de 9). Referencia constructiva de otro proyecto; no es un plano aprobado para NYA.",
                 width="stretch")

    st.markdown("**Datos de la curva facilitada por Riverflow:** "
                f"{RIVERFLOW_RATED_GPM:,.0f} US GPM ≈ {RIVERFLOW_RATED_M3_H:.1f} m³/h a 4 ft; "
                "1,220 US GPM ≈ 277.1 m³/h a 10 ft; "
                f"motor de {RIVERFLOW_MOTOR_HP:.0f} HP por unidad. "
                "[Sistema Riverflow](https://riverflowpumps.com/technical/what-the-system-includes/) · "
                "[Curva publicada](https://riverflowpumps.com/technical/riverflow-pump-curve/) · "
                "[Registro NSF](https://info.nsf.org/Certified/Pools/Listings.asp?TradeName=riverflow).")
    st.caption("Modelo preliminar de fase 1 para comparar escenarios; no sustituye diseño hidráulico, "
               "eléctrico, sanitario o de seguridad del proyecto.")
