"""Fixed CFD sheet for the approximate Riverflow overlay on the widened DXF."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from core.riverflow_supplier20_archive import WIDE_SHA, archived_wide_layout


ASSETS = Path(__file__).resolve().parents[1] / "assets" / "cfd_supplier_photo"
REFERENCE = "qa_supplier20_widepair_ampliado_vfd70_dt05"
PROPOSAL = "qa_supplier20_photo_ampliado_vfd70_dt05"


def load_supplier_photo() -> tuple[dict, dict]:
    comparison = json.loads((ASSETS / "comparison.json").read_text(encoding="utf-8"))
    metadata = json.loads((ASSETS / "metadata.json").read_text(encoding="utf-8"))
    if (comparison["result"]["dxf_sha256"] != WIDE_SHA or
            metadata["source_dxf_sha256"] != WIDE_SHA or
            metadata["active_pumps"] != 20):
        raise ValueError("La propuesta guardada no corresponde al DXF ampliado de 20 CF104.")
    if set(comparison["result"]["cases"]) != {REFERENCE, PROPOSAL}:
        raise ValueError("Falta un escenario CFD de la comparación Riverflow.")
    return comparison, metadata


def _row(label: str, case: dict) -> dict:
    return {
        "Escenario": label,
        "Vuelta hidráulica · min": round(case["projected_stationary_hydraulic_lap_min"], 2),
        "Retorno · % volumen de malla": round(100 * case["reverse_volume_fraction"], 2),
        "Paso ancho lento · %": round(
            100 * case["regions"]["wide_passage"]["volume_fraction_below_0_15"], 2),
        "P95 paso angosto · m/s": round(
            case["regions"]["narrow_passage"]["p95_m_s"], 3),
        "Mediana playa · m/s": round(case["regions"]["main_beach"]["median_m_s"], 3),
    }


def render_supplier_photo_sheet(*, source_bytes: bytes, depth_m: float,
                                floor_n: float, wall_n: float,
                                active_modules: int, speed_pct: float,
                                positions_m: tuple[float, ...],
                                banks: tuple[str, ...]) -> None:
    comparison, metadata = load_supplier_photo()
    cases = comparison["result"]["cases"]
    current, proposed = cases[REFERENCE], cases[PROPOSAL]
    st.subheader("Propuesta Riverflow · 20 ubicaciones tentativas")
    st.caption("Ensayo OpenFOAM guardado para `lazy river 28-10-26.dxf` (DXF ampliado). "
               "La imagen del proveedor marca ubicaciones opcionales; las progresivas, "
               "márgenes, tomas y direcciones usadas aquí son aproximaciones del estudio, "
               "no coordenadas ni orientaciones confirmadas por Riverflow.")

    active_sha = hashlib.sha256(source_bytes).hexdigest()
    differences = []
    if active_sha != WIDE_SHA:
        differences.append("DXF")
    if abs(depth_m - 1.2) > .01:
        differences.append("profundidad")
    if abs(floor_n - .013) > .0001 or abs(wall_n - .025) > .0001:
        differences.append("Manning")
    if active_modules != 20:
        differences.append("cantidad de bombas")
    if abs(speed_pct - 70) > .5:
        differences.append("VFD")
    current_positions, current_banks = archived_wide_layout()
    if (len(positions_m) != 20 or len(banks) != 20 or
            any(abs(a - b) > .1 for a, b in zip(positions_m, current_positions)) or
            banks != current_banks):
        differences.append("posiciones activas respecto a la referencia")
    if differences:
        st.warning("Los controles actuales difieren del ensayo guardado en: " +
                   ", ".join(differences) +
                   ". Estas vistas y cifras permanecen fijas; cambiar controles no recalcula CFD.")
    else:
        st.info("Los controles actuales coinciden con la **referencia local**. "
                "La propuesta Riverflow se muestra por separado y no sustituye esas posiciones.")

    tab_proposal, tab_compare = st.tabs(["Propuesta · flujo 2D/3D", "Comparación · resultados"])
    with tab_proposal:
        a, b, c = st.columns(3)
        a.metric("Bombas CF104", "20")
        b.metric("VFD del ensayo", "70 % hipotético")
        c.metric("Caudal por bomba", "319,9 m³/h")
        st.caption("Campo calculado hasta 1800 s físicos. Los puntos blancos son trazadores "
                   "visuales del campo guardado; no son personas ni partículas CFD.")
        view = st.radio("Vista de la propuesta", ["2D animado", "3D interactivo"],
                        horizontal=True, key="supplier_photo_view")
        name = "flow_2d.html.gz" if view == "2D animado" else "flow_3d.html.gz"
        with gzip.open(ASSETS / name, "rt", encoding="utf-8") as file:
            components.html(file.read(), height=800, scrolling=True)
        if view == "3D interactivo":
            st.caption("La vista 3D requiere WebGL en el navegador.")
        with st.expander("Ver 20 ubicaciones aproximadas"):
            stations = sorted(metadata["stations"], key=lambda item: item["chainage_m"])
            st.dataframe([{
                "Número en plano Riverflow": item["supplier_plan_number"],
                "Progresiva aproximada · m": item["chainage_m"],
                "Margen supuesta": item["bank"],
            } for item in stations], hide_index=True, width="stretch")
            st.caption("La bomba #2 del plano se interpreta cerca de 485 m en margen interior. "
                       "En la referencia local se había movido a 155 m en margen exterior.")

    with tab_compare:
        st.dataframe([
            _row("Referencia local · 20", current),
            _row("Riverflow aproximada · 20", proposed),
        ], hide_index=True, width="stretch")
        st.success("En este ensayo, la propuesta aproximada reduce el retorno y el área "
                   "lenta del paso ancho, y baja el P95 del paso angosto. La vuelta "
                   "hidráulica proyectada pasa de 30,47 a 32,12 minutos.")
        st.caption("Retorno: velocidad longitudinal < −0,02 m/s. Paso ancho lento: "
                   "velocidad < 0,15 m/s fuera de 6 m alrededor de descargas. "
                   "Ambos porcentajes son del volumen de la malla; no son caudal ni personas. "
                   "Vuelta: suma de 67 secciones en el campo final, no tiempo medido de usuarios.")
        st.caption("Ambos casos usan el mismo DXF, malla de 5352 celdas, profundidad nominal "
                   "1,20 m, Manning 0,013/0,025, 20 CF104 y 319,9 m³/h por bomba. "
                   "La propuesta parte del campo local guardado a 1200 s y corre hasta 1800 s; "
                   "no comparten un arranque independiente idéntico. Faltan comprobaciones "
                   "de malla/paso temporal y detalles de tomas y chorros confirmados por el proveedor.")
