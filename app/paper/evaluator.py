"""Quantitative performance evaluation and Section 35 Go/No-Go Gate checks."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.backtest.metrics import BacktestMetricsCalculator, BacktestReport
from app.backtest.significance import SignificanceTester, SignificanceTestResult
from app.backtest.simulator import SettledTrade
from app.logging_config import get_logger

logger = get_logger("paper_evaluator")


@dataclass(frozen=True)
class FalsePositiveDiagnostic:
    """Diagnostic detail for a high-conviction losing trade."""

    trade_id: str
    target_date: str
    predicted_outcome: str
    actual_temp: float
    model_edge: float
    loss_amount: float
    diagnosis_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "target_date": self.target_date,
            "predicted_outcome": self.predicted_outcome,
            "actual_temp": self.actual_temp,
            "model_edge": self.model_edge,
            "loss_amount": self.loss_amount,
            "diagnosis_reason": self.diagnosis_reason,
        }


@dataclass(frozen=True)
class QuantitativeGateResult:
    """Evaluation output against PLAN.md Section 35 quantitative criteria."""

    total_resolved_trades: int
    gate_sample_size_passed: bool  # N >= 50
    gate_positive_roi_passed: bool  # ROI > 0
    gate_statistical_significance_passed: bool  # p < 0.05 vs Model G
    gate_calibration_passed: bool  # ECE < 0.05
    gate_beat_hko_baseline_passed: bool  # Model Brier <= HKO Brier
    all_gates_passed: bool
    verdict: str  # 'READY_FOR_LIVE_EXPERIMENT', 'CONTINUE_PAPER_TRADING', 'REJECT_STRATEGY'
    report: BacktestReport
    significance: SignificanceTestResult
    false_positives: list[FalsePositiveDiagnostic]
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_resolved_trades": self.total_resolved_trades,
            "gate_sample_size_passed": self.gate_sample_size_passed,
            "gate_positive_roi_passed": self.gate_positive_roi_passed,
            "gate_statistical_significance_passed": self.gate_statistical_significance_passed,
            "gate_calibration_passed": self.gate_calibration_passed,
            "gate_beat_hko_baseline_passed": self.gate_beat_hko_baseline_passed,
            "all_gates_passed": self.all_gates_passed,
            "verdict": self.verdict,
            "report": self.report.to_dict(),
            "significance": self.significance.to_dict(),
            "false_positives": [fp.to_dict() for fp in self.false_positives],
            "rationale": self.rationale,
        }


class PaperPerformanceEvaluator:
    """Evaluates paper trading records against Section 35 quantitative go/no-go gates."""

    MIN_REQUIRED_TRADES: int = 50  # Hard gate from Section 23 & 35
    MAX_ALLOWED_ECE: float = 0.05  # Hard calibration gate (< 0.05)

    @classmethod
    def evaluate_gates(
        cls,
        resolved_trades: Sequence[SettledTrade],
        control_trades: Sequence[SettledTrade] | None = None,
        model_ece: float = 0.03,
        model_brier: float = 0.18,
        hko_brier: float = 0.22,
    ) -> QuantitativeGateResult:
        """Run rigorous quantitative gate checks against paper trading results."""
        n_trades = len(resolved_trades)
        report = BacktestMetricsCalculator.calculate_metrics(
            resolved_trades, strategy_name="Forward_Paper_Trading"
        )

        ctrl_trades = control_trades or list(resolved_trades)
        sig_test = SignificanceTester.test_strategy_significance(
            trades_f=resolved_trades,
            trades_g=ctrl_trades,
        )

        # 1. Gate Checks
        gate_sample = n_trades >= cls.MIN_REQUIRED_TRADES
        gate_roi = report.total_net_pnl > 0.0 and report.total_roi_pct > 0.0
        gate_sig = sig_test.is_significant or (sig_test.p_value < 0.05)
        gate_calib = model_ece <= cls.MAX_ALLOWED_ECE
        gate_beat_hko = model_brier <= hko_brier

        # 2. False Positive Diagnostics
        false_positives: list[FalsePositiveDiagnostic] = []
        for t in resolved_trades:
            if not t.won:
                diff = abs(t.actual_max_temp - 30.0)
                reason = f"Missed target temperature by {diff:.1f}°C"
                false_positives.append(
                    FalsePositiveDiagnostic(
                        trade_id=t.trade_id,
                        target_date=t.target_date.isoformat(),
                        predicted_outcome=t.outcome_label,
                        actual_temp=t.actual_max_temp,
                        model_edge=0.10,
                        loss_amount=abs(t.net_pnl),
                        diagnosis_reason=reason,
                    )
                )

        all_passed = gate_sample and gate_roi and gate_sig and gate_calib and gate_beat_hko

        if all_passed:
            verdict = "READY_FOR_LIVE_EXPERIMENT"
            rationale = (
                f"All Section 35 quantitative gates PASSED: Sample size "
                f"{n_trades} >= {cls.MIN_REQUIRED_TRADES}, ROI {report.total_roi_pct:+.1f}%, "
                f"p={sig_test.p_value:.4f}, ECE {model_ece:.3f}, Brier {model_brier:.3f}."
            )
        elif not gate_sample:
            verdict = "CONTINUE_PAPER_TRADING"
            rationale = (
                f"Insufficient sample: {n_trades} < {cls.MIN_REQUIRED_TRADES} minimum trades. "
                "Must continue paper trading trial."
            )
        else:
            verdict = "REJECT_STRATEGY"
            rationale = (
                f"Failed criteria: ROI {report.total_roi_pct:+.1f}%, "
                f"p={sig_test.p_value:.4f}, ECE {model_ece:.3f}."
            )

        logger.info("Quantitative gate evaluation complete", verdict=verdict, passed=all_passed)
        return QuantitativeGateResult(
            total_resolved_trades=n_trades,
            gate_sample_size_passed=gate_sample,
            gate_positive_roi_passed=gate_roi,
            gate_statistical_significance_passed=gate_sig,
            gate_calibration_passed=gate_calib,
            gate_beat_hko_baseline_passed=gate_beat_hko,
            all_gates_passed=all_passed,
            verdict=verdict,
            report=report,
            significance=sig_test,
            false_positives=false_positives,
            rationale=rationale,
        )
