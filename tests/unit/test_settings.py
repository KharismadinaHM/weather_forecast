"""Unit tests for application settings."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def test_settings_default_values() -> None:
    """Test default settings and URL building when DATABASE_URL is not explicitly set."""
    settings = Settings(
        POSTGRES_USER="test_user",
        POSTGRES_PASSWORD="test_password",
        POSTGRES_DB="test_db",
        DATABASE_URL=None,
    )
    assert settings.ENVIRONMENT == "development"
    assert settings.LOG_LEVEL == "INFO"
    expected_url = "postgresql+psycopg://test_user:test_password@localhost:5432/test_db"
    assert settings.sync_database_url == expected_url


def test_settings_custom_database_url() -> None:
    """Test custom DATABASE_URL handling with driver replacement."""
    settings = Settings(
        DATABASE_URL="postgresql://user:pass@remote:5432/custom_db",
    )
    assert settings.sync_database_url == "postgresql+psycopg://user:pass@remote:5432/custom_db"


def test_settings_invalid_environment() -> None:
    """Test that invalid environment value raises ValidationError."""
    invalid_data: dict[str, Any] = {"ENVIRONMENT": "invalid_env"}
    with pytest.raises(ValidationError):
        Settings(**invalid_data)


def test_settings_invalid_log_level() -> None:
    """Test that invalid log level raises ValidationError."""
    invalid_data: dict[str, Any] = {"LOG_LEVEL": "VERBOSE"}
    with pytest.raises(ValidationError):
        Settings(**invalid_data)
