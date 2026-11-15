# firmware/atech-head — AGENTS.md

> Read the root `AGENTS.md` first. Owner A · kind firmware · reference behaviour: `sim/nodes/head_sim.py` ·
> build plan: `docs/plans/07-robot-electronics.md` · decisions D31 (hardware), D32 (software).

## Purpose
**Active firmware right now: `standalone/` (D44)**: the ritual runs on the head, `src/kaiku_net.*` adds Wi-Fi + MQTT,
and the hub follows it. Its messages are listed in `standalone/src/kaiku_net.h`. Unless a line says "standalone",
the sections below describe the MQTT/contract firmware in this folder (`kaiku_link/`), which still builds
(`make atech-mqtt`) but is **not for the robot as it stands** (D54, D55): it assumes the display on ports 3-4 and
the motor on port 13, and has no orientation-sensor code, so it sends no taps.

**The robot as it stands (2026-11-14 evening):** no display, no LED grids, taps only from the head's orientation
sensor, motor on port 14, on a phone hotspot with the broker and the hub on a laptop. The standalone firmware is
Edwin's (seen working on the robot: Wi-Fi, health, pans both ways, taps, a face waking it) **with the sound work
put back on top of it** (version `atech-head-standalone-0.4.0`; his alone is `0.1.0`): the hub's songs, cues and
Kaiku's voice on the head's own speaker, the head's microphone to the hub while a conversation holds it open, and
the hub leading the drum step ("tap it back"). See "Audio streams" and "Standalone on top of the robot firmware"
below. **On the board 2026-11-15: speaker works (operator report); microphone streams but returns zeros
(measured below).** No computer's speaker or microphone is in the path.

**Help screen:** only the MQTT firmware has one (compiled, never seen on a display). The standalone head has no
display: on `cmd.head {show: "help"}` it shows nothing and says so in its health. See "Help screen" below.

The robot's face, ears and movement on the Atech 14-port board (ESP32-S3). The board sits in the body, and the head
modules are cabled up the neck. It drives the Color Display eyes, the Knob ear dial, the lid Button, two chest LED
grids, the pan motor (open loop, homed on the KY-035 hall edge) and the Speaker (purr tone and cues). The Mic is
fitted but unused in v1. Custom firmware speaks MQTT on the LAN. **Never** Atech's cloud gateway or
`atech.Board.connect()` at runtime; those are for flashing and debugging only.

## Boundaries
Only messages from `contracts/` (envelope built in C++ to match `kaiku_contracts/envelope.py`). Behaviour lives in
the custom module `kaiku_link/` (plain C++). The Atech module C++ API is touched only in `project.yaml` files
(through `HeadIO`), so a wrong method name is a one-line fix.

