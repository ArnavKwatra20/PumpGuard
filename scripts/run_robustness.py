"""Train fixed CPU classifiers and assess synthetic operating-condition shifts."""
from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from time import perf_counter
from typing import Any

from pumpguard.data.evaluation import evaluate_classification
from pumpguard.data.features import engineer_features
from pumpguard.data.pipeline import validate_rows
from pumpguard.data.robustness import (apply_uncertainty_reject, choose_uncertainty_threshold, inject_sensor_dropout,
                                       pump_cluster_bootstrap_f1)
from pumpguard.data.splitting import input_feature_names, split_dataset
from pumpguard.ml.pipeline import SavedClassifier, train_classifier
from pumpguard.simulator.generator import SCENARIOS, SimulatorConditions
from pumpguard.simulator.robustness import generate_condition_rows


def _sklearn_components():
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except (ImportError, OSError) as exc:
        raise RuntimeError("Install the optional scikit-learn extra to run robustness comparisons") from exc
    return RandomForestClassifier, SimpleImputer, LogisticRegression, make_pipeline, StandardScaler


def _score_model(model: Any, rows: list[dict], feature_names: list[str], *, kind: str) -> tuple[list[str], list[list[float]], float]:
    started = perf_counter()
    if kind == "torch":
        scores = model.predict_proba(rows)
    else:
        matrix = [[row.get(feature) for feature in feature_names] for row in rows]
        raw = model.predict_proba(matrix)
        classes = list(model[-1].classes_)
        scores = [[float(row[classes.index(label)]) for label in SCENARIOS] for row in raw]
    elapsed = perf_counter() - started
    predictions = [SCENARIOS[max(range(len(row)), key=row.__getitem__)] for row in scores]
    return predictions, scores, elapsed


def _confidence_report(rows, y_true, predictions, scores, threshold):
    confidence = [max(float(value) for value in score) for score in scores]
    ordered = sorted(confidence)
    high_confidence_errors = [
        {"pump_id": str(row["pump_id"]), "timestamp": str(row["timestamp"]),
         "true_label": truth, "predicted_label": prediction, "max_class_score": conf}
        for row, truth, prediction, conf in zip(rows, y_true, predictions, confidence)
        if prediction != truth and conf >= 0.9
    ]
    decisions = apply_uncertainty_reject(predictions, scores, threshold["threshold"])
    accepted = [index for index, decision in enumerate(decisions) if decision != "uncertain"]
    return {
        "max_class_score_quantiles": {
            "p10": ordered[int(0.10 * (len(ordered) - 1))],
            "p50": ordered[int(0.50 * (len(ordered) - 1))],
            "p90": ordered[int(0.90 * (len(ordered) - 1))],
        },
        "high_confidence_error_count_at_0_90": len(high_confidence_errors),
        "high_confidence_errors_examples": high_confidence_errors[:20],
        "validation_selected_reject_rule": threshold,
        "uncertain_prediction_count": len(rows) - len(accepted),
        "uncertain_prediction_rate": (len(rows) - len(accepted)) / len(rows),
        "accepted_coverage": len(accepted) / len(rows),
        "accepted_accuracy": (sum(predictions[i] == y_true[i] for i in accepted) / len(accepted)
                              if accepted else None),
        "score_interpretation": "Maximum class score is not a calibrated probability of equipment failure.",
    }


def _error_pairs(metrics: dict) -> list[dict]:
    labels = metrics["labels"]
    pairs = []
    matrix = metrics["confusion_matrix"]
    for actual_index, row in enumerate(matrix):
        for predicted_index, count in enumerate(row):
            if actual_index != predicted_index and count:
                pairs.append({"true": labels[actual_index], "predicted": labels[predicted_index], "count": count})
    return sorted(pairs, key=lambda item: (-item["count"], item["true"], item["predicted"]))


