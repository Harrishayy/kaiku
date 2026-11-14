// Bench: KY-054 light sensor alone (phototransistor) under the lid window. Wiring: S -> A0, + -> 3V3, - -> GND.
#include <Arduino_RouterBridge.h>
#define PIN A0

void setup() {
  Bridge.begin();
  Monitor.begin();
  analogReadResolution(14);
}

void loop() {
  Monitor.println(String("{\"event\":\"light\",\"raw\":") + analogRead(PIN) + ",\"t_ms\":" + millis() + "}");
  delay(500);
}
