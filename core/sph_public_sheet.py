"""Read-only, explicitly experimental SPlisHSPlasH sheet for Riverflow.

The bundled snapshot is one precomputed local run. No SPH solver is installed
or executed on Streamlit Community Cloud, and user controls do not alter it.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import streamlit as st

SNAPSHOT = Path(__file__).resolve().parents[1] / "data" / "sph_nya_24_reference.json"
COLORS = [[0, "#1e3a8a"], [.2, "#38bdf8"], [.5, "#22c55e"],
          [.75, "#fbbf24"], [1, "#dc2626"]]


@st.cache_data(show_spinner=False)
def load_snapshot() -> dict:
    result = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if result.get("schema_version") != 1 or not result.get("frames"):
        raise ValueError("La exportación SPH no tiene el formato esperado.")
    return result


def scenario_differences(snapshot: dict, *, length_m: float, depth_m: float,
                         pump_count: int, speed_fraction: float,
                         uploaded_dxf: bool, nozzle_type: str,
                         chainages_m: list[float] | tuple[float, ...],
                         banks: list[str] | tuple[str, ...]) -> list[str]:
    """Report only known differences; equality never proves physical validity."""
    differences = []
    if uploaded_dxf or abs(length_m - snapshot["length_m"]) > .01:
        differences.append("DXF o longitud")
    if abs(depth_m - 1.2) > .001:
        differences.append("profundidad (el ensayo no resuelve el perfil vertical)")
    if pump_count != snapshot["pump_count"]:
        differences.append("cantidad de bombas")
    if abs(speed_fraction - snapshot["speed_fraction"]) > .001:
        differences.append("variador")
    if nozzle_type != "7 puertos":
        differences.append("tipo de salida")
    ports = snapshot["ports"]
    if (len(chainages_m) != len(ports) or len(banks) != len(ports) or
            any(abs(float(position) - port["chainage_m"]) > 1.0 or bank != port["bank"]
                for position, bank, port in zip(chainages_m, banks, ports))):
        differences.append("posición u orilla de las bombas")
    return differences


def _particle_trace(frame: dict) -> go.Scattergl:
    points = np.asarray(frame["particles"], dtype=float)
    return go.Scattergl(
        x=points[:, 0], y=points[:, 1], mode="markers", name="Partículas mostradas",
        marker=dict(size=4, color=points[:, 2], cmin=0, cmax=.6,
                    colorscale=COLORS, showscale=True,
                    colorbar=dict(title="Rapidez m/s", x=1.01)),
        customdata=points[:, 2],
        hovertemplate="Rapidez instantánea %{customdata:.3f} m/s<extra></extra>",
    )


def particle_figure(snapshot: dict) -> go.Figure:
    fig = go.Figure()
    outline = snapshot["outline"]
    for ring in [outline["exterior"], *outline["interiors"]]:
        xy = np.asarray(ring, dtype=float)
        fig.add_trace(go.Scattergl(x=xy[:, 0], y=xy[:, 1], mode="lines",
                                   line=dict(color="#334155", width=2),
                                   hoverinfo="skip", showlegend=False))
    ports = snapshot["ports"]
    fig.add_trace(go.Scattergl(
        x=[p["xy_m"][0] for p in ports], y=[p["xy_m"][1] for p in ports],
        mode="markers", name="Descargas propuestas",
        marker=dict(symbol="diamond", size=9, color="#f97316"),
        text=[f"RF-{i:02d} · {p['bank']} · {p['chainage_m']:.1f} m"
              for i, p in enumerate(ports, 1)],
        hovertemplate="%{text}<extra></extra>"))
    particle_index = len(fig.data)
    frames = snapshot["frames"]
    fig.add_trace(_particle_trace(frames[-1]))
    fig.frames = [go.Frame(name=str(i), data=[_particle_trace(frame)],
                           traces=[particle_index]) for i, frame in enumerate(frames)]
    fig.update_layout(
        title="Movimiento SPH calculado · recorrido de 536 m · caso fijo de 24 CF104",
        height=680, margin=dict(l=25, r=95, t=60, b=80),
        xaxis=dict(title="Este local (m)", scaleanchor="y", scaleratio=1),
        yaxis=dict(title="Norte local (m)"),
        sliders=[dict(x=.12, len=.75, active=len(frames)-1,
                      currentvalue={"prefix": "Tiempo físico: "},
                      steps=[dict(label=f"{f['time_s']:.0f} s", method="animate",
                                  args=[[str(i)], {"mode": "immediate",
                                                    "frame": {"duration": 0, "redraw": True},
                                                    "transition": {"duration": 0}}])
                             for i, f in enumerate(frames)])],
        updatemenus=[dict(type="buttons", x=.01, y=-.09, showactive=False,
                          buttons=[dict(label="▶ Reproducir", method="animate",
                                        args=[None, {"frame": {"duration": 420, "redraw": True},
                                                     "transition": {"duration": 0},
                                                     "fromcurrent": False}]),
                                   dict(label="Pausar", method="animate",
                                        args=[[None], {"mode": "immediate",
                                                       "frame": {"duration": 0,
                                                                 "redraw": False}}])])],
    )
    return fig


def lane_heatmap(snapshot: dict) -> tuple[go.Figure, int]:
    recent = snapshot["frames"][-3:]
    values = np.asarray([f["lane_mean_along_m_s"] for f in recent], dtype=float)
    counts = np.asarray([f["lane_particle_count"] for f in recent], dtype=int)
    covered = np.all(counts >= 5, axis=0)
    beach_bins = snapshot.get("beach_section_indices", [])
    covered[np.asarray(beach_bins, dtype=int), :] = False
    persistent_reverse = int(np.sum(np.all(values < -.02, axis=0) & covered))
    means = np.mean(values, axis=0)
    means[~covered] = np.nan
    chainage = (np.arange(len(means)) + .5) * snapshot["length_m"] / len(means)
    fig = go.Figure(go.Heatmap(
        x=chainage, y=["Interior", "Centro", "Exterior"], z=means.T,
        zmin=-.6, zmax=.6, zmid=0, colorscale="RdBu",
        colorbar=dict(title="Avance m/s"),
        hovertemplate="Progresiva %{x:.0f} m<br>%{y}: %{z:.3f} m/s<extra></extra>"))
    fig.update_layout(title="Avance longitudinal · promedio de los últimos tres cuadros",
                      xaxis_title="Progresiva desde la playa principal (m)",
                      height=315, margin=dict(l=45, r=30, t=55, b=45))
    return fig, persistent_reverse


def render_sph_sheet(*, length_m: float, depth_m: float, pump_count: int,
                     speed_fraction: float, uploaded_dxf: bool, nozzle_type: str,
                     chainages_m: list[float] | tuple[float, ...],
                     banks: list[str] | tuple[str, ...]) -> None:
    st.subheader("SPlisHSPlasH · ensayo local del recorrido completo")
    st.warning("Resultado experimental, no calibrado y no apto para decidir compra, "
               "ubicación constructiva ni seguridad. No es una simulación 3D: "
               "el motor calcula partículas en una planta 2D horizontal.")
    try:
        snapshot = load_snapshot()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        st.error(f"No se pudo leer el escenario SPH publicado: {exc}")
        return
    differences = scenario_differences(
        snapshot, length_m=length_m, depth_m=depth_m,
        pump_count=pump_count, speed_fraction=speed_fraction,
        uploaded_dxf=uploaded_dxf, nozzle_type=nozzle_type,
        chainages_m=chainages_m, banks=banks)
    st.info("Esta hoja reproduce **una corrida guardada**. Cambiar los controles del menú "
            "Riverflow —incluidos Manning, playa y bombas— no recalcula SPlisHSPlasH. "
            "Para comparar otro diseño se necesita "
            "una nueva corrida local y una exportación verificada.")
    if differences:
        st.warning("El escenario activo difiere de esta corrida en: " +
                   ", ".join(differences) + ". No compare directamente sus velocidades o vueltas.")
    else:
        st.caption("Los controles principales coinciden, pero el punto de operación, "
                   "la orientación fina, la fricción y el perfil de playa no están "
                   "verificados como equivalentes.")
    c = st.columns(5)
    c[0].metric("CF104 de este ensayo", snapshot["pump_count"])
    c[1].metric("Variador supuesto", f"{snapshot['speed_fraction']:.0%}")
    c[2].metric("Caudal de referencia/unidad", f"{snapshot['pump_flow_m3_h']:.0f} m³/h")
    c[3].metric("Salida agregada", f"{snapshot['aggregate_nozzle_speed_m_s']:.2f} m/s")
    c[4].metric("Tiempo físico calculado", f"{snapshot['simulated_s']/60:.0f} min")
    st.caption("La rapidez de salida **no** es la velocidad del río. Usa el área abierta "
               "total del acelerador; los siete chorros individuales no están resueltos.")
    st.plotly_chart(particle_figure(snapshot), width="stretch")
    st.caption("Los colores muestran rapidez instantánea de las partículas visibles, "
               "no seguridad. Se muestran 220 partículas por cuadro para que cargue en la web; "
               f"el cálculo utilizó {snapshot['initial_particles']:,}. "
               "La escala de color permanece fija entre cuadros.")
    heatmap, reverse_cells = lane_heatmap(snapshot)
    st.plotly_chart(heatmap, width="stretch")
    st.caption(f"{reverse_cells} celdas fuera de la playa con avance contrario persistente "
               "en los tres cuadros "
               "mostrados al final. Son alertas para investigar, no remolinos certificados. "
               "Las celdas sin suficientes partículas y las de la playa quedan vacías. "
               "La rampa y la arena no están representadas.")
    times = [frame["time_s"] / 60 for frame in snapshot["frames"]]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=times,
                             y=[frame["mean_along_m_s"] for frame in snapshot["frames"]],
                             mode="lines+markers", name="Avance medio de partículas"))
    fig.update_layout(title="Evolución desde agua en reposo",
                      xaxis_title="Tiempo físico simulado (min)",
                      yaxis_title="Avance longitudinal medio (m/s)", height=300,
                      margin=dict(l=40, r=20, t=50, b=40))
    st.plotly_chart(fig, width="stretch")
    st.caption("No se impuso 0,25–0,30 m/s al iniciar. Esta media de partículas no es "
               "la velocidad efectiva de una persona que recorre todo el río.")
    lap = snapshot["conditional_lap_min"]
    if lap is not None:
        st.metric("Vuelta por secciones · condicional, no persona", f"{lap:.1f} min")
        st.caption(snapshot["conditional_lap_reason"])
    else:
        st.metric("Vuelta por secciones", "No estimable")
        st.caption(snapshot["conditional_lap_reason"])
    st.warning("La comprobación de repetición todavía falla: dos corridas de 24 bombas "
               "al 85 % y 20 min dieron resultados distintos, y una tuvo secciones con "
               "muy pocas partículas. No se publica un tiempo de vuelta previsto.")
    with st.expander("Comprobaciones, corridas y límites del ensayo"):
        st.dataframe([{"Corrida": row["run"],
                       "Avance medio final (m/s)": row["mean_along_m_s"],
                       "Partículas en contra (%)": round(row["reverse_fraction"]*100, 1),
                       "Vuelta condicional (min)": row["lap_min"],
                       "Motivo": row["lap_reason"]}
                      for row in snapshot["repeat_check"]],
                     hide_index=True, width="stretch")
        st.write(f"Partículas: {snapshot['initial_particles']:,} → "
                 f"{snapshot['final_particles']:,}; "
                 f"{snapshot['transfer_events']:,} traslados de bombeo; "
                 f"{snapshot['missed_suction_events']} tomas sin partícula cercana "
                 "en la corrida mostrada. Esto comprueba integridad numérica parcial, "
                 "no validez física.")
        st.write("Limitaciones: " + "; ".join(snapshot["limits"]) + ".")
        st.caption(f"Archivo de referencia: {snapshot['source_dxf']}. "
                   "La escena histórica no guardó la huella digital del DXF; "
                   "la identidad exacta del archivo usado en aquella corrida no se "
                   "puede certificar retrospectivamente.")
    st.info("La filtración sanitaria permanece en la hoja «Filtración»: el caudal "
            "de tratamiento no se suma a las descargas de propulsión de este ensayo.")
