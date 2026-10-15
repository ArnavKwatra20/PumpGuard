"""Training-only numeric imputation and standardization."""
from __future__ import annotations
from collections.abc import Sequence
from typing import Any

class TrainingOnlyStandardizer:
    """Median-impute and standardize using fitted training rows only."""
    def __init__(self) -> None:
        self.medians_: list[float] | None = None
        self.means_: list[float] | None = None
        self.scales_: list[float] | None = None

    def fit(self, rows: Sequence[Sequence[Any]]) -> "TrainingOnlyStandardizer":
        """Fit medians, means, and population standard deviations on training data."""
        if not rows or not rows[0]:
            raise ValueError("training rows must be non-empty")
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            raise ValueError("all rows must have the same number of features")
        medians = []
        for column in range(width):
            valid = sorted(float(row[column]) for row in rows if row[column] is not None)
            if not valid:
                medians.append(0.0)
            elif len(valid) % 2:
                medians.append(valid[len(valid) // 2])
            else:
                medians.append((valid[len(valid) // 2 - 1] + valid[len(valid) // 2]) / 2)
        imputed = [[medians[j] if row[j] is None else float(row[j]) for j in range(width)] for row in rows]
        means = [sum(row[j] for row in imputed) / len(imputed) for j in range(width)]
        scales = []
        for j, mean in enumerate(means):
            variance = sum((row[j] - mean) ** 2 for row in imputed) / len(imputed)
            scale = variance ** 0.5
            scales.append(scale if scale > 0 else 1.0)
        self.medians_, self.means_, self.scales_ = medians, means, scales
        return self

    def transform(self, rows: Sequence[Sequence[Any]]) -> list[list[float]]:
        """Apply the training-fitted transform without refitting."""
        if self.medians_ is None or self.means_ is None or self.scales_ is None:
            raise RuntimeError("fit must be called before transform")
        width = len(self.medians_)
        if any(len(row) != width for row in rows):
            raise ValueError("row feature count does not match fitted transformer")
        return [[
            ((self.medians_[j] if value is None else float(value)) - self.means_[j]) / self.scales_[j]
            for j, value in enumerate(row)
        ] for row in rows]

    def fit_transform(self, rows: Sequence[Sequence[Any]]) -> list[list[float]]:
        """Fit on the supplied training data and return its transformed values."""
        return self.fit(rows).transform(rows)
