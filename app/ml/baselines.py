"""Baseline forecasting models (PLAN.md Section 9.2).

Priority order:
1. Climatology (historical calendar day averages)
2. HKO Official Forecast (the primary benchmark to beat)
3. Persistence (yesterday's observed temperature sanity check)
"""

import math
from collections.abc import Sequence
from datetime import date
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.bucket_parser import ParsedBucket
from app.features.pipeline import FeaturePipeline
from app.ml.distribution import ContinuousToBucketMapper
from app.storage.models import WeatherDaily


class ClimatologyBaseline:
    """Baseline 1: Long-term calendar date seasonal climatology mean and standard deviation."""

    def __init__(self) -> None:
        # Map (month, day) -> (mean, std)
        self.date_stats: dict[tuple[int, int], tuple[float, float]] = {}
        self.global_mean: float = 27.5
        self.global_std: float = 4.0

    def fit(self, session: Session, min_years: int = 1) -> "ClimatologyBaseline":
        """Fit climatology statistics on historical WeatherDaily table."""
        stmt = select(WeatherDaily.date, WeatherDaily.max_temperature).where(
            WeatherDaily.station == FeaturePipeline.AUTHORITATIVE_STATION,
            WeatherDaily.max_temperature.isnot(None),
        )
        records = session.execute(stmt).all()
        if not records:
            return self

        temps_by_cal_day: dict[tuple[int, int], list[float]] = {}
        all_temps: list[float] = []

        for d_val, t_val in records:
            if t_val is not None and d_val is not None:
                key = (d_val.month, d_val.day)
                temps_by_cal_day.setdefault(key, []).append(float(t_val))
                all_temps.append(float(t_val))

        if all_temps:
            self.global_mean = float(np.mean(all_temps))
            self.global_std = float(np.std(all_temps)) or 3.5

        for (m, d), t_list in temps_by_cal_day.items():
            if len(t_list) >= min_years:
                mean_v = float(np.mean(t_list))
                std_v = float(np.std(t_list)) if len(t_list) > 1 else self.global_std
                self.date_stats[(m, d)] = (mean_v, std_v or 2.0)

        return self

    def predict_continuous(self, target_date: date) -> tuple[float, float]:
        """Return predicted (mean, std) for the target date."""
        key = (target_date.month, target_date.day)
        return self.date_stats.get(key, (self.global_mean, self.global_std))

    def predict_buckets(
        self,
        target_date: date,
        buckets: Sequence[ParsedBucket],
    ) -> dict[str, float]:
        """Generate discrete probability distribution across outcome buckets."""
        mean, std = self.predict_continuous(target_date)
        return ContinuousToBucketMapper.map_distribution_to_buckets(buckets, mean, std)


class PersistenceBaseline:
    """Baseline 3: Persistence model (predicts yesterday's max temperature)."""

    DEFAULT_ERROR_STD: float = 2.2

    def __init__(self, error_std: float = DEFAULT_ERROR_STD) -> None:
        self.error_std = error_std

    def predict_continuous(self, feature_row: dict[str, Any]) -> tuple[float, float]:
        """Extract max_temp_lag1 as predicted mean."""
        lag1 = feature_row.get("max_temp_lag1")
        if lag1 is not None and not math.isnan(lag1):
            return float(lag1), self.error_std
        # Fallback
        return 28.0, self.error_std

    def predict_buckets(
        self,
        feature_row: dict[str, Any],
        buckets: Sequence[ParsedBucket],
    ) -> dict[str, float]:
        """Generate discrete probability distribution across outcome buckets."""
        mean, std = self.predict_continuous(feature_row)
        return ContinuousToBucketMapper.map_distribution_to_buckets(buckets, mean, std)


class HKOFailoverBaseline:
    """Baseline 2 (CRITICAL): Official HKO 9-day Weather Forecast with lead-day uncertainty."""

    # Typical empirical standard error for HKO max temperature forecast per lead day (days 1 to 9)
    BASE_ERROR_STD_1D: float = 1.1

    def __init__(self, climatology_fallback: ClimatologyBaseline | None = None) -> None:
        self.climatology = climatology_fallback or ClimatologyBaseline()

    def _estimate_lead_std(self, lead_days: int | None) -> float:
        """Estimate forecast residual standard error based on lead time."""
        ld = lead_days if (lead_days is not None and lead_days >= 1) else 1
        # Uncertainty grows with sqrt of lead days
        return float(self.BASE_ERROR_STD_1D * math.sqrt(ld))

    def predict_continuous(
        self,
        feature_row: dict[str, Any],
        target_date: date | None = None,
    ) -> tuple[float, float]:
        """Predict continuous temperature using official HKO forecast if available."""
        hko_temp = feature_row.get("hko_forecast_max_temp")
        forecast_avail = feature_row.get("forecast_available", 0)
        lead_days = feature_row.get("lead_days")

        if forecast_avail and hko_temp is not None and not math.isnan(hko_temp):
            std = self._estimate_lead_std(int(lead_days) if lead_days is not None else 1)
            return float(hko_temp), std

        # Fallback to climatology if HKO forecast is unavailable
        t_date = target_date
        if t_date is None and "target_date" in feature_row:
            val = feature_row["target_date"]
            if isinstance(val, str):
                try:
                    t_date = date.fromisoformat(val)
                except ValueError:
                    t_date = None
            elif isinstance(val, date):
                t_date = val

        if t_date is not None:
            return self.climatology.predict_continuous(t_date)

        return 28.0, 3.5

    def predict_buckets(
        self,
        feature_row: dict[str, Any],
        buckets: Sequence[ParsedBucket],
        target_date: date | None = None,
    ) -> dict[str, float]:
        """Generate discrete probability distribution across outcome buckets."""
        mean, std = self.predict_continuous(feature_row, target_date)
        return ContinuousToBucketMapper.map_distribution_to_buckets(buckets, mean, std)