def _markdown(report: dict) -> str:
    lines = [
        "# PumpGuard Phase 3B — Synthetic Robustness Results", "",
        f"Run seed: {report['seed']}. Training used {report['split_metadata']['sample_counts']['train']} rows; "
        f"validation {report['split_metadata']['sample_counts']['validation']}; standard holdout "
        f"{report['split_metadata']['sample_counts']['test']}. Whole pump groups were kept disjoint.", "",
        "All generated records and condition shifts are synthetic. These results are software robustness checks, "
        "not real-world validation or predictive-maintenance evidence.", "",
        "## Results", "",
        "| Evaluation condition | Model | Accuracy | Balanced accuracy | Macro precision | Macro recall | Macro F1 | F1 95% pump-bootstrap interval | CPU train s | Mean batched inference ms/row | Serialized model bytes |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for condition_name, condition in report["conditions"].items():
        for model_name, outcome in condition["models"].items():
            metrics = outcome["metrics"]
            interval = outcome["pump_cluster_bootstrap"]["macro_f1_95pct_interval"]
            lines.append(f"| {condition_name} | {model_name} | {metrics['accuracy']:.3f} | "
                         f"{metrics['balanced_accuracy']:.3f} | {metrics['precision_macro']:.3f} | "
                         f"{metrics['recall_macro']:.3f} | {metrics['f1_macro']:.3f} | "
                         f"[{interval[0]:.3f}, {interval[1]:.3f}] | "
                         f"{outcome['training_seconds']:.4f} | "
                         f"{outcome['mean_inference_ms_per_row']:.4f} | {outcome['model_size_bytes']} |")
    lines += ["", "## Observed failure modes", ""]
    for name, condition in report["conditions"].items():
        for model_name, outcome in condition["models"].items():
            pairs = outcome["most_common_confusions"]
            if pairs:
                rendered = ", ".join(f"{pair['true']} → {pair['predicted']} ({pair['count']})" for pair in pairs[:3])
                lines.append(f"- {name}, {model_name}: {rendered}.")
    lines += ["",
              "Across this simulator, bearing-wear and cavitation signatures both raise vibration and sound, so those classes are repeatedly confused. With weaker faults, several models confuse fault classes with normal because the simulated offsets approach the normal sensor distribution. Under the shifted temperature/vibration/RPM baseline, Logistic Regression and the MLP collapse toward cavitation while the Random Forest remains stronger on this particular generated configuration. These are observations consistent with the hand-authored signal formulas, not a causal diagnosis of real equipment.", ""]
    shifted = report["conditions"].get("unseen_pump_configuration_and_drift", {}).get("models", {})
    if shifted:
        details = []
        for model_name, outcome in shifted.items():
            confidence = outcome["confidence"]
            details.append(f"{model_name}: uncertain {confidence['uncertain_prediction_count']}/{report['conditions']['unseen_pump_configuration_and_drift']['sample_count']}, "
                           f"high-confidence errors {confidence['high_confidence_error_count_at_0_90']}")
        lines += ["Validation-selected score cutoffs did not detect this shift reliably (" + "; ".join(details) + ")."]
    lines += ["", "## Confidence and limitations", "",
              "Validation-only reject cutoffs aim for at most 5% empirical error while retaining at least 50% "
              "validation coverage. The same cutoff is applied to every holdout condition. It is an empirical "
              "uncertain-prediction flag, not calibrated confidence or a failure probability. High-confidence errors "
              "and coverage are included in the JSON report.", "",
              "Intervals resample complete pump groups, not individual sensor rows. Each evaluation condition has "
              "four held-out pump groups, so the bootstrap intervals are coarse and flagged as small-cluster estimates. "
              "Simulator patterns, fixed schema, chosen condition ranges, and small pump counts do not establish "
              "generalization to industrial equipment. Rule-based health assessment remains independent of scenario classification.", "",
              "The report does not select a model or tune a threshold from final holdout metrics. Logistic Regression "
              "and Random Forest use fixed Phase 2 settings; the MLP checkpoint and each reject threshold use validation only.", ""]
    return "\n".join(lines)


def run_experiment(*, seed: int, samples_per_scenario: int, epochs: int,
                   artifact_path: Path, repetitions: int = 1000) -> dict:
    if samples_per_scenario < 20:
        raise ValueError("samples_per_scenario must be at least 20 for the configured 20 pump groups")
    RandomForestClassifier, SimpleImputer, LogisticRegression, make_pipeline, StandardScaler = _sklearn_components()
    pump_ids = [f"base-pump-{index:02d}" for index in range(1, 21)]
    base_conditions = SimulatorConditions()
    base_raw = generate_condition_rows(samples_per_scenario=samples_per_scenario, pump_ids=pump_ids,
                                       seed=seed, conditions=base_conditions)
    base_rows = engineer_features(validate_rows(base_raw))
    splits, split_metadata = split_dataset(base_rows, seed=seed)
    features = input_feature_names(base_rows)
    if set.union(*(set(split_metadata["groups"][part]) for part in ("train", "validation", "test"))) != set(pump_ids):
        raise RuntimeError("pump split does not account for every generated group")
    train_rows, validation_rows = splits["train"], splits["validation"]
    y_train = [str(row["scenario_label"]) for row in train_rows]
    y_validation = [str(row["scenario_label"]) for row in validation_rows]
    x_train = [[row.get(name) for name in features] for row in train_rows]
    x_validation = [[row.get(name) for name in features] for row in validation_rows]
    sklearn_models = {
        "logistic_regression": make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                             LogisticRegression(max_iter=1000, random_state=seed)),
        "random_forest": make_pipeline(SimpleImputer(strategy="median"),
                                       RandomForestClassifier(n_estimators=100, min_samples_leaf=2,
                                                              random_state=seed, n_jobs=1)),
    }
    model_reports = {}
    for name, model in sklearn_models.items():
        started = perf_counter()
        model.fit(x_train, y_train)
        fit_seconds = perf_counter() - started
        validation_predictions, validation_scores, validation_elapsed = _score_model(
            model, validation_rows, features, kind="sklearn")
        validation_metrics = evaluate_classification(y_validation, validation_predictions,
                                                      labels=SCENARIOS, y_score=validation_scores)
        threshold = choose_uncertainty_threshold(y_validation, SCENARIOS, validation_scores)
        model_reports[name] = {"model": model, "training_seconds": fit_seconds,
                               "validation_metrics": validation_metrics, "validation_scores": validation_scores,
                               "threshold": threshold, "validation_inference_seconds": validation_elapsed,
                               "model_size_bytes": len(pickle.dumps(model))}

    mlp_result = train_classifier(features, train_rows, validation_rows, artifact_path=artifact_path,
                                  seed=seed, epochs=epochs, batch_size=64, learning_rate=1e-3,
                                  patience=6, split_metadata=split_metadata)
    mlp = SavedClassifier(artifact_path)
    mlp_val_scores = mlp.predict_proba(validation_rows)
    mlp_threshold = choose_uncertainty_threshold(y_validation, SCENARIOS, mlp_val_scores)
    model_reports["pytorch_mlp"] = {"model": mlp, "kind": "torch",
                                   "training_seconds": mlp_result["training_config"]["train_seconds"],
                                   "validation_metrics": mlp_result["validation_metrics"],
                                   "validation_scores": mlp_val_scores, "threshold": mlp_threshold,
                                   "validation_inference_seconds": None,
                                   "model_size_bytes": artifact_path.stat().st_size,
                                   "parameter_count": mlp_result["parameter_count"]}

    conditions = {
        "in_distribution": (base_conditions, None),
        "unseen_pump_configuration_and_drift": (
            SimulatorConditions(baseline_temperature_c=76, baseline_vibration_mm_s=2.8,
                                operating_rpm=1680, temperature_drift_c_per_sample=0.025,
                                vibration_drift_mm_s_per_sample=0.008, rpm_drift_per_sample=-1.5), None),
        "increased_sensor_noise": (SimulatorConditions(noise_scale=2.0), None),
        "weaker_fault_signatures": (SimulatorConditions(fault_intensity=0.55), None),
        "sensor_dropout_5pct": (base_conditions, 0.05),
    }
    condition_results = {}
    holdout_pumps = [f"shift-{index:02d}" for index in range(1, 5)]
    standard_test = splits["test"]
    for condition_index, (condition_name, (condition_config, dropout_rate)) in enumerate(conditions.items()):
        if condition_name == "in_distribution":
            test_rows = standard_test
        else:
            raw = generate_condition_rows(samples_per_scenario=80, pump_ids=holdout_pumps,
                                          seed=seed + 10_000 + condition_index,
                                          conditions=condition_config)
            test_rows = engineer_features(validate_rows(raw))
        masked_count = 0
        if dropout_rate is not None:
            test_rows, masked_count = inject_sensor_dropout(test_rows, features, rate=dropout_rate,
                                                             seed=seed + condition_index)
        y_test = [str(row["scenario_label"]) for row in test_rows]
        outcomes = {}
        for model_name, model_report in model_reports.items():
            kind = model_report.get("kind", "sklearn")
            predictions, scores, elapsed = _score_model(model_report["model"], test_rows, features, kind=kind)
            metrics = evaluate_classification(y_test, predictions, labels=SCENARIOS, y_score=scores)
            outcomes[model_name] = {
                "metrics": metrics,
                "training_seconds": model_report["training_seconds"],
                "inference_seconds": elapsed,
                "mean_inference_ms_per_row": elapsed / len(test_rows) * 1000,
                "model_size_bytes": model_report["model_size_bytes"],
                "parameter_count": model_report.get("parameter_count"),
                "pump_cluster_bootstrap": pump_cluster_bootstrap_f1(
                    test_rows, y_test, predictions, labels=SCENARIOS,
                    seed=seed + 20_000 + condition_index, repetitions=repetitions),
                "most_common_confusions": _error_pairs(metrics)[:10],
                "confidence": _confidence_report(test_rows, y_test, predictions, scores,
                                                  model_report["threshold"]),
            }
        condition_results[condition_name] = {
            "data_kind": "synthetic", "conditions": condition_config.__dict__,
            "pump_ids": sorted({str(row["pump_id"]) for row in test_rows}),
            "sample_count": len(test_rows), "masked_rows": masked_count,
            "models": outcomes,
        }
    return {
        "experiment": "pumpguard_phase3b_synthetic_distribution_shift",
        "data_kind": "synthetic", "seed": seed,
        "limitations": [
            "All observations are synthetic simulator output, not field validation.",
            "Scenario classification is not future-failure prediction.",
            "Each evaluation condition uses four pump clusters; bootstrap intervals are coarse.",
            "Confidence scores are not calibrated failure probabilities.",
            "Rule-based anomaly detection and health assessment are not changed by this experiment.",
        ],
        "train_conditions": base_conditions.__dict__, "split_metadata": split_metadata,
        "feature_names": features, "label_order": list(SCENARIOS),
        "model_selection": "Fixed LR/RF settings; MLP selected by validation balanced accuracy/validation loss only. Final holdout scores do not select models.",
        "uncertainty_rule": "Per-model max-score reject threshold is chosen on validation for <=5% empirical accepted error and >=50% coverage; unchanged on holdout.",
        "conditions": condition_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", type=Path, default=Path("data/reports/phase3b_robustness.json"))
    parser.add_argument("--output-markdown", type=Path, default=Path("docs/phase3b-results.md"))
    parser.add_argument("--artifact", type=Path, default=Path("models/phase3b_mlp.pt"))
    parser.add_argument("--seed", type=int, default=2027)
    parser.add_argument("--samples-per-scenario", type=int, default=400)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--bootstrap-repetitions", type=int, default=1000)
    args = parser.parse_args()
    try:
        report = run_experiment(seed=args.seed, samples_per_scenario=args.samples_per_scenario,
                                epochs=args.epochs, artifact_path=args.artifact,
                                repetitions=args.bootstrap_repetitions)
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.output_markdown.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(args.output_json), "markdown": str(args.output_markdown),
                      "conditions": list(report["conditions"]), "test_group_count": len(report["split_metadata"]["groups"]["test"])}, indent=2))


if __name__ == "__main__":
    main()
