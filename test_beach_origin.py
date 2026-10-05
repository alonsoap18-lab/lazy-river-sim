"""The beach origin changes chainage, not the DXF shape or hydraulic totals."""

from math import isclose

from core.beach_geometry import compute_beach_geometry
from core.centerline import (CenterlineBuilder, orient_stations_counterclockwise,
                             signed_centerline_area, start_stations_at_widest_beach)
from core.orchestrator import LazyRiverModel
from core.riverflow_model import compute_riverflow_plan


def test_widest_beach_is_closed_loop_origin():
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    stations = model.stations
    assert isclose(stations[0]["width_m"], max(s["width_m"] for s in stations))
    assert isclose(stations[0]["x"], stations[-1]["x"])
    assert isclose(stations[0]["y"], stations[-1]["y"])
    assert isclose(stations[-1]["chainage_m"], 536)
    assert signed_centerline_area(stations) > 0
    assert all(b["chainage_m"] > a["chainage_m"]
               for a, b in zip(stations, stations[1:]))
    assert isclose(start_stations_at_widest_beach(stations)[0]["dxf_origin_chainage_m"],
                   stations[0]["dxf_origin_chainage_m"])


def test_reindex_preserves_volume_filtration_and_lap_within_sampling_error():
    model = LazyRiverModel()
    assert model.load_dxf("RECORRIDO.dxf") == []
    model.build_centerline(target_length_m=536)
    builder = CenterlineBuilder(model.loader.outer_wall, model.loader.inner_wall,
                                resolution_m=0.5)
    builder.build()
    old_stations = builder.get_station_data()
    scale = 536 / old_stations[-1]["chainage_m"]
    for station in old_stations:
        station["chainage_m"] *= scale
        station["width_m"] *= scale
    old_stations = orient_stations_counterclockwise(old_stations)
    old_beach = compute_beach_geometry(old_stations, 1.2)
    new_beach = compute_beach_geometry(model.stations, 1.2)
    assert new_beach.beach_start_m > new_beach.beach_end_m
    assert isclose(new_beach.area_m2[0], new_beach.area_m2[-1])
    old_plan = compute_riverflow_plan(old_stations, depth_m=1.2,
                                      target_lap_min=40, active_modules=19,
                                      beach_geometry=old_beach)
    new_plan = compute_riverflow_plan(model.stations, depth_m=1.2,
                                      target_lap_min=40, active_modules=19,
                                      beach_geometry=new_beach)
    for old, new in ((old_plan.volume_m3, new_plan.volume_m3),
                     (old_plan.filtration_flow_m3_h, new_plan.filtration_flow_m3_h),
                     (old_plan.estimated_lap_min, new_plan.estimated_lap_min)):
        assert isclose(old, new, rel_tol=0.001)
