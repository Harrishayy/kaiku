// kaiku_net implementation. Envelope, connect and last will follow ../../kaiku_link/kaiku_link.cpp, which ran on this
// board (bench 2026-11-14); contracts: contracts/python/kaiku_contracts/envelope.py + payloads.py.
// The audio streams (speaker ring + task, microphone gate) are ../../kaiku_link/head_audio.*; this file only moves
// their frames between MQTT and that module, and never waits for audio.
#include "kaiku_net.h"

#include <ArduinoJson.h>
#include <ESPmDNS.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <esp_random.h>
#include <sys/time.h>
#include <time.h>

#include "secrets.h"   // WIFI_SSID, WIFI_PASS, MQTT_HOST, MQTT_HOST_IP, MQTT_USER, MQTT_PASS, KAIKU_HOME_ID

namespace kaiku_net {
namespace {

const char* FW_VERSION = "atech-head-standalone-0.8.0";   // 0.1.0 = without the sound streams and the drum hold
const uint16_t MQTT_PORT = 1883;
const uint32_t BACKOFF_MIN_MS = 1000, BACKOFF_MAX_MS = 10000, HEALTH_EVERY_MS = 5000, PAN_EVERY_MS = 2000;

// --- the hub leads the drum step (cmd.head drum: hold | end)
const uint32_t DRUM_HOLD_MS = 10000;       // the hub re-sends hold every 3 s; this long without one = our own timer again
// --- no taps, tones or wake-on-sound while PCM plays and this long after (the speaker shakes the orientation sensor
// and fills the microphone). The motor mute (400 ms) and the 120 ms between taps are main.cpp's own.
const uint32_t TAP_AFTER_SOUND_MS = 150;
// --- sway on the beat (cmd.head pan_mode: sway + bpm, only while the drum step is held). Open loop: equal pushes
// left and right around where the head stood, a half push first and last. NOT run on the robot: tune here.
const int SWAY_SPEED_PCT = 45;             // of full speed (the purr uses about 43)
const uint32_t SWAY_PULSE_MS = 160;        // one push a beat, at most 40 % of the beat
// --- after cmd.head {show: help}: how long the head stays calm by itself (the MQTT firmware's help screen stays as long)
const uint32_t CALM_MS = 600000;

WiFiClient net;
PubSubClient mqtt(net);
char topicBuf[96], spkTopic[112], micTopic[112];
uint8_t micBuf[head_audio::FRAME_BYTES];
uint32_t bootMs = 0, nextNetTry = 0, backoff = BACKOFF_MIN_MS, nextHealth = 0, nextPan = 0, reconnects = 0;
uint32_t lastTick = 0, loopMaxMs = 0;      // longest gap between two tick() calls since the last health message
bool face = false, isMoving = false;
char motorPinCheck[24] = "";
const char* stepName = "idle";

bool inDrum = false, held = false, hubDrum = false, drumEnd = false;
uint32_t heldAt = 0;
int drumTaps = 0;
bool calmOn = false, helpNew = false;      // calm after {show: help}; a {show: help} has not been acted on yet
uint32_t calmAt = 0;
struct {
  bool want;
  float bpm;
  uint32_t nextBeat, pulseEnd, pulseMs;
  int cur, pos;   // cur: speed being driven now; pos: half pushes away from where the sway began
} sw = {false, 100.0f, 0, 0, SWAY_PULSE_MS, 0, 0};

const int QN = 6;                 // small queue of cmd.head actions
P2PCommand q[QN];
int qHead = 0, qLen = 0;

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

// {v,id,ts,home_id,source:"head",type,payload,sim:false} around `payload`. Dropped until NTP gives UTC.
bool publish(const char* type, const char* kind, const char* name, JsonDocument& payload, bool retain = false) {
  if (!mqtt.connected() || !timeOk()) return false;
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
  static char buf[768];               // health with the audio counters is about 560 bytes (the MQTT buffer is 1024)
  size_t n = serializeJson(env, buf, sizeof(buf));
  return mqtt.publish(topicFor(kind, name), (const uint8_t*)buf, n, retain);
}

bool swaying() { return (sw.want && held) || sw.cur != 0 || sw.pos != 0; }

void publishHealth(const char* status) {
  JsonDocument p;
  p["status"] = status;
  p["version"] = FW_VERSION;
  p["uptime_s"] = (millis() - bootMs) / 1000.0;
  JsonObject d = p["details"].to<JsonObject>();
  d["rssi"] = WiFi.RSSI();
  d["reconnects"] = reconnects;
  d["step"] = stepName;
  d["firmware"] = "standalone";
  if (motorPinCheck[0]) d["motor_pins"] = motorPinCheck;
  d["drum_held"] = held;
  d["help_shown"] = false;            // this head has no display: it can never show the helpline lines
  d["help_screen"] = "none";          // ... and says so, so the hub knows why
  d["calm"] = calm();                 // quiet after {show: help}: nothing but an ear press wakes it
  d["loop_max_ms"] = loopMaxMs;       // > 100 here means the main loop stalled: audio frames then arrive in bursts
  loopMaxMs = 0;
  head_audio::Stats s = head_audio::stats();
  JsonObject a = d["audio"].to<JsonObject>();   // counters since boot (head_audio.h)
  a["rx"] = s.spkFrames;
  a["drop"] = s.spkDropped;
  a["dry"] = s.spkDry;
  a["mic_open"] = head_audio::micOpen();
  a["mic_tx"] = s.micFrames;
  a["mic_drop"] = s.micDropped;
  a["mic_peak"] = s.micPeak;
  publish("health", "health", "head", p, true);
}

void publishPan() {
  JsonDocument p;
  p["deg"] = 0;          // no position estimate in the standalone firmware
  p["homed"] = true;
  p["moving"] = isMoving;
  publish("raw.head.pan", "raw", "head/pan", p);
}

void push(const char* action, const char* value) {
  if (qLen == QN) return;  // full: drop (commands are best-effort)
  P2PCommand& c = q[(qHead + qLen++) % QN];
  strlcpy(c.action, action, sizeof(c.action));
  strlcpy(c.value, value, sizeof(c.value));
  c.truncated = false;
}

void onCmdHead(JsonObject c) {
  char v[16];
  // drum first: the hub sends {drum: hold, eyes, pan_mode, bpm} in ONE message, and sway only runs while held
  const char* drum = c["drum"] | "";
  if (!strcmp(drum, "hold")) {
    if (inDrum) { held = true; hubDrum = true; heldAt = millis(); }   // outside the drum step a hold means nothing
  } else if (!strcmp(drum, "end")) {
    held = false;
    sw.want = false;
    if (inDrum) drumEnd = true;
  }
  const char* mic = c["mic"] | "";
  if (!strcmp(mic, "open")) head_audio::micHold(true);
  else if (!strcmp(mic, "close")) head_audio::micHold(false);
  // The hub's crisis path. Needs no hold and no live hub (the hub sending it may be going down). No display here, so
  // nothing is shown; the main loop ends the ritual quietly (takeHelp). Here: motor still, microphone shut, calm.
  const char* show = c["show"] | "";
  if (!strcmp(show, "help")) {
    calmOn = helpNew = true;
    calmAt = millis();
    held = drumEnd = false;           // a {drum: end} in the same message is dropped: no end chime, no done step
    sw.want = false;
    sw.cur = sw.pos = 0;              // no push back to the middle either: the head stands still
    head_audio::micHold(false);
    nextHealth = 0;
  } else if (!strcmp(show, "none") && calmOn) {
    calmOn = false;
    nextHealth = 0;
  }
  const char* pm = c["pan_mode"] | "";
  if (!strcmp(pm, "sway")) {
    if (!sw.want) sw.nextBeat = millis();
    sw.want = true;
  } else if (pm[0]) {
    sw.want = false;   // still, track
  }
  if (c["bpm"].is<float>()) sw.bpm = c["bpm"];
  if (c["eyes"].is<const char*>()) push("eyes", c["eyes"]);   // no display: accepted, nothing to see
  if (calmOn) { sw.want = false; return; }   // calm after {show: help}: the head does not move or purr
  // asking twice (D58): she asked Kaiku for an activity in words; the next press of the ear starts it (main.cpp)
  const char* act = c["activity"] | "";
  if (!strcmp(act, "drum") || !strcmp(act, "breathe") || !strcmp(act, "none")) push("arm", act);
  // she answered in words (next) or asked to stop (end): the hub moves the head's own ritual (main.cpp)
  const char* rit = c["ritual"] | "";
  if (!strcmp(rit, "next")) push("said", "next");
  else if (!strcmp(rit, "end")) push("said", "end");
  if (c["color"].is<const char*>()) push("ring", c["color"]);   // the ear ring's colour, as she asked for it
  if (c["pan"].is<JsonObject>()) {
    float t = c["pan"]["target_deg"] | 0.0f, s = c["pan"]["speed"] | 0.5f;
    snprintf(v, sizeof(v), "%d", (int)((t >= 0 ? 1 : -1) * constrain(s, 0.0f, 1.0f) * 100));
    push("pan", v);
  }
  const char* g = c["gesture"] | "";
  if (!strcmp(g, "look_left")) push("pan", "-60");
  else if (!strcmp(g, "look_right")) push("pan", "60");
  else if (!strcmp(g, "shake")) push("purr", "600");
  if (c["purr"].is<JsonObject>()) { snprintf(v, sizeof(v), "%d", (int)(c["purr"]["ms"] | 500)); push("purr", v); }
}

void onMessage(char* topic, uint8_t* data, unsigned int len) {
  if (!strcmp(topic, spkTopic)) {   // binary PCM, never an envelope: straight into the speaker ring (0 bytes = drop)
    head_audio::speakerPush(data, len);
    return;
  }
  JsonDocument env;
  if (deserializeJson(env, data, len)) return;
  const char* type = env["type"] | "";
  if (!strcmp(env["source"] | "", "head")) return;                     // our own messages
  if (!strcmp(type, "raw.hub.face")) face = true;                 // UNO Q camera
  else if (!strcmp(type, "cmd.head")) onCmdHead(env["payload"].as<JsonObject>());
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
  if (MDNS.begin("kaiku-head")) {
    String h = String(MQTT_HOST);
    h.replace(".local", "");
    ip = MDNS.queryHost(h);
  }
  if (ip == IPAddress()) ip.fromString(MQTT_HOST_IP);  // mDNS is often blocked on venue Wi-Fi
  mqtt.setServer(ip, MQTT_PORT);
  static char will[256];                                // retained health/head "down" (same as the Python Bus)
  char id[37], ts[32];
  uint64_t ms = timeOk() ? nowMsUtc() : 1700000000000ULL;
  uuid7(ms, id);
  isoTs(ms, ts, sizeof(ts));
  snprintf(will, sizeof(will),
           "{\"v\":1,\"id\":\"%s\",\"ts\":\"%s\",\"home_id\":\"%s\",\"source\":\"head\",\"type\":\"health\","
           "\"payload\":{\"status\":\"down\",\"version\":\"%s\",\"uptime_s\":0},\"sim\":false}",
           id, ts, KAIKU_HOME_ID, FW_VERSION);
  const char* user = strlen(MQTT_USER) ? MQTT_USER : nullptr;
  const char* pass = strlen(MQTT_PASS) ? MQTT_PASS : nullptr;
  char cid[24];
  snprintf(cid, sizeof(cid), "kaiku-head-%04x", (unsigned)(esp_random() & 0xFFFF));
  if (mqtt.connect(cid, user, pass, topicFor("health", "head"), 1, true, will)) {
    mqtt.subscribe(topicFor("cmd", "head"), 1);
    mqtt.subscribe(topicFor("raw", "hub/face"), 0);
    mqtt.subscribe(spkTopic, 0);
    net.setNoDelay(true);             // microphone frames leave one by one, not held back for the last one's ACK
    backoff = BACKOFF_MIN_MS;
    reconnects++;
    publishHealth("ok");
  } else {
    nextNetTry = now + backoff;
    backoff = min<uint32_t>(backoff * 2, BACKOFF_MAX_MS);
  }
}

}  // namespace

void begin(const HeadAudioIO& audio) {
  bootMs = millis();
  snprintf(spkTopic, sizeof(spkTopic), "kaiku/v1/%s/audio/head/speaker", KAIKU_HOME_ID);
  snprintf(micTopic, sizeof(micTopic), "kaiku/v1/%s/audio/head/mic", KAIKU_HOME_ID);
  head_audio::begin(audio);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);               // modem sleep holds incoming packets until the next beacon (100 ms and more):
                                      // 50 audio frames a second need the radio awake
  configTime(0, 0, "pool.ntp.org");   // envelope ts is UTC
  mqtt.setBufferSize(1024);           // one audio message = 640 bytes + its topic; PubSubClient's default is 256
  mqtt.setKeepAlive(15);
  mqtt.setCallback(onMessage);
}

