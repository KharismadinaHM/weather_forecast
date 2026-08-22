"""Unit tests for Trading Logic: Edge, EV, Fee/Slippage Models, and Risk Engine."""

import math
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.storage.models import (
    PaperTrade,
    PolymarketMarket,
    PolymarketOutcome,
    PolymarketPrice,
    Prediction,
)
from app.trading.costs import ExecutionCostEstimator, FeeModel, SlippageModel
from app.trading.edge import EdgeEngine
from app.trading.engine import SignalGenerator
from app.trading.risk import RiskEngine


def test_fee_and_slippage_models() -> None:
    """Verify fee calculation and spread-based slippage estimation."""
    fee_mod = FeeModel(taker_fee_rate=0.01, gas_cost_usd=0.005)
    fees = fee_mod.calculate_fees(order_size_usd=1.0)
    assert round(fees, 4) == 0.015

    slip_mod = SlippageModel(base_slippage=0.005, spread_impact=0.5)
    # Test with tight spread: bid 0.30, ask 0.32 (spread 0.02)
    slip_tight = slip_mod.estimate_slippage(market_price=0.31, bid_price=0.30, ask_price=0.32)
    assert round(slip_tight, 3) == 0.01

    # Test execution cost estimator
    cost_est = ExecutionCostEstimator(fee_model=fee_mod, slippage_model=slip_mod)
    eff_price, total_fees, slippage = cost_est.estimate_effective_entry_price(
        market_price=0.30, bid_price=0.29, ask_price=0.31, order_size_usd=1.0
    )
    assert eff_price > 0.30
    assert total_fees > 0.0
    assert slippage > 0.0


def test_edge_engine_evaluation() -> None:
    """Verify Edge and EV computation with research threshold filtering."""
    engine = EdgeEngine(min_edge=0.08, min_net_ev=0.05)

    # Case 1: Substantial edge (Model 45%, Market 30% -> Edge +15%, Net EV ~+13%)
    opp_actionable = engine.evaluate_outcome(
        outcome_label="32°C",
        model_prob=0.45,
        market_price=0.30,
    )
    assert math.isclose(opp_actionable.gross_edge, 0.15, rel_tol=1e-5)
    assert opp_actionable.is_actionable is True
    assert opp_actionable.is_positive_ev is True

    # Case 2: Positive EV but below MIN_EDGE threshold (Model 34%, Market 30% -> Edge 4%)
    opp_small_edge = engine.evaluate_outcome(
        outcome_label="33°C",
        model_prob=0.34,
        market_price=0.30,
    )
    assert math.isclose(opp_small_edge.gross_edge, 0.04, rel_tol=1e-5)
    assert opp_small_edge.is_actionable is False
    assert opp_small_edge.is_positive_ev is True

    # Case 3: Negative EV (Model 20%, Market 30%)
    opp_negative = engine.evaluate_outcome(
        outcome_label="31°C",
        model_prob=0.20,
        market_price=0.30,
    )
    assert opp_negative.is_actionable is False
    assert opp_negative.is_positive_ev is False


def test_risk_engine_kill_switch(db_session: Session) -> None:
    """Verify RiskEngine immediate veto when kill switch / pause is active."""
    risk = RiskEngine(is_paused=False)
    # Trade initially allowed
    dec_active = risk.check_trade(
        session=db_session,
        market_id="m1",
        outcome_label="32°C",
        entry_price=0.30,
    )
    assert dec_active.allowed is True
    assert dec_active.decision == "BUY"

    # Activate pause
    risk.pause()
    dec_paused = risk.check_trade(
        session=db_session,
        market_id="m1",
        outcome_label="32°C",
        entry_price=0.30,
    )
    assert dec_paused.allowed is False
    assert dec_paused.decision == "SKIP"
    assert "Kill switch" in dec_paused.reason


def test_risk_engine_stale_data_protection(db_session: Session) -> None:
    """Verify RiskEngine rejects prices older than maximum allowed age."""
    risk = RiskEngine(max_price_age_seconds=1800)  # 30 min max age
    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)

    # Fresh price (10 min ago)
    fresh_ts = now - timedelta(minutes=10)
    dec_fresh = risk.check_trade(
        session=db_session,
        market_id="m1",
        outcome_label="32°C",
        entry_price=0.30,
        price_timestamp=fresh_ts,
        as_of_time=now,
    )
    assert dec_fresh.allowed is True

    # Stale price (45 min ago)
    stale_ts = now - timedelta(minutes=45)
    dec_stale = risk.check_trade(
        session=db_session,
        market_id="m1",
        outcome_label="32°C",
        entry_price=0.30,
        price_timestamp=stale_ts,
        as_of_time=now,
    )
    assert dec_stale.allowed is False
    assert dec_stale.decision == "SKIP"
    assert "Stale price" in dec_stale.reason


