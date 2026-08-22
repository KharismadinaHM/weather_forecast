"""HKO Scheduled Ingestion Job Runners."""

from app.collectors.hko import HKOCollector
from app.logging_config import get_logger
from app.storage.db import get_db_session

logger = get_logger("hko_jobs")


def run_hko_observations_job() -> int:
    """Run hourly HKO current weather observations ingestion."""
    logger.info("Starting HKO current observations job")
    collector = HKOCollector()
    with get_db_session() as session:
        count = collector.ingest_current_observations(session)
    logger.info("Completed HKO current observations job", inserted_count=count)
    return count


def run_hko_forecast_job() -> int:
    """Run HKO 9-day forecast ingestion with change detection."""
    logger.info("Starting HKO 9-day forecast job")
    collector = HKOCollector()
    with get_db_session() as session:
        count = collector.ingest_9day_forecast(session)
    logger.info("Completed HKO 9-day forecast job", inserted_count=count)
    return count


if __name__ == "__main__":
    import sys

    job_type = sys.argv[1] if len(sys.argv) > 1 else "all"
    if job_type == "observations":
        run_hko_observations_job()
    elif job_type == "forecast":
        run_hko_forecast_job()
    else:
        run_hko_observations_job()
        run_hko_forecast_job()
