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
#include "modules/input/rotary_encoder.h"
#include "modules/audio/speaker.h"
#include "modules/audio/microphone.h"
#include "modules/motor/dc_motor.h"
#include "modules/sensor/icm40608.h"
#include "modules/led/neopixel.h"
#include "i2c_software.h"
#include "kaiku_net.h"   // kaiku_net: Wi-Fi + MQTT to the UNO Q and hub (contracts)
#include "driver/gpio.h"   // kaiku: motor pin check
#include "hal/gpio_ll.h"   // input readback without replacing the I2S output route

RotaryEncoder rotary_encoder_knob(PIN_ROTARY_ENCODER_KNOB_A, PIN_ROTARY_ENCODER_KNOB_B, PIN_ROTARY_ENCODER_KNOB_C, PIN_ROTARY_ENCODER_KNOB_D);
Speaker speaker(PIN_SPEAKER_B, PIN_SPEAKER_A, PIN_SPEAKER_D);
Microphone microphone(PIN_MICROPHONE_A, PIN_MICROPHONE_B, PIN_MICROPHONE_C, PIN_MICROPHONE_D);
// Supplied by patch_microphone.py when build.sh fetches the driver. Numeric magnitudes only.
extern void kaiku_microphone_stats(uint32_t* blocks, uint32_t* even, uint32_t* odd);
DCMotor dc_motor(PIN_DC_MOTOR_B, PIN_DC_MOTOR_A);
SoftwareI2C icm40608_imu_i2c(PIN_ICM40608_IMU_SDA, PIN_ICM40608_IMU_SCL);
ICM40608 icm40608_imu(&icm40608_imu_i2c);
NeoPixelGrid neopixel_grid(PIN_NEOPIXEL_GRID_A, PIN_NEOPIXEL_GRID_B);

