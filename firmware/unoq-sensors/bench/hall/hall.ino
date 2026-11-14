// Bench: KY-035 hall sensor alone (49E linear). Wiring: out -> A1, + -> 3V3, - -> GND (hardware/wiring.md).
// Prints the no-magnet mid value at boot, then edges when the turntable magnet passes. Copy `mid` into HALL_MID.
#include <Arduino_RouterBridge.h>
#define PIN A1
#define DELTA 600
int mid = 8192;
bool home = false;
uint32_t edges = 0, nextReport = 0;

void setup() {
  Bridge.begin();
  Monitor.begin();
  analogReadResolution(14);
  delay(3000);  // let the monitor attach before the first line
  long sum = 0;
  for (int i = 0; i < 200; i++) { sum += analogRead(PIN); delay(2); }   // magnet away from the sensor
  mid = sum / 200;
  Monitor.println(String("{\"event\":\"boot\",\"mid\":") + mid + "}");
}

void loop() {
  int v = analogRead(PIN), d = abs(v - mid);
  bool h = home ? d > DELTA - 150 : d > DELTA;
  if (h != home) {
    home = h;
    if (h) edges++;
    Monitor.println(String("{\"event\":\"hall\",\"at_home\":") + (h ? 1 : 0) + ",\"delta\":" + d + ",\"n\":" + edges + "}");
  }
  if (millis() >= nextReport) { nextReport = millis() + 1000; Monitor.println(String("{\"event\":\"level\",\"delta\":") + d + "}"); }
  delay(5);
}
