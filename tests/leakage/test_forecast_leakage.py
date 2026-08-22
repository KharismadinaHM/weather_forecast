"""Anti-data-leakage verification tests for weather forecasts (PLAN.md Section 8).

Guarantees:
1. Forecast revisions for the same target date are preserved across time and NEVER overwritten.
2. Point-in-time queries (forecast_created_at <= decision_timestamp) return ONLY forecasts
   available at the moment of decision, eliminating lookahead leakage.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.collectors.hko import HKOCollector
from app.storage.models import WeatherForecast


def test_forecast_revisions_are_preserved_without_overwriting(db_session: Session) -> None:
    """Verify morning and afternoon forecast revisions for target date are both retained."""
    collector = HKOCollector()

    # Morning Forecast issued at 07:00 HKT (23:00 UTC previous day)
    morning_payload: dict[str, Any] = {
        "updateTime": "2026-08-22T07:00:00+08:00",
        "weatherForecast": [
            {
                "forecastDate": "20260823",
                "forecastMaxtemp": {"value": 31, "unit": "C"},
                "forecastMintemp": {"value": 26, "unit": "C"},
                "PSR": "Medium",
            }
        ],
    }

    # Afternoon Revised Forecast issued at 16:30 HKT
    afternoon_payload: dict[str, Any] = {
        "updateTime": "2026-08-22T16:30:00+08:00",
        "weatherForecast": [
            {
                "forecastDate": "20260823",
                "forecastMaxtemp": {"value": 33, "unit": "C"},  # Temperature revised upward
                "forecastMintemp": {"value": 27, "unit": "C"},
                "PSR": "High",
            }
        ],
    }

    # Ingest morning forecast
    collector.ingest_9day_forecast(db_session, morning_payload, archive_raw=False)
    assert db_session.query(WeatherForecast).filter_by(target_date=date(2026, 8, 23)).count() == 1

    # Ingest afternoon revised forecast
    collector.ingest_9day_forecast(db_session, afternoon_payload, archive_raw=False)

    # Both revisions MUST exist in database
    all_revisions = (
        db_session.query(WeatherForecast)
        .filter_by(target_date=date(2026, 8, 23))
        .order_by(WeatherForecast.forecast_created_at.asc())
        .all()
    )
    assert len(all_revisions) == 2
    assert all_revisions[0].forecast_max_temperature == 31.0  # Morning
    assert all_revisions[1].forecast_max_temperature == 33.0  # Afternoon


def test_point_in_time_forecast_query_prevents_leakage(db_session: Session) -> None:
    """Verify decision at 12:00 HKT only accesses morning forecast, not future 16:30 revision."""
    collector = HKOCollector()

    morning_payload: dict[str, Any] = {
        "updateTime": "2026-08-22T07:00:00+08:00",
        "weatherForecast": [
            {
                "forecastDate": "20260823",
                "forecastMaxtemp": {"value": 31, "unit": "C"},
                "forecastMintemp": {"value": 26, "unit": "C"},
                "PSR": "Medium",
            }
        ],
    }
    afternoon_payload: dict[str, Any] = {
        "updateTime": "2026-08-22T16:30:00+08:00",
        "weatherForecast": [
            {
                "forecastDate": "20260823",
                "forecastMaxtemp": {"value": 33, "unit": "C"},
                "forecastMintemp": {"value": 27, "unit": "C"},
                "PSR": "High",
            }
        ],
    }

    collector.ingest_9day_forecast(db_session, morning_payload, archive_raw=False)
    collector.ingest_9day_forecast(db_session, afternoon_payload, archive_raw=False)

    # Simulate decision timestamp at 12:00 HKT (04:00 UTC)
    decision_timestamp = datetime.fromisoformat("2026-08-22T12:00:00+08:00")

    # Query latest available forecast at or before decision timestamp
    latest_known_forecast = (
        db_session.query(WeatherForecast)
        .filter(
            WeatherForecast.target_date == date(2026, 8, 23),
            WeatherForecast.forecast_created_at <= decision_timestamp,
        )
        .order_by(WeatherForecast.forecast_created_at.desc())
        .first()
    )

    assert latest_known_forecast is not None
    # Crucial anti-leakage assertion: MUST be 31°C (morning), NOT 33°C (afternoon revision)
    assert latest_known_forecast.forecast_max_temperature == 31.0
