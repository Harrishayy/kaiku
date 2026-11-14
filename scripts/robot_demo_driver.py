"""Scripted sim person for `scripts/record_robot_demo.sh` (dev harness; imports the sim twins).

Story: a person walks up to the robot -> the hub greets and offers the ritual -> the head twin answers the three dial
questions with button presses, drums (warming up), the sensors twin breathes slowly -> suggestion -> goodbye -> the
person leaves. Then the other sources land in the cloud: a glasses walk, a laptop session + Mac hour, a phone morning.

Writes one JSON line per story marker to --markers (wall-clock `ts` in UTC ms) so the replay page can label moments.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kaiku_contracts.bus import Bus  # noqa: E402

from sim.nodes.glasses_sim import GlassesSim  # noqa: E402
from sim.nodes.head_sim import HeadSim  # noqa: E402
from sim.nodes.laptop_sim import LaptopSim  # noqa: E402
from sim.nodes.phone_sim import PhoneSim  # noqa: E402
from sim.nodes.sensors_sim import SensorsSim  # noqa: E402


class Markers:
    def __init__(self, path: Path):
        self.f = path.open("w")

    def __call__(self, key: str, label: str, **extra) -> None:
        ts = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        self.f.write(json.dumps({"ts": ts, "key": key, "label": label, **extra}) + "\n")
        self.f.flush()
        print(f"# marker {key}: {label}", flush=True)


async def amain(a: argparse.Namespace) -> None:
    mark = Markers(Path(a.markers))
    stop = asyncio.Event()
    done = asyncio.Event()
    head = HeadSim(auto=True, tempo_bpm=a.tempo, mood=3, dial="button", seed=7)
    sensors = SensorsSim(arrive_after_s=None, dwell_s=10_000, seed=7)
    glasses, laptop, phone = GlassesSim(seed=7), LaptopSim(seed=7), PhoneSim(seed=7)
    labels = {("greet", "started"): ("greeting", "Greeting"), ("dial", "started"): ("dial", "Dial: 3 questions"),
              ("breathe", "started"): ("breathe", "Breathing"), ("drum", "started"): ("drum", "Drumming"),
              ("nudge", "started"): ("suggestion", "Suggestion"), ("close", "started"): ("goodbye", "Goodbye")}

    async def on_ritual(_t, env) -> None:
        p = env.payload
        if (p.step, p.status) in labels:
            mark(*labels[(p.step, p.status)])
        if p.step == "close" and p.status in ("completed", "skipped", "aborted"):
            done.set()

    watch = Bus("sim", heartbeat=False, sim=True)
    watch.on("obs/ritual", on_ritual)
    async with watch:
        tasks = [asyncio.create_task(n.run(stop)) for n in (head, sensors)]
        await asyncio.sleep(a.lead_s)
        mark("approach", "Person walks up")
        sensors.arrive()
        try:
            await asyncio.wait_for(done.wait(), a.max_ritual_s)
        except TimeoutError:
            mark("timeout", "Ritual did not close in time")
        await asyncio.sleep(2)
        mark("leave", "Person walks away")
        sensors.leave()
        await asyncio.sleep(8)
        mark("glasses", "Glasses: walk done", ok=await glasses.walk_done())
        await asyncio.sleep(2)
        mark("laptop", "Laptop: session", ok=await laptop.session())
        await asyncio.sleep(1)
        mark("mac", "Mac: an hour of screen time + firefly", ok=await laptop.mac_hour())
        await asyncio.sleep(1)
        mark("phone", "Phone: morning check", ok=await phone.morning())
        await asyncio.sleep(3)
        mark("end", "End")
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--markers", required=True)
    ap.add_argument("--tempo", type=float, default=92.0)
    ap.add_argument("--lead-s", type=float, default=4.0)
    ap.add_argument("--max-ritual-s", type=float, default=300.0)
    asyncio.run(amain(ap.parse_args()))
    time.sleep(0.1)


if __name__ == "__main__":
    main()
