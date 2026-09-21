"""Scenario engine for Lazy River analysis."""
from typing import List, Dict, Optional
from models.geometry_model import Scenario


class ScenarioEngine:
    """Manages and runs operating scenarios."""

    DEFAULT_SCENARIOS = [
        Scenario("S0", "Sin usuarios", "Sin personas en el canal", 0),
        Scenario("S1", "Operacion normal", "Operacion estandar", 20),
        Scenario("S2", "25 personas", "Ocupacion baja", 25),
        Scenario("S3", "50 personas", "Ocupacion media", 50),
        Scenario("S4", "100 personas", "Ocupacion alta", 100),
        Scenario("S5", "Maxima ocupacion", "Capacidad maxima", 150),
        Scenario("S6", "Jet fuera de servicio", "Un jet desactivado", 20),
        Scenario("S7", "Bomba fuera de servicio", "Una bomba desactivada", 20),
        Scenario("S8", "Mantenimiento", "Operacion reducida", 0),
        Scenario("S9", "Emergencia", "Condiciones de emergencia", 0),
    ]

    def __init__(self):
        self.scenarios: List[Scenario] = list(self.DEFAULT_SCENARIOS)
        self.results: Dict[str, dict] = {}

    def add_scenario(self, scenario: Scenario):
        self.scenarios.append(scenario)

    def get_scenario(self, scenario_id: str) -> Optional[Scenario]:
        for s in self.scenarios:
            if s.scenario_id == scenario_id:
                return s
        return None

    def get_all_ids(self) -> List[str]:
        return [s.scenario_id for s in self.scenarios]

    def get_all_names(self) -> List[str]:
        return [f"{s.scenario_id}: {s.name}" for s in self.scenarios]

    def store_result(self, scenario_id: str, result: dict):
        self.results[scenario_id] = result

    def get_result(self, scenario_id: str) -> Optional[dict]:
        return self.results.get(scenario_id)

    def compare_results(self) -> List[dict]:
        comparison = []
        for sid, r in self.results.items():
            s = self.get_scenario(sid)
            comparison.append({
                'scenario_id': sid,
                'name': s.name if s else sid,
                'people_count': s.people_count if s else 0,
                'velocity_avg': r.get('velocity_avg', 0),
                'lap_time': r.get('lap_time', 0),
                'total_flow': r.get('total_flow', 0),
                'tdh': r.get('tdh', 0),
                'power': r.get('power', 0),
            })
        return comparison
