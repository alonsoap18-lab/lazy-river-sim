"""Numerical consistency checks, not hydraulic validation."""

import unittest
import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np

from experiments.splishsplash_nya_pilot.depth2d_flow import (
    Flow2DInputs, load_nya, solve,
)
from experiments.splishsplash_nya_pilot.layout_screening import (
    indicators, screening_score,
)
from experiments.splishsplash_nya_pilot.depth2d_pilot import (
    drag_candidates, validate_drag_move,
)
from experiments.splishsplash_nya_pilot.scenario_store import (
    read_scenarios, save_scenario, settings_from_record,
)
from experiments.riverflow_layout_metrics import classify_beach_core


class Depth2DTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.beach = load_nya()

    def test_closed_mass_balance_and_spatial_velocity(self):
        result = solve(Flow2DInputs(steps=60, count=16),
                       model=self.model, beach=self.beach)
        wet = result["grid"]["wet"]
        self.assertAlmostEqual(result["diagnostics"]["net_pump_source_m3_s"], 0, places=10)
        self.assertLess(result["diagnostics"]["mass_error_max_m3_s_per_cell"], 1e-8)
        self.assertGreater(np.std(result["u"][wet]), 1e-5)
        self.assertGreater(np.std(result["v"][wet]), 1e-5)
        self.assertGreater(result["diagnostics"]["volume_m3_raster"], 6000)

    def test_wall_manning_changes_2d_field_and_uses_1d_section_resistance(self):
        base_inputs = Flow2DInputs(steps=120, count=16)
        base = solve(base_inputs, model=self.model, beach=self.beach)
        rougher = solve(replace(base_inputs, wall_manning_n=.05),
                        model=self.model, beach=self.beach)
        wet = base["grid"]["wet"]
        self.assertGreater(float(np.max(np.hypot(
            base["u"][wet] - rougher["u"][wet],
            base["v"][wet] - rougher["v"][wet]))), 1e-7)
        self.assertGreater(float(np.mean(
            rougher["grid"]["effective_manning"][wet])),
            float(np.mean(base["grid"]["effective_manning"][wet])))
        self.assertAlmostEqual(rougher["diagnostics"]["net_pump_source_m3_s"],
                               0, places=10)

    def test_relocation_changes_field_without_changing_total_mass(self):
        base = solve(Flow2DInputs(steps=60, count=16),
                     model=self.model, beach=self.beach)
        original = base["pump_sites"][0]
        moved = solve(Flow2DInputs(steps=60, count=16, moved_pump_index=0,
                                   moved_chainage_m=(original["chainage_m"] + 20) % 536,
                                   moved_bank="Exterior"),
                      model=self.model, beach=self.beach)
        wet = base["grid"]["wet"]
        delta = np.hypot(base["u"][wet] - moved["u"][wet],
                         base["v"][wet] - moved["v"][wet])
        self.assertGreater(float(np.mean(delta)), 1e-5)
        self.assertAlmostEqual(moved["diagnostics"]["net_pump_source_m3_s"], 0, places=10)

    def test_multiple_relocations_preserve_mass_and_change_rotation_indicator(self):
        baseline = solve(Flow2DInputs(steps=60, count=20),
                         model=self.model, beach=self.beach)
        settings = Flow2DInputs(steps=60, count=20,
                                site_overrides=((0, 38.4, "Interior"),
                                                (14, 356.6, "Exterior")))
        result = solve(settings, model=self.model, beach=self.beach)
        self.assertAlmostEqual(result["diagnostics"]["net_pump_source_m3_s"], 0, places=10)
        self.assertNotEqual(indicators(baseline)["core_rotation_rms_s_1"],
                            indicators(result)["core_rotation_rms_s_1"])
        self.assertEqual(result["pump_sites"][0]["chainage_m"], 38.4)

    def test_screening_rejects_wide_passage_flow_loss(self):
        baseline = {"forward_mean_m_s": .01,
                    "wide_passage_forward_m_s": [.003, .0001],
                    "reverse_area_fraction": .1,
                    "core_rotation_rms_s_1": .005,
                    "slow_area_fraction": .2}
        candidate = dict(baseline, wide_passage_forward_m_s=[.003, -.0001])
        self.assertEqual(screening_score(candidate, baseline), float("inf"))

    def test_duplicate_site_override_rejected(self):
        with self.assertRaises(ValueError):
            Flow2DInputs(count=20, site_overrides=((0, 32., "Interior"),
                                                   (0, 40., "Exterior"))).validate()

    def test_drag_candidates_exclude_only_calm_beach_core(self):
        candidates = drag_candidates(self.model, self.beach)
        zones = classify_beach_core(self.model.stations, self.beach, 15.0)
        calm_chainages = {round(float(station["chainage_m"]), 1)
                           for station, zone in zip(self.model.stations, zones)
                           if zone == "calm"}
        self.assertGreater(len(candidates), 100)
        self.assertTrue(all(s not in calm_chainages for s, *_ in candidates))
        # Pumps 23 and 24 of the 24-unit layout are in a narrow flowing
        # approach to the beach, not in its wide calm entry/exit core.
        for position in (454.2, 485.9):
            self.assertLess(min(abs(s - position) for s, bank, *_ in candidates
                                if bank == "Interior"), 2.0)

    def test_drag_validation_blocks_beach_and_same_bank_collision(self):
        candidates = drag_candidates(self.model, self.beach)
        s, bank, *_ = candidates[20]
        sites = [{"chainage_m": s, "bank": bank},
                 {"chainage_m": (s + 5) % 536, "bank": bank}]
        self.assertIn("12 m", validate_drag_move(0, s, bank, sites, candidates))
        self.assertIn("orilla permitida", validate_drag_move(0, 999, bank, sites, candidates))
        sites[1]["bank"] = "Exterior" if bank == "Interior" else "Interior"
        self.assertIsNone(validate_drag_move(0, s, bank, sites, candidates))

    def test_saved_drag_scenario_roundtrip_and_duplicate_protection(self):
        settings = Flow2DInputs(count=20, momentum_fraction=.15,
                                nozzle_angle_deg=5, eddy_viscosity_m2_s=.08,
                                site_overrides=((0, 38.4, "Interior"),
                                                (14, 356.6, "Exterior")))
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / "runtime") as directory:
            path = Path(directory) / "saved.json"
            save_scenario("Curvas A", settings, path)
            stored = read_scenarios(path)
            self.assertEqual(settings_from_record(stored["Curvas A"]), settings)
            with self.assertRaisesRegex(ValueError, "Ya existe"):
                save_scenario("Curvas A", settings, path)
            self.assertEqual(list(read_scenarios(path)), ["Curvas A"])

    def test_invalid_scenario_not_accepted(self):
        with self.assertRaisesRegex(ValueError, "Formato"):
            settings_from_record({"version": 99})
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / "runtime") as directory:
            path = Path(directory) / "saved.json"
            path.write_text("{truncado", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "No se pudo leer"):
                read_scenarios(path)


if __name__ == "__main__":
    unittest.main()
