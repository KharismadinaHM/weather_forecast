"""Paper Trading execution tracker and lifecycle manager (PLAN.md Section 23)."""

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.simulator import MarketResolutionHelper, SettledTrade
from app.collectors.bucket_parser import BucketParser
from app.logging_config import get_logger
from app.storage.models import PaperTrade, PolymarketMarket, Signal, WeatherDaily

logger = get_logger("paper_tracker")


class PaperTradingTracker:
    """Manages the full lifecycle of forward paper trading positions and resolutions."""

    @classmethod
    def open_paper_trade(
        cls,
        session: Session,
        signal_id: int,
        entry_price: float,
        position_size: float = 1.0,
        fees: float = 0.005,
        slippage: float = 0.005,
        opened_at: datetime | None = None,
    ) -> PaperTrade:
        """Record an open paper trade from an approved BUY signal."""
        trade = PaperTrade(
            signal_id=signal_id,
            entry_price=entry_price,
            position_size=position_size,
            fees=fees,
            slippage=slippage,
            status="OPEN",
            opened_at=opened_at or datetime.now(UTC),
        )
        session.add(trade)
        session.flush()
        logger.info(
            "Opened paper trade",
            trade_id=trade.id,
            signal_id=signal_id,
            size=position_size,
            entry_price=entry_price,
        )
        return trade

    @classmethod
    def resolve_paper_trades_for_date(
        cls,
        session: Session,
        target_date: date,
        actual_max_temp: float | None = None,
    ) -> list[SettledTrade]:
        """Resolve all open paper trades whose target date has passed."""
        now = datetime.now(UTC)

        actual_temp = actual_max_temp
        if actual_temp is None:
            daily_obs = session.scalars(
                select(WeatherDaily).where(
                    WeatherDaily.date == target_date,
                    WeatherDaily.station == "Hong Kong Observatory",
                )
            ).first()
            if daily_obs and daily_obs.max_temperature is not None:
                actual_temp = daily_obs.max_temperature

        if actual_temp is None:
            logger.info("No ground-truth temperature found", target_date=target_date)
            return []

        open_trades_stmt = (
            select(PaperTrade)
            .join(Signal, PaperTrade.signal_id == Signal.id)
            .where(PaperTrade.status == "OPEN")
        )
        open_trades = session.scalars(open_trades_stmt).all()

        settled_results: list[SettledTrade] = []

        for trade in open_trades:
            sig = trade.signal
            if not sig or not sig.prediction:
                continue

            pred = sig.prediction
            market = session.get(PolymarketMarket, pred.market_id)
            if not market or market.target_date != target_date:
                continue

            parsed_list = BucketParser.parse_bucket_schema([pred.outcome])
            if not parsed_list:
                continue
            bucket = parsed_list[0]
            won = MarketResolutionHelper.is_bucket_winner(bucket, actual_temp)

            effective_entry = trade.entry_price + (trade.slippage or 0.0)
            shares = trade.position_size / max(0.01, effective_entry)
            gross_payoff = shares * 1.0 if won else 0.0
            total_cost = trade.position_size + (trade.fees or 0.0)
            net_pnl = gross_payoff - total_cost
            roi = (net_pnl / max(0.01, total_cost)) * 100.0

            trade.status = "CLOSED"
            trade.pnl = round(net_pnl, 4)
            trade.closed_at = now
            session.add(trade)

            settled = SettledTrade(
                trade_id=str(trade.id),
                market_id=market.market_id,
                target_date=target_date,
                outcome_label=pred.outcome,
                entry_price=round(effective_entry, 4),
                position_size_usd=trade.position_size,
                shares=round(shares, 4),
                fees=trade.fees or 0.0,
                slippage=trade.slippage or 0.0,
                actual_max_temp=actual_temp,
                won=won,
                gross_payoff=round(gross_payoff, 4),
                net_pnl=round(net_pnl, 4),
                roi_pct=round(roi, 2),
            )
            settled_results.append(settled)

        session.commit()
        return settled_results
