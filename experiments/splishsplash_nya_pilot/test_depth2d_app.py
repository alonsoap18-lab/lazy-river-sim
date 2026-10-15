"""Smoke test for the pilot's save/open workflow without touching user scenarios."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from experiments.splishsplash_nya_pilot import scenario_store


PILOT_DIR = Path(__file__).parent


class ScenarioAppTests(unittest.TestCase):
    def test_embedded_sheet_keeps_scenarios_in_session(self):
        app = AppTest.from_file(str(PILOT_DIR / "embedded_depth2d_smoke.py"),
                                default_timeout=90).run()
        self.assertFalse(app.exception)
        next(item for item in app.button if item.label == "Calcular ubicación inicial y variante").click().run()
        self.assertFalse(app.exception)
        next(item for item in app.text_input if item.label == "Nombre para guardar esta distribución").set_value(
            "Web sin archivo compartido")
        next(item for item in app.button if item.label == "Guardar esta configuración").click().run()
        self.assertFalse(app.exception)
        self.assertIn("Web sin archivo compartido", app.session_state["depth2d_session_scenarios"])

    def test_save_and_open_in_app(self):
        with tempfile.TemporaryDirectory(dir=PILOT_DIR / "runtime") as directory:
            path = Path(directory) / "scenarios.json"
            with patch.object(scenario_store, "SCENARIO_FILE", path):
                app = AppTest.from_file(str(PILOT_DIR / "depth2d_pilot.py"),
                                        default_timeout=90).run()
                self.assertFalse(app.exception)
                next(item for item in app.selectbox if item.label == "Variante para comparar").set_value(
                    "Arrastrar bombas en el mapa")
                next(item for item in app.number_input if item.label.startswith("Manning n · paredes")).set_value(0.034)
                next(item for item in app.button if item.label == "Calcular ubicación inicial y variante").click().run()
                self.assertFalse(app.exception)
                next(item for item in app.text_input if item.label == "Nombre para guardar esta distribución").set_value(
                    "Ensayo guardado de prueba")
                next(item for item in app.button if item.label == "Guardar esta configuración").click().run()
                self.assertFalse(app.exception)
                self.assertIn("Ensayo guardado de prueba", scenario_store.read_scenarios(path))
                self.assertAlmostEqual(
                    scenario_store.settings_from_record(
                        scenario_store.read_scenarios(path)["Ensayo guardado de prueba"]
                    ).wall_manning_n, 0.034)
                next(item for item in app.button if item.label == "Abrir escenario guardado").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["depth2d_results"][2],
                                 "Arrastrar bombas en el mapa")


if __name__ == "__main__":
    unittest.main()
