"""Record bus traffic to JSONL for debugging and test fixtures.

    python tools/record.py ['kaiku/v1/#'] [-o logs/session.jsonl] [--seconds 60]
Each line: {"t": seconds since start, "topic": ..., "msg": <decoded JSON>}
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiomqtt  # noqa: E402

from tools.busio import decode, mqtt_kwargs  # noqa: E402


async def record(topic: str, out: Path, seconds: float | None, include_retained: bool = False) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    t0 = time.monotonic()
    async with aiomqtt.Client(**mqtt_kwargs()) as client:
        await client.subscribe(topic)
        print(f"# recording {topic} -> {out}  (Ctrl-C to stop)", file=sys.stderr)
        with out.open("a") as f:
            async def loop() -> None:
                nonlocal n
                async for m in client.messages:
                    if m.retain and not include_retained:
                        continue
                    f.write(json.dumps({"t": round(time.monotonic() - t0, 4), "topic": str(m.topic),
                                        "msg": decode(m.payload)}) + "\n")
                    f.flush()
                    n += 1
            try:
                await asyncio.wait_for(loop(), timeout=seconds)
            except TimeoutError:
                pass
    print(f"# wrote {n} messages", file=sys.stderr)
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topic", nargs="?", default="kaiku/v1/#")
    ap.add_argument("-o", "--out", type=Path,
                    default=Path("logs") / f"rec-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl")
    ap.add_argument("--seconds", type=float)
    ap.add_argument("--retained", action="store_true", help="also record retained messages present at start")
    a = ap.parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(record(a.topic, a.out, a.seconds, a.retained))


if __name__ == "__main__":
    main()
