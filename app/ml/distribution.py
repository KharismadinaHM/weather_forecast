"""Continuous probability distribution mapping to Polymarket buckets (Section 9.1 Option B)."""

import math
from collections.abc import Sequence

from scipy.stats import norm

from app.collectors.bucket_parser import ParsedBucket
from app.collectors.validators import DataQualityError


class ContinuousToBucketMapper:
    """Integrates continuous probability density over Polymarket bucket schemas."""

    @classmethod
    def calculate_bucket_probability(
        cls,
        bucket: ParsedBucket,
        mean: float,
        std: float,
        continuity_correction: float = 0.5,
    ) -> float:
        """Calculate probability mass assigned to a single bucket given N(mean, std^2).

        Applies standard half-degree continuity corrections for discrete and range buckets:
        - is_open_lower (<= X): (-inf, X + continuity_correction)
        - is_open_upper (>= X): [X - continuity_correction, +inf)
        - range (A - B): [A - continuity_correction, B + continuity_correction)
        - single degree (X): [X - continuity_correction, X + continuity_correction)
        """
        if std <= 0.0:
            std = 1e-4

        if bucket.is_open_lower:
            # P(Temp <= high + 0.5)
            upper_bound = (bucket.high if bucket.high is not None else mean) + continuity_correction
            prob = float(norm.cdf(upper_bound, loc=mean, scale=std))
            return max(0.0, min(1.0, prob))

        if bucket.is_open_upper:
            # P(Temp >= low - 0.5) = 1 - P(Temp < low - 0.5)
            lower_bound = (bucket.low if bucket.low is not None else mean) - continuity_correction
            prob = float(1.0 - norm.cdf(lower_bound, loc=mean, scale=std))
            return max(0.0, min(1.0, prob))

        if bucket.low is not None and bucket.high is not None:
            if bucket.low == bucket.high:
                # Single degree bucket e.g. '31°C'
                lower_bound = bucket.low - continuity_correction
                upper_bound = bucket.high + continuity_correction
            else:
                # Range bucket e.g. '31 - 32°C'
                lower_bound = bucket.low - continuity_correction
                upper_bound = bucket.high + continuity_correction

            cdf_upper = float(norm.cdf(upper_bound, loc=mean, scale=std))
            cdf_lower = float(norm.cdf(lower_bound, loc=mean, scale=std))
            prob = cdf_upper - cdf_lower
            return max(0.0, min(1.0, prob))

        return 0.0

    @classmethod
    def map_distribution_to_buckets(
        cls,
        buckets: Sequence[ParsedBucket],
        mean: float,
        std: float,
        continuity_correction: float = 0.5,
    ) -> dict[str, float]:
        """Map continuous distribution parameters (mean, std) to normalized probabilities.

        Returns a dictionary mapping raw_label -> normalized_probability (summing to 1.0).
        """

        if not buckets:
            raise DataQualityError("Cannot map probability to empty bucket list")

        raw_probs: dict[str, float] = {}
        for b in buckets:
            p = cls.calculate_bucket_probability(b, mean, std, continuity_correction)
            raw_probs[b.raw_label] = p

        total_p = sum(raw_probs.values())
        if total_p <= 0.0 or math.isnan(total_p):
            # Uniform fallback if degenerate
            uniform = 1.0 / len(buckets)
            return {b.raw_label: uniform for b in buckets}

        normalized = {lbl: (p / total_p) for lbl, p in raw_probs.items()}
        return normalized
