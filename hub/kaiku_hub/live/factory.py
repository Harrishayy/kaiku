"""Pick voice/music adapters from settings, falling back softly (never crash on a missing extra)."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from kaiku_contracts.jlog import get_logger

from ..settings import resolve_path
from .base import Music, OffMusic, OffVoice, Voice
from .local_audio import LocalMusic, LocalVoice
from .text import TextVoice

log = get_logger("hub")


def voice_audio(choice: str, *, head: Any = None, head_alive: Callable[[], bool] | None = None) -> Any:
    """`[voice] audio` -> where Kaiku's Live voice is heard and the person is listened to.
    head = the robot head's own speaker and microphone over the bus (`head_audio.HeadAudio`): no sound device on
    this machine. local = this machine's sound card (`sounddevice`). auto = the head when a head is alive on the
    bus at the moment a conversation opens, else this machine's sound card if it has one, else the head anyway."""
    from .head_audio import AutoAudio

    try:
        import sounddevice as local  # type: ignore[import-not-found]
    except Exception:
        local = None
    if choice == "local":
        return local
    if choice == "head" or local is None:
        return head
    return AutoAudio(head, local, head_alive or (lambda: False)) if head is not None else local


def make_voice(mode: str, *, model_id: str = "", language: str = "en", read_stdin: bool = True,
               voice_name: str = "", audio: str = "local", head: Any = None,
               head_alive: Callable[[], bool] | None = None) -> Voice:
    if mode == "gemini":
        from . import gemini_live

        device = voice_audio(audio, head=head, head_alive=head_alive)
        ok, why = gemini_live.available(model_id, device)
        if ok:
            return gemini_live.GeminiLiveVoice(model_id, language, voice_name=voice_name, audio=device)
        log.warning("voice_fallback", f"gemini unavailable: {why}; using text mode")
        return TextVoice(read_stdin=read_stdin)
    if mode == "text":
        return TextVoice(read_stdin=read_stdin)
    if mode == "local":
        return LocalVoice()
    return OffVoice()


def music_output(out: str, *, head: Any = None) -> Any:
    """`[music] out` -> what the music player writes to: the robot head's own speaker (`head`: the hub's
    `HeadSpeaker`, no sound device on this machine), this machine's sound card (`speaker`), or a WAV file (`file`;
    `KAIKU_MUSIC_FILE=<path>` names it and, as before, wins over the setting). None = nowhere."""
    path = os.environ.get("KAIKU_MUSIC_FILE")
    if path or out == "file":
        from .player import WavOut

        return WavOut(path or str(resolve_path("logs/drum-music.wav")), realtime=True)
    if out == "head":
        return head
    try:
        import sounddevice  # type: ignore[import-not-found]

        return sounddevice
    except Exception:
        return None


def make_music(mode: str, *, model_id: str = "", bpm_min: float = 60, bpm_max: float = 200, out: str = "speaker",
               head: Any = None) -> Music:
    audio = music_output(out, head=head) if mode in ("lyria", "local") else None
    if mode == "lyria":
        from . import lyria

        ok, why = lyria.available(model_id, out)
        if ok and audio is not None:
            return lyria.LyriaMusic(model_id, bpm_min, bpm_max, audio=audio)
        log.warning("music_fallback", f"lyria unavailable: {why or 'no output for the music'}; using local")
        return LocalMusic(audio)
    if mode == "local":
        return LocalMusic(audio)
    return OffMusic()
