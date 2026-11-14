# Robot Wi-Fi / MQTT handover (2026-11-14, updated end of day)

Point-in-time handover of the robot's network work (Atech head + UNO Q), for whoever picks up the robot next.
The ground truth stays where the root `AGENTS.md` puts it; this file explains what exists, what is verified, what we
tried, and what still fails, and links there for detail. Don't copy facts out of it; update the linked files instead.
Decisions: D44 (standalone head firmware), D54 (parts removed, own charger, hotspot).

## Status at a glance (end of 2026-11-14)

| | State | Verified on hardware |
|---|---|---|
| Broker | mosquitto on Edwin's Mac, `172.20.10.11:1883`, anonymous (`make broker`) | yes |
| Network | iPhone hotspot "Xavier’s iPhone" (curly ’), "Maximize Compatibility" on (2.4 GHz) | yes |
| UNO Q | `172.20.10.12`, app `kaiku-sensors` = default app (starts at boot); health, faces, distance, light | yes |
| Atech | `172.20.10.13`, standalone ritual + `kaiku_net`; health, pan, `cmd.head` eyes; UNO Q face woke it | yes |
| Taps (head orientation sensor → `raw.head.tap`, D55), head → UNO Q chimes | built in `kaiku_net` | taps and chime commands reach the broker; the buzzer sound **not yet confirmed** |
| Pan motor | turns only with the Atech on its own USB-C charger; port 13 on the MQTT firmware, 14 on the standalone (port 11: reverse only) | yes: both directions on port 14 (standalone, over MQTT) |
| Pulse | camera only (no KY-053, D54), `ppg_source = "camera"` | camera pulse is noisy (quality 0.6) |

Addresses are DHCP from the phone; they can change after a reconnect. Check with the broker log ("New client
connected from …") or on the boards.

**Read this first: what has run and what has not.** The part marked *verified on the board* was run on the robot on
2026-11-14 with the broker on a laptop: Edwin's standalone firmware (`atech-head-standalone-0.1.0`: no display, taps
from the orientation sensor, motor on port 14). Written the same day on a Mac with **no board connected** and put
on top of that firmware in the evening (`…-0.4.0`): sound through the head's speaker, the head's microphone, the
hub leading the drum step. It compiles, its logic was tested without hardware, and **none of it has been flashed
or heard**. "Tonight on the laptop" below is the order to find out, and how to go back to `0.1.0`. The section
"The robot on its own" is future work and not for the demo.

## The picture

Verified on the board (broker and hub on a laptop):

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

Where it is going (not run yet): the robot's own computer is the UNO Q's Linux side. No laptop or phone is in the
robot's path; the only thing outside the robot is the Wi-Fi's way to the internet.

```
   UNO Q (in the body), Linux side                                        Atech head (ESP32-S3)
   ┌─────────────────────────────────────────┐   Wi-Fi, 2.4 GHz    ┌───────────────────────────────────┐
   │ mosquitto :1883            (systemd)    │◄──── MQTT ─────────►│ ritual, eyes, knob, motor         │
   │ hub: ritual record, tap it back, voice  │  cmd.head (hold,    │ speaker  ◄─ audio/head/speaker    │
   │      (systemd, kaiku-hub.service)       │   sway, mic)        │ microphone ─► audio/head/mic      │
   │ kaiku-sensors app (App Lab container)   │  raw.head.tap/ear   │ motion-sensor taps                │
   │   + STM32 sketch: knock, buzzer, camera │  audio frames       │                                   │
   └───────────────┬─────────────────────────┘                     └───────────────────────────────────┘
                   │ HTTPS / WSS out: Gemini (Live voice, songs), the Kaiku cloud; NTP
                   ▼ venue Wi-Fi → internet
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
| Talking with Kaiku (Live voice through the head's speaker and microphone) | **yes, since 2026-11-14 evening:** the hub opens the conversation when she presses the ear at the head's greeting (a press the hub saw; never for a ritual it joined mid-way), Kaiku says each step's line and answers her, and it closes with the head's ritual. Shown with the real model against the firmware's twin, not on the board | yes: when she starts the ritual (the hub drives it) |
| Tap it back in the drum step | yes (`cmd.head {drum: hold}`); the microphone is closed for the whole game | yes; the same |
| Network | `src/kaiku_net.{h,cpp}`: **verified on the board** (as `0.1.0`) | Wi-Fi + MQTT, **verified on the board** |
| Sound for the hub (speaker and microphone as PCM over MQTT), drum hold, sway | on top of the verified firmware (`0.4.0`): **built, never run** | the same streams: **built, never run** |
| For the robot as it stands (no display, taps from the orientation sensor, motor on port 14) | **yes** | **no**: it draws on a display on ports 3-4, drives the motor on port 13 and has no orientation-sensor code (no taps) |
| `cmd.head {show: help}` (the hub's crisis path) | no display: nothing is shown; the ritual ends quietly, the microphone shuts, the head stays calm, and health says `help_shown: false`, `help_screen: "none"` | the helpline's name, number and the emergency number on its display: **built, never seen** |
| Open microphone shown by | the ear ring turning blue, **if it can be seen on the assembled head: not checked** | ear ring + an orange dot on the display |
| Build / flash | `make atech-standalone [FLASH=1]` | `make atech-mqtt [FLASH=1]` |
| Docs | `firmware/atech-head/AGENTS.md`, D44 | same `AGENTS.md`, `kaiku_link/kaiku_link.h` |

Both read Wi-Fi and broker from `firmware/atech-head/kaiku_link/secrets.h` (copy `secrets.example.h`; gitignored,
never commit it). **It is per laptop:** whoever flashes builds with their own copy. Set all three: `WIFI_SSID` exactly
as the phone shows it (curly ’ included), `WIFI_PASS`, `MQTT_HOST_IP` = the broker laptop's hotspot IP. The Atech
joins **2.4 GHz only**. Flash at 115200 with `--no-stub` (the make targets do it); with two boards on USB, pass the
Atech's port explicitly (`ATECH_PORT=/dev/cu.usbmodem…`), the target picks the first one it finds.

### kaiku_net (standalone): what it sends and hears

Built from `kaiku_link`'s network code (same envelope, UUIDv7, NTP UTC timestamps, 1 → 10 s backoff, retained
`health/head` with last will `down`). Hooks in `standalone/src/main.cpp` are marked `// kaiku_net` (25 lines), so
they can be re-applied when the website agent sends a new `main.cpp`. The full list of messages is the header of
`standalone/src/kaiku_net.h`. "Seen" = on the robot; the rows that say *built* arrived with `0.4.0`.

