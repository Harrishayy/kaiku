"""Button build: a run of short presses -> one dial answer (1-5).

The head button sends raw.head.button press/release. During a ritual, short presses are counted; when no new press
comes within `window_s`, the count becomes one `ear` event {value: n, pressed: true}, so every step that reads the
ear dial (Greet, Dial, Drum post-mood, PHQ-9) works unchanged. Long presses never count: they are the safety trigger
(safety/gate.py ButtonLongPress).
"""

from __future__ import annotations


class PressCounter:
    def __init__(self, window_s: float = 4.0, max_count: int = 5):
        self.window_s = window_s
        self.max_count = max_count
        self.count = 0
        self.last_at: float | None = None

    def add(self, now: float) -> None:
        if self.last_at is not None and now - self.last_at > self.window_s:
            self.count = 0
        self.count = min(self.max_count, self.count + 1)
        self.last_at = now

    def due(self, now: float) -> bool:
        return self.count > 0 and self.last_at is not None and now - self.last_at >= self.window_s

    def take(self) -> int:
        """The finished answer (1..max_count); resets the counter."""
        n, self.count, self.last_at = self.count, 0, None
        return n

    def ear_event(self) -> dict:
        return {"value": self.take(), "delta": 0, "pressed": True}
