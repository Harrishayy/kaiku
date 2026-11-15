# The Arduino UNO Q in Kaiku

> Part of [the stack pages](INDEX.md). Read from the code on 15 November 2026. Module doc:
> [`firmware/unoq-sensors/AGENTS.md`](../../firmware/unoq-sensors/AGENTS.md).

**In one paragraph.** The UNO Q is the robot's eyes. It is two computers on one board, and we use both: the
Linux side runs a Python app that reads a USB camera and turns every frame into a few numbers on the board
itself (is a face there, where, how far, how bright is the room), and the microcontroller side runs a sketch
that plays the robot's chimes. Only numbers leave the board; no picture is stored or sent by the product. Those
numbers wake the robot when someone comes near, turn its head toward them, and give the record a "first hello"
time each day.

## Two halves, one app

| Half | Runs | Code |
|---|---|---|
| **Linux** (Arduino App Lab app) | A Python node: camera, face detection, MQTT | [`python/main.py`](../../firmware/unoq-sensors/python/main.py), [`python/kaiku_unoq/`](../../firmware/unoq-sensors/python/kaiku_unoq/) |
| **Microcontroller** (STM32, Arduino core on Zephyr) | A sketch: Modulino buzzer patterns, a status icon on the LED matrix | [`sketch/sketch.ino`](../../firmware/unoq-sensors/sketch/sketch.ino) |

- **The Bridge.** The halves talk over Arduino's RPC bridge (`Arduino_RouterBridge` in the sketch,
  `arduino.app_utils.Bridge` in Python). Python calls `buzz_pattern`, `status_set` and `ping`; the sketch
  announces `mcu_ready`.
- **Threads.** App Lab owns the main thread; our asyncio node runs beside it, and camera and Bridge callbacks
  hop onto its loop.
- **MQTT.** The node uses the project's shared `Bus` and message contract, copied onto the board by
  `make unoq-app`, so the UNO Q validates its own messages against the same models as every other node.
- **At boot.** It is set as the board's default app and starts by itself; it came back by itself after a
  reboot on 14 Nov.

We do not use App Lab's ready-made AI bricks. Face detection is OpenCV's Haar cascade from the app container's
own OpenCV: small, fast enough at five checks a second, and nothing to download.

## The camera pipeline, all on the board

Source: [`camera.py`](../../firmware/unoq-sensors/python/kaiku_unoq/camera.py) and
[`vision.py`](../../firmware/unoq-sensors/python/kaiku_unoq/vision.py). Capture is 640 × 480 at 15 frames a
second from a USB camera; its own microphone is never opened.

| What | How | Message |
|---|---|---|
| **Face** | Haar frontal-face cascade, five times a second | `raw.hub.face {x_norm, y_norm, size}`: where the face is in the picture and how wide |
| **Distance** | A pinhole estimate from the face's width (`d = k / size`) | `raw.sensors.distance {cm}` |
| **Room light** | Every 10 s: lock the exposure, drop three frames, take the mean brightness of one | `raw.sensors.light` |
| **Pulse** (when asked, during breathing) | Mean green value of a forehead patch per frame, one batch a second | `raw.sensors.ppg`, marked quality 0.6 |
| **Face signs** (a few seconds, after her yes) | Per-frame numbers only: share of frames with a smile, head movement | `raw.sensors.face_signs` |

Each frame is deleted in the same loop pass that read it. A missing or unplugged camera is retried with
backoff and reported as `camera_ok: false`; it does not stop the node.

**Honest about each number.**

- Distance and light are uncalibrated. They are useful only because Kaiku compares a person with their own
  usual, not with a standard.
- Pulse from a camera at 15 frames a second can give at most a heart rate. The hub refuses to compute
  beat-to-beat variability from it, and emits nothing unless the signal passes its quality gate
  ([`hub/kaiku_hub/perception/hrv.py`](../../hub/kaiku_hub/perception/hrv.py)). No reading from a real face
  that passed the gate has been recorded yet.
- Face signs are counts of movement, shown and not scored. Nothing names an emotion. This part was written on
  15 Nov and has not run on the board.

## The camera is hers to switch (D61)

`cmd.sensors {camera_enable: false}` closes the camera device, so its own light goes out. While the robot's head
runs its own ritual the hub keeps the camera closed unless she said yes **in this conversation**: Kaiku asks
once, in a fixed line, and waits; no answer means off; a yes sounds the buzzer's `ok`. The hub repeats the
current choice when it sees the board's heartbeat (at most every 20 seconds), so a restarted board is told again.

The cost is real and accepted: with the camera closed there is no face wake, distance, light or head following.

## The buzzer

A Modulino Buzzer on the Qwiic connector plays five short patterns without blocking the sketch: `wake`, `ok`,
`start_drum`, `end_drum` and `alert` (device faults only). The [Atech head](atech.md) asks for the chimes over
MQTT, so the two boards make one robot's sounds.

## What we took off, and why

| Part | Why it is gone |
|---|---|
| Knock switch (KY-031) | The Atech head's orientation sensor feels taps and gives force: one part and three wires fewer (D55). It passed its bench 5 of 5 before it was removed |
| Finger pulse sensor (KY-039) and its converter (KY-053) | On the bench it found no heartbeat in room light, only a flicker artefact of about 117 a minute against a watch reading 44 (D39). We removed it and did not report a number we did not believe |
| Hall sensor (KY-035) | No magnet to home against |
| Light sensor (KY-054), ultrasonic distance | The camera gives both |

## What the numbers are used for

- **Waking the robot.** The Atech head listens for face messages directly, so the robot turns its attention to
  someone with no hub in between, at most once in ten minutes.
- **Turning toward her.** The hub nudges the neck when her face nears the edge of the picture.
- **First hello.** The hub's presence tracker confirms someone within about 80 cm for a second and emits
  `obs.presence`; the first arrival of a new day feeds the `getup` measure in
  [`config/criteria.toml`](../../config/criteria.toml), compared with her own usual.
- **Room light.** An hourly mean feeds the `light` measure at half weight.

## Messages and failing softly

The node publishes a heartbeat on `health/sensors` every five seconds with `camera_ok`, `mcu_ok` and the
sketch's version. Every Bridge call is wrapped, so a dead sketch shows as `mcu_ok: false`. The board rejoins the
network by itself.

## What has run on the real board

| When | What was seen |
|---|---|
| 14 Nov | Benches: buzzer pass, camera pass (opens, faces, distance, light, pulse batches); the sketch compiles at 16 % of flash |
| 14 Nov | The app running with camera and sketch healthy; faces, distance, room light and chimes on the broker; working together with the Atech head |
| 14 Nov | On a phone hotspot; restarted by itself after a reboot |
| 15 Nov | The current app and sketch deployed over ssh and started |

## Is this the best we could have done?

**Why the UNO Q fits.** A camera in someone's home is only acceptable if the picture never leaves the room. A
board with a Linux side strong enough to run vision next to the camera, and a microcontroller for the things
that must be instant, is exactly that. It also means the robot's first reaction needs no hub process: the face
wake goes from one board to the other through the broker.

## How it joins the rest

The UNO Q and the [Atech head](atech.md) are two nodes on one broker with one message contract; the hub turns
their raw events into observations for the [Modal](modal.md) cloud; the camera opens only after a yes spoken to
[Gemini Live](gemini.md). Like every hardware node it has a software twin
([`sim/nodes/sensors_sim.py`](../../sim/nodes/sensors_sim.py)) that speaks the same messages.
