"""SQLAlchemy ORM models defining the database schema."""

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.storage.db import Base


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(UTC)


class WeatherObservation(Base):
    """Hourly and ad-hoc observed weather actuals."""

    __tablename__ = "weather_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    station: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    is_authoritative: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    rainfall: Mapped[float | None] = mapped_column(Float, nullable=True)
    pressure: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_direction: Mapped[str | None] = mapped_column(String(50), nullable=True)
    weather_condition: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="hko", nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("observed_at", "station", name="uq_weather_obs_time_station"),
        Index("ix_weather_obs_authoritative_time", "is_authoritative", "observed_at"),
    )


class WeatherDaily(Base):
    """Daily aggregated weather summaries (ground truth targets)."""

    __tablename__ = "weather_daily"

    date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False)
    station: Mapped[str] = mapped_column(String(100), primary_key=True, nullable=False)
    max_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_rainfall: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (Index("ix_weather_daily_date", "date"),)


class WeatherForecast(Base):
    """Historical and live forecasts with explicit creation and target timestamps (anti-leakage)."""

    __tablename__ = "weather_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    forecast_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    target_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    target_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forecast_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_min_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_max_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    rain_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="hko_9day", nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "forecast_created_at", "target_date", "source", name="uq_forecast_created_target_src"
        ),
        Index("ix_forecast_target_created", "target_date", "forecast_created_at"),
    )


class PolymarketMarket(Base):
    """Polymarket prediction market metadata and bucket specifications."""

    __tablename__ = "polymarket_markets"

    market_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    market_type: Mapped[str] = mapped_column(String(50), default="temperature_high", nullable=False)
    outcome_bucket_schema: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    target_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(50), default="temperature_celsius", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False, index=True)
    resolution_source_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    outcomes: Mapped[list["PolymarketOutcome"]] = relationship(
        "PolymarketOutcome",
        back_populates="market",
        cascade="all, delete-orphan",
    )
    prices: Mapped[list["PolymarketPrice"]] = relationship(
        "PolymarketPrice",
        back_populates="market",
        cascade="all, delete-orphan",
    )

    __table_args__ = (Index("ix_poly_market_target_status", "target_date", "status"),)


class PolymarketOutcome(Base):
    """Specific outcome tokens / temperature bucket definitions for a market."""

    __tablename__ = "polymarket_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("polymarket_markets.market_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    outcome_label: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome_bucket_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_bucket_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_value: Mapped[str | None] = mapped_column(String(50), nullable=True)

    market: Mapped["PolymarketMarket"] = relationship("PolymarketMarket", back_populates="outcomes")

    __table_args__ = (
        UniqueConstraint("market_id", "token_id", name="uq_poly_outcome_market_token"),
    )


class PolymarketPrice(Base):
    """Time-series orderbook prices for Polymarket tokens."""

    __tablename__ = "polymarket_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("polymarket_markets.market_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    side: Mapped[str | None] = mapped_column(String(10), nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    market: Mapped["PolymarketMarket"] = relationship("PolymarketMarket", back_populates="prices")

    __table_args__ = (
        Index("ix_poly_prices_market_token_ts", "market_id", "token_id", "timestamp"),
    )


class Prediction(Base):
    """Model-generated probabilities and edge calculations against market."""

    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("polymarket_markets.market_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prediction_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    model_version: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(100), nullable=False)
    model_probability: Mapped[float] = mapped_column(Float, nullable=False)
    market_probability: Mapped[float] = mapped_column(Float, nullable=False)
    edge: Mapped[float] = mapped_column(Float, nullable=False)
    expected_value: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    signals: Mapped[list["Signal"]] = relationship(
        "Signal", back_populates="prediction", cascade="all, delete-orphan"
    )


class Signal(Base):
    """Risk engine decisions evaluated on top of model predictions."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prediction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("predictions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)  # BUY, SELL, HOLD, SKIP
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommended_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    prediction: Mapped["Prediction"] = relationship("Prediction", back_populates="signals")
    trades: Mapped[list["PaperTrade"]] = relationship(
        "PaperTrade", back_populates="signal", cascade="all, delete-orphan"
    )


class PaperTrade(Base):
    """Paper execution simulation records and PnL tracking."""

    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("signals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    position_size: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    fees: Mapped[float | None] = mapped_column(Float, nullable=True)
    slippage: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), default="OPEN", nullable=False, index=True
    )  # OPEN, CLOSED, CANCELLED
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    signal: Mapped["Signal"] = relationship("Signal", back_populates="trades")


class ModelRun(Base):
    """Metadata and calibration evaluation records for model candidates."""

    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    training_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    training_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validation_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validation_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    test_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    test_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    brier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    log_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibration_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    rmse: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
