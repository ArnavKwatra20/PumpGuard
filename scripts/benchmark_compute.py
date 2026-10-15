"""Run identical reproducible classifier training on CPU and visible AMD ROCm, when available."""
from __future__ import annotations

import argparse
import json
import platform
import tempfile
from pathlib import Path

from pumpguard.ml.compute import inspect_compute
from train_torch import run


def benchmark(input_path: Path, *, seed: int = 42, epochs: int = 40, batch_size: int = 64,
              learning_rate: float = 1e-3, patience: int = 6) -> dict:
    runtime = inspect_compute()
    settings = {"seed": seed, "epochs": epochs, "batch_size": batch_size,
                "learning_rate": learning_rate, "patience": patience,
                "input": str(input_path), "data_kind": "synthetic"}
    results = {"cpu": None, "amd_rocm": None}
    with tempfile.TemporaryDirectory(prefix="pumpguard-compute-bench-") as temporary:
        root = Path(temporary)
        cpu = run(input_path, root / "cpu.pt", seed, epochs, batch_size, learning_rate, patience, device="cpu")
        results["cpu"] = _summary(cpu)
        if runtime["provider"] == "amd_rocm":
            gpu = run(input_path, root / "amd-rocm.pt", seed, epochs, batch_size, learning_rate, patience, device="amd-rocm")
            results["amd_rocm"] = _summary(gpu)
    return {
        "benchmark_version": 1,
        "operating_system": platform.platform(),
        "pytorch_runtime": {key: runtime.get(key) for key in ("pytorch_version", "hip_version", "provider", "device", "devices")},
        "settings": settings,
        "results": results,
        "gpu_status": "benchmarked" if results["amd_rocm"] is not None else "not_available",
        "gpu_note": None if results["amd_rocm"] is not None else "No compatible AMD ROCm device was visible to PyTorch; no GPU result was fabricated.",
        "interpretation": "Synthetic scenario classification benchmark only; not evidence of industrial maintenance performance.",
    }


def _summary(report: dict) -> dict:
    return {key: report[key] for key in ("backend", "compute_provider", "device", "model_version",
            "training_config", "validation_metrics", "test_metrics", "test_inference_seconds")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/raw/pump_telemetry.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/compute_benchmark.json"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--patience", type=int, default=6)
    args = parser.parse_args()
    report = benchmark(args.input, seed=args.seed, epochs=args.epochs, batch_size=args.batch_size,
                       learning_rate=args.learning_rate, patience=args.patience)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"gpu_status": report["gpu_status"], "output": str(args.output),
                      "cpu_test_metrics": report["results"]["cpu"]["test_metrics"],
                      "amd_rocm_test_metrics": report["results"]["amd_rocm"]["test_metrics"] if report["results"]["amd_rocm"] else None}, indent=2))


if __name__ == "__main__":
    main()
