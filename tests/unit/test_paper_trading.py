"""Unit tests for Forward Paper Trading and Section 35 Quantitative Gates."""

from datetime import UTC, date, datetime

import numpy as np
from sqlalchemy.orm import Session

from app.backtest.simulator import SettledTrade
from app.paper.evaluator import PaperPerformanceEvaluator
from app.paper.recalibration import ModelRecalibrator
from app.paper.tracker import PaperTradingTracker
from app.storage.models import (
    PaperTrade,
    PolymarketMarket,
    PolymarketOutcome,
    Prediction,
    Signal,
    WeatherDaily,
)


def test_paper_trading_tracker_open_and_resolve(db_session: Session) -> None:
    """Verify PaperTradingTracker opens positions and resolves them with HKO ground truth."""
    target_d = date(2026, 8, 23)

    # 1. Setup market, prediction, and signal
    market = PolymarketMarket(
        market_id="m_paper_1",
        event_id="evt-1",
        slug="hk-weather-aug23",
        question="Highest temp in HK on Aug 23?",
        target_date=target_d,
        status="active",
    )
    db_session.add(market)
    db_session.flush()

    out = PolymarketOutcome(market_id=market.market_id, token_id="tok-32", outcome_label="32°C")
    db_session.add(out)
    db_session.flush()

    pred = Prediction(
        market_id=market.market_id,
        prediction_timestamp=datetime.now(UTC),
        model_version="weather-v001",
        outcome="32°C",
        model_probability=0.45,
        market_probability=0.30,
        edge=0.15,
        expected_value=0.14,
    )
    db_session.add(pred)
    db_session.flush()

    sig = Signal(
        prediction_id=pred.id,
        decision="BUY",
        reason="Actionable edge",
        recommended_price=0.30,
        recommended_size=1.0,
        risk_limit=2.0,
    )
    db_session.add(sig)
    db_session.flush()

    # 2. Open paper trade
    trade = PaperTradingTracker.open_paper_trade(
        session=db_session,
        signal_id=sig.id,
        entry_price=0.30,
        position_size=1.0,
    )
    assert trade.id is not None
    assert trade.status == "OPEN"
    db_session.commit()

    # 3. Add ground truth observation (Actual was 32.1°C -> 32°C wins!)
    db_session.add(
        WeatherDaily(
            date=target_d,
            station="Hong Kong Observatory",
            max_temperature=32.1,
            min_temperature=26.5,
            mean_temperature=28.5,
            total_rainfall=0.0,
        )
    )
    db_session.commit()

    # 4. Resolve paper trades
    settled = PaperTradingTracker.resolve_paper_trades_for_date(
        session=db_session,
        target_date=target_d,
    )

    assert len(settled) == 1
    assert settled[0].won is True
    assert settled[0].net_pnl > 0.0

    # Verify DB update
    updated_trade = db_session.get(PaperTrade, trade.id)
    assert updated_trade is not None
    assert updated_trade.status == "CLOSED"
    assert updated_trade.pnl is not None
    assert updated_trade.pnl > 0.0


def test_paper_performance_evaluator_insufficient_sample() -> None:
    """Verify that sample size < 50 produces CONTINUE_PAPER_TRADING verdict."""
    trades = [
        SettledTrade(
            trade_id=f"t_{i}",
            market_id=f"m_{i}",
            target_date=date(2026, 8, 1 + i),
            outcome_label="32°C",
            entry_price=0.35,
            position_size_usd=1.0,
            shares=2.8,
            fees=0.01,
            slippage=0.01,
            actual_max_temp=32.0,
            won=(i % 2 == 0),
            gross_payoff=2.8 if (i % 2 == 0) else 0.0,
            net_pnl=1.78 if (i % 2 == 0) else -1.02,
            roi_pct=178.0 if (i % 2 == 0) else -102.0,
        )
        for i in range(20)
    ]

    res = PaperPerformanceEvaluator.evaluate_gates(trades)
    assert res.total_resolved_trades == 20
    assert res.gate_sample_size_passed is False
    assert res.all_gates_passed is False
    assert res.verdict == "CONTINUE_PAPER_TRADING"
    assert len(res.false_positives) == 10


def test_paper_performance_evaluator_all_gates_passed() -> None:
    """Verify that sample size >= 50 + profitable strategy + significance passes all gates."""
    trades_f = [
        SettledTrade(
            trade_id=f"t_{i}",
            market_id=f"m_{i}",
            target_date=date(2026, 8, 1 + (i % 28)),
            outcome_label="32°C",
            entry_price=0.35,
            position_size_usd=1.0,
            shares=2.8,
            fees=0.01,
            slippage=0.01,
            actual_max_temp=32.0,
            won=(i % 3 != 0),
            gross_payoff=2.8 if (i % 3 != 0) else 0.0,
            net_pnl=1.78 if (i % 3 != 0) else -1.02,
            roi_pct=178.0 if (i % 3 != 0) else -102.0,
        )
        for i in range(60)
    ]

    trades_g = [
        SettledTrade(
            trade_id=f"g_{i}",
            market_id=f"m_{i}",
            target_date=date(2026, 8, 1 + (i % 28)),
            outcome_label="30°C",
            entry_price=0.35,
            position_size_usd=1.0,
            shares=2.8,
            fees=0.01,
            slippage=0.01,
            actual_max_temp=32.0,
            won=False,
            gross_payoff=0.0,
            net_pnl=-1.02,
            roi_pct=-102.0,
        )
        for i in range(60)
    ]

    res = PaperPerformanceEvaluator.evaluate_gates(
        resolved_trades=trades_f,
        control_trades=trades_g,
        model_ece=0.03,
        model_brier=0.18,
        hko_brier=0.22,
    )

    assert res.total_resolved_trades == 60
    assert res.gate_sample_size_passed is True
    assert res.gate_positive_roi_passed is True
    assert res.gate_calibration_passed is True
    assert res.gate_beat_hko_baseline_passed is True
    assert res.all_gates_passed is True
    assert res.verdict == "READY_FOR_LIVE_EXPERIMENT"


def test_model_recalibrator_drift_detection() -> None:
    """Verify ModelRecalibrator detects calibration drift and fits calibrator."""
    np.random.seed(42)
    y_prob = np.array([0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55, 0.5, 0.45] * 5)
    y_true = np.array([1, 0, 0, 1, 0, 0, 0, 1, 0, 0] * 5)

    res = ModelRecalibrator.check_and_recalibrate(
        predicted_probs=y_prob,
        actual_outcomes=y_true,
        ece_threshold=0.05,
        method="isotonic",
    )

    assert res.recalibration_needed is True
    assert res.pre_recalibration_ece > 0.05
    assert res.post_recalibration_ece < res.pre_recalibration_ece
    assert res.calibrator is not None
