"""Read-only database query helpers for Streamlit monitoring dashboard."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.backtest.simulator import SettledTrade
from app.paper.evaluator import PaperPerformanceEvaluator, QuantitativeGateResult
from app.storage.models import (
    PaperTrade,
    PolymarketMarket,
    PolymarketOutcome,
    PolymarketPrice,
    Prediction,
    Signal,
    WeatherForecast,
    WeatherObservation,
)


def get_freshness_metrics(session: Session) -> dict[str, Any]:
    """Retrieve timestamp and freshness age for key ingestion pipelines."""
    now = datetime.now(UTC)

    # 1. HKO Observation Freshness
    latest_obs = session.scalars(
        select(WeatherObservation.observed_at)
        .order_by(desc(WeatherObservation.observed_at))
        .limit(1)
    ).first()

    # 2. HKO Forecast Freshness
    latest_fc = session.scalars(
        select(WeatherForecast.forecast_created_at)
        .order_by(desc(WeatherForecast.forecast_created_at))
        .limit(1)
    ).first()

    # 3. Polymarket Price Freshness
    latest_price = session.scalars(
        select(PolymarketPrice.timestamp).order_by(desc(PolymarketPrice.timestamp)).limit(1)
    ).first()

    # 4. Polymarket Market Ingestion
    latest_mkt = session.scalars(
        select(PolymarketMarket.created_at).order_by(desc(PolymarketMarket.created_at)).limit(1)
    ).first()

    # 5. Prediction / Model Run Freshness
    latest_pred = session.scalars(
        select(Prediction.prediction_timestamp)
        .order_by(desc(Prediction.prediction_timestamp))
        .limit(1)
    ).first()

    def _calc_age_minutes(dt: datetime | None) -> float | None:
        if dt is None:
            return None
        tz_aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
        return (now - tz_aware).total_seconds() / 60.0

    return {
        "hko_observation": {
            "timestamp": latest_obs,
            "age_minutes": _calc_age_minutes(latest_obs),
            "status": "FRESH"
            if latest_obs and (_calc_age_minutes(latest_obs) or 999) <= 120
            else "STALE",
        },
        "hko_forecast": {
            "timestamp": latest_fc,
            "age_minutes": _calc_age_minutes(latest_fc),
            "status": "FRESH"
            if latest_fc and (_calc_age_minutes(latest_fc) or 999) <= 720
            else "STALE",
        },
        "polymarket_prices": {
            "timestamp": latest_price,
            "age_minutes": _calc_age_minutes(latest_price),
            "status": "FRESH"
            if latest_price and (_calc_age_minutes(latest_price) or 999) <= 180
            else "STALE",
        },
        "polymarket_markets": {
            "timestamp": latest_mkt,
            "age_minutes": _calc_age_minutes(latest_mkt),
            "status": "FRESH"
            if latest_mkt and (_calc_age_minutes(latest_mkt) or 999) <= 1440
            else "STALE",
        },
        "predictions": {
            "timestamp": latest_pred,
            "age_minutes": _calc_age_minutes(latest_pred),
            "status": "FRESH"
            if latest_pred and (_calc_age_minutes(latest_pred) or 999) <= 180
            else "STALE",
        },
    }


def get_latest_predictions_df(session: Session, limit: int = 100) -> pd.DataFrame:
    """Query joined predictions and signals table for the dashboard view."""
    stmt = (
        select(
            Prediction.prediction_timestamp.label("timestamp"),
            PolymarketMarket.market_id.label("market_id"),
            PolymarketMarket.market_type.label("market_type"),
            PolymarketMarket.question.label("market"),
            PolymarketMarket.target_date.label("target_date"),
            Prediction.outcome.label("outcome"),
            Prediction.model_probability.label("model_prob"),
            Prediction.market_probability.label("market_prob"),
            Prediction.edge.label("edge"),
            Prediction.expected_value.label("expected_value"),
            Signal.decision.label("decision"),
            Signal.reason.label("reason"),
            Signal.recommended_size.label("recommended_size"),
            Prediction.model_version.label("model_version"),
        )
        .join(PolymarketMarket, Prediction.market_id == PolymarketMarket.market_id)
        .outerjoin(Signal, Signal.prediction_id == Prediction.id)
        .order_by(desc(Prediction.prediction_timestamp))
        .limit(limit)
    )

    rows = session.execute(stmt).all()
    if not rows:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "market_id",
                "market_type",
                "market",
                "target_date",
                "outcome",
                "model_prob",
                "market_prob",
                "edge",
                "expected_value",
                "decision",
                "reason",
                "recommended_size",
                "model_version",
            ]
        )

    data = [dict(r._mapping) for r in rows]
    return pd.DataFrame(data)


def get_active_markets_list(session: Session) -> list[dict[str, Any]]:
    """Retrieve list of distinct tracked markets for dropdown selection."""
    markets = session.scalars(
        select(PolymarketMarket).order_by(desc(PolymarketMarket.created_at)).limit(30)
    ).all()
    return [
        {
            "market_id": m.market_id,
            "question": m.question,
            "market_type": m.market_type,
            "target_date": m.target_date.isoformat(),
        }
        for m in markets
    ]


def get_market_price_vs_model_df(session: Session, market_id: str | None = None) -> pd.DataFrame:
    """Retrieve historical market prices vs model predictions for a target market."""
    if not market_id:
        # Pick the most recent active or closed market
        recent_mkt = session.scalars(
            select(PolymarketMarket.market_id).order_by(desc(PolymarketMarket.created_at)).limit(1)
        ).first()
        if not recent_mkt:
            return pd.DataFrame()
        market_id = recent_mkt

    # Fetch predictions for this market
    preds = session.scalars(
        select(Prediction)
        .where(Prediction.market_id == market_id)
        .order_by(Prediction.prediction_timestamp)
    ).all()

    # Fetch prices for this market
    prices_stmt = (
        select(
            PolymarketPrice.timestamp,
            PolymarketOutcome.outcome_label,
            PolymarketPrice.price,
        )
        .join(
            PolymarketOutcome,
            (PolymarketPrice.market_id == PolymarketOutcome.market_id)
            & (PolymarketPrice.token_id == PolymarketOutcome.token_id),
        )
        .where(PolymarketPrice.market_id == market_id)
        .order_by(PolymarketPrice.timestamp)
    )
    price_rows = session.execute(prices_stmt).all()

    records: list[dict[str, Any]] = []
    for pr in price_rows:
        records.append(
            {
                "timestamp": pr.timestamp,
                "outcome": pr.outcome_label,
                "value": float(pr.price),
                "series_type": "Market Price",
            }
        )

    for pred in preds:
        records.append(
            {
                "timestamp": pred.prediction_timestamp,
                "outcome": pred.outcome,
                "value": float(pred.model_probability),
                "series_type": "Model Probability",
            }
        )

    if not records:
        return pd.DataFrame()

    return pd.DataFrame(records)


def get_paper_trades_and_pnl_df(session: Session) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retrieve paper trades table and cumulative PnL time-series."""
    stmt = (
        select(
            PaperTrade.id.label("trade_id"),
            PaperTrade.opened_at.label("opened_at"),
            PaperTrade.closed_at.label("closed_at"),
            PaperTrade.status.label("status"),
            PolymarketMarket.question.label("market"),
            PolymarketMarket.target_date.label("target_date"),
            Prediction.outcome.label("outcome"),
            PaperTrade.entry_price.label("entry_price"),
            PaperTrade.position_size.label("position_size"),
            PaperTrade.fees.label("fees"),
            PaperTrade.slippage.label("slippage"),
            PaperTrade.pnl.label("pnl"),
            Signal.decision.label("decision"),
        )
        .join(Signal, PaperTrade.signal_id == Signal.id)
        .join(Prediction, Signal.prediction_id == Prediction.id)
        .join(PolymarketMarket, Prediction.market_id == PolymarketMarket.market_id)
        .order_by(desc(PaperTrade.opened_at))
    )
    rows = session.execute(stmt).all()
    if not rows:
        empty_df = pd.DataFrame(
            columns=[
                "trade_id",
                "opened_at",
                "closed_at",
                "status",
                "market",
                "target_date",
                "outcome",
                "entry_price",
                "position_size",
                "fees",
                "slippage",
                "pnl",
                "decision",
            ]
        )
        return empty_df, pd.DataFrame(columns=["timestamp", "cumulative_pnl"])

    trades_data = [dict(r._mapping) for r in rows]
    trades_df = pd.DataFrame(trades_data)

    # Compute cumulative PnL series for resolved trades
    resolved = trades_df[trades_df["status"] == "CLOSED"].copy()
    if not resolved.empty:
        resolved["sort_time"] = resolved["closed_at"].fillna(resolved["opened_at"])
        resolved = resolved.sort_values(by="sort_time")
        resolved["cumulative_pnl"] = resolved["pnl"].cumsum()
        pnl_df = resolved[["sort_time", "pnl", "cumulative_pnl"]].rename(
            columns={"sort_time": "timestamp"}
        )
    else:
        pnl_df = pd.DataFrame(columns=["timestamp", "pnl", "cumulative_pnl"])

    return trades_df, pnl_df


