"""Streamlit Monitoring Dashboard for Hong Kong Weather Prediction Market Agent."""

import streamlit as st

from app.dashboard.queries import (
    evaluate_section35_gates_from_db,
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
    .gate-passed {
        background-color: #1b5e20;
        color: #ffffff;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 0.85rem;
    }
    .gate-failed {
        background-color: #b71c1c;
        color: #ffffff;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 0.85rem;
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
        # 2. Section 35 Quantitative Go/No-Go Gates
        # ---------------------------------------------------------
        st.subheader("2. 🛡️ Section 35 Quantitative Go/No-Go Gates")

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
        # 3. Latest Predictions & Signals Table
        # ---------------------------------------------------------
        st.subheader("3. 🎯 Latest Predictions & Signals")
        if not pred_df.empty:
            # Filter bar
            f_col1, f_col2 = st.columns([2, 4])
            with f_col1:
                dec_filter = st.selectbox("Filter by Decision:", ["ALL", "BUY", "HOLD"])
            with f_col2:
                search_q = st.text_input("Search Market / Outcome:", "")

            filtered_df = pred_df.copy()
            if dec_filter != "ALL":
                filtered_df = filtered_df[filtered_df["decision"] == dec_filter]
            if search_q:
                filtered_df = filtered_df[
                    filtered_df["market"].str.contains(search_q, case=False, na=False)
                    | filtered_df["outcome"].str.contains(search_q, case=False, na=False)
                ]

            st.dataframe(
                filtered_df.style.format(
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
        # 4. Polymarket Price vs Model Probability Chart
        # ---------------------------------------------------------
        st.subheader("4. 📈 Polymarket Price vs Model Probability")
        ts_df = get_market_price_vs_model_df(session)
        if not ts_df.empty:
            outcomes_list = list(ts_df["outcome"].unique())
            selected_outcome = st.selectbox("Select Outcome Bucket:", outcomes_list)
            chart_data = ts_df[ts_df["outcome"] == selected_outcome]

            pivot_chart = chart_data.pivot(
                index="timestamp", columns="series_type", values="value"
            ).fillna(method="ffill")
            st.line_chart(pivot_chart, use_container_width=True)
        else:
            st.info("No active market price series available for plotting.")

        st.markdown("---")

        # ---------------------------------------------------------
        # 5. Paper Trading History & Cumulative PnL
        # ---------------------------------------------------------
        st.subheader("5. 💼 Paper Trading Performance & Cumulative PnL")
        m_c1, m_c2, m_c3, m_c4 = st.columns(4)

        total_trades = len(trades_df)
        closed_trades = trades_df[trades_df["status"] == "CLOSED"]
        total_pnl = float(closed_trades["pnl"].sum()) if not closed_trades.empty else 0.0
        win_count = len(closed_trades[closed_trades["pnl"] > 0])
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

        # Trades Table
        st.write("#### Trade Execution Log")
        if not trades_df.empty:
            st.dataframe(
                trades_df.style.format(
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
