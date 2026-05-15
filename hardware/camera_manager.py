from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generator, Literal

import numpy as np

DeviceType = Literal["raspberry", "laptop"]


class CameraManager(ABC):
    """Abstract camera interface for frame capture."""

    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def read(self) -> np.ndarray | None:
        """Return BGR or RGB frame, or None if unavailable."""
        pass

    def frames(self) -> Generator[np.ndarray, None, None]:
        while True:
            frame = self.read()
            if frame is not None:
                yield frame


class LaptopCamera(CameraManager):
    def __init__(self, camera_index: int = 0, width: int = 640, height: int = 480) -> None:
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self._cap = None

    def start(self) -> None:
        import cv2

        self._cap = cv2.VideoCapture(self.camera_index)
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open laptop camera index {self.camera_index}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

    def stop(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def read(self) -> np.ndarray | None:
        if self._cap is None:
            return None
        ok, frame = self._cap.read()
        return frame if ok else None


class RaspberryCamera(CameraManager):
    def __init__(self, width: int = 640, height: int = 480) -> None:
        self.width = width
        self.height = height
        self._picam = None

    def start(self) -> None:
        try:
            from picamera2 import Picamera2
        except ImportError as e:
            raise RuntimeError(
                "picamera2 is required on Raspberry Pi. Install with: pip install picamera2"
            ) from e

        self._picam = Picamera2()
        config = self._picam.create_preview_configuration(
            main={"format": "RGB888", "size": (self.width, self.height)}
        )
        self._picam.configure(config)
        self._picam.start()

    def stop(self) -> None:
        if self._picam is not None:
            self._picam.stop()
            self._picam.close()
            self._picam = None

    def read(self) -> np.ndarray | None:
        if self._picam is None:
            return None
        # Picamera2 returns RGB; YOLO accepts numpy arrays directly
        return self._picam.capture_array()


def create_camera(device: DeviceType, camera_index: int = 0) -> CameraManager:
    if device == "raspberry":
        return RaspberryCamera()
    if device == "laptop":
        return LaptopCamera(camera_index=camera_index)
    raise ValueError(f"Unknown device: {device}. Use 'raspberry' or 'laptop'.")
