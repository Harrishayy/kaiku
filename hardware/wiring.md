# Wiring

Ground truth for every pin, voltage and cable (D31 hardware, D32 software, `docs/plans/07-robot-electronics.md`).
Update it the moment you wire something. Each row's "Check" is the bench test that proves it:
`make bench PART=firmware/<board>/bench/<part>` (`make bench-list`). Physical placement: `assembly.md`, `cad/README.md`.

## Power
| From | To | Cable | Check |
|---|---|---|---|
| Arduino PD supply TPX00242 (VERIFY 5 V / 3 A on the label) | powered USB-C hub PD input (behind the robot) | USB-C | hub LED on |
| USB-C hub host cable | UNO Q USB-C (through the rear opening) | USB-C | UNO Q boots; `lsusb` lists the hub |
| Arduino USB Camera (head) | hub USB-A port | its USB-A cable, down the neck, out the rear opening | `bench/camera` |
| hub USB-A port **or** a second supply | Atech port 8 (USB-C module) | USB-A → C **data** cable for flashing | board LED on |

- Power the UNO Q **through the PD hub, not VIN**: from VIN without USB-C negotiation its USB controller boots in
  device mode and the camera is not detected.
- Atech ports share 12 V / 5 V / 3.3 V / GND (no published current ratings) between the motor, speaker, display and
  LED grids: ramp the motor (100 ms), keep LED brightness ≤ 0.6, never run the motor and a loud speaker together.
- UNO Q headers + Qwiic = **3.3 V**; JCTL and bottom connectors = **1.8 V**: wire nothing there. A4/A5 are not `Wire`
  on the UNO Q; leave them free. Run every KY sensor at 3.3 V so its signal stays 3.3 V logic.

## UNO Q (node `sensors`), in the body
| Part | Pin | Voltage | Notes | Check |
|---|---|---|---|---|
| KY-031 knock S / + / − | D2 / 3V3 / GND | 3.3 V | under the head top, 3 jumpers down the neck; interrupt on CHANGE, idle level calibrated at boot, `INPUT_PULLUP` | `bench/knock` |
| ~~KY-035 hall~~ | — | — | **Not fitted** (no magnet; D35). Home = head position at power-on (`HAS_HALL 0` in both firmwares). If one turns up: out → **A1** (analog), magnet 6×3 mm in the turntable pocket, set `HAS_HALL 1` | `bench/hall` |
| ~~KY-054 light~~ | — | — | **Not fitted** (D35): room light comes from the camera (`[unoq] light_source = "camera"`) | — |
| KY-053 ADS1115 SDA / SCL / + / − | header SDA / SCL (`Wire`) / 3V3 / GND | 3.3 V | address 0x48; not A4/A5, not Qwiic | `bench/ky039` |
| KY-039 pulse S / + / − | KY-053 A0 / 3V3 / GND | 3.3 V | under the lid finger cradle | `bench/ky039` |
| Modulino Buzzer | Qwiic connector | 3.3 V | **`Wire1`**, not `Wire`; 0x1E 7-bit (0x3C 8-bit, verified 2026-11-14); ~6.4 mA; longer Qwiic cable if the 5 cm one doesn't reach | `bench/buzzer` |
| LED matrix | on board | — | hidden in the body: status only | — |

## Atech board (node `head`, 14-port), in the body; all 12 ports used
Confirm GPIOs with `atech validate`; never hard-code them. Head modules are cabled up through the neck.

| Module | Port(s) | Lives in | Check |
|---|---|---|---|
| Speaker (MAX98357A) | 1–2 | body, right-wall grille | `bench/speaker` |
| Color Display (st7735_tft, eyes) | 3–4 | head, tuning window (connector edge up) | `bench/display` |
| Knob (rotary_encoder_knob, ear dial) | 5–6 | head, left ear | `bench/knob` |
| DC Motor V2.3 (pan, 12:40 gear) | 13 | body, under the pan base | `bench/motor` |
| Microphone (ICS-43434) | 9–10 | head, right-ear grille (sound hole against it) | `bench/mic` |
| Button (active low) | 7 | lid, square opening | `bench/button` |
| LED Grid left / right (neopixel_grid) | 11 / 14 | body, behind the chest louvres | `bench/leds` |

The neck carries 6 Atech cables, 3 jumpers and the camera cable through a 19 mm axle: feed the plugs through one at
a time, the camera's USB-A plug first, and leave a service loop. Charge-only USB-C cables can't program the Atech board.
