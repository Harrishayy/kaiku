"""Crisis triggers (section 10 of docs/plans/01-foundation.md):

- phrase:      crisis phrase in any utterance / transcript (config/safety_phrases.toml, fi/en/sv)
- phq9_item9:  PHQ-9 item 9 answered > 0
- manual:      top button long-pressed >= 2 s

Pure, deterministic, synchronous. The phrase list WILL miss things (docs/safety.md).
"""

from __future__ import annotations

import re
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from kaiku_contracts.config import find_repo_file

TriggerKind = Literal["phrase", "phq9_item9", "manual"]

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
class Trigger:
    kind: TriggerKind
    detail: str = ""  # matched phrase (never the full utterance)
    language: str | None = None


class SafetyGate:
    def __init__(self, phrases: dict[str, list[str]]):
        self.patterns: list[tuple[str, str, re.Pattern[str]]] = []
        for lang, items in phrases.items():
            for phrase in items:
                for v in _variants(phrase):
                    if v:
                        # word boundary at the start only: "suicid" style stems + "not ok" ~ "not okay"
                        self.patterns.append((lang, phrase, re.compile(r"(?<!\w)" + re.escape(v))))

    @classmethod
    def from_file(cls, path: Path | None = None) -> SafetyGate:
        path = path or find_repo_file("config/safety_phrases.toml")
        if not path or not path.is_file():
            raise FileNotFoundError("config/safety_phrases.toml not found — the safety gate must not run without it")
        data = tomllib.loads(path.read_text())
        return cls({k: v["phrases"] for k, v in data.items() if isinstance(v, dict) and "phrases" in v})

    def check_text(self, text: str) -> Trigger | None:
        if not text:
            return None
        for variant in _variants(text):
            for lang, phrase, pat in self.patterns:
                if pat.search(variant):
                    return Trigger("phrase", phrase, lang)
        return None

    @staticmethod
    def check_phq9(item9_score: int | None = None, item9_positive: bool | None = None) -> Trigger | None:
        if item9_positive or (item9_score is not None and item9_score > 0):
            return Trigger("phq9_item9")
        return None


class ButtonLongPress:
    """Tracks one button; `poll(now)` fires once when held >= hold_s (no need to wait for release)."""

    def __init__(self, hold_s: float = 2.0):
        self.hold_s = hold_s
        self._down_at: float | None = None
        self._fired = False

    def update(self, pressed: bool, now: float) -> Trigger | None:
        if pressed:
            if self._down_at is None:
                self._down_at, self._fired = now, False
            return self.poll(now)
        fired = self.poll(now)
        self._down_at = None
        return fired

    def poll(self, now: float) -> Trigger | None:
        if self._down_at is not None and not self._fired and now - self._down_at >= self.hold_s:
            self._fired = True
            return Trigger("manual")
        return None

    @property
    def held(self) -> bool:
        return self._down_at is not None

    def was_short_press(self, pressed: bool, now: float) -> bool:
        """Helper for a release event: True if this was a short tap (not a long press)."""
        return (not pressed) and self._down_at is not None and not self._fired and now - self._down_at < self.hold_s


class CrisisScript:
    """Pre-written crisis message (never generated). Loaded verbatim from config/safety_phrases.toml."""

    FALLBACK = (
        "I'm really glad you told me. I'm going to stop what we're doing. You can call the MIELI Crisis "
        "Helpline any time on 09 2525 0111. If you are in immediate danger, call 112."
    )

    def __init__(self, scripts: dict[str, str]):
        self.scripts = scripts

    @classmethod
    def from_file(cls, path: Path | None = None) -> CrisisScript:
        path = path or find_repo_file("config/safety_phrases.toml")
        if path and path.is_file():
            data = tomllib.loads(path.read_text())
            return cls({k: str(v) for k, v in data.get("script", {}).items()})
        return cls({})

    def text(self, language: str = "en") -> str:
        return self.scripts.get(language) or self.scripts.get("en") or self.FALLBACK
