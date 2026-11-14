# Robot Wi-Fi / MQTT handover (2026-11-14, updated end of day)

Point-in-time handover of the robot's network work (Atech head + UNO Q), for whoever picks up the robot next.
The ground truth stays where the root `AGENTS.md` puts it; this file explains what exists, what is verified, what we
tried, and what still fails, and links there for detail. Don't copy facts out of it; update the linked files instead.
Decisions: D44 (standalone head firmware), D48 (parts removed, own charger, hotspot).

## Status at a glance (end of 2026-11-14)

| | State | Verified on hardware |
|---|---|---|
| Broker | mosquitto on Edwin's Mac, `172.20.10.11:1883`, anonymous (`make broker`) | yes |
| Network | iPhone hotspot "Xavier’s iPhone" (curly ’), "Maximize Compatibility" on (2.4 GHz) | yes |
| UNO Q | `172.20.10.12`, app `kaiku-sensors` = default app (starts at boot); health, faces, distance, light | yes |
| Atech | `172.20.10.13`, standalone ritual + `kaiku_net`; health, pan, `cmd.head` eyes; UNO Q face woke it | yes |
| Taps (head orientation sensor → `raw.head.tap`, D49), head → UNO Q chimes | built in `kaiku_net` | taps and chime commands reach the broker; the buzzer sound **not yet confirmed** |
| Pan motor | turns only with the Atech on its own USB-C charger; port 13 on the MQTT firmware, 14 on the standalone (port 11: reverse only) | yes: both directions on port 14 (standalone, over MQTT) |
| Pulse | camera only (no KY-053, D48), `ppg_source = "camera"` | camera pulse is noisy (quality 0.6) |

Addresses are DHCP from the phone; they can change after a reconnect. Check with the broker log ("New client
connected from …") or on the boards.

## The picture

```
                 iPhone hotspot "Xavier’s iPhone" (2.4 GHz)
   ┌────────────────────────────────┐
   │ Mac 172.20.10.11               │
   │ mosquitto :1883 (make broker)  │◄────────── MQTT ───────────┐
   │ hub (make hub, optional)       │                             │
   └────────────────────────────────┘                             │
            ▲ MQTT (aiomqtt)                                      │ MQTT (PubSubClient)
   ┌────────┴──────────────────────┐                ┌─────────────┴──────────────────────┐
   │ UNO Q 172.20.10.12             │ raw.head.tap ─►│ Atech head 172.20.10.13             │
   │ kaiku-sensors App Lab app      │ raw.hub.face ─►│ standalone ritual + kaiku_net (D44) │
   │ knock, camera, buzzer          │◄─ cmd.sensors  │ own USB-C charger on port 8         │
   │ PD hub: Arduino PSU + camera   │◄─ raw.head.pan │                                     │
   └────────────────────────────────┘                └─────────────────────────────────────┘
```

All messages use the contract envelope (`contracts/AGENTS.md`), home `demo-aino`, topics
`kaiku/v1/demo-aino/<kind>/<name>`. Broker config: `config/mosquitto.conf`.

## Bringing it up (the order that works)

1. Phone: Personal Hotspot on, **Maximize Compatibility** on; stay on that settings screen while boards boot
   (an idle iPhone hotspot stops broadcasting).
2. Mac joins the hotspot; note its IP (`ipconfig getifaddr en0`), `make broker`.
3. UNO Q on its PD hub (Arduino PSU + camera). It joins the hotspot and starts the app by itself in ~1-1.5 min.
   If the Mac's IP changed: edit `MQTT_HOST` in `~/ArduinoApps/kaiku-sensors/.env` on the board and restart the app.
4. Atech on its own USB-C charger. Its broker IP and Wi-Fi are compiled in from `secrets.h` (below).
5. Watch: `mosquitto_sub -h localhost -t 'kaiku/v1/#' -v`. Expect `health/head` (`"firmware":"standalone"`) and
   `health/sensors` every 5 s, faces/distance from the UNO Q, `raw.head.pan` every 2 s.

Reaching the boards: UNO Q `ssh arduino@<ip>` (or `adb shell` over USB-C; if `adb devices` is empty run
`adb kill-server` and retry). The Atech only over USB data cable or MQTT.

## Atech head: two firmwares, one switch

| | Standalone (ACTIVE, D44) | MQTT firmware (next stage) |
|---|---|---|
| Folder | `firmware/atech-head/standalone/` | `firmware/atech-head/` (`kaiku_link/`) |
| Ritual runs on | the head (knob dials, breathing, drum) | the hub (head obeys `cmd.head`) |
| Network | `src/kaiku_net.{h,cpp}`: **verified on the board** | Wi-Fi + MQTT, **verified on the board** |
| Build / flash | `make atech-standalone [FLASH=1]` | `make atech-mqtt [FLASH=1]` |
| Docs | `firmware/atech-head/AGENTS.md`, D44 | same `AGENTS.md`, `kaiku_link/kaiku_link.h` |

Both read Wi-Fi and broker from `firmware/atech-head/kaiku_link/secrets.h` (copy `secrets.example.h`; gitignored,
never commit it). **It is per laptop:** whoever flashes builds with their own copy. Set all three: `WIFI_SSID` exactly
as the phone shows it (curly ’ included), `WIFI_PASS`, `MQTT_HOST_IP` = the broker laptop's hotspot IP. The Atech
joins **2.4 GHz only**. Flash at 115200 with `--no-stub` (the make targets do it); with two boards on USB, pass the
Atech's port explicitly (`ATECH_PORT=/dev/cu.usbmodem…`), the target picks the first one it finds.

### kaiku_net (standalone): what it sends and hears

Built from `kaiku_link`'s network code (same envelope, UUIDv7, NTP UTC timestamps, 1 → 10 s backoff, retained
`health/head` with last will `down`). Hooks in `standalone/src/main.cpp` are marked `// kaiku_net` (13 lines), so
they can be re-applied when the website agent sends a new `main.cpp`.

