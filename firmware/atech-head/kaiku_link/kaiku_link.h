// kaiku_link: the Atech board's Wi-Fi + MQTT link and behaviour (custom Atech module, plain C++).
//
// All Atech module calls go through HeadIO, filled in by ../project.yaml with the generated instances, so this file
// never guesses an Atech API. Contract: same topics and envelope as sim/nodes/head_sim.py:
//   emits    raw/head/ear {value 1-5, delta, pressed} (Knob) · raw/head/button {id:"head", pressed} (lid button) ·
//            raw/head/pan {deg (estimated), homed, moving} · health/head (retained, LWT down)
//   consumes cmd/head eyes · look{x,y} · chest off|breathe|glow|pulse · bpm · color · pan{target_deg,speed} · home ·
//            gesture look_left|look_right|shake · purr{ms} · pan_mode still
//            raw/sensors/hall {at_home} (KY-035 on the UNO Q: brake there while homing)
//            health/hub (watchdog: stop motor + speaker after HUB_SILENCE_STOP_MS)
//   ignores  pan_mode sway|track (tracking arrives as pan targets; no sway with the knock drum)
#pragma once

#include <Arduino.h>

struct HeadIO {
  bool (*buttonDown)();                                   // lid button raw level (true = pressed)
  int32_t (*knobPosition)();                              // encoder counts (any origin)
  bool (*knobDown)();                                     // knob push switch
  void (*knobRing)(bool on);                              // ring light while a dial question is open
  void (*displayFill)(uint16_t rgb565);
  void (*displayRect)(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t rgb565);
  void (*ledsFill)(uint8_t r, uint8_t g, uint8_t b);      // both chest grids
  void (*motorSpeed)(int speed);                          // -255..255, sign = direction
  void (*motorBrake)();
  void (*tone)(uint16_t hz, uint16_t ms, float volume);   // must be non-blocking
  void (*speakerStop)();
};

namespace kaiku {
void begin(const HeadIO& io);
void tick();  // call from loop(); never blocks
}  // namespace kaiku
