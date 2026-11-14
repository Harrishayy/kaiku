"""Visible offline fallback and optional percussion click; speech always uses Gemini audio."""

from __future__ import annotations

import os
import sys

from .base import Music, Voice


class LocalVoice(Voice):
    """Visible deterministic fallback. Never substitute an operating-system synthetic voice."""

    name = "local"

    async def say(self, text: str) -> None:
        print(f"\U0001f916 Kaiku: {text}", file=sys.stderr, flush=True)


class LocalMusic(Music):
    name = "local"

    async def click(self, force: float) -> None:
        if os.environ.get("KAIKU_LOCAL_CLICK", "0") == "1":
            print("\a", end="", file=sys.stderr, flush=True)
