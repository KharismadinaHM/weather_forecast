"""Unit tests for Streamlit dashboard queries and metrics helpers (M-Dashboard)."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
from sqlalchemy.orm import Session

from app.dashboard.queries import (
    evaluate_section35_gates_from_db,
    get_diurnal_timing_insight,
    get_freshness_metrics,
    get_latest_predictions_df,
    get_market_price_vs_model_df,
    get_paper_trades_and_pnl_df,
)
from app.storage.models import (
    PaperTrade,
    PolymarketMarket,
    PolymarketOutcome,
    PolymarketPrice,
    Prediction,
    Signal,
    WeatherForecast,
    WeatherObservation,
)


def test_get_freshness_metrics(db_session: Session) -> None:
    """Verify freshness metrics calculation for HKO and Polymarket pipelines."""
    now = datetime.now(UTC)
    db_session.add(
        WeatherObservation(
            observed_at=now - timedelta(minutes=10),
            station="Hong Kong Observatory",
            temperature=31.0,
            rainfall=0.0,
            source="hko_rhrread",
        )
    )
    db_session.add(
        WeatherForecast(
            forecast_created_at=now - timedelta(minutes=30),
            target_date=date.today() + timedelta(days=1),
            forecast_max_temperature=33.0,
            forecast_min_temperature=27.0,
            humidity=75.0,
            rain_probability=20.0,
        )
    )
    db_session.commit()

    metrics = get_freshness_metrics(db_session)
    assert metrics["hko_observation"]["status"] == "FRESH"
    assert metrics["hko_observation"]["age_minutes"] is not None
    assert metrics["hko_observation"]["age_minutes"] < 20.0

    assert metrics["hko_forecast"]["status"] == "FRESH"
    assert metrics["polymarket_markets"]["status"] == "STALE"


def test_get_latest_predictions_df(db_session: Session) -> None:
    """Verify DataFrame construction for predictions and signals join."""
    target_d = date(2026, 8, 24)
    market = PolymarketMarket(
        market_id="mkt_dash_1",
        event_id="evt_dash_1",
        question="Highest temp in HK on Aug 24?",
        slug="hk-weather-aug24",
        target_date=target_d,
        status="active",
    )
    db_session.add(market)
    db_session.flush()

    pred = Prediction(
        market_id=market.market_id,
        prediction_timestamp=datetime.now(UTC),
        model_version="weather-v001",
        outcome="32°C",
        model_probability=0.42,
        market_probability=0.28,
        edge=0.14,
        expected_value=0.12,
    )
    db_session.add(pred)
    db_session.flush()

    sig = Signal(
        prediction_id=pred.id,
        decision="BUY",
        reason="Actionable Edge",
        recommended_price=0.28,
        recommended_size=1.0,
        risk_limit=2.0,
    )
    db_session.add(sig)
    db_session.commit()

    df = get_latest_predictions_df(db_session)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    assert df.iloc[0]["market"] == "Highest temp in HK on Aug 24?"
    assert df.iloc[0]["decision"] == "BUY"
    assert df.iloc[0]["edge"] == 0.14


def test_get_market_price_vs_model_df(db_session: Session) -> None:
    """Verify price vs model probability time-series DataFrame construction."""
    target_d = date(2026, 8, 25)
    now = datetime.now(UTC)

    market = PolymarketMarket(
        market_id="mkt_dash_2",
        event_id="evt_dash_2",
        question="Highest temp in HK on Aug 25?",
        slug="hk-weather-aug25",
        target_date=target_d,
        status="active",
    )
    db_session.add(market)
    db_session.flush()

    out = PolymarketOutcome(
        market_id=market.market_id,
        token_id="tok_31",
        outcome_label="31°C",
        outcome_bucket_low=31.0,
        outcome_bucket_high=31.0,
    )
    db_session.add(out)
    db_session.flush()

    price = PolymarketPrice(
        market_id=market.market_id,
        token_id="tok_31",
        timestamp=now - timedelta(minutes=5),
        price=0.30,
    )
    db_session.add(price)

    pred = Prediction(
        market_id=market.market_id,
        prediction_timestamp=now,
        model_version="weather-v001",
        outcome="31°C",
        model_probability=0.45,
        market_probability=0.30,
        edge=0.15,
        expected_value=0.14,
    )
    db_session.add(pred)
    db_session.commit()

    df = get_market_price_vs_model_df(db_session, market_id="mkt_dash_2")
    assert not df.empty
    assert "series_type" in df.columns
    assert set(df["series_type"].unique()) == {"Market Price", "Model Probability"}


def test_get_paper_trades_and_pnl_df(db_session: Session) -> None:
    """Verify paper trades table and cumulative PnL series computation."""
    target_d = date(2026, 8, 26)
    market = PolymarketMarket(
        market_id="mkt_dash_3",
        event_id="evt_dash_3",
        question="Highest temp in HK on Aug 26?",
        slug="hk-weather-aug26",
        target_date=target_d,
        status="active",
    )
    db_session.add(market)
    db_session.flush()

    pred = Prediction(
        market_id=market.market_id,
        prediction_timestamp=datetime.now(UTC),
        model_version="weather-v001",
        outcome="33°C",
        model_probability=0.50,
        market_probability=0.35,
        edge=0.15,
        expected_value=0.14,
    )
    db_session.add(pred)
    db_session.flush()

    sig = Signal(
        prediction_id=pred.id,
        decision="BUY",
        reason="Actionable Edge",
        recommended_price=0.35,
        recommended_size=1.0,
        risk_limit=2.0,
    )
    db_session.add(sig)
    db_session.flush()

    trade = PaperTrade(
        signal_id=sig.id,
        entry_price=0.35,
        position_size=1.0,
        fees=0.01,
        slippage=0.01,
        pnl=1.65,
        status="CLOSED",
        opened_at=datetime.now(UTC) - timedelta(hours=2),
        closed_at=datetime.now(UTC),
    )
    db_session.add(trade)
    db_session.commit()

    trades_df, pnl_df = get_paper_trades_and_pnl_df(db_session)
    assert len(trades_df) == 1
    assert trades_df.iloc[0]["status"] == "CLOSED"
    assert len(pnl_df) == 1
    assert pnl_df.iloc[0]["cumulative_pnl"] == 1.65

    gate_res = evaluate_section35_gates_from_db(db_session)
    assert gate_res.total_resolved_trades == 1
    assert gate_res.gate_sample_size_passed is False  # N < 50
    assert gate_res.verdict == "CONTINUE_PAPER_TRADING"


def test_get_diurnal_timing_insight(db_session: Session) -> None:
    """Verify calculation of diurnal peak hour and tactical entry recommendation (WIB)."""
    target_d = date(2026, 8, 27)
    market = PolymarketMarket(
        market_id="mkt_dash_4",
        event_id="evt_dash_4",
        question="Highest temp in HK on Aug 27?",
        slug="hk-weather-aug27",
        target_date=target_d,
        status="active",
    )
    db_session.add(market)
    db_session.flush()

    pred = Prediction(
        market_id=market.market_id,
        prediction_timestamp=datetime.now(UTC),
        model_version="weather-v001",
        outcome="34°C",
        model_probability=0.48,
        market_probability=0.30,
        edge=0.18,
        expected_value=0.16,
    )
    db_session.add(pred)
    db_session.commit()

    insight = get_diurnal_timing_insight(db_session)
    assert insight["recommended_outcome"] == "34°C"
    assert insight["decision"] == "BUY"
    assert "14:00 HKT" in insight["peak_hkt"]
    assert "13:00 WIB" in insight["peak_wib"]
    assert "WIB" in insight["recommended_entry_wib"]
    assert "Suhu tertinggi di HK pd tgl" in insight["formatted_insight"]
    assert "baiknya anda buy market pada suhu 34°C" in insight["formatted_insight"]
