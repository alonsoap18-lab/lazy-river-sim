"""Checks for the reduced-order 3D decision pilot's underlying balance."""

from math import isclose
from types import SimpleNamespace
import unittest

import numpy as np

from core.riverflow_3d_pilot import assess_speed_band, solve_loop_pilot
from core.beach_geometry import compute_beach_geometry
from core.riverflow_model import compute_riverflow_plan
from core.riverflow_2d import compute_field_2d
from experiments.openfoam_nya_pilot.riverflow_3d_decision_pilot import (
    geometry_from_active_plan, make_plot)
from test_riverflow_model import geometry as test_geometry


def scenario(**changes):
    params = dict(
        chainages_m=[0, 10, 20, 30], section_area_m2=[12, 12, 18, 12],
        wetted_perimeter_m=[14, 14, 20, 14],
        station_manning_n=[.02] * 4,
        module_positions_m=[5, 15, 25], module_angles_deg=[0, 0, 0],
        module_flow_m3_h=500, module_head_m=1.3,
        useful_coupling_fraction=.02, current_reference_width_m=10,
        section_width_m=[10, 10, 15, 10])
    params.update(changes)
    return solve_loop_pilot(**params)


class LoopPilotTests(unittest.TestCase):
    def test_energy_conservation_and_travel_time(self):
        result = scenario()
        q = result.loop_flow_m3_h / 3600
        self.assertTrue(isclose(result.resistance_s2_m5 * q ** 3,
                                result.total_useful_drive_m4_s, rel_tol=1e-12))
        np.testing.assert_allclose(result.section_speed_m_s,
                                   q / result.section_area_m2)
        self.assertTrue(isclose(result.lap_min * 60,
                                result.cumulative_time_s[-1]))

    def test_more_pumps_and_higher_manning_change_same_result_chain(self):
        baseline = scenario()
        more = scenario(module_positions_m=[5, 12, 18, 25],
                        module_angles_deg=[0] * 4)
        rougher = scenario(station_manning_n=[.03] * 4)
        self.assertGreater(more.loop_flow_m3_h, baseline.loop_flow_m3_h)
        self.assertLess(more.lap_min, baseline.lap_min)
        self.assertLess(rougher.loop_flow_m3_h, baseline.loop_flow_m3_h)
        self.assertGreater(rougher.lap_min, baseline.lap_min)

    def test_position_affects_gap_and_width_penalty(self):
        baseline = scenario()
        shifted = scenario(module_positions_m=[2, 17, 19])
        self.assertNotEqual(shifted.max_module_spacing_m,
                            baseline.max_module_spacing_m)
        self.assertLess(shifted.total_useful_drive_m4_s,
                        baseline.total_useful_drive_m4_s)

    def test_invalid_inputs(self):
        for changes in (
            {"section_area_m2": [12, 0, 18, 12]},
            {"module_positions_m": [5, 15, 31]},
            {"useful_coupling_fraction": 1.1},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                scenario(**changes)

    def test_speed_band_detects_geometric_impossibility(self):
        uniform = assess_speed_band([0, 10, 20], [10, 10, 10],
                                    [7, 7, 7], 9900)
        self.assertTrue(uniform.all_sections_feasible)
        self.assertTrue(isclose(uniform.current_coverage_fraction, 1))
        varied = assess_speed_band([0, 10, 20, 30], [5, 5, 10, 10],
                                   [6, 6, 8, 8], 9900)
        self.assertFalse(varied.all_sections_feasible)
        self.assertLess(varied.best_possible_coverage_fraction, 1)
        self.assertGreater(varied.required_flow_lower_m3_h,
                           varied.required_flow_upper_m3_h)

    def test_integrated_3d_reuses_active_plan_without_second_flow_solution(self):
        stations = test_geometry()
        model = SimpleNamespace(stations=stations,
                                geometry=SimpleNamespace(scale_m_per_unit=1.0))
        beach = compute_beach_geometry(stations, 1.2, 15)
        plan = compute_riverflow_plan(
            stations, depth_m=1.2, target_lap_min=40,
            active_modules=19, floor_manning_n=.013,
            wall_manning_n_current=.025, wall_manning_n_calm=.025,
            beach_geometry=beach)
        xy, bed, chainages, widths, result = geometry_from_active_plan(
            model, plan, 1.2, beach, 1/3)
        np.testing.assert_allclose(result.section_speed_m_s,
                                   plan.station_velocities_m_s)
        self.assertTrue(isclose(result.cumulative_time_s[-1] / 60,
                                plan.estimated_lap_min, rel_tol=1e-9))
        fig, rider_index, track, streak_index, streaks = make_plot(
            xy, bed, chainages, widths, beach, result,
            plan.module_chainages_m, [], plan.module_angles_deg)
        self.assertEqual(len(track), 144)
        self.assertEqual(len(streaks), 144)
        self.assertEqual(len(fig.data[streak_index].x), len(streaks[0][0]))
        self.assertEqual(len(fig.data[rider_index].x), 1)
        field = compute_field_2d(stations, plan, 1.2)
        fig_lateral, _, _, lateral_index, lateral_frames = make_plot(
            xy, bed, chainages, widths, beach, result,
            plan.module_chainages_m, [], plan.module_angles_deg, field=field)
        lateral_colors = np.asarray(fig_lateral.data[1].surfacecolor)
        self.assertGreater(float(np.max(np.ptp(lateral_colors, axis=1))), .001)
        self.assertNotEqual(lateral_frames[0][0], lateral_frames[1][0])
        self.assertEqual(len(fig_lateral.data[lateral_index].x),
                         len(lateral_frames[0][0]))
        more_units = compute_riverflow_plan(
            stations, depth_m=1.2, target_lap_min=40,
            active_modules=24, floor_manning_n=.013,
            wall_manning_n_current=.025, wall_manning_n_calm=.025,
            beach_geometry=beach)
        *_, faster = geometry_from_active_plan(model, more_units, 1.2, beach, 1/3)
        self.assertGreater(np.mean(faster.section_speed_m_s),
                           np.mean(result.section_speed_m_s))
        self.assertLess(faster.cumulative_time_s[-1],
                        result.cumulative_time_s[-1])


if __name__ == "__main__":
    unittest.main()
