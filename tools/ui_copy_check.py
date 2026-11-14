"""User-facing copy must never contain build notes (config paths, obs types, TODO/VERIFY, file names...).

Scans app source (web .tsx/.ts, Swift, glasses web app) with comments stripped and reports any developer-only
phrase that would reach a person's screen. Internal team pages (/tune, /eval, /health, /debug) are exempt.
Run: `uv run python tools/ui_copy_check.py` (also enforced by tools/tests/test_ui_copy_check.py in `make test`).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = [
    ("apps/web/app", "*.tsx"),
    ("apps/web/components", "*.tsx"),
    ("apps/glasses-webapp", "*.tsx"),
    ("apps/apple", "*.swift"),
]
EXEMPT_PARTS = {"tune", "eval", "health", "debug", "node_modules", "out", ".next", "tests", "Tests", "Preview Content"}
BANNED = re.compile(
    r"config/|\.toml\b|never generated|\bobs\.[a-z_]+|\bcmd\.[a-z_]+|\bVERIFY\b|\bTODO\b|\bFIXME\b|lorem ipsum|"
    r"workstream|kaiku_contracts|\bmake [a-z-]+\b|\bbandit\b|\bpayload\b|\bendpoint\b",
    re.IGNORECASE,
)
_COMMENTS = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_URL = re.compile(r"https?://\S+")
# Only text a person can see: JSX text nodes, visible attributes, SwiftUI view strings.
_VISIBLE = [
    re.compile(r">([^<>{}]+)<"),  # JSX text between tags (same line)
    re.compile(r"\b(?:title|aria-label|placeholder|alt|label)=\{?[\"'`]([^\"'`]+)[\"'`]"),
    re.compile(r"\{`([^`]+)`\}"),  # JSX template literal children
    re.compile(r"\b(?:Text|Label|Button|navigationTitle|Toggle|Section|alert|confirmationDialog|"
               r"LocalizedStringKey|String\(localized:)\(\s*\"([^\"]+)\""),
]


def _strip(src: str) -> str:
    src = _URL.sub("", src)  # keep '//' inside URLs from looking like comments
    return _COMMENTS.sub(lambda m: "\n" * m.group(0).count("\n"), src)


def scan(root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    for rel, pattern in SCAN:
        base = root / rel
        if not base.exists():
            continue
        for f in sorted(base.rglob(pattern)):
            if EXEMPT_PARTS & set(f.relative_to(base).parts):
                continue
            for n, line in enumerate(_strip(f.read_text(encoding="utf-8")).splitlines(), 1):
                for rx in _VISIBLE:
                    for v in rx.finditer(line):
                        for m in BANNED.finditer(v.group(1)):
                            problems.append(f"{f.relative_to(root)}:{n}: build note in UI copy: {m.group(0)!r}")
    return problems


if __name__ == "__main__":
    found = scan()
    print("\n".join(found) or "ui copy clean")
    sys.exit(1 if found else 0)
