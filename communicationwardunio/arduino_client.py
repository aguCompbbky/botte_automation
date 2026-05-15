from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Literal

from config import (
    ARDUINO_MODE,
    ARDUINO_REJECT_CMD,
    DEFAULT_BAUD_RATE,
    DEFAULT_SERIAL_PORT,
)

logger = logging.getLogger(__name__)

ArduinoMode = Literal["mock", "usb"]


class ArduinoClientBase(ABC):
    """Arduino servo kontrolu icin arayuz."""

    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def notify_reject(self) -> None:
        pass


class MockArduinoClient(ArduinoClientBase):
    """Gercek USB baglantisi olmadan Arduino davranisini simule eder."""

    def __init__(self, port: str = DEFAULT_SERIAL_PORT, baud_rate: int = DEFAULT_BAUD_RATE) -> None:
        self.port = port
        self.baud_rate = baud_rate
        self._connected = False
        self.reject_count = 0

    def connect(self) -> bool:
        self._connected = True
        logger.info(
            "[MOCK Arduino] Hazir — gercek USB baglantisi yapilmadi. "
            "Hedef port: %s @ %d baud",
            self.port,
            self.baud_rate,
        )
        return True

    def disconnect(self) -> None:
        if self._connected:
            logger.info(
                "[MOCK Arduino] Baglanti kapatildi. Toplam REJECT: %d",
                self.reject_count,
            )
        self._connected = False

    def notify_reject(self) -> None:
        if not self._connected:
            logger.warning("[MOCK Arduino] Bagli degil, REJECT atlandi.")
            return
        self.reject_count += 1
        cmd = ARDUINO_REJECT_CMD.strip()
        logger.warning(
            "[MOCK Arduino] USB >> %r  (servo tetiklenirdi)  [#%d]",
            cmd,
            self.reject_count,
        )


class UsbArduinoClient(ArduinoClientBase):
    """Arduino ile USB uzerinden serial haberlesme (pyserial)."""

    def __init__(
        self,
        port: str = DEFAULT_SERIAL_PORT,
        baud_rate: int = DEFAULT_BAUD_RATE,
    ) -> None:
        self.port = port
        self.baud_rate = baud_rate
        self._serial = None

    def connect(self) -> bool:
        try:
            import serial
        except ImportError as e:
            raise RuntimeError(
                "USB Arduino icin pyserial gerekli: pip install pyserial"
            ) from e

        try:
            self._serial = serial.Serial(self.port, self.baud_rate, timeout=1)
            logger.info(
                "[Arduino USB] Baglandi: %s @ %d baud",
                self.port,
                self.baud_rate,
            )
            return True
        except Exception as e:
            logger.error("[Arduino USB] Baglanti hatasi (%s): %s", self.port, e)
            self._serial = None
            return False

    def disconnect(self) -> None:
        if self._serial is not None and self._serial.is_open:
            self._serial.close()
            logger.info("[Arduino USB] Baglanti kapatildi.")
        self._serial = None

    def notify_reject(self) -> None:
        if self._serial is None or not self._serial.is_open:
            logger.warning("[Arduino USB] Baglanti yok, REJECT gonderilemedi.")
            return
        self._serial.write(ARDUINO_REJECT_CMD.encode("utf-8"))
        self._serial.flush()
        logger.info(
            "[Arduino USB] Komut gonderildi: %r",
            ARDUINO_REJECT_CMD.strip(),
        )


def create_arduino_client(
    mode: ArduinoMode | None = None,
    port: str = DEFAULT_SERIAL_PORT,
    baud_rate: int = DEFAULT_BAUD_RATE,
) -> ArduinoClientBase:
    """Arduino istemcisi olustur. Varsayilan: mock."""
    mode = mode or ARDUINO_MODE  # type: ignore[assignment]
    if mode == "mock":
        return MockArduinoClient(port=port, baud_rate=baud_rate)
    if mode == "usb":
        return UsbArduinoClient(port=port, baud_rate=baud_rate)
    raise ValueError(f"Gecersiz arduino mode: {mode}. 'mock' veya 'usb' kullanin.")


# Geriye uyumluluk
ArduinoClient = UsbArduinoClient
