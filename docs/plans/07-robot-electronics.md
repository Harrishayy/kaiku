# Plan 07 — Robot electronics: Atech board + UNO Q, on the printed robot · 🟡 CURRENT (hardware track)

> Source: [`../kaiku_robot_electronics_specs.md`](../kaiku_robot_electronics_specs.md) (Xavier, reconciled with the
> printed CAD by Edwin). Decisions: **D31** (hardware, Edwin) and **D32** (software mapping) in
> [`../decisions.md`](../decisions.md). Ground truth for each fact lives where the root `AGENTS.md` says. This plan
> holds the mapping, build order, scope guard, risks and open questions, plus links:
> pins/power → [`hardware/wiring.md`](../../hardware/wiring.md) · parts → [`hardware/bom.md`](../../hardware/bom.md) ·
> physical build → [`hardware/assembly.md`](../../hardware/assembly.md) · messages → `contracts/` · Atech firmware →
> [`firmware/atech-head/AGENTS.md`](../../firmware/atech-head/AGENTS.md) · UNO Q →
> [`firmware/unoq-sensors/AGENTS.md`](../../firmware/unoq-sensors/AGENTS.md) · hub → [`hub/AGENTS.md`](../../hub/AGENTS.md) ·
> numbers → `config/kaiku.toml` `[robot]` `[unoq]` `[attention]` + each firmware's `config.h`.

## 1. What the robot is

Both boards sit in the **body**. The **head** holds the camera, the eyes display, the knob ear, the mic and the
KY-031. They are cabled down through the 19 mm hollow neck, and the head pans on a 12:40 gear (about ±100°).

