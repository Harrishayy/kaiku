# Wiring

Fill in as you wire. Every pin, voltage and level shift. Photo of each harness in `hardware/photos/` if useful.

| Node | Part | Pin | Voltage | Notes |
|---|---|---|---|---|
| UNO Q | KY-053 ADS1115 (I²C) | SDA/SCL | 3.3 V | KY-039 pulse on A0 of the ADS1115 |
| UNO Q | ~~KY-050 ultrasonic~~ | — | — | Dropped 2026-11-14: presence comes from vision. If it comes back: **ECHO via KY-051 level shifter / divider** |
| UNO Q | KY-054 light | A? | 3.3 V | |
| UNO Q | KY-035 hall | D? | 3.3 V | pan homing magnet on turntable |
| UNO Q | top button | D? | 3.3 V | long-press = manual safety trigger |
| UNO Q | KY-031 knock | D2 | 3.3 V | interrupt on CHANGE; under the head top, 3 wires through the neck |
| UNO Q | KY-035 hall | D3 (VERIFY) | 3.3 V | home = magnet in the turntable |
| UNO Q | KY-054 light | A0 (VERIFY) | 3.3 V | lid window |
| UNO Q | KY-053 ADS1115 | SDA/SCL header (`Wire`) | 3.3 V | KY-039 pulse on its A0 |
| UNO Q | Modulino Buzzer | Qwiic (`Wire1`) | 3.3 V | I2C 0x3C |
| Atech | Speaker 1–2, Display 3–4, Knob 5–6, Motor 7, Mic 9–10, Button 11, LED grids 13, 14 | — | — | port plan from `docs/kaiku_robot_electronics_specs.md`; confirm GPIOs with `atech validate` |
