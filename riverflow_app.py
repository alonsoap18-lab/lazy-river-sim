"""Riverflow-focused Phase-1 Streamlit interface for the NYA DXF geometry."""

import csv
import io
import os
from math import ceil

import numpy as np
import plotly.graph_objects as go
from plotly.colors import sample_colorscale
import streamlit as st

from core.orchestrator import LazyRiverModel
from core.centerline import signed_centerline_area
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


MODEL_VERSION = "riverflow-coupled-manning-heatmap-6"
ASSET_DIR = os.path.join(os.path.dirname(__file__), "assets")


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


def add_velocity_areas(fig, model, plan):
    """Color DXF-derived cross-section strips; uniform across width, not CFD."""
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


def make_map(model, plan, show_installation=True, show_velocity_heatmap=True):
    fig = go.Figure()
    if show_velocity_heatmap:
        add_velocity_areas(fig, model, plan)
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
        index = min(range(len(model.stations)),
                    key=lambda i: abs(model.stations[i]["chainage_m"] - position))
        station = model.stations[index]
        previous = model.stations[max(0, index - 1)]
        following = model.stations[min(len(model.stations) - 1, index + 1)]
        tx = following["x"] - previous["x"]
        ty = following["y"] - previous["y"]
        norm = (tx ** 2 + ty ** 2) ** 0.5 or 1.0
        tx, ty = tx / norm, ty / norm
        nx, ny = -ty, tx
        width = float(station["width_m"])
        px = station["x"] + nx * (width / 2 + 2) / scale
        py = station["y"] + ny * (width / 2 + 2) / scale
        sx = station["x"] - tx * 1.2 / scale + nx * width * 0.3 / scale
        sy = station["y"] - ty * 1.2 / scale + ny * width * 0.3 / scale
        ox = station["x"] + tx * 1.2 / scale + nx * width * 0.3 / scale
        oy = station["y"] + ty * 1.2 / scale + ny * width * 0.3 / scale
        labels.append(f"RF-{number:02d} · {position:.0f} m")
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
            flow_x.extend([ox, ox + tx * 3 / scale, None])
            flow_y.extend([oy, oy + ty * 3 / scale, None])
            if number == 1 or number % 4 == 0:
                fig.add_annotation(x=ox + tx * 3 / scale, y=oy + ty * 3 / scale,
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
    fig.add_trace(go.Scatter(
        x=pump_x if show_installation else
        [model.stations[min(range(len(model.stations)),
                            key=lambda i: abs(model.stations[i]["chainage_m"] - p))]["x"]
         for p in plan.module_chainages_m],
        y=pump_y if show_installation else
        [model.stations[min(range(len(model.stations)),
                            key=lambda i: abs(model.stations[i]["chainage_m"] - p))]["y"]
         for p in plan.module_chainages_m],
        mode="markers", name="Estación Riverflow propuesta",
        marker=dict(size=10, color="#ea580c", symbol="diamond",
                    line=dict(color="white", width=1)),
        text=labels, hovertemplate="%{text}<extra></extra>",
    ))
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
                      xaxis_title="Recorrido horario desde origen DXF (m)",
                      yaxis_title="Pérdida acumulada de canal (m)")
    return fig


def make_installation_schematic():
    """Topology-only diagram; positions and pipe lengths are not design dimensions."""
    fig = go.Figure()
    fig.add_shape(type="rect", x0=0, y0=0, x1=10, y1=3,
                  fillcolor="#dbeafe", line=dict(color="#60a5fa"))
    fig.add_trace(go.Scatter(x=[1.5, 1.5, 5, 7.5], y=[1.5, 3.3, 3.3, 1.5],
                             mode="lines", name="Circuito local",
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
    fig.add_annotation(x=5, y=4.25, text="Variador y tableros en área eléctrica protegida",
                       showarrow=False)
    fig.add_annotation(x=5, y=0.4, text="Agua del río · sin cotas de NYA",
                       showarrow=False)
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=15, b=10),
                      xaxis=dict(visible=False, range=[-0.5, 10.5]),
                      yaxis=dict(visible=False, range=[-0.5, 4.6], scaleanchor="x"),
                      legend=dict(orientation="h", y=-0.08))
    return fig


def make_count_chart(plan):
    counts = list(range(1, 61))
    times = [plan.volume_m3 * 60 / scenario_channel_flow_m3_h(
        plan.channel_resistance_s2_m5, plan.module_flow_full_speed_m3_h,
        count, plan.speed_fraction,
        plan.transfer_fraction) for count in counts]
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