void tick() {
  uint32_t t0 = millis();
  if (lastTick && t0 - lastTick > loopMaxMs) loopMaxMs = t0 - lastTick;
  lastTick = t0;
  netTick(t0);
  mqtt.loop();                        // PubSubClient handles ONE message a call:
  for (int i = 0; i < 3 && net.available(); i++) mqtt.loop();   // after a slow pass take up to 4 in a row
  if (!mqtt.connected()) {
    head_audio::micHold(false);       // no broker, no hub holding the microphone
  } else {
    for (int i = 0; i < 4 && head_audio::micFrame(micBuf); i++)   // only ever true while the hub holds it open
      mqtt.publish(micTopic, micBuf, head_audio::FRAME_BYTES, false);
  }
  uint32_t now = millis();            // after mqtt.loop(), never before (unsigned wrap, bench 2026-11-14)
  if (now >= nextHealth) { nextHealth = now + HEALTH_EVERY_MS; publishHealth("ok"); }
  if (now >= nextPan) { nextPan = now + PAN_EVERY_MS; publishPan(); }
}

bool nextCommand(P2PCommand* out) {
  if (!qLen) return false;
  *out = q[qHead];
  qHead = (qHead + 1) % QN;
  qLen--;
  return true;
}

void tap(float force_g) {
  if (inDrum) drumTaps++;
  JsonDocument p;
  p["t_ms"] = (uint32_t)(millis() - bootMs);
  p["force"] = roundf(max(force_g, 0.0f) * 100) / 100.0f;
  p["src"] = "imu";
  publish("raw.head.tap", "raw", "head/tap", p);
}

