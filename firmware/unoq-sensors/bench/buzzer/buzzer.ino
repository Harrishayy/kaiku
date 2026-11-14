// Bench: Modulino Buzzer alone on the Qwiic connector (Wire1, 0x1E 7-bit = 0x3C 8-bit). Scans the bus, then plays every chime.
#include <Arduino_RouterBridge.h>
#include <Arduino_Modulino.h>
#include <Wire.h>
ModulinoBuzzer buzzer;
struct Note { int hz, ms; };
const char* names[] = {"wake", "ok", "start_drum", "end_drum", "alert"};
const Note pats[][4] = {{{660, 80}, {880, 120}}, {{1320, 60}}, {{880, 60}, {0, 60}, {880, 60}},
                        {{1320, 80}, {990, 80}, {660, 120}}, {{440, 300}, {0, 150}, {440, 300}}};
const int lens[] = {2, 1, 3, 3, 3};

void setup() {
  Bridge.begin();
  Monitor.begin();
  delay(3000);  // let App Lab's monitor attach before the first line
  Wire1.begin();
  for (int a = 1; a < 127; a++) {
    Wire1.beginTransmission(a);
    if (Wire1.endTransmission() == 0) Monitor.println(String("{\"event\":\"i2c\",\"addr\":") + a + "}");
  }
  Modulino.begin(Wire1);  // VERIFY: begin(TwoWire&) on Arduino_Modulino >= 0.6.1
  bool ok = buzzer.begin();
  Monitor.println(String("{\"event\":\"buzzer\",\"ok\":") + (ok ? 1 : 0) + "}");
  for (int p = 0; p < 5; p++) {
    Monitor.println(String("{\"event\":\"chime\",\"name\":\"") + names[p] + "\"}");
    for (int i = 0; i < lens[p]; i++) {
      if (pats[p][i].hz) buzzer.tone(pats[p][i].hz, pats[p][i].ms);
      delay(pats[p][i].ms);  // bench only: real sketch waits with millis()
    }
    delay(800);
  }
  Monitor.println("{\"event\":\"done\"}");
}

void loop() {}
