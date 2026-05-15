#!/usr/bin/env python3
"""Raspberry / laptop bottle inspection: camera + YOLO classify + Arduino."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Run from raspberry/ directory
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from communicationwardunio.arduino_client import create_arduino_client
from config import (
    ARDUINO_MODE,
    DEFAULT_BAUD_RATE,
    DEFAULT_CAMERA_INDEX,
    DEFAULT_CONF,
    DEFAULT_DEVICE,
    DEFAULT_FRAME_INTERVAL,
    DEFAULT_SERIAL_PORT,
    MODEL_PATH,
)
from hardware.camera_manager import create_camera
from image_detection.detector import BottleDetector


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Sise doluluk kontrolu (accept/reject)")
    parser.add_argument(
        "--device",
        default=DEFAULT_DEVICE,
        choices=["raspberry", "laptop"],
        help="Kamera kaynagi (varsayilan: raspberry)",
    )
    parser.add_argument("--camera-index", type=int, default=DEFAULT_CAMERA_INDEX)
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--conf", type=float, default=DEFAULT_CONF)
    parser.add_argument("--interval", type=float, default=DEFAULT_FRAME_INTERVAL)
    parser.add_argument("--serial-port", default=DEFAULT_SERIAL_PORT, help="USB serial port (ornek: /dev/ttyACM0)")
    parser.add_argument("--baud-rate", type=int, default=DEFAULT_BAUD_RATE)
    parser.add_argument(
        "--arduino-mode",
        default=ARDUINO_MODE,
        choices=["mock", "usb"],
        help="Arduino: mock (varsayilan) veya usb (gercek USB serial)",
    )
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
    log.info("Arduino modu: %s", args.arduino_mode)

    detector = BottleDetector(
        model_path=args.model,
        conf_threshold=args.conf,
        on_reject=lambda r: arduino.notify_reject(),
    )

    camera = create_camera(args.device, camera_index=args.camera_index)
    log.info("Cihaz: %s | Model: %s | Conf: %.2f", args.device, args.model, args.conf)

    try:
        camera.start()
        log.info("Kamera acildi. Ctrl+C ile cikis.")
        while True:
            frame = camera.read()
            if frame is None:
                time.sleep(0.01)
                continue
            detector.process_frame(frame)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log.info("Durduruldu.")
    finally:
        camera.stop()
        arduino.disconnect()


if __name__ == "__main__":
    main()
