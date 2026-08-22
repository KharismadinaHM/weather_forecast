"""Point-in-time training and inference dataset builder (Section 8 compliant)."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.derived import compute_forecast_revision_features
from app.features.pipeline import FeaturePipeline
from app.storage.models import WeatherDaily

HKT = ZoneInfo("Asia/Hong_Kong")


class DatasetBuilder:
    """Builder for reproducible, point-in-time feature matrices and target labels."""

    @classmethod
    def build_feature_row(
        cls,
        session: Session,
        target_date: date,
        decision_timestamp: datetime,
    ) -> dict[str, Any]:
        """Construct a leak-free feature vector for a specific prediction decision.

        Respects Section 8 anti-leakage rules:
        - Uses local Hong Kong time to determine finalized historical daily observations.
        - Daily observations for target_date T are strictly excluded.
        """
        # Calendar features
        cal_features = FeaturePipeline.extract_calendar_features(target_date)

        # Historical lag & rolling features (strictly before local decision date and target date)
        local_decision_dt = decision_timestamp.astimezone(HKT)
        local_decision_date = local_decision_dt.date()

        as_of_date = min(
            local_decision_date - timedelta(days=1),
            target_date - timedelta(days=1),
        )
        lag_features = FeaturePipeline.extract_historical_lag_features(
            session, as_of_date=as_of_date
        )

        # Forecast & revision features (point-in-time)
        fc_features = compute_forecast_revision_features(session, target_date, decision_timestamp)

        return {
            "target_date": target_date.isoformat(),
            "decision_timestamp": decision_timestamp.isoformat(),
            **cal_features,
            **lag_features,
            **fc_features,
        }

    @classmethod
    def build_dataset(
        cls,
        session: Session,
        target_dates: list[date],
        lead_hours_before_midnight: int = 16,
    ) -> tuple[pd.DataFrame, pd.Series]:
        """Build historical feature matrix and target vector for model evaluation."""
        rows: list[dict[str, Any]] = []
        targets: list[float | None] = []

        for t_date in target_dates:
            target_midnight = datetime(t_date.year, t_date.month, t_date.day, 0, 0, tzinfo=UTC)
            decision_ts = target_midnight - timedelta(hours=lead_hours_before_midnight)

            rows.append(cls.build_feature_row(session, t_date, decision_ts))

            stmt = select(WeatherDaily.max_temperature).where(
                WeatherDaily.station == FeaturePipeline.AUTHORITATIVE_STATION,
                WeatherDaily.date == t_date,
            )
            actual_max_t = session.scalar(stmt)
            targets.append(actual_max_t)

        df_features = pd.DataFrame(rows)
        s_target = pd.Series(targets, name="actual_max_temperature")
        return df_features, s_target
