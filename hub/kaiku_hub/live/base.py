"""Adapter interfaces. Core ritual code only talks to these."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from kaiku_contracts.jlog import get_logger

log = get_logger("hub")

UtteranceHandler = Callable[[str], Awaitable[None]]
ToolHandler = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class Voice:
    """Speech in/out. `on_utterance` receives user text (transcripts go through the safety gate first)."""

    name = "off"
    # Streaming adapters scan every fragment for safety, then dispatch one completed utterance.
    on_partial_utterance: UtteranceHandler | None = None
    on_completed_utterance: UtteranceHandler | None = None
    on_speech_features: Callable[[dict], Awaitable[None]] | None = None

    async def start(self, on_utterance: UtteranceHandler, on_tool: ToolHandler | None = None) -> None:
        return None

    async def say(self, text: str) -> None:
        log.info("say", text, voice=self.name)

    async def say_verbatim(self, text: str) -> None:
        """Speak exactly this text (crisis script). Must not route through an LLM."""
        await self.say(text)

    async def interrupt(self) -> None:
        return None

    async def after_speech(self) -> None:
        """Return once nothing of this voice is being said or about to be said (bounded). For a line that is only
        worth saying if it is still true when it can be said. No-op for a voice that does not speak."""
        return None

    def listen(self, on: bool) -> None:
        """Close (False) or reopen (True) the microphone inside an open conversation, without ending it: while a
        game owns the speaker and her taps, nothing she does is speech. No-op for a voice with no microphone."""
        return None

    async def send_context(self, text: str) -> None:
        """A short bracketed context event (live/context_events.py) for the open conversation. No-op by default."""
        return None

    # A conversation session (Gemini Live) is opened per ritual, never kept open (mic only while consented).
    wants_session = False
    in_session = False  # a conversation is open right now

    async def open_session(self, system_instruction: str, tools: list[dict[str, Any]],
                           model: str | None = None, voice: str | None = None) -> bool:
        return False

    async def close_session(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class OffVoice(Voice):
    name = "off"


class Music:
    """Music for the drum step. Free drumming: it follows her (`set_tempo` every few taps). Tap it back: it leads
    (`song` plays at a tempo, `hush` makes it quiet for her turn, `chime` gives a cue)."""

    name = "off"
    # True only while generated music is really open (a started Lyria session): `[tap_back] mode = "auto"` plays
    # the game only then.
    can_play_songs = False

    async def start(self, mood: int | None = None) -> None:
        return None

    async def set_tempo(self, bpm: float, force: float) -> None:
        return None

    async def click(self, force: float) -> None:
        """Immediate local feedback on each tap."""
        return None

    async def song(self, bpm: float) -> str:
        """Play at this tempo from now. Returns what will give the tempo: "music" (generated), "beat" (the hub's
        own plain beat) or "" (nothing will be heard)."""
        return ""

    def tempo_by(self) -> str:
        """What `song` would give the tempo with, asked before playing: "music", "beat" or ""."""
        return ""

    def heard_s(self) -> float:
        """Seconds of the current song that have really gone to the output since `song` (0.0 = nothing yet)."""
        return 0.0

    async def hush(self) -> None:
        """Go quiet now (her turn). `song` starts the next one."""
        return None

    async def chime(self, name: str) -> float:
        """A short cue on the same output (`sounds.CHIMES`). Returns how long it sounds; 0.0 = not played."""
        return 0.0

    async def stop(self) -> None:
        return None


class OffMusic(Music):
    name = "off"
