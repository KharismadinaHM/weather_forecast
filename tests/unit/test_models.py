"""Unit tests for SQLAlchemy models and database schema integrity."""

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.storage.models import (
    ModelRun,
    PaperTrade,
    PolymarketMarket,
    PolymarketOutcome,
    Prediction,
    Signal,
    WeatherDaily,
    WeatherForecast,
    WeatherObservation,
)


def test_weather_observation_model(db_session: Session) -> None:
    """Test WeatherObservation model persistence and authoritative station flag."""
    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    obs = WeatherObservation(
        observed_at=now,
        station="Hong Kong Observatory",
        is_authoritative=True,
        temperature=31.5,
        humidity=78.0,
        rainfall=0.0,
        pressure=1008.2,
        wind_speed=15.0,
        wind_direction="SW",
        weather_condition="Mainly Cloudy",
        source="hko",
    )
    db_session.add(obs)
    db_session.commit()

    saved = db_session.query(WeatherObservation).filter_by(station="Hong Kong Observatory").first()
    assert saved is not None
    assert saved.is_authoritative is True
    assert saved.temperature == 31.5


def test_weather_daily_model(db_session: Session) -> None:
    """Test WeatherDaily ground truth target table."""
    today = date(2026, 8, 22)
    daily = WeatherDaily(
        date=today,
        station="Hong Kong Observatory",
        max_temperature=33.2,
        min_temperature=27.4,
        mean_temperature=29.8,
        total_rainfall=2.5,
    )
    db_session.add(daily)
    db_session.commit()

    saved = (
        db_session.query(WeatherDaily)
        .filter_by(date=today, station="Hong Kong Observatory")
        .first()
    )
    assert saved is not None
    assert saved.max_temperature == 33.2


def test_weather_forecast_anti_leakage_fields(db_session: Session) -> None:
    """Verify WeatherForecast preserves both forecast_created_at and target_date per Section 8."""
    created_at = datetime(2026, 8, 22, 8, 0, tzinfo=UTC)
    target_dt = date(2026, 8, 23)

    forecast = WeatherForecast(
        forecast_created_at=created_at,
        target_date=target_dt,
        forecast_max_temperature=32.0,
        forecast_min_temperature=27.0,
        humidity=90.0,
        rain_probability=0.6,
        source="hko_9day",
    )
    db_session.add(forecast)
    db_session.commit()

    saved = db_session.query(WeatherForecast).filter_by(target_date=target_dt).first()
    assert saved is not None
    # Compare ISO date/time or ensure both representation match
    assert saved.forecast_created_at.strftime("%Y-%m-%d %H:%M") == created_at.strftime(
        "%Y-%m-%d %H:%M"
    )
    assert saved.target_date == target_dt


def test_polymarket_market_and_outcomes_relationship(db_session: Session) -> None:
    """Verify PolymarketMarket and PolymarketOutcome relationship with bucket schema."""
    target_dt = date(2026, 8, 23)
    bucket_schema = [
        {"label": "<=30C", "low": None, "high": 30.0},
        {"label": "31C", "low": 30.1, "high": 31.0},
        {"label": "32C", "low": 31.1, "high": 32.0},
        {"label": ">=33C", "low": 32.1, "high": None},
    ]

    market = PolymarketMarket(
        market_id="mkt_12345",
        event_id="evt_9876",
        slug="hong-kong-high-temp-august-23",
        question="What will the highest temperature in Hong Kong be on August 23?",
        market_type="temperature_high",
        outcome_bucket_schema=bucket_schema,
        target_date=target_dt,
        metric="temperature_celsius",
        status="active",
        resolution_source_raw="Hong Kong Observatory (https://data.weather.gov.hk)",
    )

    outcome_1 = PolymarketOutcome(
        market_id="mkt_12345",
        token_id="tok_31c",
        outcome_label="31C",
        outcome_bucket_low=30.1,
        outcome_bucket_high=31.0,
    )
    outcome_2 = PolymarketOutcome(
        market_id="mkt_12345",
        token_id="tok_32c",
        outcome_label="32C",
        outcome_bucket_low=31.1,
        outcome_bucket_high=32.0,
    )

    db_session.add(market)
    db_session.add_all([outcome_1, outcome_2])
    db_session.commit()

    saved_market = db_session.query(PolymarketMarket).filter_by(market_id="mkt_12345").first()
    assert saved_market is not None
    assert len(saved_market.outcomes) == 2
    assert saved_market.resolution_source_raw is not None
    assert "Hong Kong Observatory" in saved_market.resolution_source_raw


def test_trading_and_signal_chain(db_session: Session) -> None:
    """Verify end-to-end relational chain: Market -> Prediction -> Signal -> PaperTrade."""
    target_dt = date(2026, 8, 23)
    market = PolymarketMarket(
        market_id="mkt_trading_test",
        event_id="evt_test",
        slug="hk-temp-test",
        question="Highest temp test?",
        target_date=target_dt,
        status="active",
    )
    db_session.add(market)
    db_session.flush()

    pred = Prediction(
        market_id="mkt_trading_test",
        prediction_timestamp=datetime.now(UTC),
        model_version="weather-v001",
        outcome="32C",
        model_probability=0.45,
        market_probability=0.30,
        edge=0.15,
        expected_value=0.11,
        confidence=0.85,
    )
    db_session.add(pred)
    db_session.flush()

    sig = Signal(
        prediction_id=pred.id,
        decision="BUY",
        reason="Positive EV above threshold (+11%)",
        recommended_price=0.30,
        recommended_size=1.0,
        risk_limit=2.0,
    )
    db_session.add(sig)
    db_session.flush()

    trade = PaperTrade(
        signal_id=sig.id,
        entry_price=0.30,
        position_size=1.0,
        status="OPEN",
    )
    db_session.add(trade)
    db_session.commit()

    saved_trade = db_session.query(PaperTrade).filter_by(id=trade.id).first()
    assert saved_trade is not None
    assert saved_trade.signal.decision == "BUY"
    assert saved_trade.signal.prediction.model_version == "weather-v001"


def test_model_run_model(db_session: Session) -> None:
    """Test ModelRun tracking table."""
    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    run = ModelRun(
        model_version="weather-v001",
        training_start=now,
        training_end=now,
        validation_start=now,
        validation_end=now,
        test_start=now,
        test_end=now,
        brier_score=0.125,
        log_loss=0.380,
        calibration_error=0.035,
        mae=0.65,
        rmse=0.82,
    )
    db_session.add(run)
    db_session.commit()

    saved = db_session.query(ModelRun).filter_by(model_version="weather-v001").first()
    assert saved is not None
    assert saved.brier_score == 0.125
