"""
Selvatura NYA - Lazy River Hydraulic Digital Model V2.3
Streamlit web interface with animated water flow simulation.
"""
import streamlit as st
import numpy as np
import plotly.graph_objects as go
import sys
import os
import math
from copy import deepcopy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.orchestrator import LazyRiverModel
from core.reference import get_reference_table, get_design_standards, compare_with_reference, get_pump_types, get_jet_types
from models.geometry_model import HydraulicResults

st.set_page_config(page_title="Selvatura NYA - Lazy River", page_icon="", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""<style>
.main-header { font-size: 2.2rem; color: #1E90FF; text-align: center; margin-bottom: 0.5rem; }
.explain-box { background: #f8f9fa; border-left: 4px solid #1E90FF; padding: 12px 16px;
               margin: 8px 0; border-radius: 4px; font-size: 0.95em; }
.status-ok { color: #28a745; font-weight: bold; }
.status-warn { color: #ffc107; font-weight: bold; }
.status-crit { color: #dc3545; font-weight: bold; }

/* Dark mode support */
[data-theme="dark"] .main-header { color: #4DA6FF; }
[data-theme="dark"] .explain-box { background: #1e1e1e; border-left-color: #4DA6FF; color: #e0e0e0; }
[data-theme="dark"] .stMetric { background-color: #2d2d2d; }
</style>""", unsafe_allow_html=True)


MODEL_CACHE_VERSION = "phase1-zoning-treatment-2"


@st.cache_resource(show_spinner="Cargando geometria DXF...")
def load_model(dxf_path, length_m, cache_version):
    """Load model from DXF. Cached for performance - only reloads when path/length change.
    Width always comes from DXF geometry (isotropic scaling).

    This object is a read-only base model.  Each Streamlit rerun gets a deep
    copy below so manual scenario controls never alter the shared cache.
    """
    m = LazyRiverModel()
    m.load_dxf(path=dxf_path)
    m.build_centerline(resolution_m=0.5, target_length_m=length_m)
    return m


def explain(label, simple, technical, status="INFO"):
    """Render an expandable explanation card."""
    icons = {"NORMAL": "ok", "REVIEW": "warning", "CRITICAL": "error", "INFO": "info"}
    with st.expander(f"{label}"):
        st.markdown(f'<div class="explain-box">{simple}</div>', unsafe_allow_html=True)
        if technical:
            with st.expander("Ver detalles tecnicos"):
                st.code(technical)




@st.cache_data
def get_reference_data():
    """Cache reference data lookups."""
    from core.reference import get_reference_table, get_design_standards, get_pump_types, get_jet_types
    return {
        'ref_table': get_reference_table(),
        'standards': get_design_standards(),
        'pump_types': get_pump_types(),
        'jet_types': get_jet_types(),
    }


def make_geometry_plot(model, show_stations=False):
    fig = go.Figure()
    if model.loader and model.loader.outer_wall:
        oc = list(model.loader.outer_wall.coords)
        fig.add_trace(go.Scatter(x=[c[0] for c in oc], y=[c[1] for c in oc],
                                 mode='lines', name='Muro Exterior',
                                 line=dict(color='navy', width=2)))
    if model.loader and model.loader.inner_wall and model.loader.inner_wall != model.loader.outer_wall:
        ic = list(model.loader.inner_wall.coords)
        fig.add_trace(go.Scatter(x=[c[0] for c in ic], y=[c[1] for c in ic],
                                 mode='lines', name='Muro Interior',
                                 line=dict(color='darkred', width=2)))
    if model.geometry and model.geometry.centerline_coords:
        cl = model.geometry.centerline_coords
        fig.add_trace(go.Scatter(x=[c[0] for c in cl], y=[c[1] for c in cl],
                                 mode='lines', name='Centroline',
                                 line=dict(color='green', width=1.5, dash='dot')))
    if show_stations and model.stations:
        step = max(1, len(model.stations) // 20)
        for s in model.stations[::step]:
            fig.add_trace(go.Scatter(x=[s['x']], y=[s['y']], mode='markers',
                                     marker=dict(size=4, color='gray'),
                                     showlegend=False, hoverinfo='skip'))
    fig.update_layout(title="Geometria del Canal", xaxis_title="X", yaxis_title="Y",
                      plot_bgcolor='white', paper_bgcolor='white', width=900, height=600)
    fig.update_yaxes(scaleanchor='x', scaleratio=1)
    return fig


def make_simulation_plot(model, results, particles, jets_viz, t,
                          show_particles=True, show_vectors=True,
                          show_jets=True, show_heatmap=True, person=None):
    """Build the main simulation figure with animated elements."""
    fig = go.Figure()

    # Walls
    if model.loader and model.loader.outer_wall:
        oc = list(model.loader.outer_wall.coords)
        fig.add_trace(go.Scatter(x=[c[0] for c in oc], y=[c[1] for c in oc],
                                 mode='lines', name='Muro Exterior',
                                 line=dict(color='navy', width=2)))
    if model.loader and model.loader.inner_wall and model.loader.inner_wall != model.loader.outer_wall:
        ic = list(model.loader.inner_wall.coords)
        fig.add_trace(go.Scatter(x=[c[0] for c in ic], y=[c[1] for c in ic],
                                 mode='lines', name='Muro Interior',
                                 line=dict(color='darkred', width=2)))

    # Velocity heatmap along centerline
    if show_heatmap and results and results.stations:
        cl = model.geometry.centerline_coords
        speeds = [s.velocity_m_s for s in results.stations]
        for i in range(len(cl) - 1):
            v = speeds[i]
            v_norm = min(1.0, max(0.0, (v - 0.2) / 0.6))
            r = int(255 * min(1, 2 * v_norm))
            g = int(255 * min(1, 2 * (1 - v_norm)))
            color = f'rgb({r},{g},100)'
            fig.add_trace(go.Scatter(
                x=[cl[i][0], cl[i+1][0]], y=[cl[i][1], cl[i+1][1]],
                mode='lines', line=dict(color=color, width=6),
                showlegend=False, hoverinfo='skip', opacity=0.5))

    # Velocity vectors
    if show_vectors and results and results.stations:
        step = max(1, len(results.stations) // 40)
        for s in results.stations[::step]:
            scale = 2.0
            fig.add_trace(go.Scatter(
                x=[s.x, s.x + s.tangent_x * scale],
                y=[s.y, s.y + s.tangent_y * scale],
                mode='lines', line=dict(color='rgba(0,0,150,0.3)', width=1),
                showlegend=False, hoverinfo='skip'))

    # Jet sprays
    if show_jets and jets_viz:
        spray_lines = jets_viz.get_spray_lines(t)
        for sl in spray_lines:
            color = 'cyan' if sl['active'] else 'lightgray'
            fig.add_trace(go.Scatter(
                x=sl['xs'], y=sl['ys'], mode='lines+markers',
                line=dict(color=color, width=2),
                marker=dict(size=4, color=color),
                showlegend=False,
                hovertemplate=f"Jet {sl['jet_id']}<br>Caudal: {sl['flow']:.1f} m3/h<extra></extra>"))
            fig.add_trace(go.Scatter(
                x=[sl['xs'][0]], y=[sl['ys'][0]], mode='markers+text',
                marker=dict(size=10, color='red' if sl['active'] else 'gray', symbol='diamond'),
                text=[f"J-{sl['jet_id']}"], textposition='top center',
                showlegend=False))

    # Water particles
    if show_particles and particles and particles.active:
        px, py = particles.get_xy()
        pspeeds = particles.get_speeds()
        if len(px) > 0:
            fig.add_trace(go.Scatter(
                x=px, y=py, mode='markers',
                marker=dict(size=4, color=pspeeds, colorscale='Blues',
                            cmin=0.2, cmax=1.0, opacity=0.8),
                name=f'Agua ({len(px)} particulas)',
                hoverinfo='skip'))

    # Jet markers on map
    if show_jets and model.propulsion:
        jets = model.propulsion.get_active_jets()
        if jets:
            fig.add_trace(go.Scatter(
                x=[j.x for j in jets], y=[j.y for j in jets],
                mode='markers+text',
                marker=dict(size=12, color='red', symbol='diamond'),
                text=[f"J-{j.jet_id}" for j in jets],
                textposition='top center',
                name='Jets', hovertemplate='Jet %{text}<extra></extra>'))

    # Person/floater marker
    if person:
        px, py = person.get_xy()
        v = person.get_velocity()
        progress = person.get_progress()
        fig.add_trace(go.Scatter(
            x=[px], y=[py], mode='markers+text',
            marker=dict(size=20, color='lime', symbol='circle',
                        line=dict(color='darkgreen', width=2)),
            text=[f"PERSONA"], textposition='top center',
            name=f'Persona (vuelta {person.laps + 1})',
            hovertemplate=f"Persona<br>Vuelta: {person.laps + 1}<br>"
                          f"Velocidad: {v:.2f} m/s<br>"
                          f"Progreso: {progress:.0f}%<extra></extra>"))

    fig.update_layout(
        title="Simulacion de Flujo - Lazy River",
        xaxis_title="X", yaxis_title="Y",
        plot_bgcolor='white', paper_bgcolor='white',
        width=1000, height=700,
        showlegend=True,
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01,
                    bgcolor='rgba(255,255,255,0.8)'))
    fig.update_yaxes(scaleanchor='x', scaleratio=1)
    return fig


def make_velocity_plot(results):
    fig = go.Figure()
    if not results or not results.stations:
        return fig
    chainages = [s.chainage_m for s in results.stations]
    velocities = [s.velocity_m_s for s in results.stations]
    fig.add_trace(go.Scatter(x=chainages, y=velocities, mode='lines',
                             name='Velocidad', line=dict(color='blue', width=2)))
    fig.add_hline(y=0.5, line_dash="dash", line_color="green",
                  annotation_text="Objetivo 0.50 m/s")
    fig.update_layout(title="Velocidad vs Chainage", xaxis_title="Chainage (m)",
                      yaxis_title="Velocidad (m/s)", plot_bgcolor='white', paper_bgcolor='white')
    return fig


def make_width_plot(model):
    fig = go.Figure()
    if not model.stations:
        return fig
    chainages = [s['chainage_m'] for s in model.stations]
    widths = [s['width_m'] for s in model.stations]
    fig.add_trace(go.Scatter(x=chainages, y=widths, mode='lines',
                             name='Ancho', line=dict(color='teal', width=2)))
    fig.update_layout(title="Ancho Local vs Chainage", xaxis_title="Chainage (m)",
                      yaxis_title="Ancho (m)", plot_bgcolor='white', paper_bgcolor='white')
    return fig


def make_loss_pie(results):
    fig = go.Figure()
    if not results or not results.losses:
        return fig
    names = [l.name for l in results.losses]
    values = [max(l.value_m, 0.001) for l in results.losses]
    fig.add_trace(go.Pie(labels=names, values=values, hole=0.3))
    fig.update_layout(title="Distribucion de Perdidas")
    return fig


def make_system_curve_plot(model, depth_m, manning_n):
    fig = go.Figure()
    if not model.hydraulic_stations:
        return fig
    from core.hydraulics import HydraulicEngine
    he = HydraulicEngine(model.stations, depth_m=depth_m, manning_n=manning_n)
    q_range = np.linspace(100, 20000, 50)
    H = he.system_curve(q_range, model.hydraulic_stations)
    fig.add_trace(go.Scatter(x=q_range, y=H, mode='lines', name='Curva Sistema',
                             line=dict(color='blue', width=2)))
    fig.update_layout(title="Curva del Sistema", xaxis_title="Caudal (m3/h)",
                      yaxis_title="TDH (m)", plot_bgcolor='white', paper_bgcolor='white')
    return fig


def generate_whats_happening(model, results, n_people, n_jets, depth_m, n_pumps=2, pump_flow=5400.0):
    """Generate plain-language status report."""
    g = model.geometry
    lines = []
    lines.append("**Estado del sistema:**")
    lines.append("")

    v = results.velocity_lap_m_s if results else 0
    lap = results.lap_time_min if results else 0
    total_q = n_pumps * pump_flow

    if v >= 0.3 and v <= 1.0:
        lines.append("El Lazy River esta funcionando en condiciones normales segun el modelo.")
    elif v < 0.3:
        lines.append("La velocidad es baja. Podria no ser suficiente para el desplazamiento de usuarios.")
    else:
        lines.append("La velocidad es alta. Revisar criterios de seguridad.")

    lines.append("")
    lines.append(f"**Como se calcula:**")
    lines.append(f"- Las {n_pumps} bombas entregan {total_q:.0f} m3/h de caudal total")
    lines.append(f"- El area del canal es {g.channel_width_avg_m:.1f} m x {depth_m:.2f} m = {g.channel_width_avg_m*depth_m:.1f} m2")
    lines.append(f"- La velocidad es V = Q/A = {v:.3f} m/s ({v*3.6:.1f} km/h)")
    lines.append(f"- El tiempo de vuelta es T = L/V = {lap:.1f} minutos")
    lines.append("")
    lines.append(f"**Si cambias los parametros:**")
    lines.append(f"- Mas bombas o mas caudal → mas velocidad → menos tiempo de vuelta")
    lines.append(f"- Mas Manning n (rugosidad) → mas perdidas → el TDH aumenta → necesitas bombas mas potentes")
    lines.append(f"- Mas personas → mas resistencia → la velocidad baja un poco")
    lines.append("")
    lines.append(f"- Jets: {n_jets} (distribuyen el flujo en el canal)")
    lines.append(f"- Profundidad: {depth_m:.2f} m")

    if n_people > 0:
        lines.append(f"- Personas en canal: {n_people} (generan resistencia)")
    else:
        lines.append("- Sin usuarios actualmente")

    if results and results.losses:
        total_loss = results.tdh_m
        lines.append(f"- TDH (perdidas totales): {total_loss:.2f} m")
        lines.append(f"- Potencia requerida: {results.power_motor_kw:.1f} kW")

    lines.append("")
    lines.append("**NOTA:** Los resultados provienen de un modelo hidraulico simplificado.")
    lines.append("Deben validarse con mediciones reales antes de usarse como criterio definitivo.")

    return "\n".join(lines)


def main():
    st.markdown('<div class="main-header">Selvatura NYA - Lazy River Hydraulic Model</div>',
                unsafe_allow_html=True)
    st.markdown("**Modelo digital hidraulico | Circuito cerrado | 536 m**")

    # Sidebar
    st.sidebar.header("Configuracion del Proyecto")

    # Save/Load project
    import json
    from datetime import datetime

    col_save, col_load = st.sidebar.columns(2)
    with col_save:
        if st.button("Guardar", help="Guardar configuracion actual"):
            config = {
                "timestamp": datetime.now().isoformat(),
                "length_m": st.session_state.get("length_m", 536.0),
                # width_m NOT saved — always comes from DXF
                "depth_m": st.session_state.get("depth_m", 1.2),
                "manning_n": st.session_state.get("manning_n", 0.015),
                "n_pumps": st.session_state.get("n_pumps", 2),
                "pump_flow": st.session_state.get("pump_flow", 5400.0),
                "pump_efficiency": st.session_state.get("pump_efficiency", 0.70),
                "pump_head": st.session_state.get("pump_head", 5.0),
                "n_pump_rooms": st.session_state.get("n_pump_rooms", 1),
                "n_jets": st.session_state.get("n_jets", 8),
                "jet_diam": st.session_state.get("jet_diam", 0.400),
                "safety_factor": st.session_state.get("safety_factor", 1.15),
                "n_people": st.session_state.get("n_people", 0),
            }
            st.session_state["saved_config"] = json.dumps(config, indent=2)
            st.success("Configuracion guardada")

    with col_load:
        if st.button("Cargar", help="Cargar configuracion guardada"):
            if "saved_config" in st.session_state:
                config = json.loads(st.session_state["saved_config"])
                for key, value in config.items():
                    if key != "timestamp":
                        st.session_state[key] = value
                st.success(f"Cargado: {config.get('timestamp', 'N/A')[:16]}")
                st.rerun()
            else:
                st.warning("No hay configuracion guardada")

    # Export/Import
    col_exp, col_imp = st.sidebar.columns(2)
    with col_exp:
        if st.button("Exportar JSON", help="Descargar configuracion como JSON"):
            config = {
                "project": "Selvatura NYA",
                "timestamp": datetime.now().isoformat(),
                "length_m": st.session_state.get("length_m", 536.0),
                # width_m NOT exported — always comes from DXF
                "depth_m": st.session_state.get("depth_m", 1.2),
                "manning_n": st.session_state.get("manning_n", 0.015),
                "n_pumps": st.session_state.get("n_pumps", 2),
                "pump_flow": st.session_state.get("pump_flow", 5400.0),
                "pump_efficiency": st.session_state.get("pump_efficiency", 0.70),
                "pump_head": st.session_state.get("pump_head", 5.0),
                "n_pump_rooms": st.session_state.get("n_pump_rooms", 1),
                "n_jets": st.session_state.get("n_jets", 8),
                "jet_diam": st.session_state.get("jet_diam", 0.400),
                "safety_factor": st.session_state.get("safety_factor", 1.15),
                "n_people": st.session_state.get("n_people", 0),
            }
            st.download_button(
                label="Descargar JSON",
                data=json.dumps(config, indent=2),
                file_name="selvatura_config.json",
                mime="application/json"
            )

    with col_imp:
        uploaded_json = st.file_uploader("Importar JSON", type=['json'], key="json_import")
        if uploaded_json:
            try:
                config = json.loads(uploaded_json.read())
                for key, value in config.items():
                    if key not in ("project", "timestamp"):
                        st.session_state[key] = value
                st.success(f"Importado: {config.get('project', 'N/A')}")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    st.sidebar.markdown("---")

    # Dark mode toggle
    dark_mode = st.sidebar.checkbox("Modo oscuro", value=False,
                                     help="Activa el tema oscuro para la interfaz.")
    if dark_mode:
        st.markdown("""
        <script>
        document.documentElement.setAttribute('data-theme', 'dark');
        </script>
        """, unsafe_allow_html=True)

    st.sidebar.markdown("---")

    default_dxf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RECORRIDO.dxf")
    uploaded = st.sidebar.file_uploader("Cargar DXF", type=['dxf'])
    dxf_path = default_dxf

    # Presets
    st.sidebar.subheader("Presets")
    preset = st.sidebar.selectbox("Seleccionar preset", [
        "Personalizado",
        "Selvatura NYA (536m)",
        "Pequeno (300m)",
        "Mediano (500m)",
        "Grande (800m)",
        "Referencia: Siam Park",
        "Referencia: WhiteWater West",
    ], help="Cargar configuracion predefinida")

    if preset == "Selvatura NYA (536m)":
        # Optimizado para V=0.50 m/s con geometría real del DXF (ancho 10.95m)
        # 4 bombas × 4,400 m³/h = 17,600 m³/h total
        # 16 jets × 450mm, 4 cuartos de bombas
        # V_avg=0.502 m/s, TDH=3.74 m, HP=368
        st.session_state.update({"length_m": 536.0, "depth_m": 1.2,
                                  "manning_n": 0.015, "n_pumps": 4, "pump_flow": 4400.0,
                                  "pump_efficiency": 0.75, "pump_head": 5.0, "n_pump_rooms": 4,
                                  "n_jets": 16, "jet_diam": 0.450, "safety_factor": 1.15})
    elif preset == "Pequeno (300m)":
        st.session_state.update({"length_m": 300.0, "depth_m": 1.0,
                                  "manning_n": 0.015, "n_pumps": 2, "pump_flow": 3000.0,
                                  "pump_efficiency": 0.70, "pump_head": 3.0, "n_pump_rooms": 1,
                                  "n_jets": 5, "jet_diam": 0.300, "safety_factor": 1.15})
    elif preset == "Mediano (500m)":
        st.session_state.update({"length_m": 500.0, "depth_m": 1.1,
                                  "manning_n": 0.015, "n_pumps": 2, "pump_flow": 5000.0,
                                  "pump_efficiency": 0.70, "pump_head": 4.0, "n_pump_rooms": 1,
                                  "n_jets": 8, "jet_diam": 0.350, "safety_factor": 1.15})
    elif preset == "Grande (800m)":
        st.session_state.update({"length_m": 800.0, "depth_m": 1.2,
                                  "manning_n": 0.015, "n_pumps": 3, "pump_flow": 6000.0,
                                  "pump_efficiency": 0.70, "pump_head": 5.0, "n_pump_rooms": 2,
                                  "n_jets": 13, "jet_diam": 0.400, "safety_factor": 1.15})
    elif preset == "Referencia: Siam Park":
        st.session_state.update({"length_m": 500.0, "depth_m": 1.1,
                                  "manning_n": 0.015, "n_pumps": 2, "pump_flow": 3960.0,
                                  "pump_efficiency": 0.70, "pump_head": 4.0, "n_pump_rooms": 1,
                                  "n_jets": 8, "jet_diam": 0.296, "safety_factor": 1.0})
    elif preset == "Referencia: WhiteWater West":
        st.session_state.update({"length_m": 400.0, "depth_m": 1.0,
                                  "manning_n": 0.015, "n_pumps": 2, "pump_flow": 2835.0,
                                  "pump_efficiency": 0.70, "pump_head": 3.0, "n_pump_rooms": 1,
                                  "n_jets": 6, "jet_diam": 0.289, "safety_factor": 1.0})

    st.sidebar.markdown("---")

    st.sidebar.subheader("Geometria")
    length_m = st.sidebar.number_input("Longitud circuito (m)", 100.0, 1000.0, 536.0, 10.0)

    # Width override (disabled by default — width comes from DXF)
    width_override = st.sidebar.checkbox(
        "Forzar ancho manual (ignora DXF)",
        value=False,
        help="ACTIVAR SOLO para escenarios hipotéticos. "
             "Por defecto, el ancho viene del DXF cargado."
    )
    if width_override:
        width_m = st.sidebar.number_input(
            "Ancho promedio manual (m)", 1.0, 30.0, 11.0, 0.5,
            help="⚠️ Modo manual: este valor IGNORA la geometría del DXF."
        )
        st.sidebar.warning("⚠️ Usando ancho MANUAL, no el del DXF")

    st.sidebar.subheader("Canal")
    depth_m = st.sidebar.slider("Profundidad (m)", 0.5, 2.0, 1.2, 0.05)
    manning_n = st.sidebar.slider("Manning n (rugosidad)", 0.010, 0.030, 0.015, 0.001, format="%.3f",
                                   help="Mayor n = más pérdidas y mayor TDH requerido. Con caudal de bomba fijado, no cambia Q ni la velocidad hasta resolver una curva H-Q real.")

    st.sidebar.subheader("Zonificación 2D desde DXF")
    calm_zone_width_m = st.sidebar.number_input(
        "Ancho desde el que es zona calma (m)", 6.0, 35.0, 15.0, 0.5,
        help="Los tramos más anchos se clasifican como entrada a playa/zona calma. "
             "No se les exige la velocidad mínima del canal de corriente."
    )

    st.sidebar.subheader("Bombas (CONFIGURAR AQUI)")
    calculation_basis = st.sidebar.radio(
        "Base del cálculo hidráulico",
        ["Caudal configurado de bombas", "Tiempo objetivo de vuelta"],
        help="Elige si el modelo calcula el tiempo resultante desde el caudal o el caudal requerido desde el tiempo deseado."
    )
    target_lap_time_min = None
    if calculation_basis == "Tiempo objetivo de vuelta":
        target_lap_time_min = st.sidebar.number_input(
            "Tiempo objetivo por vuelta (min)", 5.0, 120.0, 20.0, 0.5,
            help="El modelo ajusta el caudal requerido usando toda la geometría del DXF para cumplir este tiempo."
        )
    n_pumps = st.sidebar.number_input("Numero de bombas", 1, 4, 4, 1)
    pump_flow = st.sidebar.number_input("Caudal por bomba (m3/h)", 100.0, 20000.0, 4400.0, 100.0,
                                         help="Caudal que cada bomba entrega. En modo tiempo objetivo se usa para comparar la capacidad por bomba requerida.")
    pump_efficiency = st.sidebar.slider("Eficiencia bomba", 0.5, 0.9, 0.75, 0.05,
                                         help="Eficiencia de la bomba. Afecta la potencia requerida.")
    pump_head = st.sidebar.number_input("TDH disponible (m)", 0.5, 30.0, 5.0, 0.5,
                                         help="Valor nominal para contrastar con el TDH calculado. No sustituye la curva H-Q certificada ni modifica el caudal configurado.")

    st.sidebar.subheader("Cuartos de Bombas")
    n_pump_rooms = st.sidebar.number_input("Numero de cuartos de bombas", 1, 4, 4, 1,
                                            help="Mas cuartos = tuberias mas cortas = menos perdidas = menos HP. "
                                                 "4 cuartos: a 1/8, 3/8, 5/8 y 7/8 del circuito.")

    st.sidebar.subheader("Jets")
    n_jets = st.sidebar.number_input("Numero de jets", 1, 30, 16, 1,
                                      help="Mas jets = mejor distribucion del flujo en el canal.")
    jet_diam = st.sidebar.number_input("Diametro jet (m)", 0.050, 1.000, 0.450, 0.050,
                                        help="Diametro de la boquilla del jet. Afecta la velocidad de salida.")

    st.sidebar.subheader("VFD (Variador de Frecuencia)")
    use_vfd = False
    if calculation_basis == "Caudal configurado de bombas":
        use_vfd = st.sidebar.checkbox("Usar VFD", value=False,
                                       help="Variable Frequency Drive: reduce RPM de la bomba para ahorrar energia.")
    else:
        st.sidebar.caption("En modo tiempo objetivo, el caudal requerido controla el cálculo; el VFD deberá ajustarse después con la curva H-Q.")
    vfd_speed_pct = 100.0
    if use_vfd:
        vfd_speed_pct = st.sidebar.slider("Velocidad VFD (%)", 50, 100, 100, 5,
                                           help="Reducir velocidad: 80% = ~50% ahorro energetico (ley de afinidad).")

    st.sidebar.subheader("Factor de Seguridad")
    safety_factor = st.sidebar.slider("Factor de seguridad", 1.0, 2.0, 1.15, 0.05,
                                       help="Multiplica la potencia calculada para margen de seguridad. "
                                            "1.0=sin margen, 1.15=estandar industria, 1.25-1.5=condiciones severas.")

    # Safety factor justification (U7)
    with st.sidebar.expander("Desglose del Factor de Seguridad"):
        motor_sf = 1.05
        service_sf = 1.05
        aging_sf = 1.05
        st.write(f"**Motor losses:** {motor_sf:.2f} (5%)")
        st.write(f"**Service conditions:** {service_sf:.2f} (5%)")
        st.write(f"**Aging/margin:** {aging_sf:.2f} (5%)")
        st.write(f"**Total:** {motor_sf * service_sf * aging_sf:.2f}")
        st.write(f"**Seleccionado:** {safety_factor:.2f}")
        if safety_factor > 1.15:
            st.warning("SF > 1.15: condiciones severas o margen extra")
        elif safety_factor < 1.0:
            st.error("SF < 1.0: sin margen de seguridad")

    st.sidebar.subheader("Propiedades del Agua")
    water_temp = st.sidebar.slider("Temperatura agua (°C)", 15, 35, 25, 1,
                                    help="Afecta densidad, viscosidad y presión de vapor. "
                                         "Típico Costa Rica: 25-30°C.")

    st.sidebar.subheader("Tratamiento de Agua")
    filtration_turnover_h = st.sidebar.number_input(
        "Tiempo de recirculación de filtración (h)", 2.0, 12.0, 4.0, 0.5,
        help="Q de filtración = volumen calculado desde DXF / tiempo de recirculación. "
             "Circuito separado de la propulsión."
    )

    st.sidebar.subheader("Ocupacion")
    n_people = st.sidebar.slider("Personas en canal", 0, 1000, 0, 10,
                                  help="Se registra para simulación de usuarios. No modifica Q, TDH ni velocidades hidráulicas hasta calibrar resistencia humana y curva H-Q.")

    # Load model
    if uploaded:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as tmp:
            tmp.write(uploaded.read())
            dxf_path = tmp.name

    # Never mutate the cached DXF model: controls must be isolated by rerun/user.
    model = deepcopy(load_model(dxf_path, length_m, MODEL_CACHE_VERSION))

    # Apply manual width override if active
    if width_override:
        current_avg = model.geometry.channel_width_avg_m
        if current_avg > 0:
            scale = width_m / current_avg
            for s in model.stations:
                s['width_m'] *= scale
            model.geometry.channel_width_avg_m = np.mean([s['width_m'] for s in model.stations])
            model.geometry.channel_width_min_m = min([s['width_m'] for s in model.stations])
            model.geometry.channel_width_max_m = max([s['width_m'] for s in model.stations])

    # Display actual channel width (from DXF or override)
    g = model.geometry
    st.sidebar.metric(
        "Ancho promedio del canal",
        f"{g.channel_width_avg_m:.1f} m",
        help=f"Min: {g.channel_width_min_m:.1f} m | Max: {g.channel_width_max_m:.1f} m | "
             f"{'⚠️ MANUAL (no DXF)' if width_override else 'Del DXF cargado'}"
    )

    # Compute hydraulics - orchestrator handles pump selection and smart jet placement internally
    total_pump_flow = n_pumps * pump_flow

    # VFD effect: reduce flow proportionally to speed
    if use_vfd and vfd_speed_pct < 100:
        vfd_factor = vfd_speed_pct / 100.0
        # Affinity laws: Q ∝ N, H ∝ N², P ∝ N³
        total_pump_flow_effective = total_pump_flow * vfd_factor
    else:
        vfd_factor = 1.0
        total_pump_flow_effective = total_pump_flow

    results = model.compute_hydraulics(depth_m=depth_m, manning_n=manning_n,
                                        pump_flow_m3_h=(total_pump_flow_effective if target_lap_time_min is None else None),
                                        target_lap_time_min=target_lap_time_min,
                                        n_jets=n_jets, jet_diameter_m=jet_diam,
                                        pump_efficiency=pump_efficiency,
                                        n_pumps=n_pumps,
                                        safety_factor=safety_factor,
                                        n_pump_rooms=n_pump_rooms,
                                        water_temp_c=water_temp,
                                        pump_head_available_m=pump_head,
                                        calm_zone_width_m=calm_zone_width_m)

    # All secondary views and scenarios use the actual flow selected above.
    if target_lap_time_min:
        total_pump_flow_effective = results.total_flow_m3_h

    # Occupancy has no calibrated hydraulic-loss model or pump H-Q curve yet.
    # Keep all hydraulic outputs continuous with Q instead of changing only one
    # average-speed field.  It remains available as a user-simulation input.

    # Separate circuits: filtration treats the full calculated water volume.
    Q_filtration = results.water_volume_m3 / filtration_turnover_h if filtration_turnover_h > 0 else 0

    # Separate flows
    g = model.geometry
    Q_canal = results.total_flow_m3_h if results else 0
    Q_propulsion = model.propulsion.total_flow_m3_h() if model.propulsion else 0
    Q_total_system = Q_propulsion + Q_filtration

    # Safety
    alerts = model.safety.evaluate(results.stations) if results.stations else []

    # Dashboard - show how configuration drives results
    st.markdown("---")
    channel_area = g.channel_width_avg_m * depth_m
    Q_required_m3s = results.total_flow_m3_s if results else 0
    st.markdown("### RESULTADOS PRELIMINARES (no aptos para construcción ni certificación de seguridad)")

    # Main results row
    c1, c2, c_time, c3, c4 = st.columns(5)
    q_label = "Q requerido para tiempo objetivo" if target_lap_time_min else "Q bombas efectivo"
    c1.metric(q_label, f"{results.total_flow_m3_h:.0f} m3/h",
              help="Caudal usado por el modelo. Si hay VFD, incorpora la reducción de velocidad.")
    c2.metric("Velocidad de recorrido (L/T)", f"{results.velocity_lap_m_s:.3f} m/s",
              help="Velocidad principal del diseño: longitud del circuito dividida entre el tiempo de vuelta integrado.")
    c_time.metric("Tiempo de vuelta", f"{results.lap_time_min:.1f} min",
                  help="Tiempo integrado con las velocidades locales; es la base de la velocidad de recorrido L/T.")
    c3.metric("V local (mín–máx)", f"{results.velocity_min_m_s:.3f}–{results.velocity_max_m_s:.3f} m/s",
              help="Rango de velocidad por sección; permite detectar zonas lentas o rápidas.")
    c4.metric("TDH Sistema", f"{results.total_system_tdh_m:.2f} m",
              help="TDH total = friccion canal + perdidas boquillas + friccion tuberias")

    if results.pump_head_margin_m < 0:
        st.error(
            f"El TDH nominal configurado ({pump_head:.2f} m) es menor que el TDH estimado "
            f"({results.total_system_tdh_m:.2f} m). El caudal configurado no está demostrado: "
            "confírmalo con una curva H-Q certificada."
        )
    else:
        st.info(
            f"Margen nominal de TDH: {results.pump_head_margin_m:.2f} m. "
            "Comprobación preliminar: falta validar el punto de operación con la curva H-Q del fabricante."
        )

    if target_lap_time_min:
        required_per_pump = results.total_flow_m3_h / n_pumps
        capacity_status = "OK" if pump_flow >= required_per_pump else "REVISAR"
        st.info(
            f"Objetivo: {target_lap_time_min:.1f} min/vuelta → caudal requerido {results.total_flow_m3_h:.0f} m³/h "
            f"({required_per_pump:.0f} m³/h por bomba; capacidad configurada: {pump_flow:.0f} m³/h, {capacity_status})."
        )

    # COMMERCIAL HP - highlighted
    st.markdown("#### POTENCIA COMERCIAL REQUERIDA")
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("POTENCIA TOTAL (HP)", f"{results.total_hp:.1f} HP",
              help="Potencia comercial total = (rho x g x Q x TDH) / eficiencia / 745.7")
    c6.metric("HP POR BOMBA", f"{results.pump_hp:.1f} HP",
              help="HP comercial por bomba = HP total / numero de bombas")
    c7.metric("Potencia teorica", f"{results.theoretical_kw:.1f} kW",
              help="Potencia teorica (informativa)")
    c8.metric("Bombas", f"{n_pumps} x {pump_flow:.0f} m3/h",
              help="Configuracion de bombas")

    # TDH breakdown
    st.markdown("#### DESGLOSE DEL TDH DEL SISTEMA")
    c9, c10, c11, c12 = st.columns(4)
    c9.metric("Friccion canal", f"{results.canal_friction_m:.3f} m",
              help="Perdidas por friccion en el canal (Darcy-Weisbach + Manning)")
    c10.metric("Perdidas boquillas", f"{results.nozzle_loss_m:.3f} m",
              help="Perdida de velocidad en boquillas = V_exit² / (2g)")
    c11.metric("Friccion tuberias", f"{results.pipe_friction_m:.3f} m",
              help="Perdidas por friccion en tuberias (estimacion empirica)")
    c12.metric("TDH TOTAL", f"{results.total_system_tdh_m:.3f} m",
              help="Suma de todas las perdidas del sistema")

    # Additional info
    c13, c14, c15, c16 = st.columns(4)
    c13.metric("Jets", f"{n_jets}",
              help="Numero de jets instalados")
    jets_active = model.propulsion.get_active_jets() if model.propulsion else []
    v_exit_display = jets_active[0].velocity_exit_m_s if jets_active else 0
    c14.metric("V_exit boquilla", f"{v_exit_display:.1f} m/s",
              help="Velocidad de salida del jet (nozzle)")
    c15.metric("Potencia W", f"{results.total_power_watts:.0f} W",
              help="Potencia total en Watts")
    c16.metric("Personas", f"{n_people}")

    z1, z2, z3 = st.columns(3)
    z1.metric("Volumen teórico DXF", f"{results.water_volume_m3:,.0f} m³")
    z2.metric("Canal de corriente", f"{results.current_zone_length_m:.0f} m")
    z3.metric("Entradas a playa / calma", f"{results.calm_zone_length_m:.0f} m",
              help=f"Ancho ≥ {calm_zone_width_m:.1f} m según la zonificación editable.")

    if n_people > 0:
        st.info(
            "La ocupación está registrada para la simulación de usuarios. Aún no se aplica a Q, TDH ni "
            "velocidades: hacerlo sin datos de arrastre calibrados y una curva H-Q produciría resultados inconsistentes."
        )

    # Gauge charts for key metrics
    st.markdown("#### INDICADORES CLAVE")
    froude_numbers = [s.froude_number for s in results.stations if hasattr(s, 'froude_number')]
    fr_max = max(froude_numbers) if froude_numbers else 0
    eff_system = (results.power_hydraulic_kw / (results.power_motor_kw * safety_factor) * 100
                  if results.power_motor_kw > 0 else 0)

    gauge_col1, gauge_col2, gauge_col3 = st.columns(3)

    with gauge_col1:
        fig_v = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=results.velocity_lap_m_s,
            title={'text': "Velocidad de recorrido L/T (m/s)"},
            delta={'reference': 0.5, 'increasing': {'color': "red"}, 'decreasing': {'color': "green"}},
            gauge={
                'axis': {'range': [0, 1.0], 'tickwidth': 1},
                'bar': {'color': "darkblue"},
                'steps': [
                    {'range': [0, 0.2], 'color': "red"},
                    {'range': [0.2, 0.3], 'color': "yellow"},
                    {'range': [0.3, 0.6], 'color': "lightgreen"},
                    {'range': [0.6, 0.8], 'color': "yellow"},
                    {'range': [0.8, 1.0], 'color': "red"},
                ],
                'threshold': {'line': {'color': "black", 'width': 4}, 'thickness': 0.75, 'value': 0.5}
            }))
        fig_v.update_layout(height=250, margin=dict(l=20, r=20, t=50, b=20))
        st.plotly_chart(fig_v, use_container_width=True)

    with gauge_col2:
        fig_fr = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=fr_max,
            title={'text': "Froude Max"},
            delta={'reference': 0.8, 'increasing': {'color': "red"}, 'decreasing': {'color': "green"}},
            gauge={
                'axis': {'range': [0, 1.2], 'tickwidth': 1},
                'bar': {'color': "darkblue"},
                'steps': [
                    {'range': [0, 0.8], 'color': "lightgreen"},
                    {'range': [0.8, 1.0], 'color': "yellow"},
                    {'range': [1.0, 1.2], 'color': "red"},
                ],
                'threshold': {'line': {'color': "black", 'width': 4}, 'thickness': 0.75, 'value': 0.8}
            }))
        fig_fr.update_layout(height=250, margin=dict(l=20, r=20, t=50, b=20))
        st.plotly_chart(fig_fr, use_container_width=True)

    with gauge_col3:
        fig_eff = go.Figure(go.Indicator(
            mode="gauge+number",
            value=eff_system,
            title={'text': "Eficiencia Sistema (%)"},
            gauge={
                'axis': {'range': [0, 100], 'tickwidth': 1},
                'bar': {'color': "darkblue"},
                'steps': [
                    {'range': [0, 30], 'color': "red"},
                    {'range': [30, 50], 'color': "yellow"},
                    {'range': [50, 100], 'color': "lightgreen"},
                ],
                'threshold': {'line': {'color': "black", 'width': 4}, 'thickness': 0.75, 'value': 60}
            }))
        fig_eff.update_layout(height=250, margin=dict(l=20, r=20, t=50, b=20))
        st.plotly_chart(fig_eff, use_container_width=True)

    # Calculation chain
    st.markdown(f"""
    **Cadena de calculo:**
    ```
    {f"Objetivo de vuelta: {target_lap_time_min:.1f} min → Q requerido = {results.total_flow_m3_h:.0f} m3/h" if target_lap_time_min else f"Bombas: {n_pumps} x {pump_flow:.0f} m3/h = {total_pump_flow:.0f} m3/h"}
    {f"VFD: {vfd_speed_pct:.0f}% → Q efectivo = {total_pump_flow_effective:.0f} m3/h" if use_vfd and vfd_speed_pct < 100 else ""}
    Area canal: {g.channel_width_avg_m:.1f} m x {depth_m:.2f} m = {channel_area:.1f} m2
    Tiempo integrado de vuelta: {results.lap_time_min:.2f} min
    Velocidad de recorrido: {g.channel_length_m:.0f} / ({results.lap_time_min:.2f} x 60) = {results.velocity_lap_m_s:.3f} m/s
    Velocidad local: min={results.velocity_min_m_s:.3f}, max={results.velocity_max_m_s:.3f} m/s (varía con el ancho local)
    TDH sistema: {results.canal_friction_m:.3f} + {results.nozzle_loss_m:.3f} + {results.pipe_friction_m:.3f} = {results.total_system_tdh_m:.3f} m
    Potencia: (998 x 9.81 x {Q_required_m3s:.3f} x {results.total_system_tdh_m:.3f}) / {pump_efficiency:.2f} = {results.total_power_watts:.0f} W
    HP total: {results.total_power_watts:.0f} / 745.7 = {results.total_hp:.1f} HP
    HP/bomba: {results.total_hp:.1f} / {n_pumps} = {results.pump_hp:.1f} HP
    Temperatura: {water_temp}°C | rho={model.hydraulics.rho:.1f} kg/m³ | nu={model.hydraulics.nu:.2e} m²/s
    ```
    """)

    # VFD Savings Analysis
    if use_vfd and vfd_speed_pct < 100:
        st.markdown("---")
        st.markdown("#### ANALISIS VFD (Variador de Frecuencia)")
        # Affinity laws: P ∝ N³
        vfd_factor = vfd_speed_pct / 100.0
        power_with_vfd = results.power_motor_kw * safety_factor
        power_without_vfd = power_with_vfd / (vfd_factor ** 3)  # P ∝ N³
        annual_savings_kwh = (power_without_vfd - power_with_vfd) * 10 * 300  # 10h/day, 300 days
        electricity_cost = 0.12  # USD/kWh
        annual_savings_usd = annual_savings_kwh * electricity_cost

        cv1, cv2, cv3, cv4 = st.columns(4)
        cv1.metric("Potencia sin VFD", f"{power_without_vfd:.1f} kW")
        cv2.metric("Potencia con VFD", f"{power_with_vfd:.1f} kW",
                   delta=f"-{power_without_vfd - power_with_vfd:.1f} kW")
        cv3.metric("Ahorro anual", f"${annual_savings_usd:,.0f}",
                   help=f"{annual_savings_kwh:,.0f} kWh/año")
        cv4.metric("Reduccion potencia", f"{(1 - vfd_factor**3)*100:.0f}%",
                   help="Ley de afinidad: P ∝ N³")

        st.info(f"**VFD al {vfd_speed_pct:.0f}%**: Reducir velocidad un {100-vfd_speed_pct:.0f}% "
                f"ahorra {(1 - vfd_factor**3)*100:.0f}% de energia. "
                f"Ahorro estimado: ${annual_savings_usd:,.0f}/año ({annual_savings_kwh:,.0f} kWh).")

    st.markdown("---")
    st.markdown("#### TRATAMIENTO DE AGUA — CIRCUITO SEPARADO")
    cb1, cb2, cb3, cb4 = st.columns(4)
    cb1.metric("Volumen hidráulico", f"{results.water_volume_m3:,.0f} m³")
    cb2.metric("Recirculación teórica", f"{filtration_turnover_h:.1f} h")
    cb3.metric("Q filtración requerido", f"{Q_filtration:,.0f} m³/h")
    cb4.metric("Q propulsión (jets)", f"{Q_propulsion:,.0f} m³/h")
    st.caption("La filtración se calcula por volumen/tiempo de recirculación. No se suma al TDH de propulsión "
               "hasta definir bomba, filtros, tuberías y pérdidas propias del sistema de tratamiento.")

    # Status
    summary = model.safety.summary(alerts) if alerts else {'overall': 'NORMAL'}
    status_colors = {"NORMAL": "green", "REVIEW": "orange", "CRITICAL": "red"}
    st.sidebar.markdown(f"**Estado: :{status_colors.get(summary['overall'], 'gray')}[{summary['overall']}]**")

    # "What's happening" button
    with st.expander("QUE ESTA PASANDO? (Explicacion simple)"):
        report = generate_whats_happening(model, results, n_people, n_jets, depth_m, n_pumps, pump_flow)
        st.markdown(report)

    # Tabs
    tab_geo, tab_est, tab_hid, tab_prop, tab_sim, tab_esc, tab_val, tab_rep, tab_ref, tab_infra = st.tabs([
        "Geometria", "Estaciones", "Hidraulica", "Propulsion",
        "SIMULACION", "Escenarios", "Validacion", "Reportes", "REFERENCIA", "INFRAESTRUCTURA"
    ])

    with tab_geo:
        st.subheader("Geometria del Canal")
        c1, c2 = st.columns([2, 1])
        with c1:
            fig = make_geometry_plot(model, show_stations=True)
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            st.write(f"**Muro exterior:** {len(model.loader.get_outer_coords())} puntos")
            st.write(f"**Muro interior:** {len(model.loader.get_inner_coords())} puntos")
            st.write(f"**Estaciones:** {len(model.stations)}")
            st.write(f"**Ancho min:** {g.channel_width_min_m:.2f} m")
            st.write(f"**Ancho max:** {g.channel_width_max_m:.2f} m")
            st.write(f"**Escala:** {g.scale_m_per_unit:.4f} m/unidad DXF")

            # Width explanation
            w_range = g.channel_width_max_m - g.channel_width_min_m
            if w_range > 3.0:
                st.warning(f"El ancho varia {w_range:.1f} m entre min y max. Revisar geometria del DXF.")

        explain("Ancho del canal",
                f"El ancho promedio es {g.channel_width_avg_m:.1f} m. El canal no tiene el mismo ancho en todo el recorrido. "
                f"El ancho varia entre {g.channel_width_min_m:.1f} m y {g.channel_width_max_m:.1f} m.",
                f"Ancho calculado por proyeccion de cada punto de la centerline sobre ambos muros.\n"
                f"Promedio: {g.channel_width_avg_m:.2f} m\n"
                f"Minimo: {g.channel_width_min_m:.2f} m\n"
                f"Maximo: {g.channel_width_max_m:.2f} m")

        st.plotly_chart(make_width_plot(model), use_container_width=True)

    with tab_est:
        st.subheader("Estaciones Hidraulicas")
        if model.hydraulic_stations:
            import pandas as pd
            data = []
            for s in model.hydraulic_stations:
                data.append({
                    'ID': s.station_id,
                    'Chainage (m)': f"{s.chainage_m:.1f}",
                    'Ancho (m)': f"{s.width_m:.2f}",
                    'Area (m2)': f"{s.area_m2:.2f}",
                    'Rh (m)': f"{s.hydraulic_radius_m:.3f}",
                    'V (m/s)': f"{s.velocity_m_s:.3f}",
                    'Q (m3/s)': f"{s.flow_m3_s:.4f}",
                    'Curvatura': f"{s.curvature_1_m:.5f}",
                })
            df = pd.DataFrame(data)
            st.dataframe(df, height=400)
            st.caption(f"Total: {len(model.hydraulic_stations)} estaciones")

    with tab_hid:
        st.subheader("Analisis Hidraulico")

        # Show how velocity is calculated
        Q_jets_total = model.propulsion.total_flow_m3_h()
        A_channel = g.channel_width_avg_m * depth_m
        v_from_jets = (Q_jets_total / 3600) / A_channel if A_channel > 0 else 0

        explain("Velocidad del agua",
                f"La velocidad de recorrido es {results.velocity_lap_m_s:.3f} m/s ({results.velocity_lap_m_s*3.6:.1f} km/h). "
                f"El agua tarda {results.lap_time_min:.1f} minutos en completar una vuelta.\n\n"
                f"**La velocidad depende de los jets:** {n_jets} jets inyectan {Q_jets_total:.0f} m3/h, "
                f"lo que genera {v_from_jets:.3f} m/s. Si aumentas los jets, la velocidad aumenta.",
                f"Calculo de velocidad:\n"
                f"  Q_jets = {n_jets} jets x {total_pump_flow/n_jets:.1f} m3/h = {Q_jets_total:.0f} m3/h\n"
                f"  Area canal = {g.channel_width_avg_m:.1f} x {depth_m:.2f} = {A_channel:.1f} m2\n"
                f"  V_jets = Q/A = {v_from_jets:.3f} m/s\n"
                f"  V_manning (resistencia) = referencia\n"
                f"  V de recorrido (L/T) = {results.velocity_lap_m_s:.3f} m/s\n"
                f"  Manning n: {manning_n}")

        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(make_velocity_plot(results), use_container_width=True)
        with c2:
            st.plotly_chart(make_loss_pie(results), use_container_width=True)

        st.subheader("Perdidas Detalladas")
        if results.losses:
            import pandas as pd
            loss_data = [{'Componente': l.name, 'Tipo': l.type,
                          'Perdida (m)': f"{l.value_m:.4f}", 'Fuente': l.source}
                         for l in results.losses]
            st.dataframe(loss_data)

        explain("TDH (Total Dynamic Head)",
                f"El TDH es {results.tdh_m:.2f} m. Representa la resistencia total que debe vencer la bomba "
                f"para mover el agua por el sistema. Es como la 'resistencia del camino'.",
                f"TDH total: {results.tdh_m:.4f} m\n" +
                "\n".join(f"  {l.name}: {l.value_m:.4f} m" for l in results.losses))

        st.subheader("Curva del Sistema")
        st.plotly_chart(make_system_curve_plot(model, depth_m, manning_n),
                        use_container_width=True)

        # Pump curve × System curve (Operating Point)
        st.subheader("Punto de Operacion: Curva Bomba × Curva Sistema")
        if model.pumps and model.pumps.pumps:
            fig_op = go.Figure()

            # Generate system curve
            q_range = np.linspace(0, total_pump_flow * 1.5, 50)
            sys_h = model.hydraulics.system_curve(q_range, model.hydraulic_stations)

            # Generate combined pump curve
            pump_curve = model.pumps.get_combined_pump_curve(50)
            q_pump = pump_curve['q_m3h']
            h_pump = pump_curve['head_m']

            # Plot system curve
            fig_op.add_trace(go.Scatter(
                x=q_range.tolist(), y=sys_h.tolist(),
                mode='lines', name='Curva del Sistema',
                line=dict(color='blue', width=2)))

            # Plot pump curve
            fig_op.add_trace(go.Scatter(
                x=q_pump, y=h_pump,
                mode='lines', name=f'Curva Bomba ({pump_curve.get("n_pumps", 1)} bombas)',
                line=dict(color='red', width=2)))

            # Mark operating point
            op = model.pumps.find_operating_point(
                lambda q: float(np.interp(q, q_range, sys_h)))
            fig_op.add_trace(go.Scatter(
                x=[op['q_operating']], y=[op['h_operating']],
                mode='markers+text',
                marker=dict(size=12, color='green', symbol='star'),
                text=[f"Punto op.\nQ={op['q_operating']:.0f} m3/h\nH={op['h_operating']:.2f}m"],
                textposition='top center',
                name='Punto de operacion'))

            # Mark BEP range
            if pump_curve.get('q_bep'):
                q_bep = pump_curve['q_bep']
                fig_op.add_vrect(
                    x0=q_bep * 0.8, x1=q_bep * 1.2,
                    fillcolor='rgba(0,255,0,0.1)', line_width=0,
                    annotation_text="BEP range", annotation_position="top left")

            fig_op.update_layout(
                title="Punto de Operacion: Curva Bomba × Curva Sistema",
                xaxis_title="Caudal (m3/h)", yaxis_title="Altura (m)",
                plot_bgcolor='white', paper_bgcolor='white',
                width=900, height=500)
            st.plotly_chart(fig_op, use_container_width=True)

            # Operating point info
            col_op1, col_op2, col_op3 = st.columns(3)
            col_op1.metric("Q operacion", f"{op['q_operating']:.0f} m3/h")
            col_op2.metric("H operacion", f"{op['h_operating']:.2f} m")
            col_op3.metric("Eficiencia", f"{op['efficiency']:.0%}")
        else:
            st.info("Configure bombas para ver el punto de operacion.")

        # Energy Sankey Diagram
        st.subheader("Diagrama de Flujo de Energia (Sankey)")
        if results and results.losses:
            # Build Sankey: Input → Losses → Useful
            p_input = results.power_motor_kw * safety_factor  # Electrical input
            p_hydraulic = results.power_hydraulic_kw  # Hydraulic power
            p_losses_total = p_input - p_hydraulic  # Total losses

            # Break down losses by component
            loss_labels = []
            loss_values = []
            for l in results.losses:
                # Convert loss (m head) to kW: P = rho * g * Q * h
                q_m3s = total_pump_flow_effective / 3600
                p_loss_kw = 998 * 9.81 * q_m3s * l.value_m / 1000
                if p_loss_kw > 0.01:  # Only show significant losses
                    loss_labels.append(l.name)
                    loss_values.append(p_loss_kw)

            # Sankey: Input → [losses] + Useful work
            labels = ["Energia Electrica"] + loss_labels + ["Energia Util (bombeo)"]
            source = list(range(1, len(loss_labels) + 1)) + [0] * (len(loss_labels) + 1)
            target = [len(loss_labels) + 1] * len(loss_labels) + list(range(1, len(loss_labels) + 2))
            values = loss_values + loss_values + [p_hydraulic]

            # Fix: Sankey needs proper source/target/value mapping
            # Input → each loss component + useful
            sankey_source = []
            sankey_target = []
            sankey_value = []
            sankey_labels = ["Energia Electrica"] + loss_labels + ["Energia Util"]
            sankey_colors = []

            # From input to each loss
            for i, (lbl, val) in enumerate(zip(loss_labels, loss_values)):
                sankey_source.append(0)  # From input
                sankey_target.append(i + 1)  # To loss component
                sankey_value.append(val)
                sankey_colors.append(f"rgba(255,{100+i*20},0,0.6)")

            # From input to useful
            sankey_source.append(0)
            sankey_target.append(len(loss_labels) + 1)
            sankey_value.append(p_hydraulic)
            sankey_colors.append("rgba(0,180,0,0.6)")

            fig_sankey = go.Figure(data=[go.Sankey(
                node=dict(
                    pad=15, thickness=20,
                    label=sankey_labels,
                    color=["blue"] + ["orange"] * len(loss_labels) + ["green"],
                ),
                link=dict(
                    source=sankey_source,
                    target=sankey_target,
                    value=sankey_value,
                    color=sankey_colors,
                )
            )])
            fig_sankey.update_layout(
                title=f"Flujo de Energia: {p_input:.1f} kW entrada → {p_hydraulic:.1f} kW util",
                width=800, height=400)
            st.plotly_chart(fig_sankey, use_container_width=True)

            # Efficiency breakdown
            eff_total = (p_hydraulic / p_input * 100) if p_input > 0 else 0
            st.info(f"**Eficiencia del sistema:** {eff_total:.1f}% — "
                    f"De {p_input:.1f} kW electricos, solo {p_hydraulic:.1f} kW se convierten en trabajo hidraulico. "
                    f"El resto ({p_losses_total:.1f} kW) se disipa como calor en friccion y perdidas.")

        # Sensitivity Analysis (Tornado Chart)
        st.subheader("Analisis de Sensibilidad")
        st.markdown("Variacion de cada parametro ±20% para ver su impacto en velocidad y potencia.")

        if st.button("Ejecutar analisis de sensibilidad"):
            with st.spinner("Calculando sensibilidad..."):
                base_params = {
                    "depth_m": depth_m,
                    "manning_n": manning_n,
                    "n_jets": n_jets,
                    "jet_diameter_m": jet_diam,
                    "pump_flow_m3_h": total_pump_flow,
                    "n_pumps": n_pumps,
                    "safety_factor": safety_factor,
                    "n_pump_rooms": n_pump_rooms,
                }
                sensitivity = model.sensitivity_analysis(base_params, variation_pct=20.0)

            if sensitivity:
                # Tornado chart for velocity
                fig_tornado = go.Figure()

                params = [s["parameter"] for s in sensitivity]
                v_down = [s["delta_velocity_down"] for s in sensitivity]
                v_up = [s["delta_velocity_up"] for s in sensitivity]

                fig_tornado.add_trace(go.Bar(
                    y=params, x=v_down, orientation='h',
                    name='-20%', marker_color='indianred'))
                fig_tornado.add_trace(go.Bar(
                    y=params, x=v_up, orientation='h',
                    name='+20%', marker_color='steelblue'))

                fig_tornado.update_layout(
                    title="Sensibilidad: Impacto en Velocidad (±20%)",
                    xaxis_title="Cambio en velocidad (%)",
                    barmode='overlay',
                    plot_bgcolor='white', paper_bgcolor='white',
                    width=800, height=400)
                st.plotly_chart(fig_tornado, use_container_width=True)

                # Tornado chart for power
                fig_power = go.Figure()
                p_down = [s["delta_power_down"] for s in sensitivity]
                p_up = [s["delta_power_up"] for s in sensitivity]

                fig_power.add_trace(go.Bar(
                    y=params, x=p_down, orientation='h',
                    name='-20%', marker_color='indianred'))
                fig_power.add_trace(go.Bar(
                    y=params, x=p_up, orientation='h',
                    name='+20%', marker_color='steelblue'))

                fig_power.update_layout(
                    title="Sensibilidad: Impacto en Potencia (±20%)",
                    xaxis_title="Cambio en potencia (%)",
                    barmode='overlay',
                    plot_bgcolor='white', paper_bgcolor='white',
                    width=800, height=400)
                st.plotly_chart(fig_power, use_container_width=True)

                # Summary table
                st.subheader("Tabla de Sensibilidad")
                sens_table = []
                for s in sensitivity:
                    sens_table.append({
                        "Parametro": s["parameter"],
                        "Base": f"{s['baseline']:.3f}",
                        "-20%": f"{s['varied_down']:.3f}",
                        "+20%": f"{s['varied_up']:.3f}",
                        "ΔV (%)": f"{s['delta_velocity_down']:+.1f} / {s['delta_velocity_up']:+.1f}",
                        "ΔP (%)": f"{s['delta_power_down']:+.1f} / {s['delta_power_up']:+.1f}",
                    })
                st.dataframe(sens_table, use_container_width=True)

                # Key finding
                most_sensitive = sensitivity[0]
                st.info(f"**Parametro mas sensible:** {most_sensitive['parameter']} "
                        f"(impacto en velocidad: {most_sensitive['velocity_range']:.1f}%)")

        # Uncertainty Analysis (Monte Carlo)
        st.subheader("Cuantificacion de Incertidumbre")
        st.markdown("Simulacion Monte Carlo con variacion aleatoria de parametros (±10-15%).")

        if st.button("Ejecutar analisis de incertidumbre"):
            with st.spinner("Ejecutando Monte Carlo (100 muestras)..."):
                base_params = {
                    "depth_m": depth_m,
                    "manning_n": manning_n,
                    "n_jets": n_jets,
                    "jet_diameter_m": jet_diam,
                    "pump_flow_m3_h": total_pump_flow,
                    "n_pumps": n_pumps,
                    "safety_factor": safety_factor,
                    "n_pump_rooms": n_pump_rooms,
                }
                uncertainty = model.uncertainty_analysis(base_params, n_samples=100)

            if "error" not in uncertainty:
                col_u1, col_u2, col_u3 = st.columns(3)
                with col_u1:
                    st.metric("Velocidad (95% CI)",
                              f"{uncertainty['velocity']['p5']:.3f} - {uncertainty['velocity']['p95']:.3f} m/s",
                              help="Intervalo de confianza 95%")
                    st.write(f"Media: {uncertainty['velocity']['mean']:.3f} ± {uncertainty['velocity']['std']:.3f} m/s")
                with col_u2:
                    st.metric("TDH (95% CI)",
                              f"{uncertainty['tdh']['p5']:.2f} - {uncertainty['tdh']['p95']:.2f} m")
                    st.write(f"Media: {uncertainty['tdh']['mean']:.2f} ± {uncertainty['tdh']['std']:.2f} m")
                with col_u3:
                    st.metric("Potencia (95% CI)",
                              f"{uncertainty['power']['p5']:.0f} - {uncertainty['power']['p95']:.0f} kW")
                    st.write(f"Media: {uncertainty['power']['mean']:.0f} ± {uncertainty['power']['std']:.0f} kW")

                # Distribution chart
                fig_dist = go.Figure()
                fig_dist.add_trace(go.Histogram(
                    x=[uncertainty['velocity']['mean']] * uncertainty['n_samples'],
                    name='Velocidad', opacity=0.7))
                fig_dist.update_layout(
                    title="Distribucion de Velocidad (Monte Carlo)",
                    xaxis_title="Velocidad (m/s)", yaxis_title="Frecuencia",
                    plot_bgcolor='white', paper_bgcolor='white')
                st.plotly_chart(fig_dist, use_container_width=True)
            else:
                st.error(uncertainty["error"])

        # Flow explanation
        st.subheader("Caudales")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Q canal (A x V)", f"{Q_canal:.0f} m3/h",
                  help="Caudal equivalente: area de seccion x velocidad. NO es el caudal de bombeo.")
        c2.metric("Q propulsion (jets)", f"{Q_propulsion:.0f} m3/h",
                  help="Caudal total que los jets inyectan al canal.")
        c3.metric("Q filtracion", f"{Q_filtration:.0f} m3/h",
                  help="Caudal del sistema de tratamiento/filtracion.")
        c4.metric("Q registrado", f"{Q_total_system:.0f} m3/h",
                  help="Suma informativa de propulsión y filtración; no representa una sola curva hidráulica.")

        explain("Caudal - Importante",
                "La propulsión se calcula en este modelo. La filtración es un registro separado hasta definir "
                "su bomba, tubería y pérdidas.",
                f"Q canal equivalente = {g.channel_width_avg_m:.1f} x {depth_m:.2f} x {results.velocity_equivalent_m_s:.3f} x 3600 = {Q_canal:.0f} m3/h\n"
                f"Q propulsion = {n_jets} jets x {total_pump_flow_effective/n_jets:.1f} m3/h = {Q_propulsion:.0f} m3/h\n"
                f"Q filtracion = {Q_filtration:.0f} m3/h\n"
                f"Q registrado = {Q_total_system:.0f} m3/h\n"
                "La filtración no se suma al TDH de propulsión en esta versión.")

        # NPSH verification with temperature-dependent vapor pressure
        st.subheader("Verificacion NPSH")
        Patm = 101325.0  # Pa (standard atmosphere at sea level)
        # Vapor pressure using Antoine equation (NIST coefficients, valid 1-100°C)
        Antoine_A, Antoine_B, Antoine_C = 8.07131, 1730.63, 233.426
        P_mmHg = 10 ** (Antoine_A - Antoine_B / (Antoine_C + water_temp))
        Pv = P_mmHg * 133.322  # Convert mmHg to Pa
        rho = 998.0  # kg/m³ (at 20°C, close enough for NPSH)
        g_const = 9.81
        Hs = 0.0  # Suction head (assume pump at water level)
        Hf_suction = results.pipe_friction_m * 0.3 if hasattr(results, 'pipe_friction_m') else 0.5
        NPSHa = Patm / (rho * g_const) - Hs - Hf_suction - Pv / (rho * g_const)
        NPSHr = 3.0  # Conservative estimate for centrifugal pumps
        npsh_margin = NPSHa - NPSHr

        col_npsh1, col_npsh2, col_npsh3, col_npsh4 = st.columns(4)
        col_npsh1.metric("NPSH disponible", f"{NPSHa:.2f} m")
        col_npsh2.metric("NPSH requerido", f"{NPSHr:.2f} m")
        npsh_status = "OK" if npsh_margin > 1.0 else "REVISAR" if npsh_margin > 0.5 else "CRITICO"
        col_npsh3.metric("Margen", f"{npsh_margin:.2f} m ({npsh_status})")
        col_npsh4.metric("Pvapor", f"{Pv:.0f} Pa",
                         help=f"Presion de vapor a {water_temp}°C. Aumenta con la temperatura.")

        if npsh_margin < 0.5:
            st.warning(f"NPSH margin bajo ({npsh_margin:.2f}m). Riesgo de cavitacion a {water_temp}°C. "
                       f"Verificar altura de succion o reducir temperatura.")
        elif npsh_margin < 1.0:
            st.info(f"NPSH marginal ({npsh_margin:.2f}m). Recomendable verificar condiciones de instalacion.")

        # Energy cost estimator (U10)
        st.subheader("Estimacion de Costos Operativos")
        from core.reference import calculate_annual_cost
        cost = calculate_annual_cost(results.power_motor_kw)

        col_cost1, col_cost2, col_cost3, col_cost4 = st.columns(4)
        col_cost1.metric("Costo anual", f"${cost['annual_cost_usd']:,.0f}")
        col_cost2.metric("Costo mensual", f"${cost['monthly_cost_usd']:,.0f}")
        col_cost3.metric("Costo diario", f"${cost['daily_cost_usd']:,.0f}")
        col_cost4.metric("kWh anuales", f"{cost['annual_kwh']:,.0f}")

    with tab_prop:
        st.subheader("Sistema de Propulsion (Jets)")

        # How jets affect the system
        st.markdown("""
        ### Como funcionan los jets

        Los **jets** son los propulsores que inyectan agua al canal para generar movimiento.

        **Cadena de energia:**
        ```
        BOMBAS → TUBERIAS → JETS → AGUA EN EL CANAL → VELOCIDAD
        ```

        **Parametros de cada jet:**
        - **Caudal (m3/h):** Cuanta agua inyecta. Mas caudal = mas empuje.
        - **Diametro (m):** Tamano de la boquilla. Define la velocidad de salida.
        - **Angulo (grados):** Direccion del chorro respecto al canal.
        - **Posicion:** Ubicacion a lo largo del circuito.

        **Efecto de cambiar parametros:**
        | Parametro | Efecto en velocidad | Efecto en TDH | Efecto en potencia |
        |-----------|-------------------|---------------|-------------------|
        | +Jets | AUMENTA | AUMENTA | AUMENTA |
        | +Caudal/jet | AUMENTA | AUMENTA | AUMENTA |
        | +Diametro | DISMINUYE V_salida | DISMINUYE | DISMINUYE |
        """)

        jets = model.propulsion.get_active_jets()
        if jets:
            import pandas as pd
            jet_data = [{
                'ID': j.jet_id, 'Station (m)': f"{j.station_m:.1f}",
                'Caudal (m3/h)': f"{j.flow_m3_h:.1f}",
                'V exit (m/s)': f"{j.velocity_exit_m_s:.1f}",
                'Diam (m)': f"{j.diameter_m:.3f}",
                'Potencia (W)': f"{model.propulsion.jet_power(j):.1f}",
            } for j in jets]
            st.dataframe(jet_data)
            c1, c2, c3 = st.columns(3)
            c1.metric("Caudal total jets", f"{model.propulsion.total_flow_m3_h():.1f} m3/h")
            c2.metric("Empuje total", f"{model.propulsion.total_thrust():.1f} N")
            c3.metric("Potencia total jets", f"{model.propulsion.total_power():.1f} W")

            # Show how jets affect velocity
            Q_jets = model.propulsion.total_flow_m3_h()
            A = g.channel_width_avg_m * depth_m
            v_from_jets = (Q_jets / 3600) / A if A > 0 else 0
            st.info(f"**Velocidad generada por los jets:** {v_from_jets:.3f} m/s "
                    f"(Q_jets={Q_jets:.0f} m3/h / Area={A:.1f} m2)")

            explain("Jets de propulsion",
                    f"Hay {len(jets)} jets activos inyectando un total de {Q_jets:.1f} m3/h. "
                    f"Esto genera una velocidad de {v_from_jets:.3f} m/s en el canal. "
                    f"Si aumentas el numero de jets o el caudal por jet, la velocidad aumenta.",
                    f"Jets: {len(jets)}\n"
                    f"Caudal total: {Q_jets:.1f} m3/h\n"
                    f"Area canal: {A:.1f} m2\n"
                    f"V = Q/A = {v_from_jets:.3f} m/s\n"
                    f"Empuje total: {model.propulsion.total_thrust():.1f} N\n"
                    f"Potencia total: {model.propulsion.total_power():.1f} W")
        else:
            st.info("No hay jets configurados. Aumente el numero de jets en la sidebar.")

        # Pump Selection Wizard
        st.markdown("---")
        st.subheader("Wizard de Seleccion de Bombas")
        st.markdown("Seleccione bombas comerciales reales basado en los requerimientos del sistema.")

        from core.reference import get_commercial_pumps, find_matching_pumps, get_design_target

        if st.button("Buscar bombas compatibles"):
            with st.spinner("Buscando bombas en base de datos..."):
                matching = find_matching_pumps(
                    required_flow_m3h=total_pump_flow_effective,
                    required_tdh_m=results.total_system_tdh_m,
                    n_pumps=n_pumps
                )

            if matching:
                # Separate verified vs generic
                verified = [p for p in matching if p.get("curve_verified", False)]
                generic = [p for p in matching if not p.get("curve_verified", False)]

                st.success(f"Se encontraron **{len(matching)}** bombas compatibles.")

                pump_table = []
                for p in matching:
                    curve_status = "Curva real" if p.get("curve_verified") else "Curva generica (H=H0-kQ2)"
                    verified_status = "Verificado" if p.get("verified") else "No verificado"
                    pump_table.append({
                        "Fabricante": p["manufacturer"],
                        "Modelo": p["model"],
                        "Tipo": p["type"],
                        "HP": p["hp"],
                        "Q (m3/h)": f"{p['flow_m3h']:.0f}",
                        "H (m)": f"{p['head_m']:.1f}",
                        "Eficiencia": f"{p['efficiency_at_point']:.0%}",
                        "HP operacion": f"{p['power_hp']:.0f}",
                        "Curva": curve_status,
                        "Verificado": verified_status,
                        "Precio est.": f"${p['price_usd']:,.0f}",
                    })
                st.dataframe(pump_table, use_container_width=True)

                # Show best match details
                best = matching[0]
                if best.get("curve_verified"):
                    st.success(f"**Mejor opcion (curva verificada):** {best['manufacturer']} {best['model']} — "
                               f"{best['hp']} HP, {best['efficiency_at_point']:.0%} eficiencia, "
                               f"~${best['price_usd']:,.0f}")
                else:
                    st.warning(
                        f"**Mejor opcion (curva GENERICA):** {best['manufacturer']} {best['model']} — "
                        f"{best['hp']} HP, {best['efficiency_at_point']:.0%} eficiencia\n\n"
                        f"Ningun modelo con curva verificada cubre este punto de operacion.\n"
                        f"**Enviar estos datos a Patterson / RiverFlow para cotizacion real:**\n"
                        f"- Q = {total_pump_flow_effective:.0f} m3/h\n"
                        f"- H = {results.total_system_tdh_m:.2f} m\n"
                        f"- Potencia = {results.total_hp:.0f} HP ({results.pump_hp:.0f} HP/bomba)\n"
                        f"- Configuracion: {n_pumps} bombas en {n_pump_rooms} cuarto(s)"
                    )

                # Show verified pumps info
                if not verified:
                    st.info(
                        "**Nota:** Ninguna bomba en la base de datos tiene curva H-Q verificada "
                        "para este punto de operacion. Las curvas mostradas son aproximaciones "
                        "genericas (H = H0 - k*Q²). Para diseno final, solicitar curvas reales "
                        "al fabricante."
                    )
            else:
                st.warning(
                    "No se encontraron bombas compatibles en la base de datos.\n\n"
                    f"**Punto de operacion requerido:**\n"
                    f"- Q = {total_pump_flow_effective:.0f} m3/h\n"
                    f"- H = {results.total_system_tdh_m:.2f} m\n"
                    f"- Potencia = {results.total_hp:.0f} HP\n\n"
                    f"**Accion:** Enviar estos datos a Patterson / RiverFlow para cotizacion real."
                )

        # Pumps section
        st.markdown("---")
        st.subheader("Sistema de Bombas")

        st.markdown("""
        ### Como funcionan las bombas

        Las **bombas** son los equipos que suministran agua a los jets a traves de tuberias.

        **Relacion bomba → jet:**
        ```
        BOMBA P-01 (850 m3/h, 18 m TDH)
            │
            ├── Tuberia principal
            │       ├── Jet J-01 (15 m3/h)
            │       ├── Jet J-02 (15 m3/h)
            │       ├── Jet J-03 (15 m3/h)
            │       └── Jet J-04 (15 m3/h)
            │
            └── Caudal restante → retorno/filtracion
        ```

        **Parametros de cada bomba:**
        - **Caudal (m3/h):** Cuanta agua mueve.
        - **TDH (m):** Altura dinamica total (friccion + perdidas + altura).
        - **Potencia (kW):** Energia necesaria.
        - **Eficiencia:** % de energia que se convierte en trabajo util.

        **Ecuaciones:**
        - P hidraulica = rho × g × Q × TDH
        - P motor = P hidraulica / eficiencia
        """)

        if model.pumps and model.pumps.pumps:
            pump_summary = model.pumps.get_system_summary()
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Bombas", f"{pump_summary['n_active']} activas / {pump_summary['n_pumps']} total")
            c2.metric("Caudal bombas", f"{pump_summary['total_flow_m3h']:.0f} m3/h")
            c3.metric("Potencia total", f"{pump_summary['total_power_kw']:.1f} kW ({pump_summary['total_power_hp']:.1f} HP)")
            c4.metric("Eficiencia", f"{pump_summary['avg_efficiency']:.0%}")

            import pandas as pd
            pump_data = [{
                'ID': f"P-{p.pump_id}",
                'Estado': 'STANDBY' if p.standby else 'ACTIVA',
                'Caudal (m3/h)': f"{p.flow_m3_h:.0f}",
                'TDH (m)': f"{p.head_m:.2f}",
                'Potencia (kW)': f"{p.motor_kw:.1f}",
                'Eficiencia': f"{p.efficiency:.0%}",
            } for p in model.pumps.pumps]
            st.dataframe(pump_data)

            explain("Bombas seleccionadas",
                    f"Se seleccionaron {pump_summary['n_pumps']} bombas para suministrar {pump_summary['total_flow_m3h']:.0f} m3/h "
                    f"contra un TDH de {results.tdh_m:.2f} m. La potencia total del sistema es {pump_summary['total_power_kw']:.1f} kW.",
                    "\n".join(f"P-{p.pump_id}: {p.flow_m3_h:.0f} m3/h, {p.head_m:.2f} m, {p.motor_kw:.1f} kW"
                              for p in model.pumps.pumps))
        else:
            st.warning("No hay bombas configuradas. Configure los jets primero.")

    with tab_sim:
        st.subheader("Simulacion Visual - Recorrido Completo")
        st.markdown(
            f"**Simulación continua con la configuración actual** sobre {model.geometry.channel_length_m:.0f} m. "
            f"Cada cambio manual recarga velocidades, posiciones de jets y tiempo de vuelta."
        )

        if not (results and results.stations and model.geometry.centerline_coords):
            st.warning("No hay datos hidraulicos para simular.")
        else:
            # Controls
            ctrl1, ctrl2, ctrl3, ctrl4 = st.columns(4)
            with ctrl1:
                n_frames = st.selectbox("Duracion simulacion",
                                         [50, 100, 200, 300], index=2,
                                         help="Numero de frames de la animacion")
            with ctrl2:
                show_vectors = st.checkbox("Vectores velocidad", value=False)
            with ctrl3:
                show_jets = st.checkbox("Mostrar jets", value=True)
            with ctrl4:
                show_crowd = st.checkbox("Mostrar multitud", value=False,
                                          help="Simular multiples personas en el canal")

            # Zoom control (S8)
            zoom_col1, zoom_col2 = st.columns(2)
            with zoom_col1:
                zoom_enabled = st.checkbox("Zoom a seccion", value=False,
                                            help="Zoom a una seccion especifica del circuito")
            with zoom_col2:
                if zoom_enabled:
                    zoom_chainage = st.slider("Chainage (m)", 0.0, float(chainages[-1]),
                                               float(chainages[-1]/2), 10.0,
                                               help="Posicion del zoom")
                    zoom_range = st.slider("Rango (m)", 20.0, 100.0, 50.0, 5.0,
                                            help="Rango del zoom (+/-)")
            # Units toggle (U8)
            use_imperial = st.checkbox("Usar unidades imperiales", value=False,
                                        help="Mostrar en ft, ft/s, HP en vez de m, m/s, kW")

            # Prepare data
            velocities = [s.velocity_m_s for s in results.stations]
            chainages = [s.chainage_m for s in results.stations]
            cl_coords = model.geometry.centerline_coords
            cl_x = [c[0] for c in cl_coords]
            cl_y = [c[1] for c in cl_coords]

            # Pre-compute person trajectory (one full lap)
            total_length = chainages[-1]
            # Use integrated lap time from hydraulic results
            lap_time = results.lap_time_min * 60  # Convert to seconds

            # Generate person positions for each frame
            person_positions = []
            person_velocities = []
            person_times = []
            dt = lap_time / n_frames
            pos = 0.0
            t_sim = 0.0

            for frame in range(n_frames):
                # Find velocity at current position
                v = float(np.interp(pos, chainages, velocities))
                person_positions.append(pos)
                person_velocities.append(v)
                person_times.append(t_sim)
                # Advance
                pos += v * dt
                t_sim += dt
                if pos >= total_length:
                    pos = pos % total_length

            # Convert positions to x, y
            person_x = [float(np.interp(p, chainages, cl_x)) for p in person_positions]
            person_y = [float(np.interp(p, chainages, cl_y)) for p in person_positions]

            # Pre-compute water particles following local velocity
            n_water = 20
            water_positions = []
            for wi in range(n_water):
                # Each particle starts at a different offset
                p_offset = (wi / n_water) * total_length
                p_pos = p_offset
                particle_frames = []
                for frame in range(n_frames):
                    particle_frames.append(p_pos)
                    # Advance by local velocity (same physics as person)
                    v_local = float(np.interp(p_pos, chainages, velocities))
                    p_pos += v_local * dt
                    if p_pos >= total_length:
                        p_pos = p_pos % total_length
                water_positions.append(particle_frames)
            # Transpose: water_positions[particle][frame] -> water_frame[frame][particle]
            water_by_frame = list(zip(*water_positions))

            # Identify velocity zones
            v_min = min(velocities)
            v_max = max(velocities)
            v_avg = sum(velocities) / len(velocities)

            # Find low velocity zones (potential problem areas)
            low_v_threshold = v_avg * 0.85
            critical_zones = []
            in_zone = False
            zone_start = 0
            for i, v in enumerate(velocities):
                if v < low_v_threshold and not in_zone:
                    in_zone = True
                    zone_start = i
                elif (v >= low_v_threshold or i == len(velocities)-1) and in_zone:
                    in_zone = False
                    mid = (zone_start + i) // 2
                    critical_zones.append({
                        'chainage': chainages[mid],
                        'x': cl_x[mid],
                        'y': cl_y[mid],
                        'velocity': velocities[mid],
                        'width': [s['width_m'] for s in model.stations][mid],
                    })

            # Build animated figure with Plotly frames
            fig = go.Figure()

            # Base layers (always visible)
            # Walls
            if model.loader and model.loader.outer_wall:
                oc = list(model.loader.outer_wall.coords)
                fig.add_trace(go.Scatter(
                    x=[c[0] for c in oc], y=[c[1] for c in oc],
                    mode='lines', name='Muro Exterior',
                    line=dict(color='navy', width=2)))
            if model.loader and model.loader.inner_wall and model.loader.inner_wall != model.loader.outer_wall:
                ic = list(model.loader.inner_wall.coords)
                fig.add_trace(go.Scatter(
                    x=[c[0] for c in ic], y=[c[1] for c in ic],
                    mode='lines', name='Muro Interior',
                    line=dict(color='darkred', width=2)))

            # Velocity heatmap using preliminary engineering screening bands.
            # These bands are not a compliance certification.
            # Yellow: 0.2-0.3 or 0.6-0.8 m/s (Review)
            # Red: <0.2 or >0.8 m/s (Critical)
            for i in range(len(cl_x) - 1):
                v = velocities[i]
                # Preliminary screening coloring
                if 0.3 <= v <= 0.6:
                    color = 'rgba(0,180,0,0.7)'  # Green - compliant
                elif 0.2 <= v < 0.3 or 0.6 < v <= 0.8:
                    color = 'rgba(255,200,0,0.7)'  # Yellow - review
                else:
                    color = 'rgba(220,30,30,0.7)'  # Red - critical

                fig.add_trace(go.Scatter(
                    x=[cl_x[i], cl_x[i+1]], y=[cl_y[i], cl_y[i+1]],
                    mode='lines', line=dict(color=color, width=8),
                    showlegend=(i == 0), name='Pantalla hidráulica preliminar',
                    hovertemplate=f"V: {v:.3f} m/s<br>"
                                  f"{'Rango preliminar' if 0.3<=v<=0.6 else 'Revisar' if 0.2<=v<=0.8 else 'Crítico'}<extra></extra>",
                    opacity=0.6))

            # Velocity vectors
            if show_vectors:
                step = max(1, len(results.stations) // 30)
                for s in results.stations[::step]:
                    scale = 1.5
                    fig.add_trace(go.Scatter(
                        x=[s.x, s.x + s.tangent_x * scale],
                        y=[s.y, s.y + s.tangent_y * scale],
                        mode='lines', line=dict(color='rgba(0,0,150,0.4)', width=1),
                        showlegend=False, hoverinfo='skip'))

            # Jet markers
            if show_jets and model.propulsion:
                jets = model.propulsion.get_active_jets()
                if jets:
                    fig.add_trace(go.Scatter(
                        x=[j.x for j in jets], y=[j.y for j in jets],
                        mode='markers+text',
                        marker=dict(size=14, color='red', symbol='diamond',
                                    line=dict(color='darkred', width=1)),
                        text=[f"J-{j.jet_id}" for j in jets],
                        textposition='top center',
                        name='Jets',
                        hovertemplate='Jet %{text}<br>Caudal: %{customdata:.0f} m3/h<extra></extra>',
                        customdata=[j.flow_m3_h for j in jets]))

            # Critical zones markers
            if critical_zones:
                fig.add_trace(go.Scatter(
                    x=[z['x'] for z in critical_zones],
                    y=[z['y'] for z in critical_zones],
                    mode='markers+text',
                    marker=dict(size=16, color='orange', symbol='triangle-up',
                                line=dict(color='darkorange', width=2)),
                    text=[f"ZONA {i+1}" for i in range(len(critical_zones))],
                    textposition='bottom center',
                    name='Zonas criticas',
                    hovertemplate='Zona critica<br>Chainage: %{customdata[0]:.0f}m<br>'
                                  'Velocidad: %{customdata[1]:.3f} m/s<br>'
                                  'Ancho: %{customdata[2]:.1f} m<extra></extra>',
                    customdata=[[z['chainage'], z['velocity'], z['width']]
                                for z in critical_zones]))

            # Create animation frames (person + water)
            frames = []
            for frame_idx in range(n_frames):
                frame_data = []

                # Water particles
                wx = [float(np.interp(p, chainages, cl_x)) for p in water_by_frame[frame_idx]]
                wy = [float(np.interp(p, chainages, cl_y)) for p in water_by_frame[frame_idx]]
                frame_data.append(go.Scatter(
                    x=wx, y=wy, mode='markers',
                    marker=dict(size=5, color='cyan', opacity=0.7),
                    showlegend=False, hoverinfo='skip'))

                # Person
                frame_data.append(go.Scatter(
                    x=[person_x[frame_idx]], y=[person_y[frame_idx]],
                    mode='markers+text',
                    marker=dict(size=22, color='lime', symbol='circle',
                                line=dict(color='darkgreen', width=3)),
                    text=['PERSONA'], textposition='top center',
                    showlegend=False,
                    hovertemplate=f"Persona<br>"
                                  f"Velocidad: {person_velocities[frame_idx]:.3f} m/s<br>"
                                  f"Tiempo: {person_times[frame_idx]:.1f} s<br>"
                                  f"Progreso: {person_positions[frame_idx]/total_length*100:.0f}%<extra></extra>"))

                frames.append(go.Frame(data=frame_data, name=str(frame_idx)))

            # Initial frame data
            # Water
            wx0 = [float(np.interp(p, chainages, cl_x)) for p in water_by_frame[0]]
            wy0 = [float(np.interp(p, chainages, cl_y)) for p in water_by_frame[0]]
            fig.add_trace(go.Scatter(
                x=wx0, y=wy0, mode='markers',
                marker=dict(size=5, color='cyan', opacity=0.7),
                showlegend=False, hoverinfo='skip', name='Agua'))

            # Person
            fig.add_trace(go.Scatter(
                x=[person_x[0]], y=[person_y[0]],
                mode='markers+text',
                marker=dict(size=22, color='lime', symbol='circle',
                            line=dict(color='darkgreen', width=3)),
                text=['PERSONA'], textposition='top center',
                showlegend=False, name='Persona'))

            fig.update_layout(
                title=f"Simulación - Vuelta completa: {lap_time/60:.1f} min a {results.velocity_lap_m_s:.3f} m/s de recorrido",
                xaxis_title="X", yaxis_title="Y",
                plot_bgcolor='white', paper_bgcolor='white',
                width=1100, height=750,
                showlegend=True,
                legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01,
                            bgcolor='rgba(255,255,255,0.8)'),
                updatemenus=[{
                    'type': 'buttons',
                    'showactive': False,
                    'y': 0, 'x': 0.05,
                    'buttons': [
                        {'label': 'PLAY', 'method': 'animate',
                         'args': [None, {'frame': {'duration': 50, 'redraw': True},
                                         'fromcurrent': True, 'mode': 'immediate'}]},
                        {'label': 'PAUSE', 'method': 'animate',
                         'args': [[None], {'frame': {'duration': 0, 'redraw': False},
                                           'mode': 'immediate'}]}
                    ]
                }])
            fig.update_yaxes(scaleanchor='x', scaleratio=1)
            fig.frames = frames

            st.plotly_chart(fig, use_container_width=True)

            # Info panel
            st.markdown("---")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Velocidad de recorrido (L/T)",
                      f"{results.velocity_lap_m_s:.3f} m/s ({results.velocity_lap_m_s*3.6:.1f} km/h)")
            time_delta = (f"Objetivo: {target_lap_time_min:.1f} min" if target_lap_time_min else None)
            c2.metric("Tiempo de vuelta", f"{lap_time/60:.1f} min", delta=time_delta)
            c3.metric("Velocidad minima", f"{v_min:.3f} m/s")
            c4.metric("Velocidad maxima", f"{v_max:.3f} m/s")

            # Froude number
            froude_numbers = [s.froude_number for s in results.stations if hasattr(s, 'froude_number')]
            fr_max = max(froude_numbers) if froude_numbers else 0
            fr_status = "OK" if fr_max < 0.8 else ("REVISAR" if fr_max < 1.0 else "CRITICO")
            c5.metric("Froude max", f"{fr_max:.2f} ({fr_status})",
                      help="Criterio hidráulico preliminar: Fr < 0.8 mantiene flujo subcrítico. Requiere validación del ingeniero responsable.")

            # Smart jet placement info
            jets = model.propulsion.get_active_jets() if model.propulsion else []
            if jets and critical_zones:
                jets_in_critical = []
                jets_evenly = []
                for j in jets:
                    is_critical = False
                    for z in critical_zones:
                        if abs(j.station_m - z['chainage']) < 20:
                            is_critical = True
                            jets_in_critical.append(j)
                            break
                    if not is_critical:
                        jets_evenly.append(j)

                st.markdown("**Ubicacion de jets (colocacion inteligente):**")
                col_a, col_b = st.columns(2)
                with col_a:
                    st.info(f"🔴 **{len(jets_in_critical)} jets en zonas criticas** (baja velocidad)")
                    for j in jets_in_critical:
                        nearby_z = min(critical_zones, key=lambda z: abs(z['chainage'] - j.station_m))
                        st.write(f"  - Jet {j.jet_id}: chainage {j.station_m:.0f}m (V={nearby_z['velocity']:.3f} m/s)")
                with col_b:
                    st.success(f"🔵 **{len(jets_evenly)} jets distribuidos uniformemente**")
                    for j in jets_evenly:
                        st.write(f"  - Jet {j.jet_id}: chainage {j.station_m:.0f}m")

            # Velocity profile chart with ASTM compliance bands
            st.subheader("Perfil de Velocidad vs Chainage")
            fig_profile = go.Figure()

            # ASTM compliance bands (background)
            fig_profile.add_hrect(y0=0.3, y1=0.6, fillcolor="rgba(0,200,0,0.1)",
                                  line_width=0, annotation_text="ASTM OK (0.3-0.6 m/s)",
                                  annotation_position="top left")
            fig_profile.add_hrect(y0=0.2, y1=0.3, fillcolor="rgba(255,200,0,0.1)",
                                  line_width=0, annotation_text="Revisar",
                                  annotation_position="top left")
            fig_profile.add_hrect(y0=0.6, y1=0.8, fillcolor="rgba(255,200,0,0.1)",
                                  line_width=0)
            fig_profile.add_hrect(y0=0, y1=0.2, fillcolor="rgba(255,0,0,0.1)",
                                  line_width=0, annotation_text="Critico",
                                  annotation_position="top left")
            fig_profile.add_hrect(y0=0.8, y1=1.2, fillcolor="rgba(255,0,0,0.1)",
                                  line_width=0)

            # Velocity line
            fig_profile.add_trace(go.Scatter(
                x=chainages, y=velocities, mode='lines',
                name='Velocidad', line=dict(color='blue', width=2),
                fill='tozeroy', fillcolor='rgba(0,100,255,0.1)'))
            fig_profile.add_hline(y=v_avg, line_dash="dash", line_color="green",
                                  annotation_text=f"Promedio: {v_avg:.3f} m/s")
            fig_profile.add_hline(y=0.5, line_dash="dash", line_color="darkgreen",
                                  annotation_text="Objetivo: 0.50 m/s")
            # Mark critical zones
            for z in critical_zones:
                fig_profile.add_vrect(x0=z['chainage']-5, x1=z['chainage']+5,
                                       fillcolor="orange", opacity=0.2, line_width=0)
            fig_profile.update_layout(
                title="Velocidad a lo largo del circuito (con bandas ASTM)",
                xaxis_title="Chainage (m)", yaxis_title="Velocidad (m/s)",
                plot_bgcolor='white', paper_bgcolor='white', height=400,
                yaxis_range=[0, max(1.0, max(velocities) * 1.1)])
            st.plotly_chart(fig_profile, use_container_width=True)

            # Critical zones analysis
            if critical_zones:
                st.subheader("ZONAS CRITICAS - Donde considerar jets adicionales")
                st.warning(f"Se detectaron **{len(critical_zones)} zonas** con velocidad por debajo del "
                           f"umbral ({low_v_threshold:.3f} m/s). Considere instalar jets adicionales en estas ubicaciones.")

                zone_data = []
                for i, z in enumerate(critical_zones):
                    zone_data.append({
                        'Zona': f"Zona {i+1}",
                        'Chainage (m)': f"{z['chainage']:.1f}",
                        'Velocidad (m/s)': f"{z['velocity']:.3f}",
                        'Ancho (m)': f"{z['width']:.1f}",
                        'Recomendacion': 'Jet adicional recomendado' if z['velocity'] < low_v_threshold * 0.9 else 'Monitorear'
                    })
                st.dataframe(zone_data)

                explain("Por que hay zonas criticas?",
                        "Las zonas criticas son puntos donde el agua se mueve mas lento. "
                        "Esto puede deberse a que el canal es mas ancho ahi, o a que esta en una curva, "
                        "o a que no hay suficientes jets cerca. Instalar un jet adicional en esa zona "
                        "aumentaria la velocidad local.",
                        f"Umbral: {low_v_threshold:.3f} m/s\n"
                        f"Zonas detectadas: {len(critical_zones)}\n" +
                        "\n".join(f"  Zona {i+1}: chainage {z['chainage']:.1f}m, V={z['velocity']:.3f}m/s, W={z['width']:.1f}m"
                                  for i, z in enumerate(critical_zones)))
            else:
                st.success("No se detectaron zonas criticas. La velocidad es uniforme en todo el circuito.")

            # Manual exploration
            st.markdown("---")
            st.subheader("EXPLORACION MANUAL - Mover la persona por el circuito")
            st.markdown("Use el slider para desplazar la persona a cualquier punto del circuito "
                        "y ver la velocidad, el ancho y las condiciones locales.")

            chainage_slider = st.slider(
                "Posicion en el circuito (m)",
                min_value=0.0,
                max_value=float(total_length),
                value=0.0,
                step=1.0,
                help="Desplace para mover la persona a lo largo del circuito")

            # Get data at slider position
            v_at = float(np.interp(chainage_slider, chainages, velocities))
            w_at = float(np.interp(chainage_slider, chainages, [s['width_m'] for s in model.stations]))
            x_at = float(np.interp(chainage_slider, chainages, cl_x))
            y_at = float(np.interp(chainage_slider, chainages, cl_y))
            t_to_here = sum(
                (chainages[i+1] - chainages[i]) / max(velocities[i], 0.05)
                for i in range(len(velocities)-1)
                if chainages[i] < chainage_slider
            )

            # Display local data
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Velocidad local", f"{v_at:.3f} m/s ({v_at*3.6:.1f} km/h)")
            c2.metric("Ancho local", f"{w_at:.1f} m")
            c3.metric("Chainage", f"{chainage_slider:.0f} m")
            c4.metric("Tiempo hasta aqui", f"{t_to_here/60:.1f} min")
            c5.metric("Progreso", f"{chainage_slider/total_length*100:.0f}%")

            # Status at this point
            if v_at < low_v_threshold:
                st.warning(f"**ZONA DE BAJA VELOCIDAD** ({v_at:.3f} m/s < {low_v_threshold:.3f} m/s). "
                           f"Considere instalar un jet adicional en chainage {chainage_slider:.0f} m.")
            elif v_at > v_avg * 1.15:
                st.info(f"**ZONA DE ALTA VELOCIDAD** ({v_at:.3f} m/s). "
                        f"El agua se mueve rapido aqui.")
            else:
                st.success(f"**VELOCIDAD NORMAL** ({v_at:.3f} m/s).")

            # Mini chart showing position on velocity profile
            fig_mini = go.Figure()
            fig_mini.add_trace(go.Scatter(
                x=chainages, y=velocities, mode='lines',
                name='Velocidad', line=dict(color='blue', width=2)))
            fig_mini.add_trace(go.Scatter(
                x=[chainage_slider], y=[v_at], mode='markers',
                marker=dict(size=15, color='lime', symbol='circle',
                            line=dict(color='darkgreen', width=3)),
                name='Posicion actual'))
            fig_mini.add_hline(y=v_avg, line_dash="dash", line_color="green", opacity=0.5)
            fig_mini.update_layout(
                title="Posicion en el perfil de velocidad",
                xaxis_title="Chainage (m)", yaxis_title="Velocidad (m/s)",
                plot_bgcolor='white', paper_bgcolor='white', height=300,
                showlegend=False)
            st.plotly_chart(fig_mini, use_container_width=True)

    with tab_esc:
        st.subheader("Analisis de Escenarios")
        if st.button("Ejecutar todos los escenarios"):
            with st.spinner("Calculando escenarios..."):
                for sid in model.scenarios.get_all_ids():
                    model.run_scenario(sid, depth_m=depth_m, manning_n=manning_n,
                                       pump_flow_m3_h=total_pump_flow_effective, n_jets=n_jets,
                                       target_lap_time_min=target_lap_time_min,
                                       jet_diameter_m=jet_diam,
                                       pump_efficiency=pump_efficiency,
                                       n_pumps=n_pumps,
                                       safety_factor=safety_factor,
                                       n_pump_rooms=n_pump_rooms,
                                       water_temp_c=water_temp,
                                       pump_head_available_m=pump_head)

            comparison = model.scenarios.compare_results()
            if comparison:
                import pandas as pd
                df = pd.DataFrame(comparison)
                st.dataframe(df)

                fig = go.Figure()
                fig.add_trace(go.Bar(x=[c['name'] for c in comparison],
                                     y=[c['velocity_avg'] for c in comparison],
                                     name='Velocidad (m/s)'))
                fig.update_layout(title="Velocidad por Escenario",
                                  yaxis_title="Velocidad (m/s)")
                st.plotly_chart(fig, use_container_width=True)

        # Multi-configuration comparison
        st.markdown("---")
        st.subheader("Comparar Configuraciones")
        st.markdown("Guarde multiples configuraciones y comparelas lado a lado.")

        col_save, col_clear = st.columns(2)
        with col_save:
            config_name = st.text_input("Nombre de configuracion", value=f"Config {len(st.session_state.get('saved_configs', {})) + 1}")
            if st.button("Guardar configuracion actual"):
                if "saved_configs" not in st.session_state:
                    st.session_state["saved_configs"] = {}
                st.session_state["saved_configs"][config_name] = {
                    "velocity": results.velocity_lap_m_s,
                    "tdh": results.total_system_tdh_m,
                    "power": results.power_motor_kw,
                    "lap_time": results.lap_time_min,
                    "flow": total_pump_flow_effective,
                    "depth": depth_m,
                    "n_jets": n_jets,
                    "n_pumps": n_pumps,
                    "pump_flow": pump_flow,
                    "safety_factor": safety_factor,
                    "temp": water_temp,
                    "vfd": vfd_speed_pct if use_vfd else 100,
                }
                st.success(f"'{config_name}' guardada")

        with col_clear:
            if st.button("Limpiar todas las configuraciones"):
                st.session_state["saved_configs"] = {}
                st.success("Configuraciones limpiadas")

        # Show comparison table
        if "saved_configs" in st.session_state and st.session_state["saved_configs"]:
            configs = st.session_state["saved_configs"]
            params = ["Velocidad (m/s)", "TDH (m)", "Potencia (kW)", "Lap time (min)",
                      "Caudal (m3/h)", "Profundidad (m)", "Jets", "Bombas", "SF", "Temp (°C)", "VFD (%)"]
            comp_table = {"Parametro": params}
            for name, cfg in configs.items():
                comp_table[name] = [
                    f"{cfg['velocity']:.3f}", f"{cfg['tdh']:.2f}",
                    f"{cfg['power']:.1f}", f"{cfg['lap_time']:.1f}",
                    f"{cfg['flow']:.0f}", f"{cfg['depth']:.2f}",
                    f"{cfg['n_jets']}", f"{cfg['n_pumps']}",
                    f"{cfg.get('safety_factor', 1.15):.2f}",
                    f"{cfg.get('temp', 25):.0f}",
                    f"{cfg.get('vfd', 100):.0f}",
                ]
            # Add current
            comp_table["ACTUAL"] = [
                f"{results.velocity_lap_m_s:.3f}", f"{results.total_system_tdh_m:.2f}",
                f"{results.power_motor_kw:.1f}", f"{results.lap_time_min:.1f}",
                f"{total_pump_flow_effective:.0f}", f"{depth_m:.2f}",
                f"{n_jets}", f"{n_pumps}", f"{safety_factor:.2f}",
                f"{water_temp:.0f}", f"{vfd_speed_pct if use_vfd else 100:.0f}",
            ]
            st.dataframe(comp_table, use_container_width=True)

            # Radar chart comparison
            if len(configs) >= 1:
                fig_radar = go.Figure()
                categories = ['Velocidad', 'TDH', 'Potencia', 'Eficiencia']
                for name, cfg in configs.items():
                    v_norm = cfg['velocity'] / 0.5  # Normalize to target
                    tdh_norm = cfg['tdh'] / 10
                    p_norm = cfg['power'] / 500
                    eff_norm = 0.7  # Default efficiency
                    fig_radar.add_trace(go.Scatterpolar(
                        r=[v_norm, tdh_norm, p_norm, eff_norm],
                        theta=categories, fill='toself', name=name))
                # Add current
                v_norm = results.velocity_lap_m_s / 0.5
                tdh_norm = results.total_system_tdh_m / 10
                p_norm = results.power_motor_kw / 500
                fig_radar.add_trace(go.Scatterpolar(
                    r=[v_norm, tdh_norm, p_norm, 0.7],
                    theta=categories, fill='toself', name='ACTUAL',
                    line=dict(color='red', width=2)))
                fig_radar.update_layout(
                    title="Comparacion Radar (normalizado)",
                    polar=dict(radialaxis=dict(visible=True, range=[0, 2])),
                    showlegend=True, width=500, height=400)
                st.plotly_chart(fig_radar, use_container_width=True)

    with tab_val:
        st.subheader("Validacion: Modelo vs Campo")
        st.info("Cargue un CSV con mediciones de campo para comparar con el modelo.")
        field_file = st.file_uploader("Cargar CSV de campo", type=['csv'])
        if field_file:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as tmp:
                tmp.write(field_file.read())
                field_path = tmp.name
            model.field_loader.load_csv(field_path)
            measurements = model.field_loader.measurements
            if measurements:
                model.validation.load_field_data(measurements)
                comparisons = model.validation.compare_at_stations(results.stations)
                metrics = model.validation.compute_metrics(comparisons)
                suggestions = model.validation.calibration_suggestions(comparisons)

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Puntos", f"{metrics.get('n_points', 0)}")
                c2.metric("RMSE", f"{metrics.get('rmse', 0):.4f} m/s")
                c3.metric("MAE", f"{metrics.get('mae', 0):.4f} m/s")
                c4.metric("R2", f"{metrics.get('r_squared', 0):.3f}")

                if suggestions:
                    for s in suggestions:
                        st.warning(s)

    with tab_rep:
        st.subheader("Exportar Resultados")
        if st.button("Generar CSV de estaciones"):
            csv = model.export_stations_csv()
            st.download_button("Descargar CSV", csv, "estaciones_lazy_river.csv", "text/csv")

        if st.button("Generar resumen del proyecto"):
            summary = model.get_summary()
            st.json(summary)

        st.subheader("Validacion del Modelo")
        issues = model.validate_model()
        if issues:
            for issue in issues:
                st.warning(issue)
        else:
            st.success("Modelo validado sin errores.")

        # Technical details
        with st.expander("Ver calculos de ingenieria"):
            st.markdown("### Manning")
            st.code(f"V = (1/n) * R^(2/3) * S^(1/2)\nn = {manning_n}")
            st.markdown("### Darcy-Weisbach")
            st.code(f"hL = f * (L/Dh) * (V^2/2g)")
            st.markdown("### Reynolds")
            avg_rh = np.mean([s.hydraulic_radius_m for s in results.stations]) if results.stations else 0
            dh = 4 * avg_rh
            re = results.velocity_lap_m_s * dh / model.hydraulics.nu if dh > 0 else 0
            st.code(f"Re = V * Dh / nu = {re:.0f} ({'turbulento' if re > 4000 else 'laminar' if re < 2300 else 'transicion'})")

    with tab_ref:
        st.subheader("Referencia: Lazy Rivers del Mundo")
        st.markdown("Comparacion de datos tecnicos reales de lazy rivers operando en parques acuaticos internacionales.")

        # Reference projects table (cached)
        ref_cache = get_reference_data()
        ref_data = ref_cache['ref_table']
        st.subheader("Proyectos de Referencia")
        ref_table = []
        for r in ref_data:
            ref_table.append({
                "Proyecto": r["name"],
                "Longitud (m)": r["length_m"],
                "Ancho (m)": r["width_m"],
                "Profundidad (m)": r["depth_m"],
                "Velocidad (m/s)": r["velocity_m_s"],
                "Caudal (m3/h)": r["flow_m3_h"],
                "Bombas (HP)": r["pump_hp"],
                "Fuente": r["source"],
            })
        st.dataframe(ref_table, use_container_width=True)

        # Comparison with Selvatura
        st.subheader("Selvatura NYA vs Referencias")
        comparisons = compare_with_reference(
            results.velocity_lap_m_s,
            g.channel_width_avg_m,
            depth_m,
            g.channel_length_m,
            total_pump_flow,
            results.power_motor_kw
        )

        comp_table = []
        for c in comparisons:
            comp_table.append({
                "Proyecto": c["name"],
                "V ref (m/s)": c["ref_velocity"],
                "V Selvatura (m/s)": f"{c['project_velocity']:.3f}",
                "Diferencia (%)": f"{c['velocity_diff_pct']:+.1f}%",
                "Veredicto": c["verdict"],
            })
        st.dataframe(comp_table, use_container_width=True)

        # Design standards (cached)
        st.subheader("Estandares de Diseno")
        standards = ref_cache['standards']
        std_table = []
        for s in standards:
            std_table.append({
                "Parametro": s["parameter"],
                "Minimo": s["min"],
                "Maximo": s["max"],
                "Unidad": s["unit"],
                "Fuente": s["source"],
                "Nota": s["note"],
            })
        st.dataframe(std_table, use_container_width=True)

        # Check Selvatura against standards
        st.subheader("Selvatura NYA vs Estandares")
        checks = []
        for s in standards:
            param = s["parameter"]
            val = None
            if "velocidad" in param.lower():
                val = results.velocity_lap_m_s
            elif "profundidad" in param.lower():
                val = depth_m
            elif "ancho" in param.lower():
                val = g.channel_width_avg_m
            elif "longitud" in param.lower() or "tiempo" in param.lower():
                val = results.lap_time_min
            elif "manning" in param.lower():
                val = manning_n

            if val is not None:
                in_range = s["min"] <= val <= s["max"]
                checks.append({
                    "Parametro": param,
                    "Valor Selvatura": f"{val:.3f}",
                    "Rango": f"{s['min']} - {s['max']} {s['unit']}",
                    "Estado": "DENTRO" if in_range else "FUERA DE RANGO",
                    "Fuente": s["source"],
                })
        st.dataframe(checks, use_container_width=True)

        # Summary
        n_ok = sum(1 for c in checks if c["Estado"] == "DENTRO")
        n_out = sum(1 for c in checks if c["Estado"] == "FUERA DE RANGO")
        if n_out == 0:
            st.success(f"Selvatura NYA cumple con los {n_ok} estandares evaluados.")
        else:
            st.warning(f"Selvatura NYA cumple con {n_ok} de {len(checks)} estandares. "
                       f"{n_out} parametros fuera de rango.")

        # Pump types reference (cached)
        st.markdown("---")
        st.subheader("Tipos de Bombas para Lazy Rivers")
        pump_types = ref_cache['pump_types']
        for pt in pump_types:
            with st.expander(f"{pt['type']} — {pt['brand']}"):
                col_a, col_b = st.columns(2)
                with col_a:
                    st.write(f"**Marca:** {pt['brand']}")
                    st.write(f"**Modelo ejemplo:** {pt['model_example']}")
                    st.write(f"**Rango HP:** {pt['hp_range']}")
                    st.write(f"**Rango caudal:** {pt['flow_range']}")
                with col_b:
                    st.write(f"**Rango TDH:** {pt['head_range']}")
                    st.write(f"**Eficiencia:** {pt['efficiency']}")
                    st.write(f"**Aplicacion:** {pt['application']}")
                st.info(f"Notas: {pt['notes']}")

        # Jet types reference (cached)
        st.subheader("Tipos de Jets para Lazy Rivers")
        jet_types = ref_cache['jet_types']
        for jt in jet_types:
            with st.expander(f"{jt['type']} — {jt['brand']}"):
                col_a, col_b = st.columns(2)
                with col_a:
                    st.write(f"**Marca:** {jt['brand']}")
                    st.write(f"**Diametro:** {jt['diameter_range']}")
                    st.write(f"**Caudal/jet:** {jt['flow_per_jet']}")
                    st.write(f"**V_exit:** {jt['exit_velocity']}")
                with col_b:
                    st.write(f"**Angulo:** {jt['angle']}")
                    st.write(f"**Material:** {jt['material']}")
                    st.write(f"**Aplicacion:** {jt['application']}")
                st.info(f"Notas: {jt['notes']}")

    # === INFRAESTRUCTURA TAB ===
    with tab_infra:
        st.subheader("Infraestructura: Bombas, Tuberias y Jets")
        st.markdown("Diseno esquematico del sistema de bombeo y distribucion de flujo en el circuito.")

        if not (results and results.stations and model.geometry.centerline_coords):
            st.warning("No hay datos hidraulicos disponibles.")
        else:
            # Get infrastructure data
            jets = model.propulsion.get_active_jets() if model.propulsion else []
            pumps = model.pumps.pumps if model.pumps else []
            cl_coords = model.geometry.centerline_coords
            cl_x = [c[0] for c in cl_coords]
            cl_y = [c[1] for c in cl_coords]
            chainages = [s.chainage_m for s in results.stations]
            velocities = [s.velocity_m_s for s in results.stations]
            total_length = chainages[-1] if chainages else 536

            # --- SCHEMATIC MAP ---
            st.subheader("Plano Esquematico del Sistema")

            fig_infra = go.Figure()

            # Walls
            if model.loader and model.loader.outer_wall:
                oc = list(model.loader.outer_wall.coords)
                fig_infra.add_trace(go.Scatter(
                    x=[c[0] for c in oc], y=[c[1] for c in oc],
                    mode='lines', name='Muro Exterior',
                    line=dict(color='navy', width=2)))
            if model.loader and model.loader.inner_wall and model.loader.inner_wall != model.loader.outer_wall:
                ic = list(model.loader.inner_wall.coords)
                fig_infra.add_trace(go.Scatter(
                    x=[c[0] for c in ic], y=[c[1] for c in ic],
                    mode='lines', name='Muro Interior',
                    line=dict(color='darkred', width=2)))

            # Centerline (faded)
            fig_infra.add_trace(go.Scatter(
                x=cl_x, y=cl_y, mode='lines',
                line=dict(color='lightgray', width=1, dash='dot'),
                name='Centerline', showlegend=True))

            # Velocity heatmap on centerline
            v_min = min(velocities)
            v_max = max(velocities)
            for i in range(len(cl_x) - 1):
                v = velocities[i]
                v_norm = min(1.0, max(0.0, (v - v_min) / (v_max - v_min + 0.001)))
                r = int(255 * min(1, 2 * v_norm))
                g_val = int(255 * min(1, 2 * (1 - v_norm)))
                color = f'rgb({r},{g_val},100)'
                fig_infra.add_trace(go.Scatter(
                    x=[cl_x[i], cl_x[i+1]], y=[cl_y[i], cl_y[i+1]],
                    mode='lines', line=dict(color=color, width=6),
                    showlegend=(i == 0), name='Velocidad',
                    hovertemplate=f"V: {v:.3f} m/s<extra></extra>",
                    opacity=0.5))

            # Pump room locations (strategic positions based on n_pump_rooms)
            # 1 room: center (50%)
            # 2 rooms: 25% and 75%
            # 3 rooms: 16.7%, 50%, 83.3%
            pump_room_positions = []
            for room_i in range(n_pump_rooms):
                # Strategic position: (2*room_i + 1) / (2 * n_pump_rooms) of circuit
                frac = (2 * room_i + 1) / (2 * n_pump_rooms)
                target_chainage = frac * total_length
                # Find closest station
                closest_idx = min(range(len(chainages)), key=lambda i: abs(chainages[i] - target_chainage))
                pump_room_positions.append({
                    'idx': closest_idx,
                    'x': cl_x[closest_idx],
                    'y': cl_y[closest_idx],
                    'chainage': chainages[closest_idx],
                    'room_id': room_i + 1,
                })

            # Draw pump rooms
            for pr in pump_room_positions:
                fig_infra.add_trace(go.Scatter(
                    x=[pr['x']], y=[pr['y']],
                    mode='markers+text',
                    marker=dict(size=24, color='black', symbol='square',
                                line=dict(color='yellow', width=3)),
                    text=[f"B-{pr['room_id']}"], textposition='top center',
                    name='Cuarto de bombas' if pr['room_id'] == 1 else None,
                    showlegend=(pr['room_id'] == 1),
                    hovertemplate=f"Cuarto de bombas {pr['room_id']}<br>"
                                  f"Chainage: {pr['chainage']:.0f}m<br>"
                                  f"Caudal: {total_pump_flow/n_pump_rooms:.0f} m3/h<br>"
                                  f"TDH: {results.total_system_tdh_m:.2f}m<extra></extra>"))

            # Pipe runs (from nearest pump room to each jet)
            if jets:
                for j in jets:
                    # Find nearest pump room
                    nearest_pr = min(pump_room_positions, key=lambda pr: abs(pr['chainage'] - j.station_m))
                    fig_infra.add_trace(go.Scatter(
                        x=[nearest_pr['x'], j.x], y=[nearest_pr['y'], j.y],
                        mode='lines',
                        line=dict(color='dimgray', width=3, dash='dash'),
                        showlegend=False, hoverinfo='skip'))

            # Jet markers with spray visualization
            if jets:
                for j in jets:
                    # Jet marker
                    fig_infra.add_trace(go.Scatter(
                        x=[j.x], y=[j.y],
                        mode='markers+text',
                        marker=dict(size=14, color='red', symbol='diamond',
                                    line=dict(color='darkred', width=2)),
                        text=[f"J-{j.jet_id}"], textposition='top center',
                        name='Jets' if j.jet_id == 1 else None,
                        showlegend=(j.jet_id == 1),
                        hovertemplate=f"Jet {j.jet_id}<br>"
                                      f"Chainage: {j.station_m:.0f}m<br>"
                                      f"Caudal: {j.flow_m3_h:.0f} m3/h<br>"
                                      f"V_exit: {j.velocity_exit_m_s:.1f} m/s<br>"
                                      f"Diametro: {j.diameter_m*1000:.0f}mm<extra></extra>"))

                    # Spray lines (fan shape from jet)
                    angle_rad = math.radians(j.angle_deg)
                    spray_length = 5.0  # Visual length in DXF units
                    n_spray = 5
                    for s_i in range(n_spray):
                        spread = (s_i - n_spray/2) * 0.15  # Spread angle
                        a = angle_rad + spread
                        sx = j.x + math.cos(a) * spray_length
                        sy = j.y + math.sin(a) * spray_length
                        fig_infra.add_trace(go.Scatter(
                            x=[j.x, sx], y=[j.y, sy],
                            mode='lines',
                            line=dict(color='rgba(0,150,255,0.4)', width=2),
                            showlegend=False, hoverinfo='skip'))

            # Critical zones
            low_v_threshold = np.mean(velocities) * 0.85
            critical_zones = []
            in_zone = False
            zone_start = 0
            velocities_arr = velocities
            for i, v in enumerate(velocities_arr):
                if v < low_v_threshold and not in_zone:
                    in_zone = True
                    zone_start = i
                elif (v >= low_v_threshold or i == len(velocities_arr)-1) and in_zone:
                    in_zone = False
                    mid = (zone_start + i) // 2
                    critical_zones.append({
                        'chainage': chainages[mid],
                        'x': cl_x[mid], 'y': cl_y[mid],
                        'velocity': velocities_arr[mid],
                        'width': [s['width_m'] for s in model.stations][mid],
                    })

            if critical_zones:
                fig_infra.add_trace(go.Scatter(
                    x=[z['x'] for z in critical_zones],
                    y=[z['y'] for z in critical_zones],
                    mode='markers',
                    marker=dict(size=18, color='orange', symbol='triangle-up',
                                line=dict(color='darkorange', width=2)),
                    name='Zonas criticas',
                    hovertemplate='Zona critica<br>V: %{customdata[0]:.3f} m/s<br>'
                                  'Ancho: %{customdata[1]:.1f}m<extra></extra>',
                    customdata=[[z['velocity'], z['width']] for z in critical_zones]))

            fig_infra.update_layout(
                title="Sistema de Bombeo, Tuberias y Jets",
                xaxis_title="X", yaxis_title="Y",
                plot_bgcolor='white', paper_bgcolor='white',
                width=1100, height=700,
                legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01,
                            bgcolor='rgba(255,255,255,0.9)'))
            fig_infra.update_yaxes(scaleanchor='x', scaleratio=1)
            st.plotly_chart(fig_infra, use_container_width=True)

            # --- DATA TABLES ---
            st.markdown("---")
            col_pump, col_pipe = st.columns(2)

            with col_pump:
                st.subheader("Cuartos de Bombas")
                if pumps:
                    # Show pump rooms info
                    for pr in pump_room_positions:
                        st.markdown(f"**Cuarto {pr['room_id']}:** Chainage {pr['chainage']:.0f}m | "
                                   f"Caudal: {total_pump_flow/n_pump_rooms:.0f} m3/h")

                    st.markdown("---")
                    pump_data = []
                    for p in pumps:
                        pump_data.append({
                            "Bomba": f"P-{p.pump_id}",
                            "Modelo": p.model,
                            "Caudal (m3/h)": f"{p.flow_m3_h:.0f}",
                            "TDH (m)": f"{p.head_m:.2f}",
                            "Eficiencia": f"{p.efficiency:.0%}",
                            "Potencia (kW)": f"{p.motor_kw:.1f}",
                            "Potencia (HP)": f"{p.motor_kw * 1.341:.0f}",
                        })
                    st.dataframe(pump_data, use_container_width=True)

                    st.markdown(f"**Caudal total:** {total_pump_flow:.0f} m3/h")
                    st.markdown(f"**TDH sistema:** {results.total_system_tdh_m:.2f} m")

            with col_pipe:
                st.subheader("Tuberias")
                n_pipes = max(n_pumps, 2)
                Q_per_pipe = (total_pump_flow / 3600) / n_pipes
                v_target = 2.5
                d_pipe = np.sqrt(4 * Q_per_pipe / (np.pi * v_target))
                d_pipe = max(0.300, min(d_pipe, 0.800))
                pipe_len = min(total_length * 0.15, 80.0)

                pipe_data = []
                for i in range(n_pipes):
                    pipe_data.append({
                        "Tuberia": f"T-{i+1}",
                        "Diametro (mm)": f"{d_pipe*1000:.0f}",
                        "Material": "HDPE PN10",
                        "Longitud (m)": f"{pipe_len:.0f}",
                        "V (m/s)": f"{Q_per_pipe / (np.pi*(d_pipe/2)**2):.1f}",
                        "Rugosidad (f)": "0.013",
                    })
                st.dataframe(pipe_data, use_container_width=True)

                pipe_loss = 0.013 * (pipe_len / d_pipe) * (Q_per_pipe / (np.pi*(d_pipe/2)**2))**2 / (2 * 9.81)
                st.markdown(f"**Perdida por tuberia:** {pipe_loss:.3f} m")
                st.markdown(f"**Velocidad en tuberia:** {Q_per_pipe / (np.pi*(d_pipe/2)**2):.1f} m/s")

            st.markdown("---")
            st.subheader("Jets de Propulsion")
            if jets:
                jet_data = []
                for j in jets:
                    # Check if jet is in critical zone
                    is_critical = any(
                        abs(j.station_m - z['chainage']) < 20
                        for z in critical_zones
                    )
                    jet_data.append({
                        "Jet": f"J-{j.jet_id}",
                        "Chainage (m)": f"{j.station_m:.0f}",
                        "Caudal (m3/h)": f"{j.flow_m3_h:.0f}",
                        "Diametro (mm)": f"{j.diameter_m*1000:.0f}",
                        "V_exit (m/s)": f"{j.velocity_exit_m_s:.1f}",
                        "Angulo (deg)": f"{j.angle_deg}",
                        "Zona": "CRITICA" if is_critical else "Normal",
                    })
                st.dataframe(jet_data, use_container_width=True)

                n_critical_jets = sum(1 for j in jets if any(
                    abs(j.station_m - z['chainage']) < 20 for z in critical_zones))
                n_normal_jets = len(jets) - n_critical_jets
                st.info(f"**{n_critical_jets} jets** en zonas criticas | "
                        f"**{n_normal_jets} jets** distribuidos uniformemente")

            # --- LOSS BREAKDOWN ---
            st.markdown("---")
            st.subheader("Desglose de Perdidas del Sistema")
            loss_data = []
            for l in results.losses:
                pct = l.value_m / results.total_system_tdh_m * 100 if results.total_system_tdh_m > 0 else 0
                loss_data.append({
                    "Componente": l.name,
                    "Perdida (m)": f"{l.value_m:.3f}",
                    "TDH (%)": f"{pct:.1f}%",
                    "Detalle": l.source,
                })
            st.dataframe(loss_data, use_container_width=True)

            # Loss pie chart
            fig_loss = go.Figure(data=[go.Pie(
                labels=[l.name for l in results.losses],
                values=[l.value_m for l in results.losses],
                hole=0.3)])
            fig_loss.update_layout(title="Distribucion de Perdidas TDH",
                                    width=500, height=400)
            st.plotly_chart(fig_loss, use_container_width=False)

    # Footer
    st.markdown("---")
    st.caption("Selvatura NYA - Lazy River Hydraulic Digital Model v2.3 | "
               "Simulacion hidraulica 1D/2D simplificada | "
               "Con VFD, bombas comerciales, Sankey, modo oscuro | "
               "Modelo preliminar - requiere validacion de ingenieria y commissioning.")


if __name__ == "__main__":
    main()
