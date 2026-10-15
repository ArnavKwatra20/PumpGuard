"""Pump-group holdout splitting and model feature selection."""
from __future__ import annotations
import math
import random
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from pumpguard.data.features import _timestamp

def input_feature_names(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return numeric sensor features while excluding IDs, timestamps, and labels."""
    if not rows:
        return []
    names = []
    for name in rows[0]:
        if name in {"temperature_c", "vibration_mm_s", "sound_db", "rpm"}:
            names.append(name)
            continue
        for sensor in ("temperature_c", "vibration_mm_s", "sound_db", "rpm"):
            if name in {f"{sensor}_delta", f"{sensor}_relative_change"} or name.startswith((f"{sensor}_lag_", f"{sensor}_roll_mean_w", f"{sensor}_roll_std_w")):
                names.append(name)
                break
    return names

def split_dataset(
    rows: Sequence[Mapping[str, Any]],
    *,
    group_column: str = "pump_id",
    seed: int = 42,
    train_fraction: float = 0.6,
    validation_fraction: float = 0.2,
    test_fraction: float = 0.2,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Hold out whole groups in chronological order and sort records within each split.

    Earlier-starting pump histories are allocated to training, then validation,
    then test. Random seed breaks ties between groups with identical start times.
    Whole groups remain together, so their overlapping rolling windows cannot
    cross split boundaries.
    """
    fractions = (train_fraction, validation_fraction, test_fraction)
    if any(f <= 0 for f in fractions) or not math.isclose(sum(fractions), 1.0, abs_tol=1e-8):
        raise ValueError("split fractions must be positive and sum to 1")
    if not rows or any(group_column not in row or "timestamp" not in row for row in rows):
        raise ValueError(f"rows must contain {group_column!r} and 'timestamp'")
    groups = sorted({str(row[group_column]) for row in rows})
    if len(groups) < 3:
        raise ValueError("At least three distinct groups are required for train/validation/test")
    group_times = {
        group: sorted(_timestamp(row["timestamp"]) for row in rows if str(row[group_column]) == group)
        for group in groups
    }
    rng = random.Random(seed)
    groups_by_start: dict[datetime, list[str]] = {}
    for group in groups:
        groups_by_start.setdefault(group_times[group][0], []).append(group)
    chronological_groups: list[str] = []
    for timestamp in sorted(groups_by_start):
        tied = groups_by_start[timestamp]
        rng.shuffle(tied)
        chronological_groups.extend(tied)
    n_train = max(1, int(round(len(groups) * train_fraction)))
    n_validation = max(1, int(round(len(groups) * validation_fraction)))
    if n_train + n_validation >= len(groups):
        n_train, n_validation = len(groups) - 2, 1
    assignments = {
        "train": set(chronological_groups[:n_train]),
        "validation": set(chronological_groups[n_train:n_train + n_validation]),
        "test": set(chronological_groups[n_train + n_validation:]),
    }
    splits: dict[str, list[dict[str, Any]]] = {}
    for name, selected in assignments.items():
        subset = [dict(row) for row in rows if str(row[group_column]) in selected]
        subset.sort(key=lambda row: (str(row[group_column]), _timestamp(row["timestamp"])))
        splits[name] = subset
    metadata = {
        "strategy": "chronological_group_holdout",
        "group_column": group_column,
        "seed": seed,
        "fractions": {"train": train_fraction, "validation": validation_fraction, "test": test_fraction},
        "groups": {
            name: sorted(values, key=lambda group: group_times[group][0])
            for name, values in assignments.items()
        },
        "group_timestamp_ranges": {
            group: {"start": group_times[group][0].isoformat(), "end": group_times[group][-1].isoformat()}
            for group in chronological_groups
        },
        "sample_counts": {name: len(values) for name, values in splits.items()},
        "timestamp_ranges": {
            name: {
                "start": min((_timestamp(row["timestamp"]) for row in values), default=None).isoformat() if values else None,
                "end": max((_timestamp(row["timestamp"]) for row in values), default=None).isoformat() if values else None,
            }
            for name, values in splits.items()
        },
    }
    return splits, metadata
