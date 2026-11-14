// Kaiku UNO Q MCU sketch: KY-039 heartbeat (via KY-053 ADS1115), KY-054 light, KY-035 hall
// (pan homing), Modulino Buzzer chimes, LED-matrix status. Talks only to the Linux app (../python) through the Bridge.
// Interface: ../AGENTS.md and ../python/kaiku_unoq/bridge.py.
//
// Provides (Linux calls): buzz_pattern(name) · ppg_start() · ppg_stop() · light_read() -> int ·
//                         status_set(name) · ping() -> version
// Notifies (Linux provides): on_ppg(t0_ms, fs_hz, "csv") · on_hall(at_home 0|1, t_ms) · mcu_ready()
// Chime names = contracts Chime: wake ok start_drum end_drum alert (alert = device fault only, never mood/safety).
//
// VERIFY on the board (App Lab, Arduino core on Zephyr): Bridge.provide with String / int args and int/String
// returns; Modulino.begin(Wire1) for Qwiic; Wire = header SDA/SCL; analogReadResolution(14).

#include <Arduino_RouterBridge.h>
#include <Arduino_LED_Matrix.h>
#include <Arduino_Modulino.h>
#include <Wire.h>
#include "config.h"

ArduinoLEDMatrix matrix;
ModulinoBuzzer buzzer;

// ------------------------------------------------------------------ status matrix (hidden; debug only)
static uint8_t frame[8 * 13];
static void drawStatus(const String& s) {
  memset(frame, 0, sizeof(frame));
  if (s == "ok") {                       // small tick
    frame[5 * 13 + 4] = frame[6 * 13 + 5] = frame[5 * 13 + 6] = frame[4 * 13 + 7] = frame[3 * 13 + 8] = STATUS_LEVEL;
  } else if (s == "error") {             // X
    for (int i = 0; i < 5; i++) { frame[(1 + i) * 13 + 4 + i] = STATUS_LEVEL; frame[(1 + i) * 13 + 8 - i] = STATUS_LEVEL; }
  } else {                               // "boot" / "net": one dot
    frame[3 * 13 + 6] = STATUS_LEVEL;
  }
  matrix.draw(frame);
}

// ------------------------------------------------------------------ buzzer (non-blocking pattern player)
struct Note { uint16_t hz; uint16_t ms; };
static Note pattern[BUZZER_MAX_NOTES];
static uint8_t patLen = 0, patIdx = 0;
static uint32_t noteEndsAt = 0;
static bool buzzerOk = false;

// Fills the global `pattern` (no Note in the signature: Arduino's auto-prototypes land above the struct).
static uint8_t loadPattern(const String& n) {
  Note* p = pattern;
  if (n == "wake")       { p[0] = {660, 80}; p[1] = {880, 120}; return 2; }
  if (n == "ok")         { p[0] = {1320, 60}; return 1; }
  if (n == "start_drum") { p[0] = {880, 60}; p[1] = {0, 60}; p[2] = {880, 60}; return 3; }
  if (n == "end_drum")   { p[0] = {1320, 80}; p[1] = {990, 80}; p[2] = {660, 120}; return 3; }
  if (n == "alert")      { p[0] = {440, 300}; p[1] = {0, 150}; p[2] = {440, 300}; p[3] = {0, 150}; p[4] = {440, 300}; return 5; }
  return 0;
}

static void tickBuzzer(uint32_t now) {
  if (patIdx >= patLen || now < noteEndsAt) return;
  Note n = pattern[patIdx++];
  // tone() is non-blocking and the buzzer never reports back, so we wait the duration ourselves (millis).
  if (n.hz > 0 && buzzerOk) buzzer.tone(n.hz, n.ms);
  noteEndsAt = now + n.ms;
}

// ------------------------------------------------------------------ hall (pan home)
static bool atHome = false;
static uint32_t nextHall = 0;

static void tickHall(uint32_t now) {
  if (!HAS_HALL || now < nextHall) return;
  nextHall = now + HALL_POLL_MS;
  int d = abs(analogRead(HALL_PIN) - HALL_MID);        // either magnet pole
  bool home = atHome ? d > HALL_DELTA - HALL_HYST : d > HALL_DELTA;
  if (home != atHome) {
    atHome = home;
    Bridge.notify("on_hall", (int)home, (int)now);
  }
}

// ------------------------------------------------------------------ KY-039 via ADS1115 (only between ppg_start/stop)
static bool adsOk = false, ppgOn = false;
static uint32_t ppgNextUs = 0, ppgT0 = 0;
static int16_t ppgBuf[PPG_BATCH];
static uint8_t ppgN = 0;

static bool adsWrite(uint8_t reg, uint8_t hi, uint8_t lo) {
  Wire.beginTransmission(ADS_ADDR);
  Wire.write(reg); Wire.write(hi); Wire.write(lo);
  return Wire.endTransmission() == 0;
}

static int16_t adsRead() {
  Wire.beginTransmission(ADS_ADDR);
  Wire.write(0x00);                                    // conversion register
  Wire.endTransmission();
  Wire.requestFrom(ADS_ADDR, 2);
  if (Wire.available() < 2) return 0;
  return (int16_t)((Wire.read() << 8) | Wire.read());
}

static void tickPpg() {
  if (!ppgOn || !adsOk) return;
  uint32_t us = micros();
  if ((int32_t)(us - ppgNextUs) < 0) return;
  ppgNextUs += 1000000UL / PPG_FS_HZ;                  // fixed grid -> stable fs_hz (hub HRV needs it)
  if (ppgN == 0) ppgT0 = millis();
  ppgBuf[ppgN++] = adsRead();
  if (ppgN < PPG_BATCH) return;
  String csv;
  csv.reserve(PPG_BATCH * 7);
  for (uint8_t i = 0; i < PPG_BATCH; i++) { if (i) csv += ','; csv += ppgBuf[i]; }
  ppgN = 0;
  Bridge.notify("on_ppg", (int)ppgT0, (int)PPG_FS_HZ, csv);
}

// ------------------------------------------------------------------ bridge handlers
void buzz_pattern(String name) { patLen = loadPattern(name); patIdx = 0; noteEndsAt = 0; }
void ppg_start() { ppgOn = true; ppgN = 0; ppgNextUs = micros(); }
void ppg_stop() { ppgOn = false; ppgN = 0; }
int light_read() { return analogRead(LIGHT_PIN); }
void status_set(String name) { drawStatus(name); }
String ping() { return String(KAIKU_SKETCH_VERSION) + (adsOk ? "" : " ads-missing") + (buzzerOk ? "" : " buzzer-missing"); }

void setup() {
  Bridge.begin();
  Bridge.provide("buzz_pattern", buzz_pattern);
  Bridge.provide("ppg_start", ppg_start);
  Bridge.provide("ppg_stop", ppg_stop);
  Bridge.provide("light_read", light_read);
  Bridge.provide("status_set", status_set);
  Bridge.provide("ping", ping);
  analogReadResolution(ADC_BITS);

  matrix.begin();
  matrix.setGrayscaleBits(3);
  drawStatus("boot");

  Modulino.begin(Wire1);                               // Qwiic is Wire1 on the UNO Q, not Wire
  buzzerOk = buzzer.begin();
  Wire.begin();                                        // header SDA/SCL: the KY-053
  adsOk = adsWrite(0x01, ADS_CONFIG_HI, ADS_CONFIG_LO);

  Bridge.notify("mcu_ready");
}

void loop() {
  uint32_t now = millis();
  tickPpg();
  tickHall(now);
  tickBuzzer(now);
}