## Consumes (topics/endpoints)
`cmd/head`: `eyes` · `look{x,y}` · `chest: off|breathe|glow|pulse` + `bpm` + `color` · `pan{target_deg, speed}` ·
`home` · `gesture: look_left|look_right|shake` · `purr{ms}` · `pan_mode: still` · `mic: open|close` ·
**`show: help|none`** (obeyed even with no live hub). Ignored:
`pan_mode: sway|track` (tracking arrives as `pan` targets) and `drum: hold|end` (the hub runs every step here).
`raw/sensors/hall` (homing brake). `health/hub` (watchdog).
`audio/head/speaker`: binary PCM frames, not an envelope (the hub's song, cues and voice; "Audio streams").

**Standalone** (`kaiku_net`): `cmd/head` `eyes` (accepted, nothing to see: no display) · `pan` · `gesture` · `purr` ·
**`drum: hold|end`** (the hub runs the drum step: "tap it back") · `pan_mode: sway` + `bpm` (only while held;
anything else stops it) · `mic: open|close` · **`show: help|none`** (needs no hold; no display, so see "Help screen").
`raw/hub/face` · `audio/head/speaker`. Not obeyed: `chest`, `look`, `home`. It does not listen for taps on the bus (D55).

## Emits (topics/endpoints)
`raw/head/ear` `{value 1–5, delta, pressed}` (Knob turns + presses) · `raw/head/button` `{id: "head", pressed}` ·
`raw/head/pan` `{deg (estimated), homed, moving}` 5 Hz while moving, 0.5 Hz idle · `health/head` (retained, 5 s,
LWT `down`) `details{rssi, homed, at_home, hub_silent, reconnects, loop_max_ms, help_shown, audio{rx, drop, dry,
mic_open, mic_tx, mic_drop, mic_peak}}`. Every envelope is also printed on USB serial.
`audio/head/mic`: binary PCM frames, not an envelope, **only while the hub holds the microphone open** ("Audio streams").

**Standalone** (`kaiku_net`): `raw/head/ear` `{value 1–10, delta, pressed}` · **`raw/head/tap` `{t_ms, force, src: "imu"}`**
for each tap its orientation sensor feels, in every step (`t_ms` = ms since boot, `force` = g above rest) ·
`raw/head/pan` `{deg 0, homed, moving}` (one `moving` for a whole sway) · `cmd/sensors {chime:
wake|start_drum|end_drum}` · `health/head` every 5 s **and at once on every step change**, `details{rssi, reconnects,
step, firmware: "standalone", motor_pins, drum_held, help_shown: false, help_screen: "none", calm, loop_max_ms,
audio{rx, drop, dry, mic_open, mic_tx, mic_drop, mic_peak}}` · `audio/head/mic`.

## Map
```
project.yaml            board + modules (speaker 1-2, display 3-4, knob 5-6, button 7, mic 9-10, LED grids 11/14,
                        motor 13, kaiku_link) + HeadIO wiring (the only place Atech method names appear)
kaiku_link/
  kaiku_link.h/.cpp     Wi-Fi + MQTT (backoff 1->10 s, mDNS then IP fallback), envelope + UUIDv7 + NTP UTC ts;
                        knob dial, button, eyes (redraw on change, random blink), chest LEDs, open-loop motor
                        (ramp, segments, dead reckoning, hall homing, home after gestures), hub watchdog
  head_audio.h/.cpp     the speaker and microphone PCM streams, shared by this firmware, the standalone (build.sh
                        copies the two files) and bench/speaker_pcm: 0.5 s ring + its own task -> the Atech
                        Speaker driver's writeSamples; the Microphone driver's capture tap -> high-pass, gain, gate.
                        Every stream number (ring, prebuffer, gains, half-duplex tail, task) is at the top of the .h
  helpline.h            the three lines of the help screen + how long it stays (HELP_SHOW_MS). A copy of
                        config/kaiku.toml [safety]; tests/test_helpline.py fails when the two differ
  help_screen.h         lays the three lines out for any screen size (largest font that fits, wraps at spaces);
                        header-only; used by this firmware only (the robot's head has no display)
  config.h              every hardware number (knob counts, eye shapes, LED brightness, motor pulses) — tune here
  library.json          PlatformIO manifest (linked from project.yaml `libraries:`) + deps (PubSubClient, ArduinoJson 7)
  secrets.example.h     copy to secrets.h (gitignored): Wi-Fi, broker host + IP, user/pass, home id
bench/<part>/           one-part tests: display, knob, button, leds, motor, speaker, mic + link (whole firmware, MQTT)
bench/speaker_pcm/      the audio streams alone, no hub, no model, no display: project.yaml (Wi-Fi + MQTT +
                        head_audio, counters on USB; speaker 1-2, microphone 9-10, the motor on port 14 declared only
                        to hold it still), bench.toml, and audio_test.py for a computer on the same broker
                        (`make head-audio`): test sound, a dropped sound, 5 s of microphone into a WAV, `hold` (leads
                        the standalone's drum step like the hub), `check` for another sender, `show help|none`,
                        `fake-head` (a stand-in to test the tool). recordings/ is gitignored. host_test/: head_audio.cpp built for a computer against a
                        model of the I2S buffer and the capture blocks (`make head-audio-test`; logic only, no board)
standalone/             ACTIVE (D44): website-agent firmware in src/ (main.cpp, pins.h, transport.*; no display code);
                        src/kaiku_net.*: Wi-Fi + MQTT (UNO Q faces in, taps + chimes + pan out; the hub's drum hold,
                        sway, PCM in, microphone out; `show` without a display; serial `net`; hooks in main.cpp
                        marked `// kaiku_net`; handover: docs/robot-network-handover.md)
                        patch_microphone.py adds numeric raw-slot peaks to the fetched microphone driver;
                        a changed upstream source shape fails the build for review
                        project.yaml only lists modules so `atech build` fetches drivers; build.sh overlays src/ +
                        head_audio.* + include shims for its modules/<group>/x.h paths (helpline.h and
                        help_screen.h are not part of this build). `make atech-standalone [FLASH=1]`
tests/                  test_helpline.py, in `make test`: helpline.h equals config/kaiku.toml [safety]; no second copy
                        of the lines in this folder; help_screen.h built for the computer keeps every row inside
                        80 x 160 and 160 x 80. No board, no display
bench/mic_record/       bench tool (no bench.toml): records 3 s, sends it over USB; record_wav.py saves a .wav
                        in bench/mic_record/recordings/ (gitignored; never commit or upload recordings)
```

## Extension points
- New part: a bench part first (`bench/<part>/project.yaml` + `bench.toml`), then a `HeadIO` hook + handling in
  `kaiku_link.cpp`, and its contract message.
- Sound: change a number in `kaiku_link/head_audio.h` (one place for all three programs), then run
  `bench/speaker_pcm` before the firmwares. A new kind of sound needs no firmware change: the hub sends PCM.
- Helpline: change `config/kaiku.toml [safety]` (its owner) and `kaiku_link/helpline.h` together, then `make test`
  (the check says which line differs, and whether a longer line still fits at the same size) and flash.
- Broker on the UNO Q (the robot on its own): `MQTT_HOST`/`MQTT_HOST_IP` in `secrets.h` only
  (docs/robot-network-handover.md → "The robot on its own").

## Audio streams (speaker + microphone over MQTT)
**Microphone troubleshooting (2026-11-15):** with the speaker quiet, a real Live diagnostic received 3145
valid microphone frames (62.9 s), all samples exactly zero, with the hold open and no speaker frames.
This establishes transport and capture callbacks, not working microphone input. Standalone USB JSON command
`{"action":"mic_channel","value":"left"}` or `"right"` changes the driver's L/R select pin without
opening the microphone or changing the decoder's selected stereo slot. It emits `mic_channel` with the
selected value; invalid values are rejected. The default remains the driver's left/LOW selection after reboot.
Use this to distinguish a channel mismatch from missing input; an all-zero result is not a gain problem.
USB JSON `{"action":"mic_probe"}` reports capture blocks and lifetime absolute peaks of both raw 32-bit
I2S slots, before channel extraction or conversion. `{"action":"mic_pins"}` polls clock/data edges for
5 ms (sampled counts, not a frequency meter); it enables input readback only, preserving I2S output routing.
Both commands report numbers only, never audio. On the physical head, both L/R selections returned zero
raw peaks; the corrected pin probe saw 160 WS edges/5 ms and toggling BCLK, but no SD edges (SD LOW).
Thus the data is absent before the hub/Gemini path; cable, module power/type and the microphone itself still
need an independent physical test. The channel selection is restored to left after diagnostics.

Wire format, fixed with the hub (`kaiku_contracts/topics.py`, `hub/kaiku_hub/live/head_audio.py`): binary, QoS 0, not
retained, never an envelope; signed 16-bit little-endian mono 16 000 Hz; one message = 20 ms = 320 samples = 640
bytes. `kaiku/v1/<home>/audio/head/speaker` (hub → head; a zero-length message = drop what is buffered) and
`kaiku/v1/<home>/audio/head/mic` (head → hub).

**What the Atech drivers are** (read from the fetched sources, atech 1.0.0a12, `build/lib/atech_speaker`,
`atech_microphone`): `Speaker` installs the ESP-IDF legacy I2S driver on `I2S_NUM_0` as master TX at 16 000 Hz,
16-bit, two channels (mono copied to both), 8 × 256-frame DMA buffers (128 ms) with `tx_desc_auto_clear`; tones are
generated by its own task (`AudioTask`, core 0, priority 2), which only writes while a tone sounds. It has a
sample call, `writeSamples(const int16_t*, int)`: blocking, scaled by the driver's volume. `Microphone` is the same
driver on `I2S_NUM_1`, master RX, 16 000 Hz, 32-bit frames (the ICS-43434's 24 bits; the top 16 are kept), read 512
frames (32 ms) at a time by `MicTask` (core 0, priority 2), with `onAudio(cb, ctx)`: a gap-free tap called with
every block.

**How PCM lives with them.** Nothing takes the I2S port away: the speaker stream calls the driver's own
`writeSamples` from a task of its own (`kaiku_pcm`, core 0, priority 3), never from the main loop. While PCM is
buffered or sounding, the firmware starts no tone of its own (same port: the two would interleave). The volume
ceiling stays the driver's (standalone: `SPEAKER_VOLUME` 0.7 in `standalone/src/main.cpp`; MQTT firmware: `SPEAKER_PCM_VOLUME` 0.4 in `config.h`);
`SPK_GAIN` in `head_audio.h` is the PCM gain before it (above 1 clips at that ceiling). The hub also scales
(`config/kaiku.toml [music] head_gain`).

| | Number | Where |
|---|---|---|
| Speaker ring | 8000 samples (0.5 s); full → the **newest** message is dropped | `SPK_RING_SAMPLES` |
| Start of a sound | once 120 ms is buffered, or 120 ms after its first frame (the hub runs about 80 ms ahead: playback starts about 20 ms after the first frame, with a 120 ms cushion) | `SPK_PREBUFFER_MS` |
| Nothing left to play | one I2S cycle of zeros (128 ms), so the amplifier gets silence and no old buffer plays twice | `SPK_DMA_BLOCK(S)` |
| Zero-length message | the ring is emptied; what the driver already took (up to 128 ms) still plays | `speakerDrop()` |
| Microphone ring | 8000 samples (0.5 s) between the capture task and the main loop | `MIC_RING_SAMPLES` |
| Microphone level | high-pass at about 75 Hz, then × 8, clipped to 16 bit. **Not measured on the board** | `MIC_GAIN` |
| Half-duplex | no microphone samples are kept while PCM is buffered or sounding, while a tone sounds, or for 250 ms after | `MIC_TAIL_MS` |
| Microphone hold | `cmd.head {mic: open}` re-sent by the hub every 3 s; 10 s without one closes it | `MIC_HOLD_MS` |
| MQTT client | PubSubClient buffer 1024 bytes (default 256; a frame + topic is about 690); it handles ONE message a call, so `tick()` calls it up to 4 times a pass; `TCP_NODELAY`; Wi-Fi modem sleep off | `kaiku_net.cpp`, `kaiku_link.cpp` |
| Load | 50 messages a second in (34 kB/s) OR 50 out, never both (half-duplex) | — |
| Tasks | Wi-Fi 23 and lwIP 18 (core 0) · `kaiku_pcm` 3 (core 0) · Atech `MicTask`, `AudioTask`, `IMU` 2 (core 0) · Arduino loop 1 (core 1: ritual, MQTT, display, knob) | — |

What half-duplex costs: the person cannot interrupt Kaiku by voice on the robot (their words while it speaks never
leave the head); the ear press still works. Talking over each other would need echo cancellation (the speaker's
signal subtracted from the microphone's, on the head or on the hub with a delay estimate) or a microphone the speaker
does not reach. What it would take is in docs/robot-network-handover.md.

## Help screen (`cmd.head {show: "help" | "none"}`)
**The robot's head has no display (D54), so on the robot nothing is shown.** The standalone firmware accepts the
command and does what it still can: the running ritual ends quietly (no chime to the UNO Q, no done step, drum hold
dropped, a `drum: end` in the same message dropped), the microphone shuts, the motor stands still, and the head
stays **calm** (`details.calm`): a face, a sound or a pat does not wake Kaiku and it obeys no `pan`, `gesture`,
`purr` or sway, until `{show: "none"}`, an ear press (the person starts again), a step started over USB, or 10
minutes. Its health says `help_shown: false` and `help_screen: "none"`, so the hub can tell that this head cannot
show the numbers (the hub re-sends `show: help` once to a head that reports `false`: harmless here). PCM from the
hub still plays, so the hub's spoken script is heard. A `{drum: end}` that arrives in a message *before*
`{show: help}` is obeyed first, the usual way (end chime, done step): send `show: help` first or in the same message.
**Until the display is back, the helpline numbers reach the person only through the hub's spoken script.**

The rest of this section is the MQTT firmware, which has the display code.
The hub's crisis path sends it (root rule 6: deterministic, no model). The head draws three lines and nothing else:
the helpline's name, its number, the emergency number, from `kaiku_link/helpline.h` (compile-time, public numbers).
`help_screen.h` picks the largest font of the display driver's built-in 6 × 8 one that fits each line's band:

| Screen | Name | Helpline number | Emergency number |
|---|---|---|---|
| Upright 80 × 160 (no program draws it now; kept in the test) | size 1 (8 px high), two rows | size 3 (24 px), one group of digits a row | size 4 (32 px) |
| MQTT firmware, wide 160 × 80 | size 1, one row | size 2 (16 px), one row | size 3 (24 px) |

The name is small on both screens: 21 characters do not fit larger across 80 or 160 pixels. The numbers are what
must be read at arm's length, and **nobody has looked at this on the real display**.

Rules (MQTT firmware; the standalone's are above):
- Obeyed at once, in any state, **without a drum hold and without a live `health/hub`** (the hub that sends it may
  be going down). QoS as every `cmd.head` (the head subscribes at QoS 1 with a clean session; not retained, so a
  head that is off the broker when it is sent never shows it: the hub can see that in `health/head` `help_shown`).
- **Never a sound for it, never a movement under it**: the motor stops, the firmware's own tone stops, `pan`,
  `gesture`, `purr`, sway and homing are ignored while it shows. PCM from the hub still plays (the hub's scripted
  message is the hub's to send or not).
- The microphone closes when it arrives. A later `mic: open` from the hub opens it again (the hub's decision), and
  the head shows that under the help screen too: the ear ring, plus the orange dot, which is clear of the text.
- It stays until `{show: "none"}` or 10 minutes (`HELP_SHOW_MS`), whichever is first; a new `{show: "help"}` starts
  the 10 minutes again.
- It cannot know when a ritual starts (the hub runs every step), so only `none` or the 10 minutes
  clear it. The hub must send `{show: "none"}` when the person starts again. The ear ring is off under it unless
  the microphone is open.

## Invariants
- **Power rule (strict):** the speaker amplifier and the motor share one supply, so they never run together. While any sound is on the speaker (the hub's voice, songs, cues, a tone of the head's own) the motor is off (`stop()`, both lines low), whatever asked for it: pan, purr and the hub's sway all wait for the speaker to be quiet. The speaker plays at `SPEAKER_VOLUME` (0.7; 1.0 clips the amp); only while the motor is still turning when a sound starts (one loop pass) is it at `SPEAKER_VOLUME_WITH_MOTOR` (0.2). Every motor command goes through `driveMotor()` and the volume is set only in `powerRule()` (`standalone/src/main.cpp`). Flashed 2026-11-14; not measured on the supply. Cost: no sway on the beat while a song plays.
- **Never move without a live hub**: motion commands are ignored while `health/hub` is silent or `down`. After
  `HUB_SILENCE_STOP_MS` (15 s = 3 hub heartbeats) the motor brakes and the speaker stops. The first homing waits for
  the first live hub. Eyes and LEDs may change without a hub (no motion).
- The long-press safety decision is the hub's (≥ 2 s); the firmware only reports edges and never filters long holds.
- Motor: ramp ~100 ms, ≤ 1 s per command, new moves ignored mid-gesture/homing, homing gives up after 2 s per
  direction, home after every gesture, purr only when the motor is idle.
- Same topics + payloads as `head_sim` — the hub can't tell them apart.
- Secrets only in gitignored `kaiku_link/secrets.h` (public repo).
- **The microphone leaves the head only while the hub holds it open** (`cmd.head {mic: open}` not older than 10 s,
  broker connected; in this firmware also a live `health/hub`), and the head shows it for as long: an orange dot at
  the top right of the eyes display and the ear ring on (this firmware). Nothing is stored on the head; the level
  check for "someone is near" never leaves it.
- **Standalone, the open microphone on a head without a display: the ear ring is the only light.** The knob's
  position light turns blue (it is orange otherwise) while the microphone streams. In the printed head the ring is
  seen only if the ear hole was drilled out to Ø26 (`hardware/assembly.md` calls that optional), and **nobody has
  checked whether it can be seen on the assembled robot**. If it cannot, nothing on this head shows an open
  microphone: a privacy limit to state, not to hide (`docs/privacy.md` is the place). `health/head`
  `audio.mic_open` says it on the bus either way.
- **Audio never waits in the main loop**: frames go into a ring in the MQTT callback and a task plays them; a full
  ring drops the newest frame, an empty one is silence. The motor, knob and MQTT are served the same with or
  without sound.
- No tone of the head's own (purr, cues, tap tones) while PCM plays, and none over it.
- Standalone, while the hub holds the drum step (`drum: hold`, fresh for 10 s): the head stays in its drum step,
  its own drum clock is off, it plays no tap tones, and it obeys sway (nothing shows it: no display). A knob press still ends the step
  and says so (`chime: end_drum`, then `health/head` with the new step). 10 s without a hold and the head's own
  clock decides again: a silent hub never strands it. After `drum: end`, or a step the hub held, the head prints
  `drum {"run_by":"hub","imu_taps":N}` on USB: no tempo, no average, because it measured no session.
- Standalone taps (`raw.head.tap`, `src: "imu"`, D55): the detector is the robot firmware's own (0.15 g above rest,
  at most one per 120 ms, none while the motor runs, which includes the sway, nor 400 ms after). Added on top: none
  while PCM plays nor 150 ms after (the speaker shakes the sensor), and the same rule keeps the head from being
  woken by its own speaker. Taps are published in every step; in the drum step they count, from idle they wake it.

## Run standalone
`make atech-setup` (once): a venv at `firmware/atech-head/.venv` with the pinned SDK (`requirements.txt`) and the
ESP32 toolchain inside it (~4 GB), on **espressif32 6.9.0** (Arduino core 2.0.17). Then `source
firmware/atech-head/.venv/bin/activate` in every terminal (it keeps PlatformIO in the venv). `cp
kaiku_link/secrets.example.h kaiku_link/secrets.h`, fill it in. `atech validate . && atech build . && atech upload .`
(data cable). Without hardware: `make sim NODES=head`.
Shortcuts from the repo root: `make atech-standalone FLASH=1` (active, D44) or `make atech-mqtt FLASH=1` (this firmware);
both upload at 115200 with `--no-stub`, the only upload that verifies on the bench Mac. One bench part the same way:
`make atech-bench PART=firmware/atech-head/bench/speaker_pcm [FLASH=1]`.

## Run with sim
`make broker && make hub` (+ `make sim NODES=sensors` for hall edges), flash, `make tail TOPIC='kaiku/v1/+/raw/head/#'`.

## Config & env
`kaiku_link/config.h` (numbers), `kaiku_link/secrets.h` (credentials). Hub side: `config/kaiku.toml [robot]`,
`[attention] camera_on_head` / `pan_limit_deg`.

## Health signal
`health/head` `ok` with a live hub, `degraded` while the hub is silent; LWT `down`.

## Tests
Bench, one part at a time: `make bench PART=firmware/atech-head/bench/<display|knob|button|leds|motor|speaker|mic>
FROM=-` piped from `atech monitor` (or `FROM=serial:<port>`). Then `make bench PART=firmware/atech-head/bench/link
FROM=mqtt` with `make hub` and the UNO Q app running. Checker logic: `tools/tests/test_bench.py`.
Sound, with no hub and no model: flash `bench/speaker_pcm` (or either firmware; the bench needs no display and
holds the motor on port 14 still, so nothing is unplugged), then on a computer on the same
broker `make head-audio ARGS='bench --host <broker ip>'`: a 10 s click-and-note pattern at 100 a minute, a sound
dropped on purpose, then 5 s of microphone saved to a WAV with frame count, gaps and level. With the bench program
the checker reads its USB lines (`make bench PART=firmware/atech-head/bench/speaker_pcm FROM=-`); with a firmware
the tool prints the head's own counters from `health/head`. `make head-audio ARGS='check --host <ip>'` checks
another sender (the hub) against the wire format, and `hold` leads the standalone's drum step with no hub (hold,
sway, your turn, end) and counts its taps. After changing `kaiku_link/head_audio.*`: `make head-audio-test` (the
ring, prebuffer, drop, silence and microphone-gate rules on a computer, about 25 s; it says nothing about the board).
`show: help`: `make head-audio ARGS='show --host <broker ip> help'` (then `none`): on the robot's standalone head
expect no screen, the ritual ended quietly and `calm: true` in `health/head`; on the MQTT firmware with a display,
the three lines. Without a board: `uv run pytest firmware/atech-head/tests` (in `make test`): the lines equal
`config/kaiku.toml [safety]`, and the layout stays inside both screen sizes. It cannot say how a display looks.
The order for the bench (tonight on the laptop) is in docs/robot-network-handover.md.

## Known issues
Verified 2026-11-14 with atech 1.0.0a12: all 7 `bench/<part>` projects validate and compile. SDK module IDs are
`button`, `rotary_encoder`, `neopixel` (not the website's `button_module`, `rotary_encoder_knob`, `neopixel_grid`);
two-port modules take `ports: [a, b]`; the Speaker method is `playRTTTL`. The SDK leaves the ESP32 platform unpinned
and the newest (8.x) breaks its own `dc_motor` driver (`ledcSetup`), hence the 6.9.0 pin. The root `project.yaml` also
validates and compiles: an SDK module must sit on a real port, so `kaiku_link` is a plain PlatformIO library linked in
place (`libraries: kaiku_link=symlink://../kaiku_link` + `kaiku_link/library.json`, which carries the MQTT/JSON deps).
Still to run on hardware: the full firmware and the link bench. Tune `KNOB_COUNTS_PER_STEP`, `MOTOR_DEG_PER_S_FULL`, the
eye shapes and the pan sign on the real robot. This build has no hall sensor (D39, `HAS_HALL 0`): face the head forward before
powering on; `home` drives back to the dead-reckoned 0° and the soft limit is ±80°. With `HAS_HALL 1` the edge arrives over
Bridge → MQTT → Wi-Fi, so homing may overshoot a little.

Found on the first builds (2026-11-14, espressif32 6.9.0 / Arduino core 2.0.17; benches built, mic verified on
hardware): stops use `motor.stop()` (both lines LOW, off on any H-bridge); `brake()` is untested on this motor (the
first "won't stop" run had the motor on port 13 while the code drove port 7). **A motor on a port the running program
doesn't declare floats and may spin**: unplug it when flashing other benches. Port 11 is GPIO43/44 (UART0), so an LED
grid there may flicker during boot. The display is in canvas mode by default (nothing shows until `tft.display()`), so the firmware sets
`tft.setDirectMode(true)`. Speaker calls return at once: `playNote` queues, `playTone`/`playRTTTL` interrupt.

Bench 2026-11-14 (motor + power): **the motor needs a proper USB-C charger on port 8**; the hub's charge-only port and
the Mac's USB run the logic but the motor never turns. On port 11 only reverse turns (forward = GPIO44, UART0 RX).
Fixed in `kaiku_link`: `tick()` read `now` before `mqtt.loop()`, so stamps set while handling messages wrapped the
unsigned differences (hub "silent" after each heartbeat, every motor segment skipped); with no USB host reading,
`println` stalled the loop (`Serial.setTxTimeoutMs(0)`); softer motor start (ramp 400 ms, gesture speed 110).
No LED grids in this build (ports 11/14 free).
Standalone (D44), on hardware: runs untethered on its own USB-C power. `build.sh` mutes the Atech drivers' debug prints
(with nobody reading USB they stalled the loop and knob presses were missed; `VERBOSE=1` keeps them). Opening the
serial port resets the board. Commands with a value must be JSON lines (`{"action":"pan","value":"100"}`).
Standalone, no display (removed from the head 2026-11-14): the driver, pins and all eye/screen drawing are out of
`standalone/`; `cmd.head` eyes and the serial `eyes` command are still accepted and do nothing visible. Ports 3-4 free.
Standalone motor port: **14** (GPIO36/35; `standalone/project.yaml` + `src/pins.h`), moved from 11 where only one
direction turned. At boot the firmware drives both motor lines high and low together and reports the read-back in
`health/head` details as `motor_pins`. Seen on the robot (2026-11-14, on its charger): `36:ok 35:ok`, and `cmd.head`
pans over MQTT turned the motor both ways. Serial `net` prints the Wi-Fi/MQTT state and, when offline, whether the
configured network is in range (never the password). A `cmd.head` pan runs a fixed 600 ms at `speed` (sign from `target_deg`); there is no position estimate.
`build.sh` clears its copied sources before `atech build` (a rebuild compiled them without their libraries).
`kaiku_net` verified on the board (2026-11-14, iPhone hotspot): joins Wi-Fi, connects to the broker, `health/head`
every 5 s + `raw.head.pan`, takes `cmd.head` eyes, and a face seen by the UNO Q woke the head from idle to greet.
Taps (D55): the orientation sensor on port 13 is the only tap source (`shakeG` 1.15 = total g, so 0.15 g
above rest; serial `tap_sensitivity`, never ≤ 1); each tap is published as `raw.head.tap {t_ms, force, src: imu}` in every ritual step, counts in
DRUM and wakes the head from idle; nothing counts while the motor runs or for 400 ms after. Seen on the robot
(2026-11-14): hand taps arrive on the broker at about one a second (0.15-0.73 g) and wake the head; at 0.3 g most
were missed. Not yet seen: taps counted in a DRUM step over the bus, the chimes sounding on the UNO Q buzzer.
Serial output is dropped when the USB buffer has no room: on a computer's USB port with nobody reading, writes
stalled the loop and the head left the broker after ~15 s. **`secrets.h` is per laptop**
(gitignored): flashing from another machine uses that machine's Wi-Fi and broker IP; set all three
(`WIFI_SSID` exactly as the phone shows it, curly ’ included; `WIFI_PASS`; `MQTT_HOST_IP` = the broker laptop).
On the venue Wi-Fi the head (and the UNO Q, at the same moments) lost the broker every 1-2 min; on the hotspot not.

**Standalone on top of the robot firmware (2026-11-14 evening, on a Mac with no board connected: compiled, not
flashed, nothing heard).** The robot firmware described above (no display, taps from the orientation sensor, motor
on port 14, serial lines dropped when the USB buffer is full, serial `net`) is the base, untouched in what it does;
the sound work was put back on top of it. Sizes: the robot firmware alone 802 829 B flash (24.0 %) / 55 476 B RAM
(16.9 %), version `…-0.1.0`; with sound 808 669 B (24.2 %) / 90 428 B (27.6 %), version `…-0.4.0` (the 35 kB of
RAM are the two 0.5 s rings); MQTT firmware 824 329 B / 85 244 B; `bench/speaker_pcm` 731 089 B (21.9 %) / 80 908 B
(24.7 %). `make head-audio-test`, `firmware/atech-head/tests` and the bench checker's tests pass; the host tool
was run against its stand-in head on a throwaway broker.
- Put back: the speaker stream (ring, its own task, `writeSamples`), the microphone stream (only while held open,
  half-duplex), `drum: hold|end` (own drum clock off, no tap tones, 10 s lapse), sway while held, the health
  additions, health at once on a step change (the hub follows `details.step`), the tap mute while PCM plays, no
  tone of the head's own over PCM, no wake by its own speaker, up to 4 MQTT messages a pass, modem sleep off,
  `TCP_NODELAY`, the 1024-byte MQTT buffer.
- Not carried over, and why: the help screen, the orange microphone dot and the `tap it back` text (no display);
  taps from the UNO Q's knock switch and the rule that merged them with the head's own (no knock switch, D55); the
  first version's own tap numbers (80 ms apart, 150 ms after the motor: the robot firmware's 120 ms and 400 ms are
  kept, they were tuned on the robot); the mapping of the contract's eye names onto five faces (nothing to draw).
