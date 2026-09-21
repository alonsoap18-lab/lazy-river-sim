"""Safety alerts and compliance checks."""
from typing import List, Dict
from models.geometry_model import AlertItem, Station


class SafetyEngine:
    """Evaluates hydraulic parameters against safety criteria."""

    CRITERIA = [
        {
            'parameter': 'Velocidad maxima',
            'limit': 0.80,
            'unit': 'm/s',
            'source': 'CRITERIO DE DISENO PRELIMINAR',
            'type': 'max',
        },
        {
            'parameter': 'Velocidad minima',
            'limit': 0.20,
            'unit': 'm/s',
            'source': 'CRITERIO DE DISENO PRELIMINAR',
            'type': 'min',
        },
        {
            'parameter': 'Profundidad maxima',
            'limit': 1.50,
            'unit': 'm',
            'source': 'CRITERIO DE DISENO PRELIMINAR',
            'type': 'max',
        },
        {
            'parameter': 'Froude maximo',
            'limit': 0.80,
            'unit': '-',
            'source': 'ASTM F2376 / IAAPA',
            'type': 'max',
            'note': 'Fr < 0.8 para lazy river familiar. Fr > 1.0 = flujo supercritico (peligroso).',
        },
    ]

    def __init__(self):
        self.custom_criteria: List[dict] = []

    def add_criterion(self, parameter: str, limit: float, unit: str,
                       source: str, check_type: str = 'max'):
        self.custom_criteria.append({
            'parameter': parameter,
            'limit': limit,
            'unit': unit,
            'source': source,
            'type': check_type,
        })

    def evaluate(self, stations: List[Station],
                  velocity_target: float = None) -> List[AlertItem]:
        alerts = []

        if not stations:
            return alerts

        velocities = [s.velocity_m_s for s in stations]
        v_max = max(velocities)
        v_min = min(velocities)
        froude_numbers = [s.froude_number for s in stations if hasattr(s, 'froude_number')]
        fr_max = max(froude_numbers) if froude_numbers else 0

        for c in self.CRITERIA + self.custom_criteria:
            param = c['parameter']
            limit = c['limit']
            source = c['source']
            ctype = c['type']
            unit = c['unit']

            if 'velocidad' in param.lower() and 'max' in param.lower():
                value = v_max
            elif 'velocidad' in param.lower() and 'min' in param.lower():
                value = v_min
            elif 'profundidad' in param.lower():
                value = stations[0].depth_m if stations else 0
            elif 'froude' in param.lower():
                value = fr_max
            else:
                continue

            if ctype == 'max':
                if value > limit:
                    status = "CRITICAL" if value > limit * 1.2 else "REVIEW"
                else:
                    status = "NORMAL"
            elif ctype == 'min':
                if value < limit:
                    status = "CRITICAL" if value < limit * 0.8 else "REVIEW"
                else:
                    status = "NORMAL"
            else:
                status = "NORMAL"

            alerts.append(AlertItem(
                parameter=param,
                value=value,
                limit=limit,
                source=source,
                status=status,
                unit=unit,
            ))

        return alerts

    def summary(self, alerts: List[AlertItem]) -> dict:
        n_normal = sum(1 for a in alerts if a.status == "NORMAL")
        n_review = sum(1 for a in alerts if a.status == "REVIEW")
        n_critical = sum(1 for a in alerts if a.status == "CRITICAL")

        if n_critical > 0:
            overall = "CRITICAL"
        elif n_review > 0:
            overall = "REVIEW"
        else:
            overall = "NORMAL"

        return {
            'overall': overall,
            'normal': n_normal,
            'review': n_review,
            'critical': n_critical,
            'total': len(alerts),
        }
