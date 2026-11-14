# Kaiku robot: electronics spec

Nov 14, 2026 · @Xavier

## Overview

The Kaiku home robot has two controllers that talk directly over the venue Wi-Fi using MQTT. The broker runs on the UNO Q, so no cloud sits in the robot's own control loop.

- **Head node: Atech motherboard (ESP32-S3).** Handles the button, speaker, microphone and one DC motor. It is the robot's voice, ears and movement.
- **Body node: Arduino UNO Q (2 GB).** It has two processors:
  - **Linux side (Qualcomm QRB2210, Debian).** Runs the Python `hub/` (ritual state machine, safety gate, uplink to Modal) and the Mosquitto broker. It also reads the Arduino USB Camera.
  - **Microcontroller side (STM32U585).** Drives the 8×13 LED matrix (the eyes), the Modulino Buzzer on Qwiic and the KY-031 knock sensor (the drum on top of the head).

In the README's terms, both boards together are **Source 1: Robot**. Only derived numbers leave the home. Camera frames and raw audio stay on the UNO Q and are never stored.

&#91;embedded content: System topology · 2 boards, 1 camera, 1 cloud link\]

The hub on the UNO Q is the centre: the head reaches it over MQTT, the STM32 over the Bridge, the camera over USB. Only the hub talks to Modal.

## Bill of materials

