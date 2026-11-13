"""Gemini Live ephemeral tokens (apps never hold the Gemini key — root rule 5).

Verified in the Gemini docs (geminiDocs MCP, "Ephemeral tokens in Live API", 2026-11-13): `POST
https://generativelanguage.googleapis.com/v1beta/auth_tokens` with `x-goog-api-key`, body `{uses, expireTime,
newSessionExpireTime, liveConnectConstraints: {model}}`; the response `name` is the token. Clients use it as the
API key for the Live API (v1beta only), or as `access_token=` / `Authorization: Token <t>` without the SDK.
Defaults: 1 min to start a session, 30 min session lifetime; resume with sessionResumption inside that window.

No GEMINI_API_KEY, or any error -> None (the device falls back: hub with its own key, apps to scripted lines).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import httpx
from kaiku_contracts.api import LiveToken
from kaiku_contracts.jlog import get_logger

URL = "https://generativelanguage.googleapis.com/v1beta/auth_tokens"
SESSION_MIN = 30
START_MIN = 1
log = get_logger("cloud.live_token")


def _z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def mint(model: str, *, api_key: str | None = None, now: datetime | None = None,
         transport: httpx.BaseTransport | None = None, timeout_s: float = 8.0) -> LiveToken | None:
    key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    now = now or datetime.now(UTC)
    expires, start_by = now + timedelta(minutes=SESSION_MIN), now + timedelta(minutes=START_MIN)
    body = {"uses": 1, "expireTime": _z(expires), "newSessionExpireTime": _z(start_by),
            "liveConnectConstraints": {"model": model if model.startswith("models/") else f"models/{model}"}}
    try:
        with httpx.Client(timeout=timeout_s, transport=transport) as c:
            r = c.post(URL, json=body, headers={"x-goog-api-key": key})
            r.raise_for_status()
            token = r.json().get("name")
        if not token:
            raise ValueError("no token in response")
        return LiveToken(token=token, expires_at=expires, new_session_expires_at=start_by)
    except Exception as e:  # fail soft: never break the session bootstrap
        log.warning("live_token_failed", type(e).__name__)
        return None
