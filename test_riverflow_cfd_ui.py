"""The experimental tab must never show a stale map after manual changes."""

from streamlit.testing.v1 import AppTest


def test_cfd_tab_requires_rerun_after_scenario_change():
    app = AppTest.from_file("app.py", default_timeout=90).run()
    assert not app.exception
    next(item for item in app.radio if item.label == "Seleccionar modelo").set_value(
        "Riverflow · módulos locales")
    app.run()
    assert not app.exception
    assert any(tab.label == "Simulación 2D experimental" for tab in app.tabs)
    next(item for item in app.slider if item.label == "Arranque simulado (min)").set_value(1)
    next(item for item in app.select_slider if item.label == "Tamaño de celda (m)").set_value(3.0)
    app.run()
    next(item for item in app.button if item.label ==
         "Ejecutar simulación 2D experimental").click()
    app.run()
    assert not app.exception
    assert any(item.label == "Rapidez media · arranque" for item in app.metric)
    lap_before = next(item for item in app.metric if item.label == "Vuelta media V/Q").value
    next(item for item in app.slider if item.label == "Manning n · piso liso").set_value(.020)
    app.run()
    assert not app.exception
    assert not any(item.label == "Rapidez media · arranque" for item in app.metric)
    assert any("se oculta para evitar mezclar escenarios" in item.value for item in app.warning)
    assert next(item for item in app.metric if item.label == "Vuelta media V/Q").value != lap_before


if __name__ == "__main__":
    test_cfd_tab_requires_rerun_after_scenario_change()
    print("Experimental CFD tab checks passed")
