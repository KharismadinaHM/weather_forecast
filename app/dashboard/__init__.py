"""Streamlit monitoring dashboard package (Milestone M-Dashboard)."""

from app.dashboard.queries import (
    evaluate_section35_gates_from_db,
    get_freshness_metrics,
    get_latest_predictions_df,
    get_market_price_vs_model_df,
    get_paper_trades_and_pnl_df,
)

__all__ = [
    "get_freshness_metrics",
    "get_latest_predictions_df",
    "get_market_price_vs_model_df",
    "get_paper_trades_and_pnl_df",
    "evaluate_section35_gates_from_db",
]
