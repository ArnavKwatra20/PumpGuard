"""Train/evaluate the optional compact PyTorch model on synthetic telemetry."""
import argparse
import json
from pathlib import Path
from time import perf_counter

from pumpguard.data.evaluation import evaluate_classification
from pumpguard.data.features import engineer_features
from pumpguard.data.pipeline import read_csv
from pumpguard.data.splitting import input_feature_names, split_dataset
from pumpguard.ml.pipeline import SavedClassifier, train_classifier
from pumpguard.simulator.generator import SCENARIOS


def run(input_path: Path, artifact_path: Path, seed: int = 42, epochs: int = 40,
        batch_size: int = 64, learning_rate: float = 1e-3, patience: int = 6,
        device: str = "cpu") -> dict:
    rows = engineer_features(read_csv(input_path))
    splits, split_metadata = split_dataset(rows, seed=seed)
    feature_names = input_feature_names(rows)
    trained = train_classifier(feature_names, splits["train"], splits["validation"],
                               artifact_path=artifact_path, seed=seed, epochs=epochs,
                               batch_size=batch_size, learning_rate=learning_rate,
                               patience=patience, split_metadata=split_metadata, device=device)
    saved = SavedClassifier(artifact_path, device=device)
    test_rows = splits["test"]
    started = perf_counter()
    predictions = saved.predict(test_rows)
    inference_seconds = perf_counter() - started
    scores = saved.predict_proba(test_rows)
    y_test = [str(row["scenario_label"]) for row in test_rows]
    return {
        "data_kind": "synthetic",
        "interpretation": "Controlled synthetic scenario classification only; not real industrial performance or future-failure prediction.",
        "target": "scenario_label", "backend": trained["training_config"]["execution_path"],
        "compute_provider": trained["training_config"]["compute_provider"],
        "device": trained["training_config"]["device"],
        "model_version": saved.model_version,
        "inference_execution_path": saved.compute_info["execution_path"],
        "split_metadata": split_metadata, "feature_names": feature_names,
        "parameter_count": trained["parameter_count"],
        "training_config": trained["training_config"],
        "validation_metrics": trained["validation_metrics"],
        "test_inference_seconds": inference_seconds,
        "test_metrics": evaluate_classification(y_test, predictions, labels=SCENARIOS, y_score=scores),
        "artifact_path": str(artifact_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/raw/pump_telemetry.csv"))
    parser.add_argument("--artifact", type=Path, default=Path("models/pumpguard_mlp.pt"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/torch_results.json"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--patience", type=int, default=6)
    parser.add_argument("--device", choices=("cpu", "auto", "amd-rocm", "cuda"), default="cpu",
                        help="Use CPU, auto-select only a detected AMD ROCm device, or request a device explicitly.")
    args = parser.parse_args()
    try:
        report = run(args.input, args.artifact, args.seed, args.epochs, args.batch_size,
                     args.learning_rate, args.patience, device=args.device)
    except RuntimeError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"backend": report["backend"], "compute_provider": report["compute_provider"],
                      "device": report["device"], "model_version": report["model_version"],
                      "validation_metrics": report["validation_metrics"],
                      "test_metrics": report["test_metrics"], "parameter_count": report["parameter_count"],
                      "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
