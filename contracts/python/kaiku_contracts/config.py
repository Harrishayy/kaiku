"""Load config/kaiku.toml (non-secret settings) with env-var overrides.

Lookup: $KAIKU_CONFIG, else the first `config/kaiku.toml` found walking up from CWD, else from this file.
Override any key with KAIKU_<SECTION>_<KEY>, e.g. KAIKU_RITUAL_DRUM_S=30 (parsed as TOML value if possible).
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any


def find_repo_file(rel: str) -> Path | None:
    for base in (Path.cwd(), Path(__file__).resolve()):
        for d in (base, *base.parents):
            if (d / rel).is_file():
                return d / rel
    return None


def _coerce(raw: str) -> Any:
    try:
        return tomllib.loads(f"x = {raw}")["x"]
    except tomllib.TOMLDecodeError:
        return raw


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    path = Path(os.environ["KAIKU_CONFIG"]) if os.environ.get("KAIKU_CONFIG") else find_repo_file("config/kaiku.toml")
    cfg: dict[str, Any] = tomllib.loads(path.read_text()) if path and path.is_file() else {}
    for section, values in cfg.items():
        if not isinstance(values, dict):
            continue
        for key in values:
            env = os.environ.get(f"KAIKU_{section}_{key}".upper())
            if env is not None:
                values[key] = _coerce(env)
    return cfg


def get(section: str, key: str, default: Any = None) -> Any:
    return load_config().get(section, {}).get(key, default)


def load_dotenv(path: str | os.PathLike[str] | None = None) -> None:
    """Load KEY=VALUE lines from .env into os.environ (existing env wins). Supports `# comments`."""
    p = Path(path) if path else find_repo_file(".env")
    if not p or not p.is_file():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        if key.strip() and value:
            os.environ.setdefault(key.strip(), value)
    load_config.cache_clear()
