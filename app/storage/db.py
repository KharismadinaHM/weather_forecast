"""Database connection, engine, and session management."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config.settings import Settings, get_settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""

    pass


def get_engine(settings: Settings | None = None, **kwargs: Any) -> Engine:
    """Create a SQLAlchemy engine configured from settings."""
    if settings is None:
        settings = get_settings()

    url = settings.sync_database_url
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=kwargs.get("pool_size", 5),
        max_overflow=kwargs.get("max_overflow", 10),
        **{k: v for k, v in kwargs.items() if k not in ("pool_size", "max_overflow")},
    )


@contextmanager
def get_db_session(engine: Engine | None = None) -> Generator[Session, None, None]:
    """Provide a transactional database session context."""
    if engine is None:
        engine = get_engine()

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