// ---------------- state ----------------
// kaiku: TALK (0.9.0) = awake and talking, no check-in running. A press at the greeting goes here, never straight
// into the check-in: the check-in starts only when she asks for it in words (the hub's cmd.head {ritual: start}).
enum Mode { IDLE, GREET, DIAL_MOOD, DIAL_ENERGY, DIAL_SLEEP, BREATHE, DRUM, DONE, TALK };
static Mode mode = IDLE;
static unsigned long modeStart = 0;
static const char* modeName(Mode m) {
  switch (m) {
    case IDLE: return "idle"; case GREET: return "greet"; case DIAL_MOOD: return "mood";
    case DIAL_ENERGY: return "energy"; case DIAL_SLEEP: return "sleep"; case BREATHE: return "breathe";
    case DRUM: return "drum"; case TALK: return "talk"; default: return "done";
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
static float shakeG = 1.15f;          // kaiku: total g that counts as a tap (the driver compares |g - 1| with shakeG - 1: 0.15 g)

// motor: pan for a while, or purr
static int panSpeed = 0;             // -100..100
static unsigned long panUntil = 0;
static unsigned long purrUntil = 0;

static EveryTimer micTimer, statusTimer, ledTimer;
static bool dirty = true;
static bool pressedLatch = false;
static int knobSteps = 0;
static bool tapLatch = false;
static bool micShown = false;        // kaiku_net: the ear ring is blue while the microphone streams to the hub

// kaiku: ONE way through the check-in, and nothing happens by itself that the person did not ask for (2026-11-15).
// - A press is taken once per step: none within PRESS_GUARD_MS of the last step change (a bouncing or double press
//   used to run through two or three steps), and breathing or drumming cannot be skipped in their first
//   ACTIVITY_MIN_MS (a press that was meant for the step before).
// - Kaiku wakes on a press of the ear. A face in front of the camera wakes it at most every FACE_WAKE_EVERY_MS and
//   not for RITUAL_REST_MS after a check-in ended. A bump on the table or a sound in the room wakes nothing.
static const unsigned long PRESS_GUARD_MS = 700, ACTIVITY_MIN_MS = 4000;
static const unsigned long FACE_WAKE_EVERY_MS = 10UL * 60 * 1000, RITUAL_REST_MS = 3UL * 60 * 1000;
static unsigned long lastFaceWake = 0, ritualEndedAt = 0;
// kaiku: asking twice (D58). She asked Kaiku in words for an activity; the hub armed it (cmd.head {activity}); for
// ARM_MS the next press of the ear starts THAT step instead of what a press does in the current one. The words
// alone start nothing, and neither does a press alone.
static const unsigned long ARM_MS = 20000;
// kaiku: a turn of the head that waits for the speaker (see the `pan` command)
static const unsigned long PAN_WAIT_MS = 8000;
static int panWant = 0;
static unsigned long panWantMs = 600;
static unsigned long panWantAt = 0;
static Mode armedMode = IDLE;        // IDLE = nothing armed
static Mode pausedMode = IDLE;       // kaiku: the check-in step that waits while she talks (TALK); IDLE = none
static unsigned long armedAt = 0;
static bool everFaceWake = false, everRitual = false;

// kaiku: a line goes out only when the USB buffer has room for all of it. Plugged into a computer with nobody
// reading the port, writes stalled the loop and the head fell off the broker after ~15 s (bench 2026-11-14).
static void serialLine(const char* line, size_t n) {
  if (n == 0 || Serial.availableForWrite() < (int)n) return;
  Serial.write((const uint8_t*)line, n);
}

static void emit(const char* type, const char* payload) {
  static char line[1400];
  int n = snprintf(line, sizeof line, "{\"type\":\"%s\",\"payload\":%s}\n", type, payload);
  if (n > 0 && n < (int)sizeof line) serialLine(line, n);
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
  if (m == DONE) { eyes = EYES_HAPPY; ritualEndedAt = millis(); everRitual = true; }
}

// kaiku: may this press do something now? (see PRESS_GUARD_MS)
static bool pressCounts() {
  unsigned long in = millis() - modeStart;
  if (mode == IDLE) return true;                       // waking is always allowed
  if (mode == BREATHE || mode == DRUM) return in >= ACTIVITY_MIN_MS;
  return in >= PRESS_GUARD_MS;
}
// kaiku: may a face in front of the camera start a greeting now? (see FACE_WAKE_EVERY_MS)
static bool faceMayWake() {
  unsigned long now = millis();
  if (everFaceWake && now - lastFaceWake < FACE_WAKE_EVERY_MS) return false;
  if (everRitual && now - ritualEndedAt < RITUAL_REST_MS) return false;
  return true;
}

// kaiku_net: no sound of the head's own while the hub's song, cue or voice is on the speaker (same I2S port)
static bool quiet() { return kaiku_net::speakerBusy(); }
static void chirp() { if (quiet()) return; speaker.playNote(NOTE_C5, 70); speaker.playNote(NOTE_G5, 110); }
static void purr(unsigned long ms) { purrUntil = millis() + ms; }

static void startGreeting() {
  setMode(GREET); eyes = EYES_WIDE;
  chirp(); purr(1500);
  kaiku_net::chime("wake");   // kaiku_net: the UNO Q buzzer answers
  emit("greet", "{\"offer\":\"ritual\"}");
}

static void startRitual() { mood = energy = sleepQ = -1; setMode(DIAL_MOOD); if (!quiet()) speaker.playNote(NOTE_E5, 80); }

static void finishDrum() {
  char b[160];
  if (kaiku_net::drumByHub()) {
    // kaiku_net: the hub ran this drum step (tap it back: songs, turns, levels). The head did not measure a session,
    // so it gives no tempo or average: only how many taps its own sensor felt. The hub has the result.
    snprintf(b, sizeof b, "{\"run_by\":\"hub\",\"imu_taps\":%d}", kaiku_net::drumTapsFelt());
  } else {
    float bpm = (taps > 1 && lastTap > firstTap) ? 60000.0f * (taps - 1) / (lastTap - firstTap) : 0;
    snprintf(b, sizeof b, "{\"taps\":%d,\"tempo_bpm\":%.1f,\"force_avg_g\":%.2f,\"force_max_g\":%.2f}",
             taps, bpm, taps ? forceSum / taps : 0.0f, forceMax);
  }
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
    case GREET: setMode(TALK); if (!quiet()) speaker.playNote(NOTE_E5, 80); break;   // kaiku: a press = talk
    case TALK: break;                                                                    // a press alone does nothing
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
  if (!quiet()) speaker.playNote(NOTE_A5, 60);
  advance();
}

// ---------------- outputs ----------------
// kaiku: POWER RULE (strict). The speaker amplifier and the motor share one supply; both together pull more than
// it gives. So they never run together: while any sound is on the speaker (the hub's voice, songs, cues, or a tone
// of the head's own) the motor is OFF, whatever asked for it (pan, purr, sway); it may move again once the speaker
// is quiet. That lets the speaker play at SPEAKER_VOLUME; if the motor is still turning when a sound starts, the
// speaker is at SPEAKER_VOLUME_WITH_MOTOR until the motor stops on the next pass (one loop pass, a few ms). Every motor command goes through
// driveMotor() and the volume is set in one place (powerRule), so no path can skip it.
static const float SPEAKER_VOLUME = 0.7f;                // the motor at rest (was 0.4, then 0.6: voice too quiet on the robot, 2026-11-14; 1.0 clips the amp)
static const float SPEAKER_VOLUME_WITH_MOTOR = 0.2f;     // the motor turning (only until it stops for the sound)
static bool soundOn() { return kaiku_net::speakerBusy() || speaker.isPlaying(); }
static void driveMotor(int16_t v) {
  if (soundOn()) { dc_motor.stop(); return; }            // never motor + speaker together: both lines low, no current (was: held to 128 of 255)
  dc_motor.setSpeed(v);
}
static void powerRule() {
  static bool low = false;
  bool want = dc_motor.getSpeed() != 0;
  if (want != low) { low = want; speaker.setVolume(low ? SPEAKER_VOLUME_WITH_MOTOR : SPEAKER_VOLUME); }
}

static void applyMotor() {
  unsigned long now = millis();
  if (now < panUntil && panSpeed != 0) {
    driveMotor((int16_t)(panSpeed * 255 / 100));
  } else if (now < purrUntil) {
    // purr: short alternating nudges that buzz rather than turn
    driveMotor(((now / 40) % 2) ? 110 : -110);
  } else if (int s = kaiku_net::sway()) {   // kaiku_net: the hub's sway on the beat while it holds the drum step
    driveMotor((int16_t)(s * 255 / 100));
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
    case TALK: r = 255; g = 160; b = 60; bright = 20; break;
  }
  neopixel_grid.setBrightness(bright);
  neopixel_grid.setAll(r, g, b);
  neopixel_grid.show();
}

// kaiku: no display on the head in this build (removed 2026-11-14): the eye and screen drawing is gone; `eyes`
// is still tracked so `cmd.head` eyes and the serial `eyes` command stay accepted.

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
  Serial.setTxBufferSize(2048);   // kaiku: room for the boot line (see serialLine)
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);
  p2p_transport_setup();
  icm40608_imu_i2c.begin(100000);
  rotary_encoder_knob.begin();
  speaker.begin();
  microphone.begin();
  kaiku_net::motorPins(freeMotorPins());   // kaiku: before LEDC takes the pins
  dc_motor.begin();
  bool imuOk = icm40608_imu.begin();
  icm40608_imu.setMountRotation(270);
  neopixel_grid.begin();

  speaker.setVolume(SPEAKER_VOLUME);
  icm40608_imu.setShakeThreshold(shakeG);
  rotary_encoder_knob.setAcceleration(false);
  rotary_encoder_knob.setRingColor(255, 140, 40);
  rotary_encoder_knob.setRingBrightness(40);
  lastKnobPos = rotary_encoder_knob.getPosition();
  setMode(IDLE);
  kaiku_net::begin({   // kaiku_net: Wi-Fi + MQTT, and the speaker / microphone as PCM streams for the hub
      [](const int16_t* s, int n) { speaker.writeSamples(s, n); },   // at the driver's volume (SPEAKER_VOLUME, set above)
      []() { return speaker.isPlaying(); },
      [](void (*cb)(const int16_t*, int, void*), void* ctx) { microphone.onAudio(cb, ctx); }});

  static char boot[1200];
  int bn = snprintf(boot, sizeof boot, "{\"type\":\"boot\",\"payload\":{\"reset_reason\":\"%s\",\"free_heap\":%u,\"modules\":["
                "{\"instance\":\"rotary_encoder_knob\",\"module\":\"rotary_encoder_knob\",\"ok\":true,\"detectable\":false},"
                "{\"instance\":\"speaker\",\"module\":\"speaker\",\"ok\":true,\"detectable\":false},"
                "{\"instance\":\"microphone\",\"module\":\"microphone\",\"ok\":true,\"detectable\":false},"
                "{\"instance\":\"dc_motor\",\"module\":\"dc_motor\",\"ok\":true,\"detectable\":false},"
                "{\"instance\":\"icm40608_imu\",\"module\":\"icm40608_imu\",\"ok\":%s,\"detectable\":false},"
                "{\"instance\":\"neopixel_grid\",\"module\":\"neopixel_grid\",\"ok\":true,\"detectable\":false}]}}\n",
                resetReason(), (unsigned)ESP.getFreeHeap(), imuOk ? "true" : "false");
  if (bn > 0 && bn < (int)sizeof boot) serialLine(boot, bn);
}

