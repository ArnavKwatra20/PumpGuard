"""Synthetic dataset quality audit helpers."""
from __future__ import annotations
import math
import json
from pathlib import Path
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from pumpguard.data.pipeline import SENSOR_COLUMNS, REQUIRED_COLUMNS

def build_quality_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    split_metadata: Mapping[str, Any] | None = None,
    validation_error: str | None = None,
) -> dict[str, Any]:
    """Summarize completeness, duplicates, ranges, class balance, and splits."""
    warnings: list[str] = []
    sensor_missing = {name: 0 for name in SENSOR_COLUMNS}
    numeric: dict[str, list[float]] = {name: [] for name in SENSOR_COLUMNS}
    labels: Counter[str] = Counter()
    pumps: set[str] = set()
    timestamps: list[datetime] = []
    keys: Counter[tuple[str, str]] = Counter()
    for row in rows:
        pumps.add(str(row.get("pump_id", "")))
        label = row.get("scenario_label")
        if label not in (None, ""):
            labels[str(label)] += 1
        ts = row.get("timestamp")
        try:
            parsed = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            timestamps.append(parsed)
            keys[(str(row.get("pump_id", "")), parsed.isoformat())] += 1
        except (TypeError, ValueError):
            pass
        for name in SENSOR_COLUMNS:
            value = row.get(name)
            if value is None or str(value).strip() == "":
                sensor_missing[name] += 1
        for name in SENSOR_COLUMNS:
            value = row.get(name)
            if value is None or str(value).strip() == "":
                continue
            try:
                parsed_value = float(value)
                if math.isfinite(parsed_value):
                    numeric[name].append(parsed_value)
                else:
                    sensor_missing[name] += 1
            except (TypeError, ValueError):
                sensor_missing[name] += 1
    duplicate_count = sum(count - 1 for count in keys.values() if count > 1)
    if any(sensor_missing.values()):
        warnings.append("One or more sensor values are missing, nonnumeric, or nonfinite.")
    if duplicate_count:
        warnings.append("Duplicate (pump_id, timestamp) records were found.")
    if validation_error:
        warnings.append("Strict pipeline validation failed.")
    if split_metadata:
        ranges = split_metadata.get("timestamp_ranges", {})
        ordered_names = ("train", "validation", "test")
        for earlier, later in zip(ordered_names, ordered_names[1:]):
            end = ranges.get(earlier, {}).get("end")
            start = ranges.get(later, {}).get("start")
            if end and start and end >= start:
                warnings.append(f"{earlier} and {later} split timestamp ranges overlap; strict temporal separation is not achieved.")
    if len(labels) > 1:
        imbalance = max(labels.values()) / min(labels.values())
    elif labels:
        imbalance = 1.0
    else:
        imbalance = None
    valid_times = [x for x in timestamps if x.tzinfo is not None]
    report = {
        "data_kind": "synthetic",
        "synthetic_data_notice": "All observations in this report are synthetic and do not establish real-pump accuracy.",
        "sample_count": len(rows),
        "pump_count": len(pumps - {""}),
        "timestamp_range": {
            "start": min(valid_times).isoformat() if valid_times else None,
            "end": max(valid_times).isoformat() if valid_times else None,
        },
        "scenario_distribution": dict(sorted(labels.items())),
        "missing_values": sensor_missing,
        "duplicate_record_count": duplicate_count,
        "sensor_statistics": {},
        "class_imbalance_ratio_max_to_min": imbalance,
        "split_sample_counts": dict((split_metadata or {}).get("sample_counts", {})),
        "split_metadata": dict(split_metadata or {}),
        "data_quality_warnings": warnings,
        "validation_error": validation_error,
    }
    for name, values in numeric.items():
        report["sensor_statistics"][name] = (
            {"count": len(values), "min": min(values), "max": max(values),
             "mean": sum(values) / len(values)} if values else
            {"count": 0, "min": None, "max": None, "mean": None}
        )
    return report

def report_markdown(report: Mapping[str, Any]) -> str:
    """Format a compact human-readable report."""
    lines = [
        "# Synthetic dataset quality report", "",
        "> Synthetic data only. This report is not evidence of real industrial accuracy.", "",
        f"- Samples: {report['sample_count']}",
        f"- Pumps: {report['pump_count']}",
        f"- Timestamp range: {report['timestamp_range']['start']} to {report['timestamp_range']['end']}",
        f"- Duplicate records: {report['duplicate_record_count']}",
        f"- Maximum class imbalance ratio: {report['class_imbalance_ratio_max_to_min']}",
        "", "## Scenario distribution", "",
    ]
    lines.extend(f"- {name}: {count}" for name, count in report["scenario_distribution"].items())
    lines.extend(["", "## Sensor ranges and means", "", "| Sensor | Count | Min | Max | Mean |", "|---|---:|---:|---:|---:|"])
    for name, stats in report["sensor_statistics"].items():
        lines.append(f"| {name} | {stats['count']} | {stats['min']} | {stats['max']} | {stats['mean']} |")
    lines.extend(["", "## Split sample counts", ""])
    lines.extend(f"- {name}: {count}" for name, count in report["split_sample_counts"].items())
    lines.extend(["", "## Data quality warnings", ""])
    lines.extend(f"- {warning}" for warning in report["data_quality_warnings"])
    if not report["data_quality_warnings"]:
        lines.append("- None.")
    if report.get("validation_error"):
        lines.extend(["", f"Validation error: {report['validation_error']}"])
    return "\n".join(lines) + "\n"


def write_quality_report(report: Mapping[str, Any], json_path: str | Path, markdown_path: str | Path) -> tuple[Path, Path]:
    """Write JSON and Markdown reports, creating parent directories."""
    json_target, markdown_target = Path(json_path), Path(markdown_path)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_target.write_text(report_markdown(report), encoding="utf-8")
    return json_target, markdown_target
