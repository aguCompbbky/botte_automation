from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from ultralytics import YOLO

from config import DEFAULT_CONF, DEFAULT_IMGSZ, MODEL_PATH, REJECT_COOLDOWN_SEC

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    label: str
    confidence: float
    probabilities: dict[str, float]


class BottleDetector:
    """Real-time accept/reject classification from camera frames."""

    def __init__(
        self,
        model_path: Path | str = MODEL_PATH,
        conf_threshold: float = DEFAULT_CONF,
        imgsz: int = DEFAULT_IMGSZ,
        on_reject: Callable[[ClassificationResult], None] | None = None,
        reject_cooldown_sec: float = REJECT_COOLDOWN_SEC,
    ) -> None:
        self.model_path = Path(model_path)
        self.conf_threshold = conf_threshold
        self.imgsz = imgsz
        self.on_reject = on_reject
        self.reject_cooldown_sec = reject_cooldown_sec

        if not self.model_path.exists():
            raise FileNotFoundError(f"Model not found: {self.model_path}")

        self._model = YOLO(str(self.model_path))
        self._last_reject_trigger = 0.0
        self._last_logged_label: str | None = None

    def classify(self, frame: np.ndarray) -> ClassificationResult:
        result = self._model.predict(
            frame,
            imgsz=self.imgsz,
            verbose=False,
        )[0]
        probs = result.probs
        names = result.names
        pred_idx = int(probs.top1)
        label = names[pred_idx]
        confidence = float(probs.top1conf)
        prob_dict = {names[i]: float(probs.data[i]) for i in range(len(names))}
        return ClassificationResult(label=label, confidence=confidence, probabilities=prob_dict)

    def _log_detection(self, result: ClassificationResult) -> None:
        probs_str = ", ".join(f"{k}={v:.4f}" for k, v in result.probabilities.items())
        if result.label == "accept":
            logger.info("[ACCEPT] conf=%.4f | %s", result.confidence, probs_str)
        else:
            logger.warning("[REJECT] conf=%.4f | %s", result.confidence, probs_str)

    def _maybe_trigger_reject(self, result: ClassificationResult) -> None:
        if result.label != "reject" or result.confidence < self.conf_threshold:
            return
        now = time.monotonic()
        if now - self._last_reject_trigger < self.reject_cooldown_sec:
            return
        self._last_reject_trigger = now
        logger.warning("[REJECT] Esik asildi — Arduino bildirimi gonderiliyor.")
        if self.on_reject:
            self.on_reject(result)

    def process_frame(self, frame: np.ndarray) -> ClassificationResult:
        result = self.classify(frame)

        if result.confidence >= self.conf_threshold:
            if result.label != self._last_logged_label:
                self._log_detection(result)
                self._last_logged_label = result.label
            if result.label == "reject":
                self._maybe_trigger_reject(result)
        elif self._last_logged_label is not None:
            logger.debug("Dusuk guven (%.4f), onceki: %s", result.confidence, self._last_logged_label)

        return result
