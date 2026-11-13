"""Face source `unoq_yolo` ([attention] face_source): person/face boxes from the UNO Q camera (App Lab object detection).

Interface for the UNO Q firmware (owner A; see hub/AGENTS.md -> "UNO Q face boxes"):
- publish ONE `raw.hub.face` per detected face/person box per frame, at ~5 Hz, source `sensors`, topic
  `kaiku/v1/<home>/raw/hub/face`, payload `RawFace {x_norm, y_norm, size, confidence}` (use `box_to_face`);
- two people = two messages in the same frame (the hub groups messages within [attention] frame_s);
- only boxes leave the board: frames stay in memory on the UNO Q, never stored or sent;
- obey `cmd.sensors {camera_enable: true|false}` (the hub enables it at start and disables it on shutdown).
The hub side needs nothing else: `Hub.on_raw` feeds every non-hub `raw/hub/face` into the attention ladder.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

SendSensors = Callable[..., Awaitable[None]]


def box_to_face(x1: float, y1: float, x2: float, y2: float, width: float, height: float,
                confidence: float) -> dict[str, Any]:
    """Pixel box (top-left x1,y1 / bottom-right x2,y2) in a width x height frame -> RawFace payload.
    x_norm/y_norm: box centre in -1..1 (right/down positive); size: box width / frame width."""

    def clip(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, v))

    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    return {
        "x_norm": round(clip(cx / width * 2 - 1, -1, 1), 3),
        "y_norm": round(clip(cy / height * 2 - 1, -1, 1), 3),
        "size": round(clip((x2 - x1) / width, 0, 1), 3),
        "confidence": round(clip(confidence, 0, 1), 3),
    }


class UnoqYoloFaces:
    name = "unoq_yolo"

    def __init__(self, send_sensors: SendSensors):
        self.send_sensors = send_sensors
        self.active = False

    async def start(self) -> None:
        self.active = True
        await self.send_sensors(camera_enable=True)

    async def stop(self) -> None:
        if self.active:
            self.active = False
            await self.send_sensors(camera_enable=False)
