// Kaiku head: a desk companion for the morning check-in ritual.
// Eyes on the screen, a pan/purr motor, an ear dial (knob) for mood/energy/
// sleep, a chest light that paces a guided breath, a motion sensor that feels
// drumming on the head, a microphone that notices someone and a speaker voice.
// All measurements are sent to the hub as JSON lines; the hub can drive every
// step by command.
#include <Arduino.h>
#include "transport.h"
#include "esp_system.h"
#include "pins.h"
#include "modules/shared/atech_helpers.h"
#include "modules/display/st7735_tft.h"
#include "modules/input/rotary_encoder.h"
#include "modules/audio/speaker.h"
#include "modules/audio/microphone.h"
#include "modules/motor/dc_motor.h"
#include "modules/sensor/icm40608.h"
#include "modules/led/neopixel.h"
#include "i2c_software.h"
#include "kaiku_net.h"   // kaiku_net: Wi-Fi + MQTT to the UNO Q and hub (contracts)
#include "driver/gpio.h"   // kaiku: motor pin check

ST7735_TFT st7735_tft(PIN_ST7735_TFT_D, PIN_ST7735_TFT_B, PIN_ST7735_TFT_C, PIN_ST7735_TFT_A);
RotaryEncoder rotary_encoder_knob(PIN_ROTARY_ENCODER_KNOB_A, PIN_ROTARY_ENCODER_KNOB_B, PIN_ROTARY_ENCODER_KNOB_C, PIN_ROTARY_ENCODER_KNOB_D);
Speaker speaker(PIN_SPEAKER_B, PIN_SPEAKER_A, PIN_SPEAKER_D);
Microphone microphone(PIN_MICROPHONE_A, PIN_MICROPHONE_B, PIN_MICROPHONE_C, PIN_MICROPHONE_D);
DCMotor dc_motor(PIN_DC_MOTOR_B, PIN_DC_MOTOR_A);
SoftwareI2C icm40608_imu_i2c(PIN_ICM40608_IMU_SDA, PIN_ICM40608_IMU_SCL);
ICM40608 icm40608_imu(&icm40608_imu_i2c);
NeoPixelGrid neopixel_grid(PIN_NEOPIXEL_GRID_A, PIN_NEOPIXEL_GRID_B);

// ---------------- state ----------------
enum Mode { IDLE, GREET, DIAL_MOOD, DIAL_ENERGY, DIAL_SLEEP, BREATHE, DRUM, DONE };
static Mode mode = IDLE;
static unsigned long modeStart = 0;
static const char* modeName(Mode m) {
  switch (m) {
    case IDLE: return "idle"; case GREET: return "greet"; case DIAL_MOOD: return "mood";
    case DIAL_ENERGY: return "energy"; case DIAL_SLEEP: return "sleep"; case BREATHE: return "breathe";
    case DRUM: return "drum"; default: return "done";
  }
}

enum Eyes { EYES_CALM, EYES_HAPPY, EYES_WIDE, EYES_SAD, EYES_SLEEPY };
static Eyes eyes = EYES_CALM;

static int dialValue = 5;            // 1..10 while dialling
static int mood = -1, energy = -1, sleepQ = -1;
static int knobSign = -1;            // getPosition counts up CCW; CW = higher
static int32_t lastKnobPos = 0;

static int16_t soundThreshold = 3000;
static int16_t lastPeak = 0;
static unsigned long quietUntil = 0;

// breathing: 4 s in, 6 s out
static const unsigned long IN_MS = 4000, OUT_MS = 6000;
static int breathCycles = 6;

// drumming
static unsigned long drumMs = 20000;
static int taps = 0;
static unsigned long firstTap = 0, lastTap = 0;
static float forceSum = 0, forceMax = 0, curForce = 0;
static float shakeG = 1.3f;

// motor: pan for a while, or purr
static int panSpeed = 0;             // -100..100
static unsigned long panUntil = 0;
static unsigned long purrUntil = 0;

static EveryTimer micTimer, frameTimer, statusTimer, ledTimer;
static bool dirty = true;
static bool pressedLatch = false;
static int knobSteps = 0;
static bool tapLatch = false;

static void emit(const char* type, const char* payload) {
  Serial.printf("{\"type\":\"%s\",\"payload\":%s}\n", type, payload);
}

