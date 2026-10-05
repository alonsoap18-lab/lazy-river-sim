"""Local Riverflow/DXF 3D decision pilot. Run separately from the main app.

streamlit run experiments/openfoam_nya_pilot/riverflow_3d_decision_pilot.py --server.port 8503
The 3D display is a one-dimensional steady energy/continuity scenario, NOT CFD.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.riverflow_3d_pilot import assess_speed_band, solve_loop_pilot  # noqa: E402
from core.riverflow_seven_port import SevenPortScenario, solve_seven_port  # noqa: E402
from experiments.openfoam_nya_pilot.generate_preview import build_geometry, section_depth  # noqa: E402


@st.cache_data(show_spinner="Leyendo contornos DXF y formando secciones…")
def geometry(direction_version: str):
    xy, _, chainages, widths, beach, _ = build_geometry(0, 536)
    depth = np.full(xy.shape[:2], 1.2)
    beach_mask = ((chainages >= beach.beach_start_m) &
                  (chainages <= beach.beach_end_m))
    for i in np.flatnonzero(beach_mask):
        offsets = np.linspace(0, widths[i], xy.shape[1])
        depth[i] = [section_depth(d, widths[i], beach.channel_reference_width_m,
                                  beach.first_slope, beach.ramp_slope)
                    for d in offsets]
    spacing = widths / (xy.shape[1] - 1)
    area = np.trapezoid(depth, dx=1 / (xy.shape[1] - 1), axis=1) * widths
    wet_segments = (depth[:, :-1] > 0) | (depth[:, 1:] > 0)
    floor = np.sum(np.hypot(spacing[:, None], np.diff(depth, axis=1)) *
                   wet_segments, axis=1)
    wall = depth[:, 0] + depth[:, -1]
    return xy, depth, chainages, widths, beach, area, floor, wall


def parse_intervals(raw: str, length: float) -> list[tuple[float, float]]:
    if not raw.strip():
        return []
    intervals = []
    for part in raw.split(","):
        pieces = part.strip().split("-")
        if len(pieces) != 2:
            raise ValueError("Escriba las zonas como inicio-fin, separadas por comas.")
        a, b = map(float, pieces)
        if not 0 <= a < b <= length:
            raise ValueError("Cada zona debe quedar dentro de los 536 m y tener inicio menor que fin.")
        intervals.append((a, b))
    return intervals


def auto_positions(chainages, widths, count, beach, attractions):
    """Cover the *whole* circuit, including the beach transition.

    A phase shift keeps spacing uniform while favoring narrower sections and
    a discharge near the end of the wide beach core. This is a conceptual
    placement heuristic, never an installation or bather-safety design.
    """
    length = float(chainages[-1])
    spacing = length / count
    core = ((chainages >= beach.beach_start_m) &
            (chainages <= beach.beach_end_m) & (widths >= 15))
    core_end = float(chainages[core][-1]) if np.any(core) else beach.beach_end_m
    preferred_exit = (core_end + 5.0) % length
    reference = float(np.median(widths[widths < 15]))
    best_positions = None
    best_score = -np.inf
    for phase in np.linspace(0, spacing, 61, endpoint=False):
        positions = (phase + (np.arange(count) + .5) * spacing) % length
        local_width = np.interp(positions, chainages, widths)
        width_score = np.minimum(1.0, np.sqrt(reference / local_width))
        in_attraction = sum((positions >= a) & (positions <= b)
                            for a, b in attractions)
        distance = np.min(np.abs(positions - preferred_exit))
        distance = min(distance, length - distance)
        score = (float(np.sum(width_score)) - float(np.sum(in_attraction)) +
                 .6 * np.exp(-.5 * (distance / 12) ** 2))
        if score > best_score:
            best_score, best_positions = score, positions
    return np.sort(best_positions)


def manual_positions(raw, count, length):
    positions = np.array([float(v.strip()) for v in raw.split(",")], dtype=float)
    if (len(positions) != count or not np.all(np.isfinite(positions)) or
            np.any(positions < 0) or np.any(positions >= length)):
        raise ValueError(f"Indique {count} progresivas separadas por coma, entre 0 y {length:.0f} m.")
    return positions


def geometry_from_active_plan(model, plan, depth_m, beach, first_share):
    """Draw the active DXF/plan without recalculating its hydraulics.

    The cross-section mesh is illustrative; the hydraulic areas and travel
    times come exclusively from the current RiverflowPlan.
    """
    stations = model.stations
    chainages = np.asarray([float(s["chainage_m"]) for s in stations])
    widths = np.asarray([float(s["width_m"]) for s in stations])
    if (len(stations) != len(plan.station_areas_m2) or
            len(stations) != len(plan.station_velocities_m_s) or
            not 0 < first_share < 1):
        raise ValueError("La escena 3D no corresponde al escenario hidráulico activo.")
    fractions = np.linspace(0, 1, 25)
    xy = np.zeros((len(stations), len(fractions), 2))
    bed = np.full((len(stations), len(fractions)), depth_m)
    scale = float(model.geometry.scale_m_per_unit)
    beach_indices = set(beach.beach_indices) if beach is not None else set()
    for i, station in enumerate(stations):
        centre = np.array([station["x"], station["y"]], dtype=float) * scale
        normal = np.array([station["normal_x"], station["normal_y"]], dtype=float)
        normal /= np.linalg.norm(normal)
        xy[i] = centre + (fractions[:, None] - .5) * widths[i] * normal
        if i in beach_indices and widths[i] > beach.channel_reference_width_m:
            extra = widths[i] - beach.channel_reference_width_m
            first = extra * first_share
            beach_distance = np.maximum(0, fractions * widths[i] -
                                        beach.channel_reference_width_m)
            rise = (beach.first_slope * np.minimum(beach_distance, first) +
                    beach.ramp_slope * np.maximum(0, beach_distance - first))
            bed[i] = np.maximum(0, depth_m - rise)
    xy -= xy[0, 0]
    q = plan.equivalent_channel_flow_m3_h / 3600
    ds = np.diff(chainages)
    areas = np.asarray(plan.station_areas_m2)
    travel = np.r_[0, np.cumsum(ds * (areas[:-1] + areas[1:]) / (2 * q))]
    if not np.isclose(travel[-1] / 60, plan.estimated_lap_min, rtol=1e-8):
        raise ValueError("El tiempo del 3D no coincide con el escenario activo.")
    result = SimpleNamespace(
        section_speed_m_s=np.asarray(plan.station_velocities_m_s),
        cumulative_time_s=travel)
    return xy, bed, chainages, widths, result


def make_plot(xy, depth, chainages, widths, beach, result, positions, attractions,
              module_angles_deg=None, field=None):
    positions = np.asarray(positions, dtype=float)
    take = np.unique(np.r_[np.arange(0, len(chainages), 5), len(chainages)-1,
                           np.argmin(result.section_speed_m_s),
                           np.argmax(result.section_speed_m_s)])
    lateral = np.arange(0, xy.shape[1], 2)
    x = xy[take][:, lateral, 0]
    y = xy[take][:, lateral, 1]
    bed = depth[take][:, lateral]
    color = np.repeat(result.section_speed_m_s[take, None], len(lateral), axis=1)
    if field is not None:
        # Project the already-computed 2D field onto the illustrative 3D
        # surface; do not solve a second hydraulic scenario here.
        sampled = np.array([np.interp(chainages[take], field.chainages_m,
                                      field.speed_m_s[:, j])
                            for j in range(len(field.lateral_fraction))]).T
        color = np.array([np.interp(lateral / (xy.shape[1] - 1),
                                    field.lateral_fraction, row)
                          for row in sampled])
    fig = go.Figure()
    fig.add_trace(go.Surface(
        x=x, y=y, z=-bed, surfacecolor=bed, opacity=.45, showscale=False,
        colorscale=[[0, "#a6b9b1"], [1, "#617e84"]], name="Fondo supuesto"))
    fig.add_trace(go.Surface(
        x=x, y=y, z=np.zeros_like(bed), surfacecolor=color, opacity=.9,
        colorscale=[[0, "#2469a7"], [.35, "#3fb9bd"], [.55, "#a8d573"],
                    [.78, "#f1c65e"], [1, "#d95d40"]],
        cmin=0, cmax=max(.5, float(np.max(color)) * 1.05),
        colorbar=dict(title=("Campo 2D<br>m/s" if field is not None else "Q/A<br>m/s")),
        hovertemplate=("Campo lateral 2D · hipótesis: %{surfacecolor:.3f} m/s<extra></extra>"
                       if field is not None else
                       "Corriente seccional: %{surfacecolor:.3f} m/s<extra></extra>"),
        name=("Campo 2D proyectado" if field is not None else "Corriente Q/A")))
    for index, label in ((0, "Muro interior DXF"), (-1, "Muro exterior DXF")):
        fig.add_trace(go.Scatter3d(
            x=xy[take, index, 0], y=xy[take, index, 1],
            z=np.zeros(len(take)), mode="lines",
            line=dict(color="#243c4b", width=3), name=label))

    # The arrows locate conceptual discharge directions; their size is not jet reach.
    ix = np.searchsorted(chainages, positions).clip(1, len(chainages)-2)
    beach_modules = (((positions >= beach.beach_start_m) &
                      (positions <= beach.beach_end_m)) if beach is not None
                     else np.zeros(len(positions), dtype=bool))
    # The drawn beach rises on the outer bank. Put conceptual discharges on
    # the deeper inner side there; actual suction/return siting is unverified.
    discharge_points = np.array([xy[i, 0 if in_beach else -1]
                                 for i, in_beach in zip(ix, beach_modules)])
    tangents = xy[ix+1, xy.shape[1]//2] - xy[ix-1, xy.shape[1]//2]
    tangents /= np.linalg.norm(tangents, axis=1)[:, None]
    if module_angles_deg is not None:
        angles = np.deg2rad(np.asarray(module_angles_deg, dtype=float))
        if len(angles) != len(positions):
            raise ValueError("Los ángulos 3D deben coincidir con las unidades activas.")
        tangents = np.column_stack((
            tangents[:, 0] * np.cos(angles) - tangents[:, 1] * np.sin(angles),
            tangents[:, 0] * np.sin(angles) + tangents[:, 1] * np.cos(angles)))
    fig.add_trace(go.Scatter3d(
        x=discharge_points[:, 0], y=discharge_points[:, 1], z=np.full(len(ix), .28),
        mode="markers", marker=dict(size=5, color="#df743d", symbol="diamond"),
        text=[f"RF-{i+1:02d} · {p:.1f} m · " +
              ("margen interior profunda (hipótesis)" if beach_modules[i]
               else "margen exterior (hipótesis)")
              for i, p in enumerate(positions)],
        hovertemplate="%{text}<extra></extra>", name="Descargas propuestas"))
    for point, tangent in zip(discharge_points, tangents):
        fig.add_trace(go.Scatter3d(
            x=[point[0], point[0]+3*tangent[0]],
            y=[point[1], point[1]+3*tangent[1]], z=[.25,.25],
            mode="lines", line=dict(color="#df743d", width=5),
            showlegend=False, hoverinfo="skip"))
    for j, (start, end) in enumerate(attractions, 1):
        selected = (chainages >= start) & (chainages <= end)
        if not np.any(selected):
            selected[np.argmin(abs(chainages - (start+end)/2))] = True
        fig.add_trace(go.Scatter3d(
            x=xy[selected, -1, 0], y=xy[selected, -1, 1],
            z=np.full(np.sum(selected), .15), mode="lines+markers",
            line=dict(color="#8a4ab9", width=9), marker=dict(size=2),
            name=f"Atracción supuesta {j} · {start:.0f}–{end:.0f} m"))
    if beach is not None:
        core = ((chainages >= beach.beach_start_m) &
                (chainages <= beach.beach_end_m) & (widths >= 15))
        core_start = float(chainages[core][0]) if np.any(core) else beach.beach_start_m
        core_end = float(chainages[core][-1]) if np.any(core) else beach.beach_end_m
        for p, name in ((core_start, "Inicio zona amplia"),
                        (core_end, "Fin zona amplia"),
                        (beach.beach_end_m, "Fin transición de playa")):
            i = int(np.argmin(abs(chainages-p)))
            fig.add_trace(go.Scatter3d(
                x=[xy[i,-1,0]], y=[xy[i,-1,1]], z=[.22], mode="markers+text",
                marker=dict(size=6, color="#247e5b"), text=[name],
                textposition="top center", name=name))
    center = xy[:, xy.shape[1]//2]
    travel = result.cumulative_time_s
    def rider(frame):
        elapsed = frame / 144 * travel[-1]
        at = float(np.interp(elapsed, travel, chainages))
        return (float(np.interp(at, chainages, center[:,0])),
                float(np.interp(at, chainages, center[:,1])))
    # White surface streaks are time-based tracers, not an additional velocity
    # field. Their progress follows the same cumulative section travel time as
    # the red rider, so they slow down in the wider/slower sections.
    lanes = (xy[:, xy.shape[1]//3], xy[:, 2*xy.shape[1]//3])
    if field is not None:
        lane_paths = []
        lane_x = np.array([np.interp(field.chainages_m, chainages, xy[:, j, 0])
                           for j in range(xy.shape[1])]).T
        lane_y = np.array([np.interp(field.chainages_m, chainages, xy[:, j, 1])
                           for j in range(xy.shape[1])]).T
        scene_fractions = np.linspace(0, 1, xy.shape[1])
        for fraction in (.2, .5, .8):
            eta_index = int(np.argmin(abs(field.lateral_fraction - fraction)))
            eta = field.lateral_fraction[eta_index]
            x_path = np.array([np.interp(eta, scene_fractions, row)
                               for row in lane_x])
            y_path = np.array([np.interp(eta, scene_fractions, row)
                               for row in lane_y])
            u = np.maximum(field.longitudinal_m_s[:, eta_index], .01)
            lane_time = np.r_[0, np.cumsum(np.diff(field.chainages_m) *
                                          (1 / u[:-1] + 1 / u[1:]) / 2)]
            lane_paths.append((lane_time, x_path, y_path))
    def streaks(frame):
        xs, ys, zs = [], [], []
        lap = float(chainages[-1])
        elapsed = ((frame/144 + np.arange(18)/18) % 1) * travel[-1]
        for j, moment in enumerate(elapsed):
            if field is None:
                station = float(np.interp(moment, travel, chainages))
                lane = lanes[j % 2]
                for distance in ((station-3.5) % lap, (station+3.5) % lap):
                    xs.append(float(np.interp(distance, chainages, lane[:, 0])))
                    ys.append(float(np.interp(distance, chainages, lane[:, 1])))
                    zs.append(.08)
            else:
                lane_time, lane_x, lane_y = lane_paths[j % 3]
                for t in ((moment - 5) % lane_time[-1], moment % lane_time[-1]):
                    xs.append(float(np.interp(t, lane_time, lane_x)))
                    ys.append(float(np.interp(t, lane_time, lane_y)))
                    zs.append(.08)
            xs.append(None)
            ys.append(None)
            zs.append(None)
        return xs, ys, zs
    streak_frames = [streaks(i) for i in range(144)]
    initial_x, initial_y, initial_z = streak_frames[0]
    fig.add_trace(go.Scatter3d(
        x=initial_x, y=initial_y, z=initial_z, mode="lines+markers",
        line=dict(color="rgba(245,253,255,0.9)", width=4),
        marker=dict(color="rgba(235,251,255,0.95)", size=2),
        opacity=.85, hoverinfo="skip", name="Partículas de agua · ilustrativas"))
    streak_index = len(fig.data)-1
    px, py = rider(0)
    fig.add_trace(go.Scatter3d(
        x=[px], y=[py], z=[.35], mode="markers",
        marker=dict(size=9, color="#e53535", line=dict(color="#213447", width=2)),
        hovertemplate="Recorrido calculado por Q/A<extra></extra>",
        name="Marcador de recorrido"))
    trace_index = len(fig.data)-1
    # Keep the plot static and update only this one marker with Plotly.restyle.
    # Plotly's 3D frame animation rescales the full scene on some browsers.
    track = [rider(i) for i in range(144)]
    x_span = float(np.ptp(xy[:, :, 0]))
    y_span = float(np.ptp(xy[:, :, 1]))
    x_margin, y_margin = max(5, .08*x_span), max(5, .08*y_span)
    fig.update_layout(
        height=700, margin=dict(l=0,r=0,t=20,b=20),
        uirevision="nyariver-full-loop",
        scene=dict(xaxis=dict(title="Este local (m)",
                              range=[float(np.min(xy[:, :, 0]))-x_margin,
                                     float(np.max(xy[:, :, 0]))+x_margin]),
                   yaxis=dict(title="Norte local (m)",
                              range=[float(np.min(xy[:, :, 1]))-y_margin,
                                     float(np.max(xy[:, :, 1]))+y_margin]),
                   zaxis=dict(title="Cota (m)", range=[-float(np.max(depth))-.3, 1]),
                   aspectmode="manual",
                   aspectratio=dict(x=1, y=max(.2, y_span / max(x_span, 1)), z=.15),
                   uirevision="nyariver-full-loop",
                   camera=dict(eye=dict(x=1.5, y=1.5, z=2.0),
                               projection=dict(type="perspective"))),
        legend=dict(orientation="h",y=-.04))
    return fig, trace_index, track, streak_index, streak_frames


def render_animation(fig, trace_index, track, streak_index, streak_frames):
    """Move only tracers; preserve the user's 3D camera and speed colors."""
    # Load Plotly once from its CDN instead of embedding ~5 MB of JavaScript
    # in every Streamlit rerun/iframe. The published app already needs network.
    plot = pio.to_html(fig, include_plotlyjs="cdn", full_html=False,
                       div_id="nya-riverflow-fixed-scene",
                       config={"responsive": True, "displaylogo": False,
                               "scrollZoom": True})
    points = json.dumps(track, separators=(",", ":"))
    flows = json.dumps([(x, y) for x, y, _ in streak_frames], separators=(",", ":"))
    initial_camera = json.dumps(fig.layout.scene.camera.to_plotly_json())
    return f"""
<div style="font-family: sans-serif; padding: 4px 12px;">
  <button id="rf-play" type="button" style="font-size: 16px; padding: 8px 16px; margin-right: 8px;">▶ Recorrer</button>
  <button id="rf-pause" type="button" style="font-size: 16px; padding: 8px 16px;">⏸ Pausar</button>
  <button id="rf-zoom-in" type="button" style="font-size: 16px; padding: 8px 12px; margin-left: 12px;">＋ Acercar</button>
  <button id="rf-zoom-out" type="button" style="font-size: 16px; padding: 8px 12px;">− Alejar</button>
  <button id="rf-reset-view" type="button" style="font-size: 16px; padding: 8px 12px;">Vista completa</button>
  <span id="rf-progress" style="margin-left: 12px; font-size: 14px;">0 % de la vuelta</span>
</div>
{plot}
<script>
(() => {{
  const graph = document.getElementById("nya-riverflow-fixed-scene");
  const points = {points};
  const flows = {flows};
  const markerIndex = {trace_index};
  const streakIndex = {streak_index};
  const initialCamera = {initial_camera};
  const progress = document.getElementById("rf-progress");
  let step = 0;
  let timer = null;
  function advance() {{
    step = (step + 1) % points.length;
    const [x, y] = points[step];
    const [flowX, flowY] = flows[step];
    Plotly.restyle(graph, {{x: [[x], flowX], y: [[y], flowY]}}, [markerIndex, streakIndex]);
    progress.textContent = Math.round(100 * step / points.length) + " % de la vuelta";
  }}
  function zoom(factor) {{
    const eye = graph._fullLayout.scene.camera.eye;
    const distance = Math.hypot(eye.x, eye.y, eye.z);
    const target = Math.max(0.65, Math.min(6, distance * factor));
    const scale = target / distance;
    Plotly.relayout(graph, {{"scene.camera.eye": {{x: eye.x*scale, y: eye.y*scale, z: eye.z*scale}}}});
  }}
  document.getElementById("rf-zoom-in").addEventListener("click", () => zoom(0.78));
  document.getElementById("rf-zoom-out").addEventListener("click", () => zoom(1.28));
  document.getElementById("rf-reset-view").addEventListener("click", () =>
    Plotly.relayout(graph, {{"scene.camera": initialCamera}}));
  document.getElementById("rf-play").addEventListener("click", () => {{
    if (timer === null) timer = window.setInterval(advance, 80);
  }});
  document.getElementById("rf-pause").addEventListener("click", () => {{
    if (timer !== null) window.clearInterval(timer);
    timer = null;
  }});
  document.addEventListener("visibilitychange", () => {{
    if (document.hidden && timer !== null) {{
      window.clearInterval(timer);
      timer = null;
    }}
  }});
}})();
</script>
"""


