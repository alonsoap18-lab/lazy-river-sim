"""Checks for the precomputed SPH sheet and conservative lap gate."""

import json
import unittest

from core.sph_quality import conditional_lap
from core.sph_public_sheet import SNAPSHOT, lane_heatmap, scenario_differences


class SphSheetTests(unittest.TestCase):
    def test_lap_requires_local_stability_not_just_median(self):
        baseline = [0.25] * 100
        unstable = baseline.copy()
        unstable[:12] = [0.18] * 12
        frames = [
            {"section_mean_along_m_s": unstable, "section_particle_count": [10] * 100},
            {"section_mean_along_m_s": unstable, "section_particle_count": [10] * 100},
            {"section_mean_along_m_s": baseline, "section_particle_count": [10] * 100},
        ]
        result = conditional_lap(frames)
        self.assertIsNone(result["lap_min"])
        self.assertGreater(result["p90_relative_drift"], .15)

    def test_lap_for_covered_stable_sections(self):
        frames = [{"section_mean_along_m_s": [.25] * 100,
                   "section_particle_count": [10] * 100} for _ in range(3)]
        self.assertAlmostEqual(conditional_lap(frames)["lap_min"], 536 / .25 / 60)

    def test_bundled_run_is_not_promoted_to_lap(self):
        report = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        self.assertEqual(report["pump_count"], 24)
        self.assertEqual(report["conditional_lap_min"], None)
        self.assertEqual(report["initial_particles"], report["final_particles"])
        self.assertEqual(len(report["repeat_check"]), 2)
        self.assertEqual(len(report["ports"]), 24)
        self.assertGreater(len(report["frames"]), 10)
        chart, count = lane_heatmap(report)
        self.assertGreaterEqual(count, 0)
        self.assertEqual(len(chart.data[0].z), 3)

    def test_active_controls_do_not_silently_change_snapshot(self):
        report = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        differences = scenario_differences(
            report, length_m=536, depth_m=1.2, pump_count=19,
            speed_fraction=1.0, uploaded_dxf=False, nozzle_type="7 puertos",
            chainages_m=[], banks=[])
        self.assertIn("cantidad de bombas", differences)
        self.assertIn("variador", differences)
        self.assertIn("posición u orilla de las bombas", differences)


if __name__ == "__main__":
    unittest.main()
