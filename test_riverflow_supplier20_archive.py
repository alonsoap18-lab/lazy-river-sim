"""The published CFD preset must use its own DXF and pump layout."""

from hashlib import sha256

from streamlit.testing.v1 import AppTest

from core.riverflow_supplier20_archive import (
    WIDE_SHA, _canonical_wide_dxf, archived_wide_layout, load_archive,
    wide_dxf_bytes,
)
from core.riverflow_supplier_photo import ASSETS, PROPOSAL, REFERENCE, load_supplier_photo


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


def test_supplier_photo_sheet_uses_wide_dxf_and_saved_cfd_fields():
    comparison, metadata = load_supplier_photo()
    assert metadata["source_dxf_sha256"] == sha256(wide_dxf_bytes()).hexdigest()
    assert len(metadata["stations"]) == 20
    assert {item["supplier_plan_number"] for item in metadata["stations"]} == set(range(1, 21))
    photo_two = next(item for item in metadata["stations"]
                     if item["supplier_plan_number"] == 2)
    assert (photo_two["chainage_m"], photo_two["bank"]) == (485.0, "Interior")
    cases = comparison["result"]["cases"]
    assert cases[PROPOSAL]["projected_stationary_hydraulic_lap_min"] > cases[REFERENCE]["projected_stationary_hydraulic_lap_min"]
    for name in ("flow_2d.html.gz", "flow_3d.html.gz"):
        assert (ASSETS / name).stat().st_size > 100_000


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