- Found by the first version's logic test and still true: `make head-audio-test` after any change to
  `kaiku_link/head_audio.*`. Every standalone build installs PubSubClient and ArduinoJson again: build while online.
- **Most likely to fail first on the board** (never run): sound at all (`writeSamples` from our task, the 0.4
  ceiling loud enough, no crackle); the stream under Wi-Fi (`audio.dry`, `loop_max_ms`); microphone level
  (`MIC_GAIN` is a guess) and whether 250 ms of tail is enough; taps firing on the speaker or the motor despite
  the mutes; sway (`SWAY_SPEED_PCT` 45 and `SWAY_PULSE_MS` 160 are guesses, open loop, may drift).
- **Risks for sound on this firmware and this network, none measured:**
  1. Two radio hops on a phone hotspot (laptop → phone → head) for 50 frames a second: late frames. The cushion is
     120 ms (`SPK_PREBUFFER_MS`); `audio.dry` above one a sound means it is too short here.
  2. USB serial: the firmware drops its lines when nobody reads them. The bench program does the same for its own
     lines, but the Atech-generated part of it still prints a microphone level 4 times a second with a plain
     `Serial.print`: on a computer's USB port, keep `atech monitor` reading for the whole bench run.
  3. The loop: every pass reads the orientation sensor three times, serves the knob and its ring, and every 40 ms
     writes a chest LED grid that is not fitted. Expected a few ms a pass, and the display's slow redraw is gone;
     `loop_max_ms` in `health/head` is the measure (under 100). Serial `net` blocks about 3 s when offline, and each
     try to reach a broker that is not there blocks up to about 5 s (name lookup 2 s, then the connection).
  4. Microphone frames out: a publish to a full TCP buffer on a bad link can hold the loop; watch `loop_max_ms`
     while the microphone is open.
  5. Power: speaker and motor (sway) at once on one supply, and the radio never sleeps now. On a computer's USB
     port the motor never turns (D54) and how loud the speaker gets there is not known.
  6. Sway and taps: every push mutes taps for 400 ms, so above about 105 beats a minute no tap counts while the
     head sways. That is meant (the hub listens in "your turn", when the head stands still) and never tried.
  7. The time: no envelope leaves the head until it has reached `pool.ntp.org` through the hotspot (no
     `health/head` until then); sound frames do not wait for it.
