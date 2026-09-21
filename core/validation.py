"""Validation: model vs field data."""
import numpy as np
from typing import List, Dict, Tuple, Optional
from models.geometry_model import FieldMeasurement, Station


class ValidationEngine:
    """Compares model output with field measurements."""

    def __init__(self):
        self.field_data: List[FieldMeasurement] = []

    def load_field_data(self, measurements: List[FieldMeasurement]):
        self.field_data = measurements

    def clear(self):
        self.field_data = []

    def compare_at_stations(self, model_stations: List[Station],
                             tolerance_chainage_m: float = 2.0) -> List[dict]:
        comparisons = []

        for fm in self.field_data:
            closest = min(model_stations,
                          key=lambda s: abs(s.chainage_m - fm.chainage_m))

            if abs(closest.chainage_m - fm.chainage_m) > tolerance_chainage_m:
                continue

            error_abs = abs(closest.velocity_m_s - fm.velocity_m_s)
            error_pct = (error_abs / fm.velocity_m_s * 100) if fm.velocity_m_s > 0 else 0

            comparisons.append({
                'station_id': closest.station_id,
                'chainage_m': closest.chainage_m,
                'model_velocity': closest.velocity_m_s,
                'field_velocity': fm.velocity_m_s,
                'error_abs': error_abs,
                'error_pct': error_pct,
                'model_depth': closest.depth_m,
                'field_depth': fm.depth_m,
                'temperature_c': fm.temperature_c,
                'people_count': fm.people_count,
            })

        return comparisons

    def compute_metrics(self, comparisons: List[dict]) -> dict:
        if not comparisons:
            return {'status': 'NO_DATA'}

        model_v = np.array([c['model_velocity'] for c in comparisons])
        field_v = np.array([c['field_velocity'] for c in comparisons])

        errors = model_v - field_v
        abs_errors = np.abs(errors)

        rmse = np.sqrt(np.mean(errors ** 2))
        mae = np.mean(abs_errors)
        bias = np.mean(errors)
        mape = np.mean(abs_errors / field_v * 100) if np.all(field_v > 0) else 0
        max_error = np.max(abs_errors)

        r_squared = 0.0
        if len(field_v) > 1:
            ss_res = np.sum(errors ** 2)
            ss_tot = np.sum((field_v - np.mean(field_v)) ** 2)
            r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        return {
            'n_points': len(comparisons),
            'rmse': rmse,
            'mae': mae,
            'bias': bias,
            'mape': mape,
            'max_error': max_error,
            'r_squared': r_squared,
            'model_mean': np.mean(model_v),
            'field_mean': np.mean(field_v),
        }

    def calibration_suggestions(self, comparisons: List[dict]) -> List[str]:
        suggestions = []
        metrics = self.compute_metrics(comparisons)

        if metrics.get('status') == 'NO_DATA':
            return ["No hay datos de campo para comparar"]

        if abs(metrics['bias']) > 0.05:
            if metrics['bias'] > 0:
                suggestions.append(
                    f"Modelo sobreestima velocidad (+{metrics['bias']:.3f} m/s). "
                    "Considere aumentar Manning n o reducir potencia de jets."
                )
            else:
                suggestions.append(
                    f"Modelo subestima velocidad ({metrics['bias']:.3f} m/s). "
                    "Considere reducir Manning n o aumentar potencia de jets."
                )

        if metrics['mape'] > 15:
            suggestions.append(
                f"Error porcentual medio alto ({metrics['mape']:.1f}%). "
                "Considere calibrar coeficientes de pérdida en curvas."
            )

        if metrics['r_squared'] < 0.7:
            suggestions.append(
                f"R² bajo ({metrics['r_squared']:.2f}). "
                "El modelo no captura bien la variación espacial. "
                "Revise el ancho local y las pérdidas menores."
            )

        return suggestions

    def auto_calibrate(self, field_measurements: List[FieldMeasurement],
                       model_stations, compute_func, param_ranges: dict = None) -> dict:
        """Automatic calibration using field measurements.

        Finds optimal manning_n and jet_cd that minimize RMSE between
        model and field velocities.

        Args:
            field_measurements: list of FieldMeasurement objects
            model_stations: model station data
            compute_func: function(params) -> list of model velocities at field stations
            param_ranges: dict of parameter ranges to search

        Returns:
            dict with calibrated parameters and metrics
        """
        from scipy.optimize import minimize

        if not field_measurements:
            return {"status": "NO_DATA", "message": "No field measurements provided"}

        if param_ranges is None:
            param_ranges = {
                "manning_n": (0.010, 0.025),
                "jet_cd": (0.50, 0.85),
            }

        field_v = np.array([fm.velocity_m_s for fm in field_measurements])

        def objective(params):
            manning_n, jet_cd = params
            try:
                model_v = compute_func(manning_n=manning_n, jet_cd=jet_cd)
                if len(model_v) != len(field_v):
                    return 1e6
                rmse = np.sqrt(np.mean((model_v - field_v) ** 2))
                return rmse
            except:
                return 1e6

        # Initial guess
        x0 = [0.015, 0.65]

        # Bounds
        bounds = [
            param_ranges.get("manning_n", (0.010, 0.025)),
            param_ranges.get("jet_cd", (0.50, 0.85)),
        ]

        # Optimize
        result = minimize(objective, x0, bounds=bounds, method='L-BFGS-B')

        if result.success:
            calibrated_n, calibrated_cd = result.x

            # Compute final metrics
            model_v = compute_func(manning_n=calibrated_n, jet_cd=calibrated_cd)
            comparisons = []
            for i, fm in enumerate(field_measurements):
                if i < len(model_v):
                    comparisons.append({
                        'model_velocity': model_v[i],
                        'field_velocity': fm.velocity_m_s,
                        'error_abs': abs(model_v[i] - fm.velocity_m_s),
                        'error_pct': abs(model_v[i] - fm.velocity_m_s) / fm.velocity_m_s * 100,
                    })

            metrics = self.compute_metrics(comparisons)

            return {
                "status": "SUCCESS",
                "calibrated_manning_n": float(calibrated_n),
                "calibrated_jet_cd": float(calibrated_cd),
                "rmse": float(result.fun),
                "metrics": metrics,
                "n_measurements": len(field_measurements),
            }
        else:
            return {
                "status": "FAILED",
                "message": f"Calibration failed: {result.message}",
            }
