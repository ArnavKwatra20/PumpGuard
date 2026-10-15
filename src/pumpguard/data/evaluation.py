"""Dependency-light classification metrics for CPU experiments."""
from __future__ import annotations
from collections.abc import Sequence
from typing import Any

def _binary_auc(truth: list[int], scores: list[float]) -> float | None:
    """Compute rank-based ROC-AUC with half credit for ties."""
    positives = [s for y, s in zip(truth, scores) if y == 1]
    negatives = [s for y, s in zip(truth, scores) if y == 0]
    if not positives or not negatives:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))

def _average_precision(truth: list[int], scores: list[float]) -> float | None:
    """Compute threshold-based average precision with tied scores grouped."""
    positives = sum(truth)
    if not positives or positives == len(truth):
        return None
    ranked = sorted(zip(scores, truth), key=lambda pair: pair[0], reverse=True)
    hits = retrieved = 0
    total = 0.0
    index = 0
    while index < len(ranked):
        score = ranked[index][0]
        end = index
        group_hits = 0
        while end < len(ranked) and ranked[end][0] == score:
            group_hits += ranked[end][1]
            end += 1
        hits += group_hits
        retrieved += end - index
        total += (group_hits / positives) * (hits / retrieved)
        index = end
    return total

def evaluate_classification(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    *,
    labels: Sequence[str] | None = None,
    y_score: Any = None,
) -> dict[str, Any]:
    """Return accuracy, balanced accuracy, macro metrics, and confusion matrix.

    Ranking metrics are computed only when usable scores and class coverage exist.
    Binary y_score is the positive-class score for labels[1]; multiclass scores
    must be a rows-by-class matrix ordered like labels.
    """
    if len(y_true) == 0 or len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must be non-empty and have equal lengths")
    class_order = list(labels or sorted(set(y_true) | set(y_pred)))
    if not class_order:
        raise ValueError("At least one class label is required")
    if any(label not in class_order for label in y_true) or any(label not in class_order for label in y_pred):
        raise ValueError("all observed labels must be included in labels")
    matrix = [[0 for _ in class_order] for _ in class_order]
    for actual, predicted in zip(y_true, y_pred):
        matrix[class_order.index(actual)][class_order.index(predicted)] += 1
    per_class = {}
    recalls = []
    precisions, f1s = [], []
    for index, label in enumerate(class_order):
        tp = matrix[index][index]
        support = sum(matrix[index])
        predicted_count = sum(row[index] for row in matrix)
        precision = tp / predicted_count if predicted_count else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"precision": precision, "recall": recall, "f1": f1, "support": support}
        if support:
            recalls.append(recall)
        precisions.append(precision)
        f1s.append(f1)
    accuracy = sum(a == b for a, b in zip(y_true, y_pred)) / len(y_true)
    result: dict[str, Any] = {
        "sample_count": len(y_true),
        "labels": class_order,
        "accuracy": accuracy,
        "balanced_accuracy": sum(recalls) / len(recalls) if recalls else 0.0,
        "precision_macro": sum(precisions) / len(precisions),
        "recall_macro": sum(per_class[x]["recall"] for x in class_order) / len(class_order),
        "f1_macro": sum(f1s) / len(f1s),
        "confusion_matrix": matrix,
        "per_class": per_class,
        "roc_auc": None,
        "pr_auc": None,
        "ranking_metric_note": "Not computed: valid scores and class distribution were not supplied.",
    }
    if y_score is None:
        return result
    present = set(y_true)
    if len(class_order) == 2 and len(present) == 2:
        try:
            scores = [float(value) for value in y_score]
            if len(scores) != len(y_true):
                raise ValueError("binary y_score must have one value per observation")
            binary_truth = [int(value == class_order[1]) for value in y_true]
            result["roc_auc"] = _binary_auc(binary_truth, scores)
            result["pr_auc"] = _average_precision(binary_truth, scores)
            result["ranking_metric_note"] = "Binary ROC-AUC and average precision computed from supplied positive-class scores."
        except (TypeError, ValueError) as exc:
            result["ranking_metric_note"] = f"Not computed: {exc}"
    elif len(class_order) > 2 and present == set(class_order):
        try:
            if len(y_score) != len(y_true) or any(len(scores) != len(class_order) for scores in y_score):
                raise ValueError("multiclass y_score must have one score per label per observation")
            aucs = []
            for column, label in enumerate(class_order):
                auc = _binary_auc([int(value == label) for value in y_true],
                                  [float(scores[column]) for scores in y_score])
                if auc is not None:
                    aucs.append(auc)
            result["roc_auc"] = sum(aucs) / len(aucs) if aucs else None
            result["ranking_metric_note"] = "Multiclass one-vs-rest ROC-AUC computed; PR-AUC omitted."
        except (TypeError, ValueError, IndexError) as exc:
            result["ranking_metric_note"] = f"Not computed: {exc}"
    else:
        result["ranking_metric_note"] = "Not computed: score shape or class distribution is insufficient."
    return result

def measure_inference(model: Any, features: Any) -> tuple[Any, float]:
    """Run prediction and return predictions plus wall-clock seconds."""
    from time import perf_counter
    start = perf_counter()
    predictions = model.predict(features)
    return predictions, perf_counter() - start
