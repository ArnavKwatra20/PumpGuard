"""Causal rolling features for chronological pump telemetry."""
from __future__ import annotations
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any
from pumpguard.data.pipeline import SENSOR_COLUMNS

def _timestamp(value: Any) -> datetime:
    """Normalize ISO strings and datetime inputs."""
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))

def feature_column_names(windows: tuple[int, ...] = (3, 5), lags: tuple[int, ...] = (1,)) -> list[str]:
    """List generated numeric model feature names in deterministic order."""
    names = list(SENSOR_COLUMNS)
    for sensor in SENSOR_COLUMNS:
        names.extend((f"{sensor}_delta", f"{sensor}_relative_change"))
        names.extend(f"{sensor}_lag_{lag}" for lag in lags)
        for window in windows:
            names.extend((f"{sensor}_roll_mean_w{window}", f"{sensor}_roll_std_w{window}"))
    return names

def engineer_features(
    rows: Iterable[Mapping[str, Any]],
    *,
    windows: tuple[int, ...] = (3, 5),
    lags: tuple[int, ...] = (1,),
) -> list[dict[str, Any]]:
    """Add causal per-pump rolling statistics, deltas, relative changes, and lags.

    Raw columns remain intact. Warm-up outputs are None until enough prior/current
    observations exist. Rolling standard deviation is population std (ddof=0).
    Input is sorted by pump and timestamp; no future observations are used.
    """
    if not windows or any(not isinstance(w, int) or w < 1 for w in windows):
        raise ValueError("windows must contain positive integers")
    if any(not isinstance(lag, int) or lag < 1 for lag in lags):
        raise ValueError("lags must contain positive integers")
    ordered = sorted((dict(row) for row in rows), key=lambda r: (str(r["pump_id"]), _timestamp(r["timestamp"])))
    state: dict[str, dict[str, deque[float]]] = defaultdict(
        lambda: {sensor: deque(maxlen=max((*windows, *lags, 1))) for sensor in SENSOR_COLUMNS}
    )
    history_count: dict[str, int] = defaultdict(int)
    features: list[dict[str, Any]] = []
    for source in ordered:
        row = dict(source)
        pump = str(row["pump_id"])
        for sensor in SENSOR_COLUMNS:
            value = float(row[sensor])
            values = state[pump][sensor]
            previous = values[-1] if values else None
            row[f"{sensor}_delta"] = value - previous if previous is not None else None
            row[f"{sensor}_relative_change"] = (
                (value - previous) / abs(previous) if previous not in (None, 0.0) else None
            )
            for lag in lags:
                row[f"{sensor}_lag_{lag}"] = values[-lag] if len(values) >= lag else None
            for window in windows:
                if len(values) + 1 >= window:
                    window_values = list(values)[-(window - 1):] + [value] if window > 1 else [value]
                    mean = sum(window_values) / window
                    variance = sum((x - mean) ** 2 for x in window_values) / window
                    row[f"{sensor}_roll_mean_w{window}"] = mean
                    row[f"{sensor}_roll_std_w{window}"] = variance ** 0.5
                else:
                    row[f"{sensor}_roll_mean_w{window}"] = None
                    row[f"{sensor}_roll_std_w{window}"] = None
            values.append(value)
        history_count[pump] += 1
        row["feature_warmup"] = history_count[pump] < max((*windows, *lags, 1))
        features.append(row)
    return features
