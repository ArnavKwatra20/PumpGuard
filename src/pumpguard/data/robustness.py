"""Utilities for reproducible, pump-level synthetic robustness analysis."""
from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Any

from pumpguard.data.evaluation import evaluate_classification
from pumpguard.data.pipeline import SENSOR_COLUMNS


def inject_sensor_dropout(rows: Sequence[dict[str, Any]], feature_names: Sequence[str], *,
                          rate: float, seed: int) -> tuple[list[dict[str, Any]], int]:
    """Mask one sensor channel and its derived features on selected rows.

    Dropout is applied after causal feature computation to represent a sensor
    packet/channel loss. It does not alter labels or create out-of-range values.
    """
    if not 0 <= rate <= 1:
        raise ValueError("dropout rate must be between 0 and 1")
    rng = random.Random(seed)
    output = []
    masked_rows = 0
    for source in rows:
        row = dict(source)
        if rng.random() < rate:
            sensor = rng.choice(SENSOR_COLUMNS)
            for name in feature_names:
                if name == sensor or name.startswith((f"{sensor}_delta", f"{sensor}_relative_change",
                                                      f"{sensor}_lag_", f"{sensor}_roll_mean_",
                                                      f"{sensor}_roll_std_")):
                    row[name] = None
            masked_rows += 1
        output.append(row)
    return output, masked_rows


def choose_uncertainty_threshold(
    y_true: Sequence[str],
    labels: Sequence[str],
    probabilities: Sequence[Sequence[float]],
    *,
    max_validation_error: float = 0.05,
    min_validation_coverage: float = 0.5,
) -> dict[str, Any]:
    """Choose the lowest confidence cutoff meeting validation error/coverage goals.

    This is an empirical reject option, not probability calibration. Thresholds
    must be fit on validation data only and assessed unchanged on holdout data.
    """
    if len(y_true) == 0 or len(y_true) != len(probabilities):
        raise ValueError("validation labels and probability rows must be non-empty and aligned")
    if not 0 <= max_validation_error <= 1 or not 0 < min_validation_coverage <= 1:
        raise ValueError("error and coverage constraints must be valid fractions")
    if any(len(row) != len(labels) for row in probabilities):
        raise ValueError("probability width must match labels")
    confidences = [max(float(value) for value in row) for row in probabilities]
    predictions = [labels[max(range(len(row)), key=row.__getitem__)] for row in probabilities]
    candidates = sorted(set(confidences))
    eligible = []
    for threshold in candidates:
        accepted = [index for index, confidence in enumerate(confidences) if confidence >= threshold]
        coverage = len(accepted) / len(y_true)
        error = (sum(predictions[index] != y_true[index] for index in accepted) / len(accepted)
                 if accepted else 1.0)
        if coverage >= min_validation_coverage and error <= max_validation_error:
            eligible.append((threshold, coverage, error))
    if not eligible:
        return {"threshold": 1.0000001, "validation_coverage": 0.0,
                "validation_error_rate": None, "uncertain_all": True,
                "rule": "No cutoff met validation error and coverage constraints; flag every prediction uncertain."}
    threshold, coverage, error = min(eligible, key=lambda item: item[0])
    return {"threshold": threshold, "validation_coverage": coverage,
            "validation_error_rate": error, "uncertain_all": False,
            "rule": f"Flag max-class score below {threshold:.6f}; cutoff chosen on validation only."}


def apply_uncertainty_reject(labels: Sequence[str], probabilities: Sequence[Sequence[float]],
                              threshold: float) -> list[str]:
    """Return class labels or the explicit ``uncertain`` response below cutoff."""
    if len(labels) != len(probabilities):
        raise ValueError("labels and probability rows must have equal length")
    if any(not row for row in probabilities):
        raise ValueError("probability rows must be non-empty")
    return [label if max(float(value) for value in row) >= threshold else "uncertain"
            for label, row in zip(labels, probabilities)]


def pump_cluster_bootstrap_f1(
    rows: Sequence[dict[str, Any]],
    y_true: Sequence[str],
    y_pred: Sequence[str],
    *,
    labels: Sequence[str],
    seed: int,
    repetitions: int = 1000,
) -> dict[str, Any]:
    """Bootstrap whole pump clusters, preserving within-pump row dependence."""
    if len(rows) != len(y_true) or len(rows) != len(y_pred) or not rows:
        raise ValueError("rows and aligned labels/predictions must be non-empty")
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    groups: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(str(row["pump_id"]), []).append(index)
    pump_ids = sorted(groups)
    rng = random.Random(seed)
    estimates = []
    for _ in range(repetitions):
        sampled = [rng.choice(pump_ids) for _ in pump_ids]
        indices = [index for pump in sampled for index in groups[pump]]
        result = evaluate_classification([y_true[i] for i in indices], [y_pred[i] for i in indices], labels=labels)
        estimates.append(result["f1_macro"])
    estimates.sort()
    low = estimates[max(0, int(0.025 * (repetitions - 1)))]
    high = estimates[min(repetitions - 1, int(0.975 * (repetitions - 1)))]
    return {"method": "pump-cluster percentile bootstrap", "pump_cluster_count": len(pump_ids),
            "repetitions": repetitions, "seed": seed, "macro_f1_95pct_interval": [low, high],
            "small_cluster_warning": len(pump_ids) < 8}
