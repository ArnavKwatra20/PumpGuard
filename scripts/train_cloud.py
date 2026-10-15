"""Future AMD cloud entry point. Requires a verified ROCm AMD GPU; never falls back to CPU."""
import argparse
from pathlib import Path


def require_amd_gpu(torch_module=None) -> str:
    """Return the device only when PyTorch exposes an AMD ROCm GPU."""
    if torch_module is None:
        try:
            import torch as torch_module
        except (ImportError, OSError) as exc:
            raise RuntimeError("AMD GPU training requires a compatible PyTorch installation in the cloud environment") from exc
    if not getattr(torch_module.version, "hip", None):
        raise RuntimeError("AMD GPU requested, but this PyTorch build does not report ROCm/HIP support")
    if not torch_module.cuda.is_available() or torch_module.cuda.device_count() < 1:
        raise RuntimeError("AMD GPU requested, but no usable GPU device is available; refusing CPU fallback")
    name = torch_module.cuda.get_device_name(0)
    if not any(token in name.lower() for token in ("amd", "radeon")):
        raise RuntimeError(f"AMD GPU requested, but the visible device is not identified as AMD: {name}")
    return "cuda"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--patience", type=int, default=6)
    args = parser.parse_args()
    try:
        device = require_amd_gpu()
    except RuntimeError as exc:
        parser.error(str(exc))
    # Import only after the AMD preflight, so an unavailable GPU fails before any training.
    from train_torch import run
    report = run(args.input, args.artifact, args.seed, args.epochs, args.batch_size,
                 args.learning_rate, args.patience, device=device)
    print(report)


if __name__ == "__main__":
    main()
