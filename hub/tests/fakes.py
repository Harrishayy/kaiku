"""Fakes shared by the hub's tests."""

import time

from kaiku_hub.live.base import Music


class Songs(Music):
    """A music adapter that can play songs: it records what it was asked, and `heard_s` runs `speed` times faster
    than the clock (a silent one never gets there)."""

    name = "songs"

    def __init__(self, kind: str = "music", speed: float = 200.0, generated: bool = True, silent_from: int = 99):
        self.kind, self.speed, self.generated, self.silent_from = kind, speed, generated, silent_from
        self.calls: list[str] = []
        self.bpms: list[float] = []
        self._t = 0.0
        self.started = False

    @property
    def can_play_songs(self) -> bool:  # type: ignore[override]
        return self.generated and self.started

    def tempo_by(self) -> str:
        return self.kind

    async def start(self, mood=None):
        self.started = True
        self.calls.append("start")

    async def song(self, bpm: float) -> str:
        self.bpms.append(bpm)
        self.calls.append(f"song {bpm}")
        self._t = time.monotonic()
        return self.kind

    def heard_s(self) -> float:
        if len(self.bpms) >= self.silent_from:
            return 0.0
        return (time.monotonic() - self._t) * self.speed

    async def hush(self):
        self.calls.append("hush")

    async def chime(self, name: str) -> float:
        self.calls.append(f"chime {name}")
        return 0.0

    async def stop(self):
        self.calls.append("stop")