static void setMode(Mode m) {
  mode = m; modeStart = millis(); dirty = true;
  char b[64]; snprintf(b, sizeof b, "{\"step\":\"%s\"}", modeName(m));
  emit("ritual_step", b);
  kaiku_net::step(modeName(m));   // kaiku_net
  if (m == DIAL_MOOD || m == DIAL_ENERGY || m == DIAL_SLEEP) { dialValue = 5; eyes = EYES_CALM; }
  if (m == BREATHE) eyes = EYES_SLEEPY;
  if (m == DRUM) { kaiku_net::chime("start_drum");   /* kaiku_net */ taps = 0; firstTap = lastTap = 0; forceSum = forceMax = curForce = 0; eyes = EYES_WIDE; }
  if (m == IDLE) { eyes = EYES_CALM; quietUntil = millis() + 3000; }
  if (m == DONE) eyes = EYES_HAPPY;
}

static void chirp() { speaker.playNote(NOTE_C5, 70); speaker.playNote(NOTE_G5, 110); }
static void purr(unsigned long ms) { purrUntil = millis() + ms; }

static void startGreeting() {
  setMode(GREET); eyes = EYES_WIDE;
  chirp(); purr(1500);
  kaiku_net::chime("wake");   // kaiku_net: the UNO Q buzzer answers
  emit("greet", "{\"offer\":\"ritual\"}");
}

static void startRitual() { mood = energy = sleepQ = -1; setMode(DIAL_MOOD); speaker.playNote(NOTE_E5, 80); }

static void finishDrum() {
  float bpm = (taps > 1 && lastTap > firstTap) ? 60000.0f * (taps - 1) / (lastTap - firstTap) : 0;
  char b[160];
  snprintf(b, sizeof b, "{\"taps\":%d,\"tempo_bpm\":%.1f,\"force_avg_g\":%.2f,\"force_max_g\":%.2f}",
           taps, bpm, taps ? forceSum / taps : 0.0f, forceMax);
  emit("drum", b);
  kaiku_net::chime("end_drum");   // kaiku_net
}

static void finishRitual() {
  char b[96];
  snprintf(b, sizeof b, "{\"mood\":%d,\"energy\":%d,\"sleep\":%d}", mood, energy, sleepQ);
  emit("ritual_done", b);
  setMode(DONE); chirp();
}

static void advance() {   // the step after the current one
  switch (mode) {
    case IDLE: startGreeting(); break;
    case GREET: startRitual(); break;
    case DIAL_MOOD: setMode(DIAL_ENERGY); break;
    case DIAL_ENERGY: setMode(DIAL_SLEEP); break;
    case DIAL_SLEEP: setMode(BREATHE); break;
    case BREATHE: emit("breathe", "{\"completed\":false}"); setMode(DRUM); break;
    case DRUM: finishDrum(); finishRitual(); break;
    case DONE: setMode(IDLE); break;
  }
}

static void confirmDial() {
  char b[64]; snprintf(b, sizeof b, "{\"item\":\"%s\",\"value\":%d}", modeName(mode), dialValue);
  emit("dial", b);
  if (mode == DIAL_MOOD) mood = dialValue;
  else if (mode == DIAL_ENERGY) energy = dialValue;
  else sleepQ = dialValue;
  speaker.playNote(NOTE_A5, 60);
  advance();
}

// ---------------- outputs ----------------
static void applyMotor() {
  unsigned long now = millis();
  if (now < panUntil && panSpeed != 0) {
    dc_motor.setSpeed((int16_t)(panSpeed * 255 / 100));
  } else if (now < purrUntil) {
    // purr: short alternating nudges that buzz rather than turn
    dc_motor.setSpeed(((now / 40) % 2) ? 110 : -110);
  } else {
    if (panUntil && now >= panUntil) { panUntil = 0; panSpeed = 0; emit("pan", "{\"done\":true}"); }
    dc_motor.brake();
  }
}

// breath level 0..1 and whether inhaling
static float breathLevel(bool* inhale) {
  unsigned long t = (millis() - modeStart) % (IN_MS + OUT_MS);
  if (t < IN_MS) { *inhale = true; return (float)t / IN_MS; }
  *inhale = false; return 1.0f - (float)(t - IN_MS) / OUT_MS;
}