| Direction | Message | What happens | Seen |
|---|---|---|---|
| UNO Q → head | `raw.hub.face` (camera) | from idle, wakes Kaiku (greeting) | yes |
| head → hub | `raw.head.tap {t_ms, force, src: imu}` (orientation sensor; the KY-031 is removed, D55) | counts as a drum tap on the head; from idle, wakes Kaiku | yes (taps on the broker, wake) |
| hub → head | `cmd.head` eyes / pan / gesture / purr | queued as the same actions as the USB-serial commands | eyes: yes |
| head → UNO Q | `cmd.sensors {chime}` | `wake` on greeting, `start_drum` / `end_drum` (UNO Q buzzer) | not yet |
| head → UNO Q | `raw.head.pan {moving}` | on change + every 2 s | yes |
| head → all | `health/head` (5 s, retained), `raw.head.ear` | status (`details.step`, `firmware`, `motor_pins`), dial values + presses | health: yes |
| head → all | `health/head` also at once on every step change, with `drum_held`, `loop_max_ms`, `audio{rx, drop, dry, mic_open, mic_tx, mic_drop, mic_peak}`, `help_shown: false`, `help_screen: "none"`, `calm` | the hub follows `details.step`; the counters are how to judge the sound | built |
| hub → head | `audio/head/speaker` (binary: 640 bytes = 20 ms, s16le mono 16 kHz) | played on the head's speaker; a zero-length message drops what is buffered. While it plays (and 150 ms after): no tone of the head's own, no taps, no wake by sound | built |
| hub → head | `cmd.head {mic: open}`, at least every 3 s / `{mic: close}` | microphone frames flow / stop; 10 s without `open` closes it. The ear ring turns blue | built |
| head → hub | `audio/head/mic` (binary, same format) | the microphone, only while held open and the speaker is quiet (and 250 ms after) | built |
| hub → head | `cmd.head {drum: hold}`, at least every 3 s | **only in the head's drum step**: the head stays in it, its own drum clock is off, no tap tones. 10 s without one and its own clock decides again | built |
| hub → head | `cmd.head {pan_mode: sway, bpm}` with a hold | one short push a beat, left then right; any other `pan_mode` stops it and the head goes half a push back | built |
| hub → head | `cmd.head {drum: end}` | the head ends its drum step the usual way (`chime: end_drum`, its two-note chirp, step `done`) | built |
| hub → head | `cmd.head {show: help}` / `{show: none}` | no display, nothing shown: the ritual ends quietly (no chime, no done step), the microphone shuts, the motor stands still, and the head stays calm (no wake by face, sound or pat; no pan, gesture, purr) until `none`, an ear press or 10 minutes | built |

### kaiku_link (MQTT firmware): fixed today, verified on the board

- `tick()` read the clock before `mqtt.loop()`; stamps set while handling messages wrapped the unsigned difference
  (~49 days): hub "silent" after every heartbeat, every motor segment skipped. Now read after the network loop.
- `Serial.setTxTimeoutMs(0)`: with no USB host reading, `println` stalled the loop and MQTT timed out.
- Softer motor start (ramp 400 ms, gesture speed 110); pan reported as soon as a move starts.
- Verified with the UNO Q on one broker: button, knob press + turns, eyes on `cmd.head`, pan commands, no Wi-Fi drops.
- **Not for the robot as it stands** (D54, D55): it expects the display (ports 3-4) and the motor on port 13, and has
  no orientation-sensor code. It still builds (`make atech-mqtt`) and carries the sound streams and the help screen
  (built, never run) for the day the display is back.

