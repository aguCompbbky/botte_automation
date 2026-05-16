"""Kamera islemleri ayri thread'de: camera_scan <-> camera_ok (hot-plug)."""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum

import numpy as np

from config import CAMERA_READ_FAIL_MAX, CAMERA_SCAN_INTERVAL_SEC
from hardware.camera_discovery import CameraCandidate, discover_cameras
from hardware.camera_manager import CameraManager, DeviceType

logger = logging.getLogger(__name__)


class CameraState(str, Enum):
    CAMERA_SCAN = "camera_scan"
    CAMERA_OK = "camera_ok"


class CameraService:
    """Tum kamera islemleri arka plan thread'inde."""

    def __init__(self, device: DeviceType) -> None:
        self.device = device
        self._state = CameraState.CAMERA_SCAN
        self._active_source = ""
        self._camera: CameraManager | None = None
        self._is_picamera2 = False

        self._lock = threading.Lock()
        self._latest_frame: np.ndarray | None = None
        self._frame_id = 0

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fail_streak = 0

    @property
    def state(self) -> CameraState:
        with self._lock:
            return self._state

    @property
    def active_source(self) -> str:
        with self._lock:
            return self._active_source

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._camera_loop,
            name="camera-thread",
            daemon=True,
        )
        self._thread.start()
        logger.info("Kamera thread baslatildi (device=%s)", self.device)
        logger.info("[STATE] -> %s", CameraState.CAMERA_SCAN.value)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._release_camera()
        logger.info("Kamera thread durduruldu")

    def get_latest_frame(self) -> tuple[int, np.ndarray | None]:
        with self._lock:
            return self._frame_id, self._latest_frame

    def _set_state(self, state: CameraState, source: str = "") -> None:
        with self._lock:
            old = self._state
            if old == state:
                return
            self._state = state
            self._active_source = source if state == CameraState.CAMERA_OK else ""

        if state == CameraState.CAMERA_SCAN:
            logger.warning("[STATE] %s -> %s | kamera araniyor", old.value, state.value)
        else:
            logger.info("[STATE] %s -> %s | kaynak: %s", old.value, state.value, source)

    def _publish_frame(self, frame: np.ndarray) -> None:
        with self._lock:
            self._latest_frame = frame
            self._frame_id += 1

    def _clear_frame(self) -> None:
        with self._lock:
            self._latest_frame = None

    def _release_camera(self) -> None:
        if self._camera is not None:
            try:
                self._camera.stop()
            except Exception as e:
                logger.debug("Kamera kapatilirken hata: %s", e)
        self._camera = None
        self._is_picamera2 = False
        self._fail_streak = 0
        self._clear_frame()

    def _open_camera(self, candidate: CameraCandidate) -> bool:
        self._release_camera()
        try:
            cam = candidate.create()
            cam.start()
            frame = cam.read()
            if frame is None:
                cam.stop()
                return False
            self._camera = cam
            self._is_picamera2 = candidate.backend == "picamera2"
            self._publish_frame(frame)
            self._set_state(CameraState.CAMERA_OK, candidate.label)
            return True
        except Exception as e:
            logger.warning("Kamera acilamadi (%s): %s", candidate.label, e)
            self._release_camera()
            return False

    def _scan_once(self) -> bool:
        for candidate in discover_cameras(self.device):
            logger.info("Kamera bulundu, baglaniyor: %s", candidate.label)
            if self._open_camera(candidate):
                return True
        return False

    def _handle_ok(self) -> None:
        assert self._camera is not None
        frame = self._camera.read()
        if frame is None:
            self._fail_streak += 1
            if self._fail_streak >= CAMERA_READ_FAIL_MAX:
                logger.warning(
                    "Kare okunamadi (%d) — kamera kopmus olabilir, yeniden aranacak.",
                    self._fail_streak,
                )
                self._release_camera()
                self._set_state(CameraState.CAMERA_SCAN)
            return

        self._fail_streak = 0
        self._publish_frame(frame)

    def _camera_loop(self) -> None:
        while not self._stop.is_set():
            if self.state == CameraState.CAMERA_SCAN:
                self._scan_once()
                time.sleep(CAMERA_SCAN_INTERVAL_SEC)
            else:
                self._handle_ok()
                time.sleep(0.001)

    @property
    def frame_is_rgb(self) -> bool:
        return self._is_picamera2
