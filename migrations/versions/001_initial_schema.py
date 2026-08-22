"""001_initial_schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-08-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. weather_observations
    op.create_table(
        "weather_observations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("station", sa.String(length=100), nullable=False),
        sa.Column(
            "is_authoritative", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("humidity", sa.Float(), nullable=True),
        sa.Column("rainfall", sa.Float(), nullable=True),
        sa.Column("pressure", sa.Float(), nullable=True),
        sa.Column("wind_speed", sa.Float(), nullable=True),
        sa.Column("wind_direction", sa.String(length=50), nullable=True),
        sa.Column("weather_condition", sa.String(length=100), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="hko"),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("observed_at", "station", name="uq_weather_obs_time_station"),
    )
    op.create_index("ix_weather_observations_observed_at", "weather_observations", ["observed_at"])
    op.create_index("ix_weather_observations_station", "weather_observations", ["station"])
    op.create_index(
        "ix_weather_observations_is_authoritative", "weather_observations", ["is_authoritative"]
    )
    op.create_index(
        "ix_weather_obs_authoritative_time",
        "weather_observations",
        ["is_authoritative", "observed_at"],
    )

    # 2. weather_daily
    op.create_table(
        "weather_daily",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("station", sa.String(length=100), nullable=False),
        sa.Column("max_temperature", sa.Float(), nullable=True),
        sa.Column("min_temperature", sa.Float(), nullable=True),
        sa.Column("mean_temperature", sa.Float(), nullable=True),
        sa.Column("total_rainfall", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("date", "station"),
    )
    op.create_index("ix_weather_daily_date", "weather_daily", ["date"])

    # 3. weather_forecasts
    op.create_table(
        "weather_forecasts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("forecast_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("target_hour", sa.Integer(), nullable=True),
        sa.Column("forecast_temperature", sa.Float(), nullable=True),
        sa.Column("forecast_min_temperature", sa.Float(), nullable=True),
        sa.Column("forecast_max_temperature", sa.Float(), nullable=True),
        sa.Column("humidity", sa.Float(), nullable=True),
        sa.Column("rain_probability", sa.Float(), nullable=True),
        sa.Column("wind", sa.String(length=200), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="hko_9day"),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "forecast_created_at", "target_date", "source", name="uq_forecast_created_target_src"
        ),
    )
    op.create_index(
        "ix_weather_forecasts_forecast_created_at", "weather_forecasts", ["forecast_created_at"]
    )
    op.create_index("ix_weather_forecasts_target_date", "weather_forecasts", ["target_date"])
    op.create_index(
        "ix_forecast_target_created", "weather_forecasts", ["target_date", "forecast_created_at"]
    )

    # 4. polymarket_markets
    op.create_table(
        "polymarket_markets",
        sa.Column("market_id", sa.String(length=100), nullable=False),
        sa.Column("event_id", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "market_type", sa.String(length=50), nullable=False, server_default="temperature_high"
        ),
        sa.Column(
            "outcome_bucket_schema", sa.JSON().with_variant(JSONB, "postgresql"), nullable=True
        ),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column(
            "metric", sa.String(length=50), nullable=False, server_default="temperature_celsius"
        ),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("resolution_source_raw", sa.Text(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("market_id"),
    )
    op.create_index("ix_polymarket_markets_event_id", "polymarket_markets", ["event_id"])
    op.create_index("ix_polymarket_markets_slug", "polymarket_markets", ["slug"])
    op.create_index("ix_polymarket_markets_target_date", "polymarket_markets", ["target_date"])
    op.create_index("ix_polymarket_markets_status", "polymarket_markets", ["status"])
    op.create_index("ix_poly_market_target_status", "polymarket_markets", ["target_date", "status"])

    # 5. polymarket_outcomes
    op.create_table(
        "polymarket_outcomes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("market_id", sa.String(length=100), nullable=False),
        sa.Column("token_id", sa.String(length=100), nullable=False),
        sa.Column("outcome_label", sa.String(length=100), nullable=False),
        sa.Column("outcome_bucket_low", sa.Float(), nullable=True),
        sa.Column("outcome_bucket_high", sa.Float(), nullable=True),
        sa.Column("outcome_value", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(
            ["market_id"], ["polymarket_markets.market_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("market_id", "token_id", name="uq_poly_outcome_market_token"),
    )
    op.create_index("ix_polymarket_outcomes_market_id", "polymarket_outcomes", ["market_id"])
    op.create_index("ix_polymarket_outcomes_token_id", "polymarket_outcomes", ["token_id"])

    # 6. polymarket_prices
    op.create_table(
        "polymarket_prices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("market_id", sa.String(length=100), nullable=False),
        sa.Column("token_id", sa.String(length=100), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["market_id"], ["polymarket_markets.market_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_polymarket_prices_market_id", "polymarket_prices", ["market_id"])
    op.create_index("ix_polymarket_prices_token_id", "polymarket_prices", ["token_id"])
    op.create_index("ix_polymarket_prices_timestamp", "polymarket_prices", ["timestamp"])
    op.create_index(
        "ix_poly_prices_market_token_ts",
        "polymarket_prices",
        ["market_id", "token_id", "timestamp"],
    )

    # 7. predictions
    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("market_id", sa.String(length=100), nullable=False),
        sa.Column("prediction_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_version", sa.String(length=50), nullable=False),
        sa.Column("outcome", sa.String(length=100), nullable=False),
        sa.Column("model_probability", sa.Float(), nullable=False),
        sa.Column("market_probability", sa.Float(), nullable=False),
        sa.Column("edge", sa.Float(), nullable=False),
        sa.Column("expected_value", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["market_id"], ["polymarket_markets.market_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_predictions_market_id", "predictions", ["market_id"])
    op.create_index("ix_predictions_prediction_timestamp", "predictions", ["prediction_timestamp"])
    op.create_index("ix_predictions_model_version", "predictions", ["model_version"])

    # 8. signals
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prediction_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("recommended_price", sa.Float(), nullable=True),
        sa.Column("recommended_size", sa.Float(), nullable=True),
        sa.Column("risk_limit", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["prediction_id"], ["predictions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_signals_prediction_id", "signals", ["prediction_id"])
    op.create_index("ix_signals_created_at", "signals", ["created_at"])

    # 9. paper_trades
    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("position_size", sa.Float(), nullable=False),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("pnl", sa.Float(), nullable=True),
        sa.Column("fees", sa.Float(), nullable=True),
        sa.Column("slippage", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="OPEN"),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_paper_trades_signal_id", "paper_trades", ["signal_id"])
    op.create_index("ix_paper_trades_status", "paper_trades", ["status"])
    op.create_index("ix_paper_trades_opened_at", "paper_trades", ["opened_at"])

    # 10. model_runs
    op.create_table(
        "model_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_version", sa.String(length=50), nullable=False),
        sa.Column("training_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("training_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validation_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validation_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("brier_score", sa.Float(), nullable=True),
        sa.Column("log_loss", sa.Float(), nullable=True),
        sa.Column("calibration_error", sa.Float(), nullable=True),
        sa.Column("mae", sa.Float(), nullable=True),
        sa.Column("rmse", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_version", name="uq_model_runs_version"),
    )
    op.create_index("ix_model_runs_model_version", "model_runs", ["model_version"])


def downgrade() -> None:
    op.drop_table("model_runs")
    op.drop_table("paper_trades")
    op.drop_table("signals")
    op.drop_table("predictions")
    op.drop_table("polymarket_prices")
    op.drop_table("polymarket_outcomes")
    op.drop_table("polymarket_markets")
    op.drop_table("weather_forecasts")
    op.drop_table("weather_daily")
    op.drop_table("weather_observations")
