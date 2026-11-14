# Kaiku robot: electronics spec

> **Source document (Xavier, reconciled with the printed CAD by Edwin).** How it maps onto the repo, and what we
> build: [`plans/07-robot-electronics.md`](plans/07-robot-electronics.md) (D31 hardware, D32 software). Pins:
> `hardware/wiring.md`; messages: `contracts/`; firmware: `firmware/*/AGENTS.md`. Where they differ, those win.

Nov 14, 2026 · @Xavier (updated the same day to match the printed robot, `hardware/cad/`; see "Changes" at the end)

## Overview

The Kaiku home robot has two controllers that talk directly over the venue Wi-Fi using MQTT. The broker runs on the
UNO Q, so no cloud sits in the robot's own control loop. Both boards sit in the **body**. The **head** holds the
camera, the eyes display, the knob ear, the microphone and the knock sensor, cabled down through the hollow neck.

- **Atech motherboard (ESP32-S3), in the body.** It drives the Color Display (the eyes), the Knob (the dial ear),
  the Button, the Speaker, the Microphone, two LED grids (chest glow) and the pan motor. It is the robot's face,
  voice, ears and movement.
- **Arduino UNO Q (2 GB), in the body.** It has two processors:
  - **Linux side (Qualcomm QRB2210, Debian).** Runs the Python `hub/` (ritual state machine, safety gate, uplink to
    Modal) and the Mosquitto broker. It also reads the Arduino USB Camera.
  - **Microcontroller side (STM32U585).** Reads the KY-031 knock sensor (the drum on top of the head), the KY-039
    pulse sensor (through the KY-053 ADC) and drives the Modulino Buzzer on Qwiic. (No KY-054 light or KY-035 hall in
    this build, D35: room light comes from the camera and home is the head's power-on position.)

In the README's terms, both boards together are **Source 1: Robot**. Only derived numbers leave the home. Camera
frames and raw audio stay on the UNO Q and are never stored.

&#91;embedded content: System topology · 2 boards, 1 camera, 1 cloud link\]

The hub on the UNO Q is the centre: the Atech board reaches it over MQTT, the STM32 over the Bridge, the camera over
USB. Only the hub talks to Modal.

## Bill of materials

Physical placement and sizes are in `hardware/cad/README.md`, `hardware/assembly.md` and `hardware/dimensions.md`.

| Part | Exact part / chip | Interface | Lives in | Job in Kaiku |
| --- | --- | --- | --- | --- |
| Atech motherboard | ESP32-S3, 14-port | USB-C, Wi-Fi 2.4 GHz only | Body, left wall | Face/voice/motor controller, MQTT client |
| Atech Color Display | `st7735_tft`, 160×80 TFT (0.96") | SPI, 2 ports | Head, "tuning window" above the camera | Animated eyes |
| Atech Knob | `rotary_encoder_knob`, EC11 + light ring | Digital, 2 ports | Head, left ear | Mood / energy / sleep dial ("turn my ear") |
| Atech Button | `button_module`, active-low switch | GPIO, 1 port | Body lid (square opening) | Start / confirm / talk; long press = "I'm not OK" |
| Atech Speaker | MAX98357A I2S amp | I2S, 2 ports | Body, right-wall grille | Robot voice, music, breathing cues |
| Atech Microphone | ICS-43434 I2S MEMS | I2S, 2 ports | Head, right ear grille | Speech for voice chat and speech pace |
| Atech LED Grid ×2 | `neopixel_grid`, WS2812B 3×3 | 1 port each | Body, behind the chest louvres | Breathing glow |
| Atech DC Motor V2.3 | DRV8833 driver + geared motor in one 23×23×44 mm block, 3 mm shaft | 2 GPIO (IN1, IN2), 1 port | Body, under the pan base | Turns the head (12:40 printed gear) |
| [Arduino UNO Q 2 GB](https://docs.arduino.cc/hardware/uno-q/) | QRB2210 (Linux) + STM32U585 (MCU) | Wi-Fi, USB-C | Body floor, rear | Hub, broker, sensors |
| UNO Q LED matrix | 8×13 blue, on board | MCU internal | Body (hidden) | Status/debug only; the eyes are the Atech display |
| [Arduino USB Camera](https://docs.arduino.cc/hardware/usb-camera/) | UVC video + UAC mic, ring light, autofocus | USB-A (1 m cable) via the powered hub | Head; its ring light is the round "grille" of the face | Presence, get-up time, face tracking, optional pulse |
| [Modulino Buzzer](https://docs.arduino.cc/hardware/modulino-buzzer/) (ABX00108) | STM32C011F4 + PKLCS1212E4001, I2C 0x3C | Qwiic (Wire1), 3.3 V | Body, right wall above the speaker | Chimes and alerts |
| KY-031 knock sensor | Spring switch + 10 kΩ resistor | 1 digital GPIO, 3.3 V | Under the head top, wired to the UNO Q through the neck | Drumming energy |
| KY-039 pulse + KY-053 ADC | IR LED + phototransistor; ADS1115 16-bit | Analog → I2C | Lid, under the finger cradle; ADC on the body floor | Resting HR / HRV before and after breathing |
| ~~KY-054 light sensor~~ | Phototransistor | Analog, 3.3 V | **Not fitted (D35)**; the lid window stays empty | Room light comes from the camera |
| ~~KY-035 hall sensor + 6×3 mm magnet~~ | 49E linear hall | Analog, 3.3 V | **Not fitted (D35)**; the CAD keeps the spot and the magnet pocket | Optional pan homing |
| Powered USB-C hub (PD) | Any USB-C hub with PD input | USB-C | Outside, behind the robot | Powers the UNO Q and lets it host the camera |
| Arduino power supply (TPX00242) | USB-C, VERIFY rating (spec assumes 5 V / 3 A PD) | USB-C | Outside | Main power |

Not in this build: LoRa friend link, KY-050 ultrasonic (presence comes from vision), Atech IMU (taps come from the
KY-031), Atech Speaker *and* a second motor at the same time (see the port layout).

## Power

Power the UNO Q through a **powered USB-C PD hub**, not through VIN. The camera only works when the UNO Q acts as a
USB host, and that happens reliably only on a PD hub. The hub sits behind the robot; its cables come in through the
body's rear opening.

| Rail | Source | Feeds | Notes |
| --- | --- | --- | --- |
| 5 V / 3 A USB-C PD | Arduino supply → hub PD input | Hub → UNO Q + USB Camera | UNO Q accepts USB-C 5 V up to 3 A, or VIN 7–24 V, or the 5 V pin |
| USB-C 5 V | Second USB-C supply, or a hub USB port | Atech motherboard (USB-C module, port 8) | Every port carries 12 V, 5 V, 3.3 V and GND; power pins are shared; Atech publishes no current ratings |
| 3.3 V (Qwiic) | UNO Q | Modulino Buzzer | About 6.4 mA while sounding |
| 3.3 V (header) | UNO Q 3V3 pin | KY-031, KY-039, KY-053 | Run them all at 3.3 V so their signals stay in 3.3 V logic |

Rules for the code and the build:

- **USB host gotcha.** If the UNO Q is powered from VIN with no USB-C negotiation, its USB controller boots in device
  mode and the camera is not detected. Arduino's documented setup is a PD hub powered by 5 V / 3 A.
- **Motor brown-outs.** The DC motor shares the Atech rails with the speaker, microphone, display and LED grids. Ramp
  `set_speed` over about 100 ms instead of jumping to ±255. Never run the motor and loud speaker output at full power
  at the same time.
- **Logic levels.** UNO Q headers and Qwiic are 3.3 V. JCTL and the bottom connectors are 1.8 V: do not wire anything
  to them.

## Network and messaging

The Atech board talks to the UNO Q directly over the venue Wi-Fi. It uses MQTT from **custom firmware code**, not
Atech's built-in Wi-Fi transport. Atech's Wi-Fi mode sends everything through its cloud gateway
(`wss://gateway.atech.dev`), and Atech documents no MQTT support. Atech does allow firmware to use Wi-Fi directly and
to add C++ to the main loop or as a custom module. That is how the MQTT client goes in.

**Setup**

- Broker: Mosquitto on the UNO Q Linux side, port 1883, LAN only, with a username and password.
- Addressing: give the UNO Q a hostname (`kaiku-hub.local`) and also print its IP on boot. Put the IP in the Atech
  firmware as a fallback, because mDNS is often blocked on venue networks.
- The Atech board joins **2.4 GHz** networks only. If the venue SSID is 5 GHz only, or blocks device-to-device
  traffic (client isolation), switch both boards to a phone hotspot. Test this first, before anything else.
- MQTT client IDs: `kaiku-head` (Atech) and `kaiku-hub` (UNO Q). The Atech board sets a last-will message
  `{"online":false}` on `kaiku/head/status`.

**Topics.** These names are a proposal. The repo's contracts are law (`AGENTS.md` rule 1): the real topics are
`kaiku/v1/<home>/raw/head/*`, `.../cmd/head` and `.../health/head` (`contracts/schemas/`), so map these onto them
and add any missing payload fields through a contract change. Every JSON message carries `ts` (ms since boot) and
`seq`.

| Topic | From → to | Payload | QoS |
| --- | --- | --- | --- |
| `kaiku/head/status` | head → hub | `{online, rssi, fw}` every 10 s, retained | 1 |
| `kaiku/head/button` | head → hub | `{event: "press"\|"release"\|"long", ms}` | 1 |
| `kaiku/head/knob` | head → hub | `{value: 1..5, delta, pressed}` on change | 1 |
| `kaiku/head/eyes/cmd` | hub → head | `{expr: "sleep"\|"open"\|"blink"\|"look_left"\|"look_right"\|"happy"\|"listening"\|"concern"}` | 1 |
| `kaiku/head/leds/cmd` | hub → head | `{mode: "off"\|"breathe"\|"glow"\|"pulse", bpm?, color?}` | 1 |
| `kaiku/head/mic/level` | head → hub | `{rms, peak}` at 10 Hz | 0 |
| `kaiku/head/mic/pcm` | head → hub | binary, 16-bit LE mono 16 kHz, 640 B (20 ms) a frame | 0 |
| `kaiku/head/speaker/pcm` | hub → head | binary, same format | 0 |
| `kaiku/head/speaker/cmd` | hub → head | `{op: "tone"\|"rtttl"\|"stop"\|"volume", ...}` | 1 |
| `kaiku/head/motor/cmd` | hub → head | `{op: "gesture", name: "look_left"\|"look_right"\|"shake"\|"home"}` or `{op: "speed", value: -255..255, ms}` | 1 |
| `kaiku/head/motor/state` | head → hub | `{moving, last_gesture}` | 0 |
| `kaiku/head/mic/cmd` | hub → head | `{stream: true\|false}` | 1 |
| `kaiku/hub/heartbeat` | hub → head | `{ritual_state}` every 1 s; the head stops the motor and the speaker after 5 s of silence | 0 |

The UNO Q's own parts (knock, pulse, light, hall, buzzer, camera) talk to the hub over the internal Bridge, not over
MQTT (see the UNO Q section). The hub republishes their events on `kaiku/body/...` so `tools/` can tail and replay
everything.

**Safety rule for the Atech firmware.** If no `kaiku/hub/heartbeat` message arrives for 5 s, stop the motor and the
speaker. Never move the motor without a command from the hub.

## Atech board (ESP32-S3, in the body)

Build the firmware with the open-source `atech` Python SDK (`pip install atech`, Python 3.10+). It generates
`main.cpp` and `platformio.ini` from a `project.yaml`, then compiles and flashes offline. Add Wi-Fi + MQTT as inline
loop code or as a custom module. The first build downloads about 2.4 GB of compiler, so do that now on venue Wi-Fi.

**Board facts.** The 14-port board has 12 module ports: 1–7, 9–11 and 13–14. Port 8 is USB-C and port 12 is reset.
Each port has 12 V, 5 V, 3.3 V, GND and two data lines (D1, D2) wired to ESP32-S3 GPIOs. Double-width modules take
two neighbouring ports on the same side: 1–2, 2–3, 3–4, 4–5, 5–6, 9–10, 10–11 or 13–14. USB: 115200 baud, one JSON
object per line.

**Port layout: all 12 ports are used.** The modules are cabled to the board (they live in the head and around the
body), not snapped onto it. Confirm the GPIO numbers with `atech validate`; don't hard-code them from this table.

| Module | Ports | Why there |
| --- | --- | --- |
| Speaker | 1–2 | Same side as the motor, away from the mic |
| Color Display | 3–4 | — |
| Knob | 5–6 | — |
| DC Motor (pan) | 7 | Speaker side, away from the mic |
| Microphone | 9–10 | Other side from the speaker and motor, so less noise reaches it |
| Button | 11 | — |
| LED Grid left / right | 13 / 14 | — |

With every port taken, there is **one motor** (pan) and no Atech IMU. A second motor (the "purr" mount in the CAD)
needs a free port: drop one LED grid, or drop the Speaker and play audio from the laptop.

**Color Display** (`st7735_tft`): two ports (DC/CS and MOSI/SCLK). Draws the eyes: the same expression set as
`kaiku/head/eyes/cmd`. Blink every 3–6 s, chosen at random, with a 120 ms blink; skip blinks during breathing.
Expressions are frames stored as constants in the firmware. It is mounted connector edge up behind a 28 × 13 mm
window.

**Knob** (`rotary_encoder_knob`): two ports. Clamp the dial to 1–5 and publish `kaiku/head/knob`. A press of the
knob (or the Button) confirms the current answer. Light its ring while a dial question is open.

**LED Grid ×2** (`neopixel_grid`): breathing glow behind the chest louvres. `breathe` follows the hub's in/hold/out
timing; `glow` and `pulse` are for status.

**Button** (`button_module`)

- Pins: Data A is the switch, active low. Data B is an RGB indicator LED (V2.0 modules only).
- API: `is_pressed`, `was_pressed`, `was_released` (the last two fire once per edge).
- Firmware behaviour: debounce 20 ms. A long press is 800 ms or more. Publish press, release and long to
  `kaiku/head/button`. Light the LED (if V2.0) while the robot is listening.

**Speaker** (`speaker`, MAX98357A)

- Pins: port 1 = LRCLK, BCLK. Port 2 = DIN.
- API: `play_tone(freq, ms)` (blocking), `play_note`, `play_rtttl` (non-blocking), `rest`, `stop`,
  `set_volume(0.0–1.0)`, `write_samples` (raw 16-bit mono to I2S), `play_pcm` (base64 16-bit mono PCM chunks from the
  host).
- **Audio format: 16 kHz, mono, 16-bit.** The board has no MP3 or WAV decoder. The hub must decode and resample
  Gemini Live and Lyria audio to 16 kHz mono before sending it.
- Firmware behaviour: subscribe to `kaiku/head/speaker/pcm` and push each frame to `write_samples` through a ring
  buffer of about 200 ms, to absorb Wi-Fi jitter. On underrun, play silence, not the last frame. Never call blocking
  `play_tone` from the MQTT callback; use `play_rtttl` or the sample path.

**Microphone** (`microphone`, ICS-43434)

- Pins: port 1 = LR, WS. Port 2 = SCK, SD.
- API: `get_sound_level` (RMS 0–32767), `is_sound_detected` (threshold), `get_peak_amplitude` (resets on read),
  `get_samples`, `start_recording` / `stop_recording` (heap buffer, 10 s maximum), `set_channel` (left or right
  through LR).
- Atech does not document the sample rate or bit depth. Set and verify **16 kHz, 16-bit** in firmware, so the mic
  matches the speaker format.
- Firmware behaviour: always publish `mic/level` at 10 Hz. Stream `mic/pcm` only between `{stream:true}` and
  `{stream:false}`. While the speaker is playing, mark frames `echo=1` in a header byte, or mute the mic, so the robot
  doesn't hear itself.
- The module sits behind the head's right-ear grille. Its ICS-43434 is bottom-ported: put the face with the sound
  hole against the grille.

**DC Motor** (`dc_motor`, DRV8833, motor and driver in one block)

- Pins: Data A = IN1, Data B = IN2.
- API: `forward(speed)` / `reverse(speed)` with speed 0–255. `set_speed(-255..255)`, where the sign is the
  direction. `stop` lets it coast; `brake` stops it actively.
- **What it moves.** It turns the head through a 12-tooth pinion on a 40-tooth ring gear (3.33 : 1), about ±100°.
  There is no end stop and, in this build, no hall sensor (D35): **home is the head's position at power-on**, so face
  it forward before powering up. Soft limit ±80°. (With a KY-035 + magnet, `HAS_HALL 1` brakes on the hall edge.)
- **No position feedback** between homings. Gestures are timed pulses:
  - `look_left` / `look_right`: turn about 300 ms one way, then brake.
  - `shake`: two short alternating pulses of about 120 ms each, then brake (it pans, so there is no nod).
  - `home`: drive back to the dead-reckoned 0° (the power-on position). Used after every gesture sequence. Face
    tracking is relative (the camera is in the head), so small drift doesn't affect looking at the person.
- Firmware behaviour: ramp speed over about 100 ms. Never run longer than 1 s per command. Ignore commands while a
  gesture is running. Publish `motor/state`. All pulse times need tuning on the real head.

## Arduino UNO Q (body node)

The UNO Q needs two programs: a Python app on Linux and an Arduino sketch on the STM32. They talk only through the
**Bridge**, an RPC router reached on Linux through `/var/run/arduino-router.sock`. Use Arduino App Lab, which
deploys the sketch and the Python together.

**What runs where**

| Side | Chip | Logic | Runs |
| --- | --- | --- | --- |
| Linux (MPU) | Qualcomm QRB2210, Debian | 1.8 V on the bottom connectors and JCTL | `hub/`, Mosquitto, camera pipeline, Gemini Live / Lyria clients, uplink to Modal |
| MCU | STM32U585, Cortex-M33 160 MHz, Arduino core on Zephyr | 3.3 V on the UNO headers, JSPI and Qwiic | KY-031 knock, KY-039 pulse (via KY-053), KY-054 light, KY-035 hall, Modulino Buzzer |

**Bridge API.** Sketch: `#include <Arduino_RouterBridge.h>`, then `Bridge.begin()` in `setup()`. Python:
`from arduino.app_utils import App, Bridge`, then `App.run(user_loop=loop)`.

- `Bridge.provide(name, fn)` registers a function the other side can call.
- `Bridge.call(name, args...)` calls it and waits for the answer.
- `Bridge.notify(name, args...)` sends one-way, without waiting.

Functions the **sketch provides** (Python calls them):

| Name | Args | Effect |
| --- | --- | --- |
| `buzz` | `freq_hz, ms` | One tone on the Modulino Buzzer |
| `buzz_pattern` | `name: str` | `wake`, `ok`, `start_drum`, `end_drum`, `alert` |
| `drum_arm` | `window_ms` | Starts a drumming window; the sketch counts knocks |
| `pulse_arm` | `window_ms` | Samples the KY-039 through the KY-053 at ≥ 100 Hz for the window |
| `light_read` | — | Returns the KY-054 reading (unused: not fitted, D35) |
| `ping` | — | Returns firmware version, for `make doctor` |

Functions **Python provides** (the sketch notifies them):

| Name | Args | When |
| --- | --- | --- |
| `on_knock` | `t_ms` | Every knock, debounced |
| `on_drum_done` | `count, mean_interval_ms, cv` | When the drum window ends |
| `on_pulse_done` | `samples` (batched) | When the pulse window ends; the hub computes HR/HRV |
| `on_home` | `t_ms` | Hall sensor edge (only with `HAS_HALL 1`; not fitted, D35) |
| `mcu_ready` | — | Once after boot |

**UNO Q LED matrix.** The board lies inside the body, so the matrix isn't visible. Use it for boot/status only. The
eyes are on the Atech display.

**Pin plan (MCU side)** (pins other than D2 and Qwiic: VERIFY on the board)

| Signal | UNO Q pin | Notes |
| --- | --- | --- |
| KY-031 S | D2 | Interrupt on CHANGE; 3.3 V logic |
| ~~KY-035 hall out~~ | (A1 if fitted) | Not fitted (D35) |
| ~~KY-054 light~~ | — | Not fitted (D35) |
| KY-053 ADC (KY-039 on its A0) | SDA / SCL header pins (`Wire`) | Not A4/A5 |
| All KY + | 3V3 | — |
| All KY − | GND | — |
| Modulino Buzzer | Qwiic connector | **`Wire1`**, not `Wire` (Qwiic is a separate I2C bus); 3.3 V |

On the UNO Q, A4/A5 are not the default `Wire` bus, unlike a classic UNO. Leave them free.

## Arduino USB Camera

The camera is a standard USB webcam: video shows up as a USB Video Class device and its microphone as a separate USB
Audio Class device. Read it from Python on the UNO Q Linux side with OpenCV (`cv2.VideoCapture`) through the PD hub.
No driver is needed.

- **Mounting.** The camera stands on its folded clip on the head floor, ring light forward; its ring light is the
  round "grille" of the face. Its USB-A cable runs down through the hollow neck, out of the body's rear opening and
  into the hub. Because the head pans, the camera can keep a face centred.
- **Hardware.** Autofocus lens, adjustable LED ring light, built-in mic, 1 m USB-A cable. It can capture up to 4K
  MJPEG, but **use 640×480 at 15 fps** on the 2 GB UNO Q to leave CPU for the hub.
- **Camera mic.** Not used. The Atech mic is the speech mic. Leave the camera mic unopened so the two don't conflict.
- **Privacy.** Process frames in memory and drop them. Never write frames to disk and never send them off the board.
  Only the derived numbers below leave the device.

**What the camera pipeline outputs**

| Measure | Method | Output | Rate |
| --- | --- | --- | --- |
| Person present | Face detection (OpenCV Haar or YuNet) | `present: bool`, face box | 2 Hz while idle |
| Face position | Face box centre → pan target for the motor | `face_x` (−1..1) | While a ritual runs |
| Get-up time | Clock time of the first "present" seen after 04:00 local each day | `first_seen_local` | Once a day |
| Pulse (optional backup) | Remote photoplethysmography: mean green channel over a forehead box, band-pass 0.7–3 Hz, 30 s window during breathing | `hr_bpm`, `hrv_rmssd_ms`, `quality` 0–1 | Once a ritual, only if the KY-039 reading fails |

- **Room light** comes from the camera (D35, `[unoq] light_source = "camera"`): exposure locked through `v4l2-ctl`
  (`exposure_auto=1`, a fixed `exposure_absolute`), ring light **off**. Store it as a relative index against the
  person's own baseline, not as lux. The camera is `/dev/video2` on the UNO Q (`camera_index = 2`).
- **Pulse.** The KY-039 in the finger cradle is the main source. Camera-based HRV is noisy: send `quality` with
  every reading and let the cloud drop readings below 0.6. If neither works, mark HR/HRV "not measured"; don't send
  fake values.
- **Wake trigger.** When a face is present for 2 s, call `on_person_arrived` in the hub, which starts the ritual.
  That's how "the ritual runs when the person walks up" from the README.

## Modulino Buzzer (ABX00108)

The buzzer is a small I2C board: an STM32C011F4 drives a PKLCS1212E4001 piezo, and the host sends it tones over
Qwiic. It is glued to the body's right wall above the speaker. Plug it into the UNO Q's Qwiic connector with the 5 cm
cable that comes with it (use a longer Qwiic cable if it doesn't reach).

- **Address:** 0x3C by default (hardware address 0x1E). Can be changed in firmware.
- **Power:** 3.3 V through Qwiic, about 6.4 mA while sounding.
- **Library:** `Arduino_Modulino` version 0.6.1 or later, which added UNO Q support. In App Lab it does not install
  all its dependencies automatically on the UNO Q, so add them by hand if the build fails.
- **API:** `#include <Arduino_Modulino.h>`, `ModulinoBuzzer buzzer;`, then `Modulino.begin(); buzzer.begin();` in
  `setup()`, then `buzzer.tone(freq_hz, duration_ms)`.
- **Timing gotcha.** `tone()` is **non-blocking**, and the buzzer never reports back when it has finished. For a
  pattern, the sketch has to wait the same duration (with `millis()`, not `delay()`) before sending the next note.

Patterns (frequencies in Hz / durations in ms):

| Name | Notes | Used for |
| --- | --- | --- |
| `wake` | 660/80, 880/120 | Person detected, ritual starting |
| `ok` | 1320/60 | Answer recorded |
| `start_drum` | 880/60, 880/60 | Drumming window opens |
| `end_drum` | 1320/80, 990/80, 660/120 | Drumming window closes |
| `alert` | 440/300 × 3 | Network lost or a hardware fault; **never** used for anything about mood or safety |

The buzzer is quiet and robotic. Keep it for short cues. The voice and music go through the Atech speaker.

## KY-031 knock sensor (the drum)

The KY-031 is a spring contact with a 10 kΩ resistor and three pins (S, +, −). It outputs one on/off signal per tap,
so it counts taps and their timing, **not** how hard each tap is. In Kaiku, "drumming energy" therefore means tap
rate and rhythm.

- **Mounting.** Glue it flat under the top of the head (where people tap), with foam tape so taps reach the spring.
  The motor is down in the body, so motor vibration reaches it only weakly; still ignore knocks while the motor is
  moving (the hub knows the motor state).
- **Wiring.** S → D2, + → 3V3, − → GND, three jumper wires down through the hollow neck. Powering it at 3.3 V keeps
  the signal at 3.3 V.
- **Polarity differs between sellers.** Some boards idle HIGH and go LOW on a knock; others do the opposite. At
  boot, read the pin for 500 ms with the head still, take that as the idle level, and treat any change away from it
  as a knock. Use `INPUT_PULLUP` if the idle reading floats.
- **Detection.** Interrupt on CHANGE (`attachInterrupt(digitalPinToInterrupt(2), …)`); fall back to polling at 1 kHz
  if D2 has no interrupt on this core. The spring bounces, so treat everything within 40 ms of a knock as the same
  knock.
- **Drum window.** `drum_arm(20000)` opens a 20 s window. The sketch stores knock times and, when the window closes,
  notifies `on_drum_done(count, mean_interval_ms, cv)`. `cv` is the coefficient of variation of the intervals, a
  rhythm-regularity number. The hub turns this into `drum_rate_per_min` and `drum_regularity` for the cloud.

## Wiring table

Every physical connection, in one place. Record the final port and pin numbers in `hardware/wiring.md`.

| From | To | Cable / pins | Check |
| --- | --- | --- | --- |
| Arduino PD supply | USB-C hub PD input (behind the robot) | USB-C | Hub LED on |
| USB-C hub host cable | UNO Q USB-C (through the rear opening) | USB-C | UNO Q boots; `lsusb` lists the hub |
| Arduino USB Camera (head) | Hub USB-A port | Its USB-A cable, down the neck and out the rear opening | `v4l2-ctl --list-devices` shows it |
| Hub USB-A port, or a second supply | Atech port 8 (USB-C module, rear-top of the board) | USB-A → C **data** cable for flashing, any cable after that | Board LED on |
| Atech Speaker (body) | Atech ports 1–2 | Atech cable | `play_rtttl` test |
| Atech Color Display (head) | Atech ports 3–4 | Atech cables, through the neck | Eyes appear |
| Atech Knob (head) | Atech ports 5–6 | Atech cables, through the neck | `knob` events 1–5 |
| Atech DC Motor (pan) | Atech port 7 | Atech cable | `home` gesture moves the head |
| Atech Microphone (head) | Atech ports 9–10 | Atech cables, through the neck | `mic/level` rises when you talk |
| Atech Button (lid) | Atech port 11 | Atech cable | `button` event |
| Atech LED Grid ×2 | Atech ports 13, 14 | Atech cables | Breathing glow |
| Modulino Buzzer | UNO Q Qwiic | Qwiic cable | I2C scan on `Wire1` finds 0x3C |
| KY-031 S / + / − (head) | UNO Q D2 / 3V3 / GND | Dupont jumpers, through the neck | Knock prints in the serial monitor |
| KY-053 SDA / SCL / + / − (KY-039 on its A0) | UNO Q SDA / SCL / 3V3 / GND | Dupont jumpers | I2C scan on `Wire` finds 0x48 |

Charge-only USB-C cables can't program the Atech board. The head carries 6 Atech cables, 3 jumper wires and the
camera cable through a 19 mm axle: feed the plugs through one at a time, the camera's USB-A plug first.

## Behaviour: the morning ritual

The hub runs the ritual as a state machine of about 3 minutes. Each step names what the hardware does and what it
measures. Step lengths are starting values for tuning.

| # | State | Robot does (outputs) | Measures (inputs) | Length |
| --- | --- | --- | --- | --- |
| 0 | Idle | Eyes `sleep`, motor still, mic level only | Camera at 2 Hz for a face; room light (camera) once a minute | — |
| 1 | Wake | Buzzer `wake`; eyes `open` → `blink`; head turns to the face, then `home` | Get-up time (first face of the day); room light at ritual start | 3 s |
| 2 | Greet | Speaker: greeting from Gemini Live; eyes `happy` | — | 10 s |
| 3 | Check-in dial | Asks mood, then energy, then sleep. Each answer: **turn the ear knob to 1–5 and press** (buzzer `ok` after each), or a spoken number | `mood`, `energy`, `sleep` (1–5 each) | 45 s |
| 4 | Guided breathing | Finger on the cradle; speaker paces 4 s in, 2 s hold, 6 s out × 5 (60 s); chest LEDs `breathe`; eyes slow | KY-039 pulse before and after → `hr_bpm`, `hrv_rmssd_ms`, `quality` (camera pulse as backup) | 60 s |
| 5 | Drum | Speaker: "Tap my head as long as you like"; buzzer `start_drum`; `drum_arm(20000)`; buzzer `end_drum` | `drum_rate_per_min`, `drum_regularity`, `count` | 20 s |
| 6 | Chat | Gemini Live question ("What's on today?"); mic streams; eyes `listening` | `speech_rate_wpm`, `pause_ratio`, from the transcript and mic level | 40 s |
| 7 | Goodbye | Short song from Lyria (or RTTTL fallback); motor `shake` (a happy wiggle); eyes → `sleep` | — | 10 s |

**Rules**

- **Every step can be skipped.** If there's no answer within its time, record `null` and move on. A missing value
  never blocks the ritual or the upload.
- **One ritual a day** on its own; a long button press starts one by hand.
- **Safety stays deterministic.** If the transcript matches a crisis trigger (the list lives in `docs/safety.md`),
  the hub stops the ritual and plays a **prerecorded** message with the MIELI number (09 2525 0111) and 112, at a
  normal volume. Eyes go to `concern`, the motor stays still, the buzzer stays silent, and a `safety` event goes to
  the cloud. No LLM is in this path.
- **Uplink.** After step 7, the hub sends one robot payload: the date, every measure above (or `null`), `quality`
  values and the step timings. No audio and no images.

## Code layout for generation

There are three programs to generate. Each has its own `AGENTS.md` under the repo's existing folders.

| Program | Repo path | Language / toolchain | Libraries |
| --- | --- | --- | --- |
| Atech firmware | `firmware/atech-head/` (`project.yaml` + custom module `kaiku_link/`) | C++, `atech` SDK → PlatformIO, ESP32-S3 | Atech modules `st7735_tft`, `rotary_encoder_knob`, `button_module`, `speaker`, `microphone`, `neopixel_grid`, `dc_motor`; ESP32 `WiFi.h`; `PubSubClient` (MQTT); `ArduinoJson` |
| UNO Q sketch | `firmware/unoq-sensors/` (sketch) | Arduino C++ on Zephyr, App Lab | `Arduino_RouterBridge`, `Arduino_Modulino` ≥ 0.6.1, an ADS1115 library |
| UNO Q Python | `firmware/unoq-sensors/` (Python side; calls into `hub/`) | Python 3 on Debian, App Lab | `arduino.app_utils` (Bridge), `paho-mqtt`, `opencv-python-headless`, `numpy`, `scipy` (pulse filter) |

**Order to build and test**

1. Wi-Fi test: both boards on the same network; the UNO Q runs `mosquitto`; the Atech board publishes `head/status`;
   `mosquitto_sub -t 'kaiku/#' -v` shows it.
2. UNO Q sketch: buzzer patterns, knock counter, hall edge, light and pulse reads, with `ping` over the Bridge.
3. Atech firmware: eyes, knob, button, LEDs and motor gestures over MQTT, then speaker RTTTL, then PCM streaming each
   way.
4. Camera: face presence, then face tracking with the pan motor, then the pulse backup (last, optional).
5. Hub ritual state machine, using the sim twins in `sim/` until the hardware is ready.

**Notes for the code generator**

- Don't use Atech's cloud WebSocket gateway or `atech.Board.connect()` at runtime. Use them only for flashing and
  USB debugging. Runtime traffic is MQTT on the LAN.
- Every hardware number in this doc (pulse times, thresholds, windows) goes into one config file per program, not
  into the code.
- The Atech firmware reconnects on its own: Wi-Fi first, then MQTT, with backoff from 1 s up to 10 s.
- Every program logs to serial or stdout as one JSON object per line, so `tools/` can record and replay.

## Assumptions, open questions and risks

**Assumed until someone says otherwise**

- The eyes are the Atech Color Display in the head. The UNO Q's matrix is hidden in the body.
- The mood/energy/sleep dial is the Atech Knob (left ear), confirmed by a press or answered by voice.
- HR/HRV comes from the KY-039 finger sensor; camera pulse is an optional backup.
- The DC motor turns the head left and right through a printed gear; home is the power-on position (D35).
- The Arduino supply (TPX00242) is a 5 V / 3 A USB-C PD supply. VERIFY on its label.

**Open questions**

- [ ] Do we have a powered USB-C PD hub? Without one, the camera won't work.
- [ ] Is the venue Wi-Fi 2.4 GHz, and does it let two devices talk to each other? If not, use a phone hotspot.
- [ ] Is the Atech button a V2.0 module (with the RGB LED)?
- [ ] Atech Speaker on the robot, or voice through the laptop? Keeping it uses the last two ports; dropping it frees
      ports for the purr motor.
- [ ] MQTT topic names: map them onto `contracts/` (`raw.head.*`, `cmd.head`).

**Risks**

| Risk | Effect | Fallback |
| --- | --- | --- |
| Venue Wi-Fi isolates clients | Head and hub can't reach each other | Phone hotspot; hard-coded IP |
| Audio over MQTT stutters | Choppy voice | 200 ms ring buffer; drop to RTTTL and short canned clips |
| 2 GB RAM is tight with OpenCV + Gemini Live + Mosquitto | Slow or killed processes | 640×480 at 15 fps; face detection at 2 Hz; camera pulse only as a backup |
| Pulse too noisy | Bad HR/HRV | KY-039 first, camera second, send `quality`; mark as not measured |
| Motor drift without feedback | Head ends up off-centre | Face tracking is relative; ±80° soft limit; add a KY-035 + magnet (`HAS_HALL 1`) if drift shows |
| Motor vibration trips the knock sensor | False drum counts | Ignore knocks while the motor is moving; the sensor is in the head, the motor in the body |
| Cable bundle through the 19 mm neck axle | Head can't turn freely, plugs pulled | Leave a service loop in the body; limit pan to about ±100° |

## Changes (2026-11-14, to match the printed robot)

The CAD was already printing when this spec landed. Where they disagreed, the physical design won, and the spec's
additions that need no reprint were adopted. See `docs/decisions.md` D31 (D23 on `main` before the merge).

- Both boards sit in the **body**; the camera, display, knob, microphone and KY-031 sit in the **head**.
- Eyes: the Atech **Color Display**, not the UNO Q matrix (it's hidden in the body).
- Dial: the Atech **Knob**, not 1–5 button presses (the button still confirms and starts rituals).
- Added the Atech **LED grids** (chest glow) and the **KY-039/KY-053 pulse**, **KY-054 light** and **KY-035 hall**
  sensors that the CAD already holds. Camera pulse and camera room light became backups.
- Motor: pans the head through a 12:40 gear with **hall homing**, no end stop; no `nod` (the head only pans).
- All **12 Atech ports** are used, so there is one motor and no Atech IMU (the KY-031 handles taps).
- Kept from this spec: the PD hub (now outside, behind the robot), the Modulino Buzzer, the KY-031, MQTT and Bridge
  design, power rules, audio format, safety rules.
- Firmware paths point at the existing modules (`firmware/atech-head/`, `firmware/unoq-sensors/`).
