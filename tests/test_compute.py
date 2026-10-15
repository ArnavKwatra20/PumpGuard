import pytest
from datetime import datetime, timedelta, timezone

from pumpguard.ml.compute import inspect_compute, resolve_compute


class CpuTorch:
    __version__ = "test-cpu"

    class version:
        hip = None

    class cuda:
        @staticmethod
        def is_available():
            return False

        @staticmethod
        def device_count():
            return 0


class AmdRocmTorch(CpuTorch):
    class version:
        hip = "test-hip"

    class cuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 1

        @staticmethod
        def get_device_name(index):
            return "AMD Radeon Test Device"


def test_cpu_and_amd_provider_selection_is_runtime_verified():
    assert resolve_compute("auto", CpuTorch)["execution_path"] == "pytorch_cpu"
    amd = resolve_compute("auto", AmdRocmTorch)
    assert amd["provider"] == "amd_rocm"
    assert amd["device"] == "cuda:0"
    assert amd["execution_path"] == "pytorch_amd_rocm"


def test_amd_rocm_request_never_falls_back_to_cpu():
    with pytest.raises(RuntimeError, match="no usable AMD ROCm device"):
        resolve_compute("amd-rocm", CpuTorch)


def test_non_amd_cuda_runtime_is_not_mislabeled_as_amd():
    class NvidiaTorch(AmdRocmTorch):
        class version:
            hip = None

        class cuda:
            @staticmethod
            def is_available():
                return True

            @staticmethod
            def device_count():
                return 1

            @staticmethod
            def get_device_name(index):
                return "NVIDIA Test Device"

    assert inspect_compute(NvidiaTorch)["provider"] == "cuda"
    assert resolve_compute("auto", NvidiaTorch)["provider"] == "cpu"


def test_saved_model_inference_reports_the_execution_path():
    from pathlib import Path
    from pumpguard.models.diagnostic import DiagnosticTelemetry
    from pumpguard.services.ml_inference import MLInferenceService

    try:
        import torch  # noqa: F401
    except (ImportError, OSError):
        pytest.skip("optional PyTorch is not installed")
    artifact = Path("models/pumpguard_mlp.pt")
    if not artifact.is_file():
        pytest.skip("saved scenario model is absent")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    window = [DiagnosticTelemetry(timestamp=start + timedelta(seconds=index), temperature_c=68 + index,
                                  vibration_mm_s=2 + index * 0.1, sound_db=68, rpm=1780)
              for index in range(5)]
    result = MLInferenceService(artifact).predict(window)
    assert result is not None
    assert result["label"] in {"normal", "overheating", "bearing_wear", "cavitation", "imbalance"}
    assert result["model_version"] == "pumpguard-scenario-mlp-v1"
    assert result["execution_path"] in {"pytorch_cpu", "pytorch_amd_rocm"}


def test_status_reports_selected_execution_path_and_unloaded_classifier():
    from pathlib import Path
    from pumpguard.services.ml_inference import MLInferenceService

    try:
        import torch  # noqa: F401
    except (ImportError, OSError):
        pytest.skip("optional PyTorch is not installed")
    artifact = Path("models/pumpguard_mlp.pt")
    if not artifact.is_file():
        pytest.skip("saved scenario model is absent")
    service = MLInferenceService(artifact)
    status = service.status()
    # The selected/resolved execution path is reported, never the old "not_loaded" placeholder.
    assert status["execution_path"] != "not_loaded"
    assert status["execution_path"] == {"cpu": "pytorch_cpu", "amd_rocm": "pytorch_amd_rocm",
                                        "cuda": "pytorch_cuda"}.get(status["compute_provider"], "unavailable")
    # No inference has run yet, so no classifier is instantiated.
    assert status["classifier_loaded"] is False


def test_status_marks_classifier_loaded_after_inference():
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from pumpguard.models.diagnostic import DiagnosticTelemetry
    from pumpguard.services.ml_inference import MLInferenceService

    try:
        import torch  # noqa: F401
    except (ImportError, OSError):
        pytest.skip("optional PyTorch is not installed")
    artifact = Path("models/pumpguard_mlp.pt")
    if not artifact.is_file():
        pytest.skip("saved scenario model is absent")
    service = MLInferenceService(artifact)
    assert service.status()["classifier_loaded"] is False
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    window = [DiagnosticTelemetry(timestamp=start + timedelta(seconds=index), temperature_c=68 + index,
                                  vibration_mm_s=2 + index * 0.1, sound_db=68, rpm=1780)
              for index in range(5)]
    result = service.predict(window)
    assert result is not None
    # After a completed inference the classifier is loaded and the actual execution path matches status.
    assert service.status()["classifier_loaded"] is True
    assert result["execution_path"] == service.status()["execution_path"]