static void updateChest() {
  uint8_t r = 0, g = 0, b = 0, bright = 51;
  unsigned long now = millis();
  switch (mode) {
    case IDLE: { float s = 0.5f + 0.5f * sinf(now / 1600.0f); r = 40; g = 20; b = 80; bright = 4 + (uint8_t)(s * 8); break; }
    case GREET: r = 255; g = 160; b = 60; bright = 40; break;
    case DIAL_MOOD: case DIAL_ENERGY: case DIAL_SLEEP: {
      neopixel_grid.setBrightness(30);
      neopixel_grid.clear();
      for (int i = 0; i < 9; i++) if (i < dialValue) neopixel_grid.setPixel(i, 255 - dialValue * 20, 60 + dialValue * 19, 40);
      neopixel_grid.show(); return;
    }
    case BREATHE: { bool in; float l = breathLevel(&in); r = 40; g = 120; b = 255; bright = 2 + (uint8_t)(l * 49); break; }
    case DRUM: { r = 255; g = 60; b = 200; float f = curForce > 2 ? 1 : curForce / 2; bright = 6 + (uint8_t)(f * 45); break; }
    case DONE: r = 80; g = 255; b = 100; bright = 30; break;
  }
  neopixel_grid.setBrightness(bright);
  neopixel_grid.setAll(r, g, b);
  neopixel_grid.show();
}

static void drawEyes(int cy) {
  const uint16_t W = ST7735_TFT::COLOR_WHITE, K = ST7735_TFT::COLOR_BLACK;
  bool blink = (millis() % 4000) < 140 && eyes != EYES_WIDE;
  for (int i = 0; i < 2; i++) {
    int cx = i ? 58 : 22;
    if (blink) { st7735_tft.fillRect(cx - 14, cy - 2, 28, 4, W); continue; }
    switch (eyes) {
      case EYES_WIDE:  st7735_tft.fillCircle(cx, cy, 17, W); st7735_tft.fillCircle(cx, cy, 6, K); break;
      case EYES_HAPPY: st7735_tft.fillCircle(cx, cy, 14, W); st7735_tft.fillRect(cx - 15, cy, 30, 16, K); break;
      case EYES_SAD:   st7735_tft.fillCircle(cx, cy, 13, W); st7735_tft.fillTriangle(cx - 15, cy - 15, cx + 15, cy - 15, i ? cx + 15 : cx - 15, cy - 2, K); break;
      case EYES_SLEEPY: st7735_tft.fillCircle(cx, cy, 13, W); st7735_tft.fillRect(cx - 15, cy - 15, 30, 13, K); break;
      default: st7735_tft.fillCircle(cx, cy, 13, W); st7735_tft.fillCircle(cx + 3, cy + 2, 5, K); break;
    }
  }
}

static void drawFrame() {
  char buf[24];
  st7735_tft.clear();
  drawEyes(40);
  switch (mode) {
    case IDLE: st7735_tft.displayText("hei!", 26, 120, 1, ST7735_TFT::COLOR_CYAN); break;
    case GREET:
      st7735_tft.displayText("Huomenta!", 13, 92, 1, ST7735_TFT::COLOR_YELLOW);
      st7735_tft.displayText("press ear", 13, 120, 1, ST7735_TFT::COLOR_WHITE);
      st7735_tft.displayText("to start", 16, 132, 1, ST7735_TFT::COLOR_WHITE); break;
    case DIAL_MOOD: case DIAL_ENERGY: case DIAL_SLEEP:
      st7735_tft.displayText(mode == DIAL_MOOD ? "MOOD" : mode == DIAL_ENERGY ? "ENERGY" : "SLEEP",
                             8, 86, 1, ST7735_TFT::COLOR_CYAN);
      snprintf(buf, sizeof buf, "%d", dialValue);
      st7735_tft.displayText(buf, 8, 100, 3, ST7735_TFT::COLOR_WHITE);
      st7735_tft.drawRect(8, 132, 64, 10, ST7735_TFT::COLOR_WHITE);
      st7735_tft.fillRect(10, 134, 6 * dialValue, 6, ST7735_TFT::COLOR_ORANGE);
      st7735_tft.displayText("press = ok", 8, 148, 1, ST7735_TFT::COLOR_MAGENTA); break;
    case BREATHE: {
      bool in; float l = breathLevel(&in);
      st7735_tft.displayText(in ? "breathe in" : "breathe out", 6, 92, 1, ST7735_TFT::COLOR_CYAN);
      st7735_tft.fillCircle(40, 128, 4 + (int)(l * 22), ST7735_TFT::COLOR_BLUE);
      break;
    }
    case DRUM: {
      // the clock starts at the first tap; until then the full time is shown
      unsigned long ran = taps ? millis() - firstTap : 0;
      unsigned long left = ran >= drumMs ? 0 : (drumMs - ran) / 1000;
      st7735_tft.displayText("DRUM!", 14, 86, 2, ST7735_TFT::COLOR_MAGENTA);
      snprintf(buf, sizeof buf, "taps %d", taps);
      st7735_tft.displayText(buf, 8, 112, 1, ST7735_TFT::COLOR_WHITE);
      snprintf(buf, sizeof buf, "%lus left", left);
      st7735_tft.displayText(buf, 8, 128, 1, ST7735_TFT::COLOR_WHITE);
      break;
    }
    case DONE: st7735_tft.displayText("kiitos!", 18, 110, 1, ST7735_TFT::COLOR_GREEN); break;
  }
  st7735_tft.display();
}

