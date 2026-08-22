"""Polymarket Scheduled Ingestion and Market Discovery Jobs."""

from datetime import UTC, datetime, timedelta

from app.collectors.polymarket import PolymarketCollector
from app.logging_config import get_logger
from app.storage.db import get_db_session

logger = get_logger("polymarket_jobs")


def run_polymarket_discovery_and_prices_job() -> tuple[int, int, int]:
    """Execute high-frequency market discovery and price snapshot collection."""
    logger.info("Starting Polymarket discovery and price ingestion job")
    collector = PolymarketCollector()

    # 1. Check for upcoming market coverage (next 3 days)
    today = datetime.now(UTC).date()
    target_dates = [today + timedelta(days=i) for i in range(1, 4)]
    collector.check_missing_markets(target_dates)

    # 2. Ingest markets, outcomes, and current price snapshots
    with get_db_session() as session:
        markets_cnt, outcomes_cnt, prices_cnt = collector.ingest_markets_and_prices(session)

    logger.info(
        "Completed Polymarket job",
        new_markets=markets_cnt,
        new_outcomes=outcomes_cnt,
        new_prices=prices_cnt,
    )
    return markets_cnt, outcomes_cnt, prices_cnt


if __name__ == "__main__":
    run_polymarket_discovery_and_prices_job()
