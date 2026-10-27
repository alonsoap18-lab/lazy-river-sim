"""Cross-check saved CFD diagnostics against their source summary."""

from types import SimpleNamespace
import unittest

from core.riverflow_cfd_decision import (attention_rows,
    compare_editable_to_saved, section_profile)
from core.riverflow_cfd_saved import COUNTS, load_metadata, source_dxf_matches


CASE_NAMES = {16: "16_removed_four", 19: "19_removed",
              20: "20_original", 21: "21_added_downstream"}


class SavedCfdDecisionTest(unittest.TestCase):
    def test_source_dxf_matches_across_checkout_line_endings(self):
        self.assertTrue(source_dxf_matches())

    def test_section_lap_reproduces_saved_source(self):
        _, results = load_metadata()
        for count in COUNTS:
            with self.subTest(count=count):
                speeds = [row["avance_m_s"] for row in section_profile(count)]
                self.assertEqual(len(speeds), 67)
                self.assertTrue(all(speed > 0 for speed in speeds))
                calculated = sum(8/speed for speed in speeds)/60
                source = results["cases"][CASE_NAMES[count]]["snapshots"]["1200"]
                self.assertAlmostEqual(
                    calculated, source["stationary_hydraulic_lap_min"], delta=1e-4)

    def test_saved_layout_comparison_detects_changed_position_and_manning(self):
        manifest, _ = load_metadata()
        pumps = manifest["scenarios"]["19"]["pumps"]
        flow = manifest["reference_flow_us_gpm_per_cf104"] * 0.227124707
        plan = SimpleNamespace(
            active_modules=19, installed_operating_flow_m3_h=19*flow,
            speed_fraction=1.0, length_m=536.0,
            module_chainages_m=tuple(p["chainage_m"] for p in pumps),
            module_banks=tuple(p["bank"] for p in pumps))
        inputs = dict(scenario=19, floor_n=.013, wall_n_current=.025,
                      wall_n_calm=.025, depth_m=1.2, uploaded_dxf=False,
                      source_matches=True, nozzle_type="7 puertos",
                      beach_flat_m=16.0, beach_ramp_pct=6.5)
        _, same = compare_editable_to_saved(plan, **inputs)
        self.assertTrue(same["all_match"])
        _, changed_wall = compare_editable_to_saved(
            plan, **{**inputs, "wall_n_current": .017})
        self.assertFalse(changed_wall["all_match"])
        moved = SimpleNamespace(**{**vars(plan), "module_chainages_m":
            (plan.module_chainages_m[0]+6, *plan.module_chainages_m[1:])})
        _, changed_position = compare_editable_to_saved(moved, **inputs)
        self.assertFalse(changed_position["positions_match"])

    def test_main_beach_does_not_generate_wide_pass_alerts(self):
        self.assertTrue(all("Playa" not in alert["Observación"]
                            for alert in attention_rows(19)))
        self.assertTrue(any(alert["Observación"].startswith("Paso ancho")
                            for alert in attention_rows(19)))


if __name__ == "__main__":
    unittest.main()
