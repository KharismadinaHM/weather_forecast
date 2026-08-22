"""Deterministic Risk Engine with absolute veto authority (PLAN.md Section 13)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.storage.models import PaperTrade

logger = get_logger("risk_engine")


@dataclass(frozen=True)
class RiskDecision:
    """Structured decision output from the deterministic risk engine."""

    allowed: bool
    decision: str  # 'BUY', 'SKIP', 'HOLD'
    reason: str
    recommended_size: float
    recommended_price: float
    risk_limit: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "decision": self.decision,
            "reason": self.reason,
            "recommended_size": self.recommended_size,
            "recommended_price": self.recommended_price,
            "risk_limit": self.risk_limit,
        }


class RiskEngine:
    """Deterministic Risk Engine enforcing bankroll limits and trade guardrails."""

    # Default Research Risk Parameters (PLAN.md Section 13)
    DEFAULT_BANKROLL: float = 15.0
    DEFAULT_MAX_TRADE: float = 1.0
    DEFAULT_MAX_DAILY_RISK: float = 2.0
    DEFAULT_MAX_OPEN_POSITIONS: int = 2
    DEFAULT_MAX_PRICE_AGE_SECONDS: int = 3600  # Stale data threshold (1 hour)
    DEFAULT_MIN_LIQUIDITY_USD: float = 10.0

    def __init__(
        self,
        bankroll: float = DEFAULT_BANKROLL,
        max_trade: float = DEFAULT_MAX_TRADE,
        max_daily_risk: float = DEFAULT_MAX_DAILY_RISK,
        max_open_positions: int = DEFAULT_MAX_OPEN_POSITIONS,
        max_price_age_seconds: int = DEFAULT_MAX_PRICE_AGE_SECONDS,
        min_liquidity_usd: float = DEFAULT_MIN_LIQUIDITY_USD,
        is_paused: bool = False,
    ) -> None:
        self.bankroll = bankroll
        self.max_trade = max_trade
        self.max_daily_risk = max_daily_risk
        self.max_open_positions = max_open_positions
        self.max_price_age_seconds = max_price_age_seconds
        self.min_liquidity_usd = min_liquidity_usd
        self.is_paused = is_paused

    def pause(self) -> None:
        """Activate kill-switch / pause execution immediately."""
        self.is_paused = True
        logger.warning("Risk engine paused (Kill Switch ACTIVE)")

    def resume(self) -> None:
        """Resume execution."""
        self.is_paused = False
        logger.info("Risk engine resumed")

    def check_trade(
        self,
        session: Session,
        market_id: str,
        outcome_label: str,
        entry_price: float,
        proposed_size: float = 1.0,
        price_timestamp: datetime | None = None,
        volume_24h: float | None = None,
        as_of_time: datetime | None = None,
    ) -> RiskDecision:
        """Evaluate proposed trade against deterministic risk limits.

        Returns RiskDecision with ALLOW or DENY (SKIP).
        """
        now = as_of_time or datetime.now(UTC)
        now_aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)

        # 1. Kill switch / Pause check
        if self.is_paused:
            return RiskDecision(
                allowed=False,
                decision="SKIP",
                reason="Kill switch is active (execution paused)",
                recommended_size=0.0,
                recommended_price=entry_price,
                risk_limit=0.0,
            )

        # 2. Stale data protection (Section 13)
        if price_timestamp is not None:
            ts_aware = (
                price_timestamp
                if price_timestamp.tzinfo is not None
                else price_timestamp.replace(tzinfo=UTC)
            )
            age_seconds = (now_aware - ts_aware).total_seconds()
            if age_seconds > self.max_price_age_seconds:
                return RiskDecision(
                    allowed=False,
                    decision="SKIP",
                    reason=(
                        f"Stale price rejected (age {age_seconds:.0f}s > "
                        f"{self.max_price_age_seconds}s)"
                    ),
                    recommended_size=0.0,
                    recommended_price=entry_price,
                    risk_limit=0.0,
                )

        # 3. Liquidity minimum protection (Section 13)
        if volume_24h is not None and volume_24h < self.min_liquidity_usd:
            return RiskDecision(
                allowed=False,
                decision="SKIP",
                reason=(
                    f"Insufficient liquidity (${volume_24h:.2f} < ${self.min_liquidity_usd:.2f})"
                ),
                recommended_size=0.0,
                recommended_price=entry_price,
                risk_limit=0.0,
            )

        # 4. Open position count limit (Section 13: MAX_OPEN_POSITIONS = 2)
        open_pos_count = (
            session.scalar(select(func.count(PaperTrade.id)).where(PaperTrade.status == "OPEN"))
            or 0
        )

        if open_pos_count >= self.max_open_positions:
            return RiskDecision(
                allowed=False,
                decision="SKIP",
                reason=(
                    f"Max open positions limit reached ({open_pos_count} >= "
                    f"{self.max_open_positions})"
                ),
                recommended_size=0.0,
                recommended_price=entry_price,
                risk_limit=self.max_trade,
            )

        # 5. Daily cumulative risk limit (Section 13: MAX_DAILY_RISK = $2)
        day_start = now_aware - timedelta(hours=24)
        daily_committed = (
            session.scalar(
                select(func.coalesce(func.sum(PaperTrade.position_size), 0.0)).where(
                    PaperTrade.opened_at >= day_start,
                    PaperTrade.status.in_(["OPEN", "CLOSED"]),
                )
            )
            or 0.0
        )

        effective_trade_size = min(proposed_size, self.max_trade)
        if daily_committed + effective_trade_size > self.max_daily_risk:
            remaining_daily = max(0.0, self.max_daily_risk - daily_committed)
            if remaining_daily <= 0.05:
                return RiskDecision(
                    allowed=False,
                    decision="SKIP",
                    reason=(
                        f"Daily risk budget exhausted (${daily_committed:.2f} >= "
                        f"${self.max_daily_risk:.2f})"
                    ),
                    recommended_size=0.0,
                    recommended_price=entry_price,
                    risk_limit=self.max_daily_risk,
                )
            effective_trade_size = remaining_daily

        # 6. Trade size bounds (Section 13: MAX_TRADE = $1)
        if effective_trade_size > self.max_trade:
            effective_trade_size = self.max_trade

        # Trade approved!
        return RiskDecision(
            allowed=True,
            decision="BUY",
            reason="Trade approved by risk engine within risk parameters",
            recommended_size=round(effective_trade_size, 2),
            recommended_price=round(entry_price, 4),
            risk_limit=self.max_daily_risk,
        )
