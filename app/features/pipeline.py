"""Feature extraction pipeline for calendar, atmospheric lags, and rolling aggregates."""

import math
from datetime import date, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.storage.models import WeatherDaily


class FeaturePipeline:
    """Feature engineering pipeline for temperature prediction models."""

    AUTHORITATIVE_STATION: str = "Hong Kong Observatory"

    @classmethod
    def extract_calendar_features(cls, target_date: date) -> dict[str, Any]:
        """Extract cyclical and calendar time features for a target date."""
        day_of_year = target_date.timetuple().tm_yday
        day_of_week = target_date.weekday()
        month = target_date.month

        # Cyclical transforms (period 365.25 days)
        angle = 2.0 * math.pi * (day_of_year - 1) / 365.25
        sin_doy = math.sin(angle)
        cos_doy = math.cos(angle)

        return {
            "month": month,
            "day_of_year": day_of_year,
            "day_of_week": day_of_week,
            "is_weekend": 1 if day_of_week >= 5 else 0,
            "sin_day_of_year": float(sin_doy),
            "cos_day_of_year": float(cos_doy),
        }

    @classmethod
    def extract_historical_lag_features(
        cls,
        session: Session,
        as_of_date: date,
        station: str | None = None,
    ) -> dict[str, Any]:
        """Compute lag and rolling window features strictly on or before as_of_date.

        ANTI-LEAKAGE RULE (Section 8):
        When predicting for target_date T, as_of_date must be <= T - 1 day so that
        the target day's actual outcome is NEVER included in historical aggregates.
        """
        station_name = station or cls.AUTHORITATIVE_STATION

        # Fetch up to 30 past daily records strictly <= as_of_date
        cutoff_30d = as_of_date - timedelta(days=35)
        stmt = (
            select(WeatherDaily)
            .where(
                WeatherDaily.station == station_name,
                WeatherDaily.date <= as_of_date,
                WeatherDaily.date >= cutoff_30d,
            )
            .order_by(WeatherDaily.date.desc())
        )
        records = session.scalars(stmt).all()

        if not records:
            return {
                "max_temp_lag1": None,
                "max_temp_lag2": None,
                "min_temp_lag1": None,
                "mean_temp_lag1": None,
                "rainfall_lag1": None,
                "temp_range_lag1": None,
                "rolling_7d_max_temp": None,
                "rolling_30d_max_temp": None,
                "rolling_7d_rainfall": None,
            }

        # Map records by date for accurate lag lookups
        rec_by_date = {r.date: r for r in records}

        # Lag 1: as_of_date
        r_lag1 = rec_by_date.get(as_of_date)
        max_lag1 = r_lag1.max_temperature if r_lag1 else records[0].max_temperature
        min_lag1 = r_lag1.min_temperature if r_lag1 else records[0].min_temperature
        mean_lag1 = r_lag1.mean_temperature if r_lag1 else records[0].mean_temperature
        rain_lag1 = r_lag1.total_rainfall if r_lag1 else records[0].total_rainfall

        temp_range_lag1 = (
            (max_lag1 - min_lag1) if (max_lag1 is not None and min_lag1 is not None) else None
        )

        # Lag 2: as_of_date - 1 day
        date_lag2 = as_of_date - timedelta(days=1)
        r_lag2 = rec_by_date.get(date_lag2)
        max_lag2 = (
            r_lag2.max_temperature
            if r_lag2
            else (records[1].max_temperature if len(records) > 1 else None)
        )

        # Rolling aggregates
        max_temps_7d = [r.max_temperature for r in records[:7] if r.max_temperature is not None]
        max_temps_30d = [r.max_temperature for r in records[:30] if r.max_temperature is not None]
        rain_7d = [r.total_rainfall for r in records[:7] if r.total_rainfall is not None]

        rolling_7d_max = float(np.mean(max_temps_7d)) if max_temps_7d else None
        rolling_30d_max = float(np.mean(max_temps_30d)) if max_temps_30d else None
        rolling_7d_rain = float(np.sum(rain_7d)) if rain_7d else None

        return {
            "max_temp_lag1": max_lag1,
            "max_temp_lag2": max_lag2,
            "min_temp_lag1": min_lag1,
            "mean_temp_lag1": mean_lag1,
            "rainfall_lag1": rain_lag1,
            "temp_range_lag1": temp_range_lag1,
            "rolling_7d_max_temp": rolling_7d_max,
            "rolling_30d_max_temp": rolling_30d_max,
            "rolling_7d_rainfall": rolling_7d_rain,
        }
