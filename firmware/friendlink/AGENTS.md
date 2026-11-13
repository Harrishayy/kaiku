# firmware/friendlink — AGENTS.md

> Read the root `AGENTS.md` first. Owner A · kind firmware (stretch) · reference behaviour: `sim/nodes/friendlink_sim.py`.

## Purpose
Two LilyGo ESP32 LoRa boards: `gateway/` (USB serial to the hub) and `lamp/` (friend's home: LED glow + button).

## Consumes (topics/endpoints)
No MQTT. Serial line protocol from the hub adapter `hub/kaiku_hub/devices/lora_serial.py`: `PING <pattern>\n`.

## Emits (topics/endpoints)
Serial `ACK\n` (lamp acknowledged), `BUTTON\n` (friend pressed). The hub adapter turns them into `obs.friend_link`.

## Invariants
- Changing the line protocol = change the hub adapter in the same commit.
- EU868 LoRa. Lamp glows < 3 s after the robot's antenna button.

## Run standalone
Flash both (Arduino/PlatformIO); gateway serial monitor at 115200, type `PING glow`. Without hardware: `make sim NODES=friendlink`.

## Run with sim
`make hub` with the gateway on USB (`KAIKU_LORA_PORT`) or the sim.

## Config & env
`KAIKU_LORA_PORT` (gateway serial port).

## Health signal
The hub reports gateway liveness in `health/hub.details.friendlink`.

## Tests
Antenna button on robot → lamp glows in < 3 s; ack returns.

## Known issues
Not started.
