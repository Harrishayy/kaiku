// Bench: KY-039 heartbeat alone, read through the KY-053 (ADS1115, 0x48) on the header SDA/SCL bus (Wire).
// Wiring: KY-039 S -> KY-053 A0; KY-053 SDA/SCL -> UNO Q SDA/SCL; all + -> 3V3, - -> GND.
// Samples at 100 Hz; once a second prints rate, signal range and a beat-detected pulse (bpm 0 = no steady beat).
#include <Arduino_RouterBridge.h>
#include <Wire.h>
#define ADS 0x48
#define FS 100
#define MIN_IBI_MS 273   // 220 bpm
#define MAX_IBI_MS 2000  // 30 bpm
uint32_t nextUs, winStart, lastBeat = 0;
long n = 0, lo = 40000, hi = -40000;
float slow = -99999, fast = 0, amp = 0, prevD = 0;
uint32_t ibi[5]; int nIbi = 0;  // last inter-beat intervals, newest first

// bpm from the last 4 intervals if they agree within 25 % and sit in 30..220 bpm, else 0 (noise is not a pulse)
float steadyBpm(uint32_t now) {
  if (nIbi < 4 || now - lastBeat > MAX_IBI_MS) return 0;
  uint32_t v[4]; for (int i = 0; i < 4; i++) v[i] = ibi[i];
  for (int i = 0; i < 4; i++) for (int j = i + 1; j < 4; j++) if (v[j] < v[i]) { uint32_t t = v[i]; v[i] = v[j]; v[j] = t; }
  float med = (v[1] + v[2]) / 2.0f;
  if (v[0] < med * 0.75f || v[3] > med * 1.25f) return 0;
  float bpm = 60000.0f / med;
  return (bpm >= 30 && bpm <= 220) ? bpm : 0;
}

int16_t adsRead() {
  Wire.beginTransmission(ADS); Wire.write(0x00); Wire.endTransmission();
  Wire.requestFrom(ADS, 2);
  if (Wire.available() < 2) return 0;
  return (int16_t)((Wire.read() << 8) | Wire.read());
}

void setup() {
  Bridge.begin();
  Monitor.begin();
  delay(3000);  // let the monitor attach before the first line
  Wire.begin();
  for (int a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) Monitor.println(String("{\"event\":\"i2c\",\"addr\":") + a + "}");
  }
  Wire.beginTransmission(ADS);              // AIN0, +-4.096 V, continuous, 250 SPS
  Wire.write(0x01); Wire.write(0x42); Wire.write(0xA3);
  bool ok = Wire.endTransmission() == 0;
  Monitor.println(String("{\"event\":\"ads\",\"ok\":") + (ok ? 1 : 0) + "}");
  nextUs = micros();
  winStart = millis();
}

void loop() {
  if ((int32_t)(micros() - nextUs) < 0) return;
  nextUs += 1000000UL / FS;
  int v = adsRead();
  uint32_t now = millis();
  if (slow < -9999) { slow = v; fast = v; }
  slow = slow * 0.99f + v * 0.01f;                      // baseline (~1 s)
  fast = fast * 0.75f + v * 0.25f;                      // light smoothing (ADC + flicker noise)
  float d = fast - slow;
  amp = max(fabsf(d), amp * 0.995f);                    // recent swing, decays over ~2 s
  if (prevD < 0.5f * amp && d >= 0.5f * amp && amp > 3 && now - lastBeat >= MIN_IBI_MS) {   // rising edge = beat
    if (lastBeat && now - lastBeat <= MAX_IBI_MS) {
      for (int i = 4; i > 0; i--) ibi[i] = ibi[i - 1];
      ibi[0] = now - lastBeat; if (nIbi < 5) nIbi++;
    } else nIbi = 0;
    lastBeat = now;
  }
  prevD = d;
  lo = min(lo, (long)v); hi = max(hi, (long)v); n++;
  if (now - winStart >= 1000) {
    float secs = (now - winStart) / 1000.0f;
    Monitor.println(String("{\"event\":\"batch\",\"fs_hz\":") + n / secs + ",\"min\":" + lo + ",\"max\":" + hi +
                    ",\"range\":" + (hi - lo) + ",\"bpm\":" + steadyBpm(now) + "}");
    n = 0; lo = 40000; hi = -40000; winStart = now;
  }
}
