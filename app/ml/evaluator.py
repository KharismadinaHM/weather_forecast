"""Model Evaluation and Go/No-Go Decision Engine (PLAN.md Section 9.3)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.ml.baselines import ClimatologyBaseline, HKOFailoverBaseline, PersistenceBaseline
from app.ml.calibration import (
    binary_log_loss,
    brier_score,
    expected_calibration_error,
    mean_absolute_error,
    root_mean_squared_error,
)
from app.ml.models import WeatherMLModel
from app.storage.models import ModelRun

logger = get_logger("model_evaluator")


@dataclass(frozen=True)
class EvaluationReport:
    """Structured evaluation report comparing ML against HKO forecast baseline."""

    model_version: str
    decision: str  # 'GO' or 'NO-GO'
    ml_mae: float
    hko_mae: float
    climatology_mae: float
    persistence_mae: float
    ml_rmse: float
    hko_rmse: float
    climatology_rmse: float
    persistence_rmse: float
    mae_improvement_pct: float
    rmse_improvement_pct: float
    brier_score: float | None
    log_loss: float | None
    calibration_error: float | None
    sample_size: int
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "decision": self.decision,
            "ml_mae": self.ml_mae,
            "hko_mae": self.hko_mae,
            "climatology_mae": self.climatology_mae,
            "persistence_mae": self.persistence_mae,
            "ml_rmse": self.ml_rmse,
            "hko_rmse": self.hko_rmse,
            "climatology_rmse": self.climatology_rmse,
            "persistence_rmse": self.persistence_rmse,
            "mae_improvement_pct": self.mae_improvement_pct,
            "rmse_improvement_pct": self.rmse_improvement_pct,
            "brier_score": self.brier_score,
            "log_loss": self.log_loss,
            "calibration_error": self.calibration_error,
            "sample_size": self.sample_size,
            "rationale": self.rationale,
        }


class ModelEvaluator:
    """Evaluates ML models against HKO Official Forecast and persists model run metrics."""

    @classmethod
    def evaluate(
        cls,
        ml_model: WeatherMLModel,
        df_features: pd.DataFrame,
        s_target: pd.Series,
        model_version: str = "lgbm_v1.0",
    ) -> EvaluationReport:
        """Perform rigorous comparative evaluation against HKO forecast and baselines."""
        y_true = np.asarray(s_target, dtype=float)
        valid_mask = ~np.isnan(y_true)

        if np.sum(valid_mask) == 0:
            raise ValueError("No valid ground truth targets available for evaluation")

        df_eval = df_features[valid_mask].copy()
        y_eval = y_true[valid_mask]
        sample_size = len(y_eval)

        # 1. ML Model Predictions
        ml_preds, ml_std = ml_model.predict_continuous(df_eval)
        ml_mae = mean_absolute_error(y_eval, ml_preds)
        ml_rmse = root_mean_squared_error(y_eval, ml_preds)

        # 2. HKO Official Forecast Baseline Predictions
        hko_baseline = HKOFailoverBaseline()
        hko_preds = []
        for _, row in df_eval.iterrows():
            p_mean, _ = hko_baseline.predict_continuous(dict(row))
            hko_preds.append(p_mean)
        hko_mae = mean_absolute_error(y_eval, hko_preds)
        hko_rmse = root_mean_squared_error(y_eval, hko_preds)

        # 3. Climatology Baseline Predictions
        clim_baseline = ClimatologyBaseline()
        clim_preds = []
        for _, row in df_eval.iterrows():
            t_val = row.get("target_date")
            date_val: date | None = None
            if isinstance(t_val, str):
                try:
                    date_val = date.fromisoformat(t_val)
                except ValueError:
                    date_val = None
            elif isinstance(t_val, date):
                date_val = t_val

            if date_val is not None:
                p_mean, _ = clim_baseline.predict_continuous(date_val)
            else:
                p_mean = clim_baseline.global_mean
            clim_preds.append(p_mean)

        clim_mae = mean_absolute_error(y_eval, clim_preds)
        clim_rmse = root_mean_squared_error(y_eval, clim_preds)

        # 4. Persistence Baseline Predictions
        pers_baseline = PersistenceBaseline()
        pers_preds = []
        for _, row in df_eval.iterrows():
            p_mean, _ = pers_baseline.predict_continuous(dict(row))
            pers_preds.append(p_mean)
        pers_mae = mean_absolute_error(y_eval, pers_preds)
        pers_rmse = root_mean_squared_error(y_eval, pers_preds)

        # Improvements relative to HKO baseline
        mae_imp_pct = ((hko_mae - ml_mae) / hko_mae * 100.0) if hko_mae > 0 else 0.0
        rmse_imp_pct = ((hko_rmse - ml_rmse) / hko_rmse * 100.0) if hko_rmse > 0 else 0.0

        # Calibration metrics (using synthetic binary threshold near median for calibration score)
        median_t = float(np.median(y_eval))
        y_binary = (y_eval >= median_t).astype(int)
        from scipy.stats import norm

        prob_above_median = 1.0 - norm.cdf(median_t, loc=ml_preds, scale=ml_std)
        brier = brier_score(y_binary, prob_above_median)
        loss = binary_log_loss(y_binary, prob_above_median)
        ece = expected_calibration_error(y_binary, prob_above_median)

        # Go / No-Go Decision (Section 9.3)
        # CRITICAL RULE: ML model must beat HKO forecast (lower MAE or RMSE)
        is_go = (ml_mae <= hko_mae) or (ml_rmse <= hko_rmse)
        decision = "GO" if is_go else "NO-GO"

        if is_go:
            rationale = (
                f"ML outperforms HKO forecast baseline (MAE: {ml_mae:.3f}°C vs {hko_mae:.3f}°C, "
                f"RMSE: {ml_rmse:.3f}°C vs {hko_rmse:.3f}°C). Decision: GO."
            )
        else:
            rationale = (
                f"ML failed to beat HKO baseline (MAE: {ml_mae:.3f}°C vs {hko_mae:.3f}°C, "
                f"RMSE: {ml_rmse:.3f}°C vs {hko_rmse:.3f}°C). Decision: NO-GO."
            )

        logger.info(
            "Model evaluation completed",
            version=model_version,
            decision=decision,
            ml_mae=ml_mae,
            hko_mae=hko_mae,
        )

        return EvaluationReport(
            model_version=model_version,
            decision=decision,
            ml_mae=ml_mae,
            hko_mae=hko_mae,
            climatology_mae=clim_mae,
            persistence_mae=pers_mae,
            ml_rmse=ml_rmse,
            hko_rmse=hko_rmse,
            climatology_rmse=clim_rmse,
            persistence_rmse=pers_rmse,
            mae_improvement_pct=mae_imp_pct,
            rmse_improvement_pct=rmse_imp_pct,
            brier_score=brier,
            log_loss=loss,
            calibration_error=ece,
            sample_size=sample_size,
            rationale=rationale,
        )

    @classmethod
    def record_model_run(
        cls,
        session: Session,
        report: EvaluationReport,
        training_start: datetime,
        training_end: datetime,
        validation_start: datetime,
        validation_end: datetime,
        test_start: datetime,
        test_end: datetime,
    ) -> ModelRun:
        """Persist evaluation metrics into model_runs database table."""
        run_record = ModelRun(
            model_version=report.model_version,
            training_start=training_start,
            training_end=training_end,
            validation_start=validation_start,
            validation_end=validation_end,
            test_start=test_start,
            test_end=test_end,
            brier_score=report.brier_score,
            log_loss=report.log_loss,
            calibration_error=report.calibration_error,
            mae=report.ml_mae,
            rmse=report.ml_rmse,
            created_at=datetime.now(UTC),
        )
        session.add(run_record)
        session.commit()
        return run_record