| Node (envelope `source`) | Board | Parts | Talks |
|---|---|---|---|
| `head` | Atech 14-port (ESP32-S3), all 12 ports used | Speaker 1–2 · Color Display eyes 3–4 · Knob ear 5–6 · pan motor 7 · Mic 9–10 (v1 unused) · lid Button 11 · LED grids 13, 14 | MQTT over 2.4 GHz Wi-Fi (custom firmware, not Atech's cloud gateway) |
| `sensors` | Arduino UNO Q: STM32 sketch + Linux app | KY-031 knock (D2) · KY-035 hall (A1) · KY-054 light (A0) · KY-039 via KY-053 ADS1115 (`Wire`) · Modulino Buzzer (Qwiic/`Wire1`) · USB camera (PD hub) · LED matrix = hidden status | sketch ↔ app over the Bridge; app ↔ broker over MQTT |
| `hub` | laptop (today; D32) | broker, ritual, perception, Gemini Live voice (laptop audio in v1), uplink | MQTT + HTTPS |

```
 Atech board ──MQTT──┐                 ┌── cmd/head (eyes, chest, pan, gesture), cmd/sensors (chime, ppg)
 eyes, knob, button, │    Mosquitto     │
 LEDs, pan, speaker  ├──  on the hub  ──┤── hub (laptop): ritual, HRV, drum, presence, attention, voice ─HTTPS─▶ cloud
 UNO Q app ────MQTT──┘    laptop (D14)  │
   │ Bridge                            └── raw/head/* (ear, button, pan) · raw/sensors/* (hall, light, ppg, distance)
 UNO Q sketch: knock, hall, light, KY-039, buzzer          · raw/hub/face · raw/head/tap (knock) · health/*
```

The spec's proposed topics map onto the existing contracts. There is no new transport and no new topic family:

| Spec | Contract | Notes |
|---|---|---|
| `kaiku/head/knob` `{value 1..5, delta, pressed}` | `raw.head.ear` (unchanged) | ring light on while the eyes are `listening` (a question is open) |
| `kaiku/head/button` press/release/long | `raw.head.button {id: "head", pressed}` (new type) | long press ≥ 2 s = **"I'm not OK"**, the manual safety trigger (unchanged hub rule). Short press when idle starts a ritual. The spec's 800 ms "long" isn't used, so nothing competes with safety |
| `kaiku/head/eyes/cmd` `sleep/open/blink/…/concern` | `cmd.head eyes` = `Eyes` (`neutral happy sleepy wide listening thinking soft`) + `look{x,y}`; blinking is the firmware's own | `sleep`→`sleepy`, `open`→`neutral`/`wide`, `concern`→`soft` |
| `kaiku/head/leds/cmd` `{mode, bpm, color}` | `cmd.head chest: off\|breathe\|glow\|pulse` + `bpm` + `color` (unchanged) | |
| `kaiku/head/motor/cmd` gesture / speed | `cmd.head pan{target_deg}` · `home` · **`gesture: look_left\|look_right\|shake`** (new optional field) | open loop between homings; the firmware homes after every gesture |
| `kaiku/head/motor/state` | `raw.head.pan {deg (estimated), homed, moving}` | the UNO Q mutes knocks while `moving` |
| `on_home` (hall edge) | `raw.sensors.hall {at_home}` (unchanged) | **the Atech firmware subscribes** and brakes on it while homing (gives up after 2 s per direction) |
| `kaiku/head/status`, LWT | `health/head` (retained, LWT `down`) | |
| `kaiku/hub/heartbeat` 1 s, stop after 5 s | `health/hub` (every 5 s): the Atech firmware stops motor + speaker after 15 s of silence | `HUB_SILENCE_STOP_MS` |
| `buzz_pattern` | **`cmd.sensors chime: wake\|ok\|start_drum\|end_drum\|alert`** (new optional field) | `alert` = device fault only |
| `on_knock`, `drum_arm`, `on_drum_done` | `raw.head.tap {t_ms, src: knock}`; **`force` optional** | the hub computes the drum session (`tempo_bpm`, `regularity`, `taps`; `force_mean` null) |
| `pulse_arm`, `on_pulse_done` | `cmd.sensors ppg start\|stop` → `raw.sensors.ppg` batches (KY-039 100 Hz, quality 0.9) | the hub computes HR/HRV pre/post as today. **Camera pulse backup** (~15 Hz, quality 0.6) when `[unoq] ppg_source = auto` sees no clean KY-039 signal |
| `light_read` | `raw.sensors.light` every 10 s from the KY-054 | camera light (locked exposure) only if `[unoq] light_source = "camera"` |
| camera presence, face position | `raw.hub.face` 5 Hz + `raw.sensors.distance` (from face size) | the camera turns with the head, so `[attention] camera_on_head = true` makes pan targets relative to `raw.head.pan` |
| `mic/pcm`, `speaker/pcm` | **not in v1** (D32): voice on the laptop | §4 |

The ritual stays the hub's existing state machine (greet → Knob dial ×3 → breathing with chest LEDs + KY-039 →
knock drum → nudge → close). The spec's step lengths are starting values in `config/kaiku.toml [ritual]`.

## 2. Build order (each part alone first, then the board, then the hub)

`make bench-list` lists every part. `make bench PART=firmware/<board>/bench/<part> FROM=...` checks one part.

1. **Network spike (do first).** Both boards on one 2.4 GHz network with client-to-client traffic (else a phone
   hotspot). `make broker`; flash the Atech firmware; `make bench PART=firmware/atech-head/bench/link FROM=mqtt`.
2. **UNO Q parts alone:** `knock`, `hall` (copy `mid` into `HALL_MID`), `light`, `ky039` (KY-053 first), `buzzer`,
   `camera`. Then `make unoq-app`, run the app, and `bench/link`.
3. **Atech parts alone:** `display`, `knob` (set `KNOB_COUNTS_PER_STEP`), `button`, `leds`, `motor`, `speaker`, `mic`.
   Then flash `project.yaml` + `kaiku_link` and run `bench/link` (needs `make hub` and the UNO Q app for homing).
4. **Integrate:** `make hub` + both nodes, no sims. `make tail` shows the same topics as `make sim NODES=head,sensors`
   (the reference behaviour).
