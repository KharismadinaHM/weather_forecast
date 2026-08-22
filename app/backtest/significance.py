"""Statistical significance testing: Bootstrap CI and Permutation test (PLAN.md Section 20a)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.backtest.simulator import SettledTrade


@dataclass(frozen=True)
class SignificanceTestResult:
    """Statistical hypothesis test results comparing Model F vs Model G Control."""

    model_f_roi: float
    model_g_roi: float
    roi_difference: float
    p_value: float
    is_significant: bool
    bootstrap_ci_95: tuple[float, float]
    sample_size_f: int
    sample_size_g: int
    verdict: str  # 'CONCLUSIVE_EDGE', 'PROVISIONAL_EDGE', 'NO_SIGNIFICANT_EDGE'
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_f_roi": self.model_f_roi,
            "model_g_roi": self.model_g_roi,
            "roi_difference": self.roi_difference,
            "p_value": self.p_value,
            "is_significant": self.is_significant,
            "bootstrap_ci_95": self.bootstrap_ci_95,
            "sample_size_f": self.sample_size_f,
            "sample_size_g": self.sample_size_g,
            "verdict": self.verdict,
            "rationale": self.rationale,
        }


class SignificanceTester:
    """Evaluates whether trading strategy outperformance is distinguishable from noise."""

    @classmethod
    def test_strategy_significance(
        cls,
        trades_f: Sequence[SettledTrade],
        trades_g: Sequence[SettledTrade],
        n_bootstraps: int = 1000,
        random_seed: int = 42,
    ) -> SignificanceTestResult:
        """Run Bootstrap CI and Permutation Test comparing Strategy F against Control G."""
        np.random.seed(random_seed)

        n_f = len(trades_f)
        n_g = len(trades_g)

        if n_f == 0 or n_g == 0:
            return SignificanceTestResult(
                model_f_roi=0.0,
                model_g_roi=0.0,
                roi_difference=0.0,
                p_value=1.0,
                is_significant=False,
                bootstrap_ci_95=(0.0, 0.0),
                sample_size_f=n_f,
                sample_size_g=n_g,
                verdict="NO_SIGNIFICANT_EDGE",
                rationale="Empty trade history",
            )

        returns_f = np.array([t.roi_pct for t in trades_f], dtype=float)
        returns_g = np.array([t.roi_pct for t in trades_g], dtype=float)

        mean_roi_f = float(np.mean(returns_f))
        mean_roi_g = float(np.mean(returns_g))
        obs_diff = mean_roi_f - mean_roi_g

        # 1. Bootstrap 95% Confidence Interval on Strategy F ROI
        boot_means: list[float] = []
        for _ in range(n_bootstraps):
            sample = np.random.choice(returns_f, size=n_f, replace=True)
            boot_means.append(float(np.mean(sample)))

        ci_low = float(np.percentile(boot_means, 2.5))
        ci_high = float(np.percentile(boot_means, 97.5))

        # 2. Two-sample Permutation Test vs Model G
        combined = np.concatenate([returns_f, returns_g])
        perm_diffs: list[float] = []

        for _ in range(n_bootstraps):
            perm = np.random.permutation(combined)
            perm_f = perm[:n_f]
            perm_g = perm[n_f:]
            perm_diffs.append(float(np.mean(perm_f) - np.mean(perm_g)))

        perm_diffs_arr = np.array(perm_diffs)
        # Empirical p-value: fraction of permutations where random difference >= observed difference
        p_val = float(np.mean(perm_diffs_arr >= obs_diff))

        # Section 20a & 18 Verdict logic:
        # A positive edge is conclusive only if p < 0.05 AND sample_size >= 50
        is_stat_sig = p_val < 0.05
        is_sufficient_sample = n_f >= 50

        if is_stat_sig and is_sufficient_sample and obs_diff > 0:
            verdict = "CONCLUSIVE_EDGE"
            rationale = (
                f"Statistically significant edge over Model G (ROI diff: {obs_diff:+.1f}%, "
                f"p={p_val:.4f} < 0.05, N={n_f} >= 50)."
            )
        elif obs_diff > 0:
            verdict = "PROVISIONAL_EDGE"
            rationale = (
                f"Positive ROI outperformance ({obs_diff:+.1f}%), provisional due to sample size "
                f"(N={n_f} < 50) or p-value (p={p_val:.4f})."
            )
        else:
            verdict = "NO_SIGNIFICANT_EDGE"
            rationale = (
                f"No significant edge over Model G (ROI diff: {obs_diff:+.1f}%, p={p_val:.4f})."
            )

        return SignificanceTestResult(
            model_f_roi=round(mean_roi_f, 2),
            model_g_roi=round(mean_roi_g, 2),
            roi_difference=round(obs_diff, 2),
            p_value=round(p_val, 4),
            is_significant=is_stat_sig,
            bootstrap_ci_95=(round(ci_low, 2), round(ci_high, 2)),
            sample_size_f=n_f,
            sample_size_g=n_g,
            verdict=verdict,
            rationale=rationale,
        )