def main():
    st.set_page_config(page_title="NYA · piloto Riverflow 3D", layout="wide")
    st.title("NYA · Riverflow 3D de decisión")
    st.caption("Piloto separado del app principal · contornos DXF 536 m sin modificar · modelo estacionario 1D dibujado en 3D; no es CFD ni validación de compra.")
    xy, depth, s, widths, beach, area, floor, wall = geometry("ccw-1")
    with st.sidebar:
        st.header("Unidades Riverflow · hipótesis")
        count = st.slider("Unidades activas", 4, 40, 19)
        speed = st.slider("Variador de todas las unidades (%)", 80, 100, 100, 5)
        large = st.slider("Puerto grande supuesto (mm)", 90, 105, 100, 5)
        small = st.slider("Puerto pequeño supuesto (mm)", 65, 80, 75, 5)
        cd = st.slider("Cd supuesto de boquillas", .8, .9, .85, .025)
        coupling = st.slider("Energía transferida a corriente (%) · NO medida",
                             .5, 8.0, 2.0, .5)
        st.header("Canal y ubicación")
        floor_n = st.slider("Manning n · piso liso (rugosidad editable)",
                            .010, .025, .013, .001,
                            help="Rugosidad hidráulica supuesta del fondo; no significa que el piso no tenga fricción.")
        wall_n = st.slider("Manning n · paredes tipo piedra/concreto rugoso",
                           .015, .050, .025, .001,
                           help="Se combina con el piso según el perímetro mojado de cada sección.")
        narrow_width = st.slider("Ancho máximo considerado angosto (m)",
                                 5.0, 15.0, 8.0, .5,
                                 help="Solo clasifica dónde comprobar la meta 0,25–0,30 m/s; no modifica el DXF ni la hidráulica.")
        attraction_text = st.text_input("Zonas de isla/catarata · inicio-fin en m",
                                        placeholder="Ej.: 120-145, 380-405",
                                        help="La ubicación real no figura en el DXF. Estas zonas son etiquetas editables; no cambian la hidráulica por sí solas.")
        position_text = st.text_area("Posiciones manuales de descargas (m)",
                                     placeholder="Vacío = reparto automático por todo el circuito",
                                     help="Una progresiva por unidad activa, separadas por coma. Distancia en sentido antihorario.",
                                     key="rf3d_positions_ccw")
    try:
        attractions = parse_intervals(attraction_text, float(s[-1]))
        positions = (manual_positions(position_text, count, float(s[-1]))
                     if position_text.strip() else
                     auto_positions(s, widths, count, beach, attractions))
        nozzle = solve_seven_port(SevenPortScenario(
            large_bore_m=large/1000, small_bore_m=small/1000,
            discharge_coefficient=cd, speed_fraction=speed/100))
        perimeter = floor + wall
        n = ((floor * floor_n ** 1.5 + wall * wall_n ** 1.5) /
             perimeter) ** (2/3)
        result = solve_loop_pilot(
            s, area, perimeter, n, positions, np.zeros(count),
            module_flow_m3_h=nozzle.module_flow_m3_h,
            module_head_m=nozzle.pump_head_ft * .3048,
            useful_coupling_fraction=coupling/100,
            current_reference_width_m=float(np.median(widths[widths<15])),
            section_width_m=widths)
        band = assess_speed_band(s, area, widths, result.loop_flow_m3_h,
                                 narrow_width_m=narrow_width)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    c1,c2,c3,c4,c5=st.columns(5)
    c1.metric("Q por unidad · curva + boquilla",f"{nozzle.module_flow_m3_h:.0f} m³/h")
    c2.metric("TDH por unidad",f"{nozzle.pump_head_ft:.2f} ft")
    c3.metric("Salida de cada puerto · escenario",f"{nozzle.exit_speed_m_s:.2f} m/s")
    c4.metric("Corriente media por vuelta",f"{result.mean_lap_speed_m_s:.3f} m/s")
    c5.metric("Tiempo de vuelta",f"{result.lap_min:.1f} min")
    st.subheader("Meta de corriente en secciones angostas · 0,25–0,30 m/s")
    st.caption("Meta operativa indicada para NYA; no es un límite de seguridad ni una velocidad certificada.")
    b1,b2,b3=st.columns(3)
    b1.metric(f"Velocidad con ancho ≤{narrow_width:.1f} m",
              f"{band.selected_speed_min_m_s:.3f}–{band.selected_speed_max_m_s:.3f} m/s")
    b2.metric("Longitud angosta dentro de la banda",
              f"{band.current_coverage_fraction:.0%} de {band.selected_length_m:.0f} m")
    b3.metric("Máximo geométrico posible en banda",
              f"{band.best_possible_coverage_fraction:.0%}",
              help="Máximo matemático al variar un único caudal constante; no garantiza que las bombas lo alcancen.")
    if not band.all_sections_feasible:
        q_lower = f"{band.required_flow_lower_m3_h:,.0f}".replace(",", " ")
        q_upper = f"{band.required_flow_upper_m3_h:,.0f}".replace(",", " ")
        st.warning("Con las áreas actuales del DXF, ningún caudal único puede dejar todas esas "
                   "secciones entre 0,25 y 0,30 m/s. Para cubrirlas todas haría falta "
                   f"Q ≥ {q_lower} y a la vez "
                   f"Q ≤ {q_upper} m³/h. "
                   "Cambiar la cantidad o posición de bombas no resuelve esa contradicción geométrica; "
                   "hay que definir subzonas, modificar secciones o usar un modelo de reparto 2D/3D.")
    conflicts = [float(p) for p in positions
                 if any(a <= p <= b for a,b in attractions)]
    if conflicts:
        st.warning("Descargas dentro de zona de estancia propuesta: " +
                   ", ".join(f"{p:.1f} m" for p in conflicts) +
                   ". Revise su ubicación; no se considera una instalación aprobada.")
    figure, marker_index, track, streak_index, streak_frames = make_plot(
        xy, depth, s, widths, beach, result, positions, attractions)
    st.caption("Dentro del gráfico: rueda para acercar/alejar y arrastre para girar. "
               "Los trazos blancos muestran el sentido y el ritmo relativo de la corriente; "
               "son ilustrativos, no CFD ni turbulencia calculada.")
    st.iframe(render_animation(figure, marker_index, track, streak_index, streak_frames), height=790)
    st.caption(f"Caudal longitudinal equivalente {result.loop_flow_m3_h:,.0f} m³/h (NO suma de bombas). "
               f"Velocidad seccional {result.section_speed_m_s.min():.3f}–"
               f"{result.section_speed_m_s.max():.3f} m/s. "
               f"Separación máxima entre descargas {result.max_module_spacing_m:.0f} m. "
               f"Mayor pérdida de carga sin impulso intermedio {result.max_unpowered_friction_gap_m:.3f} m. "
               f"Manning compuesto {n.min():.3f}–{n.max():.3f} (piso + paredes mojadas).")
    beach_mask = (s >= beach.beach_start_m) & (s <= beach.beach_end_m)
    beach_speed = result.section_speed_m_s[beach_mask]
    core_mask = beach_mask & (widths >= 15)
    core_start = float(s[core_mask][0]) if np.any(core_mask) else beach.beach_start_m
    core_end = float(s[core_mask][-1]) if np.any(core_mask) else beach.beach_end_m
    beach_pumps = int(np.sum((positions >= beach.beach_start_m) &
                             (positions <= beach.beach_end_m)))
    st.write(f"Playa: núcleo ancho {core_start:.0f}–{core_end:.0f} m; "
             f"transición hasta {beach.beach_end_m:.0f} m; "
             f"{beach_pumps} descargas propuestas en ese tramo, por la margen profunda. "
             f"corriente seccional {beach_speed.min():.3f}–{beach_speed.max():.3f} m/s. "
             "Su ensanchamiento y pendiente supuesta afectan el área mojada y el tiempo de paso.")
    best_q = f"{band.best_possible_flow_m3_h:,.0f}".replace(",", " ")
    best_beach_min = (beach_speed.min() * band.best_possible_flow_m3_h /
                      result.loop_flow_m3_h)
    st.caption(f"El caudal único que maximiza la longitud angosta dentro de la banda sería "
               f"aprox. {best_q} m³/h, pero en la misma geometría el mínimo de playa "
               f"bajaría a {best_beach_min:.3f} m/s. Esto muestra el compromiso; "
               "no es una recomendación automática de compra ni garantiza movimiento junto a la orilla.")
    low_speed = result.mean_lap_speed_m_s * .5 ** (1/3)
    high_speed = result.mean_lap_speed_m_s * 2 ** (1/3)
    st.warning(f"Sensibilidad de la transferencia no medida: con la mitad o el doble del "
               f"{coupling:.1f}% supuesto, la media de vuelta sería "
               f"{low_speed:.3f}–{high_speed:.3f} m/s y el tiempo "
               f"{result.lap_min / 2 ** (1/3):.1f}–"
               f"{result.lap_min / .5 ** (1/3):.1f} min. "
               "No es un intervalo estadístico ni garantía del fabricante.")
    if attractions:
        for j,(a,b) in enumerate(attractions,1):
            mask=(s>=a)&(s<=b)
            if np.any(mask):
                local=result.section_speed_m_s[mask]
                st.write(f"Atracción supuesta {j} ({a:.0f}–{b:.0f} m): "
                         f"{local.min():.3f}–{local.max():.3f} m/s. "
                         "Para hacerla más lenta de forma sostenida se requiere mayor sección mojada, "
                         "desvío de caudal o detalle hidráulico; alejar una bomba por sí solo no cambia Q/A.")
    else:
        st.caption("No se ubicaron islas ni cataratas: sus progresivas no están identificadas en el DXF. "
                   "Escriba intervalos para examinar velocidades en esos sitios sin alterar el plano.")
    st.info("El plano Riverflow define configuración e instalación, pero no los diámetros internos "
            "de cada abertura ni la transferencia de energía de sus chorros al NYA. "
            "El color representa Q/A de cada sección (uniforme de orilla a orilla); "
            "no predice remolinos, cataratas, succión, oleaje ni seguridad de bañistas.")
    st.caption("Fuentes Riverflow: [documentación lazy river]"
               "(https://riverflowpumps.com/es/technical/lazy-rivers/) · "
               "[equipo y motor](https://riverflowpumps.com/technical/what-the-system-includes/) · "
               "[instalación de siete puertos]"
               "(https://riverflowpumps.com/wp-content/uploads/NOZZLE%20INSTALLATION%20DRAWINGS/D101-7PN-INSTALLATION-DETAILS-V2.pdf). "
               "Curva digitalizada desde la imagen entregada; dimensiones internas y acoplamiento supuestos.")


if __name__ == "__main__":
    main()
