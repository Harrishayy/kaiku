# The Atech board in Kaiku

> Part of [the stack pages](INDEX.md). Read from the code on 15 November 2026. Module doc:
> [`firmware/atech-head/AGENTS.md`](../../firmware/atech-head/AGENTS.md); wiring and parts:
> [`hardware/`](../../hardware/AGENTS.md). The robot changed a great deal in 48 hours; this page describes the
> head **as built now** (decisions D44, D51, D54 to D59 and D66 in [`decisions.md`](../decisions.md)).

**In one paragraph.** The robot's head is one Atech 14-port board (ESP32-S3) with five modules: a knob that is
its ear, an orientation sensor that feels taps, a motor that turns its neck, a speaker and a microphone. It runs
a three-minute check-in by itself with no laptop: turn the ear for mood, energy and sleep, breathe, then drum on
its head. On the home network it also becomes the body of a Gemini Live conversation: Kaiku's voice comes out of
its speaker as audio frames over MQTT, and what the person did with their hands becomes observations in the
record a practitioner reads.

## What is on the board

| Atech module | Port | What it is on the robot |
|---|---|---|
| `rotary_encoder` (knob with ring light) | 5-6 | The ear dial: turn for an answer from 1 to 10, press to confirm. The ring is orange at rest and blue while the microphone streams |
| `icm40608` (orientation sensor) | 13 | Feels taps on the head; the only tap source |
| `dc_motor` | 14 | The neck: turns the head left and right |
| `speaker` (I2S amplifier) | 1-2 | Kaiku's voice, the drum song, tones |
| `microphone` (I2S) | 9-10 | Streams to the hub while a conversation is open |

Source: [`standalone/project.yaml`](../../firmware/atech-head/standalone/project.yaml) and
[`standalone/src/pins.h`](../../firmware/atech-head/standalone/src/pins.h).

## How we use the Atech platform

- **SDK and CLI.** `atech==1.0.0a12`: `atech validate`, `atech build`, `atech upload`, `atech monitor`. A
  `project.yaml` declares the modules and the platform fetches their drivers.
- **Language.** C++ on the Arduino framework for the ESP32-S3.
- **Where the code came from.** The first standalone `main.cpp` was produced by the Atech website's agent
  (D44). Everything marked `// kaiku_net` or `// kaiku:` in it, the network layer
  [`kaiku_net.cpp`](../../firmware/atech-head/standalone/src/kaiku_net.cpp) and the audio layer
  [`kaiku_link/head_audio.cpp`](../../firmware/atech-head/kaiku_link/head_audio.cpp) are hand-written.
  [`standalone/build.sh`](../../firmware/atech-head/standalone/build.sh) lays our sources over the generated
  project.
- **One bench per part.** Ten small programs under [`bench/`](../../firmware/atech-head/bench/) (button,
  display, knob, LEDs, motor, speaker, microphone and more), each with a pass rule checked by
  [`tools/bench.py`](../../tools/bench.py), so a part is proven alone before it joins the robot.
- **Things we learned on the board** and wrote down for the next team:
  the ESP32 platform has to be pinned (`espressif32@6.9.0`), since a newer one breaks the motor driver;
  `motor.stop()` is the brake; driver debug prints stall the loop when nothing is reading USB, so the build
  mutes them; port 11 shares a pin with the serial receiver, so a motor there turned one way only.
- **Not used at runtime:** Atech's cloud gateway. By the module's own rule the head speaks MQTT on the home network only;
  the gateway is for flashing and debugging.

Firmware version: `atech-head-standalone-0.9.0`. There is a second, older firmware in the same folder in which
the hub drives every step (`atech-head-0.4.0`, `make atech-mqtt`); it still builds but assumes a display and has
no orientation-sensor taps, so it is not what the robot runs (D44).

## What each part does

### The ear dial

In a dial step the head keeps a value from 1 to 10, starting at 5. Every turn is published as
`raw.head.ear {value, delta}`; a press confirms. With no display she cannot see the number, so Kaiku's spoken
line gives a direction ("clockwise for lighter"). The hub turns the confirmed answer into
`obs.self_report` for mood, energy or sleep. She can also just say the answer: the voice's `record_dial` tool
records it and the hub moves the head on (D59).

### Taps from the orientation sensor (D55)

A separate knock switch was replaced by the board's own orientation sensor: one part and three wires fewer, and
it gives force.

- A tap is the total acceleration leaving rest by more than 0.15 g.
- At most one tap per 120 ms.
- No taps while the neck motor runs or for 400 ms after, and none while the speaker plays or for 150 ms after,
  so the head never counts its own movement or voice as her drumming.
- Each tap is published with a time and a force: `raw.head.tap {t_ms, force, src: "imu"}`.

On the hub, `TapAnalyzer` ([`perception/taps.py`](../../hub/kaiku_hub/perception/taps.py)) turns four or more
taps into a drum session: tempo from the median interval, regularity as one minus the variation of the
intervals, mean force, and a quality figure.

### Tap it back, with Lyria

The drum step can be a rhythm game (D51). The hub holds the head's drum step open, a short song from Lyria
RealTime plays through the head's speaker at a set tempo (three levels: 100, 126 and 76 beats a minute), she
taps it back, and the words are "perfect", "great", "nice" or "not quite", never a score. The result
(`obs.tap_back`) is recorded and deliberately read by no rule: it is a game, not a test.