| Part | Exact part / chip | Interface | Lives on | Job in Kaiku |
| --- | --- | --- | --- | --- |
| Atech motherboard | ESP32-S3, 14-port | USB-C, Wi-Fi 2.4 GHz only | Head | Head controller, MQTT client |
| Atech Button | `button_module`, active-low switch | GPIO, 1 port | Head | Start / confirm / talk |
| Atech Speaker | MAX98357A I2S amp | I2S, 2 ports | Head | Robot voice, music, breathing cues |
| Atech Microphone | ICS-43434 I2S MEMS | I2S, 2 ports | Head | Speech for voice chat and speech pace |
| Atech DC Motor | DRV8833 H-bridge | 2 GPIO (IN1, IN2), 1 port | Head | Head turn and nod gestures |
| [Arduino UNO Q 2 GB](https://docs.arduino.cc/hardware/uno-q/) | QRB2210 (Linux) + STM32U585 (MCU) | Wi-Fi, USB-C | Body | Hub, broker, eyes, sensors |
| UNO Q LED matrix | 8×13 blue, 3-bit grayscale, on board | MCU internal | Body | Animated eyes |
| [Arduino USB Camera](https://docs.arduino.cc/hardware/usb-camera/) | UVC video + UAC mic, ring light, autofocus | USB via powered USB-C hub | Body | Presence, get-up time, room light, optional pulse |
| [Modulino Buzzer](https://docs.arduino.cc/hardware/modulino-buzzer/) (ABX00108) | STM32C011F4 + PKLCS1212E4001, I2C 0x3C | Qwiic (Wire1), 3.3 V | Body | Chimes and alerts |
| KY-031 knock sensor | Spring switch + 10 kΩ resistor | 1 digital GPIO, 3.3 V | Top of head, wired to UNO Q | Drumming energy |
| Powered USB-C hub (PD) | Any USB-C hub with PD input | USB-C | Body | Powers the UNO Q and lets it host the camera |
| Arduino power supply | 5 V / 3 A USB-C PD | USB-C | — | Main power |

Not in this build: LoRa friend link, physical mood dial, dedicated heart-rate sensor.

## Power

Power the UNO Q through a **powered USB-C PD hub**, not through VIN. The camera only works when the UNO Q acts as a USB host, and that happens reliably only on a PD hub.

| Rail | Source | Feeds | Notes |
| --- | --- | --- | --- |
| 5 V / 3 A USB-C PD | Arduino supply → hub PD input | Hub → UNO Q + USB Camera | UNO Q accepts USB-C 5 V up to 3 A, or VIN 7–24 V, or the 5 V pin |
| USB-C 5 V | Second USB-C supply, or a hub USB port | Atech motherboard | Every port carries 12 V, 5 V, 3.3 V and GND; power pins are shared; Atech publishes no current ratings |
| 3.3 V (Qwiic) | UNO Q | Modulino Buzzer | About 6.4 mA while sounding |
| 3.3 V (header) | UNO Q 3V3 pin | KY-031 | Run it at 3.3 V so the signal stays in 3.3 V logic |

Rules for the code and the build:

- **USB host gotcha.** If the UNO Q is powered from VIN with no USB-C negotiation, its USB controller boots in device mode and the camera is not detected. Arduino's documented setup is a PD hub powered by 5 V / 3 A.
- **Motor brown-outs.** The DC motor shares the Atech rails with the speaker and microphone. Ramp `set_speed` over about 100 ms instead of jumping to ±255. Never run the motor and loud speaker output at full power at the same time.
- **Logic levels.** UNO Q headers and Qwiic are 3.3 V. JCTL and the bottom connectors are 1.8 V: do not wire anything to them.

## Network and messaging

The Atech board talks to the UNO Q directly over the venue Wi-Fi. It uses MQTT from **custom firmware code**, not Atech's built-in Wi-Fi transport. Atech's Wi-Fi mode sends everything through its cloud gateway (`wss://gateway.atech.dev`), and Atech documents no MQTT support. Atech does allow firmware to use Wi-Fi directly and to add C++ to the main loop or as a custom module. That is how the MQTT client goes in.

**Setup**

- Broker: Mosquitto on the UNO Q Linux side, port 1883, LAN only, with a username and password.
- Addressing: give the UNO Q a hostname (`kaiku-hub.local`) and also print its IP on boot. Put the IP in the Atech firmware as a fallback, because mDNS is often blocked on venue networks.
- The Atech board joins **2.4 GHz** networks only. If the venue SSID is 5 GHz only, or blocks device-to-device traffic (client isolation), switch both boards to a phone hotspot. Test this first, before anything else.
- MQTT client IDs: `kaiku-head` (Atech) and `kaiku-hub` (UNO Q). The head sets a last-will message `{"online":false}` on `kaiku/head/status`.

**Topics.** These names are a proposal; map them onto `contracts/` so both ends validate the same schema. Every JSON message carries `ts` (ms since boot) and `seq`.

| Topic | From → to | Payload | QoS |
| --- | --- | --- | --- |
| `kaiku/head/status` | head → hub | `{online, rssi, fw}` every 10 s, retained | 1 |
| `kaiku/head/button` | head → hub | `{event: "press"\|"release"\|"long", ms}` | 1 |
| `kaiku/head/mic/level` | head → hub | `{rms, peak}` at 10 Hz | 0 |
| `kaiku/head/mic/pcm` | head → hub | binary, 16-bit LE mono 16 kHz, 640 B (20 ms) a frame | 0 |
| `kaiku/head/speaker/pcm` | hub → head | binary, same format | 0 |
| `kaiku/head/speaker/cmd` | hub → head | `{op: "tone"\|"rtttl"\|"stop"\|"volume", ...}` | 1 |
| `kaiku/head/motor/cmd` | hub → head | `{op: "gesture", name: "look"\|"nod"\|"shake"\|"home"}` or `{op: "speed", value: -255..255, ms}` | 1 |
| `kaiku/head/motor/state` | head → hub | `{moving, last_gesture}` | 0 |
| `kaiku/head/mic/cmd` | hub → head | `{stream: true\|false}` | 1 |
| kaiku/hub/heartbeat | hub → head | {ritual\_state} every 1 s; head stops motor and speaker after 5 s of silence | 0 |

The UNO Q's own parts (eyes, buzzer, knock, camera) talk to the hub over the internal Bridge, not over MQTT (see the UNO Q section). The hub republishes their events on `kaiku/body/...` so `tools/` can tail and replay everything.

**Safety rule for the head firmware.** If no `kaiku/hub/heartbeat` message arrives for 5 s, stop the motor and the speaker. Never move the motor without a command from the hub.

## Atech head board (ESP32-S3)

Build the head firmware with the open-source `atech` Python SDK (`pip install atech`, Python 3.10+). It generates `main.cpp` and `platformio.ini` from a `project.yaml`, then compiles and flashes offline. Add Wi-Fi + MQTT as inline loop code or as a custom module. The first build downloads about 2.4 GB of compiler, so do that now on venue Wi-Fi.

**Board facts.** The 14-port board has 12 module ports: 1–7, 9–11 and 13–14. Port 8 is USB-C and port 12 is reset. Each port has 12 V, 5 V, 3.3 V, GND and two data lines (D1, D2) wired to ESP32-S3 GPIOs. Double-width modules take two neighbouring ports on the same side: 1–2, 2–3, 3–4, 4–5, 5–6, 9–10, 10–11 or 13–14. USB: 115200 baud, one JSON object per line.

**Proposed port layout.** Confirm the GPIO numbers with `atech validate`; don't hard-code them from this table.

| Module | Ports | Why there |
| --- | --- | --- |
| Speaker | 1–2 | Front side, faces the person |
| Microphone | 9–10 | Other side from the speaker and motor, so less noise reaches it |
| Button | 11 | Next to the mic, reachable on the head's top or back |
| DC Motor | 13 | Away from the mic |

**Button** (`button_module`)

- Pins: Data A is the switch, active low. Data B is an RGB indicator LED (V2.0 modules only).
- API: `is_pressed`, `was_pressed`, `was_released` (the last two fire once per edge).
- Firmware behaviour: debounce 20 ms. A long press is 800 ms or more. Publish press, release and long to `kaiku/head/button`. Light the LED (if V2.0) while the robot is listening.

**Speaker** (`speaker`, MAX98357A)

- Pins: port 1 = LRCLK, BCLK. Port 2 = DIN.
- API: `play_tone(freq, ms)` (blocking), `play_note`, `play_rtttl` (non-blocking), `rest`, `stop`, `set_volume(0.0–1.0)`, `write_samples` (raw 16-bit mono to I2S), `play_pcm` (base64 16-bit mono PCM chunks from the host).
- **Audio format: 16 kHz, mono, 16-bit.** The board has no MP3 or WAV decoder. The hub must decode and resample Gemini Live and Lyria audio to 16 kHz mono before sending it.
- Firmware behaviour: subscribe to `kaiku/head/speaker/pcm` and push each frame to `write_samples` through a ring buffer of about 200 ms, to absorb Wi-Fi jitter. On underrun, play silence, not the last frame. Never call blocking `play_tone` from the MQTT callback; use `play_rtttl` or the sample path.

**Microphone** (`microphone`, ICS-43434)

- Pins: port 1 = LR, WS. Port 2 = SCK, SD.
- API: `get_sound_level` (RMS 0–32767), `is_sound_detected` (threshold), `get_peak_amplitude` (resets on read), `get_samples`, `start_recording` / `stop_recording` (heap buffer, 10 s maximum), `set_channel` (left or right through LR).
- Atech does not document the sample rate or bit depth. Set and verify **16 kHz, 16-bit** in firmware, so the mic matches the speaker format.
- Firmware behaviour: always publish `mic/level` at 10 Hz. Stream `mic/pcm` only between `{stream:true}` and `{stream:false}`. While the speaker is playing, mark frames `echo=1` in a header byte, or mute the mic, so the robot doesn't hear itself.

**DC Motor** (`dc_motor`, DRV8833)

- Pins: Data A = IN1, Data B = IN2.
- API: `forward(speed)` / `reverse(speed)` with speed 0–255. `set_speed(-255..255)`, where the sign is the direction. `stop` lets it coast; `brake` stops it actively.
- **No position feedback.** It is a plain DC motor, not a servo, so the firmware can't turn to an angle. Gestures are timed pulses:
  - `look`: turn about 300 ms one way, then brake.
  - `nod` / `shake`: two short alternating pulses of about 120 ms each, then brake.
  - `home`: drive slowly (speed about 80) toward a mechanical end stop for 800 ms, then brake. Use it at boot and after every gesture sequence, so drift doesn't build up.
- Firmware behaviour: ramp speed over about 100 ms. Never run longer than 1 s per command. Ignore commands while a gesture is running. Publish `motor/state`. All pulse times need tuning on the real head.

## Arduino UNO Q (body node)

The UNO Q needs two programs: a Python app on Linux and an Arduino sketch on the STM32. They talk only through the **Bridge**, an RPC router reached on Linux through `/var/run/arduino-router.sock`. Use Arduino App Lab, which deploys the sketch and the Python together.

**What runs where**

| Side | Chip | Logic | Runs |
| --- | --- | --- | --- |
| Linux (MPU) | Qualcomm QRB2210, Debian | 1.8 V on the bottom connectors and JCTL | `hub/`, Mosquitto, camera pipeline, Gemini Live / Lyria clients, uplink to Modal |
| MCU | STM32U585, Cortex-M33 160 MHz, Arduino core on Zephyr | 3.3 V on the UNO headers, JSPI and Qwiic | LED-matrix eyes, Modulino Buzzer, KY-031 knock |

**Bridge API.** Sketch: `#include <Arduino_RouterBridge.h>`, then `Bridge.begin()` in `setup()`. Python: `from arduino.app_utils import App, Bridge`, then `App.run(user_loop=loop)`.

- `Bridge.provide(name, fn)` registers a function the other side can call.
- `Bridge.call(name, args...)` calls it and waits for the answer.
- `Bridge.notify(name, args...)` sends one-way, without waiting.

Functions the **sketch provides** (Python calls them):

| Name | Args | Effect |
| --- | --- | --- |
| `eyes_set` | `expr: str` | Shows one expression: `sleep`, `open`, `blink`, `look_left`, `look_right`, `happy`, `listening`, `concern` |
| `eyes_breathe` | `inhale_ms, hold_ms, exhale_ms, cycles` | Eyes grow and shrink in brightness to pace the breathing |
| `buzz` | `freq_hz, ms` | One tone on the Modulino Buzzer |
| `buzz_pattern` | `name: str` | `wake`, `ok`, `start_drum`, `end_drum`, `alert` |
| `drum_arm` | `window_ms` | Starts a drumming window; the sketch counts knocks |
| `ping` | — | Returns firmware version, for `make doctor` |

Functions **Python provides** (the sketch notifies them):

| Name | Args | When |
| --- | --- | --- |
| `on_knock` | `t_ms` | Every knock, debounced |
| `on_drum_done` | `count, mean_interval_ms, cv` | When the drum window ends |
| `mcu_ready` | — | Once after boot; Python re-sends the eyes state |

**LED-matrix eyes.** Use `Arduino_LED_Matrix`: `matrix.begin()`, `matrix.setGrayscaleBits(3)` for 8 brightness levels, then `matrix.draw(uint8_t[104])` row by row (8 rows × 13 columns). Draw two 4×5 eyes with a 1-column gap. Blink every 3–6 s, chosen at random, with a 120 ms blink; skip blinks during `eyes_breathe`. Expressions are frames stored as constants in the sketch.

**Pin plan (MCU side)**

| Signal | UNO Q pin | Notes |
| --- | --- | --- |
| KY-031 S | D2 | Interrupt on CHANGE; 3.3 V logic |
| KY-031 + | 3V3 | — |
| KY-031 − | GND | — |
| Modulino Buzzer | Qwiic connector | **`Wire1`**, not `Wire` (Qwiic is a separate I2C bus); 3.3 V |

On the UNO Q, A4/A5 are not the default `Wire` bus, unlike a classic UNO. Leave them free.

## Arduino USB Camera

The camera is a standard USB webcam: video shows up as a USB Video Class device and its microphone as a separate USB Audio Class device. Read it from Python on the UNO Q Linux side with OpenCV (`cv2.VideoCapture`) through the PD hub. No driver is needed.

- **Hardware.** Autofocus lens, adjustable LED ring light, built-in mic, integrated USB-A cable. It can capture up to 4K MJPEG, but **use 640×480 at 15 fps** on the 2 GB UNO Q to leave CPU for the hub.
- **Camera mic.** Not used. The Atech mic is the speech mic. Leave the camera mic unopened so the two don't conflict.
- **Privacy.** Process frames in memory and drop them. Never write frames to disk and never send them off the board. Only the derived numbers below leave the device.

**What the camera pipeline outputs**

| Measure | Method | Output | Rate |
| --- | --- | --- | --- |
| Person present | Face detection (OpenCV Haar or YuNet) | `present: bool`, face box | 2 Hz while idle |
| Get-up time | Clock time of the first "present" seen after 04:00 local each day | `first_seen_local` | Once a day |
| Room light | Mean luminance (Y channel) of a frame with **auto-exposure and auto-gain locked** and the ring light **off** | `room_lux_index` 0–255 | Once a minute + at ritual start |
| Pulse (optional) | Remote photoplethysmography: mean green channel over a forehead box, band-pass 0.7–3 Hz, 30 s window during breathing | `hr_bpm`, `hrv_rmssd_ms`, `quality` 0–1 | Once a ritual |

- **Room light.** The camera's auto-exposure hides how dark the room really is. Lock exposure through `v4l2-ctl` (`exposure_auto=1`, a fixed `exposure_absolute`) before sampling. Store the values as a relative index against the person's own baseline, not as lux.
- **Pulse.** Camera-based HRV is noisy. Send `quality` with every reading and let the cloud drop readings below 0.6. Keep the ring light **on** at a fixed level during breathing, so lighting stays even. Ask the person to sit still at about 50 cm. If there's no time for this, drop HR/HRV from the robot and mark it "not measured"; don't send fake values.
- **Wake trigger.** When a face is present for 2 s, call `on_person_arrived` in the hub, which starts the ritual. That's how "the ritual runs when the person walks up" from the README.

## Modulino Buzzer (ABX00108)

The buzzer is a small I2C board: an STM32C011F4 drives a PKLCS1212E4001 piezo, and the host sends it tones over Qwiic. Plug it into the UNO Q's Qwiic connector with the 5 cm cable that comes with it.

- **Address:** 0x3C by default (hardware address 0x1E). Can be changed in firmware.
- **Power:** 3.3 V through Qwiic, about 6.4 mA while sounding.
- **Library:** `Arduino_Modulino` version 0.6.1 or later, which added UNO Q support. In App Lab it does not install all its dependencies automatically on the UNO Q, so add them by hand if the build fails.
- **API:** `#include <Arduino_Modulino.h>`, `ModulinoBuzzer buzzer;`, then `Modulino.begin(); buzzer.begin();` in `setup()`, then `buzzer.tone(freq_hz, duration_ms)`.
- **Timing gotcha.** `tone()` is **non-blocking**, and the buzzer never reports back when it has finished. For a pattern, the sketch has to wait the same duration (with `millis()`, not `delay()`, so the eyes keep animating) before sending the next note.

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

The KY-031 is a spring contact with a 10 kΩ resistor and three pins (S, +, −). It outputs one on/off signal per tap, so it counts taps and their timing, **not** how hard each tap is. In Kaiku, "drumming energy" therefore means tap rate and rhythm.

- **Mounting.** Screw it flat under the top of the head, or tape it with foam tape so taps reach the spring. Keep it away from the motor, or motor vibration will trigger it. Ignore knocks while the motor is moving: the hub sends the motor state over the Bridge.
- **Wiring.** S → D2, + → 3V3, − → GND. Powering it at 3.3 V keeps the signal at 3.3 V.
- **Polarity differs between sellers.** Some boards idle HIGH and go LOW on a knock; others do the opposite. At boot, read the pin for 500 ms with the head still, take that as the idle level, and treat any change away from it as a knock. Use `INPUT_PULLUP` if the idle reading floats.
- **Detection.** Interrupt on CHANGE (`attachInterrupt(digitalPinToInterrupt(2), …)`); fall back to polling at 1 kHz if D2 has no interrupt on this core. The spring bounces, so treat everything within 40 ms of a knock as the same knock.
- **Drum window.** `drum_arm(20000)` opens a 20 s window. The sketch stores knock times and, when the window closes, notifies `on_drum_done(count, mean_interval_ms, cv)`. `cv` is the coefficient of variation of the intervals, a rhythm-regularity number. The hub turns this into `drum_rate_per_min` and `drum_regularity` for the cloud.

## Wiring table

Every physical connection, in one place.

| From | To | Cable / pins | Check |
| --- | --- | --- | --- |
| Arduino 5 V / 3 A PD supply | USB-C hub PD input | USB-C | Hub LED on |
| USB-C hub host cable | UNO Q USB-C | USB-C | UNO Q boots; `lsusb` lists the hub |
| Arduino USB Camera | Hub USB-A port | Integrated USB-A cable | `v4l2-ctl --list-devices` shows it |
| Hub USB-A port, or a second supply | Atech port 8 (USB-C) | USB-A → C **data** cable for flashing, any cable after that | Board LED on |
| Atech Speaker | Atech ports 1–2 | Snap-in | `play_rtttl` test |
| Atech Microphone | Atech ports 9–10 | Snap-in | `mic/level` rises when you talk |
| Atech Button | Atech port 11 | Snap-in | `button` event |
| Atech DC Motor | Atech port 13 | Snap-in; motor leads to the module terminals | `home` gesture moves the head |
| Modulino Buzzer | UNO Q Qwiic | Qwiic cable | I2C scan on `Wire1` finds 0x3C |
| KY-031 S | UNO Q D2 | Dupont jumper | Knock prints in the serial monitor |
| KY-031 + | UNO Q 3V3 | Dupont jumper | — |
| KY-031 − | UNO Q GND | Dupont jumper | — |

Charge-only USB-C cables can't program the Atech board.

## Behaviour: the morning ritual

The hub runs the ritual as a state machine of about 3 minutes. Each step names what the hardware does and what it measures. Step lengths are starting values for tuning.

| # | State | Robot does (outputs) | Measures (inputs) | Length |
| --- | --- | --- | --- | --- |
| 0 | Idle | Eyes `sleep`, motor still, mic level only | Camera at 2 Hz for a face; room light once a minute | — |
| 1 | Wake | Buzzer `wake`; eyes `open` → `blink`; motor `look` then `home` | Get-up time (first face of the day); room light at ritual start | 3 s |
| 2 | Greet | Speaker: greeting from Gemini Live; eyes `happy` | — | 10 s |
| 3 | Check-in dial | Asks mood, then energy, then sleep. Each answer is **1–5 button presses within 4 s** (buzzer `ok` after each) or a spoken number | `mood`, `energy`, `sleep` (1–5 each) | 45 s |
| 4 | Guided breathing | Speaker paces 4 s in, 2 s hold, 6 s out × 5 (60 s); `eyes_breathe(4000,2000,6000,5)`; ring light on, fixed | Camera pulse → `hr_bpm`, `hrv_rmssd_ms`, `quality` | 60 s |
| 5 | Drum | Speaker: "Tap my head as long as you like"; buzzer `start_drum`; `drum_arm(20000)`; buzzer `end_drum` | `drum_rate_per_min`, `drum_regularity`, `count` | 20 s |
| 6 | Chat | Gemini Live question ("What's on today?"); mic streams; eyes `listening` | `speech_rate_wpm`, `pause_ratio`, from the transcript and mic level | 40 s |
| 7 | Goodbye | Short song from Lyria (or RTTTL fallback); motor `nod`; eyes → `sleep` | — | 10 s |

**Rules**

- **Every step can be skipped.** If there's no answer within its time, record `null` and move on. A missing value never blocks the ritual or the upload.
- **One ritual a day** on its own; a long button press starts one by hand.
- **Safety stays deterministic.** If the transcript matches a crisis trigger (the list lives in `docs/safety.md`), the hub stops the ritual and plays a **prerecorded** message with the MIELI number (09 2525 0111) and 112, at a normal volume. Eyes go to `concern`, the motor stays still, the buzzer stays silent, and a `safety` event goes to the cloud. No LLM is in this path.
- **Uplink.** After step 7, the hub sends one robot payload: the date, every measure above (or `null`), `quality` values and the step timings. No audio and no images.

## Code layout for generation

There are three programs to generate. Each has its own `AGENTS.md` under the repo's existing folders.

| Program | Repo path | Language / toolchain | Libraries |
| --- | --- | --- | --- |
| Head firmware | `firmware/atech-head/` (`project.yaml` + custom module `kaiku_link/`) | C++, `atech` SDK → PlatformIO, ESP32-S3 | Atech modules `button_module`, `speaker`, `microphone`, `dc_motor`; ESP32 `WiFi.h`; `PubSubClient` (MQTT); `ArduinoJson` |
| Body sketch | `firmware/unoq-body/sketch/` | Arduino C++ on Zephyr, App Lab | `Arduino_RouterBridge`, `Arduino_LED_Matrix`, `Arduino_Modulino` ≥ 0.6.1 |
| Body Python | `firmware/unoq-body/python/` (calls into `hub/`) | Python 3 on Debian, App Lab | `arduino.app_utils` (Bridge), `paho-mqtt`, `opencv-python-headless`, `numpy`, `scipy` (pulse filter) |

**Order to build and test**

1. Wi-Fi test: both boards on the same network; the UNO Q runs `mosquitto`; the Atech board publishes `head/status`; `mosquitto_sub -t 'kaiku/#' -v` shows it.
2. Body sketch: eyes frames, buzzer patterns, knock counter, with `ping` over the Bridge.
3. Head firmware: button and motor gestures over MQTT, then speaker RTTTL, then PCM streaming each way.
4. Camera: face presence, then locked-exposure room light, then the pulse (last, optional).
5. Hub ritual state machine, using the sim twins in `sim/` until the hardware is ready.

**Notes for the code generator**

- Don't use Atech's cloud WebSocket gateway or `atech.Board.connect()` at runtime. Use them only for flashing and USB debugging. Runtime traffic is MQTT on the LAN.
- Every hardware number in this doc (pulse times, thresholds, windows) goes into one config file per program, not into the code.
- The head firmware reconnects on its own: Wi-Fi first, then MQTT, with backoff from 1 s up to 10 s.
- Every program logs to serial or stdout as one JSON object per line, so `tools/` can record and replay.

## Assumptions, open questions and risks

**Assumed until someone says otherwise**

- The eyes are the UNO Q's built-in 8×13 LED matrix; there is no Atech display.
- HR/HRV comes from the camera (remote photoplethysmography) and is optional. There is no pulse sensor.
- The mood/energy/sleep dial is answered with button presses or by voice; there is no knob module.
- The DC motor turns the head left and right, against a mechanical end stop.
- The Arduino supply is a 5 V / 3 A USB-C PD supply.

**Open questions**

- [ ] Do we have a powered USB-C PD hub? Without one, the camera won't work.
- [ ] Is the venue Wi-Fi 2.4 GHz, and does it let two devices talk to each other? If not, use a phone hotspot.
- [ ] Is the Atech button a V2.0 module (with the RGB LED)?
- [ ] What does the motor physically move, and is there an end stop?
- [ ] MQTT topic names: map them onto `contracts/` or keep these?

**Risks**

| Risk | Effect | Fallback |
| --- | --- | --- |
| Venue Wi-Fi isolates clients | Head and hub can't reach each other | Phone hotspot; hard-coded IP |
| Audio over MQTT stutters | Choppy voice | 200 ms ring buffer; drop to RTTTL and short canned clips |
| 2 GB RAM is tight with OpenCV + Gemini Live + Mosquitto | Slow or killed processes | 640×480 at 15 fps; face detection at 2 Hz; the pulse runs only during breathing |
| Camera pulse too noisy | Bad HR/HRV | Send `quality`; mark as not measured |
| Motor drift without feedback | Head ends up off-centre | `home` against the end stop after every sequence |
| Motor vibration trips the knock sensor | False drum counts | Ignore knocks while the motor is moving; mount the sensor away from it |

## Sources

- [Atech developer documentation](https://atech.dev/docs): board, ports, transport, module APIs
- [atech Python SDK on PyPI](https://pypi.org/project/atech/): build pipeline, custom modules, Wi-Fi note
- [Arduino UNO Q pinout and specifications (Mischianti)](https://mischianti.org/arduino-uno-q-high-resolution-pinout-datasheet-schema-and-specifications/): logic levels, Qwiic on `Wire1`
- [Arduino UNO Q datasheet](https://mischianti.org/wp-content/uploads/2026/08/Arduino_UNO_Q_ABX00162-ABX00173-datasheet.pdf): power input, MCU duties
- [Arduino UNO Q Bridge (Mischianti)](https://mischianti.org/?p=36047): `call`, `notify`, `provide`
- [UNO Q LED matrix (Waveshare)](https://docs.waveshare.com/Arduino-UNO-Q-02016/Hardware-Interfaces): `Arduino_LED_Matrix`, grayscale
- [Arduino forum: USB camera on UNO Q](https://forum.arduino.cc/t/connecting-usb-camera-to-uno-q/1412062): USB host mode and the PD hub
- [Arduino USB Camera docs](https://docs.arduino.cc/hardware/usb-camera/) and [launch coverage](https://esp32.co.uk/arduino-usb-camera-4k-uno-q-ventuno-q/)
- [Modulino Buzzer datasheet](https://docs.arduino.cc/resources/datasheets/ABX00108-datasheet.pdf), [DigiKey tutorial](https://forum.digikey.com/t/arduino-modulino-buzzer-tutorial/44710), [Arduino\_Modulino releases](https://repos.ecosyste.ms/hosts/GitHub/repositories/arduino-libraries%2FArduino_Modulino/releases?sha=0.5.2)
- [KY-031 (Joy-IT)](https://sensorkit.joy-it.net/en/sensors/ky-031) and [Circuits DIY](https://www.circuits-diy.com/ky-031-knock-tap-sensor-module/)