| Direction | Message | What happens | Seen |
|---|---|---|---|
| UNO Q → head | `raw.hub.face` (camera) | from idle, wakes Kaiku (greeting) | yes |
| head → hub | `raw.head.tap {t_ms, force, src: imu}` (orientation sensor; the KY-031 is removed, D49) | counts as a drum tap on the head; from idle, wakes Kaiku | yes (taps on the broker, wake) |
| hub → head | `cmd.head` eyes / pan / gesture / purr | queued as the same actions as the USB-serial commands | eyes: yes |
| head → UNO Q | `cmd.sensors {chime}` | `wake` on greeting, `start_drum` / `end_drum` (UNO Q buzzer) | not yet |
| head → UNO Q | `raw.head.pan {moving}` | on change + every 2 s | yes |
| head → all | `health/head` (5 s, retained), `raw.head.ear` | status (`details.step`, `firmware`), dial values + presses | health: yes |

### kaiku_link (MQTT firmware): fixed today, verified on the board

- `tick()` read the clock before `mqtt.loop()`; stamps set while handling messages wrapped the unsigned difference
  (~49 days): hub "silent" after every heartbeat, every motor segment skipped. Now read after the network loop.
- `Serial.setTxTimeoutMs(0)`: with no USB host reading, `println` stalled the loop and MQTT timed out.
- Softer motor start (ramp 400 ms, gesture speed 110); pan reported as soon as a move starts.
- Verified with the UNO Q on one broker: button, knob press + turns, eyes on `cmd.head`, pan commands, no Wi-Fi drops.

## UNO Q (kaiku-sensors App Lab app)

Details and traps: `firmware/unoq-sensors/AGENTS.md` → Known issues. In short:
- Broker address: `.env` in the app folder **on the board** (`MQTT_HOST`, `MQTT_PORT`, `KAIKU_HOME_ID`).
- Default app = `kaiku-sensors` (starts at boot). Wi-Fi: hotspot preferred and retried forever; venue Wi-Fi saved but
  not auto-joined.