def test_risk_engine_max_open_positions_limit(db_session: Session) -> None:
    """Verify RiskEngine enforces MAX_OPEN_POSITIONS = 2 constraint."""
    risk = RiskEngine(max_open_positions=2)

    # Insert 2 existing OPEN paper trades
    for i in range(2):
        trade = PaperTrade(
            signal_id=i + 1,
            entry_price=0.30,
            position_size=1.0,
            status="OPEN",
            opened_at=datetime.now(UTC),
        )
        db_session.add(trade)
    db_session.commit()

    dec = risk.check_trade(
        session=db_session,
        market_id="m1",
        outcome_label="32°C",
        entry_price=0.30,
    )
    assert dec.allowed is False
    assert dec.decision == "SKIP"
    assert "Max open positions" in dec.reason


def test_risk_engine_max_daily_risk_limit(db_session: Session) -> None:
    """Verify RiskEngine enforces MAX_DAILY_RISK = $2.00 constraint."""
    risk = RiskEngine(max_daily_risk=2.0, max_trade=1.0)
    now = datetime.now(UTC)

    # Add $1.50 in trades today (status CLOSED so open positions limit is not hit)
    trade1 = PaperTrade(
        signal_id=101,
        entry_price=0.30,
        position_size=1.50,
        status="CLOSED",
        opened_at=now - timedelta(hours=2),
    )
    db_session.add(trade1)
    db_session.commit()

    # Propose $1.0 trade -> Should be resized to remaining $0.50 daily budget
    dec = risk.check_trade(
        session=db_session,
        market_id="m1",
        outcome_label="32°C",
        entry_price=0.30,
        proposed_size=1.0,
        as_of_time=now,
    )
    assert dec.allowed is True
    assert dec.recommended_size == 0.50

    # If daily budget is fully exhausted
    trade2 = PaperTrade(
        signal_id=102,
        entry_price=0.30,
        position_size=0.50,
        status="CLOSED",
        opened_at=now - timedelta(hours=1),
    )
    db_session.add(trade2)
    db_session.commit()

    dec_exhausted = risk.check_trade(
        session=db_session,
        market_id="m1",
        outcome_label="32°C",
        entry_price=0.30,
        proposed_size=1.0,
        as_of_time=now,
    )
    assert dec_exhausted.allowed is False
    assert "Daily risk budget exhausted" in dec_exhausted.reason


def test_signal_generator_end_to_end(db_session: Session) -> None:
    """Verify full signal generation flow from market probability to DB records."""
    market_id = "poly-hk-weather-20260823"

    # Setup market and outcomes in database
    market = PolymarketMarket(
        market_id=market_id,
        event_id="evt-100",
        slug="hong-kong-high-temp-aug-23",
        question="Highest temperature in Hong Kong on August 23, 2026?",
        target_date=date(2026, 8, 23),
        status="active",
    )
    db_session.add(market)
    db_session.flush()

    outcomes = [
        PolymarketOutcome(market_id=market_id, token_id="tok-30", outcome_label="<=30°C"),
        PolymarketOutcome(market_id=market_id, token_id="tok-31", outcome_label="31°C"),
        PolymarketOutcome(market_id=market_id, token_id="tok-32", outcome_label="32°C"),
        PolymarketOutcome(market_id=market_id, token_id="tok-33", outcome_label=">=33°C"),
    ]
    db_session.add_all(outcomes)
    db_session.flush()

    now = datetime.now(UTC)
    # Add live price snapshots
    prices = [
        PolymarketPrice(market_id=market_id, token_id="tok-30", timestamp=now, price=0.10),
        PolymarketPrice(market_id=market_id, token_id="tok-31", timestamp=now, price=0.25),
        PolymarketPrice(market_id=market_id, token_id="tok-32", timestamp=now, price=0.35),
        PolymarketPrice(market_id=market_id, token_id="tok-33", timestamp=now, price=0.30),
    ]
    db_session.add_all(prices)
    db_session.commit()

    # Model predicts 32°C with high probability (52%) -> Large edge over 35% market price
    model_probs = {
        "<=30°C": 0.05,
        "31°C": 0.15,
        "32°C": 0.52,
        ">=33°C": 0.28,
    }

    generator = SignalGenerator()
    results = generator.process_market_signals(
        session=db_session,
        market_id=market_id,
        model_probs=model_probs,
        model_version="lgbm_v1.0",
        confidence=0.85,
        as_of_time=now,
    )

    assert len(results) == 4

    # Verify 32°C produced a BUY signal
    buy_signals = [s for p, s in results if p.outcome == "32°C"]
    assert len(buy_signals) == 1
    assert buy_signals[0].decision == "BUY"
    assert buy_signals[0].recommended_size == 1.0
    assert buy_signals[0].recommended_price == 0.35

    # Check persistence in DB
    db_preds = db_session.scalars(select(Prediction).where(Prediction.market_id == market_id)).all()
    assert len(db_preds) == 4