static const char* resetReason() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON: return "POWERON"; case ESP_RST_EXT: return "EXT";
    case ESP_RST_SW: return "SOFTWARE"; case ESP_RST_PANIC: return "PANIC";
    case ESP_RST_INT_WDT: return "INT_WDT"; case ESP_RST_TASK_WDT: return "TASK_WDT";
    case ESP_RST_WDT: return "WDT"; case ESP_RST_BROWNOUT: return "BROWNOUT";
    case ESP_RST_DEEPSLEEP: return "DEEPSLEEP"; default: return "UNKNOWN";
  }
}

static Eyes eyesFrom(const char* v) {
  if (!strcmp(v, "happy")) return EYES_HAPPY; if (!strcmp(v, "wide")) return EYES_WIDE;
  if (!strcmp(v, "sad")) return EYES_SAD; if (!strcmp(v, "sleepy")) return EYES_SLEEPY;
  return EYES_CALM;
}

// kaiku: the motor is on port 14 (GPIO36/35); port 11 only turned one way (its GPIO44 is UART0 RX). Only one of
// port 14's lines was seen working before (LED bench), so check each can be driven high and low before LEDC attaches
// them. Both lines move together (brake / coast), so the motor does not turn. Result: health details `motor_pins`.
static const char* freeMotorPins() {
  static char r[24];
  const int pins[2] = {PIN_DC_MOTOR_A, PIN_DC_MOTOR_B};
  for (int p : pins) { gpio_reset_pin((gpio_num_t)p); gpio_set_direction((gpio_num_t)p, GPIO_MODE_INPUT_OUTPUT); }
  int hi[2], lo[2];
  for (int p : pins) gpio_set_level((gpio_num_t)p, 1);
  delay(3);
  for (int i = 0; i < 2; i++) hi[i] = gpio_get_level((gpio_num_t)pins[i]);
  for (int p : pins) gpio_set_level((gpio_num_t)p, 0);
  delay(3);
  for (int i = 0; i < 2; i++) lo[i] = gpio_get_level((gpio_num_t)pins[i]);
  const char* w[2];
  for (int i = 0; i < 2; i++) w[i] = (hi[i] && !lo[i]) ? "ok" : (!hi[i] && !lo[i]) ? "low" : (hi[i] && lo[i]) ? "high" : "odd";
  snprintf(r, sizeof(r), "%d:%s %d:%s", pins[0], w[0], pins[1], w[1]);
  return r;
}

