"""Time-based walk-forward validation for weather model (PLAN.md Section 19)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.features.builder import DatasetBuilder
from app.ml.calibration import mean_absolute_error, root_mean_squared_error
from app.ml.models import WeatherMLModel


@dataclass(frozen=True)
class WalkForwardFoldResult:
    """Evaluation output for a single time-based walk-forward validation fold."""

    fold_index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    train_sample_count: int
    test_sample_count: int
    test_mae: float
    test_rmse: float
    test_predictions: list[float]
    test_targets: list[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold_index": self.fold_index,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
            "train_sample_count": self.train_sample_count,
            "test_sample_count": self.test_sample_count,
            "test_mae": self.test_mae,
            "test_rmse": self.test_rmse,
        }


@dataclass(frozen=True)
class WalkForwardSummary:
    """Aggregate walk-forward evaluation metrics across all folds."""

    fold_count: int
    total_test_samples: int
    mean_fold_mae: float
    mean_fold_rmse: float
    overall_mae: float
    overall_rmse: float
    folds: list[WalkForwardFoldResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold_count": self.fold_count,
            "total_test_samples": self.total_test_samples,
            "mean_fold_mae": self.mean_fold_mae,
            "mean_fold_rmse": self.mean_fold_rmse,
            "overall_mae": self.overall_mae,
            "overall_rmse": self.overall_rmse,
            "folds": [f.to_dict() for f in self.folds],
        }


class WalkForwardValidator:
    """Executes non-overlapping, strictly time-ordered rolling walk-forward validation."""

    @classmethod
    def run_validation(
        cls,
        session: Session,
        fold_schedules: Sequence[tuple[tuple[date, date], tuple[date, date]]],
        n_estimators: int = 40,
        learning_rate: float = 0.05,
    ) -> WalkForwardSummary:
        """Run walk-forward validation over specified [(train_range, test_range)] folds."""
        fold_results: list[WalkForwardFoldResult] = []
        all_oof_preds: list[float] = []
        all_oof_targets: list[float] = []

        for idx, (train_range, test_range) in enumerate(fold_schedules, start=1):
            tr_start, tr_end = train_range
            te_start, te_end = test_range

            # Build list of dates for train and test
            tr_dates = [
                date.fromordinal(o) for o in range(tr_start.toordinal(), tr_end.toordinal() + 1)
            ]
            te_dates = [
                date.fromordinal(o) for o in range(te_start.toordinal(), te_end.toordinal() + 1)
            ]

            # Extract point-in-time training and testing matrices
            df_train_x, s_train_y = DatasetBuilder.build_dataset(session, tr_dates)
            df_test_x, s_test_y = DatasetBuilder.build_dataset(session, te_dates)

            # Fit ML Model on training data
            model = WeatherMLModel(n_estimators=n_estimators, learning_rate=learning_rate)
            model.fit(df_train_x, s_train_y)

            # Predict on test data
            preds, _ = model.predict_continuous(df_test_x)
            y_test = np.asarray(s_test_y, dtype=float)
            valid_mask = ~np.isnan(y_test)

            if np.sum(valid_mask) == 0:
                continue

            y_eval = y_test[valid_mask]
            p_eval = preds[valid_mask]

            fold_mae = mean_absolute_error(y_eval, p_eval)
            fold_rmse = root_mean_squared_error(y_eval, p_eval)

            all_oof_preds.extend(list(p_eval))
            all_oof_targets.extend(list(y_eval))

            fold_results.append(
                WalkForwardFoldResult(
                    fold_index=idx,
                    train_start=tr_start,
                    train_end=tr_end,
                    test_start=te_start,
                    test_end=te_end,
                    train_sample_count=int(np.sum(~np.isnan(s_train_y))),
                    test_sample_count=len(y_eval),
                    test_mae=round(fold_mae, 3),
                    test_rmse=round(fold_rmse, 3),
                    test_predictions=list(p_eval),
                    test_targets=list(y_eval),
                )
            )

        if not fold_results:
            return WalkForwardSummary(
                fold_count=0,
                total_test_samples=0,
                mean_fold_mae=0.0,
                mean_fold_rmse=0.0,
                overall_mae=0.0,
                overall_rmse=0.0,
                folds=[],
            )

        mean_mae = float(np.mean([f.test_mae for f in fold_results]))
        mean_rmse = float(np.mean([f.test_rmse for f in fold_results]))
        overall_mae = mean_absolute_error(all_oof_targets, all_oof_preds)
        overall_rmse = root_mean_squared_error(all_oof_targets, all_oof_preds)

        return WalkForwardSummary(
            fold_count=len(fold_results),
            total_test_samples=len(all_oof_targets),
            mean_fold_mae=round(mean_mae, 3),
            mean_fold_rmse=round(mean_rmse, 3),
            overall_mae=round(overall_mae, 3),
            overall_rmse=round(overall_rmse, 3),
            folds=fold_results,
        )
