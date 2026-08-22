"""Derived forecast revision features with anti-leakage point-in-time filtering."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.storage.models import WeatherForecast


def compute_forecast_revision_features(
    session: Session,
    target_date: date,
    decision_timestamp: datetime,
    source: str = "hko_9day",
) -> dict[str, Any]:
    """Compute point-in-time forecast revision features available at decision_timestamp.

    CRITICAL ANTI-LEAKAGE GUARANTEE (Section 8):
    Only forecast records with `forecast_created_at <= decision_timestamp` are queried.
    Future revisions created after `decision_timestamp` are completely inaccessible.
    """
    stmt = (
        select(WeatherForecast)
        .where(
            WeatherForecast.target_date == target_date,
            WeatherForecast.source == source,
            WeatherForecast.forecast_created_at <= decision_timestamp,
        )
        .order_by(WeatherForecast.forecast_created_at.asc())
    )
    revisions = session.scalars(stmt).all()

    revision_count = len(revisions)
    lead_days = (target_date - decision_timestamp.date()).days

    if revision_count == 0:
        return {
            "forecast_available": 0,
            "forecast_revision_count": 0,
            "forecast_revision_delta": 0.0,
            "hko_forecast_max_temp": None,
            "hko_forecast_min_temp": None,
            "hko_forecast_rain_prob": None,
            "hko_forecast_humidity": None,
            "lead_days": lead_days,
        }

    first_rev = revisions[0]
    latest_rev = revisions[-1]

    # Calculate revision shift
    init_max_t = first_rev.forecast_max_temperature or 0.0
    latest_max_t = latest_rev.forecast_max_temperature or 0.0
    revision_delta = (latest_max_t - init_max_t) if revision_count >= 2 else 0.0

    return {
        "forecast_available": 1,
        "forecast_revision_count": revision_count,
        "forecast_revision_delta": float(revision_delta),
        "hko_forecast_max_temp": latest_rev.forecast_max_temperature,
        "hko_forecast_min_temp": latest_rev.forecast_min_temperature,
        "hko_forecast_rain_prob": latest_rev.rain_probability or 0.0,
        "hko_forecast_humidity": latest_rev.humidity,
        "lead_days": lead_days,
    }
