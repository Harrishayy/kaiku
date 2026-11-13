"""Pretty-print live bus traffic. Invalid messages are shown in red with the contract error.

    python tools/bus_tail.py 'kaiku/v1/+/obs/#'      [--no-raw] [--json]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiomqtt  # noqa: E402
from kaiku_contracts import ContractError, validate  # noqa: E402

from tools.busio import decode, mqtt_kwargs  # noqa: E402

COLORS = {"raw": "\033[90m", "obs": "\033[32m", "cmd": "\033[36m", "health": "\033[35m", "log": "\033[33m"}
RED, RESET, BOLD = "\033[31m", "\033[0m", "\033[1m"


def fmt(topic: str, payload: bytes, color: bool = True) -> str:
    now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    parts = topic.split("/")
    kind = parts[3] if len(parts) > 3 else "?"
    short = "/".join(parts[2:])
    c = (lambda code, s: f"{code}{s}{RESET}") if color else (lambda code, s: s)
    try:
        env = validate(payload)
    except ContractError as e:
        return f"{now} {c(RED, short)} {c(RED, 'INVALID')} {str(e).splitlines()[0][:160]} :: {str(decode(payload))[:200]}"
    body = json.dumps(env.payload.model_dump(mode="json", exclude_none=True), separators=(",", ":"))
    if len(body) > 160:
        body = body[:157] + "..."
    tags = (c(BOLD, " SIM") if env.sim else "") + (f" q={env.quality:.2f}" if env.quality is not None else "")
    return f"{now} {c(COLORS.get(kind, ''), short):<48} {env.source:<10}{tags} {body}"


async def tail(topic: str, show_raw: bool, as_json: bool) -> None:
    color = sys.stdout.isatty()
    while True:
        try:
            async with aiomqtt.Client(**mqtt_kwargs()) as client:
                await client.subscribe(topic)
                print(f"# tailing {topic}", file=sys.stderr)
                async for m in client.messages:
                    t = str(m.topic)
                    if not show_raw and "/raw/" in t:
                        continue
                    if as_json:
                        print(json.dumps({"topic": t, "msg": decode(m.payload)}), flush=True)
                    else:
                        print(fmt(t, m.payload, color), flush=True)
        except aiomqtt.MqttError as e:
            print(f"# broker unavailable ({e}); retrying in 2 s — is `make broker` running?", file=sys.stderr)
            await asyncio.sleep(2)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topic", nargs="?", default="kaiku/v1/#")
    ap.add_argument("--no-raw", action="store_true", help="hide high-rate raw/* streams")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(tail(a.topic, not a.no_raw, a.json))


if __name__ == "__main__":
    main()
