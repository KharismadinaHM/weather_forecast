"""Backtest Engine, Walk-Forward Validation, and Statistical Significance."""

from app.backtest.engine import BacktestEngine, HistoricalMarketContext
from app.backtest.metrics import BacktestMetricsCalculator, BacktestReport
from app.backtest.significance import SignificanceTester, SignificanceTestResult
from app.backtest.simulator import MarketResolutionHelper, PaperExecutionSimulator, SettledTrade
from app.backtest.walk_forward import (
    WalkForwardFoldResult,
    WalkForwardSummary,
    WalkForwardValidator,
)

__all__ = [
    "SettledTrade",
    "MarketResolutionHelper",
    "PaperExecutionSimulator",
    "BacktestReport",
    "BacktestMetricsCalculator",
    "WalkForwardFoldResult",
    "WalkForwardSummary",
    "WalkForwardValidator",
    "HistoricalMarketContext",
    "BacktestEngine",
    "SignificanceTestResult",
    "SignificanceTester",
]
