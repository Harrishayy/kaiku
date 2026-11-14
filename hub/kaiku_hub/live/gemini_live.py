"""Consented Gemini Live PCM adapter with nonblocking playback, barge-in and bounded resumption."""

from __future__ import annotations

import asyncio
import os
import time
from threading import Lock
from typing import Any

from kaiku_contracts import genai_client
from kaiku_contracts.budget import BudgetExceeded
from kaiku_contracts.config import load_config
from kaiku_contracts.jlog import get_logger

from ..perception.speech import SpeechWindow
from .base import ToolHandler, UtteranceHandler, Voice
from .local_audio import LocalVoice
from .meter import SessionMeter

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
BUDGET_LINE = "Our voice connection is unavailable. Your check-in can continue on screen."


def available(model_id: str) -> tuple[bool, str]:
    if genai is None:
        return False, "google-genai not installed (uv sync --extra live)"
    if sd is None:
        return False, "sounddevice not installed (uv sync --extra live)"
    if not genai_client.available():
        return False, "no Gemini backend (GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT + ADC)"
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
    live = load_config().get("live", {})
    cfg: dict[str, Any] = {
        "response_modalities": ["AUDIO"],
        "system_instruction": system_instruction,
        "tools": tool_config(tools),
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        "session_resumption": {},
        "realtime_input_config": {
            "activity_handling": "START_OF_ACTIVITY_INTERRUPTS",
            "automatic_activity_detection": {
                "start_of_speech_sensitivity": live.get("start_sensitivity", "START_SENSITIVITY_LOW"),
                "end_of_speech_sensitivity": live.get("end_sensitivity", "END_SENSITIVITY_LOW"),
                "prefix_padding_ms": live.get("prefix_padding_ms", 120),
                "silence_duration_ms": live.get("silence_ms", 900),
            },
        },
    }
    if live.get("context_compression", True):
        cfg["context_window_compression"] = {"sliding_window": {}}
    if voice_name:
        cfg["speech_config"] = {"voice_config": {"prebuilt_voice_config": {"voice_name": voice_name}}}
    return cfg


