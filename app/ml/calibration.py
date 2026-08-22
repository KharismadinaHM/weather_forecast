"""Probability calibration and evaluation metrics (PLAN.md Section 10)."""

from typing import Any

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


def mean_absolute_error(y_true: Any, y_pred: Any) -> float:
    """Compute Mean Absolute Error."""
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    valid = ~(np.isnan(yt) | np.isnan(yp))
    if not np.any(valid):
        return 0.0
    return float(np.mean(np.abs(yt[valid] - yp[valid])))


def root_mean_squared_error(y_true: Any, y_pred: Any) -> float:
    """Compute Root Mean Squared Error."""
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    valid = ~(np.isnan(yt) | np.isnan(yp))
    if not np.any(valid):
        return 0.0
    return float(np.sqrt(np.mean((yt[valid] - yp[valid]) ** 2)))


def brier_score(y_true: Any, y_prob: Any) -> float:
    """Compute binary Brier Score: 1/N * sum((y_prob - y_true)^2). Lower is better."""
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_prob, dtype=float)
    if len(yt) == 0:
        return 0.0
    return float(np.mean((yp - yt) ** 2))


def multi_category_brier_score(
    y_true_indices: Any,
    y_prob_matrix: Any,
) -> float:
    """Compute multi-category Brier score across K outcome buckets."""
    probs = np.asarray(y_prob_matrix, dtype=float)
    n_samples, n_classes = probs.shape
    if n_samples == 0:
        return 0.0

    one_hot = np.zeros((n_samples, n_classes), dtype=float)
    for i, idx in enumerate(y_true_indices):
        if 0 <= idx < n_classes:
            one_hot[i, idx] = 1.0

    # Multi-class Brier score: 1/N * sum_i sum_k (p_ik - y_ik)^2
    return float(np.mean(np.sum((probs - one_hot) ** 2, axis=1)))


def binary_log_loss(
    y_true: Any,
    y_prob: Any,
    eps: float = 1e-15,
) -> float:
    """Compute binary log loss (cross-entropy)."""
    yt = np.asarray(y_true, dtype=float)
    yp = np.clip(np.asarray(y_prob, dtype=float), eps, 1.0 - eps)
    if len(yt) == 0:
        return 0.0
    return float(-np.mean(yt * np.log(yp) + (1.0 - yt) * np.log(1.0 - yp)))


def expected_calibration_error(
    y_true: Any,
    y_prob: Any,
    n_bins: int = 10,
) -> float:
    """Compute Expected Calibration Error (ECE) via equal-width probability binning."""
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_prob, dtype=float)
    n = len(yt)
    if n == 0:
        return 0.0

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0

    for i in range(n_bins):
        bin_lower = bin_edges[i]
        bin_upper = bin_edges[i + 1]

        if i == n_bins - 1:
            in_bin = (yp >= bin_lower) & (yp <= bin_upper)
        else:
            in_bin = (yp >= bin_lower) & (yp < bin_upper)

        count_in_bin = int(np.sum(in_bin))
        if count_in_bin > 0:
            avg_confidence = float(np.mean(yp[in_bin]))
            avg_accuracy = float(np.mean(yt[in_bin]))
            ece += (count_in_bin / n) * abs(avg_accuracy - avg_confidence)

    return float(ece)


class PlattCalibrator:
    """Platt scaling calibrator (logistic regression on log-odds / probabilities)."""

    def __init__(self) -> None:
        self.clf = LogisticRegression(C=1.0, solver="lbfgs")
        self.is_fitted = False

    def fit(self, y_prob: Any, y_true: Any) -> "PlattCalibrator":
        probs = np.asarray(y_prob, dtype=float).reshape(-1, 1)
        targets = np.asarray(y_true, dtype=int)
        if len(np.unique(targets)) < 2:
            self.is_fitted = False
            return self
        self.clf.fit(probs, targets)
        self.is_fitted = True
        return self

    def predict_proba(self, y_prob: Any) -> np.ndarray:
        probs = np.asarray(y_prob, dtype=float).reshape(-1, 1)
        if not self.is_fitted:
            return np.asarray(y_prob, dtype=float)
        return np.asarray(self.clf.predict_proba(probs)[:, 1], dtype=float)


class IsotonicCalibrator:
    """Non-parametric isotonic regression calibrator."""

    def __init__(self) -> None:
        self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        self.is_fitted = False

    def fit(self, y_prob: Any, y_true: Any) -> "IsotonicCalibrator":
        probs = np.asarray(y_prob, dtype=float)
        targets = np.asarray(y_true, dtype=float)
        if len(probs) < 5 or len(np.unique(targets)) < 2:
            self.is_fitted = False
            return self
        self.iso.fit(probs, targets)
        self.is_fitted = True
        return self

    def predict_proba(self, y_prob: Any) -> np.ndarray:
        probs = np.asarray(y_prob, dtype=float)
        if not self.is_fitted:
            return probs
        return np.asarray(self.iso.predict(probs), dtype=float)
