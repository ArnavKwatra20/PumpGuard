"""Small CPU-first PyTorch classifier with validation-only model selection.

PyTorch is imported lazily so the PumpGuard service and data utilities remain usable
without the optional dependency.
"""
from __future__ import annotations

import random
from pathlib import Path
from time import perf_counter
from typing import Any, Sequence

from pumpguard.data.evaluation import evaluate_classification
from pumpguard.data.preprocessing import TrainingOnlyStandardizer
from pumpguard.data.splitting import input_feature_names
from pumpguard.ml.compute import resolve_compute
from pumpguard.simulator.generator import SCENARIOS


def _torch():
    try:
        import torch
        from torch import nn
    except (ImportError, OSError) as exc:
        raise RuntimeError("PyTorch is optional; install PumpGuard with the 'torch' extra to use this pipeline.") from exc
    return torch, nn


def _model_class():
    torch, nn = _torch()

    class PumpMLP(nn.Module):
        def __init__(self, input_size: int, hidden_sizes: Sequence[int] = (64, 32), dropout: float = 0.1):
            super().__init__()
            layers: list[Any] = []
            width = input_size
            for hidden in hidden_sizes:
                layers.extend((nn.Linear(width, hidden), nn.ReLU(), nn.Dropout(dropout)))
                width = hidden
            layers.append(nn.Linear(width, len(SCENARIOS)))
            self.network = nn.Sequential(*layers)

        def forward(self, inputs):
            return self.network(inputs)

    return PumpMLP


def parameter_count(model: Any) -> int:
    """Count trainable parameters in a PyTorch module."""
    return sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)


def _metrics(y_true: list[str], probabilities: list[list[float]]) -> dict[str, Any]:
    predictions = [SCENARIOS[max(range(len(row)), key=row.__getitem__)] for row in probabilities]
    return evaluate_classification(y_true, predictions, labels=SCENARIOS, y_score=probabilities)


def _probabilities(model: Any, features: list[list[float]], *, device: str = "cpu") -> list[list[float]]:
    torch, _ = _torch()
    model.eval()
    if not features:
        return []
    with torch.no_grad():
        logits = model(torch.tensor(features, dtype=torch.float32, device=device))
        return torch.softmax(logits, dim=1).cpu().tolist()


