"""Show the Riverflow drawing and its provisional spatial transfer to the DXF."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from core.riverflow_supplier20_archive import WIDE_SHA, archived_wide_layout
from core.riverflow_supplier_photo_cfd import render_pdf_bank_cfd


ASSETS = Path(__file__).resolve().parents[1] / "assets" / "cfd_supplier_photo"


def load_supplier_photo() -> dict:
    layout = json.loads((ASSETS / "layout.json").read_text(encoding="utf-8"))
    positions = layout["positions"]
    if (layout["schema"] != 1 or layout["wide_sha"] != WIDE_SHA or
            len(positions) != 20 or
            {item["supplier_number"] for item in positions} != set(range(1, 21)) or
            positions[0]["chainage_m_approx"] >= positions[-1]["chainage_m_approx"]):
        raise ValueError("El traslado del plano Riverflow no coincide con el DXF ampliado.")
    for name in ("source_plan.jpg", "corrected_layout.png", "route_animation.html"):
        if not (ASSETS / name).is_file():
            raise ValueError(f"Falta la vista {name} del plano Riverflow.")
    return layout


def render_supplier_photo_sheet(*, source_bytes: bytes, depth_m: float,
                                floor_n: float, wall_n: float,
                                active_modules: int, speed_pct: float,
                                positions_m: tuple[float, ...],
                                banks: tuple[str, ...]) -> None:
    layout = load_supplier_photo()
    st.subheader("Propuesta Riverflow · plano y ubicación aproximada")
    st.info("Las líneas azules numeradas se leen desde la orilla donde nace cada línea: "
            "allí está la bomba propuesta. La bomba 1 queda junto a la playa en el "
            "lado derecho y la 20 en el lado izquierdo. Retiramos el ensayo anterior "
            "porque invirtió las progresivas del plano.")

    if hashlib.sha256(source_bytes).hexdigest() != WIDE_SHA:
        st.info("La hoja corresponde al DXF `lazy river 28-10-26.dxf`. El DXF activo "
                "es diferente; las posiciones dibujadas no se aplican al nuevo archivo.")
    current_positions, current_banks = archived_wide_layout()
    if (active_modules != 20 or abs(depth_m-1.2) > .01 or
            abs(floor_n-.013) > .0001 or abs(wall_n-.025) > .0001 or
            abs(speed_pct-70) > .5 or len(positions_m) != 20 or
            any(abs(a-b) > .1 for a,b in zip(positions_m,current_positions)) or
            banks != current_banks):
        st.caption("Los controles actuales difieren de la referencia local guardada. "
                   "Este plano sigue siendo una comparación fija y no cambia el escenario activo.")

    cfd, animated, source, transfer = st.tabs([
        "Flujo OpenFOAM · comparar", "Recorrido animado",
        "Plano recibido de Riverflow", "Traslado al DXF · comparación"])
    with cfd:
        render_pdf_bank_cfd()
    with animated:
        html = (ASSETS / "route_animation.html").read_text(encoding="utf-8")
        components.html(html, height=760, scrolling=False)
        st.caption("Los trazadores se mueven para mostrar el sentido y la continuidad "
                   "geométrica. Su rapidez en pantalla es ilustrativa y no procede de "
                   "OpenFOAM. Para observar velocidades calculadas, abra Flujo OpenFOAM.")
    with source:
        st.image(str(ASSETS / "source_plan.jpg"),
                 caption="Plano entregado por Riverflow: marcas azules numeradas del 1 al 20. "
                         "Las líneas azules son propuestas opcionales de retornos.",
                 width="stretch")
    with transfer:
        st.image(str(ASSETS / "corrected_layout.png"),
                 caption="Naranja: inicio de la línea azul numerada de Riverflow, "
                         "trasladado aproximadamente a su orilla del DXF. "
                         "Azul: bombas de la referencia local.",
                 width="stretch")
        st.dataframe([{
            "N.º Riverflow": item["supplier_number"],
            "Progresiva aproximada · m": item["chainage_m_approx"],
            "Margen leída del plano": item["bank"],
            "Ángulo": "Por medir",
        } for item in layout["positions"]], hide_index=True, width="stretch")
        st.caption("Traslado visual con incertidumbre aproximada de ±20 m. El plano no "
                   "proporciona coordenadas CAD ni define toma, ángulo preciso de descarga, "
                   "dirección de los siete puertos o VFD individual. La orilla se interpreta "
                   "por el inicio de cada línea azul junto al número. Los ensayos CFD "
                   "de esta hoja incluyen la incertidumbre de la orientación del chorro "
                   "mediante dos hipótesis. «Plano y recorrido 2D/3D» conserva "
                   "la distribución local activa.")
