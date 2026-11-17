"""Present the completed 20-CF104 CFD comparison as a fixed, auditable archive."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "assets" / "cfd_supplier20"
ORIGINAL_SHA = "4d3a426ae2fb0acffd4b4d0a6d10cc936e94ba83d04fef7a21bfe5e4082bb5f0"
WIDE_SHA = "47154b381560b10b58d2729f9e2ae79dc90ff1f24af8a7640d36a41b15f68060"
WIDE_LF_SHA = "f1995775dbf951697d994d89fd42f0576e0f2ce719ad45adc018f63bc6e369f0"


def _canonical_wide_dxf(source: bytes) -> bytes:
    """Restore the archived CRLF bytes if Git normalized the DXF on checkout."""
    source_sha = hashlib.sha256(source).hexdigest()
    if source_sha == WIDE_SHA:
        return source
    if source_sha == WIDE_LF_SHA:
        restored = source.replace(b"\n", b"\r\n")
        if hashlib.sha256(restored).hexdigest() == WIDE_SHA:
            return restored
    raise ValueError("El DXF ampliado no coincide con el ensayo CFD archivado.")


def wide_dxf_bytes() -> bytes:
    """Return the exact widened DXF used by the archived CFD case."""
    return _canonical_wide_dxf((ARCHIVE / "wide_source.dxf").read_bytes())


def archived_wide_layout() -> tuple[tuple[float, ...], tuple[str, ...]]:
    """Return positions and banks in route order, keeping the paired station."""
    with (ARCHIVE / "locations.csv").open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    if len(rows) != 20:
        raise ValueError("El ensayo archivado requiere exactamente 20 estaciones.")
    positions = tuple(float(row["progresiva_m_aproximada"]) for row in rows)
    banks = tuple(row["margen_hipotesis"] for row in rows)
    if any(bank not in ("Exterior", "Interior") for bank in banks):
        raise ValueError("El archivo de posiciones contiene una margen desconocida.")
    return positions, banks


def render_archived_flow(*, key: str) -> None:
    """Show the saved CFD fields without implying a live OpenFOAM rerun."""
    view = st.radio("Campo OpenFOAM guardado", ["2D animado", "3D interactivo"],
                    horizontal=True, key=key)
    html_name = "flow_2d.html.gz" if view == "2D animado" else "flow_3d.html.gz"
    with gzip.open(ARCHIVE / html_name, "rt", encoding="utf-8") as file:
        components.html(file.read(), height=800, scrolling=True)
    st.caption("Campo CFD archivado del DXF ampliado, 20 CF104 al 70 % hipotético. "
               "Las orillas y bombas permanecen fijas; los puntos blancos son trazadores "
               "visuales, no partículas resueltas ni trayectorias de visitantes. "
               "El 3D requiere WebGL.")


def load_archive() -> dict:
    data = json.loads((ARCHIVE / "summary.json").read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("original_sha") != ORIGINAL_SHA or data.get("wide_sha") != WIDE_SHA:
        raise ValueError("El archivo CFD de 20 bombas no coincide con su geometría.")
    return data


def _case_row(label: str, case: dict) -> dict:
    lap = case["lap_min"]
    return {
        "Escenario guardado": label,
        "Vuelta hidráulica": f"{lap:.2f} min" if lap is not None else "Sin avance continuo",
        "Retorno local": f"{100 * case['reverse_fraction']:.1f} %",
        "Zona ancha lenta": f"{100 * case['wide_slow_fraction']:.1f} %",
        "P95 angostos": f"{case['narrow_p95_m_s']:.3f} m/s",
        "Playa mediana": f"{case['beach_median_m_s']:.3f} m/s",
    }


def render_supplier20_decision(*, source_bytes: bytes, depth_m: float,
                               floor_n: float, wall_n: float,
                               active_modules: int, speed_pct: float,
                               unit_flow_m3_h: float, turnover_h: float,
                               positions_m: tuple[float, ...] = (),
                               banks: tuple[str, ...] = ()) -> bool:
    """Return whether the active DXF belongs to either completed comparison."""
    raw_sha = hashlib.sha256(source_bytes).hexdigest()
    normalized_sha = hashlib.sha256(source_bytes.replace(b"\r\n", b"\n")).hexdigest()
    sha = raw_sha if raw_sha in (ORIGINAL_SHA, WIDE_SHA) else normalized_sha
    if sha not in (ORIGINAL_SHA, WIDE_SHA):
        return False
    data = load_archive()
    cases = data["cases"]
    best = cases["wide_relocated_70"]
    st.subheader("Decisión provisional · 20 CF104")
    st.success("El DXF ampliado con 20 bombas reubicadas y VFD al 70 % hipotético "
               "fue la opción más equilibrada de las corridas guardadas. Sirve para "
               "continuar el anteproyecto y presupuestar, no para fijar la compra o las tomas de obra.")
    if sha == ORIGINAL_SHA:
        st.info("Está viendo el DXF original. La opción recomendada procede del DXF "
                "ampliado; cárguelo para comparar sus dimensiones con el menú activo.")

    a, b, c, d = st.columns(4)
    a.metric("Vuelta hidráulica proyectada", f"{best['lap_min']:.2f} min")
    b.metric("Retorno local", f"{100 * best['reverse_fraction']:.1f} %")
    c.metric("Zona ancha lenta", f"{100 * best['wide_slow_fraction']:.1f} %")
    d.metric("Filtración teórica · 4 h", f"{data['wide_volume_m3'] / 4:,.0f} m³/h")
    st.caption("Vuelta = suma de 67 secciones del campo CFD final, no recorrido de personas. "
               "Retorno = volumen con velocidad longitudinal < −0,02 m/s. "
               "Zona ancha lenta = volumen de paso < 0,15 m/s fuera de las descargas; "
               "es un indicador comparativo, no un límite de seguridad. "
               "Filtración y propulsión son circuitos separados.")

    st.dataframe([
        _case_row("Original · 20 al 100 %", cases["original_reference_100"]),
        _case_row("Original · VFD por zonas", cases["original_zonal"]),
        _case_row("Ampliado · base 100 %", cases["wide_reference_100"]),
        _case_row("Ampliado · reubicadas 100 %", cases["wide_relocated_100"]),
        _case_row("Ampliado · reubicadas 70 %", best),
    ], hide_index=True, width="stretch")
    st.caption("Las cinco filas se evaluaron con una máscara de 6 m alrededor de todas "
               "las descargas ensayadas por cada DXF. Malla y método son iguales dentro "
               "de cada diseño; los dos DXF tienen geometrías y volúmenes distintos.")

    mismatches = []
    if sha != WIDE_SHA:
        mismatches.append("DXF")
    if abs(depth_m - 1.2) > .01:
        mismatches.append("profundidad")
    if abs(floor_n - .013) > .0001 or abs(wall_n - .025) > .0001:
        mismatches.append("Manning")
    if active_modules != 20:
        mismatches.append("cantidad de bombas")
    if abs(speed_pct - 70) > .5:
        mismatches.append("VFD")
    if abs(unit_flow_m3_h - best["unit_flow_m3_h"]) > .05 * best["unit_flow_m3_h"]:
        mismatches.append("caudal por bomba")
    archive_positions, archive_banks = archived_wide_layout()
    layout_matches = (len(positions_m) == 20 and len(banks) == 20 and
                      all(abs(a - b) < .1 for a, b in zip(positions_m, archive_positions))
                      and banks == archive_banks)
    if not layout_matches:
        mismatches.append("posiciones/orillas")
    if mismatches:
        st.warning("El menú activo difiere de este ensayo en: " + ", ".join(mismatches) +
                   ". Cambiar controles no vuelve a ejecutar OpenFOAM; la tabla y las "
                   "animaciones conservan sus entradas archivadas.")
    else:
        st.info("DXF, profundidad, Manning, cantidad, VFD, caudal unitario y "
                "posiciones/orillas coinciden con el ensayo guardado. El perfil de playa "
                "del modelo rápido y la malla CFD usan discretizaciones distintas.")
    if abs(turnover_h - 4) > .01:
        st.caption(f"El menú calcula filtración a {turnover_h:g} h; la cifra de la tarjeta "
                   "corresponde exclusivamente al ensayo de 4 h.")

    with st.expander("Ver flujo del DXF ampliado · ensayo guardado", expanded=False):
        show_view = st.checkbox("Cargar visor interactivo", key="supplier20_load_view")
        if show_view:
            render_archived_flow(key="supplier20_archive_view")
    with st.expander("Ver las 20 posiciones provisionales", expanded=False):
        with (ARCHIVE / "locations.csv").open(encoding="utf-8-sig", newline="") as file:
            st.dataframe(list(csv.DictReader(file)), hide_index=True, width="stretch")
        st.caption("La estación 2 se trasladó por criterio del ensayo a una zona ancha "
                   "cerca del metro 155. Riverflow no indicó ese cambio ni confirmó "
                   "márgenes, ángulos o cotas de estas posiciones.")
    st.caption("Modelo 3D de tapa rígida, cuatro capas; Manning como arrastre equivalente; "
               "dos tomas y siete puertos agregados, sin chorros individuales. El caudal "
               "al 70 % depende de curva digitalizada y pérdidas locales supuestas. "
               "Hay 1,3 % de retorno local y falta comprobar sensibilidad temporal del "
               "caso recomendado; no certifica comodidad ni seguridad.")
    return True
