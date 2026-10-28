"""Show a completed OpenFOAM run only for the exact uploaded DXF bytes."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "cfd_uploaded"


def load_matching_run(dxf_sha256: str) -> tuple[Path, dict, dict] | None:
    if len(dxf_sha256) != 64 or any(c not in "0123456789abcdef" for c in dxf_sha256):
        return None
    folder = ASSETS / dxf_sha256[:12]
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("source_dxf_sha256") != dxf_sha256:
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
                any(not (scenario_folder / name).is_file() for name in
                    ("flow_2d.html.gz", "flow_3d.html.gz"))):
            return None
        scenarios[key] = (metadata, report)
    if not scenarios:
        return None
    return folder, manifest, scenarios


def render_matching_run(dxf_sha256: str, *, active_length_m: float | None = None,
                        active_depth_m: float | None = None,
                        active_pumps: int | None = None,
                        active_floor_n: float | None = None,
                        active_wall_n: float | None = None,
                        active_flow_each_m3_h: float | None = None,
                        active_nozzle_type: str | None = None,
                        active_chainages_m: tuple[float, ...] | None = None,
                        active_banks: tuple[str, ...] | None = None,
                        active_angles_deg: tuple[float, ...] | None = None) -> bool:
    """Return True only when a verified bundle matches the uploaded file."""
    match = load_matching_run(dxf_sha256)
    if match is None:
        return False
    import streamlit as st

    folder, bundle, scenarios = match
    st.subheader("OpenFOAM · resultado del DXF cargado")
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
               "Cambiar el contenido del DXF, aunque conserve el nombre, invalida esta corrida.")
    differences = []
    for label, active, saved, tolerance in (
        ("longitud escalada", active_length_m, manifest["length_m"], .1),
        ("profundidad", active_depth_m, 1.2, .001),
        ("bombas activas", active_pumps, manifest["active_pumps"], 0),
        ("Manning del piso", active_floor_n, manifest["floor_manning_n"], .0001),
        ("Manning de pared", active_wall_n, manifest["wall_manning_n"], .0001),
    ):
        if active is not None and abs(active - saved) > tolerance:
            differences.append(f"{label}: menú {active:g}, corrida {saved:g}")
    saved_flow_m3_h = manifest["reference_flow_gpm_per_pump"] * .003785411784 * 60
    if (active_flow_each_m3_h is not None and
            abs(active_flow_each_m3_h - saved_flow_m3_h) > .05 * saved_flow_m3_h):
        differences.append("caudal CF104 por unidad: menú "
                           f"{active_flow_each_m3_h:.0f} m³/h, corrida "
                           f"{saved_flow_m3_h:.0f} m³/h")
    if active_nozzle_type is not None and not active_nozzle_type.startswith("7"):
        differences.append("la corrida representa 7 puertos agrupados; "
                           f"el menú usa {active_nozzle_type}")
    saved_stations = manifest["stations"]
    if (active_chainages_m is not None and active_banks is not None and
            len(active_chainages_m) == len(saved_stations) and
            len(active_banks) == len(saved_stations) and
            any(abs(position - station["chainage_m"]) > 1.0 or
                bank != station["bank"] for position, bank, station in
                zip(active_chainages_m, active_banks, saved_stations, strict=True))):
        differences.append("posiciones u orillas de bombas distintas")
    if (active_angles_deg is not None and
            any(abs(angle) > 1.0 for angle in active_angles_deg)):
        differences.append("ángulos de descarga distintos de 0°")
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
    d.metric("Duración física simulada", f"{last['physical_time_s']:.0f} s")
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
    if len(scenarios) > 1:
        st.dataframe([{
            "Distribución": bundle["scenarios"][key],
            "Avance mediano final (m/s)": round(data[1]["time_profile"][-1][
                "median_longitudinal_cell_m_s"], 3),
            "Celdas con retorno (%)": round(100 * data[1]["time_profile"][-1][
                "fraction_cell_reverse_below_minus_0_02"], 1),
            "Cambio de mediana últimos 60 s (%)": round(100 * data[1][
                "last_60s_median_speed_change_fraction"], 1),
        } for key, data in scenarios.items()], hide_index=True, width="stretch")
        st.caption("Los dos casos usan el mismo DXF, malla, caudal unitario y duración; "
                   "solo cambia la distribución de bombas. Los porcentajes son de "
                   "celdas de esta malla, no de personas ni de caudal total.")
    view = st.radio("Vista del DXF cargado", ("2D · velocidad y dirección", "3D · paredes y profundidad"),
                    horizontal=True, key=f"rf_uploaded_cfd_view_{dxf_sha256[:12]}")
    filename = "flow_2d.html.gz" if view.startswith("2D") else "flow_3d.html.gz"
    with gzip.open(folder / selected / filename, "rt", encoding="utf-8") as source:
        html = source.read()
    st.components.v1.html(html, height=900, scrolling=True)
    with st.expander("Procedencia y límites del cálculo"):
        st.json({"dx_fingerprint": dxf_sha256,
                 "malla_celdas": manifest["mesh_cells"],
                 "volumen_malla_m3": manifest["volume_mesh_m3"],
                 "manning_piso": manifest["floor_manning_n"],
                 "manning_pared": manifest["wall_manning_n"],
                 "arrastre_Manning_volumetrico": manifest["manning_equivalent_bulk_drag_applied"],
                 "cambio_mediana_ultimos_60s": report["last_60s_median_speed_change_fraction"],
                 "limitaciones": manifest["limitations"]})
    return True
