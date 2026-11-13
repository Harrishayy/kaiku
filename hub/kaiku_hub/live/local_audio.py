"""Offline fallback: local TTS (macOS `say` / `espeak`) for scripted lines, local click for taps.

TODO(B): pre-recorded voice lines (assets) + a local music loop for KAIKU_MUSIC=local.
Local TTS is only used when KAIKU_LOCAL_TTS=1 (tests and CI stay silent).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys

from .base import Music, Voice


def _tts_cmd() -> list[str] | None:
    if os.environ.get("KAIKU_LOCAL_TTS", "0") != "1":
        return None
    if shutil.which("say"):
        return ["say"]
    if shutil.which("espeak"):
        return ["espeak"]
    return None


async def speak_local(text: str) -> None:
    cmd = _tts_cmd()
    if not cmd:
        return
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, text)
        await asyncio.wait_for(proc.wait(), timeout=60)
    except Exception:
        pass


class LocalVoice(Voice):
    """Prints + local TTS. Deterministic: used for the crisis script and offline demos."""

    name = "local"

    async def say(self, text: str) -> None:
        print(f"\U0001f916 Kaiku: {text}", file=sys.stderr, flush=True)
        await speak_local(text)


class LocalMusic(Music):
    name = "local"

    async def click(self, force: float) -> None:
        if os.environ.get("KAIKU_LOCAL_CLICK", "0") == "1":
            print("\a", end="", file=sys.stderr, flush=True)
