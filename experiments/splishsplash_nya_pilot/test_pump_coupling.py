"""Regression checks for the isolated reference coupling, not NYA validation."""

import unittest

from experiments.splishsplash_nya_pilot.pump_coupling import (
    REFERENCE_FLOW_GPM, TOTAL_SEVEN_PORT_AREA_M2, US_GPM_TO_M3_H,
    solve_reference_coupling,
)


class PumpCouplingTests(unittest.TestCase):
    def test_reference_intersection_matches_published_arrangement(self):
        point = solve_reference_coupling()
        self.assertAlmostEqual(point.pump_flow_m3_h,
                               REFERENCE_FLOW_GPM * US_GPM_TO_M3_H,
                               delta=1.0)
        self.assertAlmostEqual(point.pump_head_ft, 6.5, delta=0.05)
        self.assertAlmostEqual(point.aggregate_nozzle_speed_m_s,
                               point.pump_flow_m3_h / 3600 /
                               TOTAL_SEVEN_PORT_AREA_M2)

    def test_two_suction_boxes_balance_one_discharge(self):
        point = solve_reference_coupling()
        self.assertAlmostEqual(point.each_suction_box_flow_m3_h * 2,
                               point.pump_flow_m3_h)
        self.assertAlmostEqual(point.nominal_particle_transfer_interval_s,
                               point.particle_volume_m3 /
                               (point.pump_flow_m3_h / 3600))

    def test_more_head_loss_reduces_flow(self):
        low_loss = solve_reference_coupling(system_head_factor=.8)
        reference = solve_reference_coupling()
        high_loss = solve_reference_coupling(system_head_factor=1.2)
        self.assertGreater(low_loss.pump_flow_m3_h, reference.pump_flow_m3_h)
        self.assertGreater(reference.pump_flow_m3_h, high_loss.pump_flow_m3_h)

    def test_invalid_inputs_rejected(self):
        for value in (0, -1, float("nan")):
            with self.assertRaises(ValueError):
                solve_reference_coupling(system_head_factor=value)


if __name__ == "__main__":
    unittest.main()
