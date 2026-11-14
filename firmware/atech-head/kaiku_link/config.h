// Atech firmware settings. Every hardware number lives here (plan 07: config, not code). Pulse times and the eye
// shapes need tuning on the real robot. Secrets (Wi-Fi, broker IP/user/password, home id) go in secrets.h
// (gitignored; copy secrets.example.h).
#pragma once

#define KAIKU_FW_VERSION "atech-head-0.2.0"

// --- network
#define MQTT_PORT_DEFAULT 1883
#define BACKOFF_MIN_MS 1000          // Wi-Fi first, then MQTT; backoff 1 s -> 10 s
#define BACKOFF_MAX_MS 10000
#define HEALTH_EVERY_MS 5000         // health/head heartbeat (retained), same cadence as the Python Bus
#define HUB_SILENCE_STOP_MS 15000    // no health/hub this long -> stop motor + speaker (hub beats every 5 s)
#define NTP_SERVER "pool.ntp.org"    // envelope ts must be UTC; until NTP syncs, messages wait

// --- button (lid; Atech button_module, active low)
#define BUTTON_DEBOUNCE_MS 20        // the long press (>= 2 s = "I'm not OK") is decided by the hub

// --- knob (left ear; rotary_encoder_knob) -> raw.head.ear
#define KNOB_COUNTS_PER_STEP 2       // encoder counts per dial step (EC11 detents; VERIFY with bench/knob)
#define KNOB_START_VALUE 3           // dial position at boot
#define KNOB_PRESS_DEBOUNCE_MS 30

// --- Color Display eyes (st7735_tft, 160x80, RGB565)
#define DISPLAY_W 160
#define DISPLAY_H 80
#define EYE_COLOR 0xFFDF             // warm white
#define EYE_SOFT_COLOR 0x9CD3        // dimmer, for "soft"
#define EYE_BG 0x0000
#define EYE_W 30
#define EYE_H 40
#define EYE_GAP 60                   // centre-to-centre
#define EYE_LOOK_PX 18               // look.x = +-1 shifts the eyes this far
#define BLINK_MS 120
#define BLINK_MIN_MS 3000            // random gap between blinks; no blinks while the chest breathes
#define BLINK_MAX_MS 6000

// --- LED grids x2 (neopixel_grid 3x3, chest louvres)
#define LED_DEFAULT_RGB 0xFFB070     // warm amber when cmd.head has no `color`
#define LED_MAX_BRIGHT 0.6f          // never full white (shared rails, and it's a glow, not a lamp)
#define LED_GLOW_BRIGHT 0.25f
#define LED_FRAME_MS 33

// --- DC motor (pan, port 7, 12:40 gear, ~+-100 deg). No position feedback between homings: dead reckoning.
#define MOTOR_RAMP_MS 100            // ramp speed instead of jumping (brown-outs on the shared rails)
#define MOTOR_MAX_RUN_MS 1000        // never drive longer than this per command
#define MOTOR_DEG_PER_S_FULL 120.0f  // estimated head speed at |speed| = 255 (TUNE)
#define HAS_HALL 0                   // 0 = no KY-035/magnet in this build (D39): home = head position at power-on,
                                     // then dead reckoning only. 1 = brake on the hall edge (raw/sensors/hall).
#define PAN_LIMIT_DEG (HAS_HALL ? 100.0f : 80.0f)  // cable bundle through the neck; tighter while the angle can drift
#define PAN_DEADBAND_DEG 3.0f
#define HOME_SPEED 80                // slow toward the front; brake on the KY-035 edge (raw/sensors/hall)
#define HOME_TRY_MS 2000             // give up after this per direction (then try the other way once)
#define LOOK_MS 300                  // gesture look_left / look_right: one way, then home
#define SHAKE_PULSE_MS 120           // gesture shake: two short alternating pulses each way, then home
#define GESTURE_SPEED 160
#define PAN_PUBLISH_MOVING_MS 200    // raw.head.pan while moving (the UNO Q mutes knocks on `moving`)
#define PAN_PUBLISH_IDLE_MS 2000

// --- speaker (MAX98357A). Voice is on the laptop in v1; the speaker does purr + cues.
#define PURR_HZ 90                   // cmd.head purr {ms}: a low soft tone (no purr motor on this build)
#define PURR_VOLUME 0.25f            // keep low: never motor + loud speaker together
