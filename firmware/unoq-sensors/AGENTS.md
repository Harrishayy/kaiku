# firmware/unoq-sensors — AGENTS.md

> Read the root `AGENTS.md` first. Owner A · kind firmware · reference behaviour: `sim/nodes/sensors_sim.py`.

## Purpose
Arduino UNO Q sensor node (App Lab: MCU sketch + Python relay via Bridge RPC → MQTT): KY-039 pulse via KY-053
(ADS1115, 16-bit) at ≥ 100 Hz, KY-054 light, KY-050 ultrasonic, KY-035 hall (pan homing), top button.

## Consumes (topics/endpoints)
`cmd/sensors` — `{ppg: start|stop}`, `{camera_enable: bool}` (status LED).

## Emits (topics/endpoints)
`raw/sensors/ppg` `{t0_ms, fs_hz, samples[25]}` · `raw/sensors/distance` `{cm}` 5–10 Hz · `raw/sensors/light`
`{raw, lux_est}` 0.1 Hz · `raw/sensors/button` `{id:"top", pressed}` · `raw/sensors/hall` `{at_home}` ·
`health/sensors`. Schemas: `contracts/schemas/raw/sensors.*`.

## Invariants
- PPG only between `ppg start` and `ppg stop`; batches of 25 samples at a stable `fs_hz`.
- Top-button long-press (≥ 2 s) is the manual safety trigger — never debounce it away.
- KY-050 echo is 5 V → KY-051 level shifter or divider before any 3.3 V pin (`hardware/wiring.md`; the kit
  leaflet mislabels it "KY-052").
- App Lab Python is containerised and may not see USB devices — camera and LoRa serial stay on the hub laptop.

## Run standalone
Arduino App Lab: `sketch/` (MCU) + `python/` (relay to the hub laptop's broker). Without hardware: `make sim NODES=sensors`.

## Run with sim
`make broker && make hub` on the laptop, UNO Q on the same network, `make tail TOPIC='kaiku/v1/+/raw/sensors/#'`.

## Config & env
Broker host/port in the relay config (gitignored if it holds credentials).

## Health signal
`health/sensors` with `details{ppg_rate_hz, adc_ok}`.

## Tests
PPG batches at a stable rate (`fs_hz` × batches/s); distance, light and button events visible; `health/sensors` ok.

## Known issues
Not started.
