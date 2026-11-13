"""Kaiku's one voice (D27): keyed lines from config/voice_lines.toml, rendered by Gemini TTS, cached on disk.

    lines(lang)            -> {key: text}               (GET /v1/voice?lang=)
    audio(key, lang)       -> wav bytes                 (GET /v1/voice/{key}?lang=)
    python -m kaiku_cloud.voice [--lang en,fi,sv]       pre-render every line into the cache (needs GEMINI_API_KEY)

Voice name, model, default style, cache dir and timeout: config/kaiku.toml [voice]. Cache key = hash of
(model, voice, lang, text, style), so editing a line re-renders only that line. Fail soft: with no key and nothing
cached, `VoiceUnavailable` (the API answers 503 with a hint). The crisis message is never rendered from here.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import time
import tomllib
from pathlib import Path
from typing import Any

from kaiku_contracts.config import find_repo_file, get, load_dotenv
from kaiku_contracts.jlog import get_logger

LANGS: tuple[str, ...] = ("en", "fi", "sv")
log = get_logger("voice")
_cache: dict[str, tuple[float, dict[str, dict[str, str]]]] = {}


class VoiceUnavailable(RuntimeError):
    """TTS can't answer right now (no key, quota, network). Carries a hint for the client."""


class UnknownLine(KeyError):
    pass


def lines_path() -> Path | None:
    env = os.environ.get("KAIKU_VOICE_LINES")
    return Path(env) if env else find_repo_file("config/voice_lines.toml")


def _flatten(node: dict[str, Any], prefix: str = "") -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for k, v in node.items():
        if not isinstance(v, dict):
            continue
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v.get("en"), str):
            out[key] = {x: str(y) for x, y in v.items() if isinstance(y, str)}
        out.update(_flatten({kk: vv for kk, vv in v.items() if isinstance(vv, dict)}, key))
    return out


def all_lines() -> dict[str, dict[str, str]]:
    """{key: {en, fi, sv, style?}} — re-read when the file changes."""
    p = lines_path()
    if p is None or not p.is_file():
        return {}
    mtime = p.stat().st_mtime
    hit = _cache.get(str(p))
    if hit is None or hit[0] != mtime:
        _cache[str(p)] = (mtime, _flatten(tomllib.loads(p.read_text())))
    return _cache[str(p)][1]


def lines(lang: str) -> dict[str, str]:
    return {k: v.get(lang) or v["en"] for k, v in sorted(all_lines().items())}


def voice_name() -> str:
    return str(get("voice", "name", "Sulafat"))


def tts_model() -> str:
    return str(get("voice", "model", "") or get("models", "tts", ""))


def cache_dir() -> Path:
    env = os.environ.get("KAIKU_VOICE_CACHE")
    if env:
        return Path(env)
    rel = str(get("voice", "cache_dir", "logs/voice_cache"))
    root = find_repo_file("config/kaiku.toml")
    return (root.parents[1] / rel) if root else Path(rel)


def _spec(key: str, lang: str) -> tuple[str, str]:
    entry = all_lines().get(key)
    if entry is None:
        raise UnknownLine(key)
    return entry.get(lang) or entry["en"], entry.get("style") or str(get("voice", "style", "warm, gentle"))


def cache_path(key: str, lang: str) -> Path:
    text, style = _spec(key, lang)
    h = hashlib.sha256("|".join([tts_model(), voice_name(), lang, text, style]).encode()).hexdigest()[:12]
    return cache_dir() / lang / f"{key}.{h}.wav"


def _audio_bytes(resp: Any) -> bytes:
    """Last audio block of an Interactions response (SDK convenience property if present, else walk the steps)."""
    out = getattr(resp, "output_audio", None)
    data = getattr(out, "data", None) if out is not None else None
    if data is None:
        dump = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        for step in dump.get("steps") or []:
            for c in step.get("content") or []:
                if c.get("type") == "audio" and c.get("data"):
                    data = c["data"]
    if not data:
        raise VoiceUnavailable("TTS returned no audio")
    return base64.b64decode(data) if isinstance(data, str) else bytes(data)


def synthesize(text: str, style: str, lang: str) -> bytes:
    """One TTS call (google-genai Interactions API, unary -> complete WAV). Retries once with backoff."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    model = tts_model()
    if not key:
        raise VoiceUnavailable("GEMINI_API_KEY is not set on the cloud; audio is served from the cache only")
    if not model or model.upper().startswith("VERIFY"):
        raise VoiceUnavailable("config/kaiku.toml [voice].model is not set")
    from google import genai  # lazy: the cloud runs without it when voice is unused

    codes = get("voice", "lang_codes", {}) or {}
    timeout_s = float(get("voice", "timeout_s", 20))
    client = genai.Client(api_key=key, http_options={"timeout": int(timeout_s * 1000)})
    err: Exception | None = None
    for attempt in range(2):
        try:
            resp = client.interactions.create(
                model=model,
                input=[{"type": "user_input", "content": [{
                    "type": "text", "text": text,
                    "annotations": [{"type": "speech_metadata", "style": style}]}]}],
                response_format={"type": "audio"},
                generation_config={"speech_config": [{"voice": voice_name(), "language": codes.get(lang, lang)}]},
            )
            return _audio_bytes(resp)
        except VoiceUnavailable:
            raise
        except Exception as e:  # network, quota, shape: retry once, then fail soft
            err = e
            time.sleep(0.5 * (attempt + 1))
    raise VoiceUnavailable(f"TTS failed: {type(err).__name__}")


def audio(key: str, lang: str) -> bytes:
    """Cached wav for a line; renders + caches on a miss. Raises UnknownLine / VoiceUnavailable."""
    path = cache_path(key, lang)
    if path.is_file():
        return path.read_bytes()
    text, style = _spec(key, lang)
    data = synthesize(text, style, lang)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    log.info("voice_rendered", key, lang=lang, bytes=len(data))
    return data


def main(argv: list[str] | None = None) -> int:
    """Pre-render every line (demo works offline afterwards). Skips what's cached."""
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", default=",".join(LANGS))
    a = ap.parse_args(argv)
    failed = 0
    for lang in a.lang.split(","):
        for key in sorted(all_lines()):
            try:
                audio(key, lang)
            except VoiceUnavailable as e:
                print(f"{lang} {key}: {e}")
                failed += 1
                if "GEMINI_API_KEY" in str(e):
                    return 1
    print(f"voice cache: {cache_dir()} ({failed} failed)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
