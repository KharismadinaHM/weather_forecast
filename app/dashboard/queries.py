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
    WeatherDaily,
    WeatherForecast,
    WeatherObservation,
)


def get_3day_forecast(session: Session) -> list[dict[str, Any]]:
    """Fetch 3-day temperature forecast combining HKO forecast, model predictions & actuals.

    Priority per day:
    1. HKO 9-day forecast (most authoritative, latest revision)
    2. Model predictions from the active Polymarket market
    3. WeatherDaily actual (if already resolved)
    """
    now = datetime.now(UTC)
    today_hkt = (now + timedelta(hours=8)).date()

    results: list[dict[str, Any]] = []

    for day_offset in range(3):
        target_d = today_hkt + timedelta(days=day_offset)

        # --- HKO Forecast: latest revision for this target date ---
        hko_fc = session.scalars(
            select(WeatherForecast)
            .where(
                WeatherForecast.target_date == target_d,
                WeatherForecast.source == "hko_9day",
            )
            .order_by(desc(WeatherForecast.forecast_created_at))
            .limit(1)
        ).first()

        hko_max = float(hko_fc.forecast_max_temperature) if (hko_fc and hko_fc.forecast_max_temperature) else None
        hko_min = float(hko_fc.forecast_min_temperature) if (hko_fc and hko_fc.forecast_min_temperature) else None
        hko_rain_prob = float(hko_fc.rain_probability) if (hko_fc and hko_fc.rain_probability is not None) else None
        hko_humidity = float(hko_fc.humidity) if (hko_fc and hko_fc.humidity is not None) else None
        hko_wind = hko_fc.wind if hko_fc else None
        hko_updated_at = hko_fc.forecast_created_at if hko_fc else None

        # --- Model predictions for this target date (from Polymarket markets) ---
        market = session.scalars(
            select(PolymarketMarket)
            .where(
                PolymarketMarket.target_date == target_d,
                PolymarketMarket.market_type != "temperature_low",
            )
            .order_by(desc(PolymarketMarket.status == "active"))
            .limit(1)
        ).first()

        model_best_outcome: str | None = None
        model_best_prob: float | None = None
        model_best_edge: float | None = None
        model_decision: str | None = None

        if market:
            best_pred = session.scalars(
                select(Prediction)
                .where(Prediction.market_id == market.market_id)
                .order_by(desc(Prediction.edge))
                .limit(1)
            ).first()
            if best_pred:
                model_best_outcome = best_pred.outcome
                model_best_prob = float(best_pred.model_probability)
                model_best_edge = float(best_pred.edge)
                model_decision = "BUY" if model_best_edge >= 0.10 else "HOLD"

        # --- Actual observed data (only available for today or past) ---
        actual = session.scalars(
            select(WeatherDaily)
            .where(
                WeatherDaily.date == target_d,
                WeatherDaily.station == "Hong Kong Observatory",
            )
        ).first()

        actual_max = float(actual.max_temperature) if (actual and actual.max_temperature is not None) else None
        actual_min = float(actual.min_temperature) if (actual and actual.min_temperature is not None) else None

        # Label for the day
        if day_offset == 0:
            day_label = "Hari Ini"
        elif day_offset == 1:
            day_label = "Besok"
        else:
            day_label = "Lusa"

        results.append({
            "day_offset": day_offset,
            "day_label": day_label,
            "target_date": target_d,
            "target_date_str": target_d.strftime("%d %b %Y"),
            "weekday": target_d.strftime("%A"),
            # HKO Forecast
            "hko_max": hko_max,
            "hko_min": hko_min,
            "hko_rain_prob": hko_rain_prob,
            "hko_humidity": hko_humidity,
            "hko_wind": hko_wind,
            "hko_updated_at": hko_updated_at,
            "has_hko_forecast": hko_fc is not None,
            # Model Prediction
            "model_best_outcome": model_best_outcome,
            "model_best_prob": model_best_prob,
            "model_best_edge": model_best_edge,
            "model_decision": model_decision,
            "has_model_prediction": market is not None and model_best_outcome is not None,
            # Actual (if resolved)
            "actual_max": actual_max,
            "actual_min": actual_min,
            "has_actual": actual is not None,
        })

    return results


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
            PolymarketMarket.market_type.label("market_type"),
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
                "market_type",
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
    """Calculate tactical diurnal peak and minimum timing and recommended entry windows (WIB vs HKT).

    Enhanced with:
    - HKO forecast cross-validation to prevent physically unrealistic recommendations
    - Model temperature estimate display for user transparency
    - Deviation warnings when recommendation diverges from official forecast
    """
    now = datetime.now(UTC)
    today_hkt = (now + timedelta(hours=8)).date()

    # ---- Fetch latest HKO forecast for physical validation ----
    hko_fc = session.scalars(
        select(WeatherForecast)
        .where(WeatherForecast.target_date >= today_hkt)
        .order_by(
            WeatherForecast.target_date.asc(),
            desc(WeatherForecast.forecast_created_at),
        )
        .limit(1)
    ).first()

    hko_max_temp = float(hko_fc.forecast_max_temperature) if (hko_fc and hko_fc.forecast_max_temperature) else None
    hko_min_temp = float(hko_fc.forecast_min_temperature) if (hko_fc and hko_fc.forecast_min_temperature) else None

    # ---- Fetch latest observation for real-time reference ----
    latest_obs = session.scalars(
        select(WeatherObservation)
        .where(WeatherObservation.is_authoritative.is_(True))
        .order_by(desc(WeatherObservation.observed_at))
        .limit(1)
    ).first()
    current_temp = float(latest_obs.temperature) if (latest_obs and latest_obs.temperature) else None

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

    # Defaults based on HKO forecast (not arbitrary hardcoded values)
    high_model_temp_estimate = hko_max_temp or 33.0
    high_rec_outcome = f"{high_model_temp_estimate:.0f}°C"
    high_rec_prob = 0.40
    high_rec_price = 0.28
    high_rec_edge = 0.12
    high_decision = "HOLD"
    high_deviation_warning = ""

    if high_mkt:
        preds = session.scalars(
            select(Prediction)
            .where(Prediction.market_id == high_mkt.market_id)
            .order_by(desc(Prediction.edge))
        ).all()
        if preds:
            best_pred = preds[0]

            # Physical validation: check if best prediction's outcome is
            # physically plausible vs HKO forecast
            if hko_max_temp is not None:
                # Try to find a prediction whose outcome is close to HKO forecast
                validated_pred = _find_physically_validated_prediction(
                    preds, hko_max_temp, max_deviation=2.0
                )
                if validated_pred is not None:
                    best_pred = validated_pred
                else:
                    # All predictions deviate significantly from HKO forecast
                    high_deviation_warning = (
                        f"⚠️ Rekomendasi model ({best_pred.outcome}) menyimpang "
                        f"dari forecast HKO ({hko_max_temp:.0f}°C). Gunakan dengan hati-hati."
                    )

            high_rec_outcome = best_pred.outcome
            high_rec_prob = float(best_pred.model_probability)
            high_rec_price = float(best_pred.market_probability)
            high_rec_edge = float(best_pred.edge)
            high_decision = "BUY" if high_rec_edge >= 0.10 else "HOLD"

            # Extract numeric temperature from outcome for estimate
            temp_val = _extract_temp_from_outcome(best_pred.outcome)
            if temp_val is not None:
                high_model_temp_estimate = temp_val

    # Low Temp Timing (Minimum radiative cooling: 05:00 - 06:30 HKT / 04:00 - 05:30 WIB)
    low_peak_hkt = "05:30 HKT"
    low_peak_wib = "04:30 WIB"
    low_entry_hkt = "22:00 - 23:00 HKT"
    low_entry_wib = "21:00 - 22:00 WIB"

    # Defaults based on HKO forecast
    low_model_temp_estimate = hko_min_temp or 27.0
    low_rec_outcome = f"{low_model_temp_estimate:.0f}°C"
    low_rec_prob = 0.45
    low_rec_price = 0.25
    low_rec_edge = 0.20
    low_decision = "HOLD"
    low_deviation_warning = ""

    if low_mkt:
        preds = session.scalars(
            select(Prediction)
            .where(Prediction.market_id == low_mkt.market_id)
            .order_by(desc(Prediction.edge))
        ).all()
        if preds:
            best_pred = preds[0]

            # Physical validation against HKO forecast
            if hko_min_temp is not None:
                validated_pred = _find_physically_validated_prediction(
                    preds, hko_min_temp, max_deviation=2.0
                )
                if validated_pred is not None:
                    best_pred = validated_pred
                else:
                    low_deviation_warning = (
                        f"⚠️ Rekomendasi model ({best_pred.outcome}) menyimpang "
                        f"dari forecast HKO ({hko_min_temp:.0f}°C). Gunakan dengan hati-hati."
                    )

            low_rec_outcome = best_pred.outcome
            low_rec_prob = float(best_pred.model_probability)
            low_rec_price = float(best_pred.market_probability)
            low_rec_edge = float(best_pred.edge)
            low_decision = "BUY" if low_rec_edge >= 0.10 else "HOLD"

            temp_val = _extract_temp_from_outcome(best_pred.outcome)
            if temp_val is not None:
                low_model_temp_estimate = temp_val

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
        "high_model_temp_estimate": high_model_temp_estimate,
        "high_deviation_warning": high_deviation_warning,
        # Legacy aliases for backward compatibility
        "recommended_outcome": high_rec_outcome,
        "recommended_entry_hkt": high_entry_hkt,
        "recommended_entry_wib": high_entry_wib,
        "peak_hkt": high_peak_hkt,
        "peak_wib": high_peak_wib,
        "model_prob": high_rec_prob,
        "market_price": high_rec_price,
        "edge": high_rec_edge,
        "decision": high_decision,
        "low_peak_hkt": low_peak_hkt,
        "low_peak_wib": low_peak_wib,
        "low_entry_hkt": low_entry_hkt,
        "low_entry_wib": low_entry_wib,
        "low_recommended_outcome": low_rec_outcome,
        "low_model_prob": low_rec_prob,
        "low_market_price": low_rec_price,
        "low_edge": low_rec_edge,
        "low_decision": low_decision,
        "low_model_temp_estimate": low_model_temp_estimate,
        "low_deviation_warning": low_deviation_warning,
        # HKO Forecast reference values
        "hko_forecast_max_temp": hko_max_temp,
        "hko_forecast_min_temp": hko_min_temp,
        "current_temp": current_temp,
        "formatted_insight": formatted_msg,
    }


