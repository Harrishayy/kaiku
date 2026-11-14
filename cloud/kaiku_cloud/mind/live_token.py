"""Gemini Live ephemeral tokens with Kaiku's whole session LOCKED in (apps never hold the Gemini key — root rule 5).

Verified in the Gemini docs (geminiDocs MCP, Live API reference "Ephemeral authentication tokens", 2026-11-14) and by
a real call: `POST https://generativelanguage.googleapis.com/v1beta/auth_tokens` with `x-goog-api-key`, body
`{uses, expireTime, newSessionExpireTime, bidiGenerateContentSetup}` (the REST field; `liveConnectConstraints` is
only the SDK's name and the REST API rejects it with 400). The response `name` is the token; clients connect to
`BidiGenerateContentConstrained?access_token=<token>` (v1beta).

`fieldMask: "model"` locks ONLY the model (as google-genai's tokens.py does): the device sends its own setup frame —
persona + context card, voice, tools, VAD, session resumption, context compression — built from the session
bootstrap. Without a mask the token would lock every field and the device's resumption / compression / tool
behaviour would be silently ignored. The cloud's recommended setup (persona, voice, `[live]` VAD) still goes back to
the device as `live_setup`; Kaiku's apps send exactly that plus their own transport fields.

Defaults: 1 min to start, configured session authorization/resumption lifetime. Clients enforce the duration.
No GEMINI_API_KEY, budget admission or provider availability -> None; apps keep the microphone closed.
Robot bootstrap skips token minting because its server-side Live adapter meters its own key.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from kaiku_contracts import budget
from kaiku_contracts.api import LiveToken
from kaiku_contracts.config import get
from kaiku_contracts.jlog import get_logger

from ..llm import ledger

URL = "https://generativelanguage.googleapis.com/v1beta/auth_tokens"
_MINT_LOCK = threading.Lock()
START_MIN = 1
log = get_logger("cloud.live_token")


def _z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def model_path(model: str) -> str:
    return model if model.startswith("models/") else f"models/{model}"


def setup(model: str, voice: str, system_instruction: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
    """The BidiGenerateContentSetup (REST camelCase) for one Kaiku session. VAD knobs: config/kaiku.toml [live]."""
    vad: dict[str, Any] = {"disabled": False}
    for key, field in (("start_sensitivity", "startOfSpeechSensitivity"), ("end_sensitivity", "endOfSpeechSensitivity"),
                       ("prefix_padding_ms", "prefixPaddingMs"), ("silence_ms", "silenceDurationMs")):
        v = get("live", key, None)
        if v not in (None, ""):
            vad[field] = v
    gen: dict[str, Any] = {"responseModalities": ["AUDIO"]}
    if voice:
        gen["speechConfig"] = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}
    if get("live", "affective_dialog", False):
        gen["enableAffectiveDialog"] = True
    s: dict[str, Any] = {
        "model": model_path(model),
        "generationConfig": gen,
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "realtimeInputConfig": {"automaticActivityDetection": vad,
                                "activityHandling": "START_OF_ACTIVITY_INTERRUPTS"},  # barge-in
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
        "sessionResumption": {},
    }
    # `behavior: NON_BLOCKING` (asynchronous function calling, supported on gemini-3.8-live per the Live tools
    # guide): the model keeps talking while `feel` runs; the device answers with the result's `scheduling`.
    decls = [{k: t[k] for k in ("name", "description", "parameters", "behavior") if k in t} for t in tools]
    if decls:
        s["tools"] = [{"functionDeclarations": decls}]
    if get("live", "context_compression", True):
        s["contextWindowCompression"] = {"slidingWindow": {}}  # sessions longer than the audio context limit
    return s


def mint(model: str, *, live_setup: dict[str, Any] | None = None, api_key: str | None = None,
         now: datetime | None = None, transport: httpx.BaseTransport | None = None,
         timeout_s: float = 8.0, home_id: str | None = None) -> LiveToken | None:
    key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    now = now or datetime.now(UTC)
    minutes = float(get("live", "session_max_minutes", 5))
    expires, start_by = now + timedelta(minutes=minutes), now + timedelta(minutes=START_MIN)
    body = {"uses": 1, "expireTime": _z(expires), "newSessionExpireTime": _z(start_by),
            "bidiGenerateContentSetup": {"model": model_path(model)}, "fieldMask": "model"}
    started = time.perf_counter()
    estimate = budget.estimate(model, audio_min=minutes)
    try:
        # The estimate reserves the full client-enforced duration. Token expiry governs authorization,
        # not a guaranteed server-side end to an already established audio stream.
        with _MINT_LOCK:
            budget.charge("gemini", model, estimate, task="live_reservation", component="cloud",
                          units=f"reserved_audio_minutes={minutes:g}")
            with httpx.Client(timeout=timeout_s, transport=transport) as c:
                r = c.post(URL, json=body, headers={"x-goog-api-key": key})
                r.raise_for_status()
                token = r.json().get("name")
            if not token:
                raise ValueError("no token in response")
        ledger.record(model, "live_reservation", ok=True, home_id=home_id,
                      latency_ms=(time.perf_counter() - started) * 1000)
        return LiveToken(token=token, expires_at=expires, new_session_expires_at=start_by)
    except Exception as e:  # fail soft: no unmetered token when the budget or provider is unavailable
        status = getattr(getattr(e, "response", None), "status_code", None)
        reason = "budget" if isinstance(e, budget.BudgetExceeded) else "unavailable"
        ledger.record(model, "live_reservation", ok=False, home_id=home_id, route=reason,
                      latency_ms=(time.perf_counter() - started) * 1000)
        log.warning("live_token_failed", type(e).__name__, status=status)
        return None