void setup() {
  Serial.setRxBufferSize(8192);
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);
  p2p_transport_setup();
  icm40608_imu_i2c.begin(100000);
  st7735_tft.begin();
  st7735_tft.setRotation(2);   // portrait, image top toward the board's top edge
  rotary_encoder_knob.begin();
  speaker.begin();
  microphone.begin();
  kaiku_net::motorPins(freeMotorPins());   // kaiku: before LEDC takes the pins
  dc_motor.begin();
  bool imuOk = icm40608_imu.begin();
  icm40608_imu.setMountRotation(270);
  neopixel_grid.begin();

  speaker.setVolume(0.4f);
  icm40608_imu.setShakeThreshold(shakeG);
  rotary_encoder_knob.setAcceleration(false);
  rotary_encoder_knob.setRingColor(255, 140, 40);
  rotary_encoder_knob.setRingBrightness(40);
  lastKnobPos = rotary_encoder_knob.getPosition();
  setMode(IDLE);
  drawFrame();
  kaiku_net::begin();   // kaiku_net

  Serial.printf("{\"type\":\"boot\",\"payload\":{\"reset_reason\":\"%s\",\"free_heap\":%u,\"modules\":["
                "{\"instance\":\"st7735_tft\",\"module\":\"st7735_tft\",\"ok\":true,\"detectable\":false},"
                "{\"instance\":\"rotary_encoder_knob\",\"module\":\"rotary_encoder_knob\",\"ok\":true,\"detectable\":false},"
                "{\"instance\":\"speaker\",\"module\":\"speaker\",\"ok\":true,\"detectable\":false},"
                "{\"instance\":\"microphone\",\"module\":\"microphone\",\"ok\":true,\"detectable\":false},"
                "{\"instance\":\"dc_motor\",\"module\":\"dc_motor\",\"ok\":true,\"detectable\":false},"
                "{\"instance\":\"icm40608_imu\",\"module\":\"icm40608_imu\",\"ok\":%s,\"detectable\":false},"
                "{\"instance\":\"neopixel_grid\",\"module\":\"neopixel_grid\",\"ok\":true,\"detectable\":false}]}}\n",
                resetReason(), (unsigned)ESP.getFreeHeap(), imuOk ? "true" : "false");
}

