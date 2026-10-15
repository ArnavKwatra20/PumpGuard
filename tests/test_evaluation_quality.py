from pumpguard.data.evaluation import evaluate_classification
from pumpguard.data.quality import build_quality_report, report_markdown, write_quality_report

def test_metrics_are_robust_when_classes_are_missing():
    result = evaluate_classification(["normal", "normal", "warning"], ["normal", "warning", "warning"],
                                     labels=["normal", "warning", "critical"])
    assert 0 <= result["accuracy"] <= 1
    assert result["per_class"]["critical"]["support"] == 0
    assert len(result["confusion_matrix"]) == 3
    assert result["roc_auc"] is None
    assert "not supplied" in result["ranking_metric_note"]

def test_quality_report_is_synthetic_and_lists_gaps_duplicates_and_stats():
    rows = [
        {"timestamp": "2026-01-01T00:00:00+00:00", "pump_id": "p1", "temperature_c": 60,
         "vibration_mm_s": 1, "sound_db": 50, "rpm": 1700, "scenario_label": "normal", "operating_mode": "steady"},
        {"timestamp": "2026-01-01T00:00:00+00:00", "pump_id": "p1", "temperature_c": "",
         "vibration_mm_s": 2, "sound_db": 55, "rpm": 1710, "scenario_label": "normal", "operating_mode": "steady"},
    ]
    report = build_quality_report(rows, validation_error="duplicate")
    assert report["data_kind"] == "synthetic"
    assert report["sample_count"] == 2
    assert report["missing_values"]["temperature_c"] == 1
    assert report["duplicate_record_count"] == 1
    assert report["sensor_statistics"]["temperature_c"]["mean"] == 60
    assert "Synthetic dataset quality report" in report_markdown(report)


def test_ranking_metrics_when_binary_scores_are_valid():
    result = evaluate_classification(["a", "b", "a", "b"], ["a", "b", "b", "b"], labels=["a", "b"], y_score=[0.1, 0.8, 0.4, 0.9])
    assert result["roc_auc"] == 1.0
    assert 0.0 <= result["pr_auc"] <= 1.0


def test_quality_report_writer_creates_json_and_markdown(tmp_path):
    report = build_quality_report([])
    json_path, markdown_path = write_quality_report(report, tmp_path / "a" / "report.json", tmp_path / "b" / "report.md")
    assert json_path.is_file() and markdown_path.is_file()
    assert "synthetic" in json_path.read_text(encoding="utf-8")
    assert "Synthetic dataset quality report" in markdown_path.read_text(encoding="utf-8")


def test_quality_report_warns_when_split_times_overlap():
    report = build_quality_report([], split_metadata={"timestamp_ranges": {"train": {"end": "2026-01-02"}, "validation": {"start": "2026-01-01"}}})
    assert any("overlap" in warning for warning in report["data_quality_warnings"])


def test_pure_python_baseline_runs_on_small_separated_classes():
    from pumpguard.data.baselines import run_nearest_centroid
    result = run_nearest_centroid([[0.0], [0.2], [9.8], [10.0]], ["a", "a", "b", "b"], [[0.1], [9.9]], ["a", "b"], [[0.15], [9.85]], ["a", "b"], labels=["a", "b"])
    assert result["test_metrics"]["accuracy"] == 1.0
    assert result["preprocessing_fit_scope"] == "training split only"
