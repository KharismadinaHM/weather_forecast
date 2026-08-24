"""Edge and Expected Value calculation engine (PLAN.md Section 12)."""

from dataclasses import dataclass

from app.trading.costs import ExecutionCostEstimator


@dataclass(frozen=True)
class OpportunityEvaluation:
    """Valuation analysis for a single market outcome."""

    outcome_label: str
    model_probability: float
    market_probability: float
    gross_edge: float
    effective_entry_price: float
    fees: float
    slippage: float
    net_ev: float
    is_positive_ev: bool
    is_actionable: bool
    rationale: str

    def to_dict(self) -> dict[str, float | str | bool]:
        return {
            "outcome_label": self.outcome_label,
            "model_probability": self.model_probability,
            "market_probability": self.market_probability,
            "gross_edge": self.gross_edge,
            "effective_entry_price": self.effective_entry_price,
            "fees": self.fees,
            "slippage": self.slippage,
            "net_ev": self.net_ev,
            "is_positive_ev": self.is_positive_ev,
            "is_actionable": self.is_actionable,
            "rationale": self.rationale,
        }


class EdgeEngine:
    """Calculates statistical edge and net expected value against Polymarket binary outcomes."""

    DEFAULT_MIN_EDGE: float = 0.10  # Minimum gross edge threshold (raised to reduce false signals)
    DEFAULT_MIN_NET_EV: float = 0.07  # Minimum net expected value threshold

    def __init__(
        self,
        min_edge: float = DEFAULT_MIN_EDGE,
        min_net_ev: float = DEFAULT_MIN_NET_EV,
        cost_estimator: ExecutionCostEstimator | None = None,
    ) -> None:
        self.min_edge = min_edge
        self.min_net_ev = min_net_ev
        self.cost_estimator = cost_estimator or ExecutionCostEstimator()

    def evaluate_outcome(
        self,
        outcome_label: str,
        model_prob: float,
        market_price: float,
        bid_price: float | None = None,
        ask_price: float | None = None,
        order_size_usd: float = 1.0,
    ) -> OpportunityEvaluation:
        """Evaluate gross edge and net EV for a single prediction vs market price."""
        # 1. Gross edge calculation
        gross_edge = model_prob - market_price

        # 2. Execution cost estimation
        effective_price, fees, slippage = self.cost_estimator.estimate_effective_entry_price(
            market_price=market_price,
            bid_price=bid_price,
            ask_price=ask_price,
            order_size_usd=order_size_usd,
        )

        # 3. Net Expected Value for  binary contract:
        # EV = P(win) * ( - entry_price) - P(loss) * entry_price - fees - slippage
        #    = P(win) - entry_price - fees - slippage
        net_ev = model_prob - market_price - fees - slippage

        is_pos_ev = net_ev > 0.0
        is_actionable = (gross_edge >= self.min_edge) and (net_ev >= self.min_net_ev)

        if is_actionable:
            rationale = (
                f"Actionable opportunity: Gross Edge {gross_edge:+.2%} >= {self.min_edge:.1%}, "
                f"Net EV {net_ev:+.2%} >= {self.min_net_ev:.1%}"
            )
        elif is_pos_ev:
            rationale = (
                f"Positive EV ({net_ev:+.2%}) below threshold (Min Edge {self.min_edge:.1%}, "
                f"Min Net EV {self.min_net_ev:.1%})"
            )

        else:
            rationale = f"Negative or negligible EV ({net_ev:+.2%})"

        return OpportunityEvaluation(
            outcome_label=outcome_label,
            model_probability=model_prob,
            market_probability=market_price,
            gross_edge=gross_edge,
            effective_entry_price=effective_price,
            fees=fees,
            slippage=slippage,
            net_ev=net_ev,
            is_positive_ev=is_pos_ev,
            is_actionable=is_actionable,
            rationale=rationale,
        )

    def evaluate_market_distribution(
        self,
        model_probs: dict[str, float],
        market_prices: dict[str, float],
        order_size_usd: float = 1.0,
    ) -> list[OpportunityEvaluation]:
        """Evaluate all outcome opportunities across a single market."""
        evaluations: list[OpportunityEvaluation] = []

        for outcome, m_prob in model_probs.items():
            price = market_prices.get(outcome, 0.0)
            if price <= 0.0:
                continue

            eval_res = self.evaluate_outcome(
                outcome_label=outcome,
                model_prob=m_prob,
                market_price=price,
                order_size_usd=order_size_usd,
            )
            evaluations.append(eval_res)

        # Sort descending by net expected value
        evaluations.sort(key=lambda x: x.net_ev, reverse=True)
        return evaluations
