# firmware/atech-head — AGENTS.md

> Read the root `AGENTS.md` first. Owner A · kind firmware · reference behaviour: `sim/nodes/head_sim.py`.

## Purpose
The robot's head on Atech ESP32 modules: animated eyes, IMU tap detection (KY-031 knock sensor as backup), ear
rotary encoder (KY-040 if the Atech knob is busy), pan motor (DC + gyro integration + hall homing), chest LEDs,
vibration "purr". **VERIFY first** (Phase 0 spike, record in `docs/decisions.md`): display size/driver, IMU model
and max sample rate, motor driver, and whether exported firmware may run a custom MQTT client (D6). If it can't,
expose Atech's native Wi-Fi/BLE API and translate in `hub/kaiku_hub/devices/atech_adapter.py` — nothing else changes.

## Consumes (topics/endpoints)
`cmd/head` — `eyes`, `look{x,y}`, `pan{target_deg,speed}`, `pan_mode track|still|sway`, `bpm`, `home`,
`chest off|breathe|glow|pulse`, `color #rrggbb`, `purr{ms}` (`contracts/schemas/cmd/head.schema.json`).

## Emits (topics/endpoints)
`raw/head/tap` `{t_ms, force (peak g), src: imu|knock}` · `raw/head/ear` `{value 1–5, delta, pressed}` ·
`raw/head/pan` `{deg, homed, moving}` 10 Hz · `health/head` (retained, 5 s, last-will `down`).
Envelope example per type: `contracts/schemas/examples.json`.

## Invariants
- Same topics and payloads as `head_sim` — the hub can't tell them apart.
- `ear.value` is the clamped dial position 1–5; each press answers the hub's current dial question with that
  value (protocol: `hub/AGENTS.md` → Invariants).
- Taps: 80 ms refractory; suppress during pan motor accel/decel.
- Wi-Fi/broker credentials only in a gitignored `secrets.h`.

## Run standalone
Flash via https://atech.dev (Chrome/Edge, WebSerial, data USB cable; Linux: `dialout` group) or the exported
PlatformIO project here; `pip install atech` for agent work. Without hardware: `make sim NODES=head`.

## Run with sim
`make broker`, flash, `make tail TOPIC='kaiku/v1/+/raw/head/#'`; drive outputs with `make hub` + `make sim NODES=sensors`.

## Config & env
`secrets.h` (gitignored): Wi-Fi SSID/password, broker IP.

## Health signal
`health/head` `details{imu_ok, motor_ok, homed}`.

## Tests
Taps, ear and pan visible in `make tail`; every `cmd/head` field works; homing after power cycle. Record soft,
hard and pan-only tap sessions with `make record` and hand them to the hub owner as fixtures.

## Known issues
No servos: pan is a DC motor (geared? D7) — printed reduction if not geared. Foam under the visor if taps knock
the pan gear out of mesh.