def simulated_positions(stations, depth_m, time_phases):
    """Positions along a Q/A travel-time coordinate; not a CFD particle model."""
    cumulative_volume = [0.0]
    for previous, current in zip(stations, stations[1:]):
        ds = float(current["chainage_m"] - previous["chainage_m"])
        mean_width = (float(previous["width_m"]) + float(current["width_m"])) / 2
        cumulative_volume.append(cumulative_volume[-1] + ds * mean_width * depth_m)
    if cumulative_volume[-1] <= 0:
        raise ValueError("No se puede animar un recorrido sin volumen positivo.")
    fractions = np.asarray(cumulative_volume) / cumulative_volume[-1]
    phases = np.mod(np.asarray(time_phases, dtype=float), 1.0)
    return (np.interp(phases, fractions, [s["x"] for s in stations]),
            np.interp(phases, fractions, [s["y"] for s in stations]))


def make_fast_simulation(model, plan, playback_multiplier):
    """Animate one conceptual Q/A lap over the same longitudinal heatmap."""
    frame_count = 72
    rider_count = 8
    frame_ms = max(30, round(plan.estimated_lap_min * 60_000 /
                             (playback_multiplier * frame_count)))
    initial_phases = np.arange(rider_count) / rider_count
    x0, y0 = simulated_positions(model.stations, 1.0, initial_phases)
    # The normalized cumulative volume does not depend on the uniform depth;
    # use the scenario depth-independent fraction directly through depth=1.
    fig = go.Figure()
    add_velocity_areas(fig, model, plan)
    fig.add_trace(go.Scatter(x=[s["x"] for s in model.stations],
                             y=[s["y"] for s in model.stations], mode="lines",
                             name="Centro del canal · horario",
                             line=dict(color="#334155", width=1)))
    fig.add_trace(go.Scatter(x=x0, y=y0, mode="markers", name="Flotadores conceptuales",
                             marker=dict(size=13, color="#f97316", line=dict(color="white", width=1))))
    rider_trace = len(fig.data) - 1
    frames = []
    for frame in range(frame_count):
        phases = (initial_phases + frame / frame_count) % 1.0
        xs, ys = simulated_positions(model.stations, 1.0, phases)
        frames.append(go.Frame(name=str(frame), data=[go.Scatter(x=xs, y=ys,
                           mode="markers", marker=dict(size=13, color="#f97316",
                                                       line=dict(color="white", width=1)),
                           text=[f"Flotador {i+1}" for i in range(rider_count)],
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
    writer.writerow(["Unidad", "Chainage_m", "Caudal_nominal_a_velocidad_m3h",
                     "Motor_placa_HP", "Salida", "Estado"])
    flow_per_active = plan.module_flow_full_speed_m3_h * plan.speed_fraction
    for i, chainage in enumerate(plan.module_chainages_m, 1):
        writer.writerow([f"RF-{i:02d}", f"{chainage:.1f}", f"{flow_per_active:.1f}",
                         f"{RIVERFLOW_MOTOR_HP:.0f}", nozzle_type, "Activa"])
    for i in range(plan.standby_modules):
        writer.writerow([f"RES-{i+1:02d}", "Por definir", 0,
                         f"{RIVERFLOW_MOTOR_HP:.0f}", nozzle_type, "Reserva"])
    return output.getvalue().encode("utf-8-sig")


def main():
    st.markdown("<h1 style='color:#2563eb;text-align:center'>Selvatura NYA · Lazy River / Riverflow</h1>",
                unsafe_allow_html=True)
    st.caption("Fase 1 · recorrido horario · geometría DXF y dimensionamiento conceptual de propulsión, filtración e infraestructura")

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
    if signed_centerline_area(model.stations) >= 0:
        st.error("No se pudo confirmar el sentido horario del DXF.")
        st.stop()

    st.sidebar.header("Unidades Riverflow")
    target_lap_min = st.sidebar.number_input("Objetivo de tiempo por vuelta (min)",
                                             5.0, 120.0, 40.0, 0.5)
    active_modules = st.sidebar.number_input("Unidades activas", 1, 60, 19, 1)
    standby_modules = st.sidebar.number_input("Unidades de reserva", 0, 10, 1, 1,
                                              help="No aportan caudal mientras están apagadas.")
    local_head_ft = st.sidebar.number_input(
        "TDH local estimada por unidad a plena velocidad (ft)", 4.0, 10.0, 4.0, 0.5,
        help="Escenario de carga en el circuito local de una bomba, NO la TDH de una red central. "
             "Se interpola dentro de la curva recibida según el método elegido. "
             "Debe confirmarse con Riverflow para NYA.")
    curve_choice = st.sidebar.selectbox(
        "Lectura de curva H–Q", ["Puntos visibles de la imagen · aproximados",
                                   "Solo 2 puntos rotulados · interpolación lineal"],
        help="La imagen contiene puntos intermedios sin tabla numérica. Su digitalización es aproximada; "
             "los puntos rotulados de 4 y 10 ft son exactos y no se extrapola fuera de ellos.")
    curve_mode = "photo" if curve_choice.startswith("Puntos") else "anchors"
    speed_pct = st.sidebar.slider("Velocidad del variador (%)", 50, 100, 100, 1,
                                  help="Q proporcional a RPM es una aproximación; la curva H–Q real determina el caudal.")
    transfer_pct = st.sidebar.slider(
        "Energía útil para mover el río (%)", 0.5, 20.0, 2.0, 0.5,
        help="Hipótesis NO medida: fracción de la potencia hidráulica de las bombas que termina "
             "sosteniendo la corriente longitudinal tras pérdidas locales, boquillas y mezcla. "
             "2% es solo un punto de prueba, no un dato de Riverflow.")
    nozzle_type = st.sidebar.selectbox("Salida propuesta", ["7 puertos", "Manifold de 3 puertos"],
                                       help="La selección queda registrada; faltan pérdidas y dimensiones de la boquilla para diferenciar su efecto hidráulico.")
    placement_mode = st.sidebar.radio("Ubicación de unidades", ["Automática", "Editar por recorrido (m)"],
                                      help="La ubicación automática evita las entradas a playa.")
    manual_positions = None
    if placement_mode == "Editar por recorrido (m)":
        eligible = [station for station in model.stations
                    if station["width_m"] < calm_width_m] or model.stations
        initial = [eligible[round((i + 0.5) * (len(eligible) - 1) / active_modules)]["chainage_m"]
                   for i in range(active_modules)]
        text = st.sidebar.text_area("Posición de cada unidad, separada por coma",
                                    value=", ".join(f"{x:.0f}" for x in initial),
                                    key=f"riverflow_positions_{active_modules}", height=100)
        try:
            manual_positions = parse_chainages(text, model.geometry.channel_length_m)
        except ValueError as exc:
            st.sidebar.error(str(exc))
            st.stop()

    st.sidebar.header("Tratamiento separado")
    turnover_h = st.sidebar.number_input("Recirculación de filtración (h)",
                                         2.0, 12.0, 4.0, 0.5)

    try:
        plan = compute_riverflow_plan(
            model.stations, depth_m=depth_m, target_lap_min=target_lap_min,
            active_modules=active_modules, standby_modules=standby_modules,
            module_head_full_speed_ft=local_head_ft,
            speed_fraction=speed_pct / 100, transfer_fraction=transfer_pct / 100,
            calm_zone_width_m=calm_width_m, filtration_turnover_h=turnover_h,
            floor_manning_n=floor_n, wall_manning_n_current=wall_n_current,
            wall_manning_n_calm=wall_n_calm, curve_mode=curve_mode,
            module_chainages_m=manual_positions)
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

    st.info("El caudal por Riverflow proviene de la curva H–Q recibida: los dos extremos rotulados "
            "son datos exactos y los puntos intermedios leídos de la imagen son aproximados. "
            "Manning ahora interviene en la corriente y el tiempo de vuelta mediante un balance "
            "energético conceptual. La fracción de energía útil (2% inicial), la TDH instalada y "
            "las pérdidas locales NO están medidas: el resultado es sensibilidad, no desempeño garantizado.")

    st.subheader("Resultado del escenario")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Meta de vuelta", f"{plan.target_lap_min:.1f} min")
    c2.metric("Vuelta estimada", f"{plan.estimated_lap_min:.1f} min")
    c3.metric("Caudal de unidades", f"{plan.installed_operating_flow_m3_h:,.0f} m³/h")
    c4.metric("Corriente longitudinal · escenario", f"{plan.equivalent_channel_flow_m3_h:,.0f} m³/h")
    c5.metric("Velocidad de recorrido", f"{plan.velocity_lap_m_s:.3f} m/s")
    if plan.estimated_lap_min <= plan.target_lap_min:
        st.info(f"Este escenario de sensibilidad cumple la meta con {active_modules} unidades; "
                f"estimación matemática: {plan.required_active_modules} activas. "
                "No utilices esa cantidad para compra: la energía útil, las pérdidas y el punto "
                "de operación no están calibrados para NYA.")
    else:
        st.warning(f"Bajo la energía útil supuesta, el balance conceptual estima "
                   f"{plan.required_active_modules} unidades activas para {target_lap_min:.1f} min. "
                   "No es una selección de equipos validada.")

    g1, g2, g3, g4, g5 = st.columns(5)
    g1.metric("Volumen desde DXF", f"{plan.volume_m3:,.0f} m³")
    g2.metric("Q requerido para meta", f"{plan.target_equivalent_flow_m3_h:,.0f} m³/h")
    g3.metric("Motores activos · placa", f"{plan.active_motor_nameplate_hp:.0f} HP")
    g4.metric("Filtración separada", f"{plan.filtration_flow_m3_h:,.0f} m³/h")
    g5.metric("Q por unidad según curva", f"{plan.module_flow_full_speed_m3_h:,.0f} m³/h",
              help=f"Interpolado a {local_head_ft:.1f} ft ({local_head_ft * 0.3048:.2f} m) de TDH local estimada, a plena velocidad.")

    (tab_map, tab_explain, tab_hydraulic, tab_fast, tab_treatment,
     tab_equipment, tab_references) = st.tabs(
        ["Plano 2D", "Explicación", "Hidráulica", "Simulador rápido",
         "Tratamiento de agua", "Equipos", "Referencias"])

    with tab_map:
        st.info("Circulación definida: sentido horario. El origen del recorrido es el punto inicial del DXF; "
                "las posiciones editables en metros aumentan en ese sentido.")
        show_installation = st.checkbox("Mostrar montaje conceptual: bomba, tomas y descarga", value=True)
        show_heatmap = st.checkbox("Colorear zonas según velocidad Q/A", value=True)
        st.plotly_chart(make_map(model, plan, show_installation, show_heatmap), width="stretch")
        st.caption("Mapa de velocidad longitudinal equivalente por sección: azul = menor, rojo = mayor. "
                   "Cada franja se colorea uniformemente a lo ancho; NO representa remolinos, "
                   "gradientes laterales, corrientes cerca de playas ni un resultado CFD.")
        st.caption("Naranja: bomba local propuesta en una margen. Azul: dos tomas de succión. Verde: "
                   "descarga y dirección tentativa. Las conexiones son símbolos esquemáticos; "
                   "no representan cotas, diámetros, orientación definitiva ni alcance hidráulico. "
                   "Riverflow debe aprobar ubicación y detalle para NYA.")
        st.metric("Longitud del circuito", f"{plan.length_m:.0f} m")
        z1, z2 = st.columns(2)
        z1.metric("Canal de corriente", f"{plan.current_zone_length_m:.0f} m")
        z2.metric("Entradas a playa / zonas calmas", f"{plan.calm_zone_length_m:.0f} m")
        st.metric("Mayor distancia de canal a una unidad", f"{plan.max_current_distance_to_module_m:.0f} m",
                  help="Distancia más larga, medida sobre el recorrido cerrado, desde una sección de corriente hasta la unidad activa más cercana. Cambia al mover unidades; no equivale a alcance hidráulico de la descarga.")

    with tab_explain:
        st.subheader("Cómo leer este escenario")
        st.markdown(
            f"1. **Plano y agua:** el DXF fija el recorrido horario de {plan.length_m:.0f} m "
            f"y los anchos variables. Con {depth_m:.2f} m de profundidad, el volumen aproximado "
            f"es {plan.volume_m3:,.0f} m³.\n"
            f"2. **Cada bomba:** la curva Riverflow da {plan.module_flow_full_speed_m3_h:,.0f} m³/h "
            f"por unidad a la TDH local supuesta de {local_head_ft:.1f} ft y plena velocidad.\n"
            f"3. **Movimiento del río:** {active_modules} unidades dan "
            f"{plan.installed_operating_flow_m3_h:,.0f} m³/h de descarga local estimada; "
            f"con {transfer_pct:.1f}% de energía hidráulica útil supuesta y la resistencia "
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
        st.markdown("**Referencia ya recibida:** plano de montaje y curva H–Q en imagen. "
                    "**Faltan para cerrar el diseño NYA:** cotas y recorridos reales por estación, "
                    "pérdidas de succión/descarga, curvas a velocidades parciales o datos eléctricos "
                    "certificados, prueba de circulación o CFD y diseño sanitario independiente.")

    with tab_hydraulic:
        st.subheader("Fricción del canal · Manning")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("n compuesto local mín–máx", f"{min(plan.station_manning_n):.3f}–{max(plan.station_manning_n):.3f}",
                  help="Piso y dos paredes ponderados por perímetro mojado en cada sección rectangular.")
        m2.metric("Pérdida canal · escenario", f"{plan.channel_friction_head_m:.3f} m")
        m3.metric("Pérdida canal · meta", f"{plan.target_channel_friction_head_m:.3f} m")
        m4.metric("Froude equivalente máx.", f"{plan.max_froude:.2f}")
        st.plotly_chart(make_friction_profile(model, plan), width="stretch")
        st.caption("Se calcula la pendiente de fricción de Manning en cada tramo del DXF con "
                   "ancho local, profundidad, piso liso y paredes con el acabado propuesto. El n "
                   "compuesto se pondera por perímetro mojado según HEC-RAS. El balance "
                   "Pútil = ρg·Qcorriente·Hfricción vincula n, caudal y vuelta. Es una "
                   "sensibilidad condicionada al porcentaje de energía útil, no una solución "
                   "validada de las bombas ni del campo de velocidades.")
        st.markdown("[Base técnica del n compuesto (HEC-RAS)](https://www.hec.usace.army.mil/confluence/rasdocs/ras1dtechref/6.4/theoretical-basis-for-one-dimensional-and-two-dimensional-hydrodynamic-calculations/1d-steady-flow-water-surface-profiles/composite-manning-s-n-for-the-main-channel)")
        q1, q2 = st.columns(2)
        q1.metric("Tiempo en canal de corriente", f"{plan.current_lap_min:.1f} min")
        q2.metric("Tiempo en entradas a playa", f"{plan.calm_lap_min:.1f} min")
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
        st.caption("Velocidad de recorrido = longitud / tiempo estimado. Las velocidades por sección "
                   "son equivalentes Q/A, no mediciones ni un campo CFD; cambian con el ancho del DXF.")
        st.plotly_chart(make_count_chart(plan), width="stretch")
        st.markdown("**Sensibilidad a la energía útil no medida**")
        sensitivity_rows = []
        for percent in (0.5, 1.0, 2.0, 5.0):
            q_scenario = scenario_channel_flow_m3_h(
                plan.channel_resistance_s2_m5, plan.module_flow_full_speed_m3_h,
                plan.active_modules, plan.speed_fraction, percent / 100)
            q_one = scenario_channel_flow_m3_h(
                plan.channel_resistance_s2_m5, plan.module_flow_full_speed_m3_h,
                1, plan.speed_fraction, percent / 100)
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
                {"Dato editable": "TDH local estimada", "Afecta": "Q por bomba, Q total, vuelta, velocidades y unidades requeridas",
                 "Estado": "Curva H–Q desde JPG aproximado o dos anclas; no es un punto instalado"},
                {"Dato editable": "Variador y energía útil", "Afecta": "Corriente, vuelta, velocidades y fricción",
                 "Estado": "Leyes de afinidad aproximadas; energía útil no medida"},
                {"Dato editable": "Ubicación y tipo de salida", "Afecta": "Plano, distancias y listado de equipos",
                 "Estado": "Sin modelo de alcance, pérdidas de boquilla ni CFD"},
                {"Dato editable": "Recambio de filtración", "Afecta": "Caudal de tratamiento separado",
                 "Estado": "No se suma al caudal de propulsión"},
            ], width="stretch", hide_index=True)
        st.warning("La TDH ingresada no está calculada para NYA. Caudal a velocidad parcial ≈ caudal "
                   "a plena velocidad × porcentaje del variador es una aproximación de escenario, "
                   "no un punto verificado de la curva. Potencia eléctrica y velocidad de salida "
                   "requieren dimensiones de tomas/salidas, trazado local y validación del fabricante. "
                   "La placa de 10 HP no es el consumo instantáneo. No seleccionar bombas con "
                   "la cantidad calculada hasta calibrar energía útil y pérdidas de cada instalación.")
        st.markdown("**Datos indispensables para decidir:** (1) perfiles y cotas del DXF de NYA, "
                    "profundidad real y niveles de agua; (2) planos de cada módulo con diámetros, "
                    "longitudes, accesorios y salida elegida; (3) curva H–Q y potencia a varias RPM "
                    "confirmadas por Riverflow; (4) ensayo, prototipo o CFD calibrado de empuje y "
                    "velocidad en zonas estrechas, curvas y entradas a playa; (5) acabado final y "
                    "rugosidad; (6) diseño sanitario/filtración independiente y aforo de usuarios.")

    with tab_fast:
        st.subheader("Vuelta conceptual acelerada · sentido horario")
        playback = st.select_slider("Velocidad de reproducción", [60, 120, 300, 600], value=300,
                                    format_func=lambda value: f"{value}×",
                                    help="Acelera solo la animación. No cambia RPM, caudal ni tiempo físico de vuelta.")
        p1, p2, p3 = st.columns(3)
        p1.metric("Vuelta física estimada", f"{plan.estimated_lap_min:.1f} min")
        p2.metric("Reproducción", f"{playback}×")
        p3.metric("Duración de un ciclo en pantalla", f"{plan.estimated_lap_min * 60 / playback:.1f} s")
        st.plotly_chart(make_fast_simulation(model, plan, playback), width="stretch")
        st.caption("Pulsa ▶ en la gráfica. Los colores muestran la velocidad longitudinal Q/A "
                   "de cada franja y los flotadores siguen el tiempo integrado: pasan más "
                   "despacio por los tramos anchos. No representan trayectorias reales, turbulencia, "
                   "remolinos, interacción entre usuarios ni CFD. La reproducción acelerada no "
                   "modifica los resultados hidráulicos.")

    with tab_treatment:
        st.subheader("Tratamiento de agua · circuito independiente")
        t1, t2, t3 = st.columns(3)
        t1.metric("Volumen hidráulico DXF", f"{plan.volume_m3:,.0f} m³")
        t2.metric("Recambio de filtración supuesto", f"{turnover_h:.1f} h")
        t3.metric("Q que debe atravesar filtros", f"{plan.filtration_flow_m3_h:,.0f} m³/h")
        st.info("Los módulos Riverflow impulsan la corriente, pero su descarga local no se cuenta "
                "como caudal filtrado. El recambio se calcula solo con el flujo que realmente pasa "
                "por el sistema de tratamiento: Q = volumen / horas de recambio.")
        st.caption("Se mantienen 4 horas como hipótesis inicial editable, no como aprobación sanitaria "
                   "para Liberia. El volumen definitivo debe incluir también el tanque de compensación "
                   "si forma parte del circuito de tratamiento.")
        candidate_rate = st.number_input("Tasa de filtración de prueba (m/h)", 1.0, 60.0,
                                          20.0, 1.0,
                                          help="Hipótesis para comparar áreas, NO una recomendación de diseño ni un límite normativo. La tasa final depende del tipo y fabricante del filtro.")
        candidate_area = st.number_input("Área efectiva por filtro candidato (m²; 0 si no se conoce)",
                                          0.0, 200.0, 0.0, 1.0)
        total_filter_area = plan.filtration_flow_m3_h / candidate_rate
        st.metric("Área total de filtración · hipótesis", f"{total_filter_area:,.1f} m²")
        if candidate_area > 0:
            st.metric("Filtros activos mínimos · aritmética", f"{ceil(total_filter_area / candidate_area)}")
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
        st.markdown("**Equipos a prever para la hipótesis de 4 horas**")
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

    with tab_equipment:
        st.subheader("Unidades de propulsión")
        rows = [{"Unidad": f"RF-{i:02d}", "Recorrido (m)": round(position, 1),
                 "Q estimado a velocidad elegida (m³/h)": round(plan.module_flow_full_speed_m3_h * speed_pct / 100, 1),
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

    with tab_references:
        st.subheader("Comparación de configuraciones Riverflow")
        def units_for_head(head_ft):
            one_unit_flow = scenario_channel_flow_m3_h(
                plan.channel_resistance_s2_m5,
                riverflow_flow_at_head_ft(head_ft, plan.curve_mode),
                1, plan.speed_fraction, plan.transfer_fraction)
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
