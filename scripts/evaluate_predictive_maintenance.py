"""Evaluate synthetic anomaly/fault tasks and report unsupported predictive labels explicitly."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from pumpguard.data.evaluation import evaluate_classification
from pumpguard.data.features import engineer_features
from pumpguard.data.pipeline import read_csv
from pumpguard.data.splitting import split_dataset
from pumpguard.models.telemetry import TelemetryReading
from pumpguard.services.health_service import assess_reading


def evaluate(input_path: Path, *, seed: int = 42, artifact_path: Path | None = None) -> dict:
    rows = read_csv(input_path)
    splits, split_metadata = split_dataset(rows, seed=seed)
    test = splits["test"]
    anomaly_truth, anomaly_predicted = [], []
    relationships = Counter()
    for row in test:
        allowed = TelemetryReading.model_fields.keys()
        reading = TelemetryReading.model_validate({key: value for key, value in row.items() if key in allowed})
        assessment = assess_reading(reading)
        anomaly_truth.append("anomaly" if row["scenario_label"] != "normal" else "normal")
        anomaly_predicted.append("anomaly" if assessment.status != "normal" else "normal")
        for left_index, left in enumerate(assessment.detected_faults):
            for right in assessment.detected_faults[left_index + 1:]:
                relationships[tuple(sorted((left, right)))] += 1
    anomaly_metrics = evaluate_classification(anomaly_truth, anomaly_predicted, labels=["normal", "anomaly"])

    classifier = {"status": "not_evaluated", "reason": "No trained compatible classifier artifact was supplied."}
    artifact_path = artifact_path or Path("models/pumpguard_mlp.pt")
    if artifact_path.is_file():
        try:
            from pumpguard.ml.pipeline import SavedClassifier
            features = engineer_features(rows)
            feature_splits, _ = split_dataset(features, seed=seed)
            model = SavedClassifier(artifact_path, device="auto")
            predictions = model.predict(feature_splits["test"])
            classifier = {
                "status": "evaluated_synthetic_holdout",
                "model_version": model.model_version,
                "compute_provider": model.compute_info["provider"],
                "device": model.compute_info["device"],
                "execution_path": model.compute_info["execution_path"],
                "metrics": evaluate_classification([str(row["scenario_label"]) for row in feature_splits["test"]], predictions),
            }
        except (ImportError, OSError, RuntimeError, ValueError, KeyError) as exc:
            classifier = {"status": "not_evaluated", "reason": type(exc).__name__}
    return {
        "report_version": 1,
        "data_kind": "synthetic",
        "seed": seed,
        "split_metadata": split_metadata,
        "anomaly_detection": {"task": "normal_vs_threshold-anomaly", "source": "deterministic health rules", "metrics": anomaly_metrics},
        "fault_classification": classifier,
        "degradation_forecasting": {"status": "not_evaluable", "reason": "The dataset has no measured degradation trajectory or future-condition target."},
        "remaining_useful_life": {"status": "not_evaluable", "reason": "No run-to-failure duration or censoring labels exist."},
        "fault_relationships": {"status": "cooccurrence_only", "pairs": [{"faults": list(pair), "count": count} for pair, count in sorted(relationships.items())], "causal_claim": False},
        "root_cause_explanations": {"status": "evidence_referenced", "policy": "Only supplied telemetry, trend, rule assessment, and optional model evidence may be cited; hypotheses are not causal proof."},
        "interpretation": "Synthetic holdout metrics are software evaluation only and do not establish real-world pump performance.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/raw/pump_telemetry.csv"))
    parser.add_argument("--artifact", type=Path, default=Path("models/pumpguard_mlp.pt"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/predictive_maintenance_audit.json"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    result = evaluate(args.input, seed=args.seed, artifact_path=args.artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"data_kind": result["data_kind"], "anomaly_metrics": result["anomaly_detection"]["metrics"],
                      "fault_classification_status": result["fault_classification"]["status"],
                      "degradation_status": result["degradation_forecasting"]["status"],
                      "rul_status": result["remaining_useful_life"]["status"], "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
