"""Compare PyTorch MLP with Phase 2 CPU baselines on identical synthetic splits."""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from train_torch import run as run_torch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/raw/pump_telemetry.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/model_comparison.json"))
    parser.add_argument("--artifact", type=Path, default=Path("models/pumpguard_mlp.pt"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--patience", type=int, default=6)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        baseline_path = Path(temp_dir) / "baselines.json"
        completed = subprocess.run(
            [sys.executable, "scripts/run_baselines.py", "--input", str(args.input),
             "--output", str(baseline_path), "--seed", str(args.seed)],
            check=True, capture_output=True, text=True,
        )
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    torch_report = run_torch(args.input, args.artifact, args.seed, args.epochs,
                             args.batch_size, args.learning_rate, args.patience)
    if baseline["split_metadata"] != torch_report["split_metadata"]:
        parser.error("baseline and PyTorch split metadata differ; comparison is invalid")
    if baseline["feature_names"] != torch_report["feature_names"]:
        parser.error("baseline and PyTorch feature ordering differ; comparison is invalid")
    report = {
        "data_kind": "synthetic",
        "interpretation": "Synthetic scenario classification comparison only; results do not establish real-world performance.",
        "shared_split_metadata": torch_report["split_metadata"],
        "feature_names": torch_report["feature_names"],
        "selection_rule": "Each backend selects using validation balanced accuracy only; test metrics are reported after selection.",
        "models": {
            "cpu_baselines": {
                "backend": baseline["backend"], "selected_model": baseline.get("selected_model", baseline.get("model")),
                "validation": baseline.get("validation", baseline.get("validation_metrics")),
                "test_metrics": baseline.get("test_metrics"),
                "test_metrics_by_model": baseline.get("test_results_by_model"),
                "training_seconds": {name: result.get("fit_seconds") for name, result in baseline.get("validation", {}).items()},
                "validation_inference_seconds": {name: result.get("validation_inference_seconds") for name, result in baseline.get("validation", {}).items()},
                "test_inference_seconds": baseline.get("test_inference_seconds"),
            },
            "pytorch_mlp": {
                "backend": torch_report["backend"], "validation_metrics": torch_report["validation_metrics"],
                "test_metrics": torch_report["test_metrics"],
                "training_seconds": torch_report["training_config"]["train_seconds"],
                "test_inference_seconds": torch_report["test_inference_seconds"],
                "parameter_count": torch_report["parameter_count"],
                "training_config": torch_report["training_config"],
                "artifact_path": torch_report["artifact_path"],
            },
        },
        "baseline_stdout": completed.stdout.strip(),
    }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "torch_validation": torch_report["validation_metrics"],
                      "torch_test": torch_report["test_metrics"], "parameter_count": torch_report["parameter_count"]}, indent=2))


if __name__ == "__main__":
    main()
