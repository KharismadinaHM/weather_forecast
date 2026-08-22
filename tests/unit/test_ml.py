"""Unit tests for ML models, baselines, distribution mapping, and evaluation."""

import math
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.collectors.bucket_parser import BucketParser, ParsedBucket
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
from app.ml.evaluator import ModelEvaluator
from app.ml.models import WeatherMLModel
from app.storage.models import WeatherDaily


def test_continuous_to_bucket_mapper_bounds() -> None:
    """Verify Gaussian integration and half-degree continuity correction on diverse buckets."""
    b_lower = ParsedBucket(
        raw_label="<=30", low=None, high=30.0, is_open_lower=True, is_open_upper=False
    )
    b_mid1 = ParsedBucket(
        raw_label="31", low=31.0, high=31.0, is_open_lower=False, is_open_upper=False
    )
    b_mid2 = ParsedBucket(
        raw_label="32 - 33", low=32.0, high=33.0, is_open_lower=False, is_open_upper=False
    )
    b_upper = ParsedBucket(
        raw_label=">=34", low=34.0, high=None, is_open_lower=False, is_open_upper=True
    )

    buckets = [b_lower, b_mid1, b_mid2, b_upper]
    probs = ContinuousToBucketMapper.map_distribution_to_buckets(buckets, mean=31.0, std=1.0)

    # All probabilities should be positive and sum to 1.0
    assert len(probs) == 4
    assert math.isclose(sum(probs.values()), 1.0, rel_tol=1e-5)
    # Mean is 31.0 -> '31' should have high probability
    assert probs["31"] > probs[">=34"]
    assert probs["31"] > probs["<=30"]


def test_climatology_baseline(db_session: Session) -> None:
    """Verify ClimatologyBaseline computes calendar date seasonal averages."""
    # Populate historical temperatures
    for y in [2024, 2025]:
        db_session.add(
            WeatherDaily(
                date=date(y, 8, 23),
                station="Hong Kong Observatory",
                max_temperature=32.0 if y == 2024 else 34.0,
            )
        )
    db_session.commit()

    clim = ClimatologyBaseline().fit(db_session)
    mean_pred, std_pred = clim.predict_continuous(date(2026, 8, 23))

    assert round(mean_pred, 1) == 33.0
    assert std_pred > 0.0


def test_persistence_baseline() -> None:
    """Verify PersistenceBaseline extracts previous day temperature."""
    pers = PersistenceBaseline()
    mean_pred, std_pred = pers.predict_continuous({"max_temp_lag1": 29.5})
    assert mean_pred == 29.5
    assert std_pred == PersistenceBaseline.DEFAULT_ERROR_STD


def test_hko_failover_baseline() -> None:
    """Verify HKOFailoverBaseline uses official forecast and scales uncertainty with lead days."""
    hko_base = HKOFailoverBaseline()

    # When forecast is available
    features_avail = {
        "hko_forecast_max_temp": 33.5,
        "forecast_available": 1,
        "lead_days": 1,
    }
    mean_1d, std_1d = hko_base.predict_continuous(features_avail)
    assert mean_1d == 33.5
    assert round(std_1d, 2) == 1.1

    # Uncertainty should increase with 4 lead days
    features_4d = {
        "hko_forecast_max_temp": 33.5,
        "forecast_available": 1,
        "lead_days": 4,
    }
    _, std_4d = hko_base.predict_continuous(features_4d)
    assert std_4d > std_1d
    assert round(std_4d, 2) == 2.2


def test_weather_ml_model_train_and_predict() -> None:
    """Verify WeatherMLModel fits on feature DataFrame and outputs valid predictions."""
    # Generate synthetic training dataset
    np.random.seed(42)
    n_samples = 30
    rows = []
    y_vals = []
    base_date = date(2026, 8, 1)
    for i in range(n_samples):
        cur_d = base_date + timedelta(days=i)
        hko_fc = 30.0 + np.random.uniform(-2, 3)
        actual = hko_fc + np.random.normal(0, 0.6)
        rows.append(
            {
                "target_date": cur_d.isoformat(),
                "month": cur_d.month,
                "day_of_year": cur_d.timetuple().tm_yday,
                "day_of_week": cur_d.weekday(),
                "is_weekend": 1 if cur_d.weekday() >= 5 else 0,
                "sin_day_of_year": math.sin(2 * math.pi * cur_d.timetuple().tm_yday / 365.25),
                "cos_day_of_year": math.cos(2 * math.pi * cur_d.timetuple().tm_yday / 365.25),
                "max_temp_lag1": actual - 0.2,
                "max_temp_lag2": actual - 0.5,
                "min_temp_lag1": 26.0,
                "mean_temp_lag1": 28.0,
                "rainfall_lag1": 0.0,
                "temp_range_lag1": actual - 26.0,
                "rolling_7d_max_temp": 30.5,
                "rolling_30d_max_temp": 30.2,
                "rolling_7d_rainfall": 5.0,
                "hko_forecast_max_temp": hko_fc,
                "hko_forecast_min_temp": 27.0,
                "rain_probability": 0.2,
                "forecast_available": 1,
                "lead_days": 1,
                "forecast_revision_count": 1,
                "forecast_revision_delta": 0.0,
            }
        )
        y_vals.append(actual)

    df_X = pd.DataFrame(rows)
    s_y = pd.Series(y_vals)

    model = WeatherMLModel(n_estimators=30, learning_rate=0.1)
    model.fit(df_X, s_y)

    assert model.is_fitted
    preds, res_std = model.predict_continuous(df_X.iloc[:5])
    assert len(preds) == 5
    assert res_std > 0.0

    # Bucket prediction
    buckets = BucketParser.parse_bucket_schema(["<=29", "30 - 31", ">=32"])
    probs = model.predict_buckets(rows[0], buckets)
    assert len(probs) == 3
    assert math.isclose(sum(probs.values()), 1.0, rel_tol=1e-4)


