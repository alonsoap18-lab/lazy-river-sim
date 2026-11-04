"""Show a completed OpenFOAM run only for the exact uploaded DXF bytes."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "cfd_uploaded"


def _browser_compatible_2d(html: str, *, detail_scale: bool = True) -> str:
    """Keep the archived CFD data while making its 2D playback usable in SVG."""
    plot_start = html.rfind("Plotly.newPlot(")
    if plot_start < 0:
        return html
    plot = html[plot_start:].replace('"type":"scattergl"', '"type":"scatter"')
    # The archived Plotly frames contain only the three changing traces. Its
    # animation machinery can clear the other SVG traces during a frame, which
    # makes the banks and pump symbols disappear. Update those three traces
    # directly and leave all geometry and pump traces untouched.
    # The saved values do not change. A tighter display range makes the
    # near-zero flow in this failed scenario visible instead of pale white.
    if detail_scale:
        plot = plot.replace('"cmax":0.6,"cmin":-0.6',
                            '"cmax":0.15,"cmin":-0.15')
    # Passive tracers must not obscure the actual cell velocities.
    plot = plot.replace(
        '"color":"#ffffff","line":{"color":"#172d40","width":0.5},'
        '"opacity":0.95,"size":4',
        '"color":"#172d40","line":{"color":"#172d40","width":0},'
        '"opacity":0.55,"size":3')
    # Plotly.addFrames may finish after the following promise callback starts.
    # Retain the exact saved frames as a script variable instead of reading a
    # private, possibly still empty Plotly transition cache at that instant.
    call_start = plot.index("Plotly.addFrames(")
    data_start = plot.index("[", call_start)
    _, data_length = json.JSONDecoder().raw_decode(plot[data_start:])
    data_end = data_start + data_length
    call_prefix = plot[call_start:data_start]
    plot = (plot[:call_start] + "window.nyaSavedFrames = " +
            plot[data_start:data_end] + ";\n                            " +
            call_prefix + "window.nyaSavedFrames" + plot[data_end:])
    start = plot.index("        const gd = document.getElementById(")
    gd_line = plot[start:plot.index(";", start) + 1]
    end = plot.index("        setTimeout(advance, 500);", start) + len(
        "        setTimeout(advance, 500);")
    plot = plot[:start] + gd_line + '''
        const savedFrames = window.nyaSavedFrames;
        const frameByName = new Map(savedFrames.map(frame => [frame.name, frame]));
        const sequence = savedFrames.map(frame => frame.name);
        gd.dataset.nyaPlayback = 'ready:' + sequence.length;
        let playing = false, cursor = 0, timer = null, settingSlider = false;
        async function showFrame(index) {
            const frame = frameByName.get(sequence[index]);
            if (!frame) return;
            // These indices are supplied by the saved OpenFOAM figure. The
            // banks and pump markers have other indices and remain untouched.
            const [field, arrows, tracers] = frame.data;
            const [fieldIndex, arrowIndex, tracerIndex] = frame.traces;
            await Plotly.restyle(gd, {'marker.color': [field.marker.color]}, [fieldIndex]);
            await Plotly.restyle(gd, {x: [arrows.x], y: [arrows.y]}, [arrowIndex]);
            if (tracers && tracerIndex !== undefined) {
                await Plotly.restyle(gd, {x: [tracers.x], y: [tracers.y]}, [tracerIndex]);
            }
            settingSlider = true;
            try { await Plotly.relayout(gd, {'sliders[0].active': index}); }
            finally { settingSlider = false; }
            gd.dataset.nyaPlayback = 'frame:' + index;
        }
        function stopPlayback() {
            playing = false;
            if (timer !== null) clearTimeout(timer);
            timer = null;
        }
        async function advance() {
            if (!playing) return;
            try { await showFrame(cursor); }
            catch (error) {
                gd.dataset.nyaPlayback = 'error:' + String(error);
                stopPlayback(); return;
            }
            cursor += 1;
            if (cursor >= sequence.length) { stopPlayback(); return; }
            if (playing) timer = setTimeout(advance, 450);
        }
        // Plotly's built-in animation must not run alongside direct updates.
        const originalSteps = gd.layout.sliders?.[0]?.steps;
        if (originalSteps) {
            Plotly.relayout(gd, {
                'sliders[0].steps': originalSteps.map((step, index) => ({
                    ...step, execute: false,
                    label: (index % 6 === 0 || index === originalSteps.length - 1)
                        ? step.label : ''
                })),
                annotations: []
            });
        }
        gd.on('plotly_sliderchange', event => {
            if (settingSlider) return;
            stopPlayback();
            const selected = sequence.indexOf(event.step.args?.[0]?.[0]);
            if (selected >= 0) { cursor = selected; showFrame(selected); }
        });
        // The archived Plotly buttons use execute:false. Handle clicks at the
        // DOM capture phase so playback does not depend on Plotly's optional
        // plotly_buttonclicked event or its built-in animation path.
        gd.addEventListener('click', event => {
            const button = event.target.closest('g.updatemenu-button');
            if (!button) return;
            const label = button.textContent || '';
            event.preventDefault();
            event.stopPropagation();
            if (label.includes('Pausa')) { stopPlayback(); return; }
            if (label.includes('Reproducir')) {
                stopPlayback(); cursor = 0; playing = true;
                gd.dataset.nyaPlayback = 'play:0';
                advance();
            }
        }, true);''' + plot[end:]
    return html[:plot_start] + plot


def load_matching_run(dxf_sha256: str) -> tuple[Path, dict, dict] | None:
    if len(dxf_sha256) != 64 or any(c not in "0123456789abcdef" for c in dxf_sha256):
        return None
    folder = ASSETS / dxf_sha256[:12]
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("schema") != 2 or
            manifest.get("status") != "diagnostic_only_not_purchase_or_lap" or
            manifest.get("source_dxf_sha256") != dxf_sha256):
        return None
    scenarios = {}
    for key in manifest.get("scenarios", {}):
        if key not in ("reference20", "automatic"):
            return None
        scenario_folder = folder / key
        metadata_file = scenario_folder / "metadata.json"
        report_file = scenario_folder / "transient_report.json"
        if not metadata_file.is_file() or not report_file.is_file():
            return None
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        report = json.loads(report_file.read_text(encoding="utf-8"))
        if (metadata.get("source_dxf_sha256") != dxf_sha256 or
                report.get("source_dxf_sha256") != dxf_sha256 or
                report.get("max_courant_observed", float("inf")) > .2 or
                any(not (scenario_folder / name).is_file() for name in
                    ("flow_2d.html.gz", "flow_3d.html.gz"))):
            return None
        scenarios[key] = (metadata, report)
    if not scenarios:
        return None
    return folder, manifest, scenarios


def saved_run_differences(manifest: dict, *, active_length_m: float | None = None,
                          active_depth_m: float | None = None,
                          active_pumps: int | None = None,
                          active_floor_n: float | None = None,
                          active_wall_n: float | None = None,
                          active_wall_n_calm: float | None = None,
                          active_flow_each_m3_h: float | None = None,
                          active_unit_flows_m3_h: tuple[float, ...] | None = None,
                          active_nozzle_type: str | None = None,
                          active_beach_profile: bool | None = None,
                          active_beach_share_pct: float | None = None,
                          active_beach_ramp_pct: float | None = None,
                          active_beach_threshold_m: float | None = None,
                          active_chainages_m: tuple[float, ...] | None = None,
                          active_banks: tuple[str, ...] | None = None,
                          active_angles_deg: tuple[float, ...] | None = None) -> list[str]:
    """Report menu inputs that do not describe the saved CFD boundary conditions."""
    differences = []
    for label, active, saved, tolerance in (
        ("longitud escalada", active_length_m, manifest["length_m"], .1),
        ("profundidad", active_depth_m, 1.2, .001),
        ("bombas activas", active_pumps, manifest["active_pumps"], 0),
        ("Manning del piso", active_floor_n, manifest["floor_manning_n"], .0001),
        ("Manning de pared de corriente", active_wall_n,
         manifest["wall_manning_n"], .0001),
        ("Manning de pared de playa", active_wall_n_calm,
         manifest["wall_manning_n"], .0001),
        ("fracción plana de playa (%)", active_beach_share_pct, 62.0, .01),
        ("pendiente de playa (%)", active_beach_ramp_pct,
         manifest["beach_ramp_slope"] * 100, .01),
        ("umbral de playa (m)", active_beach_threshold_m, 15.0, .01),
    ):
        if active is not None and abs(active - saved) > tolerance:
            differences.append(f"{label}: menú {active:g}, corrida {saved:g}")
    if active_beach_profile is False:
        differences.append("perfil de playa desactivado; la corrida sí lo incluye")
    saved_flow_m3_h = manifest["reference_flow_gpm_per_pump"] * .003785411784 * 60
    if (active_flow_each_m3_h is not None and
            abs(active_flow_each_m3_h - saved_flow_m3_h) > .05 * saved_flow_m3_h):
        differences.append("caudal CF104 por unidad: menú "
                           f"{active_flow_each_m3_h:.0f} m³/h, corrida "
                           f"{saved_flow_m3_h:.0f} m³/h")
    if (active_unit_flows_m3_h is not None and
            (len(active_unit_flows_m3_h) != manifest["active_pumps"] or
             any(abs(flow - saved_flow_m3_h) > .05 * saved_flow_m3_h
                 for flow in active_unit_flows_m3_h))):
        differences.append("uno o más caudales individuales CF104 difieren de la corrida")
    if active_nozzle_type is not None and not active_nozzle_type.startswith("7"):
        differences.append("la corrida representa 7 puertos agrupados; "
                           f"el menú usa {active_nozzle_type}")
    saved_stations = manifest["stations"]
    if (active_chainages_m is not None and active_banks is not None and
            (len(active_chainages_m) != len(saved_stations) or
             len(active_banks) != len(saved_stations) or
             any(abs(position - station["chainage_m"]) > 1.0 or
                 bank != station["bank"] for position, bank, station in
                 zip(active_chainages_m, active_banks, saved_stations)))):
        differences.append("posiciones u orillas de bombas distintas")
    if (active_angles_deg is not None and
            (len(active_angles_deg) != len(saved_stations) or
             any(abs(angle) > 1.0 for angle in active_angles_deg))):
        differences.append("ángulos de descarga distintos de 0°")
    return differences


def render_matching_run(dxf_sha256: str, *, active_length_m: float | None = None,
                        active_depth_m: float | None = None,
                        active_pumps: int | None = None,
                        active_floor_n: float | None = None,
                        active_wall_n: float | None = None,
                        active_wall_n_calm: float | None = None,
                        active_flow_each_m3_h: float | None = None,
                        active_unit_flows_m3_h: tuple[float, ...] | None = None,
                        active_nozzle_type: str | None = None,
                        active_beach_profile: bool | None = None,
                        active_beach_share_pct: float | None = None,
                        active_beach_ramp_pct: float | None = None,
                        active_beach_threshold_m: float | None = None,
                        active_chainages_m: tuple[float, ...] | None = None,
                        active_banks: tuple[str, ...] | None = None,
                        active_angles_deg: tuple[float, ...] | None = None) -> bool:
    """Return True only when a verified bundle matches the uploaded file."""
    match = load_matching_run(dxf_sha256)
    if match is None:
        return False
    import streamlit as st

    folder, bundle, scenarios = match
    st.subheader("OpenFOAM · diagnóstico del DXF cargado")
    st.error("Las corridas anteriores del DXF cargado tenían picos numéricos y se "
             "retiraron de esta vista. Se muestran las comprobaciones con paso "
             "temporal más fino. Ninguna demuestra aún flujo continuo ni permite "
             "recomendar una cantidad de bombas o un tiempo de vuelta.")
    selected = st.radio(
        "Distribución OpenFOAM sobre el DXF cargado",
        tuple(scenarios),
        format_func=lambda key: bundle["scenarios"][key],
        horizontal=True,
        key=f"rf_uploaded_cfd_scenario_{dxf_sha256[:12]}",
    )
    manifest, report = scenarios[selected]
    last = report["time_profile"][-1]
    st.caption(f"Archivo identificado por SHA-256 {dxf_sha256[:12]}…; "
               f"{manifest['mesh_cells']:,} celdas, {manifest['active_pumps']} unidades CF104 "
               f"hipotéticas, {last['physical_time_s']:.0f} s físicos desde reposo. "
               "Cambiar el contenido del DXF, aunque conserve el nombre, invalida esta corrida. "
               "Los dos escenarios tienen el mismo DXF, malla, caudal unitario y duración; "
               "solo cambia la ubicación de las bombas.")
    differences = saved_run_differences(
        manifest, active_length_m=active_length_m, active_depth_m=active_depth_m,
        active_pumps=active_pumps, active_floor_n=active_floor_n,
        active_wall_n=active_wall_n, active_wall_n_calm=active_wall_n_calm,
        active_flow_each_m3_h=active_flow_each_m3_h,
        active_unit_flows_m3_h=active_unit_flows_m3_h,
        active_nozzle_type=active_nozzle_type,
        active_beach_profile=active_beach_profile,
        active_beach_share_pct=active_beach_share_pct,
        active_beach_ramp_pct=active_beach_ramp_pct,
        active_beach_threshold_m=active_beach_threshold_m,
        active_chainages_m=active_chainages_m, active_banks=active_banks,
        active_angles_deg=active_angles_deg)
    if differences:
        st.warning("Esta corrida usa el mismo archivo DXF, pero sus parámetros no "
                   "coinciden con el menú actual: " + "; ".join(differences) +
                   ". Cambiar controles no recalcula OpenFOAM.")
    st.warning("Ensayo exploratorio: dos tomas y siete puertos agregados en una salida "
               "por bomba; superficie libre fija. El caudal por bomba es la referencia "
               "2014 US gpm, no el punto de operación comprobado de NYA. "
               "Esta corrida no valida compra, seguridad ni tiempo de vuelta de personas.")
    if all(data[1]["time_profile"][-1][
            "fraction_cell_reverse_below_minus_0_02"] > .1
           for data in scenarios.values()):
        st.error("Ninguna de las dos distribuciones consiguió un flujo estable en el "
                 "sentido previsto. Los mapas permiten inspeccionar el fallo del ensayo; "
                 "no hay una distribución recomendada ni un tiempo de vuelta calculable "
                 "con estas corridas.")
    a, b, c, d = st.columns(4)
    a.metric("Avance mediano de celdas · final", f"{last['median_longitudinal_cell_m_s']:.3f} m/s")
    b.metric("Celdas con retorno <−0,02 m/s", f"{last['fraction_cell_reverse_below_minus_0_02']:.1%}")
    c.metric("Courant máximo observado", f"{report['max_courant_observed']:.2f}")
    d.metric("Tramos de 10 m en retorno",
             len(report.get("returning_10m_sections_at_end", ())))
    st.caption(f"Tiempo físico: {last['physical_time_s']:.0f} s. Es un ensayo "
               "transitorio de 20 minutos, no una vuelta de 20 minutos.")
    if last["fraction_cell_reverse_below_minus_0_02"] > .1:
        st.error("Este ensayo muestra mucho flujo inverso con esta distribución. "
                 "No debe interpretarse como una vuelta estable ni como ubicación final de bombas.")
    if last["median_longitudinal_cell_m_s"] <= 0:
        st.error("La mediana longitudinal final va en sentido contrario al recorrido "
                 "previsto. Esta disposición queda descartada dentro de este ensayo; "
                 "no se puede calcular una vuelta útil con ese campo.")
    if abs(report["last_60s_median_speed_change_fraction"]) > .05:
        st.warning("La mediana de velocidad aún cambió más de 5 % durante los "
                   "últimos 60 s. El campo final no demuestra estabilidad temporal.")
    extension = bundle.get("reference_extension_1800_s")
    if extension is not None:
        st.caption("Control adicional de la distribución de referencia a 1.800 s: "
                   f"{extension['reverse_cell_fraction_below_minus_0_02']:.1%} de celdas "
                   "en retorno y "
                   f"{extension['negative_10m_section_medians']} tramos de 10 m con "
                   "mediana en retorno. El mapa de abajo termina a 1.200 s; "
                   "la extensión tampoco demuestra circulación continua.")
    if len(scenarios) > 1:
        st.dataframe([{
            "Distribución": bundle["scenarios"][key],
            "Avance mediano final (m/s)": round(data[1]["time_profile"][-1][
                "median_longitudinal_cell_m_s"], 3),
            "Celdas con retorno (%)": round(100 * data[1]["time_profile"][-1][
                "fraction_cell_reverse_below_minus_0_02"], 1),
            "Cambio de mediana últimos 60 s (%)": round(100 * data[1][
                "last_60s_median_speed_change_fraction"], 1),
            "Tramos de 10 m en retorno": len(data[1].get(
                "returning_10m_sections_at_end", ())),
        } for key, data in scenarios.items()], hide_index=True, width="stretch")
        st.caption("Los dos casos usan el mismo DXF, malla, caudal unitario y duración; "
                   "solo cambia la distribución de bombas. Los porcentajes son de "
                   "celdas de esta malla, no de personas ni de caudal total.")
    view = st.radio("Vista del DXF cargado", ("2D · velocidad y dirección", "3D · paredes y profundidad"),
                    horizontal=True, key=f"rf_uploaded_cfd_view_{dxf_sha256[:12]}")
    detail_scale = True
    if view.startswith("2D"):
        scale_choice = st.radio(
            "Escala de color del mapa 2D",
            ("Detalle de corrientes lentas · ±0,15 m/s",
             "Comparación con el DXF original · ±0,6 m/s"),
            horizontal=True, key=f"rf_uploaded_cfd_scale_{dxf_sha256[:12]}")
        detail_scale = scale_choice.startswith("Detalle")
    filename = "flow_2d.html.gz" if view.startswith("2D") else "flow_3d.html.gz"
    with gzip.open(folder / selected / filename, "rt", encoding="utf-8") as source:
        html = source.read()
    if view.startswith("2D"):
        html = _browser_compatible_2d(html, detail_scale=detail_scale)
        st.caption("Visor CFD 2D · revisión de capas fijas. Vista compatible con navegadores sin WebGL. Conserva los mismos "
                   "campos y tiempos guardados. Reproducir recorre una vez de 0 a 1.200 s "
                   "y se detiene en el último campo, sin volver bruscamente a cero. "
                   "Pausa detiene el avance y la barra permite elegir un instante. "
                   "La silueta y los ejes quedan fijos según el DXF; solo cambian "
                   "velocidades, flechas y trazadores.")
        if detail_scale:
            st.info("La escala ampliada ±0,15 m/s deja ver corrientes débiles y retornos. "
                    "Satura los colores fuera de ese rango; no modifica las velocidades "
                    "ni permite comparar colores directamente con el DXF original. "
                    "Seleccione ±0,6 m/s para esa comparación.")
    else:
        st.info("La vista 3D interactiva necesita WebGL. Si el navegador muestra un "
                "recuadro gris, selecciona la vista 2D para ver los mismos campos de "
                "velocidad y dirección sin WebGL.")
    st.components.v1.html(html, height=900, scrolling=True)
    if view.startswith("2D"):
        st.caption("En el mapa: rojo = retorno, azul = avance; rombos naranjas = "
                   "descargas; puntos oscuros = trazadores visuales del campo U. "
                   f"Escala mostrada: {'−0,15 a +0,15' if detail_scale else '−0,6 a +0,6'} "
                   "m/s; los colores se saturan fuera de ella, pero el valor numérico "
                   "se conserva al pasar el cursor sobre las celdas. "
                   "La barra muestra tiempo físico simulado, no tiempo de vuelta.")
    with st.expander("Procedencia y límites del cálculo"):
        st.markdown("**Comprobaciones para decidir distribución o compra**")
        st.dataframe([
            {"Comprobación": "Paso temporal y Courant",
             "Estado": "Revisado en ambas corridas de 1.200 s"},
            {"Comprobación": "Sensibilidad de malla en todo el circuito",
             "Estado": "Pendiente"},
            {"Comprobación": "Dos tomas y siete puertos separados por CF104",
             "Estado": "Pendiente en todo el circuito"},
            {"Comprobación": "Rugosidad de piedra como pared 3D",
             "Estado": "Pendiente; Manning es arrastre equivalente"},
            {"Comprobación": "Superficie libre y playa",
             "Estado": "Pendiente; superficie fija"},
            {"Comprobación": "Punto de operación CF104 en NYA",
             "Estado": "Pendiente; 2014 US gpm es referencia"},
        ], hide_index=True, width="stretch")
        st.json({"dx_fingerprint": dxf_sha256,
                 "malla_celdas": manifest["mesh_cells"],
                 "volumen_malla_m3": manifest["volume_mesh_m3"],
                 "manning_piso": manifest["floor_manning_n"],
                 "manning_pared": manifest["wall_manning_n"],
                 "arrastre_Manning_volumetrico": manifest["manning_equivalent_bulk_drag_applied"],
                 "cambio_mediana_ultimos_60s": report["last_60s_median_speed_change_fraction"],
                 "estado_validacion": bundle["quality_gate"],
                 "limitaciones": manifest["limitations"]})
    return True
