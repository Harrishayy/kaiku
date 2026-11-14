# firmware/atech-head — AGENTS.md

> Read the root `AGENTS.md` first. Owner A · kind firmware · reference behaviour: `sim/nodes/head_sim.py` ·
> build plan: `docs/plans/07-robot-electronics.md` · decisions D31 (hardware), D32 (software).

## Purpose
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
`home` · `gesture: look_left|look_right|shake` · `purr{ms}` · `pan_mode: still`. Ignored: `pan_mode: sway|track`
(tracking arrives as `pan` targets). `raw/sensors/hall` (homing brake). `health/hub` (watchdog).

## Emits (topics/endpoints)
`raw/head/ear` `{value 1–5, delta, pressed}` (Knob turns + presses) · `raw/head/button` `{id: "head", pressed}` ·
`raw/head/pan` `{deg (estimated), homed, moving}` 5 Hz while moving, 0.5 Hz idle · `health/head` (retained, 5 s,
LWT `down`) `details{rssi, homed, at_home, hub_silent, reconnects}`. Every envelope is also printed on USB serial.

## Map
```
project.yaml            board + modules (speaker 1-2, display 3-4, knob 5-6, button 7, mic 9-10, LED grids 11/14,
                        motor 13, kaiku_link) + HeadIO wiring (the only place Atech method names appear)
kaiku_link/
  kaiku_link.h/.cpp     Wi-Fi + MQTT (backoff 1->10 s, mDNS then IP fallback), envelope + UUIDv7 + NTP UTC ts;
                        knob dial, button, eyes (redraw on change, random blink), chest LEDs, open-loop motor
                        (ramp, segments, dead reckoning, hall homing, home after gestures), hub watchdog
  config.h              every hardware number (knob counts, eye shapes, LED brightness, motor pulses) — tune here
  library.json          PlatformIO manifest (linked from project.yaml `libraries:`) + deps (PubSubClient, ArduinoJson 7)
  secrets.example.h     copy to secrets.h (gitignored): Wi-Fi, broker host + IP, user/pass, home id
bench/<part>/           one-part tests: display, knob, button, leds, motor, speaker, mic + link (whole firmware, MQTT)
bench/mic_record/       bench tool (no bench.toml): records 3 s, sends it over USB; record_wav.py saves a .wav
                        in bench/mic_record/recordings/ (gitignored; never commit or upload recordings)
```

## Extension points
- New part: a bench part first (`bench/<part>/project.yaml` + `bench.toml`), then a `HeadIO` hook + handling in
  `kaiku_link.cpp`, and its contract message.
- Audio through the Speaker/Mic (STRETCH, plan 07 §4): `audio/head/*` binary topics + a ring buffer. Never inside
  the envelope.
- Broker on the UNO Q later: change `MQTT_HOST`/`MQTT_HOST_IP` in `secrets.h` only.

## Invariants
- **Never move without a live hub**: motion commands are ignored while `health/hub` is silent or `down`. After
  `HUB_SILENCE_STOP_MS` (15 s = 3 hub heartbeats) the motor brakes and the speaker stops. The first homing waits for
  the first live hub. Eyes and LEDs may change without a hub (no motion).
- The long-press safety decision is the hub's (≥ 2 s); the firmware only reports edges and never filters long holds.
- Motor: ramp ~100 ms, ≤ 1 s per command, new moves ignored mid-gesture/homing, homing gives up after 2 s per
  direction, home after every gesture, purr only when the motor is idle.
- Same topics + payloads as `head_sim` — the hub can't tell them apart.
- Secrets only in gitignored `kaiku_link/secrets.h` (public repo).

## Run standalone
`make atech-setup` (once): a venv at `firmware/atech-head/.venv` with the pinned SDK (`requirements.txt`) and the
ESP32 toolchain inside it (~4 GB), on **espressif32 6.9.0** (Arduino core 2.0.17). Then `source
firmware/atech-head/.venv/bin/activate` in every terminal (it keeps PlatformIO in the venv). `cp
kaiku_link/secrets.example.h kaiku_link/secrets.h`, fill it in. `atech validate . && atech build . && atech upload .`
(data cable). Without hardware: `make sim NODES=head`.

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

## Known issues
Verified 2026-11-14 with atech 1.0.0a12: all 7 `bench/<part>` projects validate and compile. SDK module IDs are
`button`, `rotary_encoder`, `neopixel` (not the website's `button_module`, `rotary_encoder_knob`, `neopixel_grid`);
two-port modules take `ports: [a, b]`; the Speaker method is `playRTTTL`. The SDK leaves the ESP32 platform unpinned
and the newest (8.x) breaks its own `dc_motor` driver (`ledcSetup`), hence the 6.9.0 pin. The root `project.yaml` also
validates and compiles: an SDK module must sit on a real port, so `kaiku_link` is a plain PlatformIO library linked in
place (`libraries: kaiku_link=symlink://../kaiku_link` + `kaiku_link/library.json`, which carries the MQTT/JSON deps).
Still to run on hardware: the full firmware and the link bench. Tune `KNOB_COUNTS_PER_STEP`, `MOTOR_DEG_PER_S_FULL`, the
eye shapes and the pan sign on the real robot. The hall edge arrives over Bridge → MQTT → Wi-Fi, so homing may overshoot a little.

Found on the first builds (2026-11-14, espressif32 6.9.0 / Arduino core 2.0.17; benches built, mic verified on
hardware): stops use `motor.stop()` (both lines LOW, off on any H-bridge); `brake()` is untested on this motor (the
first "won't stop" run had the motor on port 13 while the code drove port 7). **A motor on a port the running program
doesn't declare floats and may spin**: unplug it when flashing other benches. Port 11 is GPIO43/44 (UART0), so an LED
grid there may flicker during boot. The display is in canvas mode by default (nothing shows until `tft.display()`), so the firmware sets
`tft.setDirectMode(true)`. Speaker calls return at once: `playNote` queues, `playTone`/`playRTTTL` interrupt.
