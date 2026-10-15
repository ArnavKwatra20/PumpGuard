"""Strict raw telemetry CSV validation and serialization."""
from __future__ import annotations
import csv
import math
from datetime import datetime
from pathlib import Path
from collections.abc import Iterable, Mapping
from typing import Any
from pumpguard.models.telemetry import TelemetryReading
from pydantic import ValidationError
from pumpguard.simulator.generator import SCENARIOS

SENSOR_COLUMNS = ("temperature_c", "vibration_mm_s", "sound_db", "rpm")
REQUIRED_COLUMNS = ("timestamp", "pump_id", *SENSOR_COLUMNS, "operating_mode", "scenario_label")
CSV_COLUMNS = list(REQUIRED_COLUMNS)

def _parse_timestamp(value: Any, row_number: int) -> datetime:
    """Parse ISO timestamp and require an explicit timezone."""
    try:
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Row {row_number}: timestamp must be ISO-8601") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"Row {row_number}: timestamp must include a timezone")
    return value

def validate_rows(rows: Iterable[Mapping[str, Any]], *, require_sorted: bool = True) -> list[dict[str, Any]]:
    """Validate required columns, sensor values, labels, ordering, and duplicate keys.

    Sensor values are normalized to finite floats and timestamps to timezone-aware datetimes.
    Within each pump, input order must be chronological by default.
    """
    result: list[dict[str, Any]] = []
    previous: dict[str, datetime] = {}
    seen: set[tuple[str, datetime]] = set()
    for number, original in enumerate(rows, start=2):
        missing_columns = [name for name in REQUIRED_COLUMNS if name not in original]
        if missing_columns:
            raise ValueError(f"Row {number}: missing required columns: {', '.join(missing_columns)}")
        row = dict(original)
        for name in REQUIRED_COLUMNS:
            if row[name] is None or str(row[name]).strip() == "":
                raise ValueError(f"Row {number}: {name} is required and cannot be empty")
        pump_id = str(row["pump_id"]).strip()
        timestamp = _parse_timestamp(row["timestamp"], number)
        key = (pump_id, timestamp)
        if key in seen:
            raise ValueError(f"Row {number}: duplicate record for pump_id={pump_id!r} at {timestamp.isoformat()}")
        if require_sorted and pump_id in previous and timestamp < previous[pump_id]:
            raise ValueError(f"Row {number}: timestamps are not ordered for pump_id={pump_id!r}")
        seen.add(key)
        previous[pump_id] = timestamp
        numeric: dict[str, float] = {}
        for name in SENSOR_COLUMNS:
            try:
                value = float(row[name])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Row {number}: {name} must be numeric") from exc
            if not math.isfinite(value):
                raise ValueError(f"Row {number}: {name} must be finite")
            numeric[name] = value
        label = str(row["scenario_label"]).strip()
        if label not in SCENARIOS:
            raise ValueError(f"Row {number}: invalid scenario_label {label!r}")
        mode = str(row["operating_mode"]).strip()
        try:
            telemetry = TelemetryReading(timestamp=timestamp, pump_id=pump_id, operating_mode=mode, **numeric)
        except (ValidationError, TypeError, ValueError) as exc:
            # Convert schema failures into row-addressable data errors, preserving the cause.
            raise ValueError(f"Row {number}: invalid telemetry: {exc}") from exc
        normalized = telemetry.model_dump(mode="json")
        normalized["timestamp"] = telemetry.timestamp
        normalized["scenario_label"] = label
        for extra_name, extra_value in row.items():
            if extra_name not in REQUIRED_COLUMNS:
                normalized[extra_name] = extra_value
        result.append(normalized)
    if not result:
        raise ValueError("Dataset contains no data rows")
    return result

def read_csv(path: str | Path, *, require_sorted: bool = True) -> list[dict[str, Any]]:
    """Read and validate a Phase 1-compatible labeled CSV."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    with source.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError("CSV is missing a header row")
        absent = [name for name in REQUIRED_COLUMNS if name not in reader.fieldnames]
        if absent:
            raise ValueError(f"CSV missing required columns: {', '.join(absent)}")
        return validate_rows(reader, require_sorted=require_sorted)

def write_csv(rows: Iterable[Mapping[str, Any]], path: str | Path) -> Path:
    """Write validated processed rows using a stable CSV schema."""
    normalized = validate_rows(rows, require_sorted=False)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys(key for row in normalized for key in row))
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in normalized:
            writer.writerow({k: row.get(k, "").isoformat() if isinstance(row.get(k), datetime) else row.get(k, "") for k in columns})
    return destination
