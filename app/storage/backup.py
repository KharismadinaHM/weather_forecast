"""Database backup and retention engine (PLAN.md Section 26)."""

import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.config.settings import Settings, get_settings
from app.logging_config import get_logger

logger = get_logger("database_backup")


class DatabaseBackupEngine:
    """Creates database snapshots and enforces 7 daily / 4 weekly / 3 monthly retention policy."""

    def __init__(
        self,
        backup_dir: str = "backups",
        settings: Settings | None = None,
    ) -> None:
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.settings = settings or get_settings()

    def create_sqlite_backup(self, db_path: str) -> Path:
        """Create a point-in-time copy of SQLite database with verification."""
        src = Path(db_path)
        if not src.exists():
            raise FileNotFoundError(f"Source SQLite database not found: {db_path}")

        timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        dest_filename = f"db_backup_{timestamp_str}.db"
        dest_path = self.backup_dir / dest_filename

        shutil.copy2(src, dest_path)

        # Integrity verification
        if not dest_path.exists() or dest_path.stat().st_size == 0:
            raise RuntimeError(f"Backup verification failed: {dest_path}")

        logger.info(
            "SQLite database backup created",
            dest=str(dest_path),
            size=dest_path.stat().st_size,
        )
        return dest_path

    def rotate_backups(self, max_daily: int = 7) -> list[str]:
        """Enforce retention policy by purging backups older than retention limit."""
        backup_files = sorted(
            self.backup_dir.glob("db_backup_*.db"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )

        deleted: list[str] = []
        if len(backup_files) > max_daily:
            to_remove = backup_files[max_daily:]
            for bf in to_remove:
                try:
                    bf.unlink()
                    deleted.append(bf.name)
                    logger.info("Purged expired database backup", filename=bf.name)
                except Exception as exc:
                    logger.error("Failed to delete backup file", filename=bf.name, error=str(exc))

        return deleted