bool takeFace() { bool f = face; face = false; return f && !calmOn; }

void step(const char* name) {
  stepName = name;
  inDrum = !strcmp(name, "drum");
  held = hubDrum = drumEnd = false;   // a hold belongs to one drum step
  if (strcmp(name, "idle")) calmOn = false;   // the person started a new ritual: the calm after {show: help} is over
  sw.want = false;
  drumTaps = 0;
  nextHealth = 0;                     // say the new step at the next tick, not at the next 5 s heartbeat
}

void ear(int value, int delta, bool pressed) {
  JsonDocument p;
  p["value"] = value;
  p["delta"] = delta;
  p["pressed"] = pressed;
  publish("raw.head.ear", "raw", "head/ear", p);
}

// Why is the head offline? Status codes: wifi 3 = connected, 1 = network not found, 4 = connect failed (password),
// 6 = disconnected; mqtt 0 = connected, -2 = broker unreachable. The scan says whether our network is in range and
// on which channel (the ESP32 only hears 2.4 GHz, channels 1-13). Never prints the password.
void report(char* out, size_t n) {
  int st = WiFi.status(), ms = mqtt.state();
  String ip = WiFi.localIP().toString();
  long rssi = st == WL_CONNECTED ? WiFi.RSSI() : 0;
  int seen = -1, ch = 0, sr = 0, auth = -1, best = -127;
  int count = 0;
  if (st != WL_CONNECTED) {
    WiFi.disconnect();
    delay(200);
    count = WiFi.scanNetworks();
    for (int i = 0; i < count; i++) {
      if (WiFi.RSSI(i) > best) best = WiFi.RSSI(i);
      if (WiFi.SSID(i) == WIFI_SSID) { seen = 1; ch = WiFi.channel(i); sr = WiFi.RSSI(i); auth = (int)WiFi.encryptionType(i); }
    }
    if (seen < 0 && count >= 0) seen = 0;
    WiFi.scanDelete();
    nextNetTry = 0;
    backoff = BACKOFF_MAX_MS;   // give the next join the full window
  }
  snprintf(out, n, "{\"wifi\":%d,\"mqtt\":%d,\"ip\":\"%s\",\"rssi\":%ld,\"ssid_len\":%d,\"scan_count\":%d,\"best_rssi\":%d,"
           "\"ours_seen\":%d,\"ours_channel\":%d,\"ours_rssi\":%d,\"ours_auth\":%d,\"broker\":\"%s\"}",
           st, ms, ip.c_str(), rssi, (int)strlen(WIFI_SSID), count, best, seen, ch, sr, auth, MQTT_HOST_IP);
}

