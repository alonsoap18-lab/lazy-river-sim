"""Show a fixed OpenFOAM local comparison without merging it into live results."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st


ARCHIVE = Path(__file__).resolve().parents[1] / "assets" / "cfd_local_410_450"


def render_local_cfd_archive(*, active_dxf_sha256: str, current_volume_m3: float,
                             current_depth_m: float, current_flow_m3_h: float) -> None:
    manifest_path = ARCHIVE / "manifest.json"
    if not manifest_path.exists():
        st.info("El ensayo local 3D todavía está en comprobación de malla y caudal.")
        return
    info = json.loads(manifest_path.read_text(encoding="utf-8"))
    if info.get("schema") != 1 or not info.get("quality_gate", {}).get("mesh_and_solver_ok"):
        st.warning("El paquete del ensayo local no superó la comprobación numérica.")
        return

    st.caption("Ensayo guardado de OpenFOAM 14 sobre las orillas reales del DXF 28-10-26, "
               "solo en el tramo 410–450 m. Las dos posiciones reciben el mismo caudal de "
               "entrada y usan una CF104 de referencia con dos tomas y siete salidas. "
               "Es una solución estacionaria local, no una simulación transitoria de la vuelta.")
    if active_dxf_sha256 != info["source_dxf_sha256"]:
        st.warning("El DXF activo es distinto al del ensayo. Las imágenes se muestran como "
                   "referencia archivada y no representan el diseño cargado.")
    elif abs(current_depth_m-info["local_depth_m"]) > .01:
        st.warning("La profundidad activa cambió. Este ensayo sigue usando 1,20 m y "
                   "no se recalcula con los controles de la app.")
    else:
        current_q = current_volume_m3 / (info["target_lap_scenario_min"]*60)
        difference = 100*(info["imposed_through_flow_m3_s"]-current_q)/current_q
        st.caption(f"Caudal impuesto en el ensayo: {info['imposed_through_flow_m3_s']:.3f} m³/s "
                   f"({difference:+.1f} % frente al volumen activo para 35 min). "
                   "Ese caudal es una condición de prueba; no lo produce automáticamente "
                   "una sola estación.")
    st.caption(f"CF104 de referencia: {info['pump_flow_gpm']:.0f} US gpm por unidad. "
               f"El punto de operación activo equivale a {current_flow_m3_h:.0f} m³/h "
               "por unidad, si todas son iguales. La orientación de 15° y las superficies "
               "de toma/descarga de este modelo son hipótesis, no cotas aprobadas por Riverflow.")

    cases = info["cases"]
    table = pd.DataFrame([
        {"Estación": f"{item['station_m']} m", "Malla": f"{item['mesh_cm']} cm",
         "Avance medio local": f"{item['mean_along_m_s']:.3f} m/s",
         "Volumen en retorno": f"{100*item['reverse_volume_fraction']:.2f} %",
         "Rapidez p95": f"{item['p95_speed_m_s']:.3f} m/s"}
        for item in cases if item["station_m"] in (426, 430) and item["mesh_cm"] == 40
    ])
    st.dataframe(table, hide_index=True, width="stretch")
    pressure = info["pressure_gain_m2_s2"]
    fine_gain_mm = pressure["mesh30cm"] / 9.81 * 1000
    st.metric("Aporte hidráulico local modelado · una CF104",
              f"{fine_gain_mm:.2f} mm de columna de agua")
    st.caption("Se obtiene restando la presión necesaria en el mismo tramo y al mismo "
               "caudal con la bomba apagada y encendida. La diferencia entre mallas "
               f"fue {100*pressure['relative_mesh_difference']:.1f} %. No es la TDH "
               "de la bomba, una eficiencia certificada ni una altura aplicable "
               "automáticamente a todas las estaciones.")
    st.info("El caso sin bomba tampoco presentó retorno con este caudal ya impuesto. "
            "Por ello, estos mapas comparan el reparto local y no demuestran cuántas "
            "bombas crean o sostienen el caudal del circuito.")
    left, right = st.columns(2)
    with left:
        st.image(str(ARCHIVE / "station426.png"), caption="Estación en 426 m · caudal idéntico")
    with right:
        st.image(str(ARCHIVE / "station430.png"), caption="Estación en 430 m · caudal idéntico")
    st.caption("Colores: rojo, avance inverso < −0,02 m/s; amarillo, 0–0,05 m/s; "
               "verde, 0,05–0,15 m/s; azul claro, 0,15–0,30 m/s; azul oscuro, "
               "> 0,30 m/s. Las flechas muestran la dirección del campo estacionario. "
               "Los máximos junto a los puertos cambiaron con la malla y no se usan "
               "como velocidad segura para personas.")
    st.caption("El Manning de paredes y piso sí interviene en el cálculo general de la app. "
               "En este CFD local se usaron funciones de pared lisas: todavía no existe "
               "una calibración que convierta el Manning propuesto para la piedra de NYA "
               "en la rugosidad Ks de esas paredes 3D.")
    st.caption(info["interpretation"])

