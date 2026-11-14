// Bench: KY-031 knock sensor alone. Wiring: S -> D2, + -> 3V3, - -> GND (hardware/wiring.md).
// Prints one JSON object per line on the App Lab serial monitor (Monitor = Arduino_RouterBridge; VERIFY).
#include <Arduino_RouterBridge.h>
#define PIN 2
#define DEBOUNCE_MS 40
int idle = HIGH;
uint32_t last = 0, n = 0;
int prev;

void setup() {
  Bridge.begin();
  Monitor.begin();
  pinMode(PIN, INPUT_PULLUP);
  uint32_t t0 = millis(), highs = 0, k = 0;
  while (millis() - t0 < 500) { highs += digitalRead(PIN); k++; delay(1); }
  idle = (highs * 2 >= k) ? HIGH : LOW;
  prev = idle;
  Monitor.println(String("{\"event\":\"boot\",\"idle_level\":") + idle + ",\"high_ratio\":" + (float)highs / k + "}");
}

void loop() {  // polled at ~1 kHz: no interrupt needed for the bench
  int v = digitalRead(PIN);
  uint32_t now = millis();
  if (v != prev) {
    prev = v;
    if (v != idle && now - last >= DEBOUNCE_MS) {
      last = now;
      n++;
      Monitor.println(String("{\"event\":\"knock\",\"t_ms\":") + now + ",\"n\":" + n + "}");
    }
  }
  delay(1);
}
