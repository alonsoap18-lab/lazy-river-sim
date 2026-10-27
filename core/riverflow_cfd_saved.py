"""Read and display the saved NYA OpenFOAM screening cases in Streamlit.

These fixed fields never recalculate when Riverflow app controls change.
"""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "cfd_nya_1200"
COUNTS = (16, 19, 20, 21)
COLORS = [[0, "#632b94"], [.2, "#2452ae"], [.35, "#4bb8d2"],
          [.5, "#3aa674"], [.65, "#f0d35d"], [.8, "#eb8736"], [1, "#b52c37"]]
NAMES = {16: "16 · menos impulso", 19: "19 · quitar una",
         20: "20 · referencia", 21: "21 · añadir en bahía"}


@lru_cache(maxsize=1)
def load_metadata() -> tuple[dict, dict]:
    manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
    results = json.loads((ASSETS / "results.json").read_text(encoding="utf-8"))
    if (manifest["schema"] != 1 or manifest["mesh_cells"] != 4056 or
            manifest["length_m"] != 536.0 or len(results["cases"]) != 4):
        raise ValueError("Paquete CFD NYA incompatible")
    if set(map(int, manifest["scenarios"])) != set(COUNTS):
        raise ValueError("Falta un escenario CFD guardado")
    return manifest, results


@lru_cache(maxsize=1)
def load_geometry() -> dict[str, np.ndarray]:
    with np.load(ASSETS / "geometry.npz", allow_pickle=False) as package:
        geometry = {key: package[key] for key in package.files}
    if (geometry["centres_xyz_m"].shape != (4056, 3) or
            geometry["cell_tangent_xy"].shape != (4056, 2) or
            geometry["cell_volume_m3"].shape != (4056,) or
            np.any(geometry["cell_volume_m3"] <= 0)):
        raise ValueError("Geometría CFD guardada inválida")
    return geometry


@lru_cache(maxsize=4)
def load_scenario(count: int) -> dict[str, np.ndarray]:
    if count not in COUNTS:
        raise ValueError(f"Cantidad CFD no disponible: {count}")
    manifest, _ = load_metadata()
    path = ASSETS / manifest["scenarios"][str(count)]["bundle"]
    with np.load(path, allow_pickle=False) as package:
        data = {key: package[key] for key in package.files}
    if (data["u"].shape != (11, 4056, 3) or
            data["time_s"].shape != (11,) or
            data["k"].shape != (4056,) or
            not np.all(np.isfinite(data["u"])) or
            not np.all(np.diff(data["time_s"]) > 0) or
            not 1198 <= data["time_s"][-1] <= 1201):
        raise ValueError("Campos CFD guardados inválidos")
    return data


def source_dxf_matches() -> bool:
    manifest, _ = load_metadata()
    # Git stores the DXF with LF while Windows checks it out with CRLF.
    normalized = (ROOT / "RECORRIDO.dxf").read_bytes().replace(b"\r\n", b"\n")
    return (hashlib.sha256(normalized).hexdigest()
            == manifest["source_dxf_sha256"])


def _pump_points(manifest: dict, count: int) -> tuple[np.ndarray, list[str]]:
    pumps = manifest["scenarios"][str(count)]["pumps"]
    xy = np.asarray([pump["jet_xy_m"] for pump in pumps], dtype=float)
    labels = [f"RF-{pump['number']:02d} · {pump['chainage_m']:.0f} m · {pump['bank']}"
              for pump in pumps]
    if len(xy) != count:
        raise ValueError("Cantidad y posiciones CFD no coinciden")
    return xy, labels


def _outlines(fig: go.Figure, geometry: dict, *, row: int | None = None,
              col: int | None = None) -> None:
    for name in ("outer_xy_m", "inner_xy_m"):
        ring = geometry[name]
        trace = go.Scattergl(x=ring[:, 0], y=ring[:, 1], mode="lines",
                             line=dict(color="#26353d", width=1.8),
                             showlegend=False, hoverinfo="skip")
        if row is None:
            fig.add_trace(trace)
        else:
            fig.add_trace(trace, row=row, col=col)


