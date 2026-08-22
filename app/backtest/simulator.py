"""Paper execution and trade settlement simulator for backtesting (PLAN.md Section 18)."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.collectors.bucket_parser import ParsedBucket
from app.trading.costs import ExecutionCostEstimator


@dataclass(frozen=True)
class SettledTrade:
    """Settled trade outcome and PnL record."""

    trade_id: str
    market_id: str
    target_date: date
    outcome_label: str
    entry_price: float
    position_size_usd: float
    shares: float
    fees: float
    slippage: float
    actual_max_temp: float
    won: bool
    gross_payoff: float
    net_pnl: float
    roi_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "market_id": self.market_id,
            "target_date": self.target_date.isoformat(),
            "outcome_label": self.outcome_label,
            "entry_price": self.entry_price,
            "position_size_usd": self.position_size_usd,
            "shares": self.shares,
            "fees": self.fees,
            "slippage": self.slippage,
            "actual_max_temp": self.actual_max_temp,
            "won": self.won,
            "gross_payoff": self.gross_payoff,
            "net_pnl": self.net_pnl,
            "roi_pct": self.roi_pct,
        }


class MarketResolutionHelper:
    """Evaluates whether an observed temperature satisfies a given outcome bucket."""

    @classmethod
    def is_bucket_winner(
        cls,
        bucket: ParsedBucket,
        actual_temp: float,
        continuity_correction: float = 0.5,
    ) -> bool:
        """Check if actual_temp falls within bucket bounds."""
        if bucket.is_open_lower:
            high_bound = (
                bucket.high if bucket.high is not None else actual_temp
            ) + continuity_correction
            return actual_temp <= high_bound

        if bucket.is_open_upper:
            low_bound = (
                bucket.low if bucket.low is not None else actual_temp
            ) - continuity_correction
            return actual_temp >= low_bound

        if bucket.low is not None and bucket.high is not None:
            low_bound = bucket.low - continuity_correction
            high_bound = bucket.high + continuity_correction
            return low_bound <= actual_temp < high_bound

        return False


class PaperExecutionSimulator:
    """Simulates trade entry and contract settlement upon resolution."""

    def __init__(self, cost_estimator: ExecutionCostEstimator | None = None) -> None:
        self.cost_estimator = cost_estimator or ExecutionCostEstimator()

    def simulate_trade_settlement(
        self,
        trade_id: str,
        market_id: str,
        target_date: date,
        outcome_bucket: ParsedBucket,
        market_price: float,
        position_size_usd: float,
        actual_max_temp: float,
        bid_price: float | None = None,
        ask_price: float | None = None,
    ) -> SettledTrade:
        """Simulate execution entry, market resolution, and settlement calculation."""
        eff_price, fees, slippage = self.cost_estimator.estimate_effective_entry_price(
            market_price=market_price,
            bid_price=bid_price,
            ask_price=ask_price,
            order_size_usd=position_size_usd,
        )

        # Number of $1 shares purchased
        shares = position_size_usd / max(0.01, eff_price)

        # Resolution evaluation
        won = MarketResolutionHelper.is_bucket_winner(outcome_bucket, actual_max_temp)

        # $1 per winning share, $0 for losing share
        gross_payoff = shares * 1.0 if won else 0.0
        total_cost = position_size_usd + fees

        # Net PnL = Payoff - Initial Capital Invested - Transaction Fees
        net_pnl = gross_payoff - total_cost
        roi_pct = (net_pnl / max(0.01, total_cost)) * 100.0

        return SettledTrade(
            trade_id=trade_id,
            market_id=market_id,
            target_date=target_date,
            outcome_label=outcome_bucket.raw_label,
            entry_price=round(eff_price, 4),
            position_size_usd=round(position_size_usd, 2),
            shares=round(shares, 4),
            fees=round(fees, 4),
            slippage=round(slippage, 4),
            actual_max_temp=actual_max_temp,
            won=won,
            gross_payoff=round(gross_payoff, 4),
            net_pnl=round(net_pnl, 4),
            roi_pct=round(roi_pct, 2),
        )
