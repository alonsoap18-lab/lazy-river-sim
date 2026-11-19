"""Archived OpenFOAM comparison for the Riverflow PDF line-start layout."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from core.riverflow_supplier20_archive import WIDE_SHA


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "cfd_supplier_photo"
CURRENT = "qa_supplier20_widepair_ampliado_vfd70_dt05"
TANGENT = "qa_supplier20_pdf_banks_ampliado_vfd70_dt05"
ANGLE20 = "qa_supplier20_pdf_banks_angle20_ampliado_vfd70_dt05"


def load_pdf_bank_cfd() -> dict:
    report = json.loads((ASSETS / "cfd_comparison.json").read_text(encoding="utf-8"))
    result = report["result"]
    if (result["dxf_sha256"] != WIDE_SHA or result["mesh_cells"] != 5352 or
            report["layout_sha256"] != hashlib.sha256((ASSETS / "layout.json").read_bytes()).hexdigest() or
            set(result["cases"]) != {CURRENT, TANGENT, ANGLE20}):
        raise ValueError("La comparación CFD no corresponde al DXF ampliado y sus tres casos.")
    for name in ("flow_tangent_2d.html.gz", "flow_tangent_3d.html.gz",
                 "flow_angle20_2d.html.gz", "flow_angle20_3d.html.gz"):
        if not (ASSETS / name).is_file():
            raise ValueError(f"Falta el campo CFD {name} de Riverflow.")
    return report


def _row(label: str, case: dict) -> dict:
    lap = case["projected_stationary_hydraulic_lap_min"]
    return {
        "Caso guardado": label,
        "Vuelta hidráulica": f"{lap:.2f} min" if lap is not None else "Sin avance continuo",
        "Retorno · % volumen": round(100*case["reverse_volume_fraction"], 2),
        "Paso ancho lento · %": round(
            100*case["regions"]["wide_passage"]["volume_fraction_below_0_15"], 2),
        "P95 angostos · m/s": round(case["regions"]["narrow_passage"]["p95_m_s"], 3),
        "Mediana playa · m/s": round(case["regions"]["main_beach"]["median_m_s"], 3),
        "Secciones 10 m con retorno": case["negative_10m_median_section_count"],
    }


def render_pdf_bank_cfd() -> None:
    report = load_pdf_bank_cfd()
    cases = report["result"]["cases"]
    st.subheader("Flujo calculado · misma geometría y 20 CF104")
    st.dataframe([
        _row("Referencia local · 16 exterior / 4 interior", cases[CURRENT]),
        _row("Riverflow leído del plano · chorros tangenciales", cases[TANGENT]),
        _row("Riverflow · 20° hacia el centro, hipótesis", cases[ANGLE20]),
    ], hide_index=True, width="stretch")
    reference = cases[CURRENT]
    tangent = cases[TANGENT]
    if (tangent["reverse_volume_fraction"] < reference["reverse_volume_fraction"] and
            tangent["regions"]["wide_passage"]["volume_fraction_below_0_15"] <
            reference["regions"]["wide_passage"]["volume_fraction_below_0_15"] and
            tangent["regions"]["narrow_passage"]["p95_m_s"] <
            reference["regions"]["narrow_passage"]["p95_m_s"]):
        st.success("Con chorros tangenciales, la propuesta interpretada de Riverflow "
                   "mejora los tres indicadores del ensayo: menos retorno, menos "
                   "volumen lento en pasos anchos y menor velocidad alta en los "
                   "tramos angostos. Compare el caso de 20° para ver la sensibilidad "
                   "a la orientación del chorro.")
    else:
        st.info("Los indicadores no mejoran todos a la vez. Revise cada columna y "
                "la orientación de descarga antes de elegir una disposición.")
    st.caption("Mismo DXF de 536 m, malla de 5352 celdas, profundidad nominal 1,20 m, "
               "Manning 0,013 fondo / 0,025 pared, 20 CF104 y 319,9 m³/h por bomba "
               "(VFD 70 % hipotético). Riverflow: 10 bombas exteriores y 10 interiores "
               "según el inicio de las líneas azules del PDF. La progresiva estimada "
               "puede variar ±20 m.")
    st.caption("Retorno: velocidad longitudinal < −0,02 m/s; paso ancho lento: "
               "< 0,15 m/s fuera de 6 m alrededor de las descargas. Son porcentajes "
               "del volumen de la malla, no de personas ni del caudal total. "
               "La vuelta es la suma de 67 secciones del campo final, no un tiempo "
               "medido de flotadores.")
    st.caption("La referencia termina en 1200 s físicos. Los dos casos Riverflow "
               "continúan desde ese campo hasta 1800 s tras mover las fuentes. "
               "Se comparan campos próximos a estabilidad, con distinto historial "
               "de arranque. Las dos tomas y siete puertos se representan de forma "
               "agregada; faltan la dirección medida de cada chorro y comprobaciones "
               "de malla y paso temporal antes de elegir compra o certificar seguridad.")

    if not st.checkbox("Cargar visor CFD 2D/3D", key="supplier_pdf_cfd_load"):
        return
    scenario = st.radio("Escenario CFD", [
        "Referencia local", "Riverflow · tangencial", "Riverflow · 20° al centro"],
        horizontal=True, key="supplier_pdf_cfd_scenario")
    view = st.radio("Vista CFD", ["2D animado", "3D interactivo"],
                    horizontal=True, key="supplier_pdf_cfd_view")
    suffix = "2d" if view == "2D animado" else "3d"
    name = {
        "Referencia local": ROOT / "assets" / "cfd_supplier20" / f"flow_{suffix}.html.gz",
        "Riverflow · tangencial": ASSETS / f"flow_tangent_{suffix}.html.gz",
        "Riverflow · 20° al centro": ASSETS / f"flow_angle20_{suffix}.html.gz",
    }[scenario]
    with gzip.open(name, "rt", encoding="utf-8") as stream:
        components.html(stream.read(), height=800, scrolling=True)
    st.caption("Cuadros del campo OpenFOAM guardado. Los puntos blancos son trazadores "
               "visuales, no partículas calculadas ni personas. El 3D requiere WebGL.")