def _arrows(xy: np.ndarray, u: np.ndarray) -> tuple[list[float | None],
                                                     list[float | None]]:
    xx: list[float | None] = []
    yy: list[float | None] = []
    for point, vector in zip(xy[::13], u[::13]):
        mag = float(np.linalg.norm(vector))
        if mag < .025:
            continue
        end = point + np.clip(9*mag, 0, 4.5)*vector/mag
        xx.extend((float(point[0]), float(end[0]), None))
        yy.extend((float(point[1]), float(end[1]), None))
        normal = np.array([-vector[1], vector[0]])/mag
        head = min(.75, .33*np.linalg.norm(end-point))
        for wing in (1, -1):
            start = end - head*vector/mag + .45*wing*head*normal
            xx.extend((float(start[0]), float(end[0]), None))
            yy.extend((float(start[1]), float(end[1]), None))
    return xx, yy


def _animation_controls(times: np.ndarray, *, frame_ms: int) -> tuple[list[dict],
                                                                     list[dict]]:
    names = [str(index) for index in range(len(times))]
    slider = [dict(active=len(times)-1, currentvalue=dict(prefix="Tiempo físico: ", suffix=" s"),
                   steps=[dict(label=f"{time:.0f}", method="animate",
                               args=[[name], {"mode": "immediate",
                                              "frame": {"duration": 0, "redraw": True},
                                              "transition": {"duration": 0}}])
                          for name, time in zip(names, times)])]
    buttons = [dict(type="buttons", showactive=False, x=.02, y=1.07,
                    buttons=[
                        dict(label="▶ Reproducir campos CFD", method="animate",
                             args=[None, {"frame": {"duration": frame_ms, "redraw": True},
                                          "fromcurrent": False,
                                          "transition": {"duration": 0}}]),
                        dict(label="Pausa", method="animate",
                             args=[[None], {"frame": {"duration": 0},
                                            "mode": "immediate"}]),
                    ])]
    return slider, buttons


def figure_2d(count: int, layer: str = "velocidad") -> go.Figure:
    geometry = load_geometry()
    data = load_scenario(count)
    manifest, _ = load_metadata()
    centres = geometry["centres_xyz_m"]
    xy = centres.reshape(-1, 4, 3)[:, 0, :2]
    tangent = geometry["cell_tangent_xy"]
    forward = np.einsum("fij,ij->fi", data["u"][:, :, :2], tangent)
    planar = forward.reshape(len(data["time_s"]), -1, 4).mean(axis=2)
    if layer == "k":
        color = data["k"].reshape(-1, 4).mean(axis=1)
        title = "Energía turbulenta modelada k (m²/s²)"
    elif layer == "velocidad":
        color = planar[-1]
        title = "Velocidad longitudinal (m/s)"
    else:
        raise ValueError("Capa CFD desconocida")
    fig = go.Figure()
    marker = dict(size=7, color=color, colorscale=COLORS if layer == "velocidad" else "Turbo",
                  cmin=-.2 if layer == "velocidad" else 0,
                  cmax=.8 if layer == "velocidad" else float(np.quantile(color, .99)),
                  showscale=True, colorbar=dict(title=title))
    fig.add_trace(go.Scattergl(x=xy[:, 0], y=xy[:, 1], mode="markers",
        marker=marker, name="Celdas OpenFOAM",
        hovertemplate=f"{title}: %{{marker.color:.4f}}<extra></extra>"))
    arrow_x, arrow_y = _arrows(
        xy, data["u"][-1].reshape(-1, 4, 3)[:, :, :2].mean(axis=1))
    fig.add_trace(go.Scattergl(x=arrow_x, y=arrow_y, mode="lines",
        line=dict(color="#173044", width=1.4), name="Dirección de U calculada",
        hoverinfo="skip"))
    _outlines(fig, geometry)
    pumps, labels = _pump_points(manifest, count)
    fig.add_trace(go.Scattergl(x=pumps[:, 0], y=pumps[:, 1], mode="markers",
        marker=dict(symbol="diamond", size=10, color="#ff921b",
                    line=dict(color="#26353d", width=1)),
        name="Descargas equivalentes", text=labels,
        hovertemplate="%{text}<extra></extra>"))
    if layer == "velocidad":
        frames = []
        for i, (u, current) in enumerate(zip(data["u"], planar)):
            ax, ay = _arrows(xy, u.reshape(-1, 4, 3)[:, :, :2].mean(axis=1))
            frames.append(go.Frame(name=str(i), traces=[0, 1],
                data=[go.Scattergl(marker=dict(color=current)),
                      go.Scattergl(x=ax, y=ay)]))
        fig.frames = frames
        sliders, buttons = _animation_controls(data["time_s"], frame_ms=650)
        fig.update_layout(sliders=sliders, updatemenus=buttons)
    fig.update_layout(
        title=f"NYA 536 m · {count} CF104 equivalentes · {'campo transitorio' if layer == 'velocidad' else 'k a 1200 s'}",
        xaxis=dict(title="Este local (m)", scaleanchor="y", scaleratio=1),
        yaxis=dict(title="Norte local (m)"),
        height=790, uirevision=f"nyacfd2d-{count}-{layer}",
        margin=dict(l=20, r=25, t=65, b=70))
    return fig


