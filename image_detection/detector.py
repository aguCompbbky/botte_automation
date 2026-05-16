from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

import numpy as np
from ultralytics import YOLO

from config import (
    ACCEPT_CONF,
    BOTTLE_CROP_PADDING,
    BOTTLE_DETECT_CONF,
    BOTTLE_DETECT_MODEL,
    COCO_BOTTLE_CLASS_ID,
    DEFAULT_CONF,
    DEFAULT_IMGSZ,
    MODEL_PATH,
    REJECT_CONF,
    REJECT_COOLDOWN_SEC,
)

logger = logging.getLogger(__name__)

FrameStatus = Literal["no_bottle", "accept", "reject", "uncertain"]


@dataclass
class ClassificationResult:
    label: str
    confidence: float
    probabilities: dict[str, float]


@dataclass
class FrameResult:
    """Bir kamer karesi icin tam sonuc."""

    status: FrameStatus
    label: str = ""
    confidence: float = 0.0
    probabilities: dict[str, float] = field(default_factory=dict)
    bottle_detect_conf: float = 0.0
    bbox_xyxy: tuple[int, int, int, int] | None = None


class BottleDetector:
    """
    1) YOLO detect ile sise var mi?
    2) Varsa kirpilmis goruntude accept/reject siniflandir.
    Sise yoksa accept/reject + Arduino tetiklenmez.
    """

    def __init__(
        self,
        model_path: Path | str = MODEL_PATH,
        accept_conf: float = ACCEPT_CONF,
        reject_conf: float = REJECT_CONF,
        conf_threshold: float | None = None,
        imgsz: int = DEFAULT_IMGSZ,
        on_reject: Callable[[ClassificationResult], None] | None = None,
        reject_cooldown_sec: float = REJECT_COOLDOWN_SEC,
        bottle_gate: bool = True,
        bottle_detect_conf: float = BOTTLE_DETECT_CONF,
        detect_model: str = BOTTLE_DETECT_MODEL,
    ) -> None:
        self.model_path = Path(model_path)
        if conf_threshold is not None:
            reject_conf = conf_threshold
        self.accept_conf = accept_conf
        self.reject_conf = reject_conf
        self.imgsz = imgsz
        self.on_reject = on_reject
        self.reject_cooldown_sec = reject_cooldown_sec
        self.bottle_gate = bottle_gate
        self.bottle_detect_conf = bottle_detect_conf

        if not self.model_path.exists():
            raise FileNotFoundError(f"Model not found: {self.model_path}")

        self._cls_model = YOLO(str(self.model_path))
        self._detect_model = YOLO(detect_model) if bottle_gate else None
        self._last_reject_trigger = 0.0
        self._last_logged_status: FrameStatus | None = None

    def _find_bottle_bbox(self, frame: np.ndarray) -> tuple[tuple[int, int, int, int], float] | None:
        if self._detect_model is None:
            return None

        result = self._detect_model.predict(
            frame,
            classes=[COCO_BOTTLE_CLASS_ID],
            conf=self.bottle_detect_conf,
            verbose=False,
        )[0]

        if result.boxes is None or len(result.boxes) == 0:
            return None

        best = max(result.boxes, key=lambda b: float(b.conf[0]))
        xyxy = best.xyxy[0].cpu().numpy().astype(int).tolist()
        conf = float(best.conf[0])
        return (int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3])), conf

    @staticmethod
    def _crop_with_padding(frame: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        pad_x = int((x2 - x1) * BOTTLE_CROP_PADDING)
        pad_y = int((y2 - y1) * BOTTLE_CROP_PADDING)
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(w, x2 + pad_x)
        y2 = min(h, y2 + pad_y)
        return frame[y1:y2, x1:x2]

    def classify(self, frame: np.ndarray) -> ClassificationResult:
        result = self._cls_model.predict(frame, imgsz=self.imgsz, verbose=False)[0]
        probs = result.probs
        names = result.names
        pred_idx = int(probs.top1)
        label = names[pred_idx]
        confidence = float(probs.top1conf)
        prob_dict = {names[i]: float(probs.data[i]) for i in range(len(names))}
        return ClassificationResult(label=label, confidence=confidence, probabilities=prob_dict)

    def _log_result(self, frame_result: FrameResult) -> None:
        if frame_result.status == "no_bottle":
            logger.info("[NO_BOTTLE] Sise bulunamadi — siniflandirma atlandi")
            return
        if frame_result.status == "uncertain":
            logger.info(
                "[UNCERTAIN] conf=%.4f | %s",
                frame_result.confidence,
                frame_result.probabilities,
            )
            return
        probs_str = ", ".join(f"{k}={v:.4f}" for k, v in frame_result.probabilities.items())
        if frame_result.status == "accept":
            logger.info(
                "[ACCEPT] conf=%.4f | sise=%.4f | %s",
                frame_result.confidence,
                frame_result.bottle_detect_conf,
                probs_str,
            )
        else:
            logger.warning(
                "[REJECT] conf=%.4f | sise=%.4f | %s",
                frame_result.confidence,
                frame_result.bottle_detect_conf,
                probs_str,
            )

    def _passes_threshold(self, cls: ClassificationResult) -> bool:
        if cls.label == "accept":
            return cls.confidence >= self.accept_conf
        return cls.confidence >= self.reject_conf

    def _maybe_trigger_reject(self, cls: ClassificationResult) -> None:
        if cls.label != "reject" or cls.confidence < self.reject_conf:
            return
        now = time.monotonic()
        if now - self._last_reject_trigger < self.reject_cooldown_sec:
            return
        self._last_reject_trigger = now
        logger.warning("[REJECT] Esik asildi — Arduino bildirimi gonderiliyor.")
        if self.on_reject:
            self.on_reject(cls)

    def process_frame(self, frame: np.ndarray) -> FrameResult:
        bbox_info = self._find_bottle_bbox(frame) if self.bottle_gate else None

        if self.bottle_gate and bbox_info is None:
            out = FrameResult(status="no_bottle")
            if self._last_logged_status != "no_bottle":
                self._log_result(out)
                self._last_logged_status = "no_bottle"
            return out

        bbox, bottle_conf = bbox_info if bbox_info else (None, 0.0)
        roi = self._crop_with_padding(frame, bbox) if bbox else frame
        cls = self.classify(roi)

        if not self._passes_threshold(cls):
            out = FrameResult(
                status="uncertain",
                label=cls.label,
                confidence=cls.confidence,
                probabilities=cls.probabilities,
                bottle_detect_conf=bottle_conf,
                bbox_xyxy=bbox,
            )
            if self._last_logged_status != "uncertain":
                self._log_result(out)
                self._last_logged_status = "uncertain"
            return out

        status: FrameStatus = "accept" if cls.label == "accept" else "reject"
        out = FrameResult(
            status=status,
            label=cls.label,
            confidence=cls.confidence,
            probabilities=cls.probabilities,
            bottle_detect_conf=bottle_conf,
            bbox_xyxy=bbox,
        )

        if status != self._last_logged_status:
            self._log_result(out)
            self._last_logged_status = status

        if status == "reject":
            self._maybe_trigger_reject(cls)

        return out
