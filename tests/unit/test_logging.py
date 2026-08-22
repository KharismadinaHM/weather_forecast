"""Unit tests for structured logging."""

from app.logging_config import get_logger, setup_logging


def test_logging_configuration_development() -> None:
    """Test logger initialization in development mode."""
    setup_logging(environment="development", log_level="DEBUG")
    logger = get_logger("test_dev")
    assert logger is not None
    # Ensure call does not throw
    logger.info("Test development log message", extra_field="value")


def test_logging_configuration_production() -> None:
    """Test logger initialization in production mode."""
    setup_logging(environment="production", log_level="INFO")
    logger = get_logger("test_prod")
    assert logger is not None
    # Ensure call does not throw
    logger.info("Test production JSON log message", metric=100)
