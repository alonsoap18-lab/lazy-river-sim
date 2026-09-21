"""DXF file loader - extracts geometry from AutoCAD files."""
import ezdxf
import numpy as np
from shapely.geometry import Polygon, LineString
from typing import List, Tuple, Optional
import tempfile
import os


class DXFLoader:
    """Loads and validates DXF geometry from PAREDES layer."""

    def __init__(self, dxf_path: str = None, dxf_content: bytes = None):
        self.dxf_path = dxf_path
        self.polylines: List[Polygon] = []
        self.outer_polygon: Optional[Polygon] = None
        self.inner_polygon: Optional[Polygon] = None
        self.outer_wall: Optional[LineString] = None
        self.inner_wall: Optional[LineString] = None
        self.domain_polygon = None
        self.errors: List[str] = []
        self.warnings: List[str] = []

        if dxf_content:
            self._load_from_bytes(dxf_content)
        elif dxf_path and os.path.exists(dxf_path):
            self._load_from_file()
        else:
            self.errors.append("No DXF source provided")

    def _load_from_file(self):
        try:
            doc = ezdxf.readfile(self.dxf_path)
            self._extract_entities(doc)
        except Exception as e:
            self.errors.append(f"Error reading DXF: {e}")

    def _load_from_bytes(self, content: bytes):
        with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            doc = ezdxf.readfile(tmp_path)
            self._extract_entities(doc)
        except Exception as e:
            self.errors.append(f"Error reading DXF bytes: {e}")
        finally:
            os.unlink(tmp_path)

    def _extract_entities(self, doc):
        msp = doc.modelspace()
        found_paredes = False

        for entity in msp:
            layer = entity.dxf.layer if hasattr(entity.dxf, 'layer') else ''
            if layer != 'PAREDES':
                continue
            found_paredes = True
            self._process_entity(entity)

        if not found_paredes:
            self.warnings.append("Layer 'PAREDES' not found in DXF")

        if len(self.polylines) >= 2:
            self._build_walls()
        elif len(self.polylines) == 1:
            self.warnings.append("Only 1 polyline found in PAREDES")
            self.outer_polygon = self.polylines[0]
            self.outer_wall = LineString(list(self.outer_polygon.exterior.coords))
            self.inner_wall = self.outer_wall
            self.domain_polygon = self.outer_polygon

    def _process_entity(self, entity):
        etype = entity.dxftype()

        if etype == 'LWPOLYLINE':
            points = [(p[0], p[1]) for p in entity.get_points(format='xy')]
            if len(points) >= 3 and entity.closed:
                poly = Polygon(points)
                if poly.is_valid and poly.area > 0:
                    self.polylines.append(poly)
                else:
                    self.warnings.append(f"Invalid LWPOLYLINE (area={poly.area:.1f})")
            elif not entity.closed:
                self.warnings.append("Open LWPOLYLINE ignored (not closed)")

        elif etype == 'POLYLINE':
            if entity.is_closed:
                points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
                if len(points) >= 3:
                    poly = Polygon(points)
                    if poly.is_valid and poly.area > 0:
                        self.polylines.append(poly)

    def _build_walls(self):
        self.polylines.sort(key=lambda p: p.area, reverse=True)
        self.outer_polygon = self.polylines[0]
        self.inner_polygon = self.polylines[1]

        self.outer_wall = LineString(list(self.outer_polygon.exterior.coords))
        self.inner_wall = LineString(list(self.inner_polygon.exterior.coords))

        self.domain_polygon = self.outer_polygon.difference(self.inner_polygon)
        if not self.domain_polygon.is_valid:
            self.domain_polygon = self.domain_polygon.buffer(0)

    def validate(self) -> List[str]:
        issues = []
        if not self.outer_wall:
            issues.append("No outer wall extracted")
        if not self.inner_wall:
            issues.append("No inner wall extracted")
        if self.outer_wall and self.inner_wall:
            if self.outer_wall == self.inner_wall:
                issues.append("Outer and inner walls are identical")
        if self.domain_polygon and self.domain_polygon.area <= 0:
            issues.append("Domain polygon has zero area")
        if self.outer_polygon and self.inner_polygon:
            if self.inner_polygon.area >= self.outer_polygon.area:
                issues.append("Inner polygon is larger than outer")
        return issues

    def get_outer_coords(self) -> List[tuple]:
        if self.outer_wall:
            return list(self.outer_wall.coords)
        return []

    def get_inner_coords(self) -> List[tuple]:
        if self.inner_wall:
            return list(self.inner_wall.coords)
        return []
