"""Local-only preview of an experimental shallow-water calculation for NYA.

Run with: streamlit run cfd_preview_local.py --server.port 8503
This file is intentionally NOT imported by the public app.
"""

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from core.orchestrator import LazyRiverModel
from core.riverflow_cfd_preview import compute_cfd_preview
from core.riverflow_model import compute_riverflow_plan


st.set_page_config(page_title="NYA · prueba CFD 2D local", layout="wide")
st.title("NYA · prueba local de hidráulica 2D")
st.warning("Experimento numérico de anteproyecto, NO CFD validado ni criterio para construir o comprar. "
           "Se resuelven agua y momento 2D promediados en profundidad sobre una malla del DXF. "
           "El fondo se simplifica por sección; tomas, forma de boquilla, turbulencia y bañistas no están resueltos.")


@st.cache_resource
def geometry():
    model = LazyRiverModel()
    issues = model.load_dxf("RECORRIDO.dxf")
    if issues or model.loader.errors:
        raise ValueError("No se pudo cargar el DXF de referencia.")
    model.build_centerline(target_length_m=536)
    return model


model = geometry()
with st.form("cfd_controls"):
    st.subheader("Escenario de prueba · sin cambiar el modelo público")
    a, b, c = st.columns(3)
    modules = a.number_input("Unidades Riverflow activas", 1, 40, 19)
    head_ft = b.slider("TDH local usada en curva (ft)", 4.0, 10.0, 4.0, .5)
    depth_m = c.slider("Profundidad principal (m)", .6, 2.0, 1.2, .05)
    d, e, f = st.columns(3)
    manning = d.slider("Manning compuesto · supuesto", .010, .035, .018, .001, format="%.3f")
    impulse = e.slider("Impulso que llega al agua · supuesto (%)", 1, 100, 10, 1,
                       help="Fracción de un límite ideal de momento Q·sqrt(2gH). NO es el 2% de energía del modelo principal.")
    duration_min = f.slider("Tiempo físico simulado (min)", 1, 10, 5)
    g, h = st.columns(2)
    cell_m = g.select_slider("Tamaño de celda (m)", [1.5, 2.0, 2.5, 3.0], value=2.5)
    mixing = h.slider("Mezcla horizontal · supuesto (m²/s)", .0, .5, .12, .02)
    run = st.form_submit_button("Ejecutar prueba local", type="primary")

if run:
    try:
        plan = compute_riverflow_plan(
            model.stations, depth_m=depth_m, target_lap_min=40,
            active_modules=modules, module_head_full_speed_ft=head_ft,
            manning_n_current=manning, manning_n_calm=manning,
            transfer_fraction=.02)
        with st.spinner("Calculando el campo transitorio 2D sobre el DXF…"):
            result = compute_cfd_preview(
                model, plan, cell_m=cell_m, duration_s=duration_min * 60,
                impulse_fraction=impulse / 100, mixing_m2_s=mixing)
        st.session_state["cfd_local_result"] = result
        st.session_state["cfd_local_summary"] = (modules, head_ft, depth_m, manning, impulse, duration_min, cell_m)
    except (ValueError, FloatingPointError) as exc:
        st.error(f"No se pudo completar la prueba: {exc}")

if "cfd_local_result" not in st.session_state:
    st.info("Pulsa «Ejecutar prueba local» para ver el mapa. El cálculo puede tardar unos segundos.")
    st.stop()

result = st.session_state["cfd_local_result"]
summary = st.session_state["cfd_local_summary"]
st.caption("Último cálculo: " + ", ".join(map(str, summary)) +
           " (unidades, TDH ft, profundidad m, Manning, impulso %, minutos, celda m).")
st.info("El agua parte en reposo. El mapa muestra solo los primeros "
        f"{result.duration_s / 60:.0f} minutos de arranque, NO una corriente estabilizada. "
        "No compare directamente estas velocidades con la vuelta o el mapa del modelo principal.")
wet_speed = result.speed_m_s[result.wet]
wet_along = result.along_m_s[result.wet]
q1, q2, q3, q4 = st.columns(4)
q1.metric("Velocidad media espacial", f"{np.mean(wet_speed):.3f} m/s")
q2.metric("Velocidad máxima de celda", f"{np.max(wet_speed):.3f} m/s")
q3.metric("Celdas con corriente inversa", f"{np.mean(wet_along < -.005):.1%}")
q4.metric("Variación máxima de superficie", f"{np.max(abs(result.surface_change_m[result.wet])):.3f} m")

left, right = st.columns([2, 1])
with left:
    st.subheader("Mapa de velocidad · instante final")
    fig = go.Figure()
    fig.add_trace(go.Heatmap(
        x=result.x_dxf, y=result.y_dxf,
        z=np.where(result.wet, result.speed_m_s, np.nan),
        colorscale="Turbo", colorbar=dict(title="m/s"),
        hovertemplate="Velocidad: %{z:.3f} m/s<extra></extra>"))
    for wall, name in ((model.loader.outer_wall, "Muro exterior DXF"),
                       (model.loader.inner_wall, "Muro interior DXF")):
        coordinates = list(wall.coords)
        fig.add_trace(go.Scatter(
            x=[p[0] for p in coordinates], y=[p[1] for p in coordinates],
            mode="lines", line=dict(color="#1e293b", width=2), name=name))
    fig.add_trace(go.Scatter(
        x=result.module_x_dxf, y=result.module_y_dxf, mode="markers",
        marker=dict(size=7, color="white", line=dict(color="#111827", width=1)),
        name="Descarga esquemática"))
    fig.update_layout(height=650, margin=dict(l=5, r=5, t=20, b=5),
                      xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x"),
                      legend=dict(orientation="h", y=-.08))
    st.plotly_chart(fig, width="stretch")
with right:
    st.subheader("Cómo leerlo")
    st.write("El color corresponde a la **rapidez del agua** al terminar el tiempo físico indicado, "
             "no al tiempo de vuelta de una persona. Las marcas blancas son descargas supuestas. "
             "La malla sigue el contorno del DXF; cada celda usa una profundidad y rugosidad aproximadas.")
    st.write("El porcentaje de impulso es un parámetro para explorar sensibilidad. "
             "Al cambiarlo, la corriente cambia, pero eso no identifica el valor real de NYA.")
    st.metric("Celdas mojadas", f"{result.wet_cell_count:,}")
    st.metric("Error de balance de agua", f"{result.water_balance_error_m3:.2e} m³")
    st.metric("Courant máximo", f"{result.max_courant:.2f}")
    st.caption("Balance y estabilidad son verificaciones numéricas, no validación física.")

st.info("Próximo paso antes de interpretar vueltas: representar tomas y descargas con caudales "
        "emparejados, comprobar convergencia de malla y tiempo, incorporar la pendiente lateral real "
        "de la playa y medir o acotar el impulso efectivo. Este prototipo no actualiza compras ni filtración.")
