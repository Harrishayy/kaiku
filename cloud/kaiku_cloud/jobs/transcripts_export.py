"""Opt-in conversation transcripts → a de-identified JSONL training set for Gemma (chat format).

Only transcripts the person opted into exist (device consent `transcripts`, off by default; crisis conversations are
never stored, see mind/session.py). De-identification, per home: the person's name and every capitalised word from
their `name`, `people` and `places` memories become [NAME] / [PERSON] / [PLACE]; emails, phone numbers, URLs and long
digit runs are replaced; the home id becomes a salted hash. Run after a person deletes something and the next export
no longer contains it (the export reads the live table; it keeps no copy).

    uv run --package kaiku-cloud python -m kaiku_cloud.jobs.transcripts_export OUT.jsonl [--salt S]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from ..settings import Settings
from ..store.db import Store

_STOP = {"I", "I'm", "My", "The", "A", "An", "We", "He", "She", "They", "Likes", "Loves", "Lives", "Has", "Is", "In",
         "On", "At", "By", "To", "And", "With", "Her", "His", "Their", "Our", "Name", "Called", "Usually", "Sometimes"}
_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
    (re.compile(r"https?://\S+|www\.\S+"), "[URL]"),
    (re.compile(r"\+?\d[\d\s().-]{6,}\d"), "[PHONE]"),
    (re.compile(r"\b\d{6,}\b"), "[NUMBER]"),
]
_TAG = {"name": "[NAME]", "people": "[PERSON]", "places": "[PLACE]"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\b[A-ZÅÄÖ][\wåäöÅÄÖ'-]+", text) if w not in _STOP}


def identifiers(memories: list[dict[str, Any]]) -> dict[str, str]:
    """Words to replace for one home, from its own memories (longest first when applied)."""
    out: dict[str, str] = {}
    for m in memories:
        tag = _TAG.get(m.get("category", ""))
        if tag:
            for w in _words(m.get("text", "")):
                out.setdefault(w, tag)
    return out


def scrub(text: str, ids: dict[str, str]) -> str:
    for pat, rep in _PATTERNS:
        text = pat.sub(rep, text)
    for w in sorted(ids, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(w)}\b", ids[w], text)
    return text


def export(store: Store, salt: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cache: dict[str, dict[str, str]] = {}
    for t in store.transcripts():
        home = t["home_id"]
        if home not in cache:
            cache[home] = identifiers(store.memories(home))
        msgs = [{"role": "user" if turn["role"] == "person" else "model", "content": scrub(turn["text"], cache[home])}
                for turn in t["turns"] if turn.get("text", "").strip()]
        if not any(m["role"] == "model" for m in msgs):
            continue
        rows.append({"messages": msgs, "surface": t["surface"], "intent": t["intent"],
                     "home": hashlib.sha256(f"{salt}:{home}".encode()).hexdigest()[:12]})
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--salt", default="kaiku")
    a = ap.parse_args(argv)
    rows = export(Store(Settings().db_path), a.salt)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"{len(rows)} conversations → {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
