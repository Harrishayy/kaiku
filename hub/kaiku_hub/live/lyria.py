"""Lyria RealTime music adapter (KAIKU_MUSIC=lyria). Optional deps: `uv sync --extra live`.

VERIFY: model ID (config [models].lyria_realtime), SDK calls (`client.aio.live.music.connect`,
`set_weighted_prompts`, `set_music_generation_config`, `play`, `reset_context`), allowed BPM range
(config [music] bpm_min/bpm_max), and output format (48 kHz stereo 16-bit PCM at time of writing).
Send the FULL generation config on each update, not a partial one (handoff §9.3).
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from kaiku_contracts.jlog import get_logger

from .base import Music
from .local_audio import LocalMusic

log = get_logger("hub")

try:
    from google import genai  # type: ignore[import-not-found]
    from google.genai import types  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    genai = None
    types = None
try:
    import sounddevice as sd  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    sd = None

MOOD_PROMPTS = {
    1: "soft warm ambient pads, gentle hand percussion",
    2: "calm acoustic groove, soft hand drums",
    3: "light acoustic groove, hand drums, marimba",
    4: "upbeat warm hand percussion, marimba, bright",
    5: "joyful bright percussion groove, marimba, bass",
}


def clamp_bpm(bpm: float, lo: float, hi: float) -> int:
    return int(round(min(hi, max(lo, bpm))))


def available(model_id: str) -> tuple[bool, str]:
    if genai is None or sd is None:
        return False, "google-genai/sounddevice not installed (uv sync --extra live)"
    if not os.environ.get("GEMINI_API_KEY"):
        return False, "GEMINI_API_KEY not set"
    if not model_id or model_id.upper().startswith("VERIFY"):
        return False, "config [models].lyria_realtime is a VERIFY placeholder"
    return True, ""


class LyriaMusic(Music):  # pragma: no cover - needs network, key and audio devices
    name = "lyria"

    def __init__(self, model_id: str, bpm_min: float = 60, bpm_max: float = 200):
        self.model_id, self.bpm_min, self.bpm_max = model_id, bpm_min, bpm_max
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options={"api_version": "v1alpha"})
        self._cm: Any = None
        self._session: Any = None
        self._task: asyncio.Task | None = None
        self._bpm: int | None = None
        self._last_update = 0.0
        self._local = LocalMusic()

    async def start(self, mood: int | None = None) -> None:
        try:
            self._cm = self.client.aio.live.music.connect(model=self.model_id)
            self._session = await asyncio.wait_for(self._cm.__aenter__(), timeout=10)
            await self._session.set_weighted_prompts(
                prompts=[types.WeightedPrompt(text=MOOD_PROMPTS.get(mood or 3, MOOD_PROMPTS[3]), weight=1.0)]
            )
            await self._session.set_music_generation_config(config=types.LiveMusicGenerationConfig(bpm=90))
            await self._session.play()
            self._task = asyncio.create_task(self._play_loop())
        except Exception as e:
            log.warning("lyria_unavailable", f"{type(e).__name__}: {e}; local click only")
            self._session = None

    async def _play_loop(self) -> None:
        out = sd.RawOutputStream(samplerate=48000, channels=2, dtype="int16")
        out.start()
        try:
            async for message in self._session.receive():
                sc = getattr(message, "server_content", None)
                for chunk in getattr(sc, "audio_chunks", None) or []:
                    out.write(chunk.data)
        finally:
            out.stop()

    async def set_tempo(self, bpm: float, force: float) -> None:
        if self._session is None:
            return
        target = clamp_bpm(bpm, self.bpm_min, self.bpm_max)
        now = time.monotonic()
        if self._bpm is not None and abs(target - self._bpm) < 6 or now - self._last_update < 4:
            return
        self._bpm, self._last_update = target, now
        try:
            cfg = types.LiveMusicGenerationConfig(
                bpm=target, density=round(0.3 + 0.6 * force, 2), brightness=round(0.3 + 0.6 * force, 2)
            )
            await self._session.set_music_generation_config(config=cfg)
            await self._session.reset_context()  # BPM changes need a context reset (VERIFY)
        except Exception as e:
            log.warning("lyria_update_failed", str(e))

    async def click(self, force: float) -> None:
        await self._local.click(force)

    async def stop(self) -> None:
        session, self._session = self._session, None
        if self._task:
            self._task.cancel()
        if session is not None:
            try:
                await session.stop()
                await self._cm.__aexit__(None, None, None)
            except Exception:
                pass
