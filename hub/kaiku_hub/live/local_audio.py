"""Visible offline fallback and optional percussion click; speech always uses Gemini audio."""

from __future__ import annotations

import os
import sys
from typing import Any

from .base import Voice
from .player import PlayedMusic


class LocalVoice(Voice):
    """Visible deterministic fallback. Never substitute an operating-system synthetic voice."""

    name = "local"

    async def say(self, text: str) -> None:
        print(f"\U0001f916 Kaiku: {text}", file=sys.stderr, flush=True)


class LocalMusic(PlayedMusic):
    """No generated music. With an output (`audio`) it can still give Tap it back a plain beat and its cues; free
    drumming gets the optional terminal click only, as before."""

    name = "local"

    def __init__(self, audio: Any = None):
        super().__init__(audio)

    async def start(self, mood: int | None = None) -> None:
        self._start_player()

    async def song(self, bpm: float) -> str:
        return await self._beat(bpm)

    async def click(self, force: float) -> None:
        if os.environ.get("KAIKU_LOCAL_CLICK", "0") == "1":
            print("\a", end="", file=sys.stderr, flush=True)

    async def stop(self) -> None:
        self._stop_player()
