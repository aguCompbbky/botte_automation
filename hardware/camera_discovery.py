"""Kamera kesfi: Raspberry (Picamera2 / USB) ve laptop (webcam)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from config import CAMERA_HEIGHT, CAMERA_WIDTH, USB_CAMERA_SCAN_MAX_INDEX
from hardware.camera_manager import CameraManager, DeviceType, LaptopCamera, RaspberryCamera

logger = logging.getLogger(__name__)

CameraBackend = Literal["picamera2", "usb"]


@dataclass(frozen=True)
class CameraCandidate:
    backend: CameraBackend | Literal["webcam"]
    index: int = 0
    label: str = ""

    def create(self) -> CameraManager:
        if self.backend == "picamera2":
            return RaspberryCamera(width=CAMERA_WIDTH, height=CAMERA_HEIGHT)
        return LaptopCamera(
            camera_index=self.index,
            width=CAMERA_WIDTH,
            height=CAMERA_HEIGHT,
        )


def _probe_picamera2() -> bool:
    try:
        from picamera2 import Picamera2
    except ImportError:
        return False

    picam = None
    try:
        picam = Picamera2()
        config = picam.create_preview_configuration(
            main={"format": "RGB888", "size": (CAMERA_WIDTH, CAMERA_HEIGHT)}
        )
        picam.configure(config)
        picam.start()
        frame = picam.capture_array()
        return frame is not None
    except Exception as e:
        logger.debug("Picamera2 probe failed: %s", e)
        return False
    finally:
        if picam is not None:
            try:
                picam.stop()
                picam.close()
            except Exception:
                pass


def _probe_usb_index(index: int) -> bool:
    import cv2

    cap = cv2.VideoCapture(index)
    try:
        if not cap.isOpened():
            return False
        ok, frame = cap.read()
        return ok and frame is not None
    except Exception as e:
        logger.debug("USB camera probe index %d failed: %s", index, e)
        return False
    finally:
        cap.release()


def discover_raspberry_cameras() -> list[CameraCandidate]:
    candidates: list[CameraCandidate] = []
    if _probe_picamera2():
        candidates.append(
            CameraCandidate(backend="picamera2", label="Raspberry Pi Camera (Picamera2)")
        )
    for idx in range(USB_CAMERA_SCAN_MAX_INDEX):
        if _probe_usb_index(idx):
            candidates.append(
                CameraCandidate(
                    backend="usb",
                    index=idx,
                    label=f"USB kamera (index {idx})",
                )
            )
    return candidates


def discover_laptop_cameras() -> list[CameraCandidate]:
    order = [0] + [i for i in range(USB_CAMERA_SCAN_MAX_INDEX) if i != 0]
    candidates: list[CameraCandidate] = []
    for idx in order:
        if _probe_usb_index(idx):
            candidates.append(
                CameraCandidate(
                    backend="webcam",
                    index=idx,
                    label=f"Webcam (index {idx})",
                )
            )
    return candidates


def discover_cameras(device: DeviceType) -> list[CameraCandidate]:
    if device == "raspberry":
        return discover_raspberry_cameras()
    if device == "laptop":
        return discover_laptop_cameras()
    raise ValueError(f"Unknown device: {device}")
