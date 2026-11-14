// UNO Q MCU (STM32U585) settings. Every hardware number for the sketch lives here (plan 07: config, not code).
// Wiring ground truth: hardware/wiring.md (pins marked VERIFY there are confirmed on the board).
#pragma once

#define KAIKU_SKETCH_VERSION "unoq-sketch-0.2.0"

// KY-031 knock sensor (the drum, under the head top; 3 wires down the neck): S -> D2, + -> 3V3, - -> GND
#define KNOCK_PIN 2
#define KNOCK_DEBOUNCE_MS 40      // the spring bounces: one knock = everything within this window
#define KNOCK_CALIBRATE_MS 500    // boot: read the idle level with the head still (sellers differ in polarity)
#define KNOCK_USE_PULLUP 1        // INPUT_PULLUP if the idle reading floats
#define KNOCK_POLL_FALLBACK 0     // 1 = poll at ~1 kHz if D2 has no interrupt on this core

// KY-035 hall sensor (49E linear, analog) under the pan base; magnet in the turntable = head faces front
#define HALL_PIN A1               // analog (the 49E is linear; a digital pin only works if the swing crosses logic)
#define HALL_MID 8192             // 49E output with no magnet ~ Vcc/2 = mid-scale (bench/hall prints the real value)
#define HALL_DELTA 600            // |reading - HALL_MID| above this (14-bit counts) = magnet over the sensor
#define HALL_HYST 150             // ... and below DELTA - HYST = magnet gone
#define HALL_POLL_MS 5            // 200 Hz: the hub/head brakes on the edge, so keep it fast

// KY-054 light sensor (phototransistor) under the lid window
#define LIGHT_PIN A0

// KY-039 heartbeat via KY-053 (ADS1115, 16-bit) on the header SDA/SCL bus = Wire (not A4/A5, not Qwiic)
#define ADS_ADDR 0x48
#define ADS_CONFIG_HI 0x42        // OS=0, MUX=AIN0 vs GND, PGA=+-4.096 V, continuous
#define ADS_CONFIG_LO 0xA3        // 250 SPS, comparator off (we read every 10 ms)
#define PPG_FS_HZ 100             // >= 100 Hz for beat-to-beat intervals (HRV)
#define PPG_BATCH 25              // samples per on_ppg notify (4 batches/s), same as raw.sensors.ppg in the sim

#define ADC_BITS 14               // STM32U585 ADC for the KY-054 and KY-035 (0..16383)

// UNO Q LED matrix: hidden in the body, status only (the eyes are the Atech Color Display)
#define STATUS_LEVEL 3

// Modulino Buzzer (ABX00108) on Qwiic = Wire1, default address 0x3C
#define BUZZER_MAX_NOTES 6
