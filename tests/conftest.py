"""Pytest configuration and shared test fixtures."""

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config.settings import Settings
from app.storage.db import Base


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Fixture providing test configuration."""
    return Settings(
        ENVIRONMENT="testing",
        LOG_LEVEL="DEBUG",
        POSTGRES_DB="test_hk_weather",
        POSTGRES_USER="test_user",
        POSTGRES_PASSWORD="test_password",
        DATABASE_URL="sqlite:///:memory:",
    )


@pytest.fixture
def db_engine() -> Generator[Engine, None, None]:
    """Provide an in-memory SQLite engine with all schema tables created."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Generator[Session, None, None]:
    """Provide a clean database session for each test."""
    session_factory = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
