from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from pumpguard.data.evaluation import evaluate_classification
from pumpguard.data.features import engineer_features
from pumpguard.data.robustness import (apply_uncertainty_reject, choose_uncertainty_threshold,
                                       inject_sensor_dropout, pump_cluster_bootstrap_f1)
from pumpguard.data.splitting import input_feature_names, split_dataset
from pumpguard.models.telemetry import TelemetryReading
from pumpguard.simulator.generator import SCENARIOS, SimulatorConditions
from pumpguard.simulator.robustness import generate_condition_rows


def test_robustness_generation_is_reproducible_and_changes_operating_conditions():
    baseline = SimulatorConditions(noise_scale=0, fault_intensity=1)
    shifted = SimulatorConditions(noise_scale=0, baseline_temperature_c=72,
                                  baseline_vibration_mm_s=3.0, operating_rpm=1700,
                                  temperature_drift_c_per_sample=0.1,
                                  vibration_drift_mm_s_per_sample=0.01,
                                  rpm_drift_per_sample=-1)
    kwargs = {"samples_per_scenario": 30, "pump_ids": [f"p{i}" for i in range(6)],
              "seed": 44, "start_time": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    baseline_rows = generate_condition_rows(**kwargs, conditions=baseline)
    repeated = generate_condition_rows(**kwargs, conditions=baseline)
    shifted_rows = generate_condition_rows(**kwargs, conditions=shifted)
    assert baseline_rows == repeated
    assert {row["scenario_label"] for row in baseline_rows} == set(SCENARIOS)
    assert all(row["temperature_c"] != changed["temperature_c"]
               for row, changed in zip(baseline_rows, shifted_rows))
    # Per-pump scenario order is randomized, breaking the fixed block-position shortcut.
    pump_orders = []
    for pump in kwargs["pump_ids"]:
        pump_orders.append(tuple(dict.fromkeys(row["scenario_label"] for row in baseline_rows
                                               if row["pump_id"] == pump)))
    assert len(set(pump_orders)) > 1


def test_robustness_split_and_feature_label_separation():
    rows = engineer_features(generate_condition_rows(
        samples_per_scenario=30, pump_ids=[f"pump-{i}" for i in range(6)], seed=9,
        conditions=SimulatorConditions(),
    ))
    splits, metadata = split_dataset(rows, seed=5)
    group_sets = [set(metadata["groups"][part]) for part in ("train", "validation", "test")]
    assert not (group_sets[0] & group_sets[1] or group_sets[0] & group_sets[2] or group_sets[1] & group_sets[2])
    assert set.union(*group_sets) == {f"pump-{i}" for i in range(6)}
    names = input_feature_names(rows)
    assert "scenario_label" not in names and "pump_id" not in names and "timestamp" not in names
    assert all(row["scenario_label"] not in names for row in rows)


def test_dropout_is_reproducible_and_masks_sensor_feature_family():
    rows = [{"pump_id": f"p{i}", "temperature_c": 60.0, "temperature_c_delta": 1.0,
             "vibration_mm_s": 2.0, "scenario_label": "normal"} for i in range(50)]
    features = ["temperature_c", "temperature_c_delta", "vibration_mm_s"]
    once, count = inject_sensor_dropout(rows, features, rate=0.2, seed=77)
    again, repeated_count = inject_sensor_dropout(rows, features, rate=0.2, seed=77)
    assert once == again and count == repeated_count
    assert 0 < count < len(rows)
    assert all((row["temperature_c"] is None) == (row["temperature_c_delta"] is None) for row in once)
    assert all(row["scenario_label"] == "normal" for row in once)


def test_invalid_sensor_reading_is_rejected():
    with pytest.raises(ValidationError):
        TelemetryReading(temperature_c=300, vibration_mm_s=1, sound_db=60, rpm=1700)


def test_saved_model_accepts_unseen_operating_baselines(tmp_path):
    try:
        import torch  # noqa: F401
    except (ImportError, OSError) as exc:
        pytest.skip(f"optional PyTorch runtime is unavailable: {exc}")
    from pumpguard.ml.pipeline import SavedClassifier, train_classifier

    base = engineer_features(generate_condition_rows(
        samples_per_scenario=12, pump_ids=["base-a", "base-b", "base-c"], seed=21,
        conditions=SimulatorConditions(),
    ))
    splits, _ = split_dataset(base, seed=2)
    names = input_feature_names(base)
    artifact = tmp_path / "shift-check.pt"
    train_classifier(names, splits["train"], splits["validation"], artifact_path=artifact,
                     epochs=2, batch_size=16, patience=2)
    shifted = engineer_features(generate_condition_rows(
        samples_per_scenario=6, pump_ids=["new-a", "new-b", "new-c"], seed=22,
        conditions=SimulatorConditions(baseline_temperature_c=75,
                                       baseline_vibration_mm_s=2.8, operating_rpm=1690),
    ))
    scores = SavedClassifier(artifact).predict_proba(shifted)
    assert len(scores) == len(shifted)
    assert all(len(row) == len(SCENARIOS) for row in scores)
    assert all(sum(row) == pytest.approx(1.0) for row in scores)


def test_binary_average_precision_is_order_invariant_for_tied_scores():
    first = evaluate_classification(["fault", "normal"], ["fault", "normal"],
                                    labels=["normal", "fault"], y_score=[0.5, 0.5])
    second = evaluate_classification(["normal", "fault"], ["normal", "fault"],
                                     labels=["normal", "fault"], y_score=[0.5, 0.5])
    assert first["roc_auc"] == second["roc_auc"] == 0.5
    assert first["pr_auc"] == second["pr_auc"] == 0.5


def test_validation_only_reject_cutoff_and_explicit_uncertain_response():
    threshold = choose_uncertainty_threshold(
        ["normal", "fault", "fault", "normal"], ["normal", "fault"],
        [[0.9, 0.1], [0.2, 0.8], [0.55, 0.45], [0.45, 0.55]],
        max_validation_error=0.0, min_validation_coverage=0.5,
    )
    assert threshold["validation_error_rate"] == 0
    outputs = apply_uncertainty_reject(["normal", "fault"], [[0.9, 0.1], [0.6, 0.4]],
                                       threshold["threshold"])
    assert outputs[0] == "normal"
    assert outputs[1] == "uncertain"


def test_cluster_bootstrap_resamples_pumps_not_rows():
    rows, truth, pred = [], [], []
    for pump in ("p1", "p2", "p3"):
        for label in ("normal", "fault"):
            rows.append({"pump_id": pump})
            truth.append(label)
            pred.append(label)
    first = pump_cluster_bootstrap_f1(rows, truth, pred, labels=["normal", "fault"], seed=3, repetitions=50)
    second = pump_cluster_bootstrap_f1(rows, truth, pred, labels=["normal", "fault"], seed=3, repetitions=50)
    assert first == second
    assert first["pump_cluster_count"] == 3
    assert first["small_cluster_warning"] is True
    assert first["macro_f1_95pct_interval"] == [1.0, 1.0]
