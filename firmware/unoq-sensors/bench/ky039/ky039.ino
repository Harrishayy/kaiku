// Bench: KY-039 heartbeat alone, read through the KY-053 (ADS1115, 0x48) on the header SDA/SCL bus (Wire).
// Wiring: KY-039 S -> KY-053 A0; KY-053 SDA/SCL -> UNO Q SDA/SCL; all + -> 3V3, - -> GND.
// Samples at 100 Hz; once a second prints rate, signal range and a rough pulse estimate.
#include <Arduino_RouterBridge.h>
#include <Wire.h>
#define ADS 0x48
#define FS 100
uint32_t nextUs, winStart;
long n = 0, lo = 40000, hi = -40000, crossings = 0;
float mean = -99999, prevDev = 0;

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
  mean = mean < -9999 ? v : mean * 0.98f + v * 0.02f;   // slow baseline
  float dev = v - mean;
  if (prevDev < 0 && dev >= 0) crossings++;             // one upward crossing per beat (rough)
  prevDev = dev;
  lo = min(lo, (long)v); hi = max(hi, (long)v); n++;
  uint32_t now = millis();
  if (now - winStart >= 1000) {
    float secs = (now - winStart) / 1000.0f;
    Monitor.println(String("{\"event\":\"batch\",\"fs_hz\":") + n / secs + ",\"min\":" + lo + ",\"max\":" + hi +
                    ",\"range\":" + (hi - lo) + ",\"bpm_rough\":" + crossings * 60.0f / secs + "}");
    n = 0; lo = 40000; hi = -40000; crossings = 0; winStart = now;
  }
}
