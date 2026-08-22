"""System health check and observability monitoring jobs (PLAN.md Section 16 & 27)."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.storage.db import get_db_session
from app.storage.models import WeatherObservation
from app.telegram.client import TelegramClient
from app.telegram.formatter import TelegramFormatter

logger = get_logger("health_job")


def run_health_check_job(
    session: Session | None = None,
    telegram_client: TelegramClient | None = None,
    max_observation_age_hours: int = 4,
) -> dict[str, Any]:
    """Execute end-to-end system health check and alert on critical degradation."""
    logger.info("Executing system health check")
    t_client = telegram_client or TelegramClient()
    now = datetime.now(UTC)

    health_status: dict[str, Any] = {
        "timestamp": now.isoformat(),
        "database_ok": False,
        "database_latency_ms": 0.0,
        "observations_fresh": False,
        "is_healthy": False,
    }

    def _perform_checks(sess: Session) -> None:
        t_start = datetime.now(UTC)
        sess.execute(select(1))
        latency = (datetime.now(UTC) - t_start).total_seconds() * 1000.0
        health_status["database_ok"] = True
        health_status["database_latency_ms"] = round(latency, 2)

        latest_obs = sess.scalars(
            select(WeatherObservation).order_by(WeatherObservation.observed_at.desc())
        ).first()

        if latest_obs and latest_obs.observed_at:
            obs_ts = (
                latest_obs.observed_at
                if latest_obs.observed_at.tzinfo is not None
                else latest_obs.observed_at.replace(tzinfo=UTC)
            )
            age_hours = (now - obs_ts).total_seconds() / 3600.0
            health_status["observations_fresh"] = age_hours <= max_observation_age_hours
            health_status["last_observation_age_hours"] = round(age_hours, 2)

    try:
        if session is not None:
            _perform_checks(session)
        else:
            with get_db_session() as db_sess:
                _perform_checks(db_sess)
    except Exception as exc:
        logger.error("Health check failed on database query", error=str(exc))
        health_status["database_error"] = str(exc)
        asyncio.run(
            t_client.send_message(TelegramFormatter.format_health_alert("Database", str(exc)))
        )
        return health_status

    health_status["is_healthy"] = bool(health_status["database_ok"])
    logger.info("Health check complete", is_healthy=health_status["is_healthy"])
    return health_status
