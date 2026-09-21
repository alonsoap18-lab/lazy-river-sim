"""Field data import from CSV."""
import csv
from typing import List, Optional
from models.geometry_model import FieldMeasurement


class FieldDataLoader:
    """Loads field measurements from CSV files."""

    EXPECTED_COLUMNS = [
        'timestamp', 'station_id', 'chainage_m', 'velocity_m_s',
        'depth_m', 'temperature_c', 'flow_m3_h', 'pressure_pa',
        'pump_id', 'jet_state', 'people_count', 'notes'
    ]

    def __init__(self):
        self.measurements: List[FieldMeasurement] = []
        self.errors: List[str] = []

    def load_csv(self, filepath: str) -> List[FieldMeasurement]:
        self.measurements = []
        self.errors = []

        try:
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    try:
                        m = self._parse_row(row, i)
                        self.measurements.append(m)
                    except Exception as e:
                        self.errors.append(f"Row {i+2}: {e}")
        except Exception as e:
            self.errors.append(f"Error opening file: {e}")

        return self.measurements

    def _parse_row(self, row: dict, row_idx: int) -> FieldMeasurement:
        def get_float(key, default=0.0):
            val = row.get(key, '').strip()
            if val == '':
                return default
            return float(val)

        def get_int(key, default=0):
            val = row.get(key, '').strip()
            if val == '':
                return default
            return int(float(val))

        def get_str(key, default=''):
            return row.get(key, default).strip()

        return FieldMeasurement(
            timestamp=get_str('timestamp'),
            station_id=get_int('station_id'),
            chainage_m=get_float('chainage_m'),
            velocity_m_s=get_float('velocity_m_s'),
            depth_m=get_float('depth_m'),
            temperature_c=get_float('temperature_c'),
            flow_m3_h=get_float('flow_m3_h'),
            pressure_pa=get_float('pressure_pa'),
            pump_id=get_int('pump_id'),
            jet_state=get_str('jet_state', 'on'),
            people_count=get_int('people_count'),
            notes=get_str('notes'),
        )

    def get_summary(self) -> dict:
        if not self.measurements:
            return {'n_measurements': 0}

        velocities = [m.velocity_m_s for m in self.measurements if m.velocity_m_s > 0]
        return {
            'n_measurements': len(self.measurements),
            'n_stations': len(set(m.station_id for m in self.measurements)),
            'velocity_avg': sum(velocities) / len(velocities) if velocities else 0,
            'velocity_min': min(velocities) if velocities else 0,
            'velocity_max': max(velocities) if velocities else 0,
            'n_with_people': sum(1 for m in self.measurements if m.people_count > 0),
        }
