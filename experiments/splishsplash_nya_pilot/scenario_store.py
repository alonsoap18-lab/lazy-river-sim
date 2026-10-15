"""Persistent, local-only input scenarios for the experimental 2D pilot."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from experiments.splishsplash_nya_pilot.depth2d_flow import Flow2DInputs


SCENARIO_FILE = Path(__file__).parent / "runtime" / "saved_scenarios.json"
SCHEMA_VERSION = 1
ALLOWED_COUNTS = (16, 20, 24, 28)


def record_from_settings(settings: Flow2DInputs) -> dict:
    """Portable scenario data, without writing to shared server storage."""
    if settings.count not in ALLOWED_COUNTS or settings.moved_pump_index is not None:
        raise ValueError("Solo se pueden guardar escenarios del modo de arrastre.")
    settings.validate()
    return {
        "version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "settings": {
            "count": settings.count,
            "momentum_fraction": settings.momentum_fraction,
            "nozzle_angle_deg": settings.nozzle_angle_deg,
            "eddy_viscosity_m2_s": settings.eddy_viscosity_m2_s,
            "floor_manning_n": settings.floor_manning_n,
            "wall_manning_n": settings.wall_manning_n,
            "site_overrides": [list(item) for item in settings.site_overrides],
        },
    }


def settings_from_record(record: dict) -> Flow2DInputs:
    if not isinstance(record, dict) or record.get("version") != SCHEMA_VERSION:
        raise ValueError("Formato de escenario no reconocido.")
    data = record.get("settings")
    if not isinstance(data, dict):
        raise ValueError("El escenario no contiene parámetros válidos.")
    try:
        count = int(data["count"])
        momentum = float(data["momentum_fraction"])
        angle = float(data["nozzle_angle_deg"])
        mixing = float(data["eddy_viscosity_m2_s"])
        floor_n = float(data.get("floor_manning_n", 0.013))
        wall_n = float(data.get("wall_manning_n", 0.025))
        moves = tuple((int(i), float(s), str(bank)) for i, s, bank in data["site_overrides"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Faltan datos de bombas o parámetros en el escenario.") from exc
    if count not in ALLOWED_COUNTS or not .05 <= momentum <= 1 or not -30 <= angle <= 30 or not .02 <= mixing <= .30:
        raise ValueError("Los parámetros guardados están fuera del rango de esta prueba.")
    settings = Flow2DInputs(count=count, momentum_fraction=momentum,
                            nozzle_angle_deg=angle, eddy_viscosity_m2_s=mixing,
                            floor_manning_n=floor_n, wall_manning_n=wall_n,
                            site_overrides=moves)
    settings.validate()
    return settings


def read_scenarios(path: Path | None = None) -> dict[str, dict]:
    path = SCENARIO_FILE if path is None else path
    if not path.exists():
        return {}
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("No se pudo leer el archivo local de escenarios.") from exc
    if not isinstance(stored, dict):
        raise ValueError("El archivo local de escenarios tiene un formato inválido.")
    for name, record in stored.items():
        if not isinstance(name, str):
            raise ValueError("Hay un nombre de escenario inválido.")
        settings_from_record(record)
    return stored


def save_scenario(name: str, settings: Flow2DInputs,
                  path: Path | None = None) -> None:
    path = SCENARIO_FILE if path is None else path
    name = name.strip()
    if not 1 <= len(name) <= 60 or any(ord(char) < 32 for char in name):
        raise ValueError("Escribe un nombre de 1 a 60 caracteres, sin saltos de línea.")
    record = record_from_settings(settings)
    stored = read_scenarios(path)
    if name in stored:
        raise ValueError("Ya existe un escenario con ese nombre. Elige otro para conservar el anterior.")
    stored[name] = record
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".scenarios-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(stored, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