void motorPins(const char* result) { strlcpy(motorPinCheck, result, sizeof(motorPinCheck)); }

void moving(bool m) {
  m = m || swaying();                 // one "moving" for the whole sway, not one message a beat
  if (m == isMoving) return;
  isMoving = m;
  publishPan();
  nextPan = millis() + PAN_EVERY_MS;
}

void chime(const char* name) {
  JsonDocument p;
  p["chime"] = name;
  publish("cmd.sensors", "cmd", "sensors", p);
}

bool drumHeld() {
  if (held && millis() - heldAt >= DRUM_HOLD_MS) {    // a silent hub never strands the head
    held = false;
    sw.want = false;
    nextHealth = 0;
  }
  return held;
}

bool drumByHub() { return hubDrum; }

bool takeDrumEnd() { bool e = drumEnd; drumEnd = false; return e; }

int drumTapsFelt() { return drumTaps; }

int sway() {
  uint32_t now = millis();
  bool on = sw.want && drumHeld();
  if (sw.cur && (int32_t)(now - sw.pulseEnd) >= 0) sw.cur = 0;
  if (!sw.cur) {
    if (on && (int32_t)(now - sw.nextBeat) >= 0) {
      uint32_t beat = (uint32_t)(60000.0f / constrain(sw.bpm, 40.0f, 200.0f));
      sw.pulseMs = min<uint32_t>(SWAY_PULSE_MS, beat * 2 / 5);
      bool half = sw.pos == 0;                        // the first push goes half way, so the sway stays centred
      int dir = sw.pos > 0 ? -1 : 1;
      sw.cur = dir * SWAY_SPEED_PCT;
      sw.pulseEnd = now + (half ? sw.pulseMs / 2 : sw.pulseMs);
      sw.pos += dir * (half ? 1 : 2);
      sw.nextBeat = now + beat;
    } else if (!on && sw.pos != 0) {                  // over: half a push back to where it began
      sw.cur = (sw.pos > 0 ? -1 : 1) * SWAY_SPEED_PCT;
      sw.pulseEnd = now + sw.pulseMs / 2;
      sw.pos = 0;
    }
  }
  return sw.cur;
}

bool speakerBusy() { return head_audio::speakerBusy() || head_audio::speakerQuietMs() < TAP_AFTER_SOUND_MS; }

bool micOpen() { return head_audio::micOpen(); }

bool takeHelp() { bool h = helpNew; helpNew = false; return h; }

bool calm() {
  if (calmOn && millis() - calmAt >= CALM_MS) {
    calmOn = false;
    nextHealth = 0;
  }
  return calmOn;
}

}  // namespace kaiku_net
