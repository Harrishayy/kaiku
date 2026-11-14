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

    async def start(self, on_utterance: UtteranceHandler, on_tool: ToolHandler | None = None) -> None:
        return None

    async def say(self, text: str) -> None:
        log.info("say", text, voice=self.name)

    async def say_verbatim(self, text: str) -> None:
        """Speak exactly this text (crisis script). Must not route through an LLM."""
        await self.say(text)

    async def interrupt(self) -> None:
        return None

    async def send_context(self, text: str) -> None:
        """A short bracketed context event (live/context_events.py) for the open conversation. No-op by default."""
        return None

    # A conversation session (Gemini Live) is opened per ritual, never kept open (mic only while consented).
    wants_session = False

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
    """Music that follows drumming. set_tempo is called every few taps."""

    name = "off"

    async def start(self, mood: int | None = None) -> None:
        return None

    async def set_tempo(self, bpm: float, force: float) -> None:
        return None

    async def click(self, force: float) -> None:
        """Immediate local feedback on each tap."""
        return None

    async def stop(self) -> None:
        return None


class OffMusic(Music):
    name = "off"
