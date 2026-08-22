"""Message formatters for Telegram daily summaries, alerts, and command responses."""

from datetime import date

from app.backtest.metrics import BacktestReport
from app.trading.edge import OpportunityEvaluation


class TelegramFormatter:
    """Formats rich text messages and summaries according to Section 14 templates."""

    @classmethod
    def format_daily_summary(
        cls,
        target_date: date,
        model_distribution: dict[str, float],
        best_opportunity: OpportunityEvaluation | None,
        decision: str,
        risk_allocation: float,
        model_version: str = "weather-v001",
    ) -> str:
        """Format the daily summary message matching Section 14 format exactly."""
        dist_parts = [f"{lbl} {prob * 100:.0f}%" for lbl, prob in model_distribution.items()]
        dist_str = "  ".join(dist_parts)

        dec_icon = "🟢" if decision == "BUY" else ("🟡" if decision == "HOLD" else "⚪")

        lines = [
            "🌡️ <b>HONG KONG WEATHER AI</b>",
            f"<b>Date:</b> {target_date.isoformat()}",
            "<b>Model distribution (bucket-aligned to live market):</b>",
            f"<code>{dist_str}</code>",
            "",
        ]

        if best_opportunity:
            lines.extend(
                [
                    f"<b>Best opportunity:</b> {best_opportunity.outcome_label}",
                    (
                        f"Model: {best_opportunity.model_probability * 100:.0f}%  "
                        f"Market: {best_opportunity.market_probability * 100:.0f}%  "
                        f"Gross edge: {best_opportunity.gross_edge * 100:+.0f}%  "
                        f"Net EV: {best_opportunity.net_ev * 100:+.0f}%"
                    ),
                ]
            )
        else:
            lines.append("<b>Best opportunity:</b> None (No actionable edge)")

        risk_str = (
            f"${risk_allocation:.0f}" if risk_allocation >= 1.0 else f"${risk_allocation:.2f}"
        )
        lines.extend(
            [
                f"<b>Decision:</b> {dec_icon} {decision}   <b>Risk allocation:</b> {risk_str}",
                f"<b>Model:</b> {model_version}",
            ]
        )

        return "\n".join(lines)

    @classmethod
    def format_opportunity_alert(
        cls,
        market_question: str,
        target_date: date,
        opportunity: OpportunityEvaluation,
        recommended_size: float,
        model_version: str,
    ) -> str:
        """Format an instant alert for a high-conviction BUY opportunity."""
        return (
            "🚨 <b>TRADE OPPORTUNITY DETECTED</b>\n\n"
            f"<b>Market:</b> {market_question}\n"
            f"<b>Target Date:</b> {target_date.isoformat()}\n"
            f"<b>Outcome:</b> 🎯 <code>{opportunity.outcome_label}</code>\n"
            f"<b>Model Probability:</b> {opportunity.model_probability:.1%}\n"
            f"<b>Market Price:</b> {opportunity.market_probability:.1%}\n"
            f"<b>Gross Edge:</b> {opportunity.gross_edge:+.1%}\n"
            f"<b>Net EV:</b> {opportunity.net_ev:+.1%}\n"
            f"<b>Recommended Allocation:</b> ${recommended_size:.2f}\n"
            f"<b>Model Version:</b> {model_version}\n\n"
            f"<i>{opportunity.rationale}</i>"
        )

    @classmethod
    def format_missing_market_alert(cls, target_date: date, cutoff_hkt: str = "18:00") -> str:
        """Format an alert when no Polymarket weather market is found by 18:00 HKT (Section 15)."""
        return (
            "⚠️ <b>MISSING MARKET ALERT</b>\n\n"
            f"No active Polymarket market found for target date <b>{target_date.isoformat()}</b> "
            f"by {cutoff_hkt} HKT cutoff.\n"
            "Will continue retrying discovery on the next scheduled cycle."
        )

    @classmethod
    def format_health_alert(cls, component: str, error_message: str) -> str:
        """Format a critical health alert (e.g. API failures after max retries)."""
        return (
            "🚨 <b>SYSTEM HEALTH ALERT</b>\n\n"
            f"<b>Component:</b> {component}\n"
            f"<b>Status:</b> FAILED\n"
            f"<b>Error:</b> <code>{error_message}</code>\n"
            "Please check system logs and container status."
        )

    @classmethod
    def format_performance_report(cls, report: BacktestReport) -> str:
        """Format paper trading performance summary for /performance command."""
        caveat_str = (
            f"\n\n⚠️ <i>{report.sample_size_caveat}</i>" if report.is_insufficient_sample else ""
        )
        return (
            "📊 <b>PAPER TRADING PERFORMANCE</b>\n\n"
            f"<b>Strategy:</b> {report.strategy_name}\n"
            f"<b>Total Resolved Trades:</b> {report.total_trades}\n"
            f"<b>Win Rate:</b> {report.win_rate:.1f}% "
            f"({report.winning_trades}W / {report.losing_trades}L)\n"
            f"<b>Total Capital Invested:</b> ${report.total_capital_invested:.2f}\n"
            f"<b>Total Net PnL:</b> ${report.total_net_pnl:+.2f}\n"
            f"<b>Total ROI:</b> {report.total_roi_pct:+.1f}%\n"
            f"<b>Profit Factor:</b> {report.profit_factor:.2f}\n"
            f"<b>Max Drawdown:</b> ${report.max_drawdown_usd:.2f} "
            f"({report.max_drawdown_pct:.1f}%)\n"
            f"<b>Total Fees:</b> ${report.total_fees:.3f}\n"
            f"<b>Avg Trade PnL:</b> ${report.avg_trade_pnl:+.3f}"
            f"{caveat_str}"
        )

    @classmethod
    def format_status(
        cls,
        environment: str,
        is_paused: bool,
        db_healthy: bool,
        last_prediction_time: str | None = None,
    ) -> str:
        """Format system status message for /status command."""
        state_icon = "⏸️ PAUSED (Kill Switch Active)" if is_paused else "🟢 RUNNING"
        db_icon = "✅ CONNECTED" if db_healthy else "❌ ERROR"
        pred_time = last_prediction_time or "None recorded"

        return (
            "🤖 <b>AGENT SYSTEM STATUS</b>\n\n"
            f"<b>Execution State:</b> {state_icon}\n"
            f"<b>Environment:</b> {environment}\n"
            f"<b>Database:</b> {db_icon}\n"
            f"<b>Last Prediction Cycle:</b> {pred_time}\n"
            "Use /pause or /resume to control execution."
        )
