"""Photo time: a few seconds in front of the robot's camera, counted as face signs (D52). No picture.

Started by the voice model's `photo_time` tool (the person said it) or by `cmd.hub {photo_time: true}` (a button).
The hub says "Photo time!", asks the sensors board to count for `[photo_time] seconds`, and turns its one
`raw.sensors.face_signs` into `obs.face_signs` (task photo_time, device robot, method haar_cascades). Frames stay
in the camera thread on the board; only the numbers arrive here. Nothing here names a feeling, and the result
handed to the voice model tells it not to describe the face. No face in the window is a normal result.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

START_LINE = "Photo time!"
DONE_LINE = "All done. No picture was kept, only a few numbers."
NO_FACE_LINE = "All done. Nothing was kept."
NO_CAMERA_LINE = "My camera is not answering right now. We can try later."
WAIT_EXTRA_S = 6.0  # the board answers once, right after its window; this much later it is not coming
SIGNS = ("smile_share", "smiles", "head_movement")  # what the robot's cascades can count


class Robot(Protocol):
    async def say(self, text: str) -> None: ...
    async def sensors(self, **cmd: Any) -> None: ...
    async def emit(self, type_: str, payload: dict, quality: float | None = None) -> Any: ...


def observation(raw: dict) -> dict:
    """obs.face_signs payload from the board's window. A sign the cascades did not measure stays absent."""
    out = {"task": "photo_time", "device": "robot", "method": "haar_cascades", "duration_s": raw["duration_s"],
           "samples": raw["samples"], "coverage": raw["coverage"]}
    if raw["coverage"] > 0:
        out.update({k: raw[k] for k in SIGNS if raw.get(k) is not None})
    return out


def tool_result(raw: dict | None) -> dict:
    """What the voice model gets back. It never learns how the face looked, only that it is done."""
    if raw is None:
        return {"ok": False, "error": "the camera did not answer", "say": NO_CAMERA_LINE}
    return {"ok": True, "counted": raw["coverage"] > 0,
            "note": "Photo time is over and the robot already said so. No picture was taken or kept. Do not "
                    "describe the person's face or how they looked, and do not ask them to show their face."}


class PhotoTime:
    """One window at a time. `on_raw` is fed every raw.sensors.face_signs payload."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self._waiting: asyncio.Future[dict] | None = None

    @property
    def running(self) -> bool:
        return self._waiting is not None

    def on_raw(self, payload: dict) -> None:
        if self._waiting is not None and not self._waiting.done():
            self._waiting.set_result(payload)

    async def run(self, robot: Robot) -> dict:
        if self.running:
            return {"ok": False, "error": "photo time is already running"}
        self._waiting = asyncio.get_running_loop().create_future()
        try:
            await robot.say(START_LINE)
            await robot.sensors(chime="start_drum", face_signs_s=self.seconds)
            try:
                raw = await asyncio.wait_for(self._waiting, self.seconds + WAIT_EXTRA_S)
            except TimeoutError:
                raw = None
            if raw is not None:
                await robot.emit("obs.face_signs", observation(raw), 0.6 if raw["coverage"] > 0 else None)
                await robot.sensors(chime="ok")
            await robot.say(NO_CAMERA_LINE if raw is None else DONE_LINE if raw["coverage"] > 0 else NO_FACE_LINE)
            return tool_result(raw)
        finally:
            self._waiting = None
