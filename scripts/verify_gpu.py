"""Report actual PyTorch AMD ROCm compute availability; never installs drivers."""
import json
import platform

from pumpguard.ml.compute import inspect_compute


def main() -> None:
    report = {"operating_system": platform.platform(), **inspect_compute()}
    report["intended_amd_gpu_accessible"] = report["provider"] == "amd_rocm"
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
