"""Scripted keyed lines in Kaiku's one voice (D27): cloud voice cache first, visible fallback, never synthetic speech.

    say_line("greet.morning") ->  1. text from config/voice_lines.toml (caption; always printed)
                                  2. audio from GET /v1/voice/{key}?lang= (cloud TTS cache, same voice as Live)
                                  3. cloud 404/503/offline/slow -> visible text only

Audio plays only when `play_audio` (voice gemini/local or KAIKU_LOCAL_TTS=1); text mode and tests stay silent.
Not for the crisis script: that is CrisisScript + Voice.say_verbatim (deterministic, never a cache miss).
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
import tomllib
from typing import Any

import httpx
from kaiku_contracts.config import find_repo_file
from kaiku_contracts.jlog import get_logger

log = get_logger("hub")

# Only for keys the hub needs that config/voice_lines.toml doesn't have yet (ask the config owner to add them).
FALLBACK_TEXT: dict[str, dict[str, str]] = {
    "greet.two": {"en": "Oh, hello you two!", "fi": "No hei, te kaksi!", "sv": "Nämen, hej ni två!"},
}


def load_lines() -> dict[str, dict[str, str]]:
    """Flatten voice_lines.toml ([greet.morning] -> "greet.morning": {en, fi, sv, style?})."""
    path = find_repo_file("config/voice_lines.toml")
    if not path:
        return {}
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        log.warning("voice_lines_unreadable", str(e))
        return {}
    out: dict[str, dict[str, str]] = {}

    def walk(prefix: str, node: dict[str, Any]) -> None:
        if "en" in node and isinstance(node["en"], str):
            out[prefix] = {k: v for k, v in node.items() if isinstance(v, str)}
        for k, v in node.items():
            if isinstance(v, dict):
                walk(f"{prefix}.{k}" if prefix else k, v)

    walk("", data)
    return out


class LinePlayer:
    def __init__(self, *, cloud_url: str | None, token: str | None = None, play_audio: bool = False,
                 timeout_s: float = 3.0, transport: httpx.AsyncBaseTransport | None = None):
        self.cloud_url = cloud_url.rstrip("/") if cloud_url else None
        self.token = token
        self.play_audio = play_audio
        self.timeout_s = timeout_s
        self.transport = transport
        self.lines = {**FALLBACK_TEXT, **load_lines()}
        self._audio: dict[tuple[str, str], bytes] = {}
        self.last_source: str | None = None  # cloud | cache | text (for logs/tests)

    def text(self, key: str, lang: str = "en") -> str:
        entry = self.lines.get(key) or {}
        return entry.get(lang) or entry.get("en") or key

    async def fetch(self, key: str, lang: str) -> bytes | None:
        if (key, lang) in self._audio:
            return self._audio[(key, lang)]
        if not self.cloud_url:
            return None
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            async with httpx.AsyncClient(base_url=self.cloud_url, headers=headers, timeout=self.timeout_s,
                                         transport=self.transport) as c:
                r = await c.get(f"/v1/voice/{key}", params={"lang": lang})
        except Exception as e:
            log.info("voice_line_offline", f"{type(e).__name__}", key=key)
            return None
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("audio/"):
            log.info("voice_line_unavailable", f"HTTP {r.status_code}", key=key, lang=lang)
            return None
        self._audio[(key, lang)] = r.content
        return r.content

    async def say_line(self, key: str, lang: str = "en") -> str:
        text = self.text(key, lang)
        print(f"\U0001f916 Kaiku: {text}", file=sys.stderr, flush=True)
        cached = (key, lang) in self._audio
        audio = await self.fetch(key, lang)
        if audio is not None:
            self.last_source = "cache" if cached else "cloud"
            if self.play_audio:
                await _play_wav(audio)
        else:
            self.last_source = "text"
        log.info("voice_line", key, lang=lang, source=self.last_source)
        return text


    async def say_text(self, text: str, lang: str = "en") -> None:
        """Same Gemini voice for scripted fallback; failure stays visible and never uses OS TTS."""
        for key, translations in self.lines.items():
            if text in translations.values():
                await self.say_line(key, lang)
                return
        print(f"\U0001f916 Kaiku: {text}", file=sys.stderr, flush=True)
        if not self.cloud_url or not self.play_audio:
            return
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            async with httpx.AsyncClient(base_url=self.cloud_url, headers=headers, timeout=self.timeout_s,
                                         transport=self.transport) as c:
                r = await c.post("/v1/voice/say", json={"text": text[:400], "lang": lang})
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("audio/"):
                await _play_wav(r.content)
        except Exception as e:
            log.info("voice_text_unavailable", type(e).__name__)


async def _play_wav(data: bytes) -> None:
    player = shutil.which("afplay") or shutil.which("aplay")
    if not player:
        return
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav") as f:  # deleted right after playing
            f.write(data)
            f.flush()
            proc = await asyncio.create_subprocess_exec(player, f.name)
            await asyncio.wait_for(proc.wait(), timeout=30)
    except Exception as e:
        log.warning("voice_play_failed", str(e))