void loop() {
  p2p_transport_loop();
  kaiku_net::tick();   // kaiku_net

  // ---- commands from the hub ----
  P2PCommand cmd;
  while (p2p_next_command(&cmd) || kaiku_net::nextCommand(&cmd)) {   // kaiku_net: cmd.head too
    const char* a = cmd.action;
    if (!strcmp(a, "greet")) startGreeting();
    else if (!strcmp(a, "ritual")) startRitual();
    else if (!strcmp(a, "next")) advance();
    else if (!strcmp(a, "breathe")) { breathCycles = cmd.value[0] ? constrain(atoi(cmd.value), 1, 30) : 6; setMode(BREATHE); }
    else if (!strcmp(a, "drum")) { drumMs = cmd.value[0] ? constrain(atoi(cmd.value), 5, 120) * 1000UL : 20000; setMode(DRUM); }
    else if (!strcmp(a, "idle") || !strcmp(a, "stop")) { panUntil = purrUntil = 0; setMode(IDLE); }
    else if (!strcmp(a, "pan")) { panSpeed = constrain(atoi(cmd.value), -100, 100); panUntil = millis() + 600; }
    else if (!strcmp(a, "purr")) purr(cmd.value[0] ? constrain(atoi(cmd.value), 100, 10000) : 1500);
    else if (!strcmp(a, "eyes")) { eyes = eyesFrom(cmd.value); dirty = true; }
    else if (!strcmp(a, "chirp")) chirp();
    else if (!strcmp(a, "threshold")) soundThreshold = (int16_t)constrain(atoi(cmd.value), 100, 32000);
    else if (!strcmp(a, "tap_sensitivity")) { shakeG = constrain(atof(cmd.value), 0.5f, 3.0f); icm40608_imu.setShakeThreshold(shakeG); }
    else if (!strcmp(a, "knob_reverse")) knobSign = -knobSign;
    else if (!strcmp(a, "help"))
      emit("help", "{\"commands\":[\"greet\",\"ritual\",\"next\",\"breathe [cycles]\",\"drum [seconds]\",\"idle\",\"pan -100..100\",\"purr [ms]\",\"eyes calm|happy|wide|sad|sleepy\",\"chirp\",\"threshold 100-32000\",\"tap_sensitivity 0.5-3.0\",\"knob_reverse\"]}");
  }

  // ---- inputs every pass, latched ----
  rotary_encoder_knob.update();
  pressedLatch |= rotary_encoder_knob.wasPressed();
  int32_t pos = rotary_encoder_knob.getPosition();
  if (pos != lastKnobPos) { knobSteps += knobSign * (int)(pos - lastKnobPos); lastKnobPos = pos; }
  tapLatch |= icm40608_imu.wasShaken();
  if (kaiku_net::takeTaps()) { tapLatch = true; if (curForce < 1.0f) curForce = 1.0f; }   // kaiku_net: UNO Q knocks
  {
    float ax = icm40608_imu.readAccelX(), ay = icm40608_imu.readAccelY(), az = icm40608_imu.readAccelZ();
    float dev = fabsf(sqrtf(ax * ax + ay * ay + az * az) - 1.0f);
    if (dev > curForce) curForce = dev;
  }

  applyMotor();
  kaiku_net::moving(dc_motor.getSpeed() != 0);   // kaiku_net: the UNO Q ignores knocks while the motor runs
  if (kaiku_net::takeFace() && mode == IDLE && millis() > quietUntil) startGreeting();   // kaiku_net: UNO Q camera

  // knob
  if (knobSteps) {
    if (mode == DIAL_MOOD || mode == DIAL_ENERGY || mode == DIAL_SLEEP) {
      dialValue = constrain(dialValue + knobSteps, 1, 10); dirty = true;
      kaiku_net::ear(dialValue, knobSteps, false);   // kaiku_net
    }
    knobSteps = 0;
  }
  if (pressedLatch) {
    pressedLatch = false;
    kaiku_net::ear(dialValue, 0, true);   // kaiku_net
    if (mode == DIAL_MOOD || mode == DIAL_ENERGY || mode == DIAL_SLEEP) confirmDial();
    else if (mode == IDLE || mode == GREET || mode == DONE) advance();
    else advance();   // skip breathing or end drumming early
  }

  // drumming taps
  if (tapLatch) {
    tapLatch = false;
    if (mode == DRUM) {
      unsigned long now = millis();
      if (!taps) firstTap = now;
      lastTap = now; taps++;
      forceSum += curForce; if (curForce > forceMax) forceMax = curForce;
      speaker.playTone(180 + curForce * 120, 40);
      char b[80]; snprintf(b, sizeof b, "{\"n\":%d,\"force_g\":%.2f}", taps, curForce);
      emit("tap", b);
      dirty = true;
    } else if (mode == IDLE && millis() > quietUntil) {
      startGreeting();   // a pat on the head wakes Kaiku
    }
  }

  // timed steps
  if (mode == BREATHE && millis() - modeStart >= breathCycles * (IN_MS + OUT_MS)) {
    char b[48]; snprintf(b, sizeof b, "{\"completed\":true,\"cycles\":%d}", breathCycles);
    emit("breathe", b); setMode(DRUM); speaker.playNote(NOTE_E5, 80);
  }
  // drumming time counts from the first tap; with no tap at all, give up after DRUM_WAIT_MS
  static const unsigned long DRUM_WAIT_MS = 60000;
  if (mode == DRUM && (taps ? millis() - firstTap >= drumMs : millis() - modeStart >= DRUM_WAIT_MS)) {
    finishDrum(); finishRitual();
  }
  if (mode == GREET && millis() - modeStart > 60000) setMode(IDLE);
  if (mode == DONE && millis() - modeStart > 8000) setMode(IDLE);

  // microphone: someone speaks or claps nearby while idle
  if (micTimer.ready(30)) {
    lastPeak = microphone.getPeakAmplitude();
    if (mode == IDLE && millis() > quietUntil && lastPeak > soundThreshold) startGreeting();
  }

  if (ledTimer.ready(40)) { updateChest(); curForce *= 0.85f; }

  if (statusTimer.ready(1000)) {
    char b[200];
    snprintf(b, sizeof b, "{\"step\":\"%s\",\"dial\":%d,\"sound_peak\":%d,\"tilt\":%.1f,\"taps\":%d,\"motor\":%d}",
             modeName(mode), dialValue, lastPeak, icm40608_imu.getTiltAngle(), taps, dc_motor.getSpeed());
    emit("status", b);
  }

  if (!frameTimer.ready(mode == BREATHE ? 80 : 120) && !dirty) { delay(1); return; }
  dirty = false;
  drawFrame();
}
