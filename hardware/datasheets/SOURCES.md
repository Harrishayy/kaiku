# Datasheet sources (local only, this folder is gitignored)

## arduino/
| File | Source |
|---|---|
| ABX00162-ABX00173_Arduino-UNO-Q_datasheet.pdf | https://docs.arduino.cc/resources/datasheets/ABX00162-ABX00173-datasheet.pdf |
| TPX00246_Arduino-USB-Camera_datasheet.pdf | https://docs.arduino.cc/resources/datasheets/TPX00246-datasheet.pdf |
| ABX00108_Modulino-Buzzer_datasheet.pdf | https://docs.arduino.cc/resources/datasheets/ABX00108-datasheet.pdf |

## atech/
Atech publishes no per-module datasheets, so these are the datasheets for the chip on each module.
The chip list comes from `atech_llms.txt` (https://atech.dev/llms.txt).

| Module | File | Source |
|---|---|---|
| Module reference (all) | atech_llms.txt | https://atech.dev/llms.txt |
| Motherboard (ESP32-S3) | ESP32-S3_datasheet.pdf, ESP32-S3-WROOM-1_datasheet.pdf | espressif.com (exact module variant on the board is unconfirmed) |
| Color Display | ST7735S_datasheet.pdf | displayfuture.com mirror |
| Big Screen | ST7789_datasheet.pdf | rhydolabz.com mirror (ST7789VW) |
| LED Grid | WS2812B_datasheet.pdf | cdn-shop.adafruit.com |
| Orientation Sensor | LSM6DSOX_datasheet.pdf | cdn.sparkfun.com mirror (ST DS12814). Atech's module ID says `icm40608_imu`, but its docs name the chip as the LSM6DSOX |
| Temp & Humidity | AHT20_datasheet.pdf | cdn-learn.adafruit.com |
| Air Quality | SCD40_datasheet.pdf | sensirion.com |
| Distance Sensor | VL53L5CX_datasheet.pdf | cdn.sparkfun.com mirror (ST DS13754) |
| Knob | EC11_rotary-encoder_datasheet.pdf | tech.alpsalpine.com (EC11E catalog) |
| Speaker | MAX98357A_datasheet.pdf | datasheets.maximintegrated.com |
| Microphone | ICS-43434_datasheet.pdf | cdn.sparkfun.com mirror (TDK DS-000069 v1.2) |
| DC Motor | DRV8833_datasheet.pdf | ti.com |
| Soil Sensor | CH32V003_datasheet.pdf | electrokit.com mirror (WCH CH32V003DS0) |
| Camera | OV5640_datasheet.pdf | cdn.sparkfun.com mirror |
| Button, microSD | none (generic parts) | |