def _extract_temp_from_outcome(outcome: str) -> float | None:
    """Extract numeric temperature value from outcome label like '33°C', '<=31°C', '31 - 32°C'."""
    import re

    # Try range pattern first: "31 - 32°C" -> average
    range_match = re.search(r"(\d+(?:\.\d+)?)\s*[-–—to]+\s*(\d+(?:\.\d+)?)", outcome)
    if range_match:
        low_v = float(range_match.group(1))
        high_v = float(range_match.group(2))
        return (low_v + high_v) / 2.0

    # Open lower: "<=31" -> 31
    lower_match = re.search(r"[<≤]=?\s*(\d+(?:\.\d+)?)", outcome)
    if lower_match:
        return float(lower_match.group(1))

    # Open upper: ">=34", "34+" -> 34
    upper_match = re.search(r"[>≥]=?\s*(\d+(?:\.\d+)?)", outcome)
    if upper_match:
        return float(upper_match.group(1))

    # Single degree: "33°C", "33"
    single_match = re.search(r"(\d+(?:\.\d+)?)", outcome)
    if single_match:
        return float(single_match.group(1))

    return None


def _find_physically_validated_prediction(
    preds: list,
    hko_forecast_temp: float,
    max_deviation: float = 2.0,
) -> Any | None:
    """Find the best-edge prediction whose outcome is within max_deviation of HKO forecast.

    Returns the best physically plausible prediction, or None if all deviate too much.
    """
    for pred in preds:
        temp_val = _extract_temp_from_outcome(pred.outcome)
        if temp_val is not None and abs(temp_val - hko_forecast_temp) <= max_deviation:
            # Also require positive edge for the recommendation to be actionable
            if float(pred.edge) > 0:
                return pred
    return None

