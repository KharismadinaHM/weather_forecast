"""Raw data storage helper for preserving immutable API responses."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.logging_config import get_logger

logger = get_logger("raw_storage")


def save_raw_response(
    source: str,
    endpoint: str,
    data: dict[str, Any] | list[Any],
    base_dir: str = "data/raw",
) -> Path:
    """Save raw response as JSON to persistent directory for reproducibility."""
    now = datetime.now(UTC)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%Y%m%d_%H%M%S_%f")

    target_dir = Path(base_dir) / source / endpoint / date_str
    target_dir.mkdir(parents=True, exist_ok=True)

    file_path = target_dir / f"{time_str}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.debug("Raw response archived", path=str(file_path), source=source, endpoint=endpoint)
    return file_path
