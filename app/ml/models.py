"""Machine Learning Temperature Regression Models (PLAN.md Section 9.2)."""

from collections.abc import Sequence
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

from app.collectors.bucket_parser import ParsedBucket
from app.ml.distribution import ContinuousToBucketMapper


class WeatherMLModel:
    """Gradient Boosted Regression Tree (LightGBM) with continuous residual uncertainty."""

    FEATURE_COLUMNS: list[str] = [
        "month",
        "day_of_year",
        "day_of_week",
        "is_weekend",
        "sin_day_of_year",
        "cos_day_of_year",
        "max_temp_lag1",
        "max_temp_lag2",
        "min_temp_lag1",
        "mean_temp_lag1",
        "rainfall_lag1",
        "temp_range_lag1",
        "rolling_7d_max_temp",
        "rolling_30d_max_temp",
        "rolling_7d_rainfall",
        "hko_forecast_max_temp",
        "hko_forecast_min_temp",
        "rain_probability",
        "forecast_available",
        "lead_days",
        "forecast_revision_count",
        "forecast_revision_delta",
    ]

    def __init__(
        self,
        n_estimators: int = 100,
        learning_rate: float = 0.05,
        max_depth: int = 4,
        random_state: int = 42,
    ) -> None:
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.random_state = random_state

        self.model: lgb.LGBMRegressor | Ridge | None = None
        self.residual_std: float = 1.0
        self.is_fitted: bool = False
        self.feature_names: list[str] = self.FEATURE_COLUMNS.copy()

    def _prepare_matrix(self, df: pd.DataFrame) -> pd.DataFrame:
        """Select and align numeric feature columns, handling missing values gracefully."""
        present_cols = [c for c in self.feature_names if c in df.columns]
        X = df[present_cols].copy()

        # Add missing expected columns as NaN
        for col in self.feature_names:
            if col not in X.columns:
                X[col] = np.nan
            else:
                X[col] = pd.to_numeric(X[col], errors="coerce")

        # Sort columns and enforce float type for GBDT compatibility
        X = X[self.feature_names].astype(float)
        return X

    def fit(self, X: pd.DataFrame, y: pd.Series | np.ndarray) -> "WeatherMLModel":
        """Fit regression model and estimate residual standard deviation via cross-validation."""
        X_mat = self._prepare_matrix(X)
        y_vec = np.asarray(y, dtype=float)

        # Filter out rows where y is NaN
        valid_mask = ~np.isnan(y_vec)
        X_mat = X_mat[valid_mask]
        y_vec = y_vec[valid_mask]

        if len(y_vec) < 5:
            # Not enough data for GBDT, use simple Ridge fallback
            ridge = Ridge(alpha=1.0)
            X_filled = X_mat.fillna(0.0)
            ridge.fit(X_filled, y_vec)
            self.model = ridge
            self.residual_std = 1.5
            self.is_fitted = True
            return self

        # Use LightGBM Regressor
        lgbm = lgb.LGBMRegressor(
            n_estimators=min(self.n_estimators, max(20, len(y_vec) * 2)),
            learning_rate=self.learning_rate,
            max_depth=self.max_depth,
            random_state=self.random_state,
            verbose=-1,
            min_child_samples=max(2, min(20, len(y_vec) // 5)),
        )

        # Estimate residual uncertainty via K-Fold OOF residuals
        n_splits = min(5, len(y_vec))
        if n_splits >= 3:
            kf = KFold(n_splits=n_splits, shuffle=False)
            oof_residuals: list[float] = []

            for train_idx, val_idx in kf.split(X_mat):
                X_tr, X_va = X_mat.iloc[train_idx], X_mat.iloc[val_idx]
                y_tr, y_va = y_vec[train_idx], y_vec[val_idx]

                fold_model = lgb.LGBMRegressor(
                    n_estimators=min(50, len(y_tr)),
                    learning_rate=self.learning_rate,
                    max_depth=self.max_depth,
                    random_state=self.random_state,
                    verbose=-1,
                    min_child_samples=max(2, min(10, len(y_tr) // 3)),
                )
                fold_model.fit(X_tr, y_tr)
                preds = fold_model.predict(X_va)
                oof_residuals.extend(list(y_va - preds))

            if oof_residuals:
                self.residual_std = float(np.std(oof_residuals)) or 0.8
        else:
            self.residual_std = 1.2

        # Fit final model on all data
        lgbm.fit(X_mat, y_vec)
        self.model = lgbm
        self.is_fitted = True
        return self

    def predict_continuous(self, X: pd.DataFrame | dict[str, Any]) -> tuple[np.ndarray, float]:
        """Generate point prediction and residual standard deviation."""
        if not self.is_fitted or self.model is None:
            raise RuntimeError("Model must be fitted before predict")

        if isinstance(X, dict):
            df_in = pd.DataFrame([X])
        else:
            df_in = X

        X_mat = self._prepare_matrix(df_in)

        if isinstance(self.model, Ridge):
            preds = self.model.predict(X_mat.fillna(0.0))
        else:
            preds = self.model.predict(X_mat)

        return np.asarray(preds, dtype=float), self.residual_std

    def predict_buckets(
        self,
        features: dict[str, Any],
        buckets: Sequence[ParsedBucket],
    ) -> dict[str, float]:
        """Generate calibrated discrete bucket probability distribution."""
        preds, std = self.predict_continuous(features)
        mean_pred = float(preds[0])
        return ContinuousToBucketMapper.map_distribution_to_buckets(buckets, mean_pred, std)
