"""Checks that a changed DXF reaches the Riverflow calculations."""

import io
import unittest
from math import isclose

import ezdxf
from ezdxf.math import Matrix44

from core.beach_geometry import check_beach_ramp, compute_beach_geometry
from core.orchestrator import LazyRiverModel
from core.riverflow_model import compute_riverflow_plan


def _model(content=None, *, known_length=None, unit_scale=None):
    model = LazyRiverModel()
    issues = (model.load_dxf(content=content) if content is not None
              else model.load_dxf(path="RECORRIDO.dxf"))
    assert not issues
    model.build_centerline(target_length_m=known_length,
                           meters_per_dxf_unit=unit_scale)
    return model


def test_dxf_with_changed_width_recalculates_length_volume_flow_and_filtration():
    original = _model(known_length=536.0)
    drawing = ezdxf.readfile("RECORRIDO.dxf")
    for wall in drawing.modelspace().query('LWPOLYLINE[layer=="PAREDES"]'):
        wall.transform(Matrix44.scale(1.18, 1.0, 1.0))
    content = io.StringIO()
    drawing.write(content)
    modified = _model(content.getvalue().encode("utf-8"), unit_scale=1.0)
    assert not isclose(modified.geometry.channel_length_m, 536.0, abs_tol=1)
    assert not isclose(modified.geometry.channel_width_avg_m,
                       original.geometry.channel_width_avg_m, abs_tol=.1)

    old_beach = compute_beach_geometry(original.stations, 1.2, 15,
                                       first_share=.62, flat_ramp_slope=.065)
    new_beach = compute_beach_geometry(modified.stations, 1.2, 15,
                                       first_share=.62, flat_ramp_slope=.065)
    old_plan = compute_riverflow_plan(original.stations, depth_m=1.2,
                                      target_lap_min=40, active_modules=19,
                                      beach_geometry=old_beach)
    new_plan = compute_riverflow_plan(modified.stations, depth_m=1.2,
                                      target_lap_min=40, active_modules=19,
                                      beach_geometry=new_beach)
    assert not isclose(new_plan.volume_m3, old_plan.volume_m3, rel_tol=.01)
    assert isclose(new_plan.target_equivalent_flow_m3_h, new_plan.volume_m3 * 60 / 40)
    assert isclose(new_plan.filtration_flow_m3_h, new_plan.volume_m3 / 4)
    assert not isclose(new_plan.target_equivalent_flow_m3_h,
                       old_plan.target_equivalent_flow_m3_h, rel_tol=.01)
    assert not isclose(new_plan.channel_resistance_s2_m5,
                       old_plan.channel_resistance_s2_m5, rel_tol=.01)


def test_beach_ramp_reports_missing_width_without_altering_slope():
    result = check_beach_ramp(1.2, 8.5559225473, .065)
    assert isclose(result.required_ramp_m, 18.46153846, rel_tol=1e-6)
    assert isclose(result.additional_ramp_m, 9.90561591, rel_tol=1e-6)
    assert isclose(result.edge_depth_m, .64386503, rel_tol=1e-6)
    assert isclose(result.slope_to_fit, .140253, rel_tol=1e-4)
    assert check_beach_ramp(1.2, 20, .065).additional_ramp_m == 0


def test_length_and_unit_scale_cannot_both_be_applied():
    try:
        _model(known_length=536, unit_scale=1)
    except ValueError as exc:
        assert "longitud conocida" in str(exc)
    else:
        raise AssertionError("Se aceptaron dos escalas incompatibles")


class NewDXFTests(unittest.TestCase):
    def test_changed_geometry(self):
        test_dxf_with_changed_width_recalculates_length_volume_flow_and_filtration()

    def test_ramp_width(self):
        test_beach_ramp_reports_missing_width_without_altering_slope()

    def test_scale_validation(self):
        test_length_and_unit_scale_cannot_both_be_applied()


if __name__ == "__main__":
    unittest.main()
