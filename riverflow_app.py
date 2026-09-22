"""Riverflow-focused Phase-1 Streamlit interface for the NYA DXF geometry."""

import csv
import io
import os

import plotly.graph_objects as go
import streamlit as st

from core.orchestrator import LazyRiverModel
from core.riverflow_model import (
    RIVERFLOW_MOTOR_HP,
    RIVERFLOW_RATED_GPM,
    RIVERFLOW_RATED_M3_H,
    compute_riverflow_plan,
)


MODEL_VERSION = "riverflow-distributed-planning-1"


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


def make_map(model, plan):
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
    module_stations = [min(model.stations, key=lambda s: abs(s["chainage_m"] - position))
                       for position in plan.module_chainages_m]
    fig.add_trace(go.Scatter(
        x=[s["x"] for s in module_stations], y=[s["y"] for s in module_stations],
        mode="markers", name="Unidad Riverflow activa",
        marker=dict(size=10, color="#ea580c", symbol="diamond",
                    line=dict(color="white", width=1)),
        text=[f"RF-{i:02d} · {position:.0f} m"
              for i, position in enumerate(plan.module_chainages_m, 1)],
        hovertemplate="%{text}<extra></extra>",
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
    module_flow_m3_h = st.sidebar.number_input(
        "Caudal por unidad al 100% (m³/h)", 50.0, 1500.0,
        float(round(RIVERFLOW_RATED_M3_H, 1)), 1.0,
        help="Valor publicado: 2,440 US GPM ≈ 554 m³/h. Ajustar al punto real de la curva H–Q cuando Riverflow lo confirme.")
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
            module_flow_full_speed_m3_h=module_flow_m3_h,
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

    st.info("El caudal anunciado de cada Riverflow se recircula localmente. La transferencia longitudinal "
            "es una hipótesis editable: la vuelta calculada es una estimación de escenario hasta disponer "
            "de curva H–Q, trazado de succión/descarga y validación del fabricante o CFD.")

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

    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Volumen desde DXF", f"{plan.volume_m3:,.0f} m³")
    g2.metric("Q requerido para meta", f"{plan.target_equivalent_flow_m3_h:,.0f} m³/h")
    g3.metric("Motores activos · placa", f"{plan.active_motor_nameplate_hp:.0f} HP")
    g4.metric("Filtración separada", f"{plan.filtration_flow_m3_h:,.0f} m³/h")

    tab_map, tab_hydraulic, tab_equipment = st.tabs(
        ["Plano 2D y unidades", "Cálculo y escenarios", "Equipos e infraestructura"])

    with tab_map:
        st.plotly_chart(make_map(model, plan), width="stretch")
        st.caption("Cada marcador representa una unidad Riverflow con toma de succión y salida local. "
                   "La posición es conceptual; el fabricante debe definir separación, orientación y detalles de obra.")
        st.metric("Longitud del circuito", f"{plan.length_m:.0f} m")
        z1, z2 = st.columns(2)
        z1.metric("Canal de corriente", f"{plan.current_zone_length_m:.0f} m")
        z2.metric("Entradas a playa / zonas calmas", f"{plan.calm_zone_length_m:.0f} m")
        st.metric("Mayor distancia de canal a una unidad", f"{plan.max_current_distance_to_module_m:.0f} m",
                  help="Distancia más larga, medida sobre el recorrido cerrado, desde una sección de corriente hasta la unidad activa más cercana. Cambia al mover unidades; no equivale a alcance hidráulico de la descarga.")

    with tab_hydraulic:
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
            f"{active_modules} × {module_flow_m3_h:.1f} × {speed_pct}% × {transfer_pct}%."
        )
        st.warning("TDH real, potencia eléctrica y velocidad de salida de boquillas: pendientes de la "
                   "curva H–Q, dimensiones de tomas/salidas y trazado de cada circuito local. "
                   "La potencia de placa de 10 HP por unidad no es su consumo instantáneo.")

    with tab_equipment:
        st.subheader("Unidades de propulsión")
        rows = [{"Unidad": f"RF-{i:02d}", "Recorrido (m)": round(position, 1),
                 "Q nominal a velocidad elegida (m³/h)": round(module_flow_m3_h * speed_pct / 100, 1),
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

    st.markdown("**Datos publicados del fabricante:** "
                f"{RIVERFLOW_RATED_GPM:,.0f} US GPM ≈ {RIVERFLOW_RATED_M3_H:.1f} m³/h y "
                f"motor de {RIVERFLOW_MOTOR_HP:.0f} HP por unidad. "
                "[Sistema Riverflow](https://riverflowpumps.com/technical/what-the-system-includes/) · "
                "[Curva publicada](https://riverflowpumps.com/technical/riverflow-pump-curve/) · "
                "[Registro NSF](https://info.nsf.org/Certified/Pools/Listings.asp?TradeName=riverflow).")
    st.caption("Modelo preliminar de fase 1 para comparar escenarios; no sustituye diseño hidráulico, "
               "eléctrico, sanitario o de seguridad del proyecto.")
