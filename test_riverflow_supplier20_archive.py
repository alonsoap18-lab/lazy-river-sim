"""The published CFD preset must use its own DXF and pump layout."""

from hashlib import sha256

from streamlit.testing.v1 import AppTest

from core.riverflow_supplier20_archive import (
    WIDE_SHA, _canonical_wide_dxf, archived_wide_layout, load_archive,
    wide_dxf_bytes,
)
from core.riverflow_supplier_photo import ASSETS, load_supplier_photo


def test_archived_source_and_paired_layout():
    assert sha256(wide_dxf_bytes()).hexdigest() == WIDE_SHA
    assert _canonical_wide_dxf(wide_dxf_bytes().replace(b"\r\n", b"\n")) == wide_dxf_bytes()
    positions, banks = archived_wide_layout()
    assert len(positions) == len(banks) == 20
    assert positions.count(155.0) == 2
    assert {banks[i] for i, value in enumerate(positions) if value == 155.0} == {
        "Exterior", "Interior",
    }
    assert load_archive()["cases"]["wide_relocated_70"]["lap_min"] > 30


def test_supplier_photo_sheet_has_correct_travel_direction_and_source_plan():
    layout = load_supplier_photo()
    assert layout["wide_sha"] == sha256(wide_dxf_bytes()).hexdigest()
    positions = layout["positions"]
    assert len(positions) == 20
    assert [item["supplier_number"] for item in positions] == list(range(1, 21))
    assert positions[0]["chainage_m_approx"] < 30
    assert positions[-1]["chainage_m_approx"] > 500
    assert positions[1]["chainage_m_approx"] < positions[2]["chainage_m_approx"]
    assert all(item["bank"] == "por confirmar" for item in positions)
    assert (ASSETS / "source_plan.jpg").stat().st_size > 50_000
    assert (ASSETS / "corrected_layout.png").stat().st_size > 10_000


def test_preset_opens_with_matching_inputs_and_editable_case_is_retained():
    app = AppTest.from_file("app.py", default_timeout=90).run()
    assert not app.exception
    assert next(widget for widget in app.number_input
                if widget.label == "Unidades activas").value == 20
    assert next(widget for widget in app.slider
                if widget.label == "Velocidad del variador (%)").value == 70
    assert any("posiciones/orillas coinciden" in item.value for item in app.info)
    assert any("Volumen por secciones del modelo rápido" in item.value
               for item in app.get("caption"))

    next(widget for widget in app.number_input
         if widget.label == "Unidades activas").set_value(24)
    app.run()
    assert not app.exception
    assert next(widget for widget in app.number_input
                if widget.label == "Unidades activas").value == 24
    assert any("El escenario activo tiene 24 bombas" in item.value
               for item in app.warning)
    assert any(item.label == "Bombas activas · menú principal" and item.value == "24"
               for item in app.metric)
    assert any("cantidad de bombas" in item.value for item in app.warning)

    next(widget for widget in app.radio
         if widget.label == "Escenario de trabajo").set_value(
             "Exploración editable · DXF original o propio")
    app.run()
    assert not app.exception
    assert next(widget for widget in app.number_input
                if widget.label == "Unidades activas").value == 24
    assert next(widget for widget in app.metric
                if widget.label == "Volumen DXF + perfil").value.startswith("6,748")

    next(widget for widget in app.number_input
         if widget.label == "Profundidad de agua (m)").set_value(1.5)
    next(widget for widget in app.checkbox
         if widget.label == "Aplicar cotas proporcionales al DXF").set_value(False)
    app.run()
    assert not app.exception
    next(widget for widget in app.number_input
         if widget.label == "Unidades activas").set_value(20)
    app.run()
    assert not app.exception
    next(widget for widget in app.radio
         if widget.label == "Escenario de trabajo").set_value(
             "DXF ampliado · referencia CFD de 20 CF104")
    app.run()
    assert not app.exception
    assert next(widget for widget in app.number_input
                if widget.label == "Profundidad de agua (m)").value == 1.2
    assert next(widget for widget in app.checkbox
                if widget.label == "Aplicar cotas proporcionales al DXF").value
    assert any("posiciones/orillas coinciden" in item.value for item in app.info)
