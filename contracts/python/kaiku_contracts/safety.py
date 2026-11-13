"""Deterministic crisis phrase check (config/safety_phrases.toml) — the same matcher as the hub gate
(`hub/kaiku_hub/safety/gate.py`). Shared by the cloud (companion tool endpoint) and the companion evals;
`tools/tests/test_companion_evals.py` asserts it agrees with the hub gate on `fixtures/safety_cases.json`.
No model, no network. A Hit carries only the list phrase, never the utterance.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .config import find_repo_file

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'", "ʼ": "'"})
_NON_TEXT = re.compile(r"[^\w\s']+", re.UNICODE)
_WS = re.compile(r"\s+")


def phrases_path() -> Path:
    p = find_repo_file("config/safety_phrases.toml")
    if p is None:
        raise FileNotFoundError("config/safety_phrases.toml not found")
    return p


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).translate(_APOSTROPHES).casefold()
    t = _NON_TEXT.sub(" ", t.replace("-", " "))
    return _WS.sub(" ", t).strip()


def _variants(text: str) -> set[str]:
    n = normalise(text)
    return {n, n.replace("'", "")}


@dataclass(frozen=True)
class Hit:
    phrase: str  # the matched list phrase (never the utterance)
    language: str


class SafetyCheck:
    def __init__(self, phrases: dict[str, list[str]], scripts: dict[str, str] | None = None):
        self.scripts = scripts or {}
        self.patterns: list[tuple[str, str, re.Pattern[str]]] = []
        for lang, items in phrases.items():
            for phrase in items:
                for v in _variants(phrase):
                    if v:
                        self.patterns.append((lang, phrase, re.compile(r"(?<!\w)" + re.escape(v))))

    @classmethod
    def from_file(cls, path: Path | None = None) -> SafetyCheck:
        data = tomllib.loads((path or phrases_path()).read_text())
        phrases = {k: v["phrases"] for k, v in data.items() if isinstance(v, dict) and "phrases" in v}
        return cls(phrases, {k: str(v) for k, v in data.get("script", {}).items()})

    def check(self, text: str) -> Hit | None:
        if not text:
            return None
        for variant in _variants(text):
            for lang, phrase, pat in self.patterns:
                if pat.search(variant):
                    return Hit(phrase, lang)
        return None

    def script(self, language: str = "en") -> str:
        return self.scripts.get(language) or self.scripts.get("en", "")


def version(path: Path | None = None) -> str:
    return "safety+" + hashlib.sha256((path or phrases_path()).read_bytes()).hexdigest()[:8]
