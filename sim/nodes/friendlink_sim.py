"""Sim twin of the LoRa friend link (gateway + friend's lamp).

Real hardware: the hub's devices/lora_serial.py adapter emits obs/friend_link. In sim mode this node
plays both the gateway and the lamp: on cmd/friendlink ping it "glows" the lamp and emits the ack.
"""

from __future__ import annotations

import argparse
import asyncio
import random

from kaiku_contracts.bus import Bus
from kaiku_contracts.config import load_dotenv


class FriendlinkSim:
    def __init__(self, *, ack_prob: float = 1.0, latency_s: float = 1.0, seed: int | None = None):
        self.ack_prob = ack_prob
        self.latency_s = latency_s
        self.rng = random.Random(seed)
        self.bus = Bus("friendlink", sim=True, details=lambda: {"sim": True})
        self.bus.on("cmd/friendlink", self._on_cmd)

    async def _on_cmd(self, _t, env) -> None:
        if env.payload.ping is None:
            return
        await asyncio.sleep(self.latency_s)
        self.bus.log.info("lamp_glow", f"friend's lamp glows ({env.payload.ping.pattern})")
        await self.bus.publish("obs.friend_link", {"direction": "sent", "ack": self.rng.random() < self.ack_prob})

    async def friend_presses_button(self) -> None:
        await self.bus.publish("obs.friend_link", {"direction": "received", "ack": True})

    async def run(self, stop: asyncio.Event | None = None) -> None:
        async with self.bus:
            await (stop.wait() if stop else asyncio.Event().wait())


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ack-prob", type=float, default=1.0)
    a = ap.parse_args()
    asyncio.run(FriendlinkSim(ack_prob=a.ack_prob).run())


if __name__ == "__main__":
    main()
