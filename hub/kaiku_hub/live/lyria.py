"""Lyria RealTime music adapter (KAIKU_MUSIC=lyria). Optional deps: `uv sync --extra live`.

Shown on 2026-11-14 with real sessions (audio written to a file or to the head twin, never played here): model ID
`lyria-realtime-exp`, `client.aio.live.music.connect`, `set_weighted_prompts`, `set_music_generation_config`, `play`,
`pause`, a tempo change with `reset_context`, and the output format (`audio/l16;rate=48000;channels=2`, 2 s chunks).
`pause()` stops the chunks at once; after it, config + `reset_context()` + `play()` brings the first chunk of the new
tempo in about 0.7 s.
Gemini Developer API only: on the platform (Google Cloud) backend the SDK refuses with "Live music generation is not
supported in Vertex AI", so this edge picks GEMINI_API_KEY itself, like the Live voice adapter.
Where the sound goes is `[music] out` (`player.py`): the robot head's own speaker (default; no sound device on the
hub), a sound card, or a file.
Not checked: the model's own allowed BPM range (the hub clamps to config [music] bpm_min/bpm_max). What was and was
not heard on the real head is in hub/AGENTS.md (Known issues) and docs/progress.md.
Send the FULL generation config on each update, not a partial one (handoff §9.3).
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from kaiku_contracts import genai_client
from kaiku_contracts.budget import BudgetExceeded
from kaiku_contracts.jlog import get_logger

from .local_audio import LocalMusic
from .meter import SessionMeter
from .player import FADE_BYTES, FADE_MS, SLICE_BYTES, PlayedMusic, WavOut, faded  # noqa: F401 (the names tests use)

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


def available(model_id: str, out: str = "speaker") -> tuple[bool, str]:
    """Can the adapter start? A sound card on this machine is needed only when the music is to play here
    (`out = "speaker"`): the head's speaker and a file need none."""
    if genai is None:
        return False, "google-genai not installed (uv sync --extra live)"
    if out == "speaker" and sd is None and not os.environ.get("KAIKU_MUSIC_FILE"):
        return False, "sounddevice not installed (uv sync --extra live), or set [music] out = \"head\""
    if not os.environ.get("GEMINI_API_KEY"):
        return False, "Lyria RealTime needs GEMINI_API_KEY (the Developer API; the platform backend has no live music)"
    if not model_id or model_id.upper().startswith("VERIFY"):
        return False, "config [models].lyria_realtime is a VERIFY placeholder"
    return True, ""


