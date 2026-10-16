"""Regression checks for the shared Riverflow map and scenario arithmetic."""

import unittest
from math import isclose

import numpy as np

from core.beach_geometry import compute_beach_geometry
from core.orchestrator import LazyRiverModel
from core.riverflow_2d import compute_field_2d
from core.riverflow_decision import consistency_checks, evaluate_decision_cases
from core.riverflow_model import compute_riverflow_plan
from core.riverflow_placement import (cumulative_manning_resistance,
                                      curve_candidates,
                                      suggest_curve_aware_positions)
from experiments.openfoam_nya_pilot.riverflow_3d_decision_pilot import (
    geometry_from_active_plan, make_plot)
from riverflow_app import make_map


class RiverflowMapConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = LazyRiverModel()
        assert cls.model.load_dxf("RECORRIDO.dxf") == []
        cls.model.build_centerline(target_length_m=536)
        cls.beach = compute_beach_geometry(
            cls.model.stations, 1.2, 15, .62, flat_ramp_slope=.065)

    def test_only_main_beach_is_calm_and_wide_passages_remain_current(self):
        plan = compute_riverflow_plan(
            self.model.stations, depth_m=1.2, target_lap_min=40,
            active_modules=19, beach_geometry=self.beach)
        beach_indices = set(self.beach.beach_indices)
        if 0 in beach_indices:
            beach_indices.add(len(self.model.stations) - 1)
        calm_core = {i for i in beach_indices
                     if float(self.model.stations[i]["width_m"]) >= 15}
        self.assertEqual({i for i, zone in enumerate(plan.station_zones)
                          if zone == "calm"}, calm_core)
        self.assertTrue(any(plan.station_zones[i] == "current" and
                            float(self.model.stations[i]["width_m"]) < 15
                            for i in beach_indices))
        self.assertTrue(any(float(station["width_m"]) >= 15 and zone == "current"
                            for station, zone in zip(self.model.stations,
                                                     plan.station_zones)))

    def test_default_layout_has_separation_and_both_banks(self):
        provisional = compute_riverflow_plan(
            self.model.stations, depth_m=1.2, target_lap_min=40,
            active_modules=19, beach_geometry=self.beach,
            floor_manning_n=.013, wall_manning_n_current=.025,
            wall_manning_n_calm=.025)
        resistance = cumulative_manning_resistance(
            self.model.stations, provisional.station_areas_m2,
            self.beach.wetted_perimeter_m, provisional.station_manning_n)
        bends = curve_candidates(self.model.stations, provisional.station_zones,
                                 self.model.geometry.scale_m_per_unit)
        positions, banks = suggest_curve_aware_positions(
            self.model.stations, resistance, provisional.station_zones, 19, bends)
        self.assertEqual(len(positions), 19)
        self.assertGreaterEqual(min(np.diff(positions)), 12)
        self.assertIn("Exterior", banks)
        self.assertIn("Interior", banks)
        for position in positions:
            index = min(range(len(self.model.stations)), key=lambda i:
                        abs(self.model.stations[i]["chainage_m"] - position))
            self.assertEqual(provisional.station_zones[index], "current")

    def test_2d_markers_keep_banks_when_plumbing_is_hidden(self):
        plan = compute_riverflow_plan(
            self.model.stations, depth_m=1.2, target_lap_min=40,
            active_modules=2, module_chainages_m=(100, 300),
            module_banks=("Interior", "Exterior"), beach_geometry=self.beach)
        shown = make_map(self.model, plan, show_installation=True,
                         show_velocity_heatmap=False)
        hidden = make_map(self.model, plan, show_installation=False,
                          show_velocity_heatmap=False)
        for bank in ("interior", "exterior"):
            name = f"Riverflow · margen {bank}"
            a = next(trace for trace in shown.data if trace.name == name)
            b = next(trace for trace in hidden.data if trace.name == name)
            self.assertEqual(list(a.x), list(b.x))
            self.assertEqual(list(a.y), list(b.y))

    def test_3d_uses_same_bank_and_positive_angle_aims_to_selected_bank(self):
        plan = compute_riverflow_plan(
            self.model.stations, depth_m=1.2, target_lap_min=40,
            active_modules=2, module_chainages_m=(100, 300),
            module_banks=("Interior", "Exterior"), beach_geometry=self.beach)
        xy, bed, chainages, widths, result = geometry_from_active_plan(
            self.model, plan, 1.2, self.beach, .62)
        figure, *_ = make_plot(
            xy, bed, chainages, widths, self.beach, result,
            plan.module_chainages_m, [], module_angles_deg=(15, 15),
            module_banks=plan.module_banks)
        groups = [trace for trace in figure.data if trace.name and
                  trace.name.startswith("RF · margen")]
        self.assertEqual(sum(len(trace.x) for trace in groups), 2)
        arrows = [trace for trace in figure.data if trace.type == "scatter3d"
                  and trace.mode == "lines" and trace.line.color == "#df743d"]
        self.assertEqual(len(arrows), 2)
        indices = np.searchsorted(chainages, plan.module_chainages_m).clip(
            1, len(chainages) - 2)
        for arrow, index, bank in zip(arrows, indices, plan.module_banks):
            direction = np.array([arrow.x[1] - arrow.x[0],
                                  arrow.y[1] - arrow.y[0]])
            outward = xy[index, -1] - xy[index, 0]
            sign = 1 if bank == "Exterior" else -1
            self.assertGreater(float(np.dot(direction, outward)) * sign, 0)

    def test_same_layout_and_arithmetic_across_sensitivity_cases(self):
        plan = compute_riverflow_plan(
            self.model.stations, depth_m=1.2, target_lap_min=40,
            active_modules=2, module_chainages_m=(100, 300),
            module_banks=("Interior", "Exterior"), beach_geometry=self.beach)
        field = compute_field_2d(
            self.model.stations, plan, 1.2,
            scale_m_per_unit=self.model.geometry.scale_m_per_unit)
        cases = evaluate_decision_cases(
            self.model.stations, current_plan=plan, current_field=field,
            depth_m=1.2, scale_m_per_unit=self.model.geometry.scale_m_per_unit,
            calm_zone_width_m=15, floor_manning_n=.013,
            wall_manning_n_current=.025, wall_manning_n_calm=.025,
            filtration_turnover_h=4, beach_geometry=self.beach)
        for case in cases:
            self.assertIsNotNone(case.plan, case.error)
            self.assertEqual(case.plan.module_banks, plan.module_banks)
            self.assertEqual(case.plan.module_chainages_m, plan.module_chainages_m)
            self.assertTrue(all(ok for _, ok in consistency_checks(case.plan, 4)))
            self.assertTrue(isclose(case.plan.filtration_flow_m3_h,
                                    case.plan.volume_m3 / 4, rel_tol=1e-12))


if __name__ == "__main__":
    unittest.main()
