"""Runtime compute-provider discovery for CPU and AMD ROCm PyTorch workloads."""
from __future__ import annotations

from typing import Any


def inspect_compute(torch_module: Any | None = None) -> dict[str, Any]:
    """Report only devices PyTorch actually exposes; never infer AMD from the host CPU."""
    if torch_module is None:
        try:
            import torch as torch_module
        except (ImportError, OSError) as exc:
            return {"provider": "cpu", "device": "cpu", "available": True,
                    "accelerator_available": False, "torch_available": False,
                    "pytorch_version": None, "hip_version": None, "devices": [],
                    "error": type(exc).__name__}
    hip_version = getattr(getattr(torch_module, "version", None), "hip", None)
    pytorch_version = getattr(torch_module, "__version__", None)
    devices = []
    accelerator_available = False
    is_amd_rocm = False
    try:
        accelerator_available = bool(torch_module.cuda.is_available())
        if accelerator_available:
            count = int(torch_module.cuda.device_count())
            for index in range(count):
                name = str(torch_module.cuda.get_device_name(index))
                devices.append({"index": index, "name": name})
            is_amd_rocm = bool(hip_version and devices and all(
                any(mark in item["name"].lower() for mark in ("amd", "radeon", "instinct"))
                for item in devices
            ))
    except (RuntimeError, OSError) as exc:
        return {"provider": "cpu", "device": "cpu", "available": True,
                "accelerator_available": False, "torch_available": True,
                "pytorch_version": pytorch_version, "hip_version": hip_version,
                "devices": [], "error": type(exc).__name__}
    return {
        "provider": "amd_rocm" if is_amd_rocm else "cuda" if accelerator_available else "cpu",
        "device": "cuda:0" if accelerator_available else "cpu",
        "available": True,
        "accelerator_available": accelerator_available,
        "torch_available": True,
        "pytorch_version": pytorch_version,
        "hip_version": hip_version,
        "devices": devices,
    }


def resolve_compute(requested: str = "auto", torch_module: Any | None = None) -> dict[str, Any]:
    """Resolve auto/cpu/amd-rocm; retain cuda as an explicit legacy option."""
    if requested not in {"auto", "cpu", "amd-rocm", "cuda"}:
        raise ValueError("compute provider must be auto, cpu, amd-rocm, or cuda")
    status = inspect_compute(torch_module)
    if requested == "cpu":
        return {**status, "provider": "cpu", "device": "cpu", "execution_path": "pytorch_cpu"}
    if requested == "amd-rocm":
        if status["provider"] != "amd_rocm":
            raise RuntimeError("AMD ROCm compute was requested but no usable AMD ROCm device is available")
        return {**status, "execution_path": "pytorch_amd_rocm"}
    if requested == "cuda":
        if not status["accelerator_available"]:
            raise RuntimeError("CUDA-compatible compute was requested but no usable accelerator is available")
        return {**status, "execution_path": "pytorch_amd_rocm" if status["provider"] == "amd_rocm" else "pytorch_cuda"}
    if status["provider"] == "amd_rocm":
        return {**status, "execution_path": "pytorch_amd_rocm"}
    return {**status, "provider": "cpu", "device": "cpu", "execution_path": "pytorch_cpu"}