5. **Tune** on the real robot: pulse times, `MOTOR_DEG_PER_S_FULL`, `HALL_DELTA`, `distance_k_cm`, eye shapes, pan
   sign. Record the values in `docs/progress.md`.

## 3. Scope guard

**MUST (demo path):** network spike · Knob dial + lid button (safety long press) · knock drum · display eyes · chest
LED breathing · KY-039 HRV · camera face → presence/attention with head tracking · hall homing · chimes.
**STRETCH:** camera pulse fallback tuning · speaker RTTTL goodbye · PCM voice through the Atech board · mic level ·
YuNet detector · ring-light control · purr motor (needs a free port).

## 4. Future: the same messages, other placements (kept open by design)

- **Hub + broker on the UNO Q** (what the spec proposes). Written up on 14 Nov as a runbook with a setup script,
  **not yet run on the board**: [`../robot-network-handover.md`](../robot-network-handover.md) → "The robot on its own:
  no laptop" and `scripts/unoq_robot_setup.sh`. The hub is plain Python on MQTT and needs no sound device. The sensors
  app reaches the broker at the board's address as its App Lab container sees it, not `localhost`. Watch the RAM (2 GB
  with OpenCV + Live) and give the broker a password outside a bench.
- **Audio over MQTT through the Atech speaker and microphone.** Built on 14 Nov (D51), compiled, **not yet flashed or
  heard**: binary topics outside the envelope families, `kaiku/v1/<home>/audio/head/{mic,speaker}` (wire format:
  [`contracts/AGENTS.md`](../../contracts/AGENTS.md)); hub adapter `hub/kaiku_hub/live/head_audio.py`, selected by
  `[music] out` and `[voice] audio`; firmware `firmware/atech-head/kaiku_link/head_audio.*` (a 0.5 s ring that plays
  silence on underrun, microphone sent only while the hub holds it open and never while the speaker plays). The bus
  tools and the uplink skip `audio/` (root rules 5 and 9).

## 5. Risks

| Risk | Effect | Fallback |
|---|---|---|
| Venue Wi-Fi 5 GHz-only or client isolation | the Atech board can't reach the broker | phone hotspot; `MQTT_HOST_IP` fallback |
| No powered USB-C PD hub | the UNO Q stays in device mode: no camera | PD hub 5 V/3 A; presence then only from the button/knob |
| KY-039 weak through the cradle | flat PPG | shade it; `ppg_source = auto` → camera pulse |
| Hall edge reaches the Atech board late (Bridge → MQTT → Wi-Fi) | overshoots the front | slow `HOME_SPEED`; re-zero whenever the magnet passes |
| Motor drift between homings | head off-centre | home after every gesture; re-zero on any hall edge |
| Motor vibration trips the knock switch | false drum counts | the UNO Q mutes knocks while `moving`; `drum_sway = false` |
| Shared Atech rails (motor, speaker, display, LEDs) | brown-outs | 100 ms ramps; LED brightness ≤ 0.6; purr only with the motor idle |
| Cable bundle through the 19 mm neck | head can't turn freely | service loop; `pan_limit_deg = 100` |
| Atech C++ names differ from the docs | build errors | only the `project.yaml` files touch them; fix there (`atech info <module>`) |

## 6. Open questions

- [ ] Powered USB-C PD hub available? TPX00242 really 5 V / 3 A PD? (label)
- [ ] Venue Wi-Fi 2.4 GHz with client-to-client traffic? (else a hotspot)
- [ ] Atech button V2.0 (RGB LED)? If yes, light it while listening (not wired yet)
- [ ] KY-035 on A1 (analog, recommended) or D3 (the spec; only works if the 49E swing crosses the logic threshold)?
      Bench `hall` answers it.
- [ ] Pan sign: does `+target_deg` turn toward the image's right? (bench `motor` + `link`)
- [ ] Keep the Speaker (future voice through the robot) or drop it for the purr motor? We keep it for now (D32).