## UNO Q (kaiku-sensors App Lab app)

Details and traps: `firmware/unoq-sensors/AGENTS.md` → Known issues. In short:
- Broker address: `.env` in the app folder **on the board** (`MQTT_HOST`, `MQTT_PORT`, `KAIKU_HOME_ID`).
- Default app = `kaiku-sensors` (starts at boot). Wi-Fi: hotspot preferred and retried forever; venue Wi-Fi saved but
  not auto-joined.
- No OpenCV/numpy in `python/requirements.txt` (App Lab ships its own OpenCV). Camera found by its stable by-id name.
- **Open bug:** without a camera (UNO Q on the Mac's USB instead of its hub) the app quits instead of reporting
  `camera_ok: false`.
- **A new broker address** (another laptop, or the same one after the hotspot gave it a new address): only
  `MQTT_HOST` in `~/ArduinoApps/kaiku-sensors/.env` on the board changes. Over Wi-Fi: `ssh arduino@<UNO Q address>`;
  over USB-C: `adb shell` (`adb kill-server` first if `adb devices` is empty). Then, on the board:
  `sed -i 's/^MQTT_HOST=.*/MQTT_HOST=<broker>/' ~/ArduinoApps/kaiku-sensors/.env`, check it with
  `grep MQTT_HOST ~/ArduinoApps/kaiku-sensors/.env`, and restart the app. From the notes of 2026-11-14:
  `arduino-app-cli app restart` stopped the app and then failed with "app is running", and `app start` afterwards
  worked (`arduino-app-cli app start ~/ArduinoApps/kaiku-sensors`; Arduino's own form is `user:kaiku-sensors`).
  Expect `health/sensors` on the new broker within a minute. The `sed` line was not run on the board by its author.
- **The sketch `unoq-sketch-0.3.0` (no knock switch, D55) is in the repo but not on the board**: the board was off
  the network when it was written, so it still runs the app from earlier that day, with the knock code for a switch
  that is no longer fitted. To deploy, as it was done for the earlier version: on the laptop `make unoq-app`
  (copies the contracts and `config/kaiku.toml` into `python/vendor`), copy `firmware/unoq-sensors/python` and
  `sketch` into `~/ArduinoApps/kaiku-sensors/` on the board over ssh (its `.env` is not in those two folders and
  stays), then start the app, which rebuilds and flashes the sketch. Check: `health/sensors` `details.mcu_fw` names
  `unoq-sketch-0.3.0`, and no `raw.head.tap` with `"src":"knock"` ever appears. Until then a `"src":"knock"` tap
  on the broker comes from the old app, not from a person.

## The robot on its own: no laptop

**Future work, not for the demo** (decided 2026-11-14 evening): for the demo the broker and the hub stay on a laptop
on the hotspot ("Tonight on the laptop" below). Nothing in this section has been run.

**Status: written 2026-11-14 from the repo and Arduino's documentation. Not one step here has been run on the
board.** Each step says what to expect, so the first run is also the test. What was checked on a Mac instead is
said where it applies.

What Arduino documents and this relies on (source: `github.com/arduino/docs-content`, folder
`content/hardware/uno/boards/uno-q/tutorials/`, read 2026-11-14; rendered at `docs.arduino.cc/tutorials/uno-q/<name>/`):
- *User manual* (`first-steps/user-manual`): the Linux side has dual-band Wi-Fi (2.4 / 5 GHz) and 2 GB or 4 GB of
  RAM; `sudo nmcli d wifi connect <SSID> password <PASSWORD>` joins a network from a shell; "Running an App at
  Startup": the App Lab switch, or `arduino-app-cli properties set default user:<NAME_OF_YOUR_APP>`.
- *Debian guide* (`linux/debian-guide`): Debian with the `trixie` package sources (Debian 13), user `arduino`,
  `sudo apt install <package>`, `ssh arduino@<boardname>.local` once App Lab's first setup has turned SSH on, apps
  in `/home/arduino/ArduinoApps/`, `arduino-app-cli app start user:<app>`.
- *SSH* (`linux/ssh`): when the network blocks mDNS, use the board's IP (`hostname -I` on the board);
  `scp -rp <folder> arduino@<boardname>.local:/home/arduino/ArduinoApps/` copies an app.
- *Remote access* (`linux/remote-access`): of the addresses `hostname -I` prints, the `172.x.x.x` ones "belong to
  Docker's internal networks, not your LAN".

Not from Arduino, from this repo and general Debian practice: that mosquitto and a systemd service are the way to run
the broker and the hub there, and that the App Lab app sits in a container (this repo's own notes from the board).

| Piece | Where it runs | Starts at boot by | Finds the broker at |
|---|---|---|---|
| mosquitto | UNO Q, Debian package | its own systemd unit | listens on :1883, all interfaces (`/etc/mosquitto/conf.d/kaiku.conf`) |
| hub | UNO Q, `~/kaiku/.venv` | `kaiku-hub.service` (`Restart=always`) | `MQTT_HOST=localhost` in `~/kaiku/.env` |
| sensors app | UNO Q, App Lab container | App Lab "run at startup" (default app) | `MQTT_HOST` in the app's `.env`: the board **as the container sees it** (Docker bridge address, else the Wi-Fi address) |
| head | Atech ESP32-S3 | its firmware | `MQTT_HOST "<boardname>.local"` (mDNS), then `MQTT_HOST_IP` in `secrets.h` |

The key: `GEMINI_API_KEY` lives in **`~/kaiku/.env` on the board**, mode 600. `.env` is gitignored and the script
never reads, writes or prints its value. Nothing else on the robot holds a key (the head and the sensors app have
none).

The network the robot needs (venue Wi-Fi): the head and the UNO Q on the **same** network with client-to-client
traffic allowed, 2.4 GHz for the head; from the UNO Q out to the internet: HTTPS and WebSocket to Google's Gemini API
(Live voice, the songs) and to the Kaiku cloud, DNS, and NTP. The head also needs NTP (`pool.ntp.org`): until it has
the time it sends no envelope (audio frames still flow).

Python: the board's own Python (Debian 13 ships 3.13) is not used. `uv` installs Python 3.12 (`.python-version`) and
only the hub's packages (`uv sync --package kaiku-hub --extra live --no-dev --frozen`: not the cloud, tools or tests).
Checked on a Mac: that command builds a working hub from exactly the files in step 2 (`python -m kaiku_hub.main
--help` runs), and all 33 locked packages have a ready-made wheel for 64-bit ARM Linux on Python 3.12 and 3.13 (numpy
2.5.4, scipy 1.18.1, pydantic-core, cryptography, cffi among them), so nothing should need compiling on the board.
The hub uses no sound device there (`[voice] audio = head`, `[music] out = head`); `libportaudio2` is installed only
so that importing `sounddevice` cannot fail.

Steps (every one: **not run on the board**):

1. **A shell on the board.** `ssh arduino@<boardname>.local` from any computer on the same Wi-Fi (or a keyboard and
   screen on the board). Setting up needs this once; running needs none. If the board is not on the Wi-Fi yet:
   `sudo nmcli d wifi connect <SSID> password <PASSWORD>`, typed on the board, never into a file here.
   Expect: a prompt. Fails: mDNS blocked → use the IP (`hostname -I` on the board, or the router's list).
2. **Copy the hub to the board** (about 1 MB; from the repo root on a computer, with this working tree):
   ```bash
   COPYFILE_DISABLE=1 tar --exclude=__pycache__ --exclude=.venv --exclude='*.sqlite' -czf - contracts hub cloud \
       config pyproject.toml uv.lock .python-version .env.example scripts/unoq_robot_setup.sh \
     | ssh arduino@<boardname>.local 'mkdir -p ~/kaiku && tar -xzf - -C ~/kaiku'
   ```
   `cloud/` goes along only because the workspace file names it; it is not installed. `.env` is not in the list
   (checked: the archive holds no `.env` and no `secrets.h`).
3. **Look before touching:** `cd ~/kaiku && ./scripts/unoq_robot_setup.sh check`. Changes nothing. Expect `arm64`,
   a Wi-Fi address, `Gemini API reachable: HTTP 404` or another HTTP code (any code means the internet is there),
   memory and disk figures (the install needs about 0.5 GB of disk).
4. **Install:** `./scripts/unoq_robot_setup.sh install` (asks for the sudo password; minutes the first time). It
   installs mosquitto and gives it a Wi-Fi listener, installs uv and the hub's packages, writes three settings into
   `.env` (`MQTT_HOST=localhost`, `KAIKU_VOICE_AUDIO=head`, `KAIKU_MUSIC_OUT=head`), and installs and starts
   `kaiku-hub.service`. Expect `hub imports fine`, then the status block: `active` twice and a `:1883` listener.
   Fails at `uv sync`: read the error; it is the internet, the disk, or a package without an ARM wheel after all.
5. **The key and the record:** `nano ~/kaiku/.env` on the board and add `GEMINI_API_KEY`, `KAIKU_HOME_ID` (the
   person's record), `KAIKU_HUB_ROBOT_HOME_ID=demo-aino`, `KAIKU_CLOUD_URL`, `KAIKU_HOME_TOKEN`, `KAIKU_VOICE=gemini`,
   `KAIKU_MUSIC=lyria` (names: `.env.example`; what they do: `hub/AGENTS.md` → Config & env). Or copy your own once:
   `scp .env arduino@<boardname>.local:~/kaiku/.env`, then set `MQTT_HOST=localhost` in it. Then
   `sudo systemctl restart kaiku-hub`. Do not use `KAIKU_VOICE=text` under the service (it waits for a keyboard).
   Expect in `journalctl -u kaiku-hub -f`: the hub's start line and no error about the key.
6. **The sensors app:** in `~/ArduinoApps/kaiku-sensors/.env` set `MQTT_HOST` to the Docker bridge address the
   script printed (`ip -4 addr show docker0`), start the app (`arduino-app-cli app start user:kaiku-sensors`), and
   make it the default so it starts at boot: `arduino-app-cli properties set default user:kaiku-sensors`.
   Expect `health/sensors` on the broker within a minute. Fails: try the board's Wi-Fi address as `MQTT_HOST`.
7. **The head:** `MQTT_HOST "<boardname>.local"` and `MQTT_HOST_IP "<the board's Wi-Fi address>"` in
   `kaiku_link/secrets.h`, flash once (`make atech-standalone FLASH=1`), back on its charger.
   Expect `health/head` on the broker within 20 s of power-on.
8. **See all three:** on the board `./scripts/unoq_robot_setup.sh status`, or from anywhere
   `mosquitto_sub -h <board address> -t 'kaiku/v1/+/health/+' -v`: `hub`, `sensors` and `head`, all `ok`.
9. **Pull every plug, put them back, touch nothing.** Expect the same three `ok` within about two minutes. This is
   the test that the robot is on its own.

The three things most likely to go wrong, in this order:
1. **The head cannot reach the broker.** The venue Wi-Fi keeps clients apart or blocks mDNS, or the UNO Q got a new
   address from DHCP (it was 10.0.41.254 and "can change"): the head then needs `MQTT_HOST_IP` changed and a reflash,
   which takes a computer once. Sign: `hub` and `sensors` on the broker, no `head`. A network of your own (a travel
   router) removes both causes.
2. **The sensors app cannot reach the broker from inside its container**, or does not come back after a power cut.
   Sign: no `health/sensors`. Try the other address in its `.env`; start it by hand
   (`arduino-app-cli app start user:kaiku-sensors`).
3. **The hub on the board:** the install (download size, disk), memory on a 2 GB board with the App Lab container,
   OpenCV and a Live conversation at once (`free -m`; `journalctl -u kaiku-hub` shows a restart loop if it is killed),
   or the service starting before the Wi-Fi is up (it retries by itself; a wrong `.env` does not fix itself).

### Voice on the robot

Hub on the UNO Q with `KAIKU_VOICE=gemini` and `[voice] audio = head` (the script sets `KAIKU_VOICE_AUDIO=head`):
the hub opens the Gemini Live conversation over the board's internet, sends Kaiku's voice to
`audio/head/speaker` and holds the head's microphone open with `cmd.head {mic: open}`. When a conversation opens
(and with which head firmware) is the hub's rule: `hub/AGENTS.md`.

What the person sees and hears: Kaiku's voice from the head. While Kaiku listens, the ear ring is blue (the robot's
head has no display; on the MQTT firmware the ring is lit and an orange dot shows on the display). **Whether the
ring can be seen on the assembled head has not been checked** (`hardware/assembly.md`: only with the ear hole
drilled out to Ø26): if not, nothing on the head shows that it is listening. While Kaiku speaks, and a quarter
second after, the head sends nothing: speak after it has finished. Pressing the ear works at any time.

Check on the board first, in this order (the checklist below has the commands):
1. `bench/speaker_pcm` with the tool, both directions: is the test sound clean, is the WAV of your voice clear, and
   what level does the tool print (tune `MIC_GAIN`).
2. With the firmware and the tool: no microphone frame before `open` or after `close` (the tool counts them).
3. With the hub: `health/head` `audio.mic_tx` rises only during a conversation; Kaiku does not answer its own voice
   (if it does, raise `MIC_TAIL_MS`); words are not cut at the start (if they are, the tail is too long or the
   speaker is "busy" with silence the hub keeps sending).

## Tonight on the laptop (2026-11-14 evening): sound on the robot's head

For exactly this setup: the phone hotspot; **the broker and the hub on a laptop** on that hotspot; the head on the
standalone firmware with sound (`0.4.0`); the UNO Q's sensors app. In this order: each step proves one more thing,
and a failure points at one place. **Nothing below has been done on hardware.** The firmware underneath (`0.1.0`)
has; step 8 is the way back to it.

`<broker>` = the laptop's address on the hotspot (`ipconfig getifaddr en0`). `<port>` = the head's USB port
(`ls /dev/cu.usbmodem*`; with the UNO Q also on USB there are two: unplug one to see which is which).
Commands run from the repo root.

0. **Before anything.**
   - Phone: Personal Hotspot on, "Maximize Compatibility" on, and stay on that settings screen while boards boot.
     Laptop on the hotspot; note `<broker>`. A broker on the laptop (`make broker`; its config listens on every
     interface and sends each sound frame at once). From the laptop, `mosquitto_sub -h <broker> -t 'kaiku/v1/#' -v
     -T 'kaiku/v1/+/audio/#'` must connect (leave it running: it is the view of everything but the sound frames).
   - `firmware/atech-head/kaiku_link/secrets.h` (gitignored, one per laptop, never committed, never pasted
     anywhere). Seven names: `WIFI_SSID` (the hotspot's name exactly as the phone shows it, a curly ’ included),
     `WIFI_PASS`, `MQTT_HOST` (a `.local` name tried first; any name will do, the next line is what counts),
     `MQTT_HOST_IP` = `<broker>`, `MQTT_USER` and `MQTT_PASS` (empty for the anonymous broker), `KAIKU_HOME_ID`
     (`demo-aino`: the home the boards publish on). **Every build compiles this file in**: after changing it,
     build and flash again, the bench program and the firmware alike.
   - Build once while online, without flashing: `make atech-standalone` (each build fetches two libraries).
     Expect `SUCCESS` and about 809 kB of flash.
   - The head on a USB **data** cable to the laptop for flashing. Opening its serial port resets it.
1. **Sound alone** (`bench/speaker_pcm`: speaker, microphone, Wi-Fi, nothing else; it needs no display and holds
   the motor on port 14 still, so nothing is unplugged).
   Flash: `make atech-bench PART=firmware/atech-head/bench/speaker_pcm FLASH=1 ATECH_PORT=<port>`
   Leave the head on the laptop's USB. Terminal A reads it and checks its lines for two minutes (it resets the
   board when it opens the port): `make bench PART=firmware/atech-head/bench/speaker_pcm FROM=serial:<port>`
   Wait for two notes from the head and a `net` line with `"mqtt":1`, then in terminal B:
   `make head-audio ARGS='bench --host <broker>'`
   Expect: 10 s of even clicks and notes (100 a minute) from the head; one very short blip (a sound dropped on
   purpose); "speak now": talk towards the head for 5 s; the tool prints frames, gaps and a level and saves a WAV;
   terminal A ends with `PASS` after you answer its one question.
   - No notes at boot: the speaker module or ports 1-2 (`bench/speaker` plays tones only).
   - Notes but no `net` line, or `"mqtt":0`: the hotspot's name or password, the phone not on its hotspot screen, or
     `MQTT_HOST_IP` (is it this laptop's address **now**?). Fix `secrets.h`, flash again.
   - `pcm` lines but silence: frames arrive and nothing sounds. That is the one call never run (`writeSamples` from
     our task): report it. The firmware of step 2 would play no hub sound either: use step 8's firmware and the
     laptop's speaker for the hub's sound until it is fixed.
   - Gaps (`sound … "gaps"` above 0, `dry` rising): look at `loop_max_ms` and `rssi` in the `pcm` and `net` lines;
     bring the phone closer; raise `SPK_PREBUFFER_MS` to 200 in `kaiku_link/head_audio.h` (then
     `make head-audio-test`, 25 s on the laptop, before flashing).
   - Crackle, a reset (the two notes again), or very quiet: the laptop's USB port may not feed the amplifier. Put
     the head on its own charger and judge by ear and by the tool (there is no serial then, so no `PASS`).
     Still too quiet on the charger: `SPK_GAIN` 2.0 in `head_audio.h`.
   - Keep terminal A reading for the whole run: with the head on a computer's USB port and nobody reading it, its
     serial lines can stall the loop, and the sound with it.
   - Microphone: no frames, or `peak` under −30 dBFS: raise `MIC_GAIN` in `head_audio.h`; clipped: lower it.
2. **The firmware with sound.** `make atech-standalone FLASH=1 ATECH_PORT=<port>`, then **onto its own charger**
   (port 8; the motor never turns on a laptop port).
   In the broker view expect within about 20 s a `health/head` with `"version":"atech-head-standalone-0.4.0"`,
   `"firmware":"standalone"`, `"motor_pins":"36:ok 35:ok"`, `"help_screen":"none"` and an `audio` block; then one
   every 5 s and at every step change. Press the ear, turn it, press through a ritual: it must feel as it did.
   - No `health/head`: step 7 (serial and `net`). A `health/head` with `"status":"down"` is the broker's note that
     the head left.
   - `make head-audio ARGS='play --host <broker> --drop'`: the test sound from the robot; the tool ends with
     `head reports (health/head): 520 of 520 frames received, 0 dropped, ran dry 2 times`. Turn and press the ear
     while it plays: the ritual must answer as always (its own beeps are held back while the sound plays).
     Fewer frames, or more dry events than in step 1: the ritual's loop is too slow for the stream; read
     `loop_max_ms` in the health line (step 7) and report it.
   - `make head-audio ARGS='mic --host <broker>'`: 5 s of microphone. Expect `before it was open 0`, `after it was
     closed 0`, a WAV and a level. **Look at the ear while it runs: is a blue light visible on the assembled head?
     Write the answer down.** It is the only sign of an open microphone on a head without a display.
3. **Taps.** In the broker view, tap the top of the head five times, a second apart: five `raw/head/tap` messages
   with `"src":"imu"` and a `force` (from idle the first one also wakes the head: greeting). Tap while
   `play` runs: none (muted on purpose). Any tap with `"src":"knock"` comes from the UNO Q's old app (section
   "UNO Q").
   - Missed taps or taps by themselves: over USB, `{"action":"tap_sensitivity","value":"1.15"}` is today's value
     (total g; lower is softer, never 1.0 or less).
4. **The hub's hold, without a hub.** `make head-audio ARGS='hold --host <broker>'`, then bring the head to its drum
   step (press the ear at the greeting, through mood, energy and sleep; a press skips the breathing). Expect: the
   head stays in the drum step and sways a little on the beat for 10 s; then it stands still: tap it; then the end
   chime on the UNO Q and the head's two notes. The tool prints `held … yes`, the taps of "your turn" and
   `end_drum … yes`.
   - No sway but `held yes`: is the head on its charger? Else `SWAY_SPEED_PCT` (45) is too low to move it. It
     drifts to one side: lower `SWAY_PULSE_MS` (both in `standalone/src/kaiku_net.cpp`, never run on the robot).
   - A reset or a lost broker during sway and sound together: the supply. Say so; the game works without sway.
   - Close the tool's terminal in the middle of a hold: 10 s later the head's own drum clock decides again (the
     step ends 20 s after the first tap, or 60 s after it began if nobody tapped). A silent hub never strands it.
5. **`show: help` on a head without a display.** In the middle of the mood dial:
   `make head-audio ARGS='show --host <broker> help'`. Expect, in silence: the ritual is over (`"step":"idle"`,
   `"calm":true`, `"help_shown":false` in `health/head`), no chime on the UNO Q, the motor still; a pat or a clap
   does not wake Kaiku. `… show --host <broker> none'` or a press of the ear ends the calm. Any sound when the
   command arrives is a fault. **Nothing shows the helpline numbers on this robot**: only the hub's spoken script.
6. **With the UNO Q and the hub.** The UNO Q on the same broker (section "UNO Q": its `.env` has the broker's
   address; `health/sensors` in the broker view; a face wakes the head). Then the hub on the laptop as
   `hub/AGENTS.md` → "Robot bring-up with the standalone head" says, with the music and the voice on the head
   (`[music] out = "head"` is the default; `[voice] audio`, `KAIKU_VOICE`, `KAIKU_MUSIC`: `hub/AGENTS.md`).
   - **Tap it back:** at the head's drum step the hub holds it; the song comes from the head, which sways; the
     "your turn" cue; your taps; the result cue; after the last level the end chime. Nothing may sound from the
     laptop. No song: `make head-audio ARGS='check --host <broker> --seconds 30'` during a song shows whether the
     hub sends frames, their size and pacing. Frames there and silence here: step 2. No frames: the hub (its log,
     the key, `KAIKU_MUSIC`). The head leaves the drum step in the middle: a hold came more than 10 s after the
     last one, or the ear was pressed.
   - **Voice.** The conversation is opened by the person, on the head: wake it, let the invitation finish, and
     press the ear at the greeting with the hub already running. Expect, in order: no blue ear before your press
     (nothing is listened to); within about a second of it the blue ear, and Kaiku saying its first line from the
     head; say something when it has finished and get an answer from the head; turn and press through the three
     dials, each with Kaiku's line; in the drum step, with the game running, **the blue ear off** (the hub closes
     the microphone for the whole game) and on again at the game's closing line; the goodbye, then the ear orange
     for good. `mosquitto_sub -h <broker> -t 'kaiku/v1/+/raw/hub/trace' -v` shows each line as Kaiku finishes it,
     and `health/head` `audio.mic_open` says the same as the ear.
     No blue ear (and `mic_open` false) after your press: the hub did not see the press at the greeting (it was
     started after the head's ritual began, or the head publishes under another home id): back to idle and start
     again; its log says `follow_conversation opening: …` or `not opened: …` with the reason. `mic_open` true
     during the song or your taps: report it. Kaiku's first line and your first words collide: the head is
     half-duplex, wait for the line to end. Kaiku answers its own voice: raise `MIC_TAIL_MS` (250) in `head_audio.h`.
7. **Reading the head.**
   - **`health/head`** (the broker view; retained, so the last one is there at once). `version`: `…-0.4.0` with
     sound, `…-0.1.0` the firmware before it. `motor_pins`: `36:ok 35:ok`. `rssi`: weaker than about −75, bring
     the phone closer. `reconnects`: rising means the head keeps losing the broker. `loop_max_ms`: the longest
     pass of the main loop since the last health message; under 100 is fine, more means frames arrive in bursts
     (say which step it was in). `audio.rx`: frames received, 50 a second while sound plays. `audio.drop`: stays
     0 (more: the sender runs too far ahead). `audio.dry`: one per sound is its end; more are gaps (late frames:
     the network or the loop). `audio.mic_open`, `audio.mic_tx` (rises only while the microphone is held open),
     `audio.mic_peak`. `drum_held`, `calm`, `step`.
   - **Serial**, when there is no `health/head` at all: the head on the laptop's USB, any serial terminal at 115200
     on `<port>` (`source firmware/atech-head/.venv/bin/activate && python -m serial.tools.miniterm <port> 115200`;
     opening it resets the head). One JSON line each: `boot` (`reset_reason`: `BROWNOUT` is the supply, `PANIC`
     or `TASK_WDT` is a crash: copy the lines above it), `ritual_step`, a `status` every second (`step`, `dial`,
     `sound_peak`, `tilt`, `taps`, `motor`), `tap`, `drum`. Lines are dropped when nobody reads, by design.
   - **`net`**: type `net` and Enter. It answers `{"type":"net","payload":{…}}`: `wifi` 3 = joined, 1 = network not
     found, 4 = join failed (the password), 6 = not connected; `mqtt` 0 = connected, −2 = broker unreachable (the
     address); `ours_seen` 1 = the hotspot is in range, with `ours_channel` and `ours_rssi`; `ssid_len` = the
     length of the compiled-in name (a curly ’ counts 3); `broker` = the compiled-in address. When the head is
     offline the answer takes about 3 s (it scans). It never prints the password.
8. **Back to the known-good firmware** (`0.1.0`: Edwin's, as merged in commit `985064b`, no sound streams). It is
   built beside the working tree from that commit, so nothing in the repo changes, with the `secrets.h` of now:
   ```bash
   F=$(mktemp -d) && git archive 985064b firmware/atech-head/standalone firmware/atech-head/kaiku_link | tar -x -C "$F" \
     && ln -s "$PWD/firmware/atech-head/.venv" "$F/firmware/atech-head/.venv" \
     && cp firmware/atech-head/kaiku_link/secrets.h "$F/firmware/atech-head/kaiku_link/" \
     && "$F/firmware/atech-head/standalone/build.sh" upload <port>
   ```
   Built this way on the bench laptop (802 845 bytes of flash); the upload was not run. Expect
   `"version":"atech-head-standalone-0.1.0"` in `health/head` and no `audio` block. With it the hub's music and
   voice cannot come from the head: set the hub's outputs to the laptop (`hub/AGENTS.md`).

What is not for tonight: "The robot on its own" above (the hub and the broker on the UNO Q).

## Testing without the hub

- Watch everything: `mosquitto_sub -h localhost -t 'kaiku/v1/#' -v` (or `make tail TOPIC=...`).
- Send a command: `mosquitto_pub -h localhost -t 'kaiku/v1/demo-aino/cmd/head' -m '{"v":1,"id":"01a1d9e7-0000-7000-8000-000000000001","ts":"2026-11-14T12:00:00.000Z","home_id":"demo-aino","source":"hub","type":"cmd.head","payload":{"eyes":"happy"},"sim":false}'`
  (worked today), or from Python with `kaiku_contracts.Bus("sim")` + `bus.publish(type, payload, source="hub")`;
  `source` must be a real node name (`head|sensors|hub|...`).
- The MQTT firmware moves the motor only while it hears `health/hub`: without `make hub`, publish `health`
  `{status: ok}` as `hub` every few seconds.
- The standalone over USB: plain-text commands without a value work (`greet`, `chirp`, `next`, `net`); with a value
  they must be JSON lines (`{"action":"pan","value":"100"}`). Opening the serial port resets the board.
- Sound, microphone, the hub's hold, `show`: `make head-audio ARGS='… --help'` (`bench`, `play`, `mic`, `hold`,
  `check`, `show help|none`). The two `audio/` topics are binary: leave them out of a text view
  (`mosquitto_sub … -T 'kaiku/v1/+/audio/#'`).

## What we tried today, and what it taught us

| Symptom | Tried | Outcome |
|---|---|---|
| Pan motor never turns, not even a hum | 2 motors, ports 13/9/11, 2 cables, Atech's own `atech send motor_speed` | **Power**: turns only with the Atech on its own USB-C charger (D54) |
| Motor turned one way only | port 11 | GPIO44 is UART0 RX: use port 13 (MQTT firmware) or 14 (standalone) |
| Head ignored every move, "hub silent" | read `tick()` | clock read before `mqtt.loop()` (fixed in `kaiku_link`) |
| Standalone missed knob presses without a laptop | muted the Atech drivers' debug prints (`build.sh`) | runs untethered |
| Both boards lost the broker every 1-2 min | watched the broker log: both dropped within seconds of each other | venue Wi-Fi; moved to the iPhone hotspot (D54): no drops seen since |
| UNO Q silent after power changes | — | app didn't autostart: now the default app |
| UNO Q "doesn't join Wi-Fi" on external power | — | idle iPhone hotspot sleeps; retries forever now, venue Wi-Fi not auto-joined |
| UNO Q rebooted when the Atech was unplugged | — | shared supply: separate supplies (D54) |
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
7. Run "Tonight on the laptop" and write what happened at each step into `docs/progress.md`.
8. **No display on the head:** the helpline numbers cannot be shown on the robot (the hub's spoken script is the only
   way they reach the person), and an open microphone is shown only by the ear ring, if it can be seen. Both are
   limits to state in `docs/safety.md` / `docs/privacy.md` until the display is back.
9. Deploy the UNO Q sketch 0.3.0 (section "UNO Q" above).
10. Voice interruption (echo cancellation) if half-duplex is not good enough; a broker password before the robot's
    microphone is on a shared Wi-Fi.

## Hardware changes today (CAD + parts)

- Knob cap: round bore Ø9.65 × 16 deep (cap Ø22 × 18). DC motor measured 19.5 × 19.5 × 39 + 9 mm shaft:
  `pan_motor_mount` and `purr_sleeve` resized (Ø20.1 inside). Reprint plate (knob cap + both sleeves): ~23 min / 12 g
  on P1S or P2S. See `hardware/dimensions.md`.
- Removed: KY-053 (and so the KY-039), LED grids (D54); earlier KY-054 and KY-035 (D35).
