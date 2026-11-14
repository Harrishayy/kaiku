# Robot Wi-Fi / MQTT handover (2026-11-14)

Point-in-time handover of the robot's network work (Atech head + UNO Q), for whoever picks up the robot next.
The ground truth stays where the root `AGENTS.md` puts it; this file explains what exists, what is verified, and the
traps, and links there for detail. Don't copy facts out of it; update the linked files instead.

## The picture

```
              laptop (for now)                         venue Wi-Fi, 2.4 GHz
   ┌────────────────────────────────┐
   │ mosquitto :1883  (make broker) │◄──────────── MQTT ───────────┐
   │ hub (make hub, optional)       │                               │
   └────────────────────────────────┘                               │
            ▲                                                       │
            │ MQTT (aiomqtt, kaiku_contracts.Bus)                   │ MQTT (PubSubClient)
   ┌────────┴──────────────────────┐                 ┌──────────────┴─────────────────────┐
   │ UNO Q  kaiku-sensors App Lab   │                 │ Atech head (ESP32-S3)              │
   │ knock, camera faces/distance/  │  raw.head.tap ─►│ standalone ritual + kaiku_net      │
   │ light, buzzer, KY-039 pulse    │  raw.hub.face ─►│ (D44)  or  kaiku_link (next stage) │
   │                                │◄─ cmd.sensors   │                                    │
   │                                │◄─ raw.head.pan  │                                    │
   └────────────────────────────────┘                 └────────────────────────────────────┘
```

All messages use the contract envelope (`contracts/AGENTS.md`), home `demo-aino`, topics
`kaiku/v1/demo-aino/<kind>/<name>`. The broker runs anonymous on the laptop (`config/mosquitto.conf`).

## Atech head: two firmwares, one switch

| | Standalone (ACTIVE, D44) | MQTT firmware (next stage) |
|---|---|---|
| Folder | `firmware/atech-head/standalone/` | `firmware/atech-head/` (`kaiku_link/`) |
| Ritual runs on | the head (knob dials, breathing, drum) | the hub (head obeys `cmd.head`) |
| Network | `src/kaiku_net.{h,cpp}`: **built, not yet flashed or tested** | Wi-Fi + MQTT, **verified on the board** |
| Build / flash | `make atech-standalone [FLASH=1]` | `make atech-mqtt [FLASH=1]` |
| Docs | `firmware/atech-head/AGENTS.md`, `docs/decisions.md` D44 | same `AGENTS.md`, `kaiku_link/kaiku_link.h` |

Both read Wi-Fi and broker settings from the one gitignored file `firmware/atech-head/kaiku_link/secrets.h`
(copy `secrets.example.h`; never commit it, this is a public repo). `MQTT_HOST_IP` is the laptop's IP on the venue
Wi-Fi (mDNS is usually blocked there). The Atech joins **2.4 GHz only**.

### kaiku_net (standalone): what it sends and hears

Built from `kaiku_link`'s network code (same envelope, UUIDv7, NTP UTC timestamps, 1 → 10 s backoff, retained
`health/head` with last will `down`). Hooks in `standalone/src/main.cpp` are marked `// kaiku_net` (13 lines), so they
can be re-applied when the website agent sends a new `main.cpp`.

| Direction | Message | What happens |
|---|---|---|
| UNO Q → head | `raw.head.tap` (knock sensor) | counts as a drum tap; from idle, wakes Kaiku (greeting) |
| UNO Q → head | `raw.hub.face` (camera) | from idle, wakes Kaiku |
| hub → head | `cmd.head` eyes / pan / gesture / purr | queued as the same actions as the USB-serial commands |
| head → UNO Q | `cmd.sensors {chime}` | `wake` on greeting, `start_drum` / `end_drum` around drumming (UNO Q buzzer) |
| head → UNO Q | `raw.head.pan {moving}` | on change + every 2 s; the UNO Q ignores knocks while the motor runs |
| head → all | `health/head` (5 s, retained), `raw.head.ear` | status (`details.step`, `firmware: standalone`), dial values + presses |

No Wi-Fi or broker never blocks the ritual: messages are just not sent. `build.sh` copies `secrets.h` into the
(gitignored) build and adds PubSubClient + ArduinoJson.

