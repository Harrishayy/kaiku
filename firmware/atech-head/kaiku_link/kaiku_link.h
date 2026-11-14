// kaiku_link: the Atech board's Wi-Fi + MQTT link and behaviour (custom Atech module, plain C++).
//
// All Atech module calls go through HeadIO, filled in by ../project.yaml with the generated instances, so this file
// never guesses an Atech API. Contract: same topics and envelope as sim/nodes/head_sim.py:
//   emits    raw/head/ear {value 1-5, delta, pressed} (Knob) · raw/head/button {id:"head", pressed} (lid button) ·
//            raw/head/pan {deg (estimated), homed, moving} · health/head (retained, LWT down) ·
//            audio/head/mic (binary PCM frames, only while the hub holds the microphone open; head_audio.h)
//   consumes cmd/head eyes · look{x,y} · chest off|breathe|glow|pulse · bpm · color · pan{target_deg,speed} · home ·
//            gesture look_left|look_right|shake · purr{ms} · pan_mode still · mic open|close ·
//            show help|none (the helpline numbers instead of the eyes; honoured without a live hub)
//            audio/head/speaker (binary PCM frames: the hub's song, cues and voice on the head's speaker; head_audio.h)
//            raw/sensors/hall {at_home} (KY-035 on the UNO Q: brake there while homing)
//            health/hub (watchdog: stop motor + speaker after HUB_SILENCE_STOP_MS)
//   ignores  pan_mode sway|track (tracking arrives as pan targets; no sway with the knock drum) · drum hold|end
//            (that is for the standalone head: here the hub runs every step anyway)
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
  // Audio streams (head_audio.h). Null = this build has no PCM speaker path / no microphone path.
  void (*pcmWrite)(const int16_t* samples, int count, float volume) = nullptr;   // blocking, mono 16 kHz; called from
                                                                                 // the audio task, never the loop
  bool (*toneBusy)() = nullptr;                           // the tone driver is sounding
  void (*micTap)(void (*cb)(const int16_t* samples, int count, void* ctx), void* ctx) = nullptr;   // gap-free capture
  // Text on the eyes display, top-left at x, y, in the driver's built-in font (6 x 8 pixels a character at size 1).
  // Only the help screen uses it (help_screen.h). Null = this build cannot show the helpline lines.
  void (*displayText)(const char* text, int16_t x, int16_t y, uint8_t size, uint16_t rgb565) = nullptr;
};

namespace kaiku {
void begin(const HeadIO& io);
void tick();  // call from loop(); never blocks
}  // namespace kaiku