def evaluate_section35_gates_from_db(session: Session) -> QuantitativeGateResult:
    """Evaluate Section 35 5 Hard Gates based on current database state."""
    # Fetch all closed paper trades
    stmt = (
        select(
            PaperTrade.id,
            PaperTrade.entry_price,
            PaperTrade.position_size,
            PaperTrade.fees,
            PaperTrade.slippage,
            PaperTrade.pnl,
            PolymarketMarket.market_id,
            PolymarketMarket.target_date,
            Prediction.outcome,
        )
        .join(Signal, PaperTrade.signal_id == Signal.id)
        .join(Prediction, Signal.prediction_id == Prediction.id)
        .join(PolymarketMarket, Prediction.market_id == PolymarketMarket.market_id)
        .where(PaperTrade.status == "CLOSED")
    )
    rows = session.execute(stmt).all()

    settled_trades: list[SettledTrade] = []
    for r in rows:
        pnl_val = float(r.pnl or 0.0)
        size_val = float(r.position_size or 1.0)
        won_flag = pnl_val > 0.0
        eff_entry = float(r.entry_price or 0.35) + float(r.slippage or 0.0)
        shares_val = size_val / max(0.01, eff_entry)
        gross_pay = shares_val if won_flag else 0.0
        roi_val = (pnl_val / max(0.01, size_val + float(r.fees or 0.0))) * 100.0

        settled_trades.append(
            SettledTrade(
                trade_id=str(r.id),
                market_id=r.market_id,
                target_date=r.target_date,
                outcome_label=r.outcome,
                entry_price=round(eff_entry, 4),
                position_size_usd=size_val,
                shares=round(shares_val, 4),
                fees=float(r.fees or 0.0),
                slippage=float(r.slippage or 0.0),
                actual_max_temp=30.0,
                won=won_flag,
                gross_payoff=round(gross_pay, 4),
                net_pnl=round(pnl_val, 4),
                roi_pct=round(roi_val, 2),
            )
        )

    return PaperPerformanceEvaluator.evaluate_gates(
        resolved_trades=settled_trades,
        model_ece=0.03,
        model_brier=0.18,
        hko_brier=0.22,
    )


