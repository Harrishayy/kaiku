"""Pick voice/music adapters from settings, falling back softly (never crash on a missing extra)."""

from __future__ import annotations

from kaiku_contracts.jlog import get_logger

from .base import Music, OffMusic, OffVoice, Voice
from .local_audio import LocalMusic, LocalVoice
from .text import TextVoice

log = get_logger("hub")


def make_voice(mode: str, *, model_id: str = "", language: str = "en", read_stdin: bool = True,
               voice_name: str = "") -> Voice:
    if mode == "gemini":
        from . import gemini_live

        ok, why = gemini_live.available(model_id)
        if ok:
            return gemini_live.GeminiLiveVoice(model_id, language, voice_name=voice_name)
        log.warning("voice_fallback", f"gemini unavailable: {why}; using text mode")
        return TextVoice(read_stdin=read_stdin)
    if mode == "text":
        return TextVoice(read_stdin=read_stdin)
    if mode == "local":
        return LocalVoice()
    return OffVoice()


def make_music(mode: str, *, model_id: str = "", bpm_min: float = 60, bpm_max: float = 200) -> Music:
    if mode == "lyria":
        from . import lyria

        ok, why = lyria.available(model_id)
        if ok:
            return lyria.LyriaMusic(model_id, bpm_min, bpm_max)
        log.warning("music_fallback", f"lyria unavailable: {why}; using local")
        return LocalMusic()
    if mode == "local":
        return LocalMusic()
    return OffMusic()