**First test to run:** flash (`make atech-standalone FLASH=1`, USB data cable), put it back on its own charger, then
`mosquitto_sub -h localhost -t 'kaiku/v1/#' -v`: expect `health/head` with `"firmware":"standalone"`. Knock on the UNO Q's
sensor while idle → greeting on the head + wake chime on the UNO Q buzzer. In DRUM, knocks count as taps.

### kaiku_link (MQTT firmware): fixed today, verified on the board

- `tick()` read the clock **before** `mqtt.loop()`: stamps set while handling messages were newer than `now`, so the
  unsigned difference wrapped (~49 days). Symptoms: hub "silent" after every heartbeat, every motor segment skipped.
  Now the clock is read after the network loop.
- `Serial.setTxTimeoutMs(0)`: with no USB host reading, `println` stalled the loop and MQTT keep-alive timed out.
- Softer motor start (ramp 400 ms, gesture speed 110) and pan reported as soon as a move starts.
- Verified together with the UNO Q on one broker: button, knob press + turns, eyes on `cmd.head`, pan commands run,
  no Wi-Fi drops. Open: knob steps feel short (`KNOB_COUNTS_PER_STEP`, `bench/knob`).

## UNO Q (kaiku-sensors App Lab app)

- Broker address comes from `.env` in the app folder **on the board** (`~/ArduinoApps/kaiku-sensors/.env`:
  `MQTT_HOST`, `MQTT_PORT`, `KAIKU_HOME_ID`); see `firmware/unoq-sensors/AGENTS.md` → Config & env.
- `python/requirements.txt` must **not** list OpenCV or numpy: App Lab's container ships its own OpenCV, and asking for
  another fails the whole install (then aiomqtt is missing and nothing publishes).
- Camera: `camera_index = -1` finds it by its stable `/dev/v4l/by-id` name (the board renumbers video0-3 between
  boots); exposure lock falls back to OpenCV when `v4l2-ctl` is missing (the container).
- **The app does not restart by itself after a power cut.** Over SSH:
  `ssh arduino@<uno-q-ip> 'cd ~/ArduinoApps/kaiku-sensors && arduino-app-cli app start .'`
  (its IP can change; it was 10.0.41.254).
- Verified on the broker: health ok (camera + sketch), knock taps, faces + distance, room light, chimes on `cmd.sensors`.

## Testing without the hub

- Watch everything: `mosquitto_sub -h localhost -t 'kaiku/v1/#' -v` (or `make tail TOPIC=...`).
- Send a command from Python with `kaiku_contracts.Bus("sim")` and `bus.publish(type, payload, source="hub")`:
  `source` must be a real node name (`head|sensors|hub|...`), not `tester`.
- The MQTT firmware moves the motor only while it hears `health/hub` (watchdog). Without `make hub`, publish
  `health` `{status: ok}` as `hub` every few seconds.
- The standalone over USB: plain-text commands without a value work (`greet`, `chirp`, `next`); commands with a value
  must be JSON lines: `{"action":"pan","value":"100"}`. Opening the serial port resets the board.

## Hardware and power traps (cost us hours)

- **The motor needs the Atech on its own USB-C charger (port 8).** The hub's charge-only port and the Mac's USB run
  the logic but the motor never turns, not even a hum.
- On **port 11** only reverse turns: its forward line is GPIO44 (UART0 RX). Port 13 has no such conflict, but the
  standalone puts its orientation sensor there.
- Flashing the Atech from the Mac works only at 115200 baud with `--no-stub` (the make targets do it).
- Atech driver debug prints stalled the standalone without a USB host; `build.sh` mutes them (`VERBOSE=1` keeps them).
- The broker is on the laptop, so the robot still needs the laptop **on the network** (not plugged in). To drop it,
  run mosquitto on the UNO Q and point both boards at it (`firmware/unoq-sensors/AGENTS.md`, plan 07 §4).

## Open items

1. Flash and test `kaiku_net` with the UNO Q (above).
2. Port the standalone's ritual feel into `kaiku_link` behind the contracts (the hub keeps the ritual, D32/D44).
3. Ritual results (mood/energy/sleep, drum) are not sent as `obs.*` yet: the standalone only emits them on USB serial.
4. Knob step size; KY-039 pulse retest in the printed cradle.
