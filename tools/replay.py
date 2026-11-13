"""Replay a recording into the bus (debugging, demos, reproducing bugs against one module).

    python tools/replay.py logs/rec.jsonl [--speed 2] [--only 'raw/head'] [--home demo-aino] [--keep-ids] [--loop]

By default each message gets a fresh id + ts (so the cloud doesn't dedupe it) and is re-validated.
Invalid lines are skipped with a warning. Use --verbatim to publish bytes exactly as recorded.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiomqtt  # noqa: E402
from kaiku_contracts import ContractError, qos_for, to_json, topic_for, utcnow, uuid7, validate  # noqa: E402

from tools.busio import mqtt_kwargs  # noqa: E402


def load(path: Path, only: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            print(f"# line {i}: not JSON, skipped", file=sys.stderr)
            continue
        if only and only not in row.get("topic", ""):
            continue
        rows.append(row)
    return rows


def prepare(row: dict[str, Any], *, keep_ids: bool, home: str | None) -> tuple[str, str, int] | None:
    msg = row["msg"]
    if not isinstance(msg, dict):
        return None
    msg = dict(msg)
    if not keep_ids:
        msg["id"], msg["ts"] = str(uuid7()), utcnow().isoformat()
    if home:
        msg["home_id"] = home
    try:
        env = validate(msg)
    except ContractError as e:
        print(f"# skipped invalid message on {row.get('topic')}: {str(e).splitlines()[0]}", file=sys.stderr)
        return None
    return topic_for(env), to_json(env), qos_for(env)


async def replay(path: Path, speed: float, only: str | None, keep_ids: bool, home: str | None,
                 verbatim: bool, loop: bool) -> int:
    rows = load(path, only)
    if not rows:
        print("# nothing to replay", file=sys.stderr)
        return 0
    sent = 0
    async with aiomqtt.Client(**mqtt_kwargs()) as client:
        while True:
            start, t_first = time.monotonic(), rows[0].get("t", 0.0)
            for row in rows:
                delay = (row.get("t", 0.0) - t_first) / max(speed, 1e-6) - (time.monotonic() - start)
                if delay > 0:
                    await asyncio.sleep(delay)
                if verbatim:
                    await client.publish(row["topic"], json.dumps(row["msg"]))
                else:
                    prepared = prepare(row, keep_ids=keep_ids, home=home)
                    if prepared is None:
                        continue
                    topic, body, qos = prepared
                    await client.publish(topic, body, qos=qos)
                sent += 1
            if not loop:
                break
    print(f"# replayed {sent} messages", file=sys.stderr)
    return sent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--only", help="substring filter on topic, e.g. raw/head")
    ap.add_argument("--home", help="rewrite home_id")
    ap.add_argument("--keep-ids", action="store_true")
    ap.add_argument("--verbatim", action="store_true")
    ap.add_argument("--loop", action="store_true")
    a = ap.parse_args()
    if not a.file.exists():
        raise SystemExit(f"no such recording: {a.file} (make record first; recordings live in logs/)")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(replay(a.file, a.speed, a.only, a.keep_ids, a.home, a.verbatim, a.loop))


if __name__ == "__main__":
    main()