def test_calibration_and_error_metrics() -> None:
    """Verify MAE, RMSE, Brier score, Log loss, and ECE computation."""
    y_true = [1, 0, 1, 1, 0]
    y_prob = [0.9, 0.1, 0.8, 0.7, 0.2]

    brier = brier_score(y_true, y_prob)
    assert brier < 0.1

    loss = binary_log_loss(y_true, y_prob)
    assert loss < 0.5

    ece = expected_calibration_error(y_true, y_prob, n_bins=5)
    assert 0.0 <= ece <= 1.0

    # Continuous error metrics
    mae = mean_absolute_error([30.0, 32.0], [30.5, 31.5])
    assert round(mae, 2) == 0.5
    rmse = root_mean_squared_error([30.0, 32.0], [30.5, 31.5])
    assert round(rmse, 2) == 0.5

    # Multi-category Brier score
    y_idx = [0, 1]
    probs = [[0.8, 0.2], [0.1, 0.9]]
    mc_brier = multi_category_brier_score(y_idx, probs)
    assert mc_brier < 0.2


def test_platt_and_isotonic_calibrators() -> None:
    """Verify Platt and Isotonic calibration transforms."""
    probs = [0.1, 0.2, 0.4, 0.6, 0.8, 0.9]
    targets = [0, 0, 0, 1, 1, 1]

    platt = PlattCalibrator().fit(probs, targets)
    assert platt.is_fitted
    cal_p = platt.predict_proba([0.5])
    assert 0.0 <= cal_p[0] <= 1.0

    iso = IsotonicCalibrator().fit(probs, targets)
    assert iso.is_fitted
    iso_p = iso.predict_proba([0.5])
    assert 0.0 <= iso_p[0] <= 1.0


def test_model_evaluator_go_no_go_and_persistence(db_session: Session) -> None:
    """Verify ModelEvaluator outputs structured Go/No-Go report and persists to DB."""
    # Create synthetic evaluation dataset with valid sequential dates
    rows = []
    y_vals = []
    base_date = date(2026, 8, 1)
    for i in range(25):
        cur_d = base_date + timedelta(days=i)
        hko_fc = 31.0 + (i % 3)
        actual = hko_fc + 0.1  # ML can easily learn this
        rows.append(
            {
                "target_date": cur_d.isoformat(),
                "month": cur_d.month,
                "day_of_year": cur_d.timetuple().tm_yday,
                "day_of_week": cur_d.weekday(),
                "is_weekend": 0,
                "sin_day_of_year": 0.5,
                "cos_day_of_year": 0.5,
                "max_temp_lag1": actual - 0.1,
                "max_temp_lag2": actual - 0.2,
                "min_temp_lag1": 26.0,
                "mean_temp_lag1": 28.0,
                "rainfall_lag1": 0.0,
                "temp_range_lag1": 5.0,
                "rolling_7d_max_temp": 31.0,
                "rolling_30d_max_temp": 30.5,
                "rolling_7d_rainfall": 0.0,
                "hko_forecast_max_temp": hko_fc,
                "hko_forecast_min_temp": 26.0,
                "rain_probability": 0.1,
                "forecast_available": 1,
                "lead_days": 1,
                "forecast_revision_count": 1,
                "forecast_revision_delta": 0.0,
            }
        )
        y_vals.append(actual)

    df_X = pd.DataFrame(rows)
    s_y = pd.Series(y_vals)

    model = WeatherMLModel(n_estimators=40, learning_rate=0.1)
    model.fit(df_X, s_y)

    report = ModelEvaluator.evaluate(model, df_X, s_y, model_version="lgbm_test_v1")

    assert report.model_version == "lgbm_test_v1"
    assert report.decision in ["GO", "NO-GO"]
    assert report.sample_size == 25
    assert report.ml_mae >= 0.0
    assert report.hko_mae >= 0.0

    # Persist to database
    t_start = datetime(2026, 8, 1, tzinfo=UTC)
    t_end = datetime(2026, 8, 20, tzinfo=UTC)
    db_record = ModelEvaluator.record_model_run(
        db_session,
        report,
        training_start=t_start,
        training_end=t_end,
        validation_start=t_start,
        validation_end=t_end,
        test_start=t_start,
        test_end=t_end,
    )
    assert db_record.id is not None
    assert db_record.model_version == "lgbm_test_v1"
