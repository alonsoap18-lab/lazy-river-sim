"""Consistency tests for the 536 m reduced-order trial, not CFD validation."""

import unittest

import numpy as np

from experiments.riverflow_layout_metrics import LayoutSite
from experiments.splishsplash_nya_pilot.full_loop_2d import (
    TrialInputs, load_nya, mass_balanced_flux, solve_case,
)


class FullLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.beach = load_nya()

    def test_complete_loop_and_mass_balance(self):
        case = solve_case(self.model, self.beach, TrialInputs(), 20)
        self.assertAlmostEqual(case["length_m"], 536)
        self.assertEqual(len(case["chainage_mid_m"]), 536)
        self.assertEqual(len(case["pump_sites"]), 20)
        self.assertAlmostEqual(case["mass_balance_residual_m3_s"], 0, places=12)
        self.assertGreater(min(case["local_channel_flow_m3_h"]), 0)
        self.assertAlmostEqual(case["filtration_flow_4h_m3_h"],
                               case["volume_m3"] / 4)

    def test_bypass_zero_net_and_works_across_origin(self):
        class Pump:
            chainage_m = 2.0
        mid = np.arange(.5, 536, 1.0)
        flux, residual = mass_balanced_flux(mid, 536, (Pump(),), .125, 5)
        self.assertAlmostEqual(residual, 0)
        self.assertAlmostEqual(float(flux.mean()), 0, places=12)
        self.assertGreater(float(flux.max() - flux.min()), .12)

    def test_grid_and_intake_spacing_sensitivity(self):
        base = solve_case(self.model, self.beach, TrialInputs(), 20)
        fine = solve_case(self.model, self.beach,
                          TrialInputs(cell_length_m=.5), 20)
        coarse = solve_case(self.model, self.beach,
                            TrialInputs(cell_length_m=2), 20)
        for alt in (fine, coarse):
            self.assertAlmostEqual(alt["required_longitudinal_transfer_fraction"],
                                   base["required_longitudinal_transfer_fraction"],
                                   delta=.002)
            self.assertAlmostEqual(alt["conditional_lap_min"],
                                   base["conditional_lap_min"], delta=.2)
        separated = solve_case(self.model, self.beach,
                               TrialInputs(intake_upstream_m=10), 20)
        self.assertAlmostEqual(separated["mass_balance_residual_m3_s"], 0)

    def test_width_variation_prevents_one_uniform_speed_band(self):
        case = solve_case(self.model, self.beach, TrialInputs(), 20)
        self.assertFalse(case["single_uniform_flow_can_hold_all_passages_0_25_to_0_30"])
        self.assertFalse(case["beach_reaches_dry_sand_inside_dxf"])
        self.assertGreater(case["passage_fraction_above_0_45"], 0)
        self.assertGreater(case["required_longitudinal_transfer_fraction"], 0)

    def test_assumed_transfer_changes_flow_with_count(self):
        low_count = solve_case(self.model, self.beach, TrialInputs(), 16,
                               assumed_transfer_fraction=.10)
        high_count = solve_case(self.model, self.beach, TrialInputs(), 28,
                                assumed_transfer_fraction=.10)
        self.assertAlmostEqual(low_count["required_longitudinal_transfer_fraction"],
                               .10, places=9)
        self.assertAlmostEqual(high_count["required_longitudinal_transfer_fraction"],
                               .10, places=9)
        self.assertGreater(high_count["actual_typical_passage_speed_m_s"],
                           low_count["actual_typical_passage_speed_m_s"])
        self.assertLess(high_count["conditional_lap_min"],
                        low_count["conditional_lap_min"])
        self.assertAlmostEqual(low_count["mass_balance_residual_m3_s"], 0)

    def test_unmeasured_transfer_is_not_silently_assumed(self):
        target = solve_case(self.model, self.beach, TrialInputs(), 20)
        self.assertEqual(target["flow_mode"], "imposed_typical_speed")
        self.assertIsNone(target["assumed_transfer_fraction"])
        with self.assertRaises(ValueError):
            solve_case(self.model, self.beach, TrialInputs(), 20,
                       assumed_transfer_fraction=0)

    def test_relocating_pump_recalculates_balanced_flow(self):
        baseline = solve_case(self.model, self.beach, TrialInputs(), 20,
                              assumed_transfer_fraction=.10)
        sites = [LayoutSite(p["chainage_m"], p["bank"], p["purpose"])
                 for p in baseline["pump_sites"]]
        moved = sites[0]
        sites[0] = LayoutSite((moved.chainage_m + 20) % 536,
                              "Interior" if moved.bank == "Exterior" else "Exterior",
                              moved.purpose)
        new = solve_case(self.model, self.beach, TrialInputs(), 20,
                         assumed_transfer_fraction=.10,
                         pump_sites_override=tuple(sites))
        self.assertAlmostEqual(new["mass_balance_residual_m3_s"], 0)
        self.assertAlmostEqual(new["pump_sites"][0]["chainage_m"], sites[0].chainage_m)
        self.assertNotEqual(new["local_channel_flow_m3_h"],
                            baseline["local_channel_flow_m3_h"])
        with self.assertRaises(ValueError):
            solve_case(self.model, self.beach, TrialInputs(), 20,
                       pump_sites_override=tuple(sites[:-1]))


if __name__ == "__main__":
    unittest.main()
