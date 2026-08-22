"""Probability recalibration and calibration drift detector for forward paper trading."""

from dataclasses import dataclass
from typing import Any

import numpy as np

from app.logging_config import get_logger
from app.ml.calibration import IsotonicCalibrator, PlattCalibrator, expected_calibration_error

logger = get_logger("model_recalibrator")


@dataclass(frozen=True)
class RecalibrationResult:
    """Outcome of probability recalibration analysis."""

    pre_recalibration_ece: float
    post_recalibration_ece: float
    recalibration_needed: bool
    method: str  # 'isotonic' | 'platt' | 'none'
    calibrator: IsotonicCalibrator | PlattCalibrator | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pre_recalibration_ece": self.pre_recalibration_ece,
            "post_recalibration_ece": self.post_recalibration_ece,
            "recalibration_needed": self.recalibration_needed,
            "method": self.method,
        }


class ModelRecalibrator:
    """Monitors expected calibration error (ECE) and fits recalibrators when drift is detected."""

    DEFAULT_ECE_THRESHOLD: float = 0.05

    @classmethod
    def check_and_recalibrate(
        cls,
        predicted_probs: Any,
        actual_outcomes: Any,
        ece_threshold: float = DEFAULT_ECE_THRESHOLD,
        method: str = "isotonic",
    ) -> RecalibrationResult:
        """Check if calibration drift exceeds threshold and fit a recalibrator."""
        y_true = np.asarray(actual_outcomes, dtype=int)
        y_prob = np.asarray(predicted_probs, dtype=float)

        if len(y_true) < 10:
            logger.info("Insufficient samples for recalibration", sample_count=len(y_true))
            return RecalibrationResult(
                pre_recalibration_ece=0.0,
                post_recalibration_ece=0.0,
                recalibration_needed=False,
                method="none",
                calibrator=None,
            )

        pre_ece = expected_calibration_error(y_true, y_prob)

        if pre_ece <= ece_threshold:
            logger.info("Calibration within acceptable tolerance", ece=round(pre_ece, 4))
            return RecalibrationResult(
                pre_recalibration_ece=round(pre_ece, 4),
                post_recalibration_ece=round(pre_ece, 4),
                recalibration_needed=False,
                method="none",
                calibrator=None,
            )

        # Recalibrate
        logger.info(
            "Calibration drift detected; fitting recalibrator",
            pre_ece=round(pre_ece, 4),
            threshold=ece_threshold,
            method=method,
        )

        calibrator: IsotonicCalibrator | PlattCalibrator
        if method == "isotonic":
            calibrator = IsotonicCalibrator()
        else:
            calibrator = PlattCalibrator()

        calibrator.fit(y_prob, y_true)
        calibrated_probs = calibrator.predict_proba(y_prob)
        post_ece = expected_calibration_error(y_true, calibrated_probs)

        logger.info(
            "Recalibration completed",
            pre_ece=round(pre_ece, 4),
            post_ece=round(post_ece, 4),
        )

        return RecalibrationResult(
            pre_recalibration_ece=round(pre_ece, 4),
            post_recalibration_ece=round(post_ece, 4),
            recalibration_needed=True,
            method=method,
            calibrator=calibrator,
        )