def train_classifier(
    feature_names: Sequence[str],
    train_rows: Sequence[dict[str, Any]],
    validation_rows: Sequence[dict[str, Any]],
    *,
    artifact_path: str | Path,
    seed: int = 42,
    epochs: int = 40,
    batch_size: int = 64,
    learning_rate: float = 1e-3,
    patience: int = 6,
    hidden_sizes: Sequence[int] = (64, 32),
    dropout: float = 0.1,
    device: str = "cpu",
    split_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fit on train rows, select by validation balanced accuracy, and save best state."""
    if not feature_names or not train_rows or not validation_rows:
        raise ValueError("features, training rows, and validation rows must be non-empty")
    allowed_features = set(input_feature_names(train_rows))
    if any(name not in allowed_features for name in feature_names):
        raise ValueError("feature_names must come from PumpGuard's numeric feature allowlist; labels and metadata are excluded")
    if epochs < 1 or batch_size < 1 or learning_rate <= 0 or patience < 1:
        raise ValueError("epochs, batch_size, patience, and learning_rate must be positive")
    torch, nn = _torch()
    compute = resolve_compute(device, torch)
    torch_device = compute["device"]
    random.seed(seed)
    torch.manual_seed(seed)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    torch.set_num_threads(1)

    def raw(rows):
        for row in rows:
            missing = [name for name in feature_names if name not in row]
            if missing:
                raise ValueError(f"rows missing configured feature(s): {missing}")
        return [[row[name] for name in feature_names] for row in rows]

    x_train_raw = raw(train_rows)
    x_val_raw = raw(validation_rows)
    y_train = [str(row["scenario_label"]) for row in train_rows]
    y_val = [str(row["scenario_label"]) for row in validation_rows]
    unknown = sorted((set(y_train) | set(y_val)) - set(SCENARIOS))
    if unknown:
        raise ValueError(f"unknown scenario label(s): {unknown}")
    prep = TrainingOnlyStandardizer().fit(x_train_raw)
    x_train = prep.transform(x_train_raw)
    x_val = prep.transform(x_val_raw)
    X = torch.tensor(x_train, dtype=torch.float32, device=torch_device)
    y_indices = torch.tensor([SCENARIOS.index(label) for label in y_train], dtype=torch.long, device=torch_device)
    dataset = torch.utils.data.TensorDataset(X, y_indices)
    loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True, generator=generator)
    model = _model_class()(len(feature_names), hidden_sizes, dropout).to(torch_device)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    criterion = nn.CrossEntropyLoss()

    best_score = -1.0
    best_loss = float("inf")
    best_epoch = 0
    best_state = None
    stale_epochs = 0
    start = perf_counter()
    for epoch in range(1, epochs + 1):
        model.train()
        for batch_x, batch_y in loader:
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(batch_x), batch_y)
            loss.backward()
            optimizer.step()
        val_prob = _probabilities(model, x_val, device=torch_device)
        val_metrics = _metrics(y_val, val_prob)
        val_loss = criterion(model(torch.tensor(x_val, dtype=torch.float32, device=torch_device)),
                             torch.tensor([SCENARIOS.index(label) for label in y_val], dtype=torch.long, device=torch_device)).item()
        score = val_metrics["balanced_accuracy"]
        if score > best_score or (score == best_score and val_loss < best_loss):
            best_score, best_loss, best_epoch = score, val_loss, epoch
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            stale_epochs = 0
        else:
            stale_epochs += 1
        if stale_epochs >= patience:
            break
    training_seconds = perf_counter() - start
    assert best_state is not None
    model.load_state_dict(best_state)
    model.to(torch_device)
    best_validation_metrics = _metrics(y_val, _probabilities(model, x_val, device=torch_device))
    config = {
        "seed": seed, "epochs_requested": epochs, "epochs_trained": epoch,
        "batch_size": batch_size, "learning_rate": learning_rate, "patience": patience,
        "hidden_sizes": list(hidden_sizes), "dropout": dropout, "device": torch_device,
        "requested_compute_provider": device, "compute_provider": compute["provider"],
        "device_name": compute["devices"][0]["name"] if compute["devices"] and torch_device != "cpu" else "CPU",
        "execution_path": compute["execution_path"],
        "best_epoch": best_epoch, "best_validation_balanced_accuracy": best_score,
        "best_validation_loss": best_loss, "train_seconds": training_seconds,
    }
    artifact = {
        "format_version": 1, "model_version": "pumpguard-scenario-mlp-v1", "state_dict": best_state,
        "feature_names": list(feature_names),
        "preprocessing": {"medians": prep.medians_, "means": prep.means_, "scales": prep.scales_},
        "label_mapping": {label: index for index, label in enumerate(SCENARIOS)},
        "model_config": {"input_size": len(feature_names), "hidden_sizes": list(hidden_sizes),
                         "dropout": dropout, "num_classes": len(SCENARIOS)},
        "training_config": config, "split_metadata": split_metadata,
    }
    path = Path(artifact_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(artifact, path)
    return {"artifact_path": str(path), "feature_names": list(feature_names),
            "parameter_count": parameter_count(model), "training_config": config,
            "validation_metrics": best_validation_metrics, "model": model,
            "preprocessing": prep}


class SavedClassifier:
    """Loaded model artifact for ordered feature-row prediction."""
    def __init__(self, artifact_path: str | Path, *, device: str = "cpu"):
        torch, _ = _torch()
        compute = resolve_compute(device, torch)
        self.compute_info = compute
        self.device = compute["device"]
        self.artifact_path = Path(artifact_path)
        try:
            self.artifact = torch.load(self.artifact_path, map_location="cpu", weights_only=True)
        except TypeError:  # compatibility with older supported PyTorch releases
            self.artifact = torch.load(self.artifact_path, map_location="cpu")
        self.feature_names = list(self.artifact["feature_names"])
        self.label_mapping = dict(self.artifact["label_mapping"])
        config = self.artifact["model_config"]
        self.model = _model_class()(config["input_size"], config["hidden_sizes"], config["dropout"])
        self.model.load_state_dict(self.artifact["state_dict"])
        self.model.to(self.device)
        self.model.eval()
        self.model_version = self.artifact.get("model_version", "pumpguard-scenario-mlp-v1")

    def predict_proba(self, rows: Sequence[dict[str, Any]]) -> list[list[float]]:
        torch, _ = _torch()
        prep_data = self.artifact["preprocessing"]
        prep = TrainingOnlyStandardizer()
        prep.medians_ = list(prep_data["medians"])
        prep.means_ = list(prep_data["means"])
        prep.scales_ = list(prep_data["scales"])
        ordered = []
        for row in rows:
            missing = [name for name in self.feature_names if name not in row]
            if missing:
                raise ValueError(f"prediction row missing configured feature(s): {missing}")
            ordered.append([row[name] for name in self.feature_names])
        return _probabilities(self.model, prep.transform(ordered), device=self.device)

    def predict(self, rows: Sequence[dict[str, Any]]) -> list[str]:
        probabilities = self.predict_proba(rows)
        labels = [label for label, _ in sorted(self.label_mapping.items(), key=lambda item: item[1])]
        return [labels[max(range(len(scores)), key=scores.__getitem__)] for scores in probabilities]
