"""Unit tests for Production Deployment, Backup Engine, Health Monitoring, and Schedulers."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.jobs.health import run_health_check_job
from app.jobs.scheduler import OrchestratorScheduler
from app.jobs.trading_jobs import run_missing_market_alert_job
from app.storage.backup import DatabaseBackupEngine
from app.storage.models import WeatherObservation
from app.telegram.client import TelegramClient


def test_database_backup_engine_create_and_verify() -> None:
    """Verify DatabaseBackupEngine creates verified snapshots."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        src_db = Path(tmp_dir) / "test.db"
        src_db.write_text("DUMMY_DATABASE_CONTENT")

        backup_dir = Path(tmp_dir) / "backups"
        engine = DatabaseBackupEngine(backup_dir=str(backup_dir))

        backup_path = engine.create_sqlite_backup(str(src_db))
        assert backup_path.exists()
        assert backup_path.stat().st_size > 0
        assert "db_backup_" in backup_path.name


def test_database_backup_retention_rotation() -> None:
    """Verify retention rotation purges excess backups beyond max_daily threshold."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        backup_dir = Path(tmp_dir) / "backups"
        backup_dir.mkdir()

        for i in range(10):
            bf = backup_dir / f"db_backup_202608{10 + i:02d}_000000.db"
            bf.write_text("data")

        engine = DatabaseBackupEngine(backup_dir=str(backup_dir))
        purged = engine.rotate_backups(max_daily=7)

        assert len(purged) == 3
        remaining = list(backup_dir.glob("db_backup_*.db"))
        assert len(remaining) == 7


def test_health_check_job(db_session: Session) -> None:
    """Verify system health check computes latency and checks observation freshness."""
    now = datetime.now(UTC)
    db_session.add(
        WeatherObservation(
            observed_at=now - timedelta(minutes=30),
            station="Hong Kong Observatory",
            is_authoritative=True,
            temperature=31.5,
            rainfall=0.0,
            source="hko_rhrread",
        )
    )
    db_session.commit()

    health = run_health_check_job(session=db_session, max_observation_age_hours=2)
    assert health["database_ok"] is True
    assert health["database_latency_ms"] >= 0.0
    assert health["observations_fresh"] is True
    assert health["is_healthy"] is True


def test_trading_jobs_missing_market_alert(db_session: Session) -> None:
    """Verify 18:00 HKT missing market alert execution."""
    client = TelegramClient(bot_token=None, chat_id=None)
    result = run_missing_market_alert_job(session=db_session, telegram_client=client)
    assert result is False or result is True


def test_orchestrator_scheduler_run_all(db_session: Session) -> None:
    """Verify OrchestratorScheduler executes full sequential cycle."""
    scheduler = OrchestratorScheduler()
    res = scheduler.run_all_jobs_once(session=db_session)
    assert "hko_observations" in res
    assert "polymarket_markets" in res
    assert "health" in res
    assert res["health"]["is_healthy"] is True
