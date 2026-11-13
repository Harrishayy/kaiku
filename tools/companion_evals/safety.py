"""Crisis phrase check, identical to the hub gate (`hub/kaiku_hub/safety/gate.py`).

tools/ must not import hub code, so the small matcher is duplicated here and reads the same
`config/safety_phrases.toml`. `tools/tests/test_companion_evals.py` runs both on
`fixtures/safety_cases.json` and asserts identical results — change both or neither.
Deterministic, no model: evals call this on every simulated user turn BEFORE any model call.
"""

from __future__ import annotations

import re
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PHRASES = ROOT / "config" / "safety_phrases.toml"

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'", "ʼ": "'"})
_NON_TEXT = re.compile(r"[^\w\s']+", re.UNICODE)
_WS = re.compile(r"\s+")


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
    def from_file(cls, path: Path = PHRASES) -> SafetyCheck:
        data = tomllib.loads(path.read_text())
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


def version(path: Path = PHRASES) -> str:
    import hashlib

    return "safety+" + hashlib.sha256(path.read_bytes()).hexdigest()[:8]
