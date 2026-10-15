"""Optional explicit ML inference over recorded telemetry; never changes rule assessments."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pumpguard.config import PROJECT_ROOT
from pumpguard.data.features import engineer_features
from pumpguard.ml.compute import inspect_compute
from pumpguard.models.diagnostic import DiagnosticTelemetry


class MLInferenceService:
    def __init__(self, artifact_path: str | Path | None = None) -> None:
        self.artifact_path = Path(artifact_path or os.getenv("PUMPGUARD_ML_ARTIFACT", PROJECT_ROOT / "models" / "pumpguard_mlp.pt"))
        self.requested_compute = os.getenv("PUMPGUARD_COMPUTE_PROVIDER", "auto")
        self._classifier = None
        self._load_error: str | None = None

    def status(self) -> dict[str, Any]:
        compute = inspect_compute()
        artifact_available = self.artifact_path.is_file()
        if self.requested_compute == "cpu":
            provider, device, provider_available = "cpu", "cpu", True
        elif self.requested_compute == "auto":
            use_amd = compute["provider"] == "amd_rocm"
            provider, device, provider_available = ("amd_rocm", "cuda:0", True) if use_amd else ("cpu", "cpu", True)
        elif self.requested_compute == "amd-rocm":
            provider_available = compute["provider"] == "amd_rocm"
            provider, device = ("amd_rocm", "cuda:0") if provider_available else ("unavailable", "unavailable")
        elif self.requested_compute == "cuda":
            provider_available = bool(compute.get("accelerator_available"))
            provider = compute["provider"] if provider_available else "unavailable"
            device = "cuda:0" if provider_available else "unavailable"
        else:
            provider, device, provider_available = "unavailable", "unavailable", False
        torch_available = bool(compute.get("torch_available"))
        # execution_path is the provider that WOULD be used for a fresh inference, resolved from the
        # same runtime state as provider/device above. It is the selected path, not proof that inference
        # has run; classifier_loaded reports whether a classifier is actually instantiated.
        execution_path = {"cpu": "pytorch_cpu", "amd_rocm": "pytorch_amd_rocm",
                          "cuda": "pytorch_cuda"}.get(provider, "unavailable")
        return {
            "enabled": artifact_available and torch_available and provider_available,
            "artifact_available": artifact_available,
            "provider_available": provider_available,
            "model_version": "pumpguard-scenario-mlp-v1" if artifact_available else None,
            "requested_compute_provider": self.requested_compute,
            "compute_provider": provider,
            "device": device,
            "execution_path": execution_path,
            "classifier_loaded": self._classifier is not None,
            "pytorch_version": compute.get("pytorch_version"),
            "hip_version": compute.get("hip_version"),
            "devices": compute.get("devices", []),
            "inference_error": self._load_error,
            "interpretation": "Synthetic scenario classification only; this is not a fault probability, degradation forecast, or real-world validation.",
        }

    def _load(self):
        if self._classifier is not None:
            return self._classifier
        if self._load_error:
            return None
        try:
            from pumpguard.ml.pipeline import SavedClassifier
            self._classifier = SavedClassifier(self.artifact_path, device=self.requested_compute)
            return self._classifier
        except Exception as exc:
            # Exception text can expose paths or runtime details; status returns only its type.
            self._load_error = type(exc).__name__
            return None

    def predict(self, telemetry: list[DiagnosticTelemetry]) -> dict[str, Any] | None:
        if not telemetry or not self.artifact_path.is_file():
            return None
        classifier = self._load()
        if classifier is None:
            return None
        rows = [{"timestamp": reading.timestamp, "pump_id": "diagnostic-window",
                 "temperature_c": reading.temperature_c, "vibration_mm_s": reading.vibration_mm_s,
                 "sound_db": reading.sound_db, "rpm": reading.rpm} for reading in telemetry]
        feature_row = engineer_features(rows)[-1]
        probabilities = classifier.predict_proba([feature_row])[0]
        labels = [label for label, _ in sorted(classifier.label_mapping.items(), key=lambda pair: pair[1])]
        scores = dict(zip(labels, probabilities))
        label = max(scores, key=scores.get)
        compute = classifier.compute_info
        return {
            "label": label,
            "score": float(scores[label]),
            "probabilities": scores,
            "model_version": classifier.model_version,
            "compute_provider": compute["provider"],
            "device": compute["device"],
            "execution_path": compute["execution_path"],
            "interpretation": "Synthetic scenario classification only; not a fault probability, degradation forecast, or real-world validation.",
        }
