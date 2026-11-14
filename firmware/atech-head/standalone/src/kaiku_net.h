// kaiku_net: Wi-Fi + MQTT for the standalone head (D44), so the ritual on the Atech talks to the UNO Q and the hub
// through the contracts. Same envelope, topics, backoff, NTP and last will as ../../kaiku_link (the MQTT firmware).
//   emits    health/head (retained every 5 s, LWT down) · raw.head.ear {value, delta, pressed} (dial + presses) ·
//            raw.head.pan {deg 0, homed, moving} (on change + every 2 s; the UNO Q ignores knocks while moving) ·
//            cmd.sensors {chime} (wake on greet, start_drum / end_drum around drumming: the UNO Q buzzer)
//   consumes raw.head.tap from the UNO Q knock sensor (drum taps, wakes Kaiku) · raw.hub.face (wakes Kaiku) ·
//            cmd.head eyes · pan{target_deg, speed} · gesture · purr{ms} -> the same actions as the USB-serial commands
// Never blocks: no Wi-Fi or broker just means nothing is sent; the ritual runs the same.
// Secrets come from ../../kaiku_link/secrets.h (gitignored; build.sh copies it into the build).
#pragma once
#include <Arduino.h>
#include "transport.h"   // P2PCommand

namespace kaiku_net {
void begin();
void tick();                                   // every loop(); returns at once
bool nextCommand(P2PCommand* out);             // cmd.head, mapped to "eyes" / "pan" / "purr" actions
uint32_t takeTaps();                           // UNO Q knocks since the last call
bool takeFace();                               // a face was seen since the last call
void step(const char* name);                   // ritual step, shown in health details
void ear(int value, int delta, bool pressed);  // raw.head.ear
void report(char* out, size_t n);              // serial `net`: Wi-Fi/MQTT state + a scan for our network (blocks ~3 s)
void motorPins(const char* result);            // boot check of the motor lines, shown in health details
void moving(bool m);                           // raw.head.pan (sent on change)
void chime(const char* name);                  // cmd.sensors {chime} to the UNO Q
}  // namespace kaiku_net
