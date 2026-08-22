"""Execution fee and slippage estimation models (PLAN.md Section 11 & 12)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FeeModel:
    """Polymarket exchange fee structure."""

    taker_fee_rate: float = 0.0  # Polymarket CTF currently 0% fee on basic orders
    maker_fee_rate: float = 0.0
    gas_cost_usd: float = 0.005  # Estimated amortized L2 polygon gas cost per transaction

    def calculate_fees(self, order_size_usd: float, is_taker: bool = True) -> float:
        """Calculate total transaction fees for a given order size."""
        fee_rate = self.taker_fee_rate if is_taker else self.maker_fee_rate
        variable_fee = order_size_usd * fee_rate
        return float(variable_fee + self.gas_cost_usd)


@dataclass(frozen=True)
class SlippageModel:
    """Market microstructure slippage estimator based on spread and order size."""

    base_slippage: float = 0.005  # Base minimum expected slippage (0.5%)
    spread_impact: float = 0.5  # Half-spread traversal fraction

    def estimate_slippage(
        self,
        market_price: float,
        bid_price: float | None = None,
        ask_price: float | None = None,
        order_size_usd: float = 1.0,
    ) -> float:
        """Estimate price slippage per share based on observed bid-ask spread."""
        if bid_price is not None and ask_price is not None and ask_price > bid_price:
            spread = ask_price - bid_price
            slippage = max(self.base_slippage, self.spread_impact * spread)
        else:
            # Fallback based on market price magnitude
            slippage = self.base_slippage + (0.01 if order_size_usd > 5.0 else 0.0)

        return float(slippage)


class ExecutionCostEstimator:
    """Combines fee and slippage models to compute net execution costs."""

    def __init__(
        self,
        fee_model: FeeModel | None = None,
        slippage_model: SlippageModel | None = None,
    ) -> None:
        self.fee_model = fee_model or FeeModel()
        self.slippage_model = slippage_model or SlippageModel()

    def estimate_effective_entry_price(
        self,
        market_price: float,
        bid_price: float | None = None,
        ask_price: float | None = None,
        order_size_usd: float = 1.0,
    ) -> tuple[float, float, float]:
        """Compute effective entry price, fees, and estimated slippage per unit.

        Returns: (effective_entry_price, fee_per_unit, slippage_per_unit)
        """
        slippage = self.slippage_model.estimate_slippage(
            market_price, bid_price, ask_price, order_size_usd
        )
        total_fees = self.fee_model.calculate_fees(order_size_usd)
        fee_per_unit = total_fees / max(1.0, order_size_usd) * market_price

        effective_price = market_price + slippage + fee_per_unit
        return float(effective_price), float(total_fees), float(slippage)
