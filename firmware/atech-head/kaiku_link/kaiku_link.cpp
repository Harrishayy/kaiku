// kaiku_link implementation. See kaiku_link.h for the contract and ../AGENTS.md for the module rules.
// Libraries (library.json dependencies): knolleary/PubSubClient, bblanchon/ArduinoJson@7.
#include "kaiku_link.h"

#include <ArduinoJson.h>
#include <ESPmDNS.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <esp_random.h>
#include <initializer_list>
#include <sys/time.h>
#include <time.h>

#include "config.h"
#include "secrets.h"  // gitignored; copy secrets.example.h

namespace kaiku {
namespace {

HeadIO io;
WiFiClient net;
PubSubClient mqtt(net);
char topicBuf[96];
uint32_t bootMs = 0, nextNetTry = 0, backoff = BACKOFF_MIN_MS, nextHealth = 0, lastHubSeen = 0, reconnects = 0;
bool hubSilent = true;

// ---------------------------------------------------------------- envelope (contracts/python/kaiku_contracts/envelope.py)
bool timeOk() { return time(nullptr) > 1700000000; }

uint64_t nowMsUtc() {
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  return (uint64_t)tv.tv_sec * 1000ULL + tv.tv_usec / 1000;
}

void isoTs(uint64_t ms, char* out, size_t n) {
  time_t s = ms / 1000;
  struct tm t;
  gmtime_r(&s, &t);
  snprintf(out, n, "%04d-%02d-%02dT%02d:%02d:%02d.%03uZ", t.tm_year + 1900, t.tm_mon + 1, t.tm_mday, t.tm_hour,
           t.tm_min, t.tm_sec, (unsigned)(ms % 1000));
}

void uuid7(uint64_t ms, char* out) {  // RFC 9562 v7, 36 chars + NUL
  uint8_t b[16];
  for (int i = 0; i < 6; i++) b[i] = (ms >> (40 - 8 * i)) & 0xFF;
  esp_fill_random(b + 6, 10);
  b[6] = 0x70 | (b[6] & 0x0F);
  b[8] = 0x80 | (b[8] & 0x3F);
  snprintf(out, 37, "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x", b[0], b[1], b[2], b[3],
           b[4], b[5], b[6], b[7], b[8], b[9], b[10], b[11], b[12], b[13], b[14], b[15]);
}

const char* topicFor(const char* kind, const char* name) {
  snprintf(topicBuf, sizeof(topicBuf), "kaiku/v1/%s/%s/%s", KAIKU_HOME_ID, kind, name);
  return topicBuf;
}

// Builds {v,id,ts,home_id,source:"head",type,payload,sim:false} around `payload` and publishes it.
bool publish(const char* type, const char* kind, const char* name, JsonDocument& payload, bool retain = false) {
  if (!mqtt.connected() || !timeOk()) return false;  // no UTC yet -> drop (raw is best-effort, QoS 0)
  JsonDocument env;
  uint64_t ms = nowMsUtc();
  char id[37], ts[32];
  uuid7(ms, id);
  isoTs(ms, ts, sizeof(ts));
  env["v"] = 1;
  env["id"] = id;
  env["ts"] = ts;
  env["home_id"] = KAIKU_HOME_ID;
  env["source"] = "head";
  env["type"] = type;
  env["payload"] = payload;
  env["sim"] = false;
  static char buf[512];
  size_t n = serializeJson(env, buf, sizeof(buf));
  bool ok = mqtt.publish(topicFor(kind, name), (const uint8_t*)buf, n, retain);
  Serial.println(buf);  // one JSON object per line: tools/ can record it over USB too
  return ok;
}

// ---------------------------------------------------------------- motor: open loop + hall homing
enum Mode { IDLE, TO_TARGET, HOMING, GESTURE };
struct Seg { int speed; uint16_t ms; };
Mode mode = IDLE;
Seg segs[6];
uint8_t segN = 0, segI = 0;
uint32_t segStart = 0, lastMotorTick = 0, nextPan = 0, homeStart = 0;
int curSpeed = 0, targetSpeed = 0, homeDir = 1, homeTries = 0;
float deg = 0, targetDeg = 0;
bool homed = !HAS_HALL, atHome = false, bootHomePending = true;   // no hall: power-on position is home (0 deg)

bool moving() { return mode != IDLE || curSpeed != 0; }

void startSegs(Mode m, std::initializer_list<Seg> list) {
  segN = 0;
  for (auto s : list) if (segN < 6) segs[segN++] = s;
  segI = 0;
  segStart = millis();
  mode = m;
}

void stopMotor() {
  mode = IDLE;
  targetSpeed = curSpeed = 0;
  io.motorBrake();
}

uint16_t msFor(float d, int speed) {
  float rate = MOTOR_DEG_PER_S_FULL * abs(speed) / 255.0f;
  uint32_t ms = rate > 0 ? (uint32_t)(fabsf(d) / rate * 1000.0f) : 0;
  return (uint16_t)min<uint32_t>(ms, MOTOR_MAX_RUN_MS);
}

void goTo(float target, float speed01) {
  targetDeg = constrain(target, -PAN_LIMIT_DEG, PAN_LIMIT_DEG);
  float d = targetDeg - deg;
  if (fabsf(d) < PAN_DEADBAND_DEG) return;
  int sp = (int)(constrain(speed01, 0.1f, 1.0f) * 255) * (d > 0 ? 1 : -1);
  startSegs(TO_TARGET, {{sp, msFor(d, sp)}});
}

// Home = the turntable magnet over the KY-035 (raw/sensors/hall from the UNO Q). Drive slowly toward where we think
// the front is; brake on the edge; give up after HOME_TRY_MS and try the other way once.
// Without a hall sensor (HAS_HALL 0): home = drive back to the dead-reckoned 0 deg (the power-on position).
void home() {
#if !HAS_HALL
  goTo(0, HOME_SPEED / 255.0f);
  return;
#endif
  if (atHome) { stopMotor(); deg = 0; homed = true; return; }
  homeDir = deg > 0 ? -1 : 1;
  homeTries = 0;
  homeStart = millis();
  mode = HOMING;
  targetSpeed = HOME_SPEED * homeDir;
}

void onHall(bool home_) {
  if (!HAS_HALL) return;   // nothing fitted: a floating input must never re-zero or brake the head
  atHome = home_;
  if (home_ && mode == HOMING) { stopMotor(); deg = 0; homed = true; }
  else if (home_ && !moving()) { deg = 0; homed = true; }  // passing the magnet re-zeroes the estimate
}

void gesture(const char* g) {
  int s = GESTURE_SPEED;
  if (!strcmp(g, "look_left")) startSegs(GESTURE, {{-s, LOOK_MS}, {0, 300}});
  else if (!strcmp(g, "look_right")) startSegs(GESTURE, {{s, LOOK_MS}, {0, 300}});
  else if (!strcmp(g, "shake"))
    startSegs(GESTURE, {{s, SHAKE_PULSE_MS}, {-s, SHAKE_PULSE_MS}, {s, SHAKE_PULSE_MS}, {-s, SHAKE_PULSE_MS}});
}

void motorTick(uint32_t now) {
  float dt = (now - lastMotorTick) / 1000.0f;
  lastMotorTick = now;
  deg += MOTOR_DEG_PER_S_FULL * curSpeed / 255.0f * dt;  // dead reckoning
  if (mode == HOMING) {
    if (now - homeStart > HOME_TRY_MS) {
      if (++homeTries >= 2) { stopMotor(); homed = false; }  // UNO Q silent or magnet missing: stay put
      else { homeDir = -homeDir; homeStart = now; targetSpeed = HOME_SPEED * homeDir; }
    }
  } else if (mode != IDLE) {
    if (segI < segN && now - segStart >= segs[segI].ms) { segI++; segStart = now; }
    if (segI >= segN) {
      Mode done = mode;
      targetSpeed = 0;
      mode = IDLE;
      if (done == GESTURE) home();  // after every gesture sequence, so drift doesn't build up
    } else {
      targetSpeed = segs[segI].speed;
    }
  }
  int step = max(1, (int)(255.0f * dt * 1000.0f / MOTOR_RAMP_MS));  // ramp, never jump
  if (curSpeed < targetSpeed) curSpeed = min(targetSpeed, curSpeed + step);
  else if (curSpeed > targetSpeed) curSpeed = max(targetSpeed, curSpeed - step);
  if (curSpeed == 0 && targetSpeed == 0) io.motorBrake();
  else io.motorSpeed(curSpeed);
  deg = constrain(deg, -PAN_LIMIT_DEG, PAN_LIMIT_DEG);
  if (now >= nextPan) {
    nextPan = now + (moving() ? PAN_PUBLISH_MOVING_MS : PAN_PUBLISH_IDLE_MS);
    JsonDocument p;
    p["deg"] = roundf(deg * 10) / 10;
    p["homed"] = homed;
    p["moving"] = moving();
    publish("raw.head.pan", "raw", "head/pan", p);
  }
}

// ---------------------------------------------------------------- button (lid)
bool btnStable = false, btnLast = false;
uint32_t btnChangedAt = 0;

void buttonTick(uint32_t now) {
  bool raw = io.buttonDown();
  if (raw != btnLast) { btnLast = raw; btnChangedAt = now; }
  if (raw != btnStable && now - btnChangedAt >= BUTTON_DEBOUNCE_MS) {
    btnStable = raw;
    JsonDocument p;
    p["id"] = "head";
    p["pressed"] = btnStable;
    publish("raw.head.button", "raw", "head/button", p);
  }
}

// ---------------------------------------------------------------- knob (left ear) -> raw.head.ear
int32_t knobOrigin = 0;
int dialValue = KNOB_START_VALUE;
bool knobStable = false, knobLast = false;
uint32_t knobChangedAt = 0;

void publishEar(int delta, bool pressed) {
  JsonDocument p;
  p["value"] = dialValue;
  p["delta"] = delta;
  p["pressed"] = pressed;
  publish("raw.head.ear", "raw", "head/ear", p);
}

void knobTick(uint32_t now) {
  int32_t steps = (io.knobPosition() - knobOrigin) / KNOB_COUNTS_PER_STEP;
  if (steps != 0) {
    int nv = constrain(dialValue + (int)steps, 1, 5);
    knobOrigin += steps * KNOB_COUNTS_PER_STEP;          // turning past 1 or 5 just stays there
    if (nv != dialValue) { int d = nv - dialValue; dialValue = nv; publishEar(d, false); }
  }
  bool raw = io.knobDown();
  if (raw != knobLast) { knobLast = raw; knobChangedAt = now; }
  if (raw != knobStable && now - knobChangedAt >= KNOB_PRESS_DEBOUNCE_MS) {
    knobStable = raw;
    if (raw) publishEar(0, true);                        // a press answers the current question
  }
}

// ---------------------------------------------------------------- eyes (Color Display) + chest (LED grids)
String eyes = "neutral", chest = "off";
float lookX = 0, lookY = 0, bpm = 6;
uint32_t ledRgb = LED_DEFAULT_RGB, nextBlink = 0, blinkUntil = 0, nextLed = 0;
bool eyesDirty = true, blinking = false;

void drawEye(int cx, int cy, bool blink) {
  int w = EYE_W, h = EYE_H;
  uint16_t col = EYE_COLOR;
  if (blink) { io.displayRect(cx - w / 2, cy - 2, w, 4, col); return; }
  if (eyes == "wide") { w += 4; h += 10; }
  else if (eyes == "listening") { h += 4; }
  else if (eyes == "soft") { w -= 4; h -= 6; col = EYE_SOFT_COLOR; }
  else if (eyes == "thinking") { cy -= 10; }
  if (eyes == "sleepy") { io.displayRect(cx - w / 2, cy + 4, w, h / 4, col); return; }
  io.displayRect(cx - w / 2 + 3, cy - h / 2, w - 6, h, col);   // rounded-ish: two overlapping rects
  io.displayRect(cx - w / 2, cy - h / 2 + 3, w, h - 6, col);
  if (eyes == "happy") io.displayRect(cx - w / 2, cy, w, h / 2 + 1, EYE_BG);  // ^ : cut the bottom half
}

void eyesTick(uint32_t now) {
  bool breathing = chest == "breathe";
  if (!breathing && now >= nextBlink && !blinking) { blinking = true; blinkUntil = now + BLINK_MS; eyesDirty = true; }
  if (blinking && now >= blinkUntil) {
    blinking = false;
    nextBlink = now + random(BLINK_MIN_MS, BLINK_MAX_MS);
    eyesDirty = true;
  }
  if (!eyesDirty) return;                              // the TFT is slow: redraw only on change
  eyesDirty = false;
  io.displayFill(EYE_BG);
  int cx = DISPLAY_W / 2 + (int)(lookX * EYE_LOOK_PX), cy = DISPLAY_H / 2 + (int)(lookY * EYE_LOOK_PX / 3);
  drawEye(cx - EYE_GAP / 2, cy, blinking);
  drawEye(cx + EYE_GAP / 2, cy, blinking);
  io.knobRing(eyes == "listening");                    // the ear lights while a question is open
}

void ledTick(uint32_t now) {
  if (now < nextLed) return;
  nextLed = now + LED_FRAME_MS;
  float b = 0, period = 60000.0f / max(1.0f, bpm), ph = fmodf((float)now, period) / period;
  if (chest == "breathe") b = LED_MAX_BRIGHT * (0.5f - 0.5f * cosf(ph * 2 * PI));  // bright on the in-breath
  else if (chest == "glow") b = LED_GLOW_BRIGHT;
  else if (chest == "pulse") b = ph < 0.15f ? LED_MAX_BRIGHT : LED_GLOW_BRIGHT * 0.4f;
  io.ledsFill((uint8_t)(((ledRgb >> 16) & 0xFF) * b), (uint8_t)(((ledRgb >> 8) & 0xFF) * b),
              (uint8_t)((ledRgb & 0xFF) * b));
}

// ---------------------------------------------------------------- commands
void onMessage(char* topic, uint8_t* data, unsigned int len) {
  JsonDocument env;
  if (deserializeJson(env, data, len)) return;
  const char* type = env["type"] | "";
  if (!strcmp(type, "health") && !strcmp(env["source"] | "", "hub")) {
    hubSilent = !strcmp(env["payload"]["status"] | "", "down");
    if (!hubSilent) lastHubSeen = millis();
    return;
  }
  if (!strcmp(type, "raw.sensors.hall")) { onHall(env["payload"]["at_home"] | false); return; }
  if (strcmp(type, "cmd.head")) return;
  JsonObject c = env["payload"];
  // Face + chest work without a hub check (no motion); motor and speaker need a live hub.
  if (c["eyes"].is<const char*>()) { eyes = (const char*)c["eyes"]; eyesDirty = true; }
  if (c["look"].is<JsonObject>()) { lookX = c["look"]["x"] | 0.0f; lookY = c["look"]["y"] | 0.0f; eyesDirty = true; }
  if (c["chest"].is<const char*>()) chest = (const char*)c["chest"];
  if (c["bpm"].is<float>()) bpm = c["bpm"];
  if (c["color"].is<const char*>()) ledRgb = strtoul(((const char*)c["color"]) + 1, nullptr, 16);
  if (hubSilent) return;  // never move without a live hub
  bool busy = mode == GESTURE || mode == HOMING;       // ignore new moves mid-gesture / homing
  if (c["home"] | false) { if (!busy) home(); }
  else if (c["gesture"].is<const char*>()) { if (!busy) gesture(c["gesture"]); }
  else if (c["pan"].is<JsonObject>()) { if (!busy) goTo(c["pan"]["target_deg"] | 0.0f, c["pan"]["speed"] | 0.5f); }
  if (!strcmp(c["pan_mode"] | "", "still") && !busy) stopMotor();
  if (c["purr"].is<JsonObject>() && !moving()) io.tone(PURR_HZ, c["purr"]["ms"] | 500, PURR_VOLUME);
}

// ---------------------------------------------------------------- network
void publishHealth(const char* status) {
  JsonDocument p;
  p["status"] = status;
  p["version"] = KAIKU_FW_VERSION;
  p["uptime_s"] = (millis() - bootMs) / 1000.0;
  JsonObject d = p["details"].to<JsonObject>();
  d["rssi"] = WiFi.RSSI();
  d["homed"] = homed;
  d["at_home"] = atHome;
  d["hub_silent"] = hubSilent;
  d["reconnects"] = reconnects;
  publish("health", "health", "head", p, true);
}

void netTick(uint32_t now) {
  if (now < nextNetTry) return;
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    nextNetTry = now + backoff;
    backoff = min<uint32_t>(backoff * 2, BACKOFF_MAX_MS);
    return;
  }
  if (mqtt.connected()) return;
  IPAddress ip;
  const char* host = MQTT_HOST;
  if (MDNS.begin("kaiku-head")) {
    String h = String(MQTT_HOST);
    h.replace(".local", "");
    ip = MDNS.queryHost(h);
  }
  if (ip == IPAddress()) ip.fromString(MQTT_HOST_IP);  // mDNS often blocked on venue Wi-Fi
  mqtt.setServer(ip, MQTT_PORT_DEFAULT);
  // Last will: retained health/head "down" (same as the Python Bus). Built without a timestamp check.
  static char will[256];
  char id[37], ts[32];
  uint64_t ms = timeOk() ? nowMsUtc() : 1700000000000ULL;
  uuid7(ms, id);
  isoTs(ms, ts, sizeof(ts));
  snprintf(will, sizeof(will),
           "{\"v\":1,\"id\":\"%s\",\"ts\":\"%s\",\"home_id\":\"%s\",\"source\":\"head\",\"type\":\"health\","
           "\"payload\":{\"status\":\"down\",\"version\":\"%s\",\"uptime_s\":0},\"sim\":false}",
           id, ts, KAIKU_HOME_ID, KAIKU_FW_VERSION);
  const char* user = strlen(MQTT_USER) ? MQTT_USER : nullptr;
  const char* pass = strlen(MQTT_PASS) ? MQTT_PASS : nullptr;
  char cid[24];
  snprintf(cid, sizeof(cid), "kaiku-head-%04x", (unsigned)(esp_random() & 0xFFFF));
  if (mqtt.connect(cid, user, pass, topicFor("health", "head"), 1, true, will)) {
    mqtt.subscribe(topicFor("cmd", "head"), 1);
    mqtt.subscribe(topicFor("health", "hub"), 1);
    if (HAS_HALL) mqtt.subscribe(topicFor("raw", "sensors/hall"), 0);
    backoff = BACKOFF_MIN_MS;
    reconnects++;
    publishHealth("ok");
  } else {
    nextNetTry = now + backoff;
    backoff = min<uint32_t>(backoff * 2, BACKOFF_MAX_MS);
  }
  (void)host;
}

}  // namespace

void begin(const HeadIO& headIo) {
  io = headIo;
  bootMs = millis();
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  configTime(0, 0, NTP_SERVER);  // envelope ts is UTC
  mqtt.setBufferSize(1024);
  mqtt.setKeepAlive(15);
  mqtt.setCallback(onMessage);
  lastMotorTick = millis();
  knobOrigin = io.knobPosition();
  nextBlink = millis() + BLINK_MIN_MS;
  randomSeed(esp_random());
}

void tick() {
  uint32_t now = millis();
  netTick(now);
  mqtt.loop();
  if (!hubSilent && bootHomePending) { bootHomePending = false; home(); }  // first live hub: find the front
  if (!hubSilent && now - lastHubSeen > HUB_SILENCE_STOP_MS) {  // safety: hub gone -> stop everything
    hubSilent = true;
    stopMotor();
    io.speakerStop();
  }
  if (!mqtt.connected()) stopMotor();                  // homing needs the hall messages too
  buttonTick(now);
  knobTick(now);
  motorTick(now);
  eyesTick(now);
  ledTick(now);
  if (now >= nextHealth) { nextHealth = now + HEALTH_EVERY_MS; publishHealth(hubSilent ? "degraded" : "ok"); }
}

}  // namespace kaiku
