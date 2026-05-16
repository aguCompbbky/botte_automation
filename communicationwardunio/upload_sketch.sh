#!/usr/bin/env bash
# =============================================================================
# upload_sketch.sh — servo_reject.ino dosyasini Arduino'ya yukler
#
# Kullanim:
#   ./upload_sketch.sh                  # port otomatik bulunur
#   ./upload_sketch.sh /dev/ttyACM1     # port elle belirt
#
# Gereksinim: arduino-cli (yoksa bu script otomatik kurar)
# =============================================================================

set -euo pipefail

# ── Ayarlar ──────────────────────────────────────────────────────────────────
BOARD="arduino:avr:uno"                         # Arduino Uno
SKETCH_DIR="$(cd "$(dirname "$0")" && pwd)"     # bu script'in bulundugu klasor
SKETCH_FILE="$SKETCH_DIR/servo_reject.ino"
CLI_INSTALL_DIR="$HOME/.local/bin"
CLI="$CLI_INSTALL_DIR/arduino-cli"

# Port: arguman verilmisse kullan, yoksa otomatik bul
if [[ $# -ge 1 ]]; then
    PORT="$1"
else
    PORT=""
fi

# ── Renk kodlari ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── 1. arduino-cli kontrolu ve kurulumu ──────────────────────────────────────
if ! command -v arduino-cli &>/dev/null && [[ ! -x "$CLI" ]]; then
    info "arduino-cli bulunamadi, kuruluyor..."
    mkdir -p "$CLI_INSTALL_DIR"
    curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh \
        | BINDIR="$CLI_INSTALL_DIR" sh
    export PATH="$CLI_INSTALL_DIR:$PATH"
    info "arduino-cli kuruldu: $CLI"
else
    CLI=$(command -v arduino-cli || echo "$CLI")
    export PATH="$CLI_INSTALL_DIR:$PATH"
    info "arduino-cli mevcut: $($CLI version)"
fi

# ── 2. Arduino AVR core kurulumu ─────────────────────────────────────────────
info "Arduino AVR core guncelleniyor..."
"$CLI" core update-index --quiet
if ! "$CLI" core list | grep -q "arduino:avr"; then
    info "arduino:avr core kuruluyor..."
    "$CLI" core install arduino:avr --quiet
    info "arduino:avr core kuruldu."
else
    info "arduino:avr core zaten yuklu."
fi

# ── 3. Sketch dosyasi kontrolu ───────────────────────────────────────────────
[[ -f "$SKETCH_FILE" ]] || error "Sketch bulunamadi: $SKETCH_FILE"
info "Sketch bulundu: $SKETCH_FILE"

# ── 4. Arduino portu bul ─────────────────────────────────────────────────────
if [[ -z "$PORT" ]]; then
    info "Arduino portu aranıyor..."
    DETECTED=$("$CLI" board list 2>/dev/null \
        | awk '/arduino:avr:uno|Arduino Uno/ {print $1}' \
        | head -n1)

    if [[ -z "$DETECTED" ]]; then
        # Fallback: ttyACM* veya ttyUSB* portlarını dene
        DETECTED=$(ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null | head -n1 || true)
    fi

    [[ -n "$DETECTED" ]] || error "Arduino bulunamadi! USB kablosunu kontrol et ve tekrar dene.\n       Elle belirtmek icin: $0 /dev/ttyACM0"
    PORT="$DETECTED"
fi
info "Kullanilacak port: $PORT"

# ── 5. Compile ───────────────────────────────────────────────────────────────
info "Derleniyor..."
"$CLI" compile \
    --fqbn "$BOARD" \
    "$SKETCH_DIR" \
    && info "Derleme basarili." \
    || error "Derleme basarisiz! Yukaridaki hatalara bak."

# ── 6. Upload ────────────────────────────────────────────────────────────────
info "Arduino'ya yukleniyor ($PORT)..."
"$CLI" upload \
    --fqbn "$BOARD" \
    --port "$PORT" \
    "$SKETCH_DIR" \
    && info "✅ Yukleme tamamlandi! Arduino hazir." \
    || error "Yukleme basarisiz! Port: $PORT — izin sorunu olabilir, su komutu dene:\n       sudo usermod -aG dialout $USER  (sonra oturumu yenile)"

echo ""
info "Servo pin 8, Baud: 115200"
info "Python tarafinda ARDUINO_MODE='usb' oldugunu kontrol et (config.py)"
