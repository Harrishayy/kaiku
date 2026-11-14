# firmware/unoq-sensors — AGENTS.md

> Read the root `AGENTS.md` first. Owner A · kind firmware · reference behaviour: `sim/nodes/sensors_sim.py` ·
> build plan: `docs/plans/07-robot-electronics.md` · decisions D31 (hardware), D32 (software).

## Purpose
The robot's sensors on the Arduino UNO Q (in the body), as one App Lab app with two halves.
- **STM32 sketch:** reads the KY-031 knock drum (under the head top), the KY-035 hall sensor (pan home; not fitted, `HAS_HALL 0`, D39), the KY-054 (not fitted)
  room light and the KY-039 heartbeat through the KY-053 ADS1115 at 100 Hz (**neither fitted in this build, D45**: the
  pulse comes from the camera, `ppg_source = "camera"`). It plays the Modulino Buzzer chimes and
  shows a status icon on the hidden LED matrix.
- **Linux app:** bridges the sketch to MQTT and turns the USB camera (in the head) into numbers: face boxes,
  distance from face size, and backups for pulse and room light.

## Boundaries
Sketch ↔ app only through the Bridge (RPC router). App ↔ everything else only through contract messages via
`kaiku_contracts.Bus` (copied in by `make unoq-app`). No hub logic here: the hub computes drum sessions, HRV, presence
and the ritual. The eyes, knob, LEDs and motor belong to the Atech board. Camera frames never leave the camera thread.

## Consumes (topics/endpoints)
`cmd/sensors`: `chime: wake|ok|start_drum|end_drum|alert` · `ppg: start|stop` · `camera_enable`.
`raw/head/pan` `moving` → the sketch ignores knocks while the motor runs.

## Emits (topics/endpoints)
`raw/head/tap` `{t_ms, src: "knock"}` (no force) · `raw/sensors/hall` `{at_home}` on each edge ·
`raw/sensors/light` `{raw, lux_est}` every 10 s (camera with locked exposure: `light_source = "camera"`, this build; KY-054 if fitted) ·
`raw/sensors/ppg` `{t0_ms, fs_hz, samples}`: KY-039 100 Hz × 25 (quality 0.9), or the camera backup ~15 Hz (quality
0.6) · `raw/hub/face` per face at 5 Hz · `raw/sensors/distance` `{cm}` from the biggest face (`far_cm` when nobody is
there) · `health/sensors` `details{camera_ok, mcu_ok, mcu_fw, knocks, ppg, at_home}`.

## Map
```
sketch/sketch.ino     knock ISR (idle calibration, 40 ms debounce, motor mute), hall poller (200 Hz, hysteresis),
                      ADS1115 100 Hz sampler (raw I2C, no library), light_read, buzzer pattern player (millis),
                      status matrix, Bridge
sketch/config.h       every MCU number (pins, debounce, hall threshold, ADS config, PPG rate/batch)
python/main.py        App Lab entry (RouterBridge) or laptop mode (--fake-bridge, keyboard k/r/q)
python/kaiku_unoq/
  node.py             SensorsNode: Bus + Bridge glue; pulse routing (KY-039 first, camera backup); light loop
  bridge.py           RouterBridge (arduino.app_utils) + FakeBridge; the Bridge interface list
  camera.py           camera thread: Haar faces, forehead-green pulse, optional locked-exposure light; frames in memory
  vision.py           pure maths (face payload, distance, light, forehead box, PPG signal check)
python/tests/         node on a real broker with FakeBridge, pulse fallback, vision maths (in `make test`)
bench/<part>/         one-part tests: knock, hall, light, ky039, buzzer (sketches), camera (python), link (MQTT)
```

## Extension points
- New sensor: a bench part first, then a sketch handler + `Bridge.notify`, a `provide` in `node.py`, and its message.
- Pulse source: `[unoq] ppg_source = auto|ky039|camera`. Light source: `[unoq] light_source = ky054|camera`.
- Hub + broker on this board later: run them here and set `MQTT_HOST=localhost` (plan 07 §4).