def figure_3d(count: int, layer: str = "velocidad",
              vertical_scale: float = 20.0) -> go.Figure:
    geometry = load_geometry()
    data = load_scenario(count)
    manifest, _ = load_metadata()
    tangent = geometry["cell_tangent_xy"]
    forward = np.einsum("fij,ij->fi", data["u"][:, :, :2], tangent)
    if layer == "k":
        color = data["k"]
        title = "k modelada (m²/s²)"
    elif layer == "velocidad":
        color = forward[-1]
        title = "V longitudinal (m/s)"
    else:
        raise ValueError("Capa CFD desconocida")
    fig = go.Figure()
    for name, shade, opacity in (("floor", "#5f9eaf", 1.0),
                                 ("innerWall", "#81827c", .78),
                                 ("outerWall", "#81827c", .78),
                                 ("lid", "#9ddfee", .12)):
        points = geometry[f"{name}_xyz_m"]
        triangles = geometry[f"{name}_triangles"]
        fig.add_trace(go.Mesh3d(
            x=points[:, 0], y=points[:, 1], z=points[:, 2]*vertical_scale,
            i=triangles[:, 0], j=triangles[:, 1], k=triangles[:, 2],
            color=shade, opacity=opacity, name=name,
            hoverinfo="skip", flatshading=True))
    centres = geometry["centres_xyz_m"]
    fig.add_trace(go.Scatter3d(
        x=centres[:, 0], y=centres[:, 1], z=centres[:, 2]*vertical_scale,
        mode="markers", name="Campo OpenFOAM",
        marker=dict(size=2.2, opacity=.42, color=color,
                    colorscale=COLORS if layer == "velocidad" else "Turbo",
                    cmin=-.2 if layer == "velocidad" else 0,
                    cmax=.8 if layer == "velocidad" else float(np.quantile(color, .99)),
                    showscale=True, colorbar=dict(title=title))))
    pumps, labels = _pump_points(manifest, count)
    fig.add_trace(go.Scatter3d(
        x=pumps[:, 0], y=pumps[:, 1], z=np.full(count, -.5*vertical_scale),
        mode="markers", name=f"{count} descargas equivalentes", text=labels,
        marker=dict(size=5, color="#ff921b", symbol="diamond"),
        hovertemplate="%{text}<extra></extra>"))
    if layer == "velocidad":
        fig.frames = [go.Frame(name=str(i), traces=[4],
                               data=[go.Scatter3d(marker=dict(color=field))])
                      for i, field in enumerate(forward)]
        sliders, buttons = _animation_controls(data["time_s"], frame_ms=650)
        fig.update_layout(sliders=sliders, updatemenus=buttons)
    fig.update_layout(
        title=f"NYA 3D · {count} CF104 · {'campos en el tiempo' if layer == 'velocidad' else 'k a 1200 s'}",
        height=790, uirevision=f"nyacfd3d-{count}-{layer}-{vertical_scale}",
        margin=dict(l=0, r=0, t=65, b=70),
        scene=dict(aspectmode="data", dragmode="orbit",
                   xaxis_title="Este (m)", yaxis_title="Norte (m)",
                   zaxis_title=f"Cota ×{vertical_scale:g} solo visual"))
    return fig


