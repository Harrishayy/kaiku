# firmware/unoq-sensors — AGENTS.md

> Read the root `AGENTS.md` first. Owner A · kind firmware · reference behaviour: `sim/nodes/sensors_sim.py` ·
> build plan: `docs/plans/07-robot-electronics.md` · decisions D31 (hardware), D32 (software).

## Purpose
The robot's sensors on the Arduino UNO Q (in the body), as one App Lab app with two halves.
- **STM32 sketch:** reads the KY-035 hall sensor (pan home; not fitted, `HAS_HALL 0`, D39), the KY-054 (not fitted)
  room light and the KY-039 heartbeat through the KY-053 ADS1115 at 100 Hz (**neither fitted in this build, D54**: the
  pulse comes from the camera, `ppg_source = "camera"`). It plays the Modulino Buzzer chimes and
  shows a status icon on the hidden LED matrix.
- **Linux app:** bridges the sketch to MQTT and turns the USB camera (in the head) into numbers: face boxes,
  distance from face size, and backups for pulse and room light.

## Boundaries
Sketch ↔ app only through the Bridge (RPC router). App ↔ everything else only through contract messages via
`kaiku_contracts.Bus` (copied in by `make unoq-app`). No hub logic here: the hub computes drum sessions, HRV, presence
and the ritual. The eyes, knob, LEDs and motor belong to the Atech board. Camera frames never leave the camera thread.

## Consumes (topics/endpoints)
`cmd/sensors`: `chime: wake|ok|start_drum|end_drum|alert` · `ppg: start|stop` · `camera_enable` ·
`face_signs_s` (Photo time: count face signs for that many seconds, then one `raw/sensors/face_signs`).
Taps are not this node's any more (D55): the KY-031 knock switch is removed; the Atech head publishes `raw/head/tap`.

## Emits (topics/endpoints)
`raw/sensors/hall` `{at_home}` on each edge ·
`raw/sensors/light` `{raw, lux_est}` every 10 s (camera with locked exposure: `light_source = "camera"`, this build; KY-054 if fitted) ·
`raw/sensors/ppg` `{t0_ms, fs_hz, samples}`: KY-039 100 Hz × 25 (quality 0.9), or the camera backup ~15 Hz (quality
0.6) · `raw/hub/face` per face at 5 Hz · `raw/sensors/distance` `{cm}` from the biggest face (`far_cm` when nobody is
there) · `raw/sensors/face_signs` `{duration_s, samples, coverage, smile_share?, smiles?, head_movement?}` once after a
Photo time window (Haar cascades; a sign that was not measured is absent; written 15 Nov. `demo/robot-test-plan.md` records one 5 s count from the board on 2026-11-15 through `make robot-bench`: the result came back after 5.2 s with 26 frames looked at. `docs/progress.md` has no entry for it, and no Photo time window in a conversation is recorded) · `health/sensors` `details{camera_ok, mcu_ok, mcu_fw, ppg, at_home}`.

## Map
```
sketch/sketch.ino     hall poller (200 Hz, hysteresis),
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
bench/<part>/         one-part tests: knock (part not fitted, D55), hall, light, ky039, buzzer (sketches), camera (python), link (MQTT)
```

## Extension points
- New sensor: a bench part first, then a sketch handler + `Bridge.notify`, a `provide` in `node.py`, and its message.
- Pulse source: `[unoq] ppg_source = auto|ky039|camera`. Light source: `[unoq] light_source = ky054|camera`. Both are
  `camera` in `config/kaiku.toml` and in the code's own defaults, so a missing config cannot fall back to a part
  that is not fitted.
- **The robot on its own** (no laptop in its path): this board's Linux side also runs the broker (mosquitto, a
  system service) and the hub (a system service, outside App Lab), next to this app. Runbook and
  `scripts/unoq_robot_setup.sh`: docs/robot-network-handover.md → "The robot on its own". This app's code does not
  change; only `MQTT_HOST` in its `.env` does, and App Lab's "run at startup" starts it at boot.

## Invariants
- Same topics + payloads as `sensors_sim`: the hub can't tell them apart.
- No frame, audio or image is stored, logged or sent. Only the numbers above leave the camera thread (docs/privacy.md).
- Photo time counts movements (smiles, head movement), never a feeling, and takes no picture (D52).
- PPG only between `ppg start` and `ppg stop`, at a stable `fs_hz` (fixed micros grid on the sketch).
- `alert` chime = device fault only, never mood or safety.
- A dead sketch or camera never kills the node: Bridge calls and the camera fail soft and show in `health/sensors`.