- No OpenCV/numpy in `python/requirements.txt` (App Lab ships its own OpenCV). Camera found by its stable by-id name.
- **Open bug:** without a camera (UNO Q on the Mac's USB instead of its hub) the app quits instead of reporting
  `camera_ok: false`.

## Testing without the hub

- Watch everything: `mosquitto_sub -h localhost -t 'kaiku/v1/#' -v` (or `make tail TOPIC=...`).
- Send a command: `mosquitto_pub -h localhost -t 'kaiku/v1/demo-aino/cmd/head' -m '{"v":1,"id":"01a1d9e7-0000-7000-8000-000000000001","ts":"2026-11-14T12:00:00.000Z","home_id":"demo-aino","source":"hub","type":"cmd.head","payload":{"eyes":"happy"},"sim":false}'`
  (worked today), or from Python with `kaiku_contracts.Bus("sim")` + `bus.publish(type, payload, source="hub")`;
  `source` must be a real node name (`head|sensors|hub|...`).
- The MQTT firmware moves the motor only while it hears `health/hub`: without `make hub`, publish `health`
  `{status: ok}` as `hub` every few seconds.
- The standalone over USB: plain-text commands without a value work (`greet`, `chirp`, `next`); with a value they
  must be JSON lines (`{"action":"pan","value":"100"}`). Opening the serial port resets the board.

## What we tried today, and what it taught us

| Symptom | Tried | Outcome |
|---|---|---|
| Pan motor never turns, not even a hum | 2 motors, ports 13/9/11, 2 cables, Atech's own `atech send motor_speed` | **Power**: turns only with the Atech on its own USB-C charger (D48) |
| Motor turned one way only | port 11 | GPIO44 is UART0 RX: use port 13 (MQTT firmware) or 14 (standalone) |
| Head ignored every move, "hub silent" | read `tick()` | clock read before `mqtt.loop()` (fixed in `kaiku_link`) |
| Standalone missed knob presses without a laptop | muted the Atech drivers' debug prints (`build.sh`) | runs untethered |
| Both boards lost the broker every 1-2 min | watched the broker log: both dropped within seconds of each other | venue Wi-Fi; moved to the iPhone hotspot (D48): no drops seen since |
| UNO Q silent after power changes | — | app didn't autostart: now the default app |
| UNO Q "doesn't join Wi-Fi" on external power | — | idle iPhone hotspot sleeps; retries forever now, venue Wi-Fi not auto-joined |
| UNO Q rebooted when the Atech was unplugged | — | shared supply: separate supplies (D48) |
| Mac can't see a board over USB | other cables / ports, `adb kill-server` | charge-only cables; `adb kill-server` brought the UNO Q back |
| Atech flashed elsewhere didn't join the hotspot | — | that laptop's `secrets.h`; set SSID/pass/broker IP there |

## Still struggling with / open items

1. **Knock → drum and the chimes** through `kaiku_net` haven't been watched end to end yet (knock on the UNO Q while
   the head is idle: greeting + wake chime; in DRUM knocks count).
2. **UNO Q app quits without a camera** instead of reporting `camera_ok: false`.
3. **The laptop is still in the loop** (broker). To take it out: run mosquitto on the UNO Q, point both boards at it
   (`firmware/unoq-sensors/AGENTS.md`, plan 07 §4).
4. Port the standalone's ritual feel into `kaiku_link` behind the contracts (hub keeps the ritual, D32/D44); ritual
   results (mood/energy/sleep, drum) are not sent as `obs.*` yet (USB serial only).
5. Knob step size (`KNOB_COUNTS_PER_STEP`, `bench/knob`); pinion D-hole vs the real 3 mm shaft; camera pulse quality.
6. Change the UNO Q's `arduino` password: it was pasted into a chat on 2026-11-14.

## Hardware changes today (CAD + parts)

- Knob cap: round bore Ø9.65 × 16 deep (cap Ø22 × 18). DC motor measured 19.5 × 19.5 × 39 + 9 mm shaft:
  `pan_motor_mount` and `purr_sleeve` resized (Ø20.1 inside). Reprint plate (knob cap + both sleeves): ~23 min / 12 g
  on P1S or P2S. See `hardware/dimensions.md`.
- Removed: KY-053 (and so the KY-039), LED grids (D48); earlier KY-054 and KY-035 (D35).
