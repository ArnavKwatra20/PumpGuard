"""Compare small CPU logistic-regression and random-forest classifiers."""
import argparse
import json
from pathlib import Path
from time import perf_counter
from pumpguard.data.evaluation import evaluate_classification, measure_inference
from pumpguard.data.features import engineer_features
from pumpguard.data.pipeline import read_csv
from pumpguard.data.splitting import input_feature_names, split_dataset
from pumpguard.simulator.generator import SCENARIOS

def _load_sklearn():
    """Import optional native ML tools only when this experiment is invoked."""
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "scikit-learn is installed but its native components could not load in this Windows "
            "environment; check the Application Control policy. The PumpGuard API does not need scikit-learn."
        ) from exc
    return RandomForestClassifier, SimpleImputer, LogisticRegression, make_pipeline, StandardScaler

def main() -> None:
    """Run optional scikit-learn comparisons or the pure-Python fallback."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/raw/pump_telemetry.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/baseline_results.json"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    rows = engineer_features(read_csv(args.input))
    splits, metadata = split_dataset(rows, seed=args.seed)
    feature_names = input_feature_names(rows)
    matrix = lambda part: [[row.get(column) for column in feature_names] for row in splits[part]]
    labels = lambda part: [str(row["scenario_label"]) for row in splits[part]]
    base = {
        "data_kind": "synthetic",
        "target": "scenario_label",
        "interpretation": "Controlled scenario classification only; not future failure prediction.",
        "split_metadata": metadata,
        "feature_names": feature_names,
    }
    try:
        RandomForestClassifier, SimpleImputer, LogisticRegression, make_pipeline, StandardScaler = _load_sklearn()
    except RuntimeError as exc:
        from pumpguard.data.baselines import run_nearest_centroid
        result = run_nearest_centroid(
            matrix("train"), labels("train"), matrix("validation"), labels("validation"),
            matrix("test"), labels("test"), labels=SCENARIOS,
        )
        base.update(result)
        base["backend"] = "pure_python_fallback"
        base["sklearn_unavailable_reason"] = str(exc)
        base["selection_rule"] = "Single fallback model; no model selection on test data."
    else:
        models = {
            "logistic_regression": make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                                  LogisticRegression(max_iter=1000, random_state=args.seed)),
            "random_forest": make_pipeline(SimpleImputer(strategy="median"),
                                           RandomForestClassifier(n_estimators=100, min_samples_leaf=2,
                                                                  random_state=args.seed, n_jobs=1)),
        }
        reports = {}
        for name, model in models.items():
            start = perf_counter()
            model.fit(matrix("train"), labels("train"))
            fit_seconds = perf_counter() - start
            validation_prediction, validation_seconds = measure_inference(model, matrix("validation"))
            model_classes = list(model[-1].classes_)
            validation_scores_raw = model.predict_proba(matrix("validation"))
            validation_scores = [[row[model_classes.index(label)] for label in SCENARIOS] for row in validation_scores_raw]
            reports[name] = {
                "fit_seconds": fit_seconds,
                "validation_inference_seconds": validation_seconds,
                "validation_metrics": evaluate_classification(labels("validation"), validation_prediction, labels=SCENARIOS, y_score=validation_scores),
                "model": model,
            }
        chosen = max(reports, key=lambda name: reports[name]["validation_metrics"]["balanced_accuracy"])
        chosen_estimator = reports[chosen]["model"]
        test_results_by_model = {}
        for name, report in reports.items():
            estimator = report["model"]
            prediction, inference_seconds = measure_inference(estimator, matrix("test"))
            model_classes = list(estimator[-1].classes_)
            test_scores_raw = estimator.predict_proba(matrix("test"))
            test_scores = [[row[model_classes.index(label)] for label in SCENARIOS] for row in test_scores_raw]
            test_results_by_model[name] = {
                "test_inference_seconds": inference_seconds,
                "test_metrics": evaluate_classification(labels("test"), prediction, labels=SCENARIOS, y_score=test_scores),
            }
        inference_seconds = test_results_by_model[chosen]["test_inference_seconds"]
        base.update({
            "backend": "scikit_learn_cpu",
            "selection_rule": "Highest validation balanced accuracy; test data was not used for model selection.",
            "validation": {name: {k: v for k, v in report.items() if k != "model"} for name, report in reports.items()},
            "selected_model": chosen,
            "test_results_by_model": test_results_by_model,
            "test_inference_seconds": inference_seconds,
            "test_metrics": test_results_by_model[chosen]["test_metrics"],
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(base, indent=2), encoding="utf-8")
    validation_summary = base.get("validation_metrics")
    if "validation" in base and base.get("selected_model"):
        validation_summary = base["validation"][base["selected_model"]]["validation_metrics"]
    print(json.dumps({"backend": base["backend"], "model": base.get("model", base.get("selected_model")),
                      "validation_metrics": validation_summary,
                      "test_metrics": base.get("test_metrics"), "output": str(args.output)}, indent=2))

if __name__ == "__main__":
    main()