def figure_comparison() -> go.Figure:
    geometry = load_geometry()
    centres = geometry["centres_xyz_m"]
    xy = centres.reshape(-1, 4, 3)[:, 0, :2]
    tangent = geometry["cell_tangent_xy"]
    manifest, _ = load_metadata()
    fig = make_subplots(rows=2, cols=2, subplot_titles=tuple(NAMES[count] for count in COUNTS),
                        horizontal_spacing=.075, vertical_spacing=.11)
    for index, count in enumerate(COUNTS):
        row, col = divmod(index, 2)
        row += 1
        col += 1
        u = load_scenario(count)["u"][-1]
        forward = np.einsum("ij,ij->i", u[:, :2], tangent).reshape(-1, 4).mean(axis=1)
        fig.add_trace(go.Scattergl(
            x=xy[:, 0], y=xy[:, 1], mode="markers", showlegend=False,
            marker=dict(size=5.5, color=forward, colorscale=COLORS,
                        cmin=-.2, cmax=.8, showscale=count == 21,
                        colorbar=dict(title="Avance<br>m/s")),
            customdata=forward,
            hovertemplate="V longitudinal %{customdata:.3f} m/s<extra></extra>"),
            row=row, col=col)
        _outlines(fig, geometry, row=row, col=col)
        pumps, _ = _pump_points(manifest, count)
        fig.add_trace(go.Scattergl(x=pumps[:, 0], y=pumps[:, 1],
            mode="markers", showlegend=False,
            marker=dict(symbol="diamond", size=6, color="#ff921b")),
            row=row, col=col)
        axis_name = f"x{index+1}" if index else "x"
        fig.update_xaxes(title_text="Este local (m)", row=row, col=col)
        fig.update_yaxes(title_text="Norte local (m)", scaleanchor=axis_name,
                         scaleratio=1, row=row, col=col)
    fig.update_layout(title="Misma escala de color · cuatro escenarios CFD a 1200 s",
                      height=1050, margin=dict(l=20, r=20, t=70, b=40))
    return fig


def comparison_rows() -> list[dict]:
    _, results = load_metadata()
    rows = []
    for count in COUNTS:
        name = {16: "16_removed_four", 19: "19_removed",
                20: "20_original", 21: "21_added_downstream"}[count]
        snapshot = results["cases"][name]["snapshots"]["1200"]
        regions = snapshot["regions"]
        rows.append({
            "Bombas": count,
            "Vuelta hidráulica proyectada (min)": round(snapshot["stationary_hydraulic_lap_min"], 1),
            "Zonas anchas · mediana (m/s)": round(regions["wide_ge_15m"]["median_forward_m_s"], 3),
            "Zonas anchas <0,15 m/s (%)": round(100*regions["wide_ge_15m"]["slow_below_0_15_fraction"], 1),
            "Pasajes angostos · mediana (m/s)": round(regions["narrow_lt_10m"]["median_forward_m_s"], 3),
            "k mediana RANS (m²/s²)": round(regions["all"]["k_median_m2_s2"], 4),
        })
    return rows


