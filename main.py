#!/usr/bin/env python3
"""Bottle inspection: camera thread (scan/ok) + preview + YOLO classify + Arduino."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from communicationwardunio.arduino_client import create_arduino_client
from config import (
    ARDUINO_MODE,
    DEFAULT_BAUD_RATE,
    DEFAULT_CONF,
    DEFAULT_DEVICE,
    DEFAULT_FRAME_INTERVAL,
    DEFAULT_SERIAL_PORT,
    MODEL_PATH,
    PREVIEW_WINDOW_NAME,
)
from hardware.camera_service import CameraService, CameraState
from image_detection.detector import BottleDetector


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )


def draw_overlay(frame_bgr: np.ndarray, label: str, confidence: float) -> np.ndarray:
    out = frame_bgr.copy()
    color = (0, 200, 0) if label == "accept" else (0, 0, 255)
    text = f"{label.upper()} {confidence:.2f}"
    cv2.rectangle(out, (0, 0), (out.shape[1], 48), (0, 0, 0), -1)
    cv2.putText(out, text, (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2, cv2.LINE_AA)
    return out


def to_bgr(frame: np.ndarray, is_rgb: bool) -> np.ndarray:
    if is_rgb:
        return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description="Sise doluluk kontrolu (accept/reject)")
    parser.add_argument(
        "--device",
        default=DEFAULT_DEVICE,
        choices=["raspberry", "laptop"],
    )
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--conf", type=float, default=DEFAULT_CONF)
    parser.add_argument("--interval", type=float, default=DEFAULT_FRAME_INTERVAL)
    parser.add_argument("--serial-port", default=DEFAULT_SERIAL_PORT)
    parser.add_argument("--baud-rate", type=int, default=DEFAULT_BAUD_RATE)
    parser.add_argument("--arduino-mode", default=ARDUINO_MODE, choices=["mock", "usb"])
    parser.add_argument("--no-preview", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)
    log = logging.getLogger("main")

    arduino = create_arduino_client(
        mode=args.arduino_mode,
        port=args.serial_port,
        baud_rate=args.baud_rate,
    )
    arduino.connect()

    detector = BottleDetector(
        model_path=args.model,
        conf_threshold=args.conf,
        on_reject=lambda r: arduino.notify_reject(),
    )

    camera_service = CameraService(device=args.device)
    camera_service.start()

    log.info("Cihaz: %s | Model: %s | Conf: %.2f", args.device, args.model, args.conf)

    last_frame_id = -1
    preview_open = False

    try:
        while True:
            if camera_service.state == CameraState.CAMERA_SCAN:
                last_frame_id = -1
                if preview_open:
                    cv2.destroyWindow(PREVIEW_WINDOW_NAME)
                    preview_open = False
                time.sleep(0.05)
                continue

            frame_id, frame = camera_service.get_latest_frame()
            if frame is None or frame_id == last_frame_id:
                time.sleep(0.01)
                continue
            last_frame_id = frame_id

            result = detector.process_frame(frame)

            if not args.no_preview:
                display = draw_overlay(
                    to_bgr(frame, camera_service.frame_is_rgb),
                    result.label,
                    result.confidence,
                )
                cv2.imshow(PREVIEW_WINDOW_NAME, display)
                preview_open = True
                if (cv2.waitKey(1) & 0xFF) == ord("q"):
                    break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        log.info("Durduruldu.")
    finally:
        camera_service.stop()
        if preview_open:
            cv2.destroyAllWindows()
        arduino.disconnect()


if __name__ == "__main__":
    main()