class LyriaMusic(PlayedMusic):  # pragma: no cover - needs network, key and audio devices
    name = "lyria"

    def __init__(self, model_id: str, bpm_min: float = 60, bpm_max: float = 200, *, client: Any = None,
                 audio: Any = None, meter_factory: Any = SessionMeter):
        path = os.environ.get("KAIKU_MUSIC_FILE")
        super().__init__(audio if audio is not None else WavOut(path, realtime=True) if path else sd)
        self.meter_factory = meter_factory
        self.model_id, self.bpm_min, self.bpm_max = model_id, bpm_min, bpm_max
        # Live music is a Developer API feature: keep the credential choice at this edge instead of inheriting the
        # cloud text/TTS backend (the same reason as in gemini_live.py).
        if client is not None:
            self.client = client
        elif os.environ.get("GEMINI_API_KEY"):
            self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options={"api_version": "v1alpha"})
        else:
            self.client = genai_client.make_client(api_version="v1alpha")
        self._cm: Any = None
        self._session: Any = None
        self._task: asyncio.Task | None = None
        self._bpm: int | None = None
        self._last_update = 0.0
        self._paused = False  # the session is paused (her turn): chunks still in flight are not played
        self._local = LocalMusic()
        self._meter: SessionMeter | None = None

    @property
    def can_play_songs(self) -> bool:  # type: ignore[override]
        """A session is open and its stream is alive. Whether a song is really HEARD is `heard_s()`: it counts
        only audio that went to the output after the last `song()`."""
        return self._session is not None and self._task is not None and not self._task.done()

    async def start(self, mood: int | None = None) -> None:
        meter = self.meter_factory("gemini", self.model_id)
        try:
            meter.open()  # spend cap: over it = local click only
        except BudgetExceeded as e:
            log.warning("lyria_budget", str(e))
            return
        try:
            self._cm = self.client.aio.live.music.connect(model=self.model_id)
            self._session = await asyncio.wait_for(self._cm.__aenter__(), timeout=10)
            await self._session.set_weighted_prompts(
                prompts=[types.WeightedPrompt(text=MOOD_PROMPTS.get(mood or 3, MOOD_PROMPTS[3]), weight=1.0)]
            )
            await self._session.set_music_generation_config(config=types.LiveMusicGenerationConfig(bpm=90))
            await self._session.play()
            self._bpm, self._last_update, self._paused = None, 0.0, False
            self._stop_player()
            self._start_player()
            self._task = asyncio.create_task(self._receive_loop())
            self._task.add_done_callback(self._stream_ended)
            self._sound = "music"
            self._meter = meter
            meter.start(self.stop)
        except Exception as e:
            log.warning("lyria_unavailable", f"{type(e).__name__}: {e}; local click only")
            self._session = None

    def _stream_ended(self, task: asyncio.Task) -> None:
        """The stream closed under us (network, server): say so. `can_play_songs` is False from here."""
        if not task.cancelled() and self._session is not None:
            err = task.exception()
            log.warning("lyria_stream_ended", type(err).__name__ if err else "closed by the server")

    async def _receive_loop(self) -> None:
        async for message in self._session.receive():
            sc = getattr(message, "server_content", None)
            for chunk in getattr(sc, "audio_chunks", None) or []:
                if not self._paused:
                    self._put(chunk.data)

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
            await self._session.reset_context()  # a BPM change needs a context reset (Gemini API docs, steer-config)
            self._drop_queued()
        except Exception as e:
            log.warning("lyria_update_failed", str(e))

    async def song(self, bpm: float) -> str:
        """Tap it back: the song at exactly this tempo, from now. Full config, then `reset_context`, then `play`
        if the session was paused: measured, the first chunk of the new tempo comes about 0.7 s later. Without a
        live session the hub's own plain beat stands in (when there is an output)."""
        if not self.can_play_songs:
            return await self._beat(bpm)
        target = clamp_bpm(bpm, self.bpm_min, self.bpm_max)
        try:
            cfg = types.LiveMusicGenerationConfig(bpm=target, density=0.66, brightness=0.66)
            await self._session.set_music_generation_config(config=cfg)
            await self._session.reset_context()
            if self._paused:
                await self._session.play()
            self._drop_queued()
            self._paused = False
            self._bpm, self._last_update, self._sound = target, time.monotonic(), "music"
            return "music"
        except Exception as e:
            log.warning("lyria_song_failed", f"{type(e).__name__}: {e}")
            return ""

    async def hush(self) -> None:
        """Her turn: quiet now. The session is paused (measured: no chunk arrives after `pause`), what was queued
        is dropped, and the player fades out what it is in the middle of."""
        self._paused = True
        await super().hush()
        if self._session is not None:
            try:
                await self._session.pause()
            except Exception as e:
                log.warning("lyria_pause_failed", f"{type(e).__name__}: {e}")

    async def click(self, force: float) -> None:
        await self._local.click(force)

    async def stop(self) -> None:
        if self._meter is not None:
            self._meter.stop()
            self._meter = None
        session, self._session = self._session, None
        if self._task:
            self._task.cancel()
        self._task = None
        self._stop_player()
        if session is not None:
            try:
                await session.stop()
                await self._cm.__aexit__(None, None, None)
            except Exception:
                pass