def render_saved_cfd(plan, speed_pct: int, uploaded_dxf: bool, *,
                     floor_n: float, wall_n_current: float, wall_n_calm: float,
                     depth_m: float, nozzle_type: str,
                     beach_flat_m: float | None, beach_ramp_pct: float) -> None:
    import streamlit as st
    from core.riverflow_cfd_decision import (attention_rows,
        compare_editable_to_saved, section_comparison_figure, section_profile)

    try:
        manifest, results = load_metadata()
        load_geometry()
    except (OSError, KeyError, ValueError) as exc:
        st.error(f"No se pudo cargar el paquete CFD guardado: {exc}")
        return
    st.subheader("Ensayo OpenFOAM · recorrido completo 2D/3D")
    st.caption(
        "Cuatro corridas NYA de 1200 s: DXF de 536 m, malla de 4056 celdas, "
        "Manning equivalente piso 0,013 / paredes 0,025, caudal de referencia "
        "2014 US gpm por CF104. Colores y flechas proceden de U calculada; "
        "las siete salidas de cada unidad siguen agrupadas en una descarga equivalente.")
    if not source_dxf_matches():
        st.warning("El DXF base cambió desde estas corridas. Los mapas siguen mostrando "
                   "la geometría CFD archivada y no representan el plano actual.")
    if uploaded_dxf:
        st.warning("Hay un DXF cargado en esta sesión. Este ensayo conserva el DXF NYA "
                   "usado al generarlo; no se recalcula con el archivo cargado.")
    initial_scenario = plan.active_modules if plan.active_modules in COUNTS else 20
    scenario = st.selectbox("Corrida CFD guardada · bombas activas", COUNTS,
                            index=COUNTS.index(initial_scenario),
                            format_func=lambda number: NAMES[number],
                            key="rf_saved_cfd_count")
    compare_rows, comparison = compare_editable_to_saved(
        plan, scenario, floor_n, wall_n_current, wall_n_calm, depth_m,
        uploaded_dxf, source_dxf_matches(), nozzle_type, beach_flat_m,
        beach_ramp_pct)
    st.markdown("**Entradas editables frente a la corrida guardada**")
    st.dataframe([{**row, "Coincide": "Sí" if row["Coincide"] else "No"}
                  for row in compare_rows], width="stretch", hide_index=True)
    if comparison["all_match"]:
        st.info("Las entradas comparadas son próximas a las del ensayo. Su campo sigue "
                "archivado: editar una bomba no recalcula OpenFOAM. La orientación local "
                "de las siete salidas tampoco está resuelta en este CFD.")
    else:
        st.warning("El escenario editable y esta corrida tienen entradas diferentes. "
                   "Sus velocidades y vuelta no son resultados del menú actual. "
                   "Se necesita ejecutar otro CFD para evaluar las nuevas posiciones, "
                   "caudales, rugosidades o geometría.")
    case_name = {16: "16_removed_four", 19: "19_removed",
                 20: "20_original", 21: "21_added_downstream"}[scenario]
    current = results["cases"][case_name]["snapshots"]["1200"]
    region = current["regions"]
    c1, c2 = st.columns(2)
    c1.metric("Vuelta hidráulica proyectada",
              f"{current['stationary_hydraulic_lap_min']:.1f} min")
    c2.metric("Avance mediano · zonas anchas",
              f"{region['wide_ge_15m']['median_forward_m_s']:.3f} m/s")
    c3, c4 = st.columns(2)
    c3.metric("Zonas anchas con avance <0,15",
              f"{region['wide_ge_15m']['slow_below_0_15_fraction']:.1%}")
    c4.metric("Avance mediano · angostos",
              f"{region['narrow_lt_10m']['median_forward_m_s']:.3f} m/s")
    st.caption(
        "La vuelta suma 8 m / velocidad media longitudinal de cada una de 67 secciones, "
        "suponiendo estable el campo final. No es el recorrido cronometrado de personas. "
        "En esta malla a 1200 s no hubo celdas con retorno longitudinal menor que −0,02 m/s; "
        "eso no excluye remolinos pequeños o peligros junto a tomas y paredes.")
    view = st.radio("Ver ensayo", ("2D animado", "3D interactivo", "Comparar escenarios"),
                    horizontal=True, key="rf_saved_cfd_view")
    if view != "Comparar escenarios":
        layer = st.radio("Color del agua", ("Velocidad", "Turbulencia k"),
                         horizontal=True, key="rf_saved_cfd_layer")
        if layer == "Turbulencia k":
            st.caption("k es energía turbulenta calculada por RANS k-ε a 1200 s, "
                       "sin calibración ni umbral de seguridad. Esta capa es fija; "
                       "elige Velocidad para reproducir la evolución temporal.")
        else:
            st.caption("Reproduce cuadros calculados cada ~120 s de tiempo físico; "
                       "la reproducción en pantalla acelera esos cuadros y no representa "
                       "el tiempo real de una vuelta.")
        mode = "k" if layer == "Turbulencia k" else "velocidad"
        if view == "2D animado":
            figure = figure_2d(scenario, mode)
        else:
            scale = st.select_slider("Altura visual del 3D",
                                     options=(1, 5, 10, 20), value=20,
                                     format_func=lambda value:
                                     "1× real" if value == 1 else f"{value}× resaltada",
                                     key="rf_saved_cfd_vertical_scale")
            st.caption("La cota se multiplica solo para que se vea la profundidad; "
                       "los cálculos conservan la geometría original. Puedes girar, "
                       "arrastrar y acercar la cámara con el ratón.")
            figure = figure_3d(scenario, mode, float(scale))
        st.plotly_chart(figure, width="stretch",
                        config={"scrollZoom": True, "displayModeBar": True},
                        key=f"rf_saved_cfd_{view}_{scenario}_{mode}")
    else:
        st.dataframe(comparison_rows(), width="stretch", hide_index=True)
        st.plotly_chart(figure_comparison(), width="stretch",
                        config={"scrollZoom": True, "displayModeBar": True},
                        key="rf_saved_cfd_comparison")
        st.caption("Las 16 se acercan a 30 min pero dejan 37,5 % de zonas anchas por "
                   "debajo de 0,15 m/s. Las 20 reducen ese porcentaje a 21,4 %. "
                   "La unidad 21 no mejora ese indicador. Ninguna cifra determina "
                   "todavía la cantidad definitiva de compra.")
    st.markdown("**Dónde cambia el avance · secciones de 8 m**")
    st.plotly_chart(section_comparison_figure(scenario), width="stretch",
                    config={"scrollZoom": True, "displayModeBar": True},
                    key=f"rf_saved_cfd_sections_{scenario}")
    st.caption("Cada línea usa la velocidad longitudinal media ponderada por volumen "
               "de las celdas de una sección; las cuatro corridas comparten malla. "
               "Las bandas de 0,15 y 0,50 m/s son filtros de exploración, no límites "
               "de seguridad. Naranja abajo marca descargas de la corrida elegida. "
               "La playa principal sombreada se interpreta aparte.")
    alerts = attention_rows(scenario)
    wide = [row for row in alerts if row["Observación"].startswith("Paso ancho")]
    narrow = [row for row in alerts if row["Observación"].startswith("Paso angosto")]
    c_wide, c_narrow = st.columns(2)
    c_wide.metric("Pasos anchos con carril lento", len(wide))
    c_narrow.metric("Pasos angostos con avance alto", len(narrow))
    for title, values in (("Pasos anchos a revisar", wide),
                          ("Pasos angostos a revisar", narrow)):
        st.markdown(f"**{title}**")
        if values:
            st.dataframe([{key: value for key, value in row.items()
                           if key != "severidad"} for row in values[:6]],
                         width="stretch", hide_index=True)
        else:
            st.caption("Ninguna sección supera el filtro de este ensayo.")
    with st.expander("Ver las 67 secciones del escenario seleccionado"):
        st.dataframe([{
            "Tramo": f"{row['inicio_m']:.0f}–{row['fin_m']:.0f} m",
            "Zona": row["zona"], "Ancho DXF (m)": round(row["ancho_m"], 1),
            "Avance medio (m/s)": round(row["avance_m_s"], 3),
            "Interior (m/s)": round(row["interior_m_s"], 3),
            "Exterior (m/s)": round(row["exterior_m_s"], 3),
            "Celdas <0,15 (%)": round(row["celdas_lentas_pct"], 1),
            "Celdas >0,50 (%)": round(row["celdas_rapidas_pct"], 1),
            "Bomba más próxima": row["bomba_cercana"],
            "Distancia (m)": round(row["distancia_bomba_m"], 1),
        } for row in section_profile(scenario)], width="stretch", hide_index=True)
    st.caption("La bomba más cercana solo ubica un equipo en el plano. No prueba que "
               "esa bomba cause el avance observado. En estrechamientos, la reducción "
               "de área puede elevar la velocidad aunque se quiten bombas cercanas; "
               "cada cambio de ubicación exige repetir el CFD.")
    st.caption("Límites: superficie libre y bañistas no modelados; salida de siete puertos "
               "agregada, caudal Riverflow no comprobado en NYA, malla y turbulencia sin "
               "calibración física. La filtración es un circuito independiente.")
    if scenario == 16:
        st.caption("La corrida de 16 aún cambió 3,25 % en k durante los últimos 60 s; "
                   "su comparación de turbulencia es menos estable que las de 19–21.")
