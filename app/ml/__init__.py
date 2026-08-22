"""Machine Learning Module for Hong Kong Weather Prediction Market Agent."""

from app.ml.baselines import ClimatologyBaseline, HKOFailoverBaseline, PersistenceBaseline
from app.ml.calibration import (
    IsotonicCalibrator,
    PlattCalibrator,
    binary_log_loss,
    brier_score,
    expected_calibration_error,
    mean_absolute_error,
    multi_category_brier_score,
    root_mean_squared_error,
)
from app.ml.distribution import ContinuousToBucketMapper
from app.ml.evaluator import EvaluationReport, ModelEvaluator
from app.ml.models import WeatherMLModel

__all__ = [
    "ContinuousToBucketMapper",
    "ClimatologyBaseline",
    "HKOFailoverBaseline",
    "PersistenceBaseline",
    "WeatherMLModel",
    "brier_score",
    "multi_category_brier_score",
    "binary_log_loss",
    "expected_calibration_error",
    "mean_absolute_error",
    "root_mean_squared_error",
    "PlattCalibrator",
    "IsotonicCalibrator",
    "EvaluationReport",
    "ModelEvaluator",
]
