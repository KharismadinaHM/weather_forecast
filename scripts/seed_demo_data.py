"""Seed realistic historical Polymarket weather markets, predictions, and trades."""

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.bucket_parser import BucketParser
from app.logging_config import get_logger
from app.storage.db import get_db_session
from app.storage.models import (
    PaperTrade,
    PolymarketMarket,
    PolymarketOutcome,
    PolymarketPrice,
    Prediction,
    Signal,
    WeatherDaily,
)

logger = get_logger("seed_demo")


def seed_demo_data(session: Session) -> None:
    """Generate realistic demonstration data for dashboard visualization."""
    now = datetime.now(UTC)
    today = (now + timedelta(hours=8)).date()

    logger.info("Starting demo data generation")

    # 1. Ensure Daily Historical Observations exist for the past 14 days
    for day_offset in range(14, 0, -1):
        hist_date = today - timedelta(days=day_offset)
        existing_daily = session.scalars(
            select(WeatherDaily).where(
                WeatherDaily.date == hist_date,
                WeatherDaily.station == "Hong Kong Observatory",
            )
        ).first()

        if not existing_daily:
            # Hong Kong August realistic temps (31-34°C)
            max_t = round(random.uniform(31.2, 34.5), 1)
            min_t = round(max_t - random.uniform(4.5, 6.5), 1)
            session.add(
                WeatherDaily(
                    date=hist_date,
                    station="Hong Kong Observatory",
                    max_temperature=max_t,
                    min_temperature=min_t,
                    mean_temperature=round((max_t + min_t) / 2, 1),
                    total_rainfall=round(random.choice([0.0, 0.0, 1.5, 12.0]), 1),
                )
            )

    # 2. Create 5 Polymarket Markets (Past resolved + Today Active + Future)
    bucket_schemas = ["<=31°C", "32°C", "33°C", "34°C", ">=35°C"]

    for m_idx in range(-3, 2):  # -3, -2, -1 (past), 0 (today/active), 1 (tomorrow)
        target_d = today + timedelta(days=m_idx)
        market_id = f"poly_hk_{target_d.strftime('%Y%m%d')}"
        is_past = m_idx < 0

        existing_mkt = session.get(PolymarketMarket, market_id)
        if not existing_mkt:
            mkt = PolymarketMarket(
                market_id=market_id,
                event_id=f"evt_hk_{target_d.strftime('%Y%m%d')}",
                slug=f"highest-temperature-hong-kong-{target_d.strftime('%B-%d-%Y').lower()}",
                question=f"Highest temperature in Hong Kong on {target_d.strftime('%B %d, %Y')}?",
                market_type="temperature_high",
                target_date=target_d,
                status="closed" if is_past else "active",
                outcome_bucket_schema=bucket_schemas,
                resolution_source_raw="https://www.hko.gov.hk - HKO Daily Extract",
            )
            session.add(mkt)
            session.flush()
        else:
            mkt = existing_mkt
            mkt.market_type = "temperature_high"
            session.flush()

        # Create outcomes and price time-series
        for idx, b_label in enumerate(bucket_schemas):
            token_id = f"tok_{market_id}_{idx}"
            out_obj = session.scalars(
                select(PolymarketOutcome).where(
                    PolymarketOutcome.market_id == market_id,
                    PolymarketOutcome.token_id == token_id,
                )
            ).first()

            if not out_obj:
                parsed = BucketParser.parse_bucket_schema([b_label])[0]
                out_obj = PolymarketOutcome(
                    market_id=market_id,
                    token_id=token_id,
                    outcome_label=b_label,
                    outcome_bucket_low=parsed.low,
                    outcome_bucket_high=parsed.high,
                    outcome_value=str(idx),
                )
                session.add(out_obj)
                session.flush()

            # Generate price time-series curve (past 12 hours)
            base_price = 0.20 + (0.15 if b_label in ["32°C", "33°C"] else -0.05)
            for h_offset in range(12, 0, -1):
                p_ts = now - timedelta(hours=h_offset) + timedelta(days=m_idx)
                p_val = max(0.02, min(0.95, base_price + random.uniform(-0.04, 0.05)))
                session.add(
                    PolymarketPrice(
                        market_id=market_id,
                        token_id=token_id,
                        timestamp=p_ts,
                        price=round(p_val, 3),
                    )
                )

            # Generate Predictions and Signals
            model_p = (
                0.15 + (0.30 if b_label in ["32°C", "33°C"] else 0.05) + random.uniform(-0.02, 0.04)
            )
            mkt_p = base_price
            edge_val = model_p - mkt_p
            net_ev = (model_p * (1.0 - 0.01)) - (mkt_p * (1.0 + 0.01))

            pred = Prediction(
                market_id=market_id,
                prediction_timestamp=now - timedelta(hours=1) + timedelta(days=m_idx),
                model_version="weather-v001",
                outcome=b_label,
                model_probability=round(model_p, 3),
                market_probability=round(mkt_p, 3),
                edge=round(edge_val, 3),
                expected_value=round(net_ev, 3),
            )
            session.add(pred)
            session.flush()

            is_buy = edge_val >= 0.08 and net_ev >= 0.05
            sig = Signal(
                prediction_id=pred.id,
                decision="BUY" if is_buy else "HOLD",
                reason="Positive EV & actionable statistical edge"
                if is_buy
                else "Edge below threshold",
                recommended_price=round(mkt_p, 3) if is_buy else None,
                recommended_size=1.0 if is_buy else 0.0,
                risk_limit=2.0,
                created_at=pred.prediction_timestamp,
            )

            session.add(sig)
            session.flush()

            # If BUY signal and market is past, create resolved paper trade
            if is_buy:
                trade_won = b_label in ["32°C", "33°C"]
                shares = 1.0 / max(0.01, mkt_p + 0.005)
                pnl_val = (shares * 1.0 - 1.01) if trade_won else -1.01

                paper = PaperTrade(
                    signal_id=sig.id,
                    entry_price=round(mkt_p, 3),
                    position_size=1.0,
                    fees=0.005,
                    slippage=0.005,
                    pnl=round(pnl_val, 2) if is_past else None,
                    status="CLOSED" if is_past else "OPEN",
                    opened_at=pred.prediction_timestamp,
                    closed_at=(pred.prediction_timestamp + timedelta(hours=18))
                    if is_past
                    else None,
                )
                session.add(paper)

    # 3. Create Lowest Temperature Markets for Today and Tomorrow
    low_bucket_schemas = ["<=26°C", "27°C", "28°C", ">=29°C"]
    for m_idx in range(0, 2):
        target_d = today + timedelta(days=m_idx)
        market_id = f"poly_hk_low_{target_d.strftime('%Y%m%d')}"

        existing_mkt = session.get(PolymarketMarket, market_id)
        if not existing_mkt:
            mkt = PolymarketMarket(
                market_id=market_id,
                event_id=f"evt_hk_low_{target_d.strftime('%Y%m%d')}",
                slug=f"lowest-temperature-hong-kong-{target_d.strftime('%B-%d-%Y').lower()}",
                question=f"Lowest temperature in Hong Kong on {target_d.strftime('%B %d, %Y')}?",
                market_type="temperature_low",
                target_date=target_d,
                status="active",
                outcome_bucket_schema=low_bucket_schemas,
                resolution_source_raw="https://www.hko.gov.hk - HKO Daily Extract",
            )
            session.add(mkt)
            session.flush()
        else:
            mkt = existing_mkt
            mkt.market_type = "temperature_low"
            session.flush()

        for idx, b_label in enumerate(low_bucket_schemas):
            token_id = f"tok_{market_id}_{idx}"
            out_obj = session.scalars(
                select(PolymarketOutcome).where(
                    PolymarketOutcome.market_id == market_id,
                    PolymarketOutcome.token_id == token_id,
                )
            ).first()

            if not out_obj:
                parsed = BucketParser.parse_bucket_schema([b_label])[0]
                out_obj = PolymarketOutcome(
                    market_id=market_id,
                    token_id=token_id,
                    outcome_label=b_label,
                    outcome_bucket_low=parsed.low,
                    outcome_bucket_high=parsed.high,
                    outcome_value=str(idx),
                )
                session.add(out_obj)
                session.flush()

            base_price = 0.25 + (0.20 if b_label == "27°C" else -0.05)
            session.add(
                PolymarketPrice(
                    market_id=market_id,
                    token_id=token_id,
                    timestamp=now - timedelta(hours=1),
                    price=round(base_price, 3),
                )
            )

            model_p = 0.20 + (0.35 if b_label == "27°C" else 0.05) + random.uniform(-0.02, 0.03)
            mkt_p = base_price
            edge_val = model_p - mkt_p
            net_ev = (model_p * (1.0 - 0.01)) - (mkt_p * (1.0 + 0.01))

            pred = Prediction(
                market_id=market_id,
                prediction_timestamp=now - timedelta(hours=1) + timedelta(days=m_idx),
                model_version="weather-v001",
                outcome=b_label,
                model_probability=round(model_p, 3),
                market_probability=round(mkt_p, 3),
                edge=round(edge_val, 3),
                expected_value=round(net_ev, 3),
            )
            session.add(pred)
            session.flush()

            is_buy = edge_val >= 0.08 and net_ev >= 0.05
            sig = Signal(
                prediction_id=pred.id,
                decision="BUY" if is_buy else "HOLD",
                reason="Positive EV & actionable statistical edge (Min Temp)"
                if is_buy
                else "Edge below threshold",
                recommended_price=round(mkt_p, 3) if is_buy else None,
                recommended_size=1.0 if is_buy else 0.0,
                risk_limit=2.0,
                created_at=pred.prediction_timestamp,
            )
            session.add(sig)

    session.commit()
    logger.info("Demo data generation successfully completed")


if __name__ == "__main__":
    with get_db_session() as db_session:
        seed_demo_data(db_session)
    logger.info("Demo data successfully seeded into database")
