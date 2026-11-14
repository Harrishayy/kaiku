"""Electronics bench tests: prove each part works on its own before it is integrated.

Every part has a folder `firmware/<module>/bench/<part>/` with
  - one tiny program that exercises only that part and prints one JSON object per line
    (`{"event": "...", ...}`), and
  - `bench.toml`: how to flash it, what the person does, and the checks on those lines.

    make bench-list
    make bench PART=firmware/unoq-sensors/bench/knock FROM=serial:/dev/tty.usbmodem1101
    make bench PART=firmware/unoq-sensors/bench/knock FROM=-          # pipe: `atech monitor | make bench ...`
    make bench PART=firmware/unoq-sensors/bench/knock FROM=run.log    # a saved monitor log
    make bench PART=firmware/atech-head/bench/link   FROM=mqtt        # whole firmware over the broker

bench.toml:
    part = "knock"            board = "unoq-mcu" | "unoq-linux" | "atech" | "mqtt"
    program = "knock.ino"     flash = "how to load it"      steps = ["what the person does", ...]
    duration_s = 20           # stop listening after this (or when every check passed)
    topic = "kaiku/v1/+/raw/head/#"   send = [{type = "cmd.head", payload = {...}}]    # board = "mqtt" only
    [[check]]  name = "..."  event = "knock"  min_count = 5  max_count = 5
    [[check]]  name = "..."  event = "batch"  field = "fs_hz"  all_min = 95  all_max = 105   # every value in range
    [[check]]  name = "..."  event = "level"  field = "rms"  any_min = 2000                   # some value reaches it
    [[check]]  name = "..."  ask = "Did you hear three rising notes?"                        # the person answers y/n
    [[check]]  ... source = "head"                                                            # mqtt: only that node
Over MQTT, each envelope becomes a line {"event": <type>, "source": ..., **payload}.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tomllib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARDS = ("unoq-mcu", "unoq-linux", "atech", "mqtt")


@dataclass
class Check:
    name: str
    event: str | None = None
    source: str | None = None  # mqtt lines: only envelopes from this node (e.g. "head")
    field: str | None = None
    min_count: int | None = None
    max_count: int | None = None
    all_min: float | None = None
    all_max: float | None = None
    any_min: float | None = None
    ask: str | None = None

    def evaluate(self, lines: list[dict], answer: Callable[[str], bool]) -> tuple[bool, str]:
        if self.ask:
            ok = answer(self.ask)
            return ok, "yes" if ok else "no"
        hits = [ln for ln in lines if (self.event is None or ln.get("event") == self.event)
                and (self.source is None or ln.get("source") == self.source)]
        n = len(hits)
        if self.min_count is not None and n < self.min_count:
            return False, f"{n} '{self.event}' lines, need >= {self.min_count}"
        if self.max_count is not None and n > self.max_count:
            return False, f"{n} '{self.event}' lines, need <= {self.max_count}"
        if self.field:
            vals = [float(v) for ln in hits if isinstance(v := ln.get(self.field), (int, float))]
            if not vals:
                return False, f"no '{self.event}' line with a numeric '{self.field}'"
            lo, hi = min(vals), max(vals)
            if self.all_min is not None and lo < self.all_min:
                return False, f"{self.field} min {lo:g} < {self.all_min:g}"
            if self.all_max is not None and hi > self.all_max:
                return False, f"{self.field} max {hi:g} > {self.all_max:g}"
            if self.any_min is not None and hi < self.any_min:
                return False, f"{self.field} never reached {self.any_min:g} (max {hi:g})"
            return True, f"{self.field} {lo:g}..{hi:g} over {len(vals)} lines"
        return True, f"{n} '{self.event}' lines"

    @property
    def needs_data(self) -> bool:
        return self.ask is None


@dataclass
class Part:
    path: Path
    part: str
    board: str
    program: str
    flash: str
    steps: list[str]
    duration_s: float = 20
    topic: str | None = None
    send: list[dict] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)

    @classmethod
    def load(cls, folder: Path) -> Part:
        d = tomllib.loads((folder / "bench.toml").read_text())
        checks = [Check(**c) for c in d.pop("check", [])]
        part = cls(path=folder, checks=checks, **d)
        if part.board not in BOARDS:
            raise ValueError(f"{folder}: board must be one of {BOARDS}")
        if not part.checks:
            raise ValueError(f"{folder}: no [[check]]")
        if part.board != "mqtt" and not (folder / part.program).exists():
            raise ValueError(f"{folder}: program {part.program} missing")
        return part


def discover(root: Path = ROOT) -> list[Part]:
    return [Part.load(p.parent) for p in sorted(root.glob("firmware/*/bench/*/bench.toml"))]


def parse_lines(raw: Iterable[str]) -> Iterator[dict]:
    """JSON objects only; monitor noise (boot banners, Atech events) is skipped."""
    for line in raw:
        line = line.strip()
        i = line.find("{")
        if i < 0:
            continue
        try:
            obj = json.loads(line[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "event" in obj:
            yield obj


def evaluate(part: Part, lines: list[dict], answer: Callable[[str], bool]) -> list[tuple[Check, bool, str]]:
    return [(c, *c.evaluate(lines, answer)) for c in part.checks]


def data_checks_pass(part: Part, lines: list[dict]) -> bool:
    return all(c.evaluate(lines, lambda _q: True)[0] for c in part.checks if c.needs_data)


# ---------------------------------------------------------------- sources
def _serial_lines(port: str, baud: int = 115200) -> Iterator[str]:
    try:
        import serial  # pyserial
    except ImportError:
        sys.exit("pyserial missing: `uv run --with pyserial make ...` or pipe a monitor with FROM=-")
    with serial.Serial(port, baud, timeout=0.5) as s:
        while True:
            b = s.readline()
            yield b.decode(errors="replace") if b else ""


def _mqtt_lines(part: Part) -> Iterator[str]:
    import asyncio
    import queue
    import threading

    from kaiku_contracts.bus import Bus

    q: queue.Queue[str] = queue.Queue()

    async def main() -> None:
        bus = Bus("sim", heartbeat=False)

        async def on(_t, env) -> None:  # noqa: ANN001
            q.put(json.dumps({"event": env.type, "source": env.source, **env.payload.model_dump(mode="json")}))

        bus.on(part.topic or "kaiku/v1/#", on)
        async with bus:
            await bus.connected.wait()
            await asyncio.sleep(0.5)
            for msg in part.send:
                await bus.publish(msg["type"], msg["payload"])
                await asyncio.sleep(float(msg.get("wait_s", 0.5)))
            await asyncio.sleep(part.duration_s)

    threading.Thread(target=lambda: asyncio.run(main()), daemon=True).start()
    while True:
        try:
            yield q.get(timeout=0.5)
        except queue.Empty:
            yield ""


def source_lines(spec: str, part: Part) -> Iterable[str]:
    if spec == "-":
        return sys.stdin
    if spec.startswith("serial:"):
        return _serial_lines(spec.split(":", 1)[1])
    if spec == "mqtt":
        return _mqtt_lines(part)
    return Path(spec).read_text().splitlines()


def collect(raw: Iterable[str], part: Part, live: bool) -> list[dict]:
    lines: list[dict] = []
    end = time.monotonic() + part.duration_s
    for obj in parse_lines(raw if not live else _until(raw, end)):
        lines.append(obj)
        print("  ", json.dumps(obj), file=sys.stderr)
        if live and data_checks_pass(part, lines) and not any(c.max_count for c in part.checks):
            break
    return lines


def _until(raw: Iterable[str], end: float) -> Iterator[str]:
    for line in raw:
        if time.monotonic() > end:
            return
        yield line


def _ask_tty(q: str) -> bool:
    try:
        with open("/dev/tty") as tty:
            print(f"  ? {q} [y/n] ", end="", flush=True, file=sys.stderr)
            return tty.readline().strip().lower().startswith("y")
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("part", nargs="?", help="part folder, e.g. firmware/unoq-sensors/bench/knock")
    ap.add_argument("--from", dest="src", default=None, help="serial:<port> | - | mqtt | <log file>")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--yes", action="store_true", help="answer yes to every ask (dry runs only)")
    a = ap.parse_args(argv)
    if a.list or not a.part:
        for p in discover():
            print(f"{p.path.relative_to(ROOT)!s:46} {p.board:10} {len(p.checks)} checks  {p.steps[0] if p.steps else ''}")
        return 0
    part = Part.load((ROOT / a.part) if not Path(a.part).is_absolute() else Path(a.part))
    print(f"\n== bench: {part.part} ({part.board})\n  load: {part.flash}", file=sys.stderr)
    for i, s in enumerate(part.steps, 1):
        print(f"  {i}. {s}", file=sys.stderr)
    src = a.src or ("mqtt" if part.board == "mqtt" else "-")
    live = not Path(src).is_file()
    lines = collect(source_lines(src, part), part, live)
    results = evaluate(part, lines, (lambda _q: True) if a.yes else _ask_tty)
    for c, ok, why in results:
        print(f"  {'✅' if ok else '❌'} {c.name}: {why}", file=sys.stderr)
    passed = all(ok for _, ok, _ in results)
    print(f"== {part.part}: {'PASS' if passed else 'FAIL'}", file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
