"""Gemini Live voice adapter (KAIKU_VOICE=gemini). Optional deps: `uv sync --extra live`.

VERIFY before relying on this: current Live API model ID (config [models].gemini_live), SDK method
names (google-genai `client.aio.live.connect`, `send_realtime_input`, `send_client_content`,
`send_tool_response`), audio formats (16 kHz PCM in / 24 kHz PCM out at time of writing).
Use the geminiDocs MCP / gemini-live-api-dev skill. Never use the legacy google-generativeai SDK.

Privacy: mic audio streams only to Gemini during an active ritual; nothing is stored by us.
Input transcripts go to the hub's on_utterance (safety gate first) and are never logged.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from kaiku_contracts.jlog import get_logger

from .base import ToolHandler, UtteranceHandler, Voice
from .local_audio import LocalVoice
from .tools import SYSTEM_PROMPT, TOOLS

log = get_logger("hub")

try:  # optional
    from google import genai  # type: ignore[import-not-found]
    from google.genai import types  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    genai = None
    types = None

try:  # optional
    import sounddevice as sd  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    sd = None

IN_RATE, OUT_RATE, CHUNK = 16000, 24000, 1600


def available(model_id: str) -> tuple[bool, str]:
    if genai is None:
        return False, "google-genai not installed (uv sync --extra live)"
    if sd is None:
        return False, "sounddevice not installed (uv sync --extra live)"
    if not os.environ.get("GEMINI_API_KEY"):
        return False, "GEMINI_API_KEY not set"
    if not model_id or model_id.upper().startswith("VERIFY"):
        return False, "config [models].gemini_live is a VERIFY placeholder"
    return True, ""


class GeminiLiveVoice(Voice):  # pragma: no cover - needs network, key and audio devices
    name = "gemini"

    def __init__(self, model_id: str, language: str = "en"):
        self.model_id = model_id
        self.language = language
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self._session: Any = None
        self._tasks: list[asyncio.Task] = []
        self._fallback = LocalVoice()
        self._on_utterance: UtteranceHandler | None = None
        self._on_tool: ToolHandler | None = None
        self._cm: Any = None

    async def start(self, on_utterance: UtteranceHandler, on_tool: ToolHandler | None = None) -> None:
        self._on_utterance, self._on_tool = on_utterance, on_tool
        config = {
            "response_modalities": ["AUDIO"],
            "system_instruction": SYSTEM_PROMPT,
            "tools": [{"function_declarations": TOOLS}],
            "input_audio_transcription": {},
        }
        try:
            self._cm = self.client.aio.live.connect(model=self.model_id, config=config)
            self._session = await asyncio.wait_for(self._cm.__aenter__(), timeout=10)
        except Exception as e:
            log.warning("gemini_live_unavailable", f"{type(e).__name__}: {e}; using local voice")
            self._session = None
            return
        self._tasks = [asyncio.create_task(self._mic_loop()), asyncio.create_task(self._recv_loop())]

    async def _mic_loop(self) -> None:
        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=50)
        loop = asyncio.get_running_loop()

        def cb(indata, frames, t, status):  # audio thread
            loop.call_soon_threadsafe(lambda: q.full() or q.put_nowait(bytes(indata)))

        with sd.RawInputStream(samplerate=IN_RATE, channels=1, dtype="int16", blocksize=CHUNK, callback=cb):
            while self._session is not None:
                data = await q.get()
                await self._session.send_realtime_input(audio=types.Blob(data=data, mime_type=f"audio/pcm;rate={IN_RATE}"))

    async def _recv_loop(self) -> None:
        out = sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16")
        out.start()
        try:
            while self._session is not None:
                async for msg in self._session.receive():
                    sc = getattr(msg, "server_content", None)
                    if sc is not None:
                        if getattr(sc, "input_transcription", None) and sc.input_transcription.text and self._on_utterance:
                            await self._on_utterance(sc.input_transcription.text)
                        turn = getattr(sc, "model_turn", None)
                        for part in getattr(turn, "parts", None) or []:
                            if getattr(part, "inline_data", None) and part.inline_data.data:
                                out.write(part.inline_data.data)
                    tc = getattr(msg, "tool_call", None)
                    if tc is not None and self._on_tool:
                        responses = []
                        for fc in tc.function_calls:
                            result = await self._on_tool(fc.name, dict(fc.args or {}))
                            responses.append(types.FunctionResponse(id=fc.id, name=fc.name, response=result))
                        await self._session.send_tool_response(function_responses=responses)
        finally:
            out.stop()

    async def say(self, text: str) -> None:
        if self._session is None:
            await self._fallback.say(text)
            return
        try:
            await self._session.send_client_content(
                turns={"role": "user", "parts": [{"text": f"Say this to the person, naturally and briefly: {text}"}]},
                turn_complete=True,
            )
        except Exception as e:
            log.warning("gemini_say_failed", str(e))
            await self._fallback.say(text)

    async def say_verbatim(self, text: str) -> None:
        await self.interrupt()
        await self._fallback.say(text)  # deterministic: never through the model

    async def interrupt(self) -> None:
        await self.stop()

    async def stop(self) -> None:
        session, self._session = self._session, None
        for t in self._tasks:
            t.cancel()
        self._tasks = []
        if session is not None and self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:
                pass