void loop() {
  p2p_transport_loop();
  kaiku_net::tick();   // kaiku_net
  if (kaiku_net::takeHelp()) {   // kaiku_net: cmd.head {show: help} (the hub's crisis path). No display on this head,
    panUntil = purrUntil = 0; panSpeed = 0;   // so nothing is shown: whatever runs ends quietly (no chime, no done
    speaker.stop();                           // step), the motor stands still, no tone; the head stays calm (calm())
    emit("help_screen", "{\"shown\":false,\"display\":\"none\"}");
    setMode(IDLE);
  }

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
    else if (!strcmp(a, "said")) {   // kaiku: the hub heard her say it (cmd.head {ritual}); never while idle
      if (mode != IDLE && mode != GREET) {
        armedMode = IDLE;
        bool inStep = mode == DIAL_MOOD || mode == DIAL_ENERGY || mode == DIAL_SLEEP || mode == BREATHE || mode == DRUM;
        if (!strcmp(cmd.value, "end")) { panUntil = purrUntil = 0; pausedMode = IDLE; setMode(IDLE); }
        else if (!strcmp(cmd.value, "start")) { pausedMode = IDLE; startRitual(); }       // "let's start": from mood
        else if (!strcmp(cmd.value, "pause")) {                                           // she is talking about
          if (inStep) { pausedMode = mode; panUntil = purrUntil = 0; setMode(TALK); }     // something else: the
        }                                                                                 // step waits, no chime
        else if (!strcmp(cmd.value, "resume")) {                                          // "continue": the step
          if (mode == TALK) {                                                             // that was open
            Mode go = pausedMode == IDLE ? DIAL_MOOD : pausedMode; pausedMode = IDLE;
            if (go == DIAL_MOOD) startRitual();
            else { if (go == BREATHE) breathCycles = 6; else if (go == DRUM) drumMs = 20000; setMode(go); }
          }
        }
        else if (mode == DIAL_MOOD || mode == DIAL_ENERGY || mode == DIAL_SLEEP) advance();   // a spoken dial answer
      }
    }
    else if (!strcmp(a, "arm")) {   // kaiku: asking twice
      armedMode = !strcmp(cmd.value, "drum") ? DRUM : !strcmp(cmd.value, "breathe") ? BREATHE : IDLE;
      armedAt = millis();
    }
    else if (!strcmp(a, "pan")) {
      // kaiku: the motor never runs with the speaker (POWER RULE), and a turn asked for while Kaiku is speaking used
      // to run out unseen. It now waits for the speaker to go quiet (up to PAN_WAIT_MS), then turns. Value is
      // "speed" or "speed,ms" (-100..100; 120..600 ms, 600 when not given: the serial `pan` command).
      panWant = constrain(atoi(cmd.value), -100, 100); panWantAt = millis();
      const char* comma = strchr(cmd.value, ',');
      panWantMs = comma ? constrain(atoi(comma + 1), 120, 600) : 600;
    }
    else if (!strcmp(a, "purr")) purr(cmd.value[0] ? constrain(atoi(cmd.value), 100, 10000) : 1500);
    else if (!strcmp(a, "net")) { static char nb[320]; kaiku_net::report(nb, sizeof nb); emit("net", nb); }   // kaiku_net
    else if (!strcmp(a, "eyes")) { eyes = eyesFrom(cmd.value); dirty = true; }
    else if (!strcmp(a, "chirp")) chirp();
    else if (!strcmp(a, "threshold")) soundThreshold = (int16_t)constrain(atoi(cmd.value), 100, 32000);
    else if (!strcmp(a, "mic_pins")) {
      // Enable pad readback without changing the I2S peripheral's output matrix.
      gpio_ll_input_enable(&GPIO, (gpio_num_t)PIN_MICROPHONE_B);
      gpio_ll_input_enable(&GPIO, (gpio_num_t)PIN_MICROPHONE_C);
      int ws = digitalRead(PIN_MICROPHONE_B), clk = digitalRead(PIN_MICROPHONE_C), data = digitalRead(PIN_MICROPHONE_D);
      unsigned wsEdges = 0, clkEdges = 0, dataEdges = 0;
      unsigned long until = micros() + 5000;
      while ((int32_t)(micros() - until) < 0) {
        int w = digitalRead(PIN_MICROPHONE_B), c = digitalRead(PIN_MICROPHONE_C), d = digitalRead(PIN_MICROPHONE_D);
        wsEdges += w != ws; clkEdges += c != clk; dataEdges += d != data;
        ws = w; clk = c; data = d;
      }
      char b[160];
      snprintf(b, sizeof b, "{\"window_ms\":5,\"ws_edges\":%u,\"clock_edges\":%u,\"data_edges\":%u,\"data_level\":%d}",
               wsEdges, clkEdges, dataEdges, data);
      emit("mic_pins", b);
    }
    else if (!strcmp(a, "mic_probe")) {
      uint32_t blocks, even, odd;
      kaiku_microphone_stats(&blocks, &even, &odd);
      char b[160];
      snprintf(b, sizeof b, "{\"blocks\":%lu,\"even_raw_peak\":%lu,\"odd_raw_peak\":%lu,\"lr_level\":%d}",
               (unsigned long)blocks, (unsigned long)even, (unsigned long)odd, digitalRead(PIN_MICROPHONE_A));
      emit("mic_probe", b);
    }
    else if (!strcmp(a, "mic_channel")) {
      if (!strcmp(cmd.value, "left") || !strcmp(cmd.value, "right")) {
        bool right = !strcmp(cmd.value, "right");
        microphone.setChannel(right);
        emit("mic_channel", right ? "{\"select\":\"right\",\"lr_high\":true}" : "{\"select\":\"left\",\"lr_high\":false}");
      } else emit("mic_channel", "{\"error\":\"use mic_channel left|right\"}");
    }
    else if (!strcmp(a, "tap_sensitivity")) { shakeG = constrain(atof(cmd.value), 1.05f, 3.0f); icm40608_imu.setShakeThreshold(shakeG); }
    else if (!strcmp(a, "knob_reverse")) knobSign = -knobSign;
    else if (!strcmp(a, "help"))
      emit("help", "{\"commands\":[\"greet\",\"ritual\",\"next\",\"breathe [cycles]\",\"drum [seconds]\",\"idle\",\"pan -100..100\",\"purr [ms]\",\"eyes calm|happy|wide|sad|sleepy\",\"chirp\",\"threshold 100-32000\",\"mic_channel left|right\",\"mic_probe\",\"mic_pins\",\"tap_sensitivity 1.05-3.0\",\"knob_reverse\"]}");
  }

  // ---- inputs every pass, latched ----
  rotary_encoder_knob.update();
  pressedLatch |= rotary_encoder_knob.wasPressed();
  int32_t pos = rotary_encoder_knob.getPosition();
  if (pos != lastKnobPos) { knobSteps += knobSign * (int)(pos - lastKnobPos); lastKnobPos = pos; }
  tapLatch |= icm40608_imu.wasShaken();
  {
    float ax = icm40608_imu.readAccelX(), ay = icm40608_imu.readAccelY(), az = icm40608_imu.readAccelZ();
    float dev = fabsf(sqrtf(ax * ax + ay * ay + az * az) - 1.0f);
    if (dev > curForce) curForce = dev;
  }

  applyMotor();
  powerRule();   // kaiku: speaker and motor never both at full
  kaiku_net::moving(dc_motor.getSpeed() != 0);   // kaiku_net: raw.head.pan
  if (kaiku_net::takeFace() && mode == IDLE && millis() > quietUntil && faceMayWake()) {   // kaiku_net: UNO Q camera (never while calm)
    lastFaceWake = millis(); everFaceWake = true;
    startGreeting();
  }

  // knob
  if (knobSteps) {
    if (mode == DIAL_MOOD || mode == DIAL_ENERGY || mode == DIAL_SLEEP) {
      dialValue = constrain(dialValue + knobSteps, 1, 10); dirty = true;
      kaiku_net::ear(dialValue, knobSteps, false);   // kaiku_net
    }
    knobSteps = 0;
  }
  if (armedMode != IDLE && (millis() - armedAt > ARM_MS || mode == IDLE)) armedMode = IDLE;   // kaiku: the ask ran out
  if (pressedLatch && armedMode != IDLE) {   // kaiku: asking twice: this press is her yes to the activity she asked for
    pressedLatch = false;
    Mode go = armedMode; armedMode = IDLE;
    kaiku_net::ear(dialValue, 0, true);
    // (no finishDrum when leaving a running drum step: its end chime would read as "the check-in is done")
    pausedMode = IDLE;
    if (go == BREATHE) breathCycles = 6; else drumMs = 20000;
    setMode(go);
    if (!quiet()) speaker.playNote(NOTE_E5, 80);
  }
  if (pressedLatch && !pressCounts()) pressedLatch = false;   // kaiku: not a press for this step (and not sent on)
  if (pressedLatch) {
    pressedLatch = false;
    kaiku_net::ear(dialValue, 0, true);   // kaiku_net
    if (mode == DIAL_MOOD || mode == DIAL_ENERGY || mode == DIAL_SLEEP) confirmDial();
    else if (mode == TALK) {}                 // kaiku: talking: a press starts nothing (the hub still hears it)
    else if (mode == IDLE || mode == GREET || mode == DONE) advance();
    else advance();   // skip breathing or end drumming early
  }

  // taps: felt by the orientation sensor (the only tap source; the KY-031 knock switch is gone, D55).
  // kaiku: the motor (pan and purr nudges) shakes the sensor, so nothing counts while it runs or just after;
  // one tap = one message (the jolt rings for a few readings).
  static unsigned long motorQuietAt = 0, tapAgainAt = 0;
  if (dc_motor.getSpeed() != 0) motorQuietAt = millis() + 400;
  if (tapLatch && (millis() < motorQuietAt || millis() < tapAgainAt)) tapLatch = false;
  if (tapLatch && kaiku_net::speakerBusy()) tapLatch = false;   // kaiku_net: the hub's sound on the speaker shakes the sensor too (and 150 ms after)
  if (tapLatch) {
    tapLatch = false;
    tapAgainAt = millis() + 120;
    if (curForce < shakeG - 1.0f) curForce = shakeG - 1.0f;   // the driver saw at least the threshold; our own read can miss the peak
    kaiku_net::tap(curForce);   // kaiku_net: raw.head.tap {src: imu}
    if (mode == DRUM) {
      unsigned long now = millis();
      if (!taps) firstTap = now;
      lastTap = now; taps++;
      forceSum += curForce; if (curForce > forceMax) forceMax = curForce;
      if (!kaiku_net::drumHeld() && !quiet()) speaker.playTone(180 + curForce * 120, 40);   // kaiku_net: no tap tone while the hub leads or its sound plays
      char b[80]; snprintf(b, sizeof b, "{\"n\":%d,\"force_g\":%.2f}", taps, curForce);
      emit("tap", b);
      dirty = true;
    }   // kaiku: a tap while idle wakes nothing (a bump on the table did; the ear press is the way in)
  }

  // timed steps
  if (mode == BREATHE && millis() - modeStart >= breathCycles * (IN_MS + OUT_MS)) {
    char b[48]; snprintf(b, sizeof b, "{\"completed\":true,\"cycles\":%d}", breathCycles);
    emit("breathe", b); setMode(DRUM); if (!quiet()) speaker.playNote(NOTE_E5, 80);
  }
  // drumming time counts from the first tap; with no tap at all, give up after DRUM_WAIT_MS
  static const unsigned long DRUM_WAIT_MS = 60000;
  // kaiku_net: cmd.head {drum: end} ends the step now; while {drum: hold} is fresh the head's own clock does not
  // (10 s without a hold and it does again: a silent hub never strands the head)
  bool hubEnd = kaiku_net::takeDrumEnd(), hubHold = kaiku_net::drumHeld();
  if (mode == DRUM && (hubEnd || (!hubHold && (taps ? millis() - firstTap >= drumMs : millis() - modeStart >= DRUM_WAIT_MS)))) {
    finishDrum(); finishRitual();
  }
  if (mode == GREET && millis() - modeStart > 60000) setMode(IDLE);
  if (mode == DONE && millis() - modeStart > 8000) setMode(IDLE);

  // microphone: someone speaks or claps nearby while idle
  if (micTimer.ready(30)) {
    lastPeak = microphone.getPeakAmplitude();
    // kaiku: a sound in the room wakes nothing any more (it greeted people who were only talking nearby)
  }

  if (panWant && millis() - panWantAt > PAN_WAIT_MS) panWant = 0;          // kaiku: the sound never stopped: let it go
  if (panWant && !soundOn()) { panSpeed = panWant; panUntil = millis() + panWantMs; panWant = 0; }

  if (kaiku_net::micOpen() != micShown) {   // kaiku_net: the ear ring turns blue while the microphone streams to the hub
    micShown = !micShown;                   // (the only light on this head: there is no display)
    if (micShown) rotary_encoder_knob.setRingColor(40, 160, 255); else rotary_encoder_knob.setRingColor(255, 140, 40);
  }

  if (ledTimer.ready(40)) { updateChest(); curForce *= 0.85f; }

  if (statusTimer.ready(1000)) {
    char b[200];
    snprintf(b, sizeof b, "{\"step\":\"%s\",\"dial\":%d,\"sound_peak\":%d,\"tilt\":%.1f,\"taps\":%d,\"motor\":%d}",
             modeName(mode), dialValue, lastPeak, icm40608_imu.getTiltAngle(), taps, dc_motor.getSpeed());
    emit("status", b);
  }

  dirty = false;   // kaiku: nothing to redraw without the display
  delay(1);
}