### The neck

The motor is open loop: a command is a direction and a pulse length. The hub nudges the head toward her when the
camera sees her face near the edge of the picture, at most every two seconds, and stops for a minute if three
nudges did not bring the face nearer the middle. The voice can also turn it (`turn_head`).

One rule came from the power supply: **the motor never runs while the speaker sounds.** A turn asked for during
speech waits.

### Voice through the head (D51)

The head and the hub are one body in two boxes. The hub holds the Gemini Live conversation; the head is its
mouth and ears.

- **Format.** Raw 16-bit mono at 16 kHz, one MQTT message every 20 ms (640 bytes), on `audio/head/speaker` and
  `audio/head/mic`. Not stored, not logged, not uplinked.
- **Speaker.** Frames go into a one-second ring buffer; a dedicated task starts playing once 300 ms is buffered
  (it stuttered at 120 ms on a phone hotspot), with a soft limiter. The hub is the clock, and Kaiku's voice
  pre-empts music by sending an empty frame that clears the buffer.
- **Microphone.** Kept only while the hub holds it open, renewed every two seconds; the head closes it by itself
  after ten seconds of silence from the hub. Nothing is kept while the speaker sounds, so there is no talking
  over Kaiku on the robot: an ear press interrupts instead.
- **A stand-in microphone (D56).** A phone or Mac beside the robot
  can also send the same frames (`audio/phone/mic`), behind its own switch and only while the hub holds the
  microphone open.

### A press opens a talk (D66)

A press of the ear at the greeting opens a conversation, not the check-in. The check-in starts when she asks or
agrees, and can be paused and resumed (`cmd.head {ritual: start | pause | resume}`). An activity is asked twice
(D58): the voice's tool call only arms the head for 20 seconds, and her own press starts it. A model never
starts something on her body by itself.

## On the network

- **Messages.** The head builds the project's standard envelope in C++ (UUIDv7 id, UTC time from NTP) and
  publishes `raw.head.ear`, `raw.head.tap`, `raw.head.pan` and a retained `health/head` every five seconds with
  its step, firmware, signal strength and audio counters. It listens for `cmd.head`.
- **Board to board.** The head subscribes to the [UNO Q](arduino-uno-q.md)'s face messages, so a face wakes it
  with no hub in between, and it asks the UNO Q's buzzer for its chimes.
- **Fail soft.** No Wi-Fi or no broker: the ritual runs exactly the same by knob. Reconnect with backoff from 1
  to 10 seconds; a last-will message marks the head as down; the microphone and the drum hold lapse by
  themselves if the hub goes quiet.
- **Follow mode.** While the head runs its own ritual, the hub does not compete with it: it shadows the head's
  steps from its health messages ([`hub/kaiku_hub/follow.py`](../../hub/kaiku_hub/follow.py)) and writes the
  record. A dial answer it cannot attribute to a confirmed step is dropped, never guessed.

## From a tap to the practitioner's page

1. The head publishes raw events; the hub derives observations: `obs.self_report`, `obs.drum_session`,
   `obs.ritual`, `obs.tap_back`.
2. The hub queues them durably and uploads only `obs.*` to the cloud on [Modal](modal.md).
3. The deterministic rule compares mood, energy, sleep, drum tempo, force, duration and regularity with her own
   usual ([`config/criteria.toml`](../../config/criteria.toml)).
4. [Gemma](gemma.md)'s review can cite those records; the phone's History shows her drum tempo over a month.
5. [Gemini Live](gemini.md) speaks through the head and moves the check-in with tool calls.

## What has run on the real board

| When | What was seen |
|---|---|
| 14 Nov | Standalone firmware flashed; the full ritual by hand (greeting, three dials, breathing, drum), then again on external power with no laptop |
| 14 Nov | Head and UNO Q on one broker over a phone hotspot; a face seen by the UNO Q woke the head |
| 14 Nov | Motor commands over MQTT turned the neck both ways on port 14 |
| 14 Nov | 47 taps in 50 seconds from a hand on the head (0.15 to 0.73 g), and the head woke from idle |
| 15 Nov | Firmware 0.5.0: a press opened a Gemini Live conversation; Tap it back played; the ritual completed |
| 15 Nov | With a phone as the microphone, Kaiku asked about the camera through the head's speaker and her spoken yes arrived as a tool call 8 s after the session opened |
| 15 Nov | Head on the broker as firmware 0.9.0 |

## Is this the best we could have done?

**Why a board like this fits.** A person whose energy is lowest will not open an app, but may turn a knob on
something that turned to look at them. Atech's snap-in modules let us change the robot's body three times in two
days (display out, knock switch out, orientation sensor in) without redesigning anything, and the same board
that reads a knob can carry a live voice.

**Choices we would defend.** A head that works with no network at all. A hub that shadows the head, not one that
fights it for control. Audio as plain frames on the home network, never through a cloud gateway. A physical
press, not a model, starting anything on her body.

## How it joins the rest

One contract ([`contracts/`](../../contracts/AGENTS.md)) is why this board, the UNO Q, the phone and the glasses
can all feed one record. The head has a software twin ([`sim/nodes/head_sim.py`](../../sim/nodes/head_sim.py))
that speaks the same messages, so the hub, the cloud and the voice were built and tested before the hardware
was ready, and can be run by anyone without it (`make sim`, `make hub`).
