"""Trading Signal Generation Engine (PLAN.md Section 11, 12 & 13)."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.storage.models import PolymarketMarket, PolymarketPrice, Prediction, Signal
from app.trading.edge import EdgeEngine
from app.trading.risk import RiskEngine

logger = get_logger("signal_generator")


class SignalGenerator:
    """Orchestrates model probability integration, edge valuation, and risk checking."""

    def __init__(
        self,
        edge_engine: EdgeEngine | None = None,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self.edge_engine = edge_engine or EdgeEngine()
        self.risk_engine = risk_engine or RiskEngine()

    def process_market_signals(
        self,
        session: Session,
        market_id: str,
        model_probs: dict[str, float],
        model_version: str = "lgbm_v1.0",
        confidence: float | None = None,
        as_of_time: datetime | None = None,
    ) -> list[tuple[Prediction, Signal]]:
        """Evaluate a market's outcome probabilities against live prices to emit signals."""

        now = as_of_time or datetime.now(UTC)

        # 1. Fetch market metadata and latest prices
        market = session.get(PolymarketMarket, market_id)
        if not market:
            logger.warning("Market not found for signal generation", market_id=market_id)
            return []

        # Query latest price for each outcome of this market
        latest_prices_stmt = (
            select(PolymarketPrice)
            .where(PolymarketPrice.market_id == market_id)
            .order_by(PolymarketPrice.timestamp.desc())
        )
        all_prices = session.scalars(latest_prices_stmt).all()

        price_by_label: dict[str, float] = {}
        price_ts_by_label: dict[str, datetime] = {}
        volume_by_label: dict[str, float] = {}

        for p in all_prices:
            # Map by outcome label via outcomes relationship or token_id
            outcome_match = next((o for o in market.outcomes if o.token_id == p.token_id), None)
            if outcome_match and outcome_match.outcome_label not in price_by_label:
                price_by_label[outcome_match.outcome_label] = p.price
                price_ts_by_label[outcome_match.outcome_label] = p.timestamp
                if p.volume is not None:
                    volume_by_label[outcome_match.outcome_label] = p.volume

        if not price_by_label:
            logger.info("No prices found for market", market_id=market_id)
            return []

        # 2. Evaluate Edge and Expected Value across outcomes
        evaluations = self.edge_engine.evaluate_market_distribution(
            model_probs=model_probs,
            market_prices=price_by_label,
        )

        results: list[tuple[Prediction, Signal]] = []

        for ev in evaluations:
            # Create Prediction record (DB Section 7)
            pred_record = Prediction(
                market_id=market_id,
                prediction_timestamp=now,
                model_version=model_version,
                outcome=ev.outcome_label,
                model_probability=ev.model_probability,
                market_probability=ev.market_probability,
                edge=ev.gross_edge,
                expected_value=ev.net_ev,
                confidence=confidence,
            )
            session.add(pred_record)
            session.flush()  # Populate pred_record.id

            # 3. Evaluate Risk Engine Guardrails
            price_ts = price_ts_by_label.get(ev.outcome_label)
            volume_val = volume_by_label.get(ev.outcome_label)

            if ev.is_actionable:
                # Opportunity has edge & positive EV -> Check risk engine
                risk_res = self.risk_engine.check_trade(
                    session=session,
                    market_id=market_id,
                    outcome_label=ev.outcome_label,
                    entry_price=ev.market_probability,
                    proposed_size=1.0,
                    price_timestamp=price_ts,
                    volume_24h=volume_val,
                    as_of_time=now,
                )

                if risk_res.allowed:
                    decision_str = "BUY"
                    reason_str = f"{ev.rationale}. {risk_res.reason}"
                else:
                    decision_str = "SKIP"
                    reason_str = f"Actionable EV rejected by risk engine: {risk_res.reason}"

                sig_record = Signal(
                    prediction_id=pred_record.id,
                    decision=decision_str,
                    reason=reason_str,
                    recommended_price=risk_res.recommended_price,
                    recommended_size=risk_res.recommended_size,
                    risk_limit=risk_res.risk_limit,
                    created_at=now,
                )
            else:
                # Not actionable -> HOLD/SKIP
                sig_record = Signal(
                    prediction_id=pred_record.id,
                    decision="HOLD",
                    reason=ev.rationale,
                    recommended_price=ev.market_probability,
                    recommended_size=0.0,
                    risk_limit=0.0,
                    created_at=now,
                )

            session.add(sig_record)
            results.append((pred_record, sig_record))

        session.commit()
        logger.info(
            "Signals processed for market",
            market_id=market_id,
            signal_count=len(results),
            actionable_count=sum(1 for _, s in results if s.decision == "BUY"),
        )
        return results
