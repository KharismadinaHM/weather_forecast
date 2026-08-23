"""Unified job scheduler and orchestrator (PLAN.md Section 15 & 27)."""

from typing import Any

from sqlalchemy.orm import Session

from app.jobs.health import run_health_check_job
from app.jobs.hko_jobs import run_hko_forecast_job, run_hko_observations_job
from app.jobs.polymarket_jobs import run_polymarket_discovery_and_prices_job
from app.jobs.trading_jobs import (
    run_prediction_and_signals_job,
)
from app.logging_config import get_logger

logger = get_logger("orchestrator_scheduler")


class OrchestratorScheduler:
    """Coordinates periodic data collection, prediction pipelines, and alert schedules."""

    def run_all_jobs_once(self, session: Session | None = None) -> dict[str, Any]:
        """Execute a full sequential cycle across all pipelines (useful for testing and cron)."""
        logger.info("Executing comprehensive orchestration cycle")
        results: dict[str, Any] = {}

        # 1. HKO Observations & Forecast
        try:
            obs_cnt = run_hko_observations_job() if session is None else 0
            fc_cnt = run_hko_forecast_job() if session is None else 0
            results["hko_observations"] = obs_cnt
            results["hko_forecast"] = fc_cnt
        except Exception as exc:
            logger.error("HKO job execution failed", error=str(exc))
            results["hko_error"] = str(exc)

        # 2. Polymarket Discovery & Prices
        try:
            m_cnt, o_cnt, p_cnt = (
                run_polymarket_discovery_and_prices_job() if session is None else (0, 0, 0)
            )
            results["polymarket_markets"] = m_cnt
            results["polymarket_prices"] = p_cnt
        except Exception as exc:
            logger.error("Polymarket job execution failed", error=str(exc))
            results["polymarket_error"] = str(exc)

        # 3. Model Prediction & Signal Generation
        try:
            sig_cnt = run_prediction_and_signals_job(session=session)
            results["signals_generated"] = sig_cnt
        except Exception as exc:
            logger.error("Trading signal job execution failed", error=str(exc))
            results["signal_error"] = str(exc)

        # 4. System Health Check
        try:
            health = run_health_check_job(session=session)
            results["health"] = health
        except Exception as exc:
            logger.error("Health check execution failed", error=str(exc))
            results["health_error"] = str(exc)

        logger.info("Orchestration cycle complete", results=results)
        return results

    def start_daemon(self, interval_seconds: int = 900) -> None:
        """Run continuous background loop fetching data periodically (PLAN.md Section 15)."""
        import time

        logger.info(
            "Starting automated background scheduler daemon",
            interval_seconds=interval_seconds,
            interval_minutes=interval_seconds / 60.0,
        )
        while True:
            try:
                self.run_all_jobs_once()
            except Exception as exc:
                logger.error("Daemon cycle encountered error", error=str(exc))
            time.sleep(interval_seconds)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Hong Kong Weather Trading Orchestrator")
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously as background daemon every N seconds",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=900,
        help="Daemon interval in seconds (default: 900s / 15 minutes)",
    )
    args = parser.parse_args()

    scheduler = OrchestratorScheduler()
    if args.daemon:
        scheduler.start_daemon(interval_seconds=args.interval)
    else:
        scheduler.run_all_jobs_once()
