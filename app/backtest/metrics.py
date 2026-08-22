"""Financial and performance evaluation metrics for backtesting (PLAN.md Section 18)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.backtest.simulator import SettledTrade


@dataclass(frozen=True)
class BacktestReport:
    """Comprehensive performance report for backtest simulations."""

    strategy_name: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_capital_invested: float
    total_gross_payoff: float
    total_net_pnl: float
    total_roi_pct: float
    max_drawdown_usd: float
    max_drawdown_pct: float
    profit_factor: float
    sharpe_ratio: float
    total_fees: float
    total_slippage: float
    avg_trade_pnl: float
    is_insufficient_sample: bool
    sample_size_caveat: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "total_capital_invested": self.total_capital_invested,
            "total_gross_payoff": self.total_gross_payoff,
            "total_net_pnl": self.total_net_pnl,
            "total_roi_pct": self.total_roi_pct,
            "max_drawdown_usd": self.max_drawdown_usd,
            "max_drawdown_pct": self.max_drawdown_pct,
            "profit_factor": self.profit_factor,
            "sharpe_ratio": self.sharpe_ratio,
            "total_fees": self.total_fees,
            "total_slippage": self.total_slippage,
            "avg_trade_pnl": self.avg_trade_pnl,
            "is_insufficient_sample": self.is_insufficient_sample,
            "sample_size_caveat": self.sample_size_caveat,
        }


class BacktestMetricsCalculator:
    """Computes standard financial and risk metrics from settled trade sequences."""

    MIN_STATISTICAL_SAMPLE_SIZE: int = 50  # Section 18 sample size threshold

    @classmethod
    def calculate_metrics(
        cls,
        trades: Sequence[SettledTrade],
        strategy_name: str = "Model_F_Live_Trading",
        initial_bankroll: float = 15.0,
    ) -> BacktestReport:
        """Compute comprehensive performance summary."""
        n_trades = len(trades)
        if n_trades == 0:
            return BacktestReport(
                strategy_name=strategy_name,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                total_capital_invested=0.0,
                total_gross_payoff=0.0,
                total_net_pnl=0.0,
                total_roi_pct=0.0,
                max_drawdown_usd=0.0,
                max_drawdown_pct=0.0,
                profit_factor=0.0,
                sharpe_ratio=0.0,
                total_fees=0.0,
                total_slippage=0.0,
                avg_trade_pnl=0.0,
                is_insufficient_sample=True,
                sample_size_caveat="No trades executed",
            )

        wins = [t for t in trades if t.won]
        losses = [t for t in trades if not t.won]

        n_wins = len(wins)
        n_losses = len(losses)
        win_rate = (n_wins / n_trades) * 100.0

        total_invested = sum(t.position_size_usd for t in trades)
        total_payoff = sum(t.gross_payoff for t in trades)
        total_pnl = sum(t.net_pnl for t in trades)
        total_fees = sum(t.fees for t in trades)
        total_slippage = sum(t.slippage for t in trades)
        total_roi = (total_pnl / max(0.01, total_invested)) * 100.0
        avg_pnl = total_pnl / n_trades

        # Profit Factor = Gross Profits / Gross Losses
        gross_profit = sum(t.net_pnl for t in trades if t.net_pnl > 0)
        gross_loss = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))
        profit_factor = (
            (gross_profit / max(1e-4, gross_loss))
            if gross_loss > 0
            else (99.0 if gross_profit > 0 else 1.0)
        )

        # Cumulative PnL and Max Drawdown calculation
        pnls = [t.net_pnl for t in trades]
        cum_pnl = np.cumsum(pnls)
        equity_curve = initial_bankroll + cum_pnl

        peak = initial_bankroll
        max_dd_usd = 0.0
        max_dd_pct = 0.0

        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd_usd = peak - eq
            dd_pct = (dd_usd / peak * 100.0) if peak > 0 else 0.0
            if dd_usd > max_dd_usd:
                max_dd_usd = dd_usd
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

        # Sharpe ratio approximation (daily/trade normalized)
        returns = [t.roi_pct / 100.0 for t in trades]
        mean_ret = float(np.mean(returns))
        std_ret = float(np.std(returns)) if len(returns) > 1 else 0.0
        sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 1e-4 else 0.0

        # Sample size caveat (Section 18 & 20)
        is_insufficient = n_trades < cls.MIN_STATISTICAL_SAMPLE_SIZE
        caveat_msg = (
            f"Insufficient sample size (N={n_trades} < {cls.MIN_STATISTICAL_SAMPLE_SIZE}), "
            f"results are provisional and directional only."
            if is_insufficient
            else None
        )

        return BacktestReport(
            strategy_name=strategy_name,
            total_trades=n_trades,
            winning_trades=n_wins,
            losing_trades=n_losses,
            win_rate=round(win_rate, 2),
            total_capital_invested=round(total_invested, 2),
            total_gross_payoff=round(total_payoff, 2),
            total_net_pnl=round(total_pnl, 2),
            total_roi_pct=round(total_roi, 2),
            max_drawdown_usd=round(max_dd_usd, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            profit_factor=round(profit_factor, 2),
            sharpe_ratio=round(sharpe, 2),
            total_fees=round(total_fees, 4),
            total_slippage=round(total_slippage, 4),
            avg_trade_pnl=round(avg_pnl, 4),
            is_insufficient_sample=is_insufficient,
            sample_size_caveat=caveat_msg,
        )
