# Part dimensions (for CAD)

This is the single place for the physical size of every part that goes inside Kaiku's shell. All values are in mm.
"Datasheet" means the vendor published the number. "MEASURE" means nobody has published it yet: measure the
part with calipers and replace the cell, adding your initials and the date.
The datasheets themselves live in `hardware/datasheets/`, which is gitignored. Its `SOURCES.md` lists where each
PDF came from, so you can download them again.

Order of axes: **W × D × H**. For boards, W × D is the PCB outline and H is the full stack height, including parts.

## Arduino

| Part | SKU | Outline W × D | Height / thickness | Mounting | Weight | Notes |
|---|---|---|---|---|---|---|
| Arduino UNO Q | ABX00162 / ABX00173 | 68.58 × 53.34 | bottom-side parts < 2; top height MEASURE | 4× R1.6 holes, UNO R3 hole pattern | MEASURE | UNO R3 form factor, so UNO shields and standoff patterns fit. Datasheet §12 has the full drawing. |
| Arduino USB Camera | TPX00246 | 70 × 40 | 90 | MEASURE (clip or stand) | 105 g | Body only. The USB-A cable is 1 m. Lens: F/2.0, FOV 80° diag / 63° H / 50° V, autofocus from 20 cm. **The plug is USB-A, so the UNO Q needs a USB-C hub or adapter.** |
| Modulino Buzzer | ABX00108 | 41 × 25.36 | PCB 1.6 ±0.2; stack height MEASURE | 4× Ø3.2 holes, hole spacing 32 (H) × 16 (V) | MEASURE | Connects over Qwiic/I²C. Buzzer: PKLCS1212E4001. |

## Atech kit

Atech publishes no mechanical data (as of 2026-11-14 there is none on atech.dev or in llms.txt), so every module
needs measuring. Where a chip-level number affects the enclosure (an aperture, a viewing angle or an acoustic
port), it is given in the Notes column.

| Module | Atech ID | Chip | Outline W × D | Height | Mounting | Notes |
|---|---|---|---|---|---|---|
| Motherboard | — | ESP32-S3 | ~127 × 68 (est.†) | MEASURE | MEASURE | 12 module ports (1–7, 9–11, 13–14). Port 8 is USB-C and port 12 is reset. Leave clearance for the USB-C plug. |
| Color Display | `st7735_tft` | ST7735S | MEASURE | MEASURE | MEASURE | 160×80 TFT. Measure the active area for the bezel cut-out. |
| Big Screen | `st7789_tft` | ST7789 | MEASURE | MEASURE | MEASURE | 320×240 TFT. Measure the active area for the bezel cut-out. |
| LED Grid | `neopixel_grid` | WS2812B ×9 | ~22 × 22 (est.†) | MEASURE | MEASURE | Each LED is a 5050 package (5.0 × 5.0). A diffuser goes over the 3×3 grid. |
| Orientation Sensor | `icm40608_imu` | LSM6DSOX | MEASURE | MEASURE | MEASURE | Mount it rigidly to the head for tap detection. |
| Temp & Humidity | `aht20_sensor` | AHT20 | MEASURE | MEASURE | MEASURE | The shell needs a vent next to it. |
| Air Quality | `scd40_air_quality` | SCD40 | MEASURE | MEASURE | MEASURE | Sensor body is 10.1 × 10.1 × 6.5. Needs airflow. |
| Distance Sensor | `vl53l5cx_distance` | VL53L5CX | MEASURE | MEASURE | MEASURE | Sensor body is 6.4 × 3.0 × 1.5. FoV is 63° diagonal. The cover window must not clip the cone. |
| Knob | `rotary_encoder_knob` | EC11 | MEASURE | MEASURE | MEASURE | 11 mm-size metal-shaft encoder. Measure the shaft length and diameter for the knob cap. |
| Button | `button_module` | — | MEASURE | MEASURE | MEASURE | |
| Speaker | `speaker` | MAX98357A | MEASURE | MEASURE | MEASURE | Measure the speaker driver's diameter and depth. The shell needs a grille. |
| Microphone | `microphone` | ICS-43434 | MEASURE | MEASURE | MEASURE | Mic package is 3.50 × 2.65 × 0.98 and **bottom-ported**, so the sound hole goes through the PCB. Line it up with the shell's opening. |
| DC Motor | `dc_motor` | DRV8833 | ~23 × 23 cross-section | ~44 long, excluding the shaft (est.†) | MEASURE | "DC Motor V2.3": a black enclosed gearmotor block with the driver inside, about two module-lengths long. Its 6-pin connector is on one long face. The shaft comes out of one short end, about 10 long and about 3 diameter (est.†). Check whether it's a D-shaft before designing the coupler. |
| Soil Sensor | `soil_sensor` | CH32V003 | MEASURE | MEASURE | MEASURE | Not in Kaiku's design. Listed only because it's in the kit. |
| Camera | `ov5640_camera` | OV5640 | MEASURE | MEASURE | MEASURE | Measure the lens barrel diameter and its FOV. |
| microSD Card | `micro_sd_card` | — | MEASURE | MEASURE | MEASURE | |

† **Photo estimate, about ±5 %.** From two phone photos taken on 2026-11-14:
- **Front-on photo (primary source):** the board's scale comes from its own USB-C receptacle (8.94 mm wide = 117 px,
  0.077 mm/px). The motor's scale comes from the Arduino USB Camera's 70 mm face (863 px, 0.081 mm/px).
- **Overhead photo (cross-check):** its proportions agree within 2 %. Its absolute sizes came out about 13 % too large
  because the camera face sat higher above the desk than assumed. Don't use the overhead numbers.

Good enough for blocking out the shell, **not for final fits**. Replace each one with a caliper measurement.

The modules look like cubes about 22 mm on a side, on a port pitch of about 21 mm (est.†). The board is about 3 module
widths wide, and the motor is about 2 modules long.

## Other

| Part | Outline W × D | Height | Mounting | Notes |
|---|---|---|---|---|
| Pan DC motor | MEASURE | MEASURE | MEASURE | From the venue's parts, per `bom.md`. |