## Invariants
- Same topics + payloads as `sensors_sim` (and `head_sim`'s knock taps): the hub can't tell them apart.
- No frame, audio or image is stored, logged or sent. Only the numbers above leave the camera thread (docs/privacy.md).
- PPG only between `ppg start` and `ppg stop`, at a stable `fs_hz` (fixed micros grid on the sketch).
- Knocks are ignored while the pan motor moves. `alert` chime = device fault only, never mood or safety.
- A dead sketch or camera never kills the node: Bridge calls and the camera fail soft and show in `health/sensors`.

## Run standalone
On a laptop: `uv run python firmware/unoq-sensors/python/main.py --fake-bridge` (webcam stands in; `k` knock, `r`
sketch ready). On the board: `make unoq-app`, open `firmware/unoq-sensors` in App Lab (python + sketch), Run.
Without hardware: `make sim NODES=sensors`.

## Run with sim
`make broker && make hub` on the laptop, UNO Q on the same network (`MQTT_HOST` = laptop),
`make tail TOPIC='kaiku/v1/+/raw/#'`; drive the Atech side with `make sim NODES=head`.

## Config & env
`config/kaiku.toml [unoq]` (camera, distance, light and pulse routing), `sketch/config.h` (MCU numbers). Env:
`MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS`, `KAIKU_HOME_ID`.

## Health signal
`health/sensors` every 5 s. `mcu_ok` false = the sketch doesn't answer `ping` (its version string names a missing
ADS1115 or buzzer; `ads-missing` is expected in this build, D45). `camera_ok` false = no camera (check the PD hub).

## Tests
`make test` runs `python/tests`. Bench: `make bench PART=firmware/unoq-sensors/bench/<knock|hall|light|ky039|buzzer|camera>`
(saved monitor log or `FROM=-`), then `bench/link` with `FROM=mqtt`.

## Known issues
Verified on the board (2026-11-14): the sketch compiles and runs (`arduino-cli compile --profile default -b
arduino:zephyr:unoq`, libraries pinned in `bench/sketch.yaml`); health ok with camera + sketch; knock taps, faces,
distance, camera room light, buzzer chimes on `cmd.sensors`; works together with the Atech head over one broker.

Board setup that is **not in the repo** (redo it on a fresh board):
- `~/ArduinoApps/kaiku-sensors/.env`: `MQTT_HOST=<broker IP>` (the laptop on the hotspot: `172.20.10.11` today),
  `MQTT_PORT=1883`, `KAIKU_HOME_ID=demo-aino`.
- **Default app** = `kaiku-sensors`, so it starts at boot: `arduino-app-cli properties set default
  ~/ArduinoApps/kaiku-sensors` (check with `properties get default`). Before that it never restarted after a power cut.
- Wi-Fi (NetworkManager): the hotspot is saved with `autoconnect-priority 10` and `autoconnect-retries 0` (retry
  forever); the venue `Junction2026` is saved with autoconnect off. iPhone hotspots stop broadcasting when nobody
  is connected: keep the phone on Settings → Personal Hotspot while the UNO Q boots (~1-1.5 min to app running).

Traps:
- `python/requirements.txt` must not list OpenCV/numpy: App Lab's container ships its own OpenCV (4.13), asking for
  another fails the whole install and then aiomqtt is missing (nothing publishes).
- Camera: `camera_index = -1` = the stable `/dev/v4l/by-id/*-video-index0` name (the board renumbers video0-3
  between boots). `v4l2-ctl` is not in the container, so exposure lock falls back to OpenCV and may log "exposure lock
  failed" (light is then auto-exposed). OpenCV must be < 5 (5.0 dropped `CascadeClassifier`).
- **Open bug:** with no camera attached (e.g. the UNO Q on the Mac's USB instead of the hub) the app quits instead
  of reporting `camera_ok: false`.
- USB to the Mac: if `adb devices` is empty, `adb kill-server` then retry; many USB-C cables are charge-only.
- The App Lab serial relay garbles the sketch monitor: read it on the board (`socat` on 127.0.0.1:7500).
- Unplugging another board from a shared supply rebooted the UNO Q: give it its own supply (PD hub + Arduino PSU).

Still to do: tune `distance_k_cm`; KY-035 / KY-054 / KY-039 / KY-053 code stays for a future build (`HAS_HALL 0`).
