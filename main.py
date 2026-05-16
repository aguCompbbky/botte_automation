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
    ACCEPT_CONF,
    ARDUINO_MODE,
    BOTTLE_DETECT_CONF,
    COLOR_ACCEPT_BGR,
    COLOR_NO_BOTTLE_BGR,
    COLOR_REJECT_BGR,
    DEFAULT_BAUD_RATE,
    DEFAULT_DEVICE,
    DEFAULT_FRAME_INTERVAL,
    DEFAULT_SERIAL_PORT,
    FRAME_BORDER_THICKNESS,
    MODEL_PATH,
    PREVIEW_WINDOW_NAME,
    REJECT_CONF,
)
from hardware.camera_service import CameraService, CameraState
from image_detection.detector import BottleDetector, FrameResult


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )


def close_preview_window() -> None:
    try:
        cv2.destroyWindow(PREVIEW_WINDOW_NAME)
    except cv2.error:
        pass
    cv2.waitKey(1)


def border_color(result: FrameResult) -> tuple[int, int, int]:
    if result.status == "accept":
        return COLOR_ACCEPT_BGR
    if result.status == "reject":
        return COLOR_REJECT_BGR
    return COLOR_NO_BOTTLE_BGR


def status_text(result: FrameResult) -> str:
    if result.status == "no_bottle":
        return "NO BOTTLE"
    if result.status == "uncertain":
        return f"UNCERTAIN {result.label} {result.confidence:.2f}"
    return f"{result.status.upper()} {result.confidence:.2f}"


def draw_overlay(frame_bgr: np.ndarray, result: FrameResult) -> np.ndarray:
    out = frame_bgr.copy()
    h, w = out.shape[:2]
    color = border_color(result)
    t = FRAME_BORDER_THICKNESS

    cv2.rectangle(out, (0, 0), (w - 1, h - 1), color, t)

    if result.bbox_xyxy is not None:
        x1, y1, x2, y2 = result.bbox_xyxy
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)

    label = status_text(result)
    cv2.rectangle(out, (0, 0), (w, 48), (0, 0, 0), -1)
    cv2.putText(out, label, (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2, cv2.LINE_AA)
    return out


def to_bgr(frame: np.ndarray, is_rgb: bool) -> np.ndarray:
    if is_rgb:
        return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description="Sise doluluk kontrolu (accept/reject)")
    parser.add_argument("--device", default=DEFAULT_DEVICE, choices=["raspberry", "laptop"])
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--accept-conf", type=float, default=ACCEPT_CONF)
    parser.add_argument("--reject-conf", type=float, default=REJECT_CONF)
    parser.add_argument("--conf", type=float, default=None)
    parser.add_argument("--bottle-conf", type=float, default=BOTTLE_DETECT_CONF)
    parser.add_argument("--no-bottle-gate", action="store_true")
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

    reject_conf = args.conf if args.conf is not None else args.reject_conf
    detector = BottleDetector(
        model_path=args.model,
        accept_conf=args.accept_conf,
        reject_conf=reject_conf,
        bottle_gate=not args.no_bottle_gate,
        bottle_detect_conf=args.bottle_conf,
        on_reject=lambda r: arduino.notify_reject(),
    )

    camera_service = CameraService(device=args.device)
    camera_service.start()

    last_frame_id = -1
    last_state_version = -1
    preview_open = False

    try:
        while True:
            state = camera_service.state
            state_version = camera_service.state_version

            if state_version != last_state_version:
                if state == CameraState.CAMERA_SCAN and preview_open:
                    close_preview_window()
                    preview_open = False
                    last_frame_id = -1
                last_state_version = state_version

            if state == CameraState.CAMERA_SCAN:
                cv2.waitKey(1)
                time.sleep(0.05)
                continue

            frame_id, frame = camera_service.get_latest_frame()
            if frame is None or frame_id == last_frame_id:
                cv2.waitKey(1)
                time.sleep(0.01)
                continue
            last_frame_id = frame_id

            result = detector.process_frame(frame)

            if not args.no_preview:
                display = draw_overlay(to_bgr(frame, camera_service.frame_is_rgb), result)
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
            close_preview_window()
        cv2.destroyAllWindows()
        arduino.disconnect()


if __name__ == "__main__":
    main()
