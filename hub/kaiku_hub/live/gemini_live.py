"""Gemini Live voice adapter (KAIKU_VOICE=gemini). Optional deps: `uv sync --extra live`.

Model + voice from config ([models].gemini_live = gemini-3.8-live, [voice].name — the same prebuilt voice the
cloud TTS uses, so scripted lines and live talk sound like one Kaiku). Field names checked in the Gemini docs
(geminiDocs MCP, 2026-11-14, Live API capabilities guide, Python "Current SDK"): v1beta client
(`http_options={"api_version": "v1beta"}`), `enable_affective_dialog=True`, `proactivity={"proactive_audio": True}`,
`speech_config.voice_config.prebuilt_voice_config.voice_name`, `input_audio_transcription`,
`client.aio.live.connect`, `send_realtime_input(audio=Blob)`, `send_client_content`, `send_tool_response`.
Audio: 16 kHz PCM in / 24 kHz PCM out.

One Live session per ritual (`open_session` at ritual start, `close_session` at the end): the mic streams to Gemini
only during that consented conversation. System instruction + tools come from the cloud
(`POST /v1/companion/session`) or, if it's missing/offline, from the local `tools.py`. The ritual state machine
stays the boss; if the model doesn't start speaking within `stall_s` after a scripted prompt, the line is spoken
locally instead (fail soft). Input transcripts go to the hub's on_utterance (safety gate first) and are never logged.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from kaiku_contracts.jlog import get_logger

from .base import ToolHandler, UtteranceHandler, Voice
from .local_audio import LocalVoice

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


def tool_config(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Accept either plain function declarations [{name, description, parameters}] or Gemini tool blocks."""
    if tools and all(isinstance(t, dict) and "function_declarations" in t for t in tools):
        return tools
    decls = [t for t in tools if isinstance(t, dict) and t.get("name")]
    return [{"function_declarations": decls}] if decls else []


def live_config(system_instruction: str, tools: list[dict[str, Any]], voice_name: str = "") -> dict[str, Any]:
    """LiveConnectConfig as a dict (pure; tested without the SDK)."""
    cfg: dict[str, Any] = {
        "response_modalities": ["AUDIO"],
        "system_instruction": system_instruction,
        "tools": tool_config(tools),
        "input_audio_transcription": {},
        "enable_affective_dialog": True,
        "proactivity": {"proactive_audio": True},
    }
    if voice_name:
        cfg["speech_config"] = {"voice_config": {"prebuilt_voice_config": {"voice_name": voice_name}}}
    return cfg


class GeminiLiveVoice(Voice):  # pragma: no cover - needs network, key and audio devices
    name = "gemini"
    wants_session = True

    def __init__(self, model_id: str, language: str = "en", voice_name: str = "", stall_s: float = 4.0):
        self.model_id = model_id
        self.language = language
        self.voice_name = voice_name
        self.stall_s = stall_s
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options={"api_version": "v1beta"})
        self._session: Any = None
        self._tasks: list[asyncio.Task] = []
        self._fallback = LocalVoice()
        self._on_utterance: UtteranceHandler | None = None
        self._on_tool: ToolHandler | None = None
        self._cm: Any = None
        self._spoke = asyncio.Event()

    async def start(self, on_utterance: UtteranceHandler, on_tool: ToolHandler | None = None) -> None:
        self._on_utterance, self._on_tool = on_utterance, on_tool  # no session until a ritual starts

    async def open_session(self, system_instruction: str, tools: list[dict[str, Any]],
                           model: str | None = None, voice: str | None = None) -> bool:
        await self.close_session()
        model = model or self.model_id
        config = live_config(system_instruction, tools, voice or self.voice_name)
        try:
            self._cm = self.client.aio.live.connect(model=model, config=config)
            self._session = await asyncio.wait_for(self._cm.__aenter__(), timeout=10)
        except Exception as e:
            log.warning("gemini_live_unavailable", f"{type(e).__name__}: {e}; scripted lines only")
            self._session = None
            return False
        log.info("gemini_live_open", model, voice=voice or self.voice_name)
        self._tasks = [asyncio.create_task(self._mic_loop()), asyncio.create_task(self._recv_loop())]
        return True

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
                        it = getattr(sc, "input_transcription", None)
                        if it is not None and it.text and self._on_utterance:
                            await self._on_utterance(it.text)  # safety gate runs first in the hub
                            if self._session is None:  # crisis closed the session: play nothing more
                                return
                        turn = getattr(sc, "model_turn", None)
                        for part in getattr(turn, "parts", None) or []:
                            if getattr(part, "inline_data", None) and part.inline_data.data:
                                self._spoke.set()
                                out.write(part.inline_data.data)
                    tc = getattr(msg, "tool_call", None)
                    if tc is not None and self._on_tool:
                        responses = []
                        for fc in tc.function_calls:
                            result = await self._on_tool(fc.name, dict(fc.args or {}))
                            responses.append(types.FunctionResponse(id=fc.id, name=fc.name, response=result))
                        await self._session.send_tool_response(function_responses=responses)
        except Exception as e:
            log.warning("gemini_live_recv_ended", f"{type(e).__name__}")
        finally:
            out.stop()

    async def say(self, text: str) -> None:
        if self._session is None:
            await self._fallback.say(text)
            return
        self._spoke.clear()
        try:
            await self._session.send_client_content(
                turns={"role": "user", "parts": [{"text": f"(Kaiku, say this to the person, naturally and briefly: "
                                                          f"{text})"}]},
                turn_complete=True,
            )
            await asyncio.wait_for(self._spoke.wait(), timeout=self.stall_s)
        except Exception as e:  # stall or send failure -> the scripted line, locally
            log.warning("gemini_say_fallback", type(e).__name__)
            await self._fallback.say(text)

    async def say_verbatim(self, text: str) -> None:
        await self.interrupt()
        await self._fallback.say(text)  # deterministic: never through the model

    async def interrupt(self) -> None:
        await self.close_session()

    async def close_session(self) -> None:
        session, self._session = self._session, None
        for t in self._tasks:
            t.cancel()
        self._tasks = []
        if session is not None and self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:
                pass
            log.info("gemini_live_closed", "")

    async def stop(self) -> None:
        await self.close_session()
