// Bench: KY-031 knock sensor alone. Wiring: S -> D2, + -> 3V3, - -> GND (hardware/wiring.md).
// Prints one JSON object per line on the serial monitor (Monitor = Arduino_RouterBridge).
// The spring touches for well under a millisecond, so edges are caught by an interrupt, not by polling.
#include <Arduino_RouterBridge.h>
#define PIN 2
#define DEBOUNCE_MS 40
volatile uint32_t edges = 0;      // every edge the ISR saw (raw, includes bounce)
volatile uint32_t lastEdgeMs = 0;
int idle = HIGH;
uint32_t last = 0, n = 0, seenEdges = 0, nextStatus = 0;

void onEdge() {
  edges++;
  lastEdgeMs = millis();
}

void setup() {
  Bridge.begin();
  Monitor.begin();
  pinMode(PIN, INPUT_PULLUP);
  delay(3000);  // let the serial monitor attach; keep the sensor still from here
  uint32_t t0 = millis(), highs = 0, k = 0;
  while (millis() - t0 < 500) { highs += digitalRead(PIN); k++; delay(1); }
  idle = (highs * 2 >= k) ? HIGH : LOW;
  attachInterrupt(digitalPinToInterrupt(PIN), onEdge, CHANGE);
  Monitor.println(String("{\"event\":\"boot\",\"idle_level\":") + idle + ",\"high_ratio\":" + (float)highs / k + "}");
}

void loop() {
  noInterrupts();
  uint32_t e = edges, t = lastEdgeMs;
  interrupts();
  if (e != seenEdges) {             // new edges since we last looked = one burst of spring contact
    seenEdges = e;
    if (t - last >= DEBOUNCE_MS) {  // bounce inside one tap counts once
      last = t;
      n++;
      Monitor.println(String("{\"event\":\"knock\",\"t_ms\":") + t + ",\"n\":" + n + "}");
    }
  }
  if (millis() >= nextStatus) {     // diagnostic: raw level and edge count, twice a second
    nextStatus = millis() + 500;
    Monitor.println(String("{\"event\":\"status\",\"level\":") + digitalRead(PIN) + ",\"edges\":" + e + "}");
  }
  delay(1);
}