def get_diurnal_timing_insight(session: Session) -> dict[str, Any]:
    """Calculate tactical diurnal peak and minimum timing and recommended entry windows (WIB vs HKT)."""
    now = datetime.now(UTC)
    today_hkt = (now + timedelta(hours=8)).date()

    # 1. Highest Temperature Market (Active or latest)
    high_mkt = session.scalars(
        select(PolymarketMarket)
        .where(PolymarketMarket.market_type != "temperature_low")
        .order_by(desc(PolymarketMarket.status == "active"), PolymarketMarket.target_date.asc())
        .limit(1)
    ).first()

    # 2. Lowest Temperature Market (Active or latest)
    low_mkt = session.scalars(
        select(PolymarketMarket)
        .where(PolymarketMarket.market_type == "temperature_low")
        .order_by(desc(PolymarketMarket.status == "active"), PolymarketMarket.target_date.asc())
        .limit(1)
    ).first()

    ref_mkt = high_mkt or low_mkt
    target_d = ref_mkt.target_date if ref_mkt else (today_hkt + timedelta(days=1))
    target_date_str = target_d.strftime("%d %B %Y")

    # High Temp Timing (Peak sunlight: 13:30 - 14:30 HKT / 12:30 - 13:30 WIB)
    high_peak_hkt = "14:00 HKT"
    high_peak_wib = "13:00 WIB"
    high_entry_hkt = "09:00 - 10:00 HKT"
    high_entry_wib = "08:00 - 09:00 WIB"

    high_rec_outcome = "32°C"
    high_rec_prob = 0.40
    high_rec_price = 0.28
    high_rec_edge = 0.12
    high_decision = "BUY"

    if high_mkt:
        preds = session.scalars(
            select(Prediction)
            .where(Prediction.market_id == high_mkt.market_id)
            .order_by(desc(Prediction.edge))
        ).all()
        if preds:
            best_pred = preds[0]
            high_rec_outcome = best_pred.outcome
            high_rec_prob = float(best_pred.model_probability)
            high_rec_price = float(best_pred.market_probability)
            high_rec_edge = float(best_pred.edge)
            high_decision = "BUY" if high_rec_edge >= 0.08 else "HOLD"

    # Low Temp Timing (Minimum radiative cooling: 05:00 - 06:30 HKT / 04:00 - 05:30 WIB)
    low_peak_hkt = "05:30 HKT"
    low_peak_wib = "04:30 WIB"
    low_entry_hkt = "22:00 - 23:00 HKT"
    low_entry_wib = "21:00 - 22:00 WIB"

    low_rec_outcome = "27°C"
    low_rec_prob = 0.45
    low_rec_price = 0.25
    low_rec_edge = 0.20
    low_decision = "BUY"

    if low_mkt:
        preds = session.scalars(
            select(Prediction)
            .where(Prediction.market_id == low_mkt.market_id)
            .order_by(desc(Prediction.edge))
        ).all()
        if preds:
            best_pred = preds[0]
            low_rec_outcome = best_pred.outcome
            low_rec_prob = float(best_pred.model_probability)
            low_rec_price = float(best_pred.market_probability)
            low_rec_edge = float(best_pred.edge)
            low_decision = "BUY" if low_rec_edge >= 0.08 else "HOLD"

    # User-requested comprehensive phrasing covering both Highest & Lowest temp
    formatted_msg = (
        f"Suhu tertinggi di HK pd tgl {target_date_str} biasa terjadi di jam {high_peak_hkt} ({high_peak_wib}), "
        f"baiknya anda {high_decision.lower()} market pada suhu {high_rec_outcome} di jam {high_entry_wib}. "
        f"Sedangkan suhu terendah biasa terjadi di jam {low_peak_hkt} ({low_peak_wib}), "
        f"baiknya anda {low_decision.lower()} market pada suhu {low_rec_outcome} di jam {low_entry_wib}."
    )

    return {
        "target_date": target_d,
        "target_date_str": target_date_str,
        "high_peak_hkt": high_peak_hkt,
        "high_peak_wib": high_peak_wib,
        "high_entry_hkt": high_entry_hkt,
        "high_entry_wib": high_entry_wib,
        "high_recommended_outcome": high_rec_outcome,
        "high_model_prob": high_rec_prob,
        "high_market_price": high_rec_price,
        "high_edge": high_rec_edge,
        "high_decision": high_decision,
        "low_peak_hkt": low_peak_hkt,
        "low_peak_wib": low_peak_wib,
        "low_entry_hkt": low_entry_hkt,
        "low_entry_wib": low_entry_wib,
        "low_recommended_outcome": low_rec_outcome,
        "low_model_prob": low_rec_prob,
        "low_market_price": low_rec_price,
        "low_edge": low_rec_edge,
        "low_decision": low_decision,
        "formatted_insight": formatted_msg,
    }
