from pathlib import Path

RASPBERRY_ROOT = Path(__file__).resolve().parent
MODEL_PATH = RASPBERRY_ROOT / "model" / "best.pt"

DEFAULT_DEVICE = "raspberry"
DEFAULT_CAMERA_INDEX = 0
DEFAULT_IMGSZ = 224
DEFAULT_CONF = 0.85
DEFAULT_FRAME_INTERVAL = 0.05
REJECT_COOLDOWN_SEC = 2.0

# Arduino over USB serial (pyserial)
# Linux: /dev/ttyACM0 (native USB) veya /dev/ttyUSB0 (USB-serial chip)
ARDUINO_MODE = "mock"  # "mock" | "usb"
DEFAULT_SERIAL_PORT = "/dev/ttyACM0"
DEFAULT_BAUD_RATE = 115200
ARDUINO_REJECT_CMD = "REJECT\n"
