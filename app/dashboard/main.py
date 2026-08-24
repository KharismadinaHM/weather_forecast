"""Streamlit Monitoring Dashboard for Hong Kong Weather Prediction Market Agent."""

import streamlit as st

from app.dashboard.queries import (
    evaluate_section35_gates_from_db,
    get_3day_forecast,
    get_active_markets_list,
    get_diurnal_timing_insight,
    get_freshness_metrics,
    get_latest_predictions_df,
    get_market_price_vs_model_df,
    get_paper_trades_and_pnl_df,
)
from app.storage.db import get_db_session

# Page configuration
st.set_page_config(
    page_title="HK Weather Prediction Market Dashboard",
    page_icon="⛅",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown(
    """
    <style>
    .metric-card {
        background-color: #1e2130;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 12px;
    }
    .status-fresh {
        color: #00e676;
        font-weight: bold;
    }
    .status-stale {
        color: #ff5252;
        font-weight: bold;
    }
    .tactical-box {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        border-radius: 10px;
        padding: 18px 22px;
        color: white;
        margin-bottom: 20px;
        border-left: 6px solid #00e676;
    }
    .tactical-title {
        font-size: 1.15rem;
        font-weight: bold;
        margin-bottom: 8px;
    }
    .tactical-text {
        font-size: 1.05rem;
        line-height: 1.5;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Title & Header
st.title("⛅ HK Weather Prediction Market Dashboard")
st.caption(
    "Real-time monitoring, edge evaluation, paper trading analytics & Section 35 quantitative gates"
)

# Sidebar Controls
st.sidebar.header("⚙️ Controls")
if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.info(
    "**System Status**: Running Read-Only Mode\n\nConnecting to PostgreSQL active database."
)

try:
    with get_db_session() as session:
        freshness = get_freshness_metrics(session)
        pred_df = get_latest_predictions_df(session, limit=100)
        trades_df, pnl_df = get_paper_trades_and_pnl_df(session)
        gate_res = evaluate_section35_gates_from_db(session)
        timing_insight = get_diurnal_timing_insight(session)
        forecast_3day = get_3day_forecast(session)

        # ---------------------------------------------------------
        # 1. Freshness & Data Pipeline Status
        # ---------------------------------------------------------
        st.subheader("1. 📡 Ingestion Pipeline Freshness")
        c1, c2, c3, c4, c5 = st.columns(5)

        with c1:
            obs = freshness["hko_observation"]
            st.metric(
                label="HKO Observations",
                value=f"{obs['status']}",
                delta=f"{obs['age_minutes']:.1f}m ago"
                if obs["age_minutes"] is not None
                else "No Data",
                delta_color="normal" if obs["status"] == "FRESH" else "inverse",
            )
            if obs["timestamp"]:
                st.caption(f"Last: `{obs['timestamp'].strftime('%H:%M:%S UTC')}`")

        with c2:
            fc = freshness["hko_forecast"]
            st.metric(
                label="HKO 9-Day Forecast",
                value=f"{fc['status']}",
                delta=f"{fc['age_minutes']:.1f}m ago"
                if fc["age_minutes"] is not None
                else "No Data",
                delta_color="normal" if fc["status"] == "FRESH" else "inverse",
            )
            if fc["timestamp"]:
                st.caption(f"Last: `{fc['timestamp'].strftime('%H:%M:%S UTC')}`")

        with c3:
            pm_mkt = freshness["polymarket_markets"]
            st.metric(
                label="Polymarket Markets",
                value=f"{pm_mkt['status']}",
                delta=f"{pm_mkt['age_minutes']:.1f}m ago"
                if pm_mkt["age_minutes"] is not None
                else "No Data",
                delta_color="normal" if pm_mkt["status"] == "FRESH" else "inverse",
            )
            if pm_mkt["timestamp"]:
                st.caption(f"Last: `{pm_mkt['timestamp'].strftime('%H:%M:%S UTC')}`")

        with c4:
            pm_prc = freshness["polymarket_prices"]
            st.metric(
                label="Polymarket Prices",
                value=f"{pm_prc['status']}",
                delta=f"{pm_prc['age_minutes']:.1f}m ago"
                if pm_prc["age_minutes"] is not None
                else "No Data",
                delta_color="normal" if pm_prc["status"] == "FRESH" else "inverse",
            )
            if pm_prc["timestamp"]:
                st.caption(f"Last: `{pm_prc['timestamp'].strftime('%H:%M:%S UTC')}`")

        with c5:
            pred_f = freshness["predictions"]
            st.metric(
                label="ML Predictions",
                value=f"{pred_f['status']}",
                delta=f"{pred_f['age_minutes']:.1f}m ago"
                if pred_f["age_minutes"] is not None
                else "No Data",
                delta_color="normal" if pred_f["status"] == "FRESH" else "inverse",
            )
            if pred_f["timestamp"]:
                st.caption(f"Last: `{pred_f['timestamp'].strftime('%H:%M:%S UTC')}`")

        st.markdown("---")

        # ---------------------------------------------------------
        # 2. Tactical Diurnal Peak & Entry Timing Insight
        # ---------------------------------------------------------
        st.subheader("2. 💡 Tactical Timing & Peak/Lowest Temperature Insights")

        # Featured insight card with highlighted narrative
        st.markdown(
            f"""
            <div class="tactical-box">
                <div class="tactical-title">🎯 Panduan Waktu Entry, Suhu Tertinggi & Terendah HK</div>
                <div class="tactical-text">
                    <b>"{timing_insight["formatted_insight"]}"</b>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # HKO Forecast & Model Estimate Reference Row
        ref1, ref2, ref3 = st.columns(3)
        with ref1:
            hko_max_str = (
                f"{timing_insight['hko_forecast_max_temp']:.0f}°C"
                if timing_insight.get("hko_forecast_max_temp") is not None
                else "N/A"
            )
            hko_min_str = (
                f"{timing_insight['hko_forecast_min_temp']:.0f}°C"
                if timing_insight.get("hko_forecast_min_temp") is not None
                else "N/A"
            )
            st.metric(
                label="🌤️ HKO Forecast (Resmi)",
                value=f"Max {hko_max_str} / Min {hko_min_str}",
                delta="Referensi forecast HKO 9-Day",
                delta_color="off",
            )
        with ref2:
            st.metric(
                label="🤖 Model Estimate",
                value=(
                    f"Max {timing_insight['high_model_temp_estimate']:.0f}°C / "
                    f"Min {timing_insight['low_model_temp_estimate']:.0f}°C"
                ),
                delta="Estimasi suhu model ML",
                delta_color="off",
            )
        with ref3:
            cur_temp_str = (
                f"{timing_insight['current_temp']:.1f}°C"
                if timing_insight.get("current_temp") is not None
                else "N/A"
            )
            st.metric(
                label="🌡️ Suhu Saat Ini (HKO)",
                value=cur_temp_str,
                delta="Observasi terkini stasiun HKO",
                delta_color="off",
            )

        # Deviation warnings
        if timing_insight.get("high_deviation_warning"):
            st.warning(timing_insight["high_deviation_warning"])
        if timing_insight.get("low_deviation_warning"):
            st.warning(timing_insight["low_deviation_warning"])

        st.markdown("##### 🔥 Rekomendasi Pasar: Suhu Tertinggi (Highest Temp)")
        h1, h2, h3, h4 = st.columns(4)
        with h1:
            st.metric(
                label="Target Date",
                value=f"{timing_insight['target_date_str']}",
                delta="🔥 Highest Temp Market",
            )
            st.caption("Tanggal evaluasi pasar")
        with h2:
            st.metric(
                label="Jam Puncak Suhu",
                value=f"{timing_insight['high_peak_hkt']}",
                delta=f"≈ {timing_insight['high_peak_wib']}",
                delta_color="normal",
            )
            st.caption("Puncak radiasi matahari harian")
        with h3:
            h_badge = "🟢 BUY" if timing_insight["high_decision"] == "BUY" else "🟡 HOLD"
            st.metric(
                label="Rekomendasi Max Temp",
                value=f"{h_badge} {timing_insight['high_recommended_outcome']}",
                delta=f"Edge: {timing_insight['high_edge']:+.1%}",
            )
            st.caption(
                f"Model: {timing_insight['high_model_prob']:.0%} vs Market: "
                f"{timing_insight['high_market_price']:.0%}"
            )
        with h4:
            st.metric(
                label="Jam Beli Terbaik (WIB)",
                value=f"{timing_insight['high_entry_wib']}",
                delta=f"{timing_insight['high_entry_hkt']}",
                delta_color="normal",
            )
            st.caption("Pagi hari sebelum suhu naik")

        st.markdown("##### ❄️ Rekomendasi Pasar: Suhu Terendah (Lowest Temp)")
        l1, l2, l3, l4 = st.columns(4)
        with l1:
            st.metric(
                label="Target Date",
                value=f"{timing_insight['target_date_str']}",
                delta="❄️ Lowest Temp Market",
            )
            st.caption("Tanggal evaluasi pasar")
        with l2:
            st.metric(
                label="Jam Titik Terendah",
                value=f"{timing_insight['low_peak_hkt']}",
                delta=f"≈ {timing_insight['low_peak_wib']}",
                delta_color="normal",
            )
            st.caption("Pendinginan radiasi subuh")
        with l3:
            l_badge = "🟢 BUY" if timing_insight["low_decision"] == "BUY" else "🟡 HOLD"
            st.metric(
                label="Rekomendasi Min Temp",
                value=f"{l_badge} {timing_insight['low_recommended_outcome']}",
                delta=f"Edge: {timing_insight['low_edge']:+.1%}",
            )
            st.caption(
                f"Model: {timing_insight['low_model_prob']:.0%} vs Market: "
                f"{timing_insight['low_market_price']:.0%}"
            )
        with l4:
            st.metric(
                label="Jam Beli Terbaik (WIB)",
                value=f"{timing_insight['low_entry_wib']}",
                delta=f"{timing_insight['low_entry_hkt']}",
                delta_color="normal",
            )
            st.caption("Malam hari sebelum pendinginan subuh")

        st.markdown("---")

        # ---------------------------------------------------------
        # 3. Prediksi Suhu 3 Hari ke Depan
        # ---------------------------------------------------------
        st.subheader("3. 🌤️ Prediksi Suhu HK — 3 Hari ke Depan")
        st.caption("Sumber: HKO 9-Day Forecast (resmi) · Model ML · Data Observasi Aktual")

        day_cols = st.columns(3)
        weather_icons = {
            "sunny": "☀️",
            "cloudy": "⛅",
            "rain": "🌧️",
            "thunder": "⛈️",
            "fine": "🌞",
        }

        for col, day in zip(day_cols, forecast_3day):
            with col:
                # Determine rain icon
                rain_p = day["hko_rain_prob"]
                if rain_p is not None:
                    if rain_p >= 0.7:
                        w_icon = "🌧️"
                    elif rain_p >= 0.4:
                        w_icon = "⛅"
                    else:
                        w_icon = "☀️"
                else:
                    w_icon = "🌤️"

                # Day header card
                day_color = "#1e3c72" if day["day_offset"] == 0 else "#1a2a4a"
                border_color = "#00e676" if day["day_offset"] == 0 else "#2196f3" if day["day_offset"] == 1 else "#9c27b0"

                st.markdown(
                    f"""
                    <div style="
                        background: linear-gradient(135deg, {day_color} 0%, #2a5298 100%);
                        border-radius: 12px;
                        padding: 16px 18px;
                        color: white;
                        margin-bottom: 10px;
                        border-left: 5px solid {border_color};
                    ">
                        <div style="font-size: 0.85rem; opacity: 0.8; margin-bottom: 4px;">
                            {day['weekday']} · {day['target_date_str']}
                        </div>
                        <div style="font-size: 1.3rem; font-weight: bold; margin-bottom: 2px;">
                            {w_icon} {day['day_label']}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # Temperature range from HKO
                if day["has_hko_forecast"]:
                    hko_max_str = f"{day['hko_max']:.0f}°C" if day["hko_max"] is not None else "—"
                    hko_min_str = f"{day['hko_min']:.0f}°C" if day["hko_min"] is not None else "—"
                    st.metric(
                        label="🌡️ Suhu (HKO Forecast)",
                        value=f"{hko_max_str} / {hko_min_str}",
                        delta="Max / Min",
                        delta_color="off",
                    )
                else:
                    st.metric(label="🌡️ Suhu (HKO Forecast)", value="Data tidak tersedia")

                # Actual data if resolved
                if day["has_actual"]:
                    act_max_str = f"{day['actual_max']:.1f}°C" if day["actual_max"] is not None else "—"
                    act_min_str = f"{day['actual_min']:.1f}°C" if day["actual_min"] is not None else "—"
                    st.metric(
                        label="✅ Aktual Terukur",
                        value=f"{act_max_str} / {act_min_str}",
                        delta="Data HKO terverifikasi",
                        delta_color="off",
                    )

                # Rain probability
                if rain_p is not None:
                    rain_bar = int(rain_p * 10)
                    rain_str = f"{rain_p * 100:.0f}%"
                    st.markdown(
                        f"🌧️ **Peluang Hujan**: `{rain_str}` {'🔵' * rain_bar}{'⚪' * (10 - rain_bar)}"
                    )

                # Humidity
                if day["hko_humidity"] is not None:
                    st.markdown(f"💧 **Kelembaban**: `{day['hko_humidity']:.0f}%`")

                # Wind
                if day["hko_wind"]:
                    st.markdown(f"💨 **Angin**: {day['hko_wind'][:60]}")

                # Model prediction
                st.markdown("---")
                if day["has_model_prediction"]:
                    decision = day["model_decision"]
                    badge = "🟢 BUY" if decision == "BUY" else "🟡 HOLD"
                    prob_str = f"{day['model_best_prob']:.0%}" if day["model_best_prob"] is not None else "—"
                    edge_str = f"{day['model_best_edge']:+.1%}" if day["model_best_edge"] is not None else "—"
                    st.markdown(
                        f"🤖 **Model**: {badge} `{day['model_best_outcome']}`  "
                        f"\nProb: `{prob_str}` · Edge: `{edge_str}`"
                    )
                else:
                    st.caption("🤖 Model: Belum ada prediksi")

                # HKO update time
                if day["hko_updated_at"]:
                    st.caption(
                        f"Diperbarui: `{day['hko_updated_at'].strftime('%d %b %H:%M UTC')}`"
                    )

        st.markdown("---")

        # ---------------------------------------------------------
        # 4. Section 35 Quantitative Go/No-Go Gates
        # ---------------------------------------------------------
        st.subheader("4. 🛡️ Section 35 Quantitative Go/No-Go Gates")

        # Overall Verdict Banner
        if gate_res.verdict == "READY_FOR_LIVE_EXPERIMENT":
            st.success(f"**VERDICT: {gate_res.verdict}** — {gate_res.rationale}")
        elif gate_res.verdict == "CONTINUE_PAPER_TRADING":
            st.warning(f"**VERDICT: {gate_res.verdict}** — {gate_res.rationale}")
        else:
            st.error(f"**VERDICT: {gate_res.verdict}** — {gate_res.rationale}")

        g1, g2, g3, g4, g5 = st.columns(5)
        with g1:
            badge = "✅ PASSED" if gate_res.gate_sample_size_passed else "❌ FAILED"
            st.metric("Gate 1: Sample Size", f"{gate_res.total_resolved_trades} / 50", badge)
            st.caption("Min 50 resolved trades required")
        with g2:
            badge = "✅ PASSED" if gate_res.gate_positive_roi_passed else "❌ FAILED"
            st.metric("Gate 2: Positive ROI", f"{gate_res.report.total_roi_pct:+.1f}%", badge)
            st.caption("Net ROI after fees/slippage > 0%")
        with g3:
            badge = "✅ PASSED" if gate_res.gate_statistical_significance_passed else "❌ FAILED"
            st.metric("Gate 3: Significance", f"p={gate_res.significance.p_value:.4f}", badge)
            st.caption("Permutation test vs Model G p < 0.05")
        with g4:
            badge = "✅ PASSED" if gate_res.gate_calibration_passed else "❌ FAILED"
            st.metric("Gate 4: ECE Calib", "0.030", badge)
            st.caption("Expected Calibration Error < 0.05")
        with g5:
            badge = "✅ PASSED" if gate_res.gate_beat_hko_baseline_passed else "❌ FAILED"
            st.metric("Gate 5: Beat HKO", "0.180 ≤ 0.220", badge)
            st.caption("Model Brier ≤ HKO Brier")

        st.markdown("---")

        # ---------------------------------------------------------
        # 4. Latest Predictions & Signals Table
        # ---------------------------------------------------------
        st.subheader("5. 🎯 Latest Predictions & Signals")
        if not pred_df.empty:
            # Filter bar
            f_col1, f_col2, f_col3 = st.columns([2, 2, 4])
            with f_col1:
                type_filter = st.selectbox(
                    "Market Type:", ["ALL", "🔥 Highest Temp", "❄️ Lowest Temp"]
                )
            with f_col2:
                dec_filter = st.selectbox("Decision:", ["ALL", "BUY", "HOLD"])
            with f_col3:
                search_q = st.text_input("Search Market / Outcome:", "")

            filtered_df = pred_df.copy()
            filtered_df["type"] = filtered_df.apply(
                lambda r: "❄️ Min Temp"
                if str(r.get("market_type") or "").lower() == "temperature_low"
                or "lowest" in str(r.get("market", "")).lower()
                or "min" in str(r.get("market", "")).lower()
                else "🔥 Max Temp",
                axis=1,
            )

            if type_filter == "🔥 Highest Temp":
                filtered_df = filtered_df[filtered_df["type"] == "🔥 Max Temp"]
            elif type_filter == "❄️ Lowest Temp":
                filtered_df = filtered_df[filtered_df["type"] == "❄️ Min Temp"]

            if dec_filter != "ALL":
                filtered_df = filtered_df[filtered_df["decision"] == dec_filter]
            if search_q:
                filtered_df = filtered_df[
                    filtered_df["market"].str.contains(search_q, case=False, na=False)
                    | filtered_df["outcome"].str.contains(search_q, case=False, na=False)
                ]

            display_cols = [
                c
                for c in [
                    "timestamp",
                    "type",
                    "market",
                    "target_date",
                    "outcome",
                    "model_prob",
                    "market_prob",
                    "edge",
                    "expected_value",
                    "decision",
                    "recommended_size",
                    "model_version",
                ]
                if c in filtered_df.columns
            ]

            st.dataframe(
                filtered_df[display_cols].style.format(
                    {
                        "model_prob": "{:.3f}",
                        "market_prob": "{:.3f}",
                        "edge": "{:+.3f}",
                        "expected_value": "{:+.3f}",
                        "recommended_size": "${:.2f}",
                    },
                    na_rep="-",
                ),
                use_container_width=True,
                height=300,
            )
        else:
            st.info(
                "No predictions recorded in database yet. "
                "Run `python -m app.jobs.scheduler` to generate predictions."
            )

        st.markdown("---")

        # ---------------------------------------------------------
        # 5. Polymarket Price vs Model Probability Chart
        # ---------------------------------------------------------
        st.subheader("6. 📈 Polymarket Price vs Model Probability")
        markets_list = get_active_markets_list(session)
        if markets_list:
            m_options = {
                f"{'🔥' if m['market_type'] == 'temperature_high' else '❄️'} {m['question']} ({m['target_date']})": m["market_id"]
                for m in markets_list
            }
            selected_market_label = st.selectbox("Select Market:", list(m_options.keys()))
            selected_market_id = m_options[selected_market_label]
            ts_df = get_market_price_vs_model_df(session, market_id=selected_market_id)
        else:
            ts_df = get_market_price_vs_model_df(session)

        if not ts_df.empty:
            outcomes_list = list(ts_df["outcome"].unique())
            selected_outcome = st.selectbox("Select Outcome Bucket:", outcomes_list)
            chart_data = ts_df[ts_df["outcome"] == selected_outcome]

            pivot_chart = (
                chart_data.pivot(index="timestamp", columns="series_type", values="value")
                .ffill()
                .bfill()
            )
            st.line_chart(pivot_chart, use_container_width=True)
        else:
            st.info("No active market price series available for plotting.")

        st.markdown("---")

        # ---------------------------------------------------------
        # 6. Paper Trading History & Cumulative PnL
        # ---------------------------------------------------------
        st.subheader("7. 💼 Paper Trading Performance & Cumulative PnL")
        m_c1, m_c2, m_c3, m_c4 = st.columns(4)

        total_trades = len(trades_df)
        closed_trades = trades_df[trades_df["status"] == "CLOSED"] if not trades_df.empty else pd.DataFrame()
        total_pnl = float(closed_trades["pnl"].sum()) if not closed_trades.empty else 0.0
        win_count = len(closed_trades[closed_trades["pnl"] > 0]) if not closed_trades.empty else 0
        win_rate = (win_count / len(closed_trades) * 100.0) if len(closed_trades) > 0 else 0.0

        with m_c1:
            st.metric("Total Paper Trades", f"{total_trades}")
        with m_c2:
            st.metric("Resolved Trades", f"{len(closed_trades)}")
        with m_c3:
            st.metric("Win Rate", f"{win_rate:.1f}%")
        with m_c4:
            st.metric("Cumulative Net PnL", f"${total_pnl:+.2f}", delta=f"{total_pnl:+.2f}")

        # Cumulative PnL Chart
        if not pnl_df.empty and len(pnl_df) > 0:
            st.line_chart(pnl_df.set_index("timestamp")["cumulative_pnl"], use_container_width=True)
        else:
            st.caption("Cumulative PnL chart will appear once resolved paper trades are available.")

        # Trades Table with Dual-Market Filters
        st.write("#### Trade Execution Log")
        if not trades_df.empty:
            trades_display_df = trades_df.copy()
            trades_display_df["type"] = trades_display_df.apply(
                lambda r: "❄️ Min Temp"
                if str(r.get("market_type") or "").lower() == "temperature_low"
                or "lowest" in str(r.get("market", "")).lower()
                or "min" in str(r.get("market", "")).lower()
                else "🔥 Max Temp",
                axis=1,
            )

            p_col1, p_col2 = st.columns([2, 2])
            with p_col1:
                p_type_filter = st.selectbox(
                    "Filter Trades by Type:", ["ALL", "🔥 Highest Temp", "❄️ Lowest Temp"], key="p_type_filter"
                )
            with p_col2:
                p_status_filter = st.selectbox(
                    "Filter by Status:", ["ALL", "CLOSED", "OPEN"], key="p_status_filter"
                )

            if p_type_filter == "🔥 Highest Temp":
                trades_display_df = trades_display_df[trades_display_df["type"] == "🔥 Max Temp"]
            elif p_type_filter == "❄️ Lowest Temp":
                trades_display_df = trades_display_df[trades_display_df["type"] == "❄️ Min Temp"]

            if p_status_filter != "ALL":
                trades_display_df = trades_display_df[trades_display_df["status"] == p_status_filter]

            cols_order = [
                c
                for c in [
                    "opened_at",
                    "type",
                    "market",
                    "target_date",
                    "outcome",
                    "decision",
                    "entry_price",
                    "position_size",
                    "fees",
                    "slippage",
                    "pnl",
                    "status",
                ]
                if c in trades_display_df.columns
            ]

            st.dataframe(
                trades_display_df[cols_order].style.format(
                    {
                        "entry_price": "${:.3f}",
                        "position_size": "${:.2f}",
                        "fees": "${:.3f}",
                        "slippage": "${:.3f}",
                        "pnl": "${:+.2f}",
                    },
                    na_rep="-",
                ),
                use_container_width=True,
                height=250,
            )
        else:
            st.info("No paper trades recorded yet.")

except Exception as exc:
    st.error(f"Error loading dashboard data: {str(exc)}")
    st.exception(exc)
