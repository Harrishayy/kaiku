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
project.yaml            board + modules (speaker 1-2, display 3-4, knob 5-6, motor 7, mic 9-10, button 11,
                        LED grids 13/14, kaiku_link) + HeadIO wiring (the only place Atech method names appear)
kaiku_link/
  kaiku_link.h/.cpp     Wi-Fi + MQTT (backoff 1->10 s, mDNS then IP fallback), envelope + UUIDv7 + NTP UTC ts;
                        knob dial, button, eyes (redraw on change, random blink), chest LEDs, open-loop motor
                        (ramp, segments, dead reckoning, hall homing, home after gestures), hub watchdog
  config.h              every hardware number (knob counts, eye shapes, LED brightness, motor pulses) — tune here
  module.yaml           custom-module declaration + lib_deps (PubSubClient, ArduinoJson 7)
  secrets.example.h     copy to secrets.h (gitignored): Wi-Fi, broker host + IP, user/pass, home id
bench/<part>/           one-part tests: display, knob, button, leds, motor, speaker, mic + link (whole firmware, MQTT)
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
`pip install atech` (Python ≥ 3.10; the first build downloads ~2.4 GB, once). `cp kaiku_link/secrets.example.h
kaiku_link/secrets.h`, fill it in. `atech validate . && atech build . && atech upload .` (data cable). Without
hardware: `make sim NODES=head`.

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
Not compiled yet (no Atech toolchain on the authoring machine). VERIFY with `atech guide` / `atech info`: the
`code.setup` key; C++ method names (camelCase assumed from the docs' example: `isPressed`, `getPosition`,
`enableRing`, `fillScreen`/`fillRect`, `setAll`/`show`, `setSpeed`, `brake`, `playNote`, `setVolume`, `stop`); the
`module.yaml` shape; the port id for a non-hardware module. Tune `KNOB_COUNTS_PER_STEP`, `MOTOR_DEG_PER_S_FULL`, the
eye shapes and the pan sign on the real robot. The hall edge arrives over Bridge → MQTT → Wi-Fi, so homing may overshoot a little.
