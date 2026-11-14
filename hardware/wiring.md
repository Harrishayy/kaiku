# Wiring

Fill in as you wire. Every pin, voltage and level shift. Photo of each harness in `hardware/photos/` if useful.

| Node | Part | Pin | Voltage | Notes |
|---|---|---|---|---|
| UNO Q | KY-053 ADS1115 (I²C) | SDA/SCL | 3.3 V | KY-039 pulse on A0 of the ADS1115 |
| UNO Q | ~~KY-050 ultrasonic~~ | — | — | Dropped 2026-11-14: presence comes from vision. If it comes back: **ECHO via KY-051 level shifter / divider** |
| UNO Q | KY-054 light | A? | 3.3 V | |
| UNO Q | KY-035 hall | D? | 3.3 V | pan homing magnet on turntable |
| UNO Q | top button | D? | 3.3 V | long-press = manual safety trigger |
| Atech | IMU, display, encoder, motor driver, LEDs | — | — | VERIFY module pinouts in Atech docs |
