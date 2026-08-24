"""Unit tests for Backtest Engine, Walk-Forward Validation, and Significance Testing."""

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.backtest.engine import BacktestEngine, HistoricalMarketContext
from app.backtest.metrics import BacktestMetricsCalculator
from app.backtest.significance import SignificanceTester
from app.backtest.simulator import MarketResolutionHelper, PaperExecutionSimulator, SettledTrade
from app.backtest.walk_forward import WalkForwardValidator
from app.collectors.bucket_parser import BucketParser, ParsedBucket
from app.ml.models import WeatherMLModel
from app.storage.models import WeatherDaily


def test_market_resolution_helper() -> None:
    """Verify market resolution conditions across all bucket geometries."""
    b_low = ParsedBucket(
        raw_label="<=30°C", low=None, high=30.0, is_open_lower=True, is_open_upper=False
    )
    b_single = ParsedBucket(
        raw_label="31°C", low=31.0, high=31.0, is_open_lower=False, is_open_upper=False
    )
    b_range = ParsedBucket(
        raw_label="32-33°C", low=32.0, high=33.0, is_open_lower=False, is_open_upper=False
    )
    b_high = ParsedBucket(
        raw_label=">=34°C", low=34.0, high=None, is_open_lower=False, is_open_upper=True
    )

    # Actual temp 30.2°C -> falls in <=30°C with 0.5 continuity correction (<=30.5)
    assert MarketResolutionHelper.is_bucket_winner(b_low, actual_temp=30.2) is True
    assert MarketResolutionHelper.is_bucket_winner(b_single, actual_temp=30.2) is False

    # Actual temp 31.0°C -> falls in 31°C [30.5, 31.5)
    assert MarketResolutionHelper.is_bucket_winner(b_single, actual_temp=31.0) is True

    # Actual temp 32.8°C -> falls in 32-33°C [31.5, 33.5)
    assert MarketResolutionHelper.is_bucket_winner(b_range, actual_temp=32.8) is True

    # Actual temp 34.5°C -> falls in >=34°C [33.5, +inf)
    assert MarketResolutionHelper.is_bucket_winner(b_high, actual_temp=34.5) is True


def test_paper_execution_simulator() -> None:
    """Verify execution costs, payoffs, and PnL for winning vs losing trades."""
    sim = PaperExecutionSimulator()
    bucket = ParsedBucket(
        raw_label="32°C", low=32.0, high=32.0, is_open_lower=False, is_open_upper=False
    )

    # Winning trade: Bought at 0.35, actual was 32.1°C
    won_trade = sim.simulate_trade_settlement(
        trade_id="t1",
        market_id="m1",
        target_date=date(2026, 8, 23),
        outcome_bucket=bucket,
        market_price=0.35,
        position_size_usd=1.0,
        actual_max_temp=32.1,
    )
    assert won_trade.won is True
    assert won_trade.gross_payoff > 1.0  # $1 per share > initial $1 cost
    assert won_trade.net_pnl > 0.0
    assert won_trade.roi_pct > 0.0

    # Losing trade: Bought at 0.35, actual was 35.0°C
    lost_trade = sim.simulate_trade_settlement(
        trade_id="t2",
        market_id="m1",
        target_date=date(2026, 8, 23),
        outcome_bucket=bucket,
        market_price=0.35,
        position_size_usd=1.0,
        actual_max_temp=35.0,
    )
    assert lost_trade.won is False
    assert lost_trade.gross_payoff == 0.0
    assert lost_trade.net_pnl < 0.0


def test_backtest_metrics_and_sample_size_caveat() -> None:
    """Verify metrics calculation and Section 18 sample-size caveat when N < 50."""
    # Synthetic 10 trades (small sample)
    trades = []
    for i in range(10):
        won = i % 2 == 0
        trades.append(
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
                actual_max_temp=32.0 if won else 29.0,
                won=won,
                gross_payoff=2.8 if won else 0.0,
                net_pnl=1.79 if won else -1.01,
                roi_pct=177.2 if won else -100.0,
            )
        )

    report = BacktestMetricsCalculator.calculate_metrics(trades, strategy_name="Test_Strategy")
    assert report.total_trades == 10
    assert report.winning_trades == 5
    assert report.win_rate == 50.0
    assert report.is_insufficient_sample is True
    assert report.sample_size_caveat is not None
    assert "Insufficient sample size" in report.sample_size_caveat


def test_walk_forward_validator(db_session: Session) -> None:
    """Verify multi-fold time-based walk-forward validation without lookahead."""
    # Create 3 months of historical data
    start_d = date(2026, 6, 1)
    for i in range(90):
        d = start_d + timedelta(days=i)
        db_session.add(
            WeatherDaily(
                date=d,
                station="Hong Kong Observatory",
                max_temperature=30.0 + (i % 5) * 0.5,
                min_temperature=26.0,
                mean_temperature=28.0,
                total_rainfall=0.0,
            )
        )
    db_session.commit()

    # Define 2 sequential non-overlapping walk-forward folds
    folds = [
        ((date(2026, 6, 1), date(2026, 6, 30)), (date(2026, 7, 1), date(2026, 7, 15))),
        ((date(2026, 6, 1), date(2026, 7, 15)), (date(2026, 7, 16), date(2026, 7, 31))),
    ]

    summary = WalkForwardValidator.run_validation(db_session, fold_schedules=folds)
    assert summary.fold_count == 2
    assert summary.total_test_samples > 0
    assert summary.mean_fold_mae >= 0.0
    assert summary.overall_rmse >= 0.0


