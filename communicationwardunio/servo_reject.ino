/*
 * servo_reject.ino
 *
 * Raspberry Pi'dan USB Serial üzerinden "REJECT\n" geldiğinde:
 *   1. Continuous servo ile kapağı aç (belirli ms)
 *   2. Bekle — yük düşsün
 *   3. Servoy ters çevir, kapağı kapat
 *   4. Tekrar "REJECT" beklemeye dön
 *
 * Kullanılan komutlar:
 *   "REJECT\n"  — kapağı aç/kapat döngüsünü tetikle
 *
 * Baud rate: 115200 (config.py DEFAULT_BAUD_RATE ile eşleşmeli)
 *
 * Continuous servo değerleri:
 *   90  → DUR
 *   180 → İLERİ (kapak açılma yönü)
 *   0   → GERİ (kapak kapanma yönü)
 *
 * NOT: OPEN_MS ve CLOSE_MS değerlerini kendi servona göre
 *      deneme-yanılma ile ayarla.
 */

#include <Servo.h>

// ── Pinler ──────────────────────────────────────────────────────────────────
const int SERVO_PIN      = 8;

// ── Süre ayarları (ms) ──────────────────────────────────────────────────────
const int OPEN_MS        = 270;   // kapağı tam açmak için gereken süre
const int LID_OPEN_WAIT  = 2000;  // kapak açık bekle (yük düşsün)
const int CLOSE_MS       = 270;   // kapağı tam kapatmak için gereken süre
const int SETTLE_MS      = 200;   // işlem bittikten sonra kısa bekleme

// ── Servo değerleri ─────────────────────────────────────────────────────────
const int SERVO_STOP     = 90;
const int SERVO_OPEN_DIR = 180;   // kapak açılma yönü
const int SERVO_CLOSE_DIR = 0;    // kapak kapanma yönü

Servo myServo;

// Kapak açık mı? Döngü içinde tekrar tetiklenmesini önler.
volatile bool busy = false;

// ── Yardımcı fonksiyonlar ────────────────────────────────────────────────────
void servoStop() {
  myServo.write(SERVO_STOP);
}

void openLid() {
  myServo.write(SERVO_OPEN_DIR);
  delay(OPEN_MS);
  servoStop();
}

void closeLid() {
  myServo.write(SERVO_CLOSE_DIR);
  delay(CLOSE_MS);
  servoStop();
}

void rejectCycle() {
  // Kapağı aç
  openLid();

  // Yük düşsün, bekle
  delay(LID_OPEN_WAIT);

  // Kapağı kapat
  closeLid();

  // Stabilizasyon
  delay(SETTLE_MS);
}

// ── Setup ────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  myServo.attach(SERVO_PIN);
  servoStop();            // Başlangıçta dur
  delay(300);

  Serial.println("READY");   // Pi'ye hazır olduğunu bildir (opsiyonel)
}

// ── Loop ─────────────────────────────────────────────────────────────────────
void loop() {
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd == "REJECT" && !busy) {
      busy = true;
      rejectCycle();
      busy = false;
    }
    // ACCEPT için hiçbir şey yapılmıyor — sadece yoksay
  }
}
