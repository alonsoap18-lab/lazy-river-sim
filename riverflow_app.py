"""Riverflow-focused Phase-1 Streamlit interface for the NYA DXF geometry."""

import csv
import io
import os
from math import ceil

import plotly.graph_objects as go
import streamlit as st

from core.orchestrator import LazyRiverModel
from core.riverflow_model import (
    RIVERFLOW_MOTOR_HP,
    RIVERFLOW_RATED_GPM,
    RIVERFLOW_RATED_M3_H,
    compute_riverflow_plan,
    riverflow_flow_at_head_ft,
)


MODEL_VERSION = "riverflow-curve-anchors-2"
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


def make_map(model, plan, show_installation=True):
    fig = go.Figure()
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
                               ("calm", "Entradas a playa / zona calma", "#86efac")):
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
        px = station["x"] + nx * (width / 2 + 2)
        py = station["y"] + ny * (width / 2 + 2)
        sx = station["x"] - tx * 1.2 + nx * (width * 0.3)
        sy = station["y"] - ty * 1.2 + ny * (width * 0.3)
        ox = station["x"] + tx * 1.2 + nx * (width * 0.3)
        oy = station["y"] + ty * 1.2 + ny * (width * 0.3)
        labels.append(f"RF-{number:02d} · {position:.0f} m")
        pump_x.append(px)
        pump_y.append(py)
        if show_installation:
            for side in (-0.6, 0.6):
                x, y = sx + tx * side, sy + ty * side
                suction_x.append(x)
                suction_y.append(y)
                pipe_x.extend([x, px, None])
                pipe_y.extend([y, py, None])
            outlet_x.append(ox)
            outlet_y.append(oy)
            pipe_x.extend([px, ox, None])
            pipe_y.extend([py, oy, None])
            flow_x.extend([ox, ox + tx * 3, None])
            flow_y.extend([oy, oy + ty * 3, None])
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
    per_module_effective = (plan.module_flow_full_speed_m3_h * plan.speed_fraction
                            * plan.transfer_fraction)
    times = [plan.volume_m3 * 60 / (count * per_module_effective) for count in counts]
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
    st.caption("Fase 1 · geometría DXF y dimensionamiento conceptual de propulsión, filtración e infraestructura")

    st.sidebar.header("Diseño NYA desde DXF")
    uploaded = st.sidebar.file_uploader("Plano DXF (capa PAREDES)", type=["dxf"])
    target_length_m = st.sidebar.number_input(
        "Longitud de referencia para escalar DXF (m)", min_value=100.0,
        max_value=2000.0, value=536.0, step=1.0,
        help="Escala longitud y anchos con el mismo factor. Ningún ancho fijo reemplaza el DXF.")
    depth_m = st.sidebar.number_input("Profundidad de agua (m)", 0.4, 3.0, 1.2, 0.05)
    calm_width_m = st.sidebar.number_input("Zona calma desde ancho (m)", 4.0, 40.0, 15.0, 0.5,
                                           help="Las partes anchas del DXF se tratan como entradas a playa.")

    try:
        model, issues = load_geometry(uploaded.getvalue() if uploaded else None,
                                      target_length_m, MODEL_VERSION)
    except (ValueError, OSError) as exc:
        st.error(f"No se pudo procesar el DXF: {exc}")
        st.stop()
    for issue in issues:
        st.warning(str(issue))

    st.sidebar.header("Unidades Riverflow")
    target_lap_min = st.sidebar.number_input("Objetivo de tiempo por vuelta (min)",
                                             5.0, 120.0, 40.0, 0.5)
    active_modules = st.sidebar.number_input("Unidades activas", 1, 60, 19, 1)
    standby_modules = st.sidebar.number_input("Unidades de reserva", 0, 10, 1, 1,
                                              help="No aportan caudal mientras están apagadas.")
    local_head_ft = st.sidebar.number_input(
        "TDH local estimada por unidad a plena velocidad (ft)", 4.0, 10.0, 4.0, 0.5,
        help="Escenario de carga en el circuito local de una bomba, NO la TDH de una red central. "
             "Se interpola entre 2,440 US GPM a 4 ft y 1,220 US GPM a 10 ft de la curva recibida. "
             "Debe confirmarse con Riverflow para NYA.")
    speed_pct = st.sidebar.slider("Velocidad del variador (%)", 50, 100, 100, 1,
                                  help="Q proporcional a RPM es una aproximación; la curva H–Q real determina el caudal.")
    transfer_pct = st.sidebar.slider(
        "Transferencia a circulación longitudinal (%)", 10, 100, 100, 5,
        help="Hipótesis de escenario no calibrada: representa qué parte del caudal local equivale a movimiento longitudinal del río. 100% es el límite optimista, no una garantía.")
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

    st.info("El caudal por Riverflow proviene de dos puntos rotulados de la curva H–Q recibida. "
            "La TDH local y la transferencia longitudinal son hipótesis editables: el caudal de las "
            "bombas no equivale automáticamente a circulación neta del río. La vuelta es una "
            "estimación hasta verificar las pérdidas locales y la circulación con Riverflow o CFD.")

    st.subheader("Resultado del escenario")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Meta de vuelta", f"{plan.target_lap_min:.1f} min")
    c2.metric("Vuelta estimada", f"{plan.estimated_lap_min:.1f} min")
    c3.metric("Caudal de unidades", f"{plan.installed_operating_flow_m3_h:,.0f} m³/h")
    c4.metric("Circulación equivalente", f"{plan.equivalent_channel_flow_m3_h:,.0f} m³/h")
    c5.metric("Velocidad de recorrido", f"{plan.velocity_lap_m_s:.3f} m/s")
    if plan.estimated_lap_min <= plan.target_lap_min:
        st.success(f"Bajo la transferencia supuesta, {active_modules} unidades alcanzan la meta. "
                   f"Mínimo aritmético estimado: {plan.required_active_modules} activas.")
    else:
        st.warning(f"Bajo la transferencia supuesta, se necesitarían al menos "
                   f"{plan.required_active_modules} unidades activas para {target_lap_min:.1f} min.")

    g1, g2, g3, g4, g5 = st.columns(5)
    g1.metric("Volumen desde DXF", f"{plan.volume_m3:,.0f} m³")
    g2.metric("Q requerido para meta", f"{plan.target_equivalent_flow_m3_h:,.0f} m³/h")
    g3.metric("Motores activos · placa", f"{plan.active_motor_nameplate_hp:.0f} HP")
    g4.metric("Filtración separada", f"{plan.filtration_flow_m3_h:,.0f} m³/h")
    g5.metric("Q por unidad según curva", f"{plan.module_flow_full_speed_m3_h:,.0f} m³/h",
              help=f"Interpolado a {local_head_ft:.1f} ft ({local_head_ft * 0.3048:.2f} m) de TDH local estimada, a plena velocidad.")

    tab_map, tab_hydraulic, tab_equipment, tab_references = st.tabs(
        ["Plano 2D y unidades", "Cálculo y escenarios", "Equipos e infraestructura",
         "Comparativos y planos Riverflow"])

    with tab_map:
        show_installation = st.checkbox("Mostrar montaje conceptual: bomba, tomas y descarga", value=True)
        st.plotly_chart(make_map(model, plan, show_installation), width="stretch")
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

    with tab_hydraulic:
        curve_heads = [4.0 + i * 0.1 for i in range(61)]
        curve = go.Figure()
        curve.add_trace(go.Scatter(x=[riverflow_flow_at_head_ft(h) for h in curve_heads],
                                   y=curve_heads, mode="lines", name="Interpolación entre anclas",
                                   line=dict(color="#2563eb", width=3)))
        curve.add_trace(go.Scatter(x=[plan.module_flow_full_speed_m3_h], y=[local_head_ft],
                                   mode="markers", name="Escenario seleccionado",
                                   marker=dict(size=12, color="#ea580c")))
        curve.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=25),
                            xaxis_title="Caudal por unidad a plena velocidad (m³/h)",
                            yaxis_title="TDH local estimada (ft)")
        st.plotly_chart(curve, width="stretch")
        st.caption("Curva recibida: 2,440 US GPM a 4 ft y 1,220 US GPM a 10 ft. "
                   "La línea entre esos puntos es interpolación de planificación, no una curva "
                   "certificada digitalizada. Fuera de 4–10 ft no se extrapola. "
                   "El punto de operación real requiere cruzar la curva de la bomba con la curva del circuito local.")
        st.plotly_chart(make_profile(model, plan), width="stretch")
        h1, h2, h3 = st.columns(3)
        h1.metric("V local en canal de corriente", f"{plan.current_velocity_min_m_s:.3f}–{plan.current_velocity_max_m_s:.3f} m/s")
        h2.metric("V local en todo el recorrido", f"{plan.velocity_min_m_s:.3f}–{plan.velocity_max_m_s:.3f} m/s")
        h3.metric("V equivalente Q/A medio", f"{plan.velocity_equivalent_m_s:.3f} m/s")
        st.caption("Velocidad de recorrido = longitud / tiempo estimado. La V equivalente Q/A medio "
                   "usa el área media y puede diferir de ella por los cambios de ancho del DXF.")
        st.plotly_chart(make_count_chart(plan), width="stretch")
        st.markdown(
            f"**Cálculo enlazado:** volumen DXF {plan.volume_m3:,.1f} m³ ÷ "
            f"caudal longitudinal equivalente {plan.equivalent_channel_flow_m3_h:,.1f} m³/h "
            f"= {plan.estimated_lap_min:.1f} min/vuelta. Este caudal equivale a "
            f"{active_modules} × {plan.module_flow_full_speed_m3_h:.1f} m³/h por unidad "
            f"a {local_head_ft:.1f} ft × {speed_pct}% × {transfer_pct}%."
        )
        st.warning("La TDH ingresada no está calculada para NYA. Caudal a velocidad parcial ≈ caudal "
                   "a plena velocidad × porcentaje del variador es una aproximación de escenario, "
                   "no un punto verificado de la curva. Potencia eléctrica y velocidad de salida "
                   "requieren dimensiones de tomas/salidas, trazado local y validación del fabricante. "
                   "La placa de 10 HP no es el consumo instantáneo.")

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
            "succión protegida, descarga, válvulas, drenaje y ventilación según Riverflow.\n"
            "- **Área eléctrica protegida:** tableros, variadores ABB, protecciones y control; "
            "alimentación y demanda por definir con el ingeniero eléctrico.\n"
            f"- **Planta de tratamiento independiente:** dimensionamiento preliminar "
            f"{plan.filtration_flow_m3_h:,.0f} m³/h para un recambio de {turnover_h:.1f} h."
        )
        st.caption("Las unidades de reserva no aportan caudal al escenario. Su ubicación de almacenamiento "
                   "o instalación queda pendiente del plan de redundancia.")
        st.caption("El plano 'Espada Amenity' recibido de Riverflow muestra como referencia una bomba vertical, "
                   "dos tomas de succión, descarga y requisitos de elevación/drenaje. Es otro proyecto: "
                   "sus cotas y disposición no se transfieren a NYA sin un plano específico aprobado.")

    with tab_references:
        st.subheader("Comparación de configuraciones Riverflow")
        st.dataframe([
            {"Escenario": "NYA · hipótesis 4 ft", "Longitud conocida": f"{plan.length_m:.0f} m desde DXF",
             "Q por unidad": "554 m³/h", "Unidades para meta":
             f"{ceil(plan.target_equivalent_flow_m3_h / (riverflow_flow_at_head_ft(4) * plan.speed_fraction * plan.transfer_fraction))} aprox.",
             "Alcance del dato": "Cálculo NYA; TDH y transferencia sin verificar"},
            {"Escenario": "NYA · hipótesis 10 ft", "Longitud conocida": f"{plan.length_m:.0f} m desde DXF",
             "Q por unidad": "277 m³/h", "Unidades para meta":
             f"{ceil(plan.target_equivalent_flow_m3_h / (riverflow_flow_at_head_ft(10) * plan.speed_fraction * plan.transfer_fraction))} aprox.",
             "Alcance del dato": "Cálculo NYA; TDH y transferencia sin verificar"},
            {"Escenario": "Espada Amenity · plano recibido", "Longitud conocida": "No indicada",
             "Q por unidad": "No indicado en el plano", "Unidades para meta": "No comparable",
             "Alcance del dato": "Detalle constructivo de otro proyecto, 3.5 ft de profundidad"},
            {"Escenario": "Gator Grounds · referencia pública", "Longitud conocida": "301 ft ≈ 92 m",
             "Q por unidad": "No publicado para ese proyecto", "Unidades para meta": "No comparable",
             "Alcance del dato": "Longitud publicada; sin cantidad ni TDH de bombas"},
            {"Escenario": "AquaNick Riviera Maya · referencia pública", "Longitud conocida": "No publicada",
             "Q por unidad": "No publicado para ese proyecto", "Unidades para meta": "No comparable",
             "Alcance del dato": "Riverflow confirma uso, sin datos hidráulicos comparables"},
        ], width="stretch", hide_index=True)
        st.caption("Los conteos NYA son aritméticos bajo las hipótesis actuales, no diseños de esos "
                   "proyectos. Falta una medición de corriente y una curva de sistema para comparar desempeño.")
        st.markdown("Fuentes externas: [Gator Grounds (Riverflow)](https://riverflowpumps.com/aqua-magazine-a-fiberglass-lazy-river/) · "
                    "[AquaNick (Riverflow)](https://riverflowpumps.com/commercial-projects/) · "
                    "[Componentes del sistema](https://riverflowpumps.com/technical/what-the-system-includes/).")
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