def test_backtest_engine_model_f_and_model_g() -> None:
    """Verify simultaneous backtesting of Strategy Model F vs Control Model G."""
    # Synthetic model
    np.random.seed(42)
    rows = []
    y_vals = []
    for i in range(30):
        rows.append(
            {
                "month": 8,
                "day_of_year": 230 + i,
                "day_of_week": i % 7,
                "is_weekend": 0,
                "sin_day_of_year": 0.5,
                "cos_day_of_year": 0.5,
                "max_temp_lag1": 31.0,
                "max_temp_lag2": 30.5,
                "min_temp_lag1": 26.0,
                "mean_temp_lag1": 28.0,
                "rainfall_lag1": 0.0,
                "temp_range_lag1": 5.0,
                "rolling_7d_max_temp": 31.0,
                "rolling_30d_max_temp": 30.5,
                "rolling_7d_rainfall": 0.0,
                "hko_forecast_max_temp": 32.0,
                "hko_forecast_min_temp": 26.0,
                "rain_probability": 0.1,
                "forecast_available": 1,
                "lead_days": 1,
                "forecast_revision_count": 1,
                "forecast_revision_delta": 0.0,
            }
        )
        y_vals.append(32.1)

    model = WeatherMLModel(n_estimators=30, learning_rate=0.1)
    model.fit(pd.DataFrame(rows), pd.Series(y_vals))

    # Create 5 historical market contexts with market prices that create
    # clear mispricing opportunities for the model to detect
    buckets = BucketParser.parse_bucket_schema(["<=30°C", "31°C", "32°C", ">=33°C"])
    contexts = []
    f_rows = []
    for i in range(5):
        t_date = date(2026, 8, 10 + i)
        contexts.append(
            HistoricalMarketContext(
                market_id=f"poly_m_{i}",
                target_date=t_date,
                decision_timestamp=datetime(2026, 8, 9 + i, 16, 0, tzinfo=UTC),
                buckets=buckets,
                outcome_prices={"<=30°C": 0.25, "31°C": 0.25, "32°C": 0.20, ">=33°C": 0.30},
                actual_max_temp=32.2,  # 32°C wins!
            )
        )
        f_rows.append(rows[0])

    # Use explicit edge engine with test-specific thresholds to decouple
    # from production threshold changes
    from app.trading.edge import EdgeEngine

    engine = BacktestEngine(edge_engine=EdgeEngine(min_edge=0.08, min_net_ev=0.05))
    trades_f, trades_g, rep_f, rep_g = engine.run_backtest_on_contexts(contexts, model, f_rows)

    assert len(trades_f) > 0
    assert len(trades_g) > 0
    assert rep_f.strategy_name == "Model_F_ML_Edge"
    assert rep_g.strategy_name == "Model_G_Random_Control"


def test_significance_tester() -> None:
    """Verify Bootstrap Confidence Interval and Permutation Test vs Model G."""
    # Synthetic Model F (profitable) vs Model G (losing)
    trades_f = [
        SettledTrade(
            trade_id=f"f_{i}",
            market_id=f"m_{i}",
            target_date=date(2026, 8, 1 + i),
            outcome_label="32°C",
            entry_price=0.35,
            position_size_usd=1.0,
            shares=2.8,
            fees=0.01,
            slippage=0.01,
            actual_max_temp=32.0,
            won=(i % 3 != 0),  # 66% win rate
            gross_payoff=2.8 if (i % 3 != 0) else 0.0,
            net_pnl=1.78 if (i % 3 != 0) else -1.02,
            roi_pct=178.0 if (i % 3 != 0) else -102.0,
        )
        for i in range(30)
    ]

    trades_g = [
        SettledTrade(
            trade_id=f"g_{i}",
            market_id=f"m_{i}",
            target_date=date(2026, 8, 1 + i),
            outcome_label="30°C",
            entry_price=0.35,
            position_size_usd=1.0,
            shares=2.8,
            fees=0.01,
            slippage=0.01,
            actual_max_temp=32.0,
            won=(i % 4 == 0),  # 25% win rate
            gross_payoff=2.8 if (i % 4 == 0) else 0.0,
            net_pnl=1.78 if (i % 4 == 0) else -1.02,
            roi_pct=178.0 if (i % 4 == 0) else -102.0,
        )
        for i in range(30)
    ]

    sig_res = SignificanceTester.test_strategy_significance(trades_f, trades_g, n_bootstraps=500)
    assert sig_res.model_f_roi > sig_res.model_g_roi
    assert sig_res.roi_difference > 0
    assert 0.0 <= sig_res.p_value <= 1.0
    assert sig_res.verdict in ["CONCLUSIVE_EDGE", "PROVISIONAL_EDGE"]
