"""Tiny pure-Python CPU fallback for scenario classification."""
from __future__ import annotations
from collections import defaultdict
from collections.abc import Sequence
from math import dist
from time import perf_counter
from typing import Any
from pumpguard.data.evaluation import evaluate_classification
from pumpguard.data.preprocessing import TrainingOnlyStandardizer

class NearestCentroidClassifier:
    """Simple Euclidean nearest-centroid classifier for small CPU baselines."""
    def __init__(self) -> None:
        self.labels_: list[str] = []
        self.centroids_: dict[str, list[float]] = {}

    def fit(self, features: Sequence[Sequence[float]], labels: Sequence[str]) -> "NearestCentroidClassifier":
        """Fit one centroid per observed class."""
        if not features or len(features) != len(labels):
            raise ValueError("features and labels must be non-empty and have equal lengths")
        grouped: dict[str, list[list[float]]] = defaultdict(list)
        for row, label in zip(features, labels):
            grouped[str(label)].append(list(map(float, row)))
        self.labels_ = sorted(grouped)
        self.centroids_ = {
            label: [sum(row[j] for row in grouped[label]) / len(grouped[label]) for j in range(len(grouped[label][0]))]
            for label in self.labels_
        }
        return self

    def predict(self, features: Sequence[Sequence[float]]) -> list[str]:
        """Predict the nearest fitted class centroid."""
        if not self.centroids_:
            raise RuntimeError("fit must be called before predict")
        return [min(self.labels_, key=lambda label: dist(row, self.centroids_[label])) for row in features]

def run_nearest_centroid(
    train_x: Sequence[Sequence[Any]],
    train_y: Sequence[str],
    validation_x: Sequence[Sequence[Any]],
    validation_y: Sequence[str],
    test_x: Sequence[Sequence[Any]],
    test_y: Sequence[str],
    *,
    labels: Sequence[str],
) -> dict[str, Any]:
    """Fit preprocessing and centroids on training data; evaluate on held-out sets."""
    start = perf_counter()
    preprocessor = TrainingOnlyStandardizer().fit(train_x)
    transformed_train = preprocessor.transform(train_x)
    model = NearestCentroidClassifier().fit(transformed_train, train_y)
    fit_seconds = perf_counter() - start
    start = perf_counter()
    validation_prediction = model.predict(preprocessor.transform(validation_x))
    validation_inference_seconds = perf_counter() - start
    start = perf_counter()
    test_prediction = model.predict(preprocessor.transform(test_x))
    test_inference_seconds = perf_counter() - start
    return {
        "model": "nearest_centroid_pure_python_fallback",
        "fit_seconds": fit_seconds,
        "validation_inference_seconds": validation_inference_seconds,
        "validation_metrics": evaluate_classification(validation_y, validation_prediction, labels=labels),
        "test_inference_seconds": test_inference_seconds,
        "test_metrics": evaluate_classification(test_y, test_prediction, labels=labels),
        "preprocessing_fit_scope": "training split only",
    }
