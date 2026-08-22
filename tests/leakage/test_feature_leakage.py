"""Dedicated anti-data-leakage test suite for raw and derived features (PLAN.md Section 8).

Strict rules tested:
1. No actual observation from target_date T is ever present in input feature matrix X.
2. Derived features (forecast_revision_count, forecast_revision_delta) do NOT leak future revisions.
3. Historical rolling windows strictly exclude target_date T.
"""

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.features.builder import DatasetBuilder
from app.features.derived import compute_forecast_revision_features
from app.features.pipeline import FeaturePipeline
from app.storage.models import WeatherDaily, WeatherForecast


def test_raw_target_observation_never_in_features(db_session: Session) -> None:
    """Verify target date's actual observation is excluded from lag and rolling features."""
    target_dt = date(2026, 8, 23)
    decision_dt = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)

    # Insert historical actuals for day before AND for the target day itself
    day_before = WeatherDaily(
        date=date(2026, 8, 22),
        station="Hong Kong Observatory",
        max_temperature=31.0,
        min_temperature=26.0,
        mean_temperature=28.5,
        total_rainfall=0.0,
    )
    target_day_actual = WeatherDaily(
        date=date(2026, 8, 23),
        station="Hong Kong Observatory",
        max_temperature=36.0,  # Extreme temperature that happened on target day!
        min_temperature=29.0,
        mean_temperature=32.0,
        total_rainfall=50.0,
    )
    db_session.add_all([day_before, target_day_actual])
    db_session.commit()

    # Build feature row for target date
    feature_row = DatasetBuilder.build_feature_row(db_session, target_dt, decision_dt)

    # CRITICAL ASSERTION: max_temp_lag1 must be 31.0 (from Aug 22), NEVER 36.0 (Aug 23)
    assert feature_row["max_temp_lag1"] == 31.0
    assert feature_row["max_temp_lag1"] != 36.0
    assert feature_row["rainfall_lag1"] == 0.0
    assert feature_row["rainfall_lag1"] != 50.0


def test_derived_forecast_revision_leakage(db_session: Session) -> None:
    """Verify revision count and delta exclude revisions published after decision_timestamp."""
    target_dt = date(2026, 8, 23)

    # Revision 1: 2 days before (Aug 21 07:00 HKT / Aug 20 23:00 UTC)
    rev1 = WeatherForecast(
        forecast_created_at=datetime(2026, 8, 20, 23, 0, tzinfo=UTC),
        target_date=target_dt,
        forecast_max_temperature=30.0,
        source="hko_9day",
    )
    # Revision 2: 1 day before morning (Aug 22 07:00 HKT / Aug 21 23:00 UTC)
    rev2 = WeatherForecast(
        forecast_created_at=datetime(2026, 8, 21, 23, 0, tzinfo=UTC),
        target_date=target_dt,
        forecast_max_temperature=32.0,
        source="hko_9day",
    )
    # Revision 3: 1 day before afternoon (Aug 22 16:30 HKT / Aug 22 08:30 UTC) - FUTURE REVISION!
    rev3 = WeatherForecast(
        forecast_created_at=datetime(2026, 8, 22, 8, 30, tzinfo=UTC),
        target_date=target_dt,
        forecast_max_temperature=35.0,
        source="hko_9day",
    )
    db_session.add_all([rev1, rev2, rev3])
    db_session.commit()

    # Decision at 08:00 HKT on Aug 22 (00:00 UTC) - between Rev 2 and Rev 3
    decision_dt = datetime(2026, 8, 22, 0, 0, tzinfo=UTC)

    derived = compute_forecast_revision_features(db_session, target_dt, decision_dt)

    # ASSERTION 1: Exactly 2 revisions known at decision time (Rev 1 & Rev 2), NOT 3
    assert derived["forecast_revision_count"] == 2

    # ASSERTION 2: Latest forecast max temperature is 32.0 (Rev 2), NOT 35.0 (future Rev 3)
    assert derived["hko_forecast_max_temp"] == 32.0

    # ASSERTION 3: Revision delta is 32.0 - 30.0 = +2.0, NOT 35.0 - 30.0 = +5.0
    assert derived["forecast_revision_delta"] == 2.0


def test_rolling_window_leakage_exclusion(db_session: Session) -> None:
    """Verify rolling 7-day temperature aggregate strictly uses past days without lookahead."""
    # Insert 10 days of data
    for i in range(1, 11):
        db_session.add(
            WeatherDaily(
                date=date(2026, 8, i),
                station="Hong Kong Observatory",
                max_temperature=float(i),  # Aug 1=1.0, Aug 2=2.0 ... Aug 10=10.0
            )
        )
    db_session.commit()

    # Compute as of Aug 7 (must use Aug 1 to Aug 7)
    lag_feats_aug7 = FeaturePipeline.extract_historical_lag_features(
        db_session, as_of_date=date(2026, 8, 7)
    )
    # Aug 1..7 max temps = 1+2+3+4+5+6+7 = 28 / 7 = 4.0
    assert lag_feats_aug7["max_temp_lag1"] == 7.0
    assert lag_feats_aug7["rolling_7d_max_temp"] == 4.0
    # Make sure subsequent days (Aug 8=8.0, Aug 9=9.0, Aug 10=10.0) did NOT leak
    assert lag_feats_aug7["max_temp_lag1"] < 8.0
