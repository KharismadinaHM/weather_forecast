"""Historical Backtesting Engine supporting Model F and Model G Control."""

import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.backtest.metrics import BacktestMetricsCalculator, BacktestReport
from app.backtest.simulator import PaperExecutionSimulator, SettledTrade
from app.collectors.bucket_parser import ParsedBucket
from app.ml.models import WeatherMLModel
from app.trading.costs import ExecutionCostEstimator
from app.trading.edge import EdgeEngine
from app.trading.risk import RiskEngine


@dataclass(frozen=True)
class HistoricalMarketContext:
    """Historical market state on a given target date."""

    market_id: str
    target_date: date
    decision_timestamp: datetime
    buckets: list[ParsedBucket]
    outcome_prices: dict[str, float]
    actual_max_temp: float


class BacktestEngine:
    """Simulates point-in-time trading execution across historical test periods."""

    def __init__(
        self,
        edge_engine: EdgeEngine | None = None,
        risk_engine: RiskEngine | None = None,
        cost_estimator: ExecutionCostEstimator | None = None,
    ) -> None:
        self.edge_engine = edge_engine or EdgeEngine()
        self.risk_engine = risk_engine or RiskEngine()
        self.cost_estimator = cost_estimator or ExecutionCostEstimator()
        self.simulator = PaperExecutionSimulator(cost_estimator=self.cost_estimator)

    def run_backtest_on_contexts(
        self,
        contexts: Sequence[HistoricalMarketContext],
        model: WeatherMLModel,
        feature_rows: Sequence[dict[str, Any]],
        random_seed: int = 42,
    ) -> tuple[list[SettledTrade], list[SettledTrade], BacktestReport, BacktestReport]:
        """Run Strategy Model F and Control Model G simultaneously over historical markets.

        Returns:
            (model_f_trades, model_g_trades, model_f_report, model_g_report)
        """
        random.seed(random_seed)
        model_f_trades: list[SettledTrade] = []
        model_g_trades: list[SettledTrade] = []

        for ctx, f_row in zip(contexts, feature_rows, strict=False):
            # 1. Model F Prediction: Predict discrete probability distribution
            model_probs = model.predict_buckets(f_row, ctx.buckets)

            # 2. Evaluate opportunities via EdgeEngine
            evaluations = self.edge_engine.evaluate_market_distribution(
                model_probs=model_probs,
                market_prices=ctx.outcome_prices,
            )

            # Filter for actionable opportunities (Edge >= 8%, EV >= 5%)
            actionable = [e for e in evaluations if e.is_actionable]
            if actionable:
                best_opp = actionable[0]  # Highest EV outcome
                matching_bucket = next(
                    (b for b in ctx.buckets if b.raw_label == best_opp.outcome_label),
                    None,
                )
                if matching_bucket:
                    trade_f = self.simulator.simulate_trade_settlement(
                        trade_id=f"f_{ctx.market_id}",
                        market_id=ctx.market_id,
                        target_date=ctx.target_date,
                        outcome_bucket=matching_bucket,
                        market_price=best_opp.market_probability,
                        position_size_usd=1.0,
                        actual_max_temp=ctx.actual_max_temp,
                    )
                    model_f_trades.append(trade_f)

            # 3. Model G Control: Random / No-edge trade picker (Section 20a)
            # Picks an outcome randomly with probability proportional to market price
            valid_buckets = [b for b in ctx.buckets if b.raw_label in ctx.outcome_prices]
            if valid_buckets:
                chosen_bucket = random.choice(valid_buckets)
                mkt_p = ctx.outcome_prices[chosen_bucket.raw_label]
                trade_g = self.simulator.simulate_trade_settlement(
                    trade_id=f"g_{ctx.market_id}",
                    market_id=ctx.market_id,
                    target_date=ctx.target_date,
                    outcome_bucket=chosen_bucket,
                    market_price=mkt_p,
                    position_size_usd=1.0,
                    actual_max_temp=ctx.actual_max_temp,
                )
                model_g_trades.append(trade_g)

        report_f = BacktestMetricsCalculator.calculate_metrics(
            model_f_trades, strategy_name="Model_F_ML_Edge"
        )
        report_g = BacktestMetricsCalculator.calculate_metrics(
            model_g_trades, strategy_name="Model_G_Random_Control"
        )

        return model_f_trades, model_g_trades, report_f, report_g
