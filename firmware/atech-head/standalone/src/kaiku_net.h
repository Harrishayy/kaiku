// kaiku_net: Wi-Fi + MQTT for the standalone head (D44), so the ritual on the Atech talks to the UNO Q and the hub
// through the contracts. Same envelope, topics, backoff, NTP and last will as ../../kaiku_link (the MQTT firmware).
//   emits    health/head (retained every 5 s and at once on every step change, LWT down) ·
//            raw.head.ear {value, delta, pressed} (dial + presses) ·
//            raw.head.pan {deg 0, homed, moving} (on change + every 2 s; one `moving` for a whole sway) ·
//            raw.head.tap {t_ms, force, src: imu} (a tap felt by the head's orientation sensor) ·
//            cmd.sensors {chime} (wake on greet, start_drum / end_drum around drumming: the UNO Q buzzer) ·
//            audio/head/mic (binary PCM frames, only while the hub holds the microphone open; ../../kaiku_link/head_audio.h)
//   consumes raw.hub.face (wakes Kaiku) ·
//            cmd.head eyes · pan{target_deg, speed} · gesture · purr{ms} -> the same actions as the USB-serial commands ·
//            cmd.head drum: hold | end (the hub runs the drum step: tap it back) · pan_mode: sway + bpm (only while
//            held) · mic: open | close · show: help | none (this head has NO display: see takeHelp) ·
//            audio/head/speaker (binary PCM frames: the hub's song, cues and voice on the head's own speaker)
// Never blocks on audio: frames go into a ring here and a task plays them. No Wi-Fi or broker just means nothing is
// sent; the ritual runs the same.
// Secrets come from ../../kaiku_link/secrets.h (gitignored; build.sh copies it into the build).
#pragma once
#include <Arduino.h>
#include "head_audio.h"   // HeadAudioIO (build.sh copies ../../kaiku_link/head_audio.* next to this file)
#include "transport.h"    // P2PCommand

namespace kaiku_net {
void begin(const HeadAudioIO& audio);          // Wi-Fi + MQTT + the speaker / microphone streams
void tick();                                   // every loop(); returns at once
bool nextCommand(P2PCommand* out);             // cmd.head, mapped to "eyes" / "pan" / "purr" actions
void tap(float force_g);                       // raw.head.tap: a tap felt by the orientation sensor (peak g above rest)
bool takeFace();                               // a face was seen since the last call (never while calm(), below)
void step(const char* name);                   // ritual step, shown in health details (sent at once)
void ear(int value, int delta, bool pressed);  // raw.head.ear
void report(char* out, size_t n);              // serial `net`: Wi-Fi/MQTT state + a scan for our network (blocks ~3 s)
void motorPins(const char* result);            // boot check of the motor lines, shown in health details
void moving(bool m);                           // raw.head.pan (sent on change)
void chime(const char* name);                  // cmd.sensors {chime} to the UNO Q

// --- the hub leads the drum step (tap it back) and the voice
bool drumHeld();       // cmd.head {drum: hold} is fresh (10 s): stay in the drum step, no timer of our own, no tap tones
bool drumByHub();      // the hub held this drum step at some point: the head has no drum summary of its own
bool takeDrumEnd();    // cmd.head {drum: end} arrived while in the drum step
int drumTapsFelt();    // taps the orientation sensor felt in this drum step
int sway();            // motor speed -100..100 for the hub's sway on the beat (0 = none); call every loop
bool speakerBusy();    // the hub's song, cue or voice is on the speaker (or was 150 ms ago): no tones of our own
                       // over it, no taps and no wake-on-sound from it (the speaker shakes the sensor and the microphone)
bool micOpen();        // the microphone is streaming to the hub: the head shows it (ear ring)

// --- cmd.head {show: help | none} (the hub's crisis path). This head has no display, so nothing can be shown:
// health says `help_shown: false` and `help_screen: "none"`. What the head still does: the ritual ends quietly, the
// microphone shuts, the motor stands still, and the head stays calm.
bool takeHelp();       // a {show: help} arrived: end whatever runs, quietly, and go to idle (true once per message)
bool calm();           // after {show: help}, until {show: none}, an ear press that starts a new ritual (any step but
                       // idle) or 10 minutes: a face, a sound or a pat does not wake Kaiku, and it obeys no pan,
                       // gesture, purr or sway
}  // namespace kaiku_net
