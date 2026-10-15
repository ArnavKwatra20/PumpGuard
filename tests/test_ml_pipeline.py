from datetime import datetime, timezone

import pytest

from pumpguard.data.evaluation import evaluate_classification
from pumpguard.data.features import engineer_features
from pumpguard.data.splitting import input_feature_names, split_dataset
from pumpguard.simulator.generator import SCENARIOS
from scripts.generate_dataset import generate_rows
from scripts.train_cloud import require_amd_gpu


class _NoGpuTorch:
    class version:
        hip = None

    class cuda:
        @staticmethod
        def is_available():
            return False

        @staticmethod
        def device_count():
            return 0


def _require_torch_test_runtime():
    try:
        import torch  # noqa: F401
    except (ImportError, OSError) as exc:
        pytest.skip(f"optional PyTorch runtime is unavailable: {exc}")


def test_requested_amd_gpu_fails_clearly_without_rocm():
    with pytest.raises(RuntimeError, match="does not report ROCm/HIP"):
        require_amd_gpu(_NoGpuTorch)


def test_requested_amd_gpu_fails_clearly_when_rocm_has_no_device():
    class RocmWithoutDevice(_NoGpuTorch):
        class version:
            hip = "test-runtime"

    with pytest.raises(RuntimeError, match="no usable GPU device"):
        require_amd_gpu(RocmWithoutDevice)


def test_metric_report_has_expected_dimensions_and_scores():
    labels = ["a", "b", "a", "b"]
    result = evaluate_classification(labels, ["a", "a", "a", "b"], labels=["a", "b"])
    assert result["accuracy"] == 0.75
    assert result["balanced_accuracy"] == 0.75
    assert result["f1_macro"] == pytest.approx((0.8 + 2 / 3) / 2)
    assert result["confusion_matrix"] == [[2, 0], [1, 1]]
    assert set(result["per_class"]) == {"a", "b"}


def test_torch_training_reproducibility_order_and_artifact(tmp_path):
    _require_torch_test_runtime()
    from pumpguard.ml.pipeline import SavedClassifier, train_classifier

    raw = generate_rows(15, 83, 1.0, 3, datetime(2026, 1, 1, tzinfo=timezone.utc))
    rows = engineer_features(raw)
    splits, metadata = split_dataset(rows, seed=11)
    features = input_feature_names(rows)
    assert "scenario_label" not in features
    assert "pump_id" not in features
    assert "timestamp" not in features
    assert "operating_mode" not in features
    first_path, second_path = tmp_path / "one.pt", tmp_path / "two.pt"
    first = train_classifier(features, splits["train"], splits["validation"], artifact_path=first_path,
                             seed=19, epochs=3, batch_size=32, patience=3, split_metadata=metadata)
    second = train_classifier(features, splits["train"], splits["validation"], artifact_path=second_path,
                              seed=19, epochs=3, batch_size=32, patience=3, split_metadata=metadata)
    loaded = SavedClassifier(first_path)
    ordered_rows = splits["test"]
    scores = loaded.predict_proba(ordered_rows)
    predictions = loaded.predict(ordered_rows)
    assert len(scores) == len(ordered_rows)
    assert all(len(row) == len(SCENARIOS) for row in scores)
    assert len(predictions) == len(ordered_rows)
    assert loaded.feature_names == features
    assert loaded.artifact["label_mapping"] == {label: i for i, label in enumerate(SCENARIOS)}
    assert loaded.artifact["split_metadata"] == metadata
    assert first["parameter_count"] > 0
    assert first["training_config"]["best_epoch"] <= first["training_config"]["epochs_trained"] <= 3
    assert first["validation_metrics"] == second["validation_metrics"]
    assert first["training_config"]["best_epoch"] == second["training_config"]["best_epoch"]
    assert predictions == SavedClassifier(second_path).predict(ordered_rows)


def test_prediction_requires_configured_features(tmp_path):
    _require_torch_test_runtime()
    from pumpguard.ml.pipeline import SavedClassifier, train_classifier

    raw = generate_rows(12, 7, 1.0, 3, datetime(2026, 1, 1, tzinfo=timezone.utc))
    rows = engineer_features(raw)
    splits, _ = split_dataset(rows)
    features = input_feature_names(rows)
    path = tmp_path / "model.pt"
    train_classifier(features, splits["train"], splits["validation"], artifact_path=path, epochs=1,
                     batch_size=64, patience=1)
    model = SavedClassifier(path)
    with pytest.raises(ValueError, match="missing configured feature"):
        model.predict([{"scenario_label": "normal"}])