class GeminiLiveVoice(Voice):
    name = "gemini"
    wants_session = True

    def __init__(self, model_id: str, language: str = "en", voice_name: str = "", stall_s: float = 4.0,
                 *, client: Any = None, audio: Any = None, meter_factory=SessionMeter):
        self.model_id = model_id
        self.language = language
        self.voice_name = voice_name
        self.stall_s = stall_s
        # Live's configured Developer API model is not a Vertex/enterprise model ID. Keep its
        # credential selection at this edge instead of inheriting the cloud text/TTS backend.
        if client is not None:
            self.client = client
        elif os.environ.get("GEMINI_API_KEY"):
            self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options={"api_version": "v1beta"})
        else:
            self.client = genai_client.make_client(api_version="v1beta")
        self.audio = audio if audio is not None else sd
        self.meter_factory = meter_factory
        self.fallback_say = None
        self.keep_transcript = False
        self.transcript: list[dict[str, Any]] = []
        self._transcript_pending: dict[str, dict[str, Any]] = {}
        self._pcm = bytearray()
        self._pcm_lock = Lock()
        self._input_text = ""
        self._speech_window = SpeechWindow()
        self._playback_until = 0.0
        self._resume: str | None = None
        self._connection: tuple[str, dict] | None = None
        self._generation = 0
        self._reconnects = 0
        self.max_seconds = float(load_config().get("live", {}).get("session_max_minutes", 5)) * 60
        self._deadline = 0.0
        self._session: Any = None
        self._tasks: list[asyncio.Task] = []
        self._fallback = LocalVoice()
        self._on_utterance: UtteranceHandler | None = None
        self._on_tool: ToolHandler | None = None
        self._cm: Any = None
        self._spoke = asyncio.Event()
        self._meter: SessionMeter | None = None

    async def start(self, on_utterance: UtteranceHandler, on_tool: ToolHandler | None = None) -> None:
        self._on_utterance, self._on_tool = on_utterance, on_tool  # no session until a ritual starts

    async def open_session(self, system_instruction: str, tools: list[dict[str, Any]],
                           model: str | None = None, voice: str | None = None) -> bool:
        await self.close_session()
        model = model or self.model_id
        config = live_config(system_instruction, tools, voice or self.voice_name)
        self.transcript = []
        self._transcript_pending = {}
        self._resume = None
        self._reconnects = 0
        self._deadline = time.monotonic() + self.max_seconds
        self._connection = (model, config)
        meter = self.meter_factory("gemini", model)
        try:
            meter.open()  # spend cap (kaiku_contracts/budget.py): over it = no session, scripted ritual
        except BudgetExceeded as e:
            log.warning("gemini_live_budget", str(e))
            return False
        try:
            self._cm = self.client.aio.live.connect(model=model, config=config)
            self._session = await asyncio.wait_for(self._cm.__aenter__(), timeout=10)
        except Exception as e:
            log.warning("gemini_live_unavailable", f"{type(e).__name__}: {e}; scripted lines only")
            self._session = None
            return False
        log.info("gemini_live_open", model, voice=voice or self.voice_name)
        self._meter = meter
        meter.start(self._budget_exceeded)
        self._start_io()
        return True

    async def _mic_loop(self) -> None:
        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=50)
        loop = asyncio.get_running_loop()

        def cb(indata, frames, t, status):  # audio thread
            chunk = bytes(indata)
            def enqueue():
                if q.full():
                    self._speech_window.invalid = True
                else:
                    if status:
                        self._speech_window.invalid = True
                    q.put_nowait(chunk)
            loop.call_soon_threadsafe(enqueue)

        with self.audio.RawInputStream(samplerate=IN_RATE, channels=1, dtype="int16", blocksize=CHUNK, callback=cb):
            while self._session is not None:
                data = await q.get()
                with self._pcm_lock:
                    quiet = not self._pcm and time.monotonic() >= self._playback_until
                self._speech_window.add(data, usable=quiet)
                await asyncio.wait_for(self._session.send_realtime_input(
                    audio=types.Blob(data=data, mime_type=f"audio/pcm;rate={IN_RATE}")), timeout=10)

    def _start_io(self) -> None:
        mic = asyncio.create_task(self._mic_loop())
        mic.add_done_callback(self._mic_done)
        self._tasks += [mic, asyncio.create_task(self._recv_loop()), asyncio.create_task(self._expire())]

    def _mic_done(self, task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            log.warning("gemini_microphone_failed", type(task.exception()).__name__)
            if self._session is not None:
                asyncio.create_task(self.close_session())

    async def _expire(self) -> None:
        await asyncio.sleep(max(0, self._deadline - time.monotonic()))
        await self.close_session()

    def _remember(self, role: str, text: str) -> None:
        if self.keep_transcript and text:
            pending = self._transcript_pending.get(role)
            if self.transcript and self.transcript[-1] is pending:
                combined = pending["text"] + text
                pending["text"] = combined[-2000:]
                if len(combined) > 2000:
                    pending["complete"] = False
            else:
                pending = {"role": role, "text": text[:2000], "complete": False if len(text) > 2000 else None}
                self.transcript.append(pending)
                self._transcript_pending[role] = pending
                del self.transcript[:-600]

    def _finish_transcript(self, role: str, complete: bool) -> None:
        pending = self._transcript_pending.pop(role, None)
        if pending is not None and pending.get("complete") is not False:
            pending["complete"] = complete

    async def _complete_utterance(self) -> None:
        text, self._input_text = self._input_text, ""
        features = self._speech_window.finish(heard=bool(text))
        if features and self.on_speech_features and self._session is not None:
            await self.on_speech_features(features)
        handler = self.on_completed_utterance or self._on_utterance
        if text and handler:
            await handler(text)

    def _clear_audio(self) -> None:
        with self._pcm_lock:
            self._pcm.clear()

    async def _recv_loop(self) -> None:
        session = self._session
        generation = self._generation

        def playback(outdata, frames, timing, status):
            with self._pcm_lock:
                count = min(len(outdata), len(self._pcm))
                outdata[:count] = self._pcm[:count]
                outdata[count:] = bytes(len(outdata) - count)
                del self._pcm[:count]
                if count:
                    self._playback_until = time.monotonic() + frames / OUT_RATE
                    self._speech_window.invalid = True

        try:
            with self.audio.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16", callback=playback):
                while session is self._session:
                    async for msg in session.receive():
                        update = getattr(msg, "session_resumption_update", None)
                        if update and getattr(update, "resumable", False):
                            self._resume = update.new_handle
                        if getattr(msg, "go_away", None):
                            raise ConnectionError("server rotation")
                        sc = getattr(msg, "server_content", None)
                        if sc is not None:
                            if getattr(sc, "interrupted", False):
                                self._clear_audio()
                            interim = getattr(sc, "interim_input_transcription", None)
                            if interim is not None and interim.text and self.on_partial_utterance:
                                await self.on_partial_utterance(interim.text)
                                if self._session is None:
                                    return
                            it = getattr(sc, "input_transcription", None)
                            if it is not None:
                                if it.text:
                                    self._remember("person", it.text)
                                    self._input_text = (self._input_text + it.text)[-2000:]
                                    if self.on_partial_utterance:
                                        await self.on_partial_utterance(self._input_text)
                                if self._session is None:
                                    return
                                if getattr(it, "finished", False):
                                    self._finish_transcript("person", True)
                                    await self._complete_utterance()
                                if self._session is None:
                                    return
                            if getattr(sc, "turn_complete", False):
                                # Older responses omit Transcription.finished. Flush the accumulated
                                # person turn once at the model-turn boundary rather than per fragment.
                                await self._complete_utterance()
                                if self._session is None:
                                    return
                            ot = getattr(sc, "output_transcription", None)
                            if ot is not None and ot.text:
                                self._remember("kaiku", ot.text)
                            if getattr(sc, "interrupted", False):
                                self._finish_transcript("kaiku", False)
                            elif ot is not None and getattr(ot, "finished", False):
                                self._finish_transcript("kaiku", True)
                            turn = getattr(sc, "model_turn", None)
                            for part in getattr(turn, "parts", None) or []:
                                if getattr(part, "inline_data", None) and part.inline_data.data:
                                    self._spoke.set()
                                    with self._pcm_lock:
                                        self._pcm.extend(part.inline_data.data)
                                        del self._pcm[:max(0, len(self._pcm) - OUT_RATE * 2 * 30)]
                        tc = getattr(msg, "tool_call", None)
                        if tc is not None and self._on_tool:
                            self._tasks.append(asyncio.create_task(self._handle_tools(session, tc)))
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("gemini_live_recv_ended", type(e).__name__)
            if self._session is session and self._generation == generation:
                await self._reconnect(generation)

    async def _handle_tools(self, session, tc) -> None:
        responses = []
        try:
            for fc in tc.function_calls:
                result = await self._on_tool(fc.name, dict(fc.args or {}))
                responses.append(types.FunctionResponse(id=fc.id, name=fc.name, response=result))
            if self._session is session:
                await asyncio.wait_for(session.send_tool_response(function_responses=responses), timeout=10)
        except Exception as e:
            log.warning("gemini_tool_failed", type(e).__name__)

    async def _reconnect(self, generation: int) -> None:
        self._speech_window.reset()
        self._input_text = ""  # device/network gaps never join separate speech windows
        # No resume handle means we cannot safely continue a possibly interrupted conversation.
        limit = int(load_config().get("live", {}).get("reconnect_attempts", 2))
        if not self._resume or not self._connection or self._reconnects >= limit:
            await self.close_session()
            return
        self._reconnects += 1
        meter, self._meter = self._meter, None
        await self.close_session()
        next_generation = self._generation
        await asyncio.sleep(min(self._reconnects, 2))
        if self._generation != next_generation:
            if meter:
                meter.stop()
            return
        model, cfg = self._connection
        cfg = {**cfg, "session_resumption": {"handle": self._resume}}
        try:
            cm = self.client.aio.live.connect(model=model, config=cfg)
            session = await asyncio.wait_for(cm.__aenter__(), timeout=10)
            if self._generation != next_generation:
                await asyncio.wait_for(cm.__aexit__(None, None, None), timeout=5)
                if meter:
                    meter.stop()
                return
            self._cm, self._session = cm, session
            self._meter = meter
            self._start_io()
        except Exception as e:
            if meter:
                meter.stop()
            log.warning("gemini_reconnect_failed", type(e).__name__)

    async def _say_fallback(self, text: str) -> None:
        if self.fallback_say:
            await self.fallback_say(text)
        else:
            await self._fallback.say(text)

    async def say(self, text: str) -> None:
        if self._session is None:
            await self._say_fallback(text)
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
            await self._say_fallback(text)

    async def send_context(self, text: str) -> None:
        """Append a context turn mid-session (Live capabilities guide, "Incremental content updates": Gemini 3.8
        accepts `send_client_content` mid-session to append structured text turns). turn_complete=True lets the
        model react now; with proactive audio it may also stay silent. No session -> dropped."""
        if self._session is None:
            return
        try:
            await self._session.send_client_content(
                turns={"role": "user", "parts": [{"text": f"(context from Kaiku's senses, not said by the person; "
                                                          f"react briefly only if it feels natural) {text}"}]},
                turn_complete=True,
            )
        except Exception as e:
            log.warning("gemini_context_failed", type(e).__name__)

    async def say_verbatim(self, text: str) -> None:
        await self.interrupt()
        await self._fallback.say(text)  # deterministic visible script, never sent to a model

    async def interrupt(self) -> None:
        await self.close_session()

    async def _budget_exceeded(self) -> None:
        """Cap reached mid-session: close politely; the ritual continues with scripted local lines."""
        await self.close_session()
        await self._say_fallback(BUDGET_LINE)

    async def close_session(self) -> None:
        self._generation += 1
        self._input_text = ""
        self._speech_window.reset()
        self._clear_audio()
        if self._meter is not None:
            self._meter.stop()
            self._meter = None
        session, self._session = self._session, None
        current = asyncio.current_task()
        others = [t for t in self._tasks if t is not current and not t.done()]
        self._tasks = []
        for t in others:
            t.cancel()
        if others:
            await asyncio.gather(*others, return_exceptions=True)
        if session is not None and self._cm is not None:
            try:
                await asyncio.wait_for(self._cm.__aexit__(None, None, None), timeout=5)
            except Exception:
                pass
            log.info("gemini_live_closed", "")

    async def stop(self) -> None:
        await self.close_session()
