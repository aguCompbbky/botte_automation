"""Kamera islemleri ayri thread'de: camera_scan <-> camera_ok (hot-plug)."""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum

import numpy as np

from config import (
    CAMERA_OPEN_TIMEOUT_SEC,
    CAMERA_PROBE_TIMEOUT_SEC,
    CAMERA_READ_FAIL_MAX,
    CAMERA_READ_TIMEOUT_SEC,
    CAMERA_SCAN_INTERVAL_SEC,
    CAMERA_STOP_TIMEOUT_SEC,
)
from hardware.camera_discovery import CameraCandidate, discover_cameras
from hardware.camera_manager import CameraManager, DeviceType
from hardware.timeouts import run_with_timeout

_READ_TIMEOUT = object()

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
        self._state_version = 0

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fail_streak = 0
        self._read_timeout_streak = 0

    @property
    def state(self) -> CameraState:
        with self._lock:
            return self._state

    @property
    def state_version(self) -> int:
        with self._lock:
            return self._state_version

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
        logger.info("[STATE] -> %s | Searching for camera...", CameraState.CAMERA_SCAN.value)

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
            self._state_version += 1

        if state == CameraState.CAMERA_SCAN and old == CameraState.CAMERA_OK:
            logger.error("Camera connection is lost")
            logger.warning("[STATE] %s -> %s | Searching for camera...", old.value, state.value)
        elif state == CameraState.CAMERA_OK and old == CameraState.CAMERA_SCAN:
            logger.info("Camera connected: %s", source)
            logger.info("[STATE] %s -> %s | kaynak: %s", old.value, state.value, source)
        elif state == CameraState.CAMERA_SCAN:
            logger.warning("[STATE] %s -> %s | Searching for camera...", old.value, state.value)
        else:
            logger.info("[STATE] %s -> %s | kaynak: %s", old.value, state.value, source)

    def _publish_frame(self, frame: np.ndarray) -> None:
        with self._lock:
            self._latest_frame = frame
            self._frame_id += 1

    def _clear_frame(self) -> None:
        with self._lock:
            self._latest_frame = None

    def _stop_camera_safe(self, cam: CameraManager) -> None:
        def _stop() -> None:
            cam.stop()

        try:
            run_with_timeout(_stop, CAMERA_STOP_TIMEOUT_SEC, None)
        except Exception as e:
            logger.debug("Kamera kapatma hatasi (yoksayildi): %s", e)

    def _release_camera(self) -> None:
        cam = self._camera
        self._camera = None
        self._is_picamera2 = False
        self._fail_streak = 0
        self._read_timeout_streak = 0
        self._clear_frame()
        if cam is not None:
            self._stop_camera_safe(cam)

    def _read_frame_timed(self, cam: CameraManager) -> np.ndarray | None:
        frame = run_with_timeout(lambda: cam.read(), CAMERA_READ_TIMEOUT_SEC, _READ_TIMEOUT)
        if frame is _READ_TIMEOUT:
            self._read_timeout_streak += 1
            return None
        return frame

    def _open_camera(self, candidate: CameraCandidate) -> bool:
        self._release_camera()
        try:
            cam = candidate.create()

            def _start_and_read() -> np.ndarray | None:
                cam.start()
                return cam.read()

            frame = run_with_timeout(_start_and_read, CAMERA_OPEN_TIMEOUT_SEC, None)
            if frame is None:
                self._stop_camera_safe(cam)
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
        try:
            candidates = discover_cameras(self.device)
        except Exception as e:
            logger.debug("Kamera tarama hatasi: %s", e)
            return False

        for candidate in candidates:
            logger.info("Kamera adayi bulundu, baglaniyor: %s", candidate.label)
            if self._open_camera(candidate):
                return True
        return False

    def _handle_ok(self) -> None:
        if self._camera is None:
            self._set_state(CameraState.CAMERA_SCAN)
            return

        frame = self._read_frame_timed(self._camera)

        if self._read_timeout_streak >= 2:
            self._set_state(CameraState.CAMERA_SCAN)
            self._release_camera()
            return

        if frame is None:
            self._fail_streak += 1
            if self._fail_streak >= CAMERA_READ_FAIL_MAX:
                self._set_state(CameraState.CAMERA_SCAN)
                self._release_camera()
            return

        self._fail_streak = 0
        self._read_timeout_streak = 0
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
