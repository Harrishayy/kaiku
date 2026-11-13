"""Runtime settings for the cloud: env vars + config/kaiku.toml. Consensus criteria: config/criteria.toml
(loaded per recompute by service.active_criteria, never cached across file edits)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from kaiku_contracts.config import find_repo_file, load_config

VERSION = "0.1.0"


def _tz() -> ZoneInfo:
    """Local day boundaries come from config/criteria.toml [defaults].timezone (Helsinki if unavailable)."""
    try:
        from kaiku_contracts.criteria import load_criteria

        return ZoneInfo(load_criteria().defaults.timezone)
    except Exception:
        return ZoneInfo("Europe/Helsinki")


TZ = _tz()


def _default_db() -> str:
    root = find_repo_file("config/kaiku.toml")
    base = root.parents[1] / "logs" if root else Path("logs")
    return str(base / "kaiku.sqlite")


def _default_web_dir() -> str | None:
    root = find_repo_file("config/kaiku.toml")
    if root and (root.parents[1] / "apps/web/out").is_dir():
        return str(root.parents[1] / "apps/web/out")
    return None


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: os.environ.get("KAIKU_DB_PATH") or _default_db())
    home_token: str | None = field(default_factory=lambda: os.environ.get("KAIKU_HOME_TOKEN") or None)
    admin_token: str | None = field(default_factory=lambda: os.environ.get("KAIKU_ADMIN_TOKEN") or None)
    web_dir: str | None = field(default_factory=lambda: os.environ.get("KAIKU_WEB_DIR") or _default_web_dir())
    llm: str = field(default_factory=lambda: os.environ.get("KAIKU_LLM", "template"))

    @property
    def phq9_mode(self) -> str:
        return str(load_config().get("ritual", {}).get("phq9_mode", "laptop"))

    @property
    def phq9_every_days(self) -> int:
        return int(load_config().get("ritual", {}).get("phq9_every_days", 14))
