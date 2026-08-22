"""Trading execution, prediction cycle, and automated alert jobs (PLAN.md Section 14 & 15)."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.bucket_parser import BucketParser
from app.features.builder import DatasetBuilder
from app.logging_config import get_logger
from app.ml.models import WeatherMLModel
from app.storage.db import get_db_session
from app.storage.models import PolymarketMarket, Prediction
from app.telegram.client import TelegramClient
from app.telegram.formatter import TelegramFormatter
from app.trading.edge import EdgeEngine
from app.trading.engine import SignalGenerator
from app.trading.risk import RiskEngine

logger = get_logger("trading_jobs")


def run_prediction_and_signals_job(
    session: Session | None = None,
    model: WeatherMLModel | None = None,
    edge_engine: EdgeEngine | None = None,
    risk_engine: RiskEngine | None = None,
    telegram_client: TelegramClient | None = None,
) -> int:
    """Execute prediction cycle across all active markets and generate risk-checked signals."""
    logger.info("Starting prediction and signal generation job")
    t_client = telegram_client or TelegramClient()
    s_generator = SignalGenerator(edge_engine=edge_engine, risk_engine=risk_engine)

    def _execute(sess: Session) -> int:
        total_signals = 0
        active_markets = sess.scalars(
            select(PolymarketMarket).where(PolymarketMarket.status == "active")
        ).all()

        if not active_markets:
            logger.info("No active markets to process")
            return 0

        ml_model = model or WeatherMLModel(n_estimators=50, learning_rate=0.05)

        for m in active_markets:
            try:
                outcome_labels = [o.outcome_label for o in m.outcomes]
                buckets = BucketParser.parse_bucket_schema(outcome_labels)

                feature_row = DatasetBuilder.build_feature_row(
                    session=sess,
                    target_date=m.target_date,
                    decision_timestamp=datetime.now(UTC),
                )

                if ml_model.is_fitted:
                    model_probs = ml_model.predict_buckets(feature_row, buckets)
                else:
                    uniform_p = 1.0 / max(1, len(buckets))
                    model_probs = {b.raw_label: uniform_p for b in buckets}

                results = s_generator.process_market_signals(
                    session=sess,
                    market_id=m.market_id,
                    model_probs=model_probs,
                    model_version="weather-v001",
                )
                total_signals += len(results)

                buy_signals = [(p, s) for p, s in results if s.decision == "BUY"]
                for pred, sig in buy_signals:
                    opp_eval = s_generator.edge_engine.evaluate_outcome(
                        outcome_label=pred.outcome,
                        model_prob=pred.model_probability,
                        market_price=pred.market_probability,
                    )
                    alert_text = TelegramFormatter.format_opportunity_alert(
                        market_question=m.question,
                        target_date=m.target_date,
                        opportunity=opp_eval,
                        recommended_size=sig.recommended_size or 0.0,
                        model_version=pred.model_version,
                    )
                    asyncio.run(t_client.send_message(alert_text))

            except Exception as exc:
                logger.error(
                    "Error generating predictions for market",
                    market_id=m.market_id,
                    error=str(exc),
                )
        return total_signals

    if session is not None:
        return _execute(session)
    with get_db_session() as db_sess:
        return _execute(db_sess)


def run_daily_summary_job(
    session: Session | None = None,
    telegram_client: TelegramClient | None = None,
) -> bool:
    """Send 07:00 HKT morning daily summary message to Telegram (Section 14 & 15)."""
    logger.info("Starting daily Telegram summary job")
    t_client = telegram_client or TelegramClient()
    today_hkt = (datetime.now(UTC) + timedelta(hours=8)).date()

    def _execute(sess: Session) -> bool:
        market = sess.scalars(
            select(PolymarketMarket)
            .where(PolymarketMarket.target_date == today_hkt)
            .order_by(PolymarketMarket.created_at.desc())
        ).first()

        if not market:
            logger.info("No market found for today's daily summary", target_date=today_hkt)
            return False

        preds = sess.scalars(
            select(Prediction)
            .where(Prediction.market_id == market.market_id)
            .order_by(Prediction.prediction_timestamp.desc())
            .limit(10)
        ).all()

        if not preds:
            logger.info("No predictions found for daily summary")
            return False

        model_dist = {p.outcome: p.model_probability for p in preds}
        best_p = max(preds, key=lambda x: x.expected_value or -999.0)
        best_opp = (
            SignalGenerator().edge_engine.evaluate_outcome(
                outcome_label=best_p.outcome,
                model_prob=best_p.model_probability,
                market_price=best_p.market_probability,
            )
            if best_p.edge and best_p.edge >= 0.08
            else None
        )

        dec_str = "BUY" if (best_opp and best_opp.is_actionable) else "HOLD"
        risk_alloc = 1.0 if dec_str == "BUY" else 0.0

        summary_msg = TelegramFormatter.format_daily_summary(
            target_date=today_hkt,
            model_distribution=model_dist,
            best_opportunity=best_opp,
            decision=dec_str,
            risk_allocation=risk_alloc,
            model_version=preds[0].model_version,
        )

        return asyncio.run(t_client.send_message(summary_msg))

    if session is not None:
        return _execute(session)
    with get_db_session() as db_sess:
        return _execute(db_sess)


def run_missing_market_alert_job(
    session: Session | None = None,
    telegram_client: TelegramClient | None = None,
) -> bool:
    """Check if Polymarket market is missing by 18:00 HKT cutoff (Section 15)."""
    logger.info("Checking missing market cutoff")
    t_client = telegram_client or TelegramClient()
    tomorrow_hkt = (datetime.now(UTC) + timedelta(hours=8)).date() + timedelta(days=1)

    def _execute(sess: Session) -> bool:
        market = sess.scalars(
            select(PolymarketMarket).where(PolymarketMarket.target_date == tomorrow_hkt)
        ).first()

        if not market:
            logger.warning("Missing market alert triggered", target_date=tomorrow_hkt)
            alert_msg = TelegramFormatter.format_missing_market_alert(tomorrow_hkt)
            return asyncio.run(t_client.send_message(alert_msg))
        return True

    if session is not None:
        return _execute(session)
    with get_db_session() as db_sess:
        return _execute(db_sess)
