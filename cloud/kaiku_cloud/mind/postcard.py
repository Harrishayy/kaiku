"""Walk postcard (plan 06 §2): Nano Banana 2 Lite (`[mind].image_model`) paints a small postcard from walk STATS
only — a length word, light-hunt finds, a weather word — in one fixed style. Never photos, never faces, no text.
Cached on disk by (model, prompt) hash, so the same walk shape is generated once for everyone (nothing personal in
it). No fallback image: without a key / on failure / over [budget].images_per_home_day -> PostcardUnavailable and
the API answers 503 + hint; the app shows its own static card.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from kaiku_contracts.api import PostcardRequest
from kaiku_contracts.config import find_repo_file, get

from ..llm import gemini, ledger
from ..llm.errors import LlmUnavailable
from ..settings import TZ
from ..store.db import Store
from . import memory

STYLE = (
    "A small hand-painted watercolour postcard of a quiet Nordic nature path in {weather} weather, soft muted "
    "colours, gentle light, a calm and cosy mood after a {length} walk. Little painted details along the path: "
    "{finds}. Absolutely no people, no faces, no hands, no animals' faces close up, no text, no letters, no numbers, "
    "no logos, no photos."
)
FIND = re.compile(r"^[a-zäöå][a-zäöå ]{0,23}$")


class PostcardUnavailable(RuntimeError):
    pass


def length_word(minutes: int) -> str:
    return "short" if minutes < 15 else "gentle" if minutes < 40 else "long"


def clean_finds(finds: list[str], check) -> list[str]:
    out: list[str] = []
    for f in finds:
        w = re.sub(r"\s+", " ", f.casefold()).strip()
        if FIND.match(w) and not memory.health_detail(w) and not check(w) and w not in out:
            out.append(w)
    return out[:5]


def prompt_for(req: PostcardRequest, check) -> str:
    finds = clean_finds(req.finds, check)
    return STYLE.format(weather=req.weather_word, length=length_word(req.minutes),
                        finds=", ".join(finds) if finds else "a few small green leaves")


def cache_dir() -> Path:
    d = str(get("mind", "postcard_dir", "logs/postcards"))
    p = Path(d)
    if not p.is_absolute():
        root = find_repo_file("config/kaiku.toml")
        p = (root.parents[1] / d) if root else Path.cwd() / d
    return p


def make(store: Store, req: PostcardRequest, check, now: datetime | None = None) -> tuple[str, bool, str]:
    """(postcard id, cached?, model). Raises PostcardUnavailable."""
    now = now or datetime.now(UTC)
    model = gemini.image_model()
    prompt = prompt_for(req, check)
    pid = hashlib.sha256(f"{model}\n{prompt}".encode()).hexdigest()[:20]
    meta = store.kv_get(f"postcard:{pid}")
    if isinstance(meta, dict) and Path(meta.get("path", "")).is_file():
        return pid, True, model
    cap = int(get("budget", "images_per_home_day", 3))
    if store.model_calls_count(req.home_id, model, ledger.day_start_utc(now, TZ)) >= cap:
        raise PostcardUnavailable("daily postcard limit reached")
    try:
        data, mime = gemini.image(prompt, task="postcard", home_id=req.home_id)
    except LlmUnavailable as e:
        raise PostcardUnavailable(str(e)) from e
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(mime, "png")
    d = cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{pid}.{ext}"
    path.write_bytes(data)
    store.kv_set(f"postcard:{pid}", {"path": str(path), "mime": mime, "created": now.isoformat()})
    return pid, False, model


def load(store: Store, pid: str) -> tuple[bytes, str] | None:
    if not re.fullmatch(r"[0-9a-f]{20}", pid):
        return None
    meta = store.kv_get(f"postcard:{pid}")
    if not isinstance(meta, dict) or not Path(meta.get("path", "")).is_file():
        return None
    return Path(meta["path"]).read_bytes(), str(meta.get("mime", "image/png"))