## Run standalone
On a laptop: `uv run python firmware/unoq-sensors/python/main.py --fake-bridge` (webcam stands in; `r`
sketch ready). On the board: `make unoq-app`, open `firmware/unoq-sensors` in App Lab (python + sketch), Run.
Without hardware: `make sim NODES=sensors`.

## Run with sim
`make broker && make hub` on the laptop, UNO Q on the same network (`MQTT_HOST` = laptop),
`make tail TOPIC='kaiku/v1/+/raw/#'`; drive the Atech side with `make sim NODES=head`.

## Config & env
`config/kaiku.toml [unoq]` (camera, distance, light and pulse routing), `sketch/config.h` (MCU numbers). Env:
`MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS`, `KAIKU_HOME_ID` (on the board: `~/ArduinoApps/kaiku-sensors/.env`).
With the broker on this board, `MQTT_HOST` is the board itself **as the app's container sees it**: the Docker bridge
address (`ip -4 addr show docker0`) or the board's Wi-Fi address; inside a container `localhost` is the container
itself, unless App Lab puts it on the host's network. Which one it is has not been tried on the board.

## Health signal
`health/sensors` every 5 s. `mcu_ok` false = the sketch doesn't answer `ping` (its version string names a missing
ADS1115 or buzzer; `ads-missing` is expected in this build, D54). `camera_ok` false = no camera (check the PD hub).

## Tests
`make test` runs `python/tests`. Bench: `make bench PART=firmware/unoq-sensors/bench/<knock|hall|light|ky039|buzzer|camera>`
(saved monitor log or `FROM=-`), then `bench/link` with `FROM=mqtt`.

## Known issues
Verified on the board (2026-11-14): the sketch compiles and runs (`arduino-cli compile --profile default -b
arduino:zephyr:unoq`, libraries pinned in `bench/sketch.yaml`); health ok with camera + sketch; faces, distance,
camera room light, buzzer chimes on `cmd.sensors`; works together with the Atech head over one broker.
History: knock taps from the KY-031 were also seen that day (bench 5 of 5); the part was removed afterwards (D55)
and this node reads no taps now.

Board setup that is **not in the repo** (redo it on a fresh board):
- `~/ArduinoApps/kaiku-sensors/.env`: `MQTT_HOST=<broker IP>` (the laptop on the hotspot),
  `MQTT_PORT=1883`, `KAIKU_HOME_ID=demo-aino`.
- **Default app** = `kaiku-sensors`, so it starts at boot: `arduino-app-cli properties set default
  ~/ArduinoApps/kaiku-sensors` (check with `properties get default`). Before that it never restarted after a power cut.
- Wi-Fi (NetworkManager): the hotspot is saved with `autoconnect-priority 10` and `autoconnect-retries 0` (retry
  forever); the venue's Wi-Fi is saved with autoconnect off. iPhone hotspots stop broadcasting when nobody
  is connected: keep the phone on Settings → Personal Hotspot while the UNO Q boots (~1-1.5 min to app running).

**Deployed (`docs/progress.md`, 2026-11-15 02:35 UTC):** the board had been running older code than the repo; the
repo's `python/` and `sketch/` were copied over ssh (the old app is kept on the board as `~/kaiku-sensors.bak`) and
the app started ("started successfully"). That entry does not record the sketch version the board reported
(`health/sensors` `details.mcu_fw`) nor a check that no `raw/head/tap` with `"src":"knock"` appears any more; before
that deploy such a tap came from the old app, not from a person. Not seen on the robot per that entry: the
camera's light going on with a yes and the spoken confirmation. Deploying, as it was done: `make unoq-app` on the laptop, copy `python/` and
`sketch/` into `~/ArduinoApps/kaiku-sensors/` over ssh (the board's `.env` stays), start the app (it rebuilds and
flashes the sketch), and check `health/sensors` `details.mcu_fw`. A new broker address is one line in that `.env`
(`MQTT_HOST`) and an app restart: commands in docs/robot-network-handover.md → "UNO Q".

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

Still to do: tune `distance_k_cm`; the KY-035 / KY-054 / KY-039 / KY-053 code paths are still in the sketch and the app but unused: none of those parts is fitted and none is planned (D39, D54; `HAS_HALL 0`).
