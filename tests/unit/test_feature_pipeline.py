"""Unit tests for feature engineering pipeline and dataset builder."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.features.builder import DatasetBuilder
from app.features.pipeline import FeaturePipeline
from app.storage.models import WeatherDaily, WeatherForecast


def test_calendar_features() -> None:
    """Verify calendar and cyclical feature extraction."""
    d = date(2026, 8, 23)
    feats = FeaturePipeline.extract_calendar_features(d)

    assert feats["month"] == 8
    assert feats["day_of_year"] == 235
    assert feats["day_of_week"] == 6  # Sunday
    assert feats["is_weekend"] == 1
    assert -1.0 <= feats["sin_day_of_year"] <= 1.0
    assert -1.0 <= feats["cos_day_of_year"] <= 1.0


def test_historical_lag_features(db_session: Session) -> None:
    """Verify lag 1, lag 2, and rolling window computations."""
    base_date = date(2026, 8, 20)

    # Populate 10 days of historical weather daily data
    for i in range(10):
        d = base_date - timedelta(days=i)
        record = WeatherDaily(
            date=d,
            station="Hong Kong Observatory",
            max_temperature=30.0 + i,  # 30.0 on base_date, 31.0 on base-1, etc.
            min_temperature=25.0,
            mean_temperature=27.5,
            total_rainfall=1.0,
        )
        db_session.add(record)
    db_session.commit()

    lag_feats = FeaturePipeline.extract_historical_lag_features(db_session, as_of_date=base_date)

    assert lag_feats["max_temp_lag1"] == 30.0
    assert lag_feats["max_temp_lag2"] == 31.0
    assert lag_feats["min_temp_lag1"] == 25.0
    assert lag_feats["temp_range_lag1"] == 5.0
    assert lag_feats["rolling_7d_max_temp"] is not None
    # 7-day average: (30 + 31 + 32 + 33 + 34 + 35 + 36) / 7 = 33.0
    assert round(lag_feats["rolling_7d_max_temp"], 1) == 33.0


def test_dataset_builder_build_feature_row(db_session: Session) -> None:
    """Verify full feature row assembly with calendar, lag, and forecast features."""
    target_dt = date(2026, 8, 23)
    decision_dt = datetime(2026, 8, 22, 8, 0, tzinfo=UTC)

    # Add historical daily row
    db_session.add(
        WeatherDaily(
            date=date(2026, 8, 21),
            station="Hong Kong Observatory",
            max_temperature=32.5,
            min_temperature=27.0,
            mean_temperature=29.0,
            total_rainfall=0.0,
        )
    )
    # Add forecast row
    db_session.add(
        WeatherForecast(
            forecast_created_at=datetime(2026, 8, 22, 7, 0, tzinfo=UTC),
            target_date=target_dt,
            forecast_max_temperature=33.0,
            forecast_min_temperature=28.0,
            rain_probability=0.35,
            source="hko_9day",
        )
    )
    db_session.commit()

    row = DatasetBuilder.build_feature_row(db_session, target_dt, decision_dt)

    assert row["target_date"] == "2026-08-23"
    assert row["month"] == 8
    assert row["max_temp_lag1"] == 32.5
    assert row["hko_forecast_max_temp"] == 33.0
    assert row["forecast_available"] == 1
    assert row["forecast_revision_count"] == 1
    assert row["lead_days"] == 1


def test_dataset_builder_build_dataset(db_session: Session) -> None:
    """Verify X and y DataFrame and Series generation across dates."""
    dates = [date(2026, 8, 22), date(2026, 8, 23)]

    # Add ground truth daily records
    db_session.add_all(
        [
            WeatherDaily(date=dates[0], station="Hong Kong Observatory", max_temperature=31.8),
            WeatherDaily(date=dates[1], station="Hong Kong Observatory", max_temperature=33.4),
        ]
    )
    db_session.commit()

    df_features, s_target = DatasetBuilder.build_dataset(
        db_session, dates, lead_hours_before_midnight=12
    )

    assert len(df_features) == 2
    assert len(s_target) == 2
    assert s_target.iloc[0] == 31.8
    assert s_target.iloc[1] == 33.4
    assert "sin_day_of_year" in df_features.columns
    assert "hko_forecast_max_temp" in df_features.columns
