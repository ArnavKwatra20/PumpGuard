"""Seedable simulator helpers for controlled condition-shift experiments."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

import numpy as np

from pumpguard.simulator.generator import SCENARIOS, SimulatorConditions, TelemetryGenerator


def generate_condition_rows(
    *,
    samples_per_scenario: int,
    pump_ids: Sequence[str],
    seed: int,
    conditions: SimulatorConditions,
    start_time: datetime | None = None,
) -> list[dict]:
    """Generate balanced records with randomized scenario order independently per pump.

    This specifically avoids the legacy generator shortcut where scenario blocks
    always occur in the same order. All records and conditions remain synthetic.
    """
    if len(pump_ids) < 1 or len(set(pump_ids)) != len(pump_ids):
        raise ValueError("pump_ids must contain unique pump identities")
    if samples_per_scenario < len(pump_ids):
        raise ValueError("samples_per_scenario must be at least the number of pumps")
    if any(not pump or len(pump) > 64 for pump in pump_ids):
        raise ValueError("pump IDs must contain 1 to 64 characters")
    start = start_time or datetime(2026, 1, 1, tzinfo=timezone.utc)
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("start_time must include a timezone")
    interval_seconds = 1.0
    pump_duration = len(SCENARIOS) * (samples_per_scenario + 1) * interval_seconds
    rows: list[dict] = []
    for pump_index, pump_id in enumerate(pump_ids):
        pump_seed = seed + pump_index * 65_537
        order_rng = np.random.default_rng(pump_seed)
        order = [str(name) for name in order_rng.permutation(SCENARIOS)]
        generator = TelemetryGenerator(pump_seed + 17, conditions=conditions)
        sequence_base = start + timedelta(seconds=pump_index * pump_duration)
        for order_index, scenario in enumerate(order):
            count = samples_per_scenario // len(pump_ids) + (pump_index < samples_per_scenario % len(pump_ids))
            segment_start = sequence_base + timedelta(seconds=order_index * (samples_per_scenario + 1))
            for reading, label in generator.generate_sequence(scenario, count, interval_seconds,
                                                               pump_id, segment_start):
                record = reading.model_dump(mode="json")
                record["scenario_label"] = label
                rows.append(record)
    rows.sort(key=lambda row: (row["pump_id"], row["timestamp"]))
    return rows
