"""Save Kaiku's voice for the silent simulator clips: the same audio the app plays, from a running Kaiku service.

    uv run python scripts/record_voice.py --url http://127.0.0.1:8000
    uv run python scripts/record_voice.py --url <service> --key welcome.hello --say "Thank you for telling me. I'm listening."

`simctl io recordVideo` records no sound, so the cut builder (`demo/draft_cut.py`) lays these files under the
moments where the app spoke. Fixed lines come from `GET /v1/voice/{key}` (config/voice_lines.toml), anything
else from `POST /v1/voice/say`; both are Kaiku's one Gemini TTS voice and both are cached by the service
(`logs/voice_cache/`), so a line that was rendered before costs nothing. A new line is one paid TTS call on the
service: when its budget cap refuses (503), this script says so and goes on. It never works around the cap:
raise it in `config/kaiku.toml [budget]`, restart the service, run the same command again.

Writes demo/recordings/voice/<key>.wav and say-<slug>.wav plus lines.txt (file, seconds, words).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
import wave
from pathlib import Path

# the lines the recorded flows play (first run, Talk, the walk) and the typed-path replies of Talk
DEFAULT_KEYS = ["welcome.hello", "welcome.done", "greet.morning", "greet.afternoon", "greet.evening",
                "walk.light_hunt.1", "walk.light_hunt.found", "walk.done"]
DEFAULT_SAY = ["Thank you for telling me. I'm listening.", "I'm here. Tell me more if you like."]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48]


def fetch(req: urllib.request.Request) -> tuple[bytes | None, str]:
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.read(), ""
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            reason = json.loads(body).get("reason") or json.loads(body).get("detail") or body
        except ValueError:
            reason = body
        return None, f"HTTP {e.code}: {str(reason)[:200]}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, str(e)


def seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="a running Kaiku service (local or deployed)")
    ap.add_argument("--out", default="demo/recordings/voice")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--key", action="append", default=[], help="a keyed line (repeatable); default: the recorded flows' lines")
    ap.add_argument("--say", action="append", default=[], help="any short line (repeatable); default: Talk's two typed-path replies")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    keys = a.key or ([] if a.say else DEFAULT_KEYS)
    says = a.say or ([] if a.key else DEFAULT_SAY)
    words: dict[str, str] = {}
    data, _ = fetch(urllib.request.Request(f"{base}/v1/voice?lang={a.lang}"))
    if data:
        words = json.loads(data).get("lines", {})
    rows, failed = [], 0
    jobs = [(f"{k}.wav", words.get(k, k), urllib.request.Request(f"{base}/v1/voice/{k}?lang={a.lang}")) for k in keys]
    jobs += [(f"say-{slug(t)}.wav", t, urllib.request.Request(
        f"{base}/v1/voice/say", data=json.dumps({"text": t, "lang": a.lang}).encode(),
        headers={"content-type": "application/json"}, method="POST")) for t in says]
    for name, text, req in jobs:
        data, why = fetch(req)
        if data is None:
            failed += 1
            print(f"NOT SAVED {name}: {why}")
            continue
        path = out / name
        path.write_bytes(data)
        rows.append(f"{name}\t{seconds(path):.2f}\t{text}")
        print(f"{path}  {seconds(path):.1f} s  {text}")
    listing = out / "lines.txt"
    old = {r.split("\t")[0]: r for r in listing.read_text().splitlines()} if listing.exists() else {}
    old.update({r.split("\t")[0]: r for r in rows})
    listing.write_text("\n".join(old[k] for k in sorted(old)) + "\n")
    if failed:
        print(f"{failed} line(s) not saved. If the reason is the budget cap: raise [budget] in config/kaiku.toml, "
              "restart the service, run this again. The clips stay silent where a line is missing.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
