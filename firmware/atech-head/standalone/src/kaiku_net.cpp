// kaiku_net implementation. Envelope, connect and last will follow ../../kaiku_link/kaiku_link.cpp, which ran on this
// board (bench 2026-11-14); contracts: contracts/python/kaiku_contracts/envelope.py + payloads.py.
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

const char* FW_VERSION = "atech-head-standalone-0.1.0";
const uint16_t MQTT_PORT = 1883;
const uint32_t BACKOFF_MIN_MS = 1000, BACKOFF_MAX_MS = 10000, HEALTH_EVERY_MS = 5000, PAN_EVERY_MS = 2000;

WiFiClient net;
PubSubClient mqtt(net);
char topicBuf[96];
uint32_t bootMs = 0, nextNetTry = 0, backoff = BACKOFF_MIN_MS, nextHealth = 0, nextPan = 0, reconnects = 0;
volatile uint32_t taps = 0;
bool face = false, isMoving = false;
char motorPinCheck[24] = "";
const char* stepName = "idle";

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
  static char buf[512];
  size_t n = serializeJson(env, buf, sizeof(buf));
  return mqtt.publish(topicFor(kind, name), (const uint8_t*)buf, n, retain);
}

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
  if (c["eyes"].is<const char*>()) push("eyes", c["eyes"]);   // neutral/soft/... fall back to calm
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
  JsonDocument env;
  if (deserializeJson(env, data, len)) return;
  const char* type = env["type"] | "";
  if (!strcmp(env["source"] | "", "head")) return;                     // our own messages
  if (!strcmp(type, "raw.head.tap")) taps++;                           // UNO Q knock sensor
  else if (!strcmp(type, "raw.hub.face")) face = true;                 // UNO Q camera
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
    mqtt.subscribe(topicFor("raw", "head/tap"), 0);
    mqtt.subscribe(topicFor("raw", "hub/face"), 0);
    backoff = BACKOFF_MIN_MS;
    reconnects++;
    publishHealth("ok");
  } else {
    nextNetTry = now + backoff;
    backoff = min<uint32_t>(backoff * 2, BACKOFF_MAX_MS);
  }
}

}  // namespace

void begin() {
  bootMs = millis();
  WiFi.mode(WIFI_STA);
  configTime(0, 0, "pool.ntp.org");   // envelope ts is UTC
  mqtt.setBufferSize(1024);
  mqtt.setKeepAlive(15);
  mqtt.setCallback(onMessage);
}

void tick() {
  netTick(millis());
  mqtt.loop();
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

uint32_t takeTaps() { uint32_t n = taps; taps = 0; return n; }

bool takeFace() { bool f = face; face = false; return f; }

void step(const char* name) { stepName = name; }

void ear(int value, int delta, bool pressed) {
  JsonDocument p;
  p["value"] = value;
  p["delta"] = delta;
  p["pressed"] = pressed;
  publish("raw.head.ear", "raw", "head/ear", p);
}

void motorPins(const char* result) { strlcpy(motorPinCheck, result, sizeof(motorPinCheck)); }

void moving(bool m) {
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

}  // namespace kaiku_net
