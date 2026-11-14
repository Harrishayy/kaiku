"""Run sim twins together: python -m sim.run --nodes head,sensors,friendlink,glasses,laptop,phone [--keyboard]

head/sensors/friendlink talk MQTT (like the robot hardware); glasses/laptop/phone POST to the cloud (like the apps).

Keyboard (with --keyboard):  t tap · [ / ] ear down/up · e press ear · b press head button · p person arrives/leaves
                             s start ritual · x long-press top button (manual safety trigger)
                             f friend presses lamp button · w glasses walk done · l laptop session
                             9 laptop PHQ-9 · m Mac hour (screen activity + firefly)
                             o phone morning (watch summary + weather check)
                             2 toggle a second person (camera sees two faces) · q quit
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys

from kaiku_contracts.bus import Bus
from kaiku_contracts.config import load_dotenv

from sim.nodes.friendlink_sim import FriendlinkSim
from sim.nodes.glasses_sim import GlassesSim
from sim.nodes.head_sim import HeadSim
from sim.nodes.laptop_sim import LaptopSim
from sim.nodes.phone_sim import PhoneSim
from sim.nodes.sensors_sim import SensorsSim

HELP = __doc__.split("\n\n", 1)[1]


@contextlib.contextmanager
def _cbreak():
    if not sys.stdin.isatty():
        yield
        return
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


async def _keyboard(nodes: dict, stop: asyncio.Event) -> None:
    head: HeadSim | None = nodes.get("head")
    sensors: SensorsSim | None = nodes.get("sensors")
    friend: FriendlinkSim | None = nodes.get("friendlink")
    glasses: GlassesSim | None = nodes.get("glasses")
    laptop: LaptopSim | None = nodes.get("laptop")
    phone: PhoneSim | None = nodes.get("phone")
    loop = asyncio.get_running_loop()
    print(HELP, file=sys.stderr)
    async with Bus("sim", heartbeat=False, sim=True) as ctl:
        with _cbreak():
            while not stop.is_set():
                ch = await loop.run_in_executor(None, sys.stdin.read, 1)
                if not ch or ch == "q":
                    stop.set()
                elif ch == "t" and head:
                    await head.tap()
                elif ch in "[]" and head:
                    await head.turn_ear(-1 if ch == "[" else 1)
                elif ch == "e" and head:
                    await head.press_ear()
                elif ch == "b" and head:
                    await head.press_button()
                elif ch == "p" and sensors:
                    sensors.leave() if sensors.is_near else sensors.arrive()
                    print(f"presence: {'near' if sensors.is_near else 'leaving'}", file=sys.stderr)
                elif ch == "2" and sensors:
                    print(f"people in view: {sensors.toggle_second_person()}", file=sys.stderr)
                elif ch == "x" and sensors:
                    await sensors.button(hold_s=2.5)
                elif ch == "f" and friend:
                    await friend.friend_presses_button()
                elif ch == "w" and glasses:
                    await glasses.walk_done()
                elif ch == "l" and laptop:
                    await laptop.session()
                elif ch == "9" and laptop:
                    await laptop.phq9()
                elif ch == "m" and laptop:
                    await laptop.mac_hour()
                elif ch == "o" and phone:
                    await phone.morning()
                elif ch == "s":
                    await ctl.publish("cmd.hub", {"start_ritual": True}, source="sim")


async def amain(names: list[str], keyboard: bool, args: argparse.Namespace) -> None:
    stop = asyncio.Event()
    nodes: dict = {}
    if "head" in names:
        nodes["head"] = HeadSim(auto=not keyboard, tempo_bpm=args.tempo, mood=args.mood)
    if "sensors" in names:
        nodes["sensors"] = SensorsSim(arrive_after_s=None if keyboard or args.arrive_after < 0 else args.arrive_after)
        nodes["sensors"].people = 2 if args.two else 1
    if "friendlink" in names:
        nodes["friendlink"] = FriendlinkSim()
    if "glasses" in names:
        nodes["glasses"] = GlassesSim(every_s=args.every)
    if "laptop" in names:
        nodes["laptop"] = LaptopSim(every_s=args.every)
    if "phone" in names:
        nodes["phone"] = PhoneSim(every_s=args.every)
    unknown = set(names) - set(nodes)
    if unknown:
        raise SystemExit(f"unknown sim nodes: {', '.join(sorted(unknown))} "
                         "(have head, sensors, friendlink, glasses, laptop, phone)")
    tasks = []
    for name, n in nodes.items():
        if keyboard and name in ("glasses", "laptop", "phone"):
            continue  # keyboard mode: these post only on w / l / 9 / m / o
        if name == "laptop":
            tasks.append(asyncio.create_task(n.run(stop, phq9=args.phq9, item9=args.phq9_item9)))
        else:
            tasks.append(asyncio.create_task(n.run(stop)))
    if keyboard:
        tasks.append(asyncio.create_task(_keyboard(nodes, stop)))
    try:
        await stop.wait()
    finally:
        await asyncio.gather(*tasks, return_exceptions=True)


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nodes", default="head,sensors,glasses,laptop,phone",
                    help="comma list: head,sensors,friendlink,glasses,laptop,phone")
    ap.add_argument("--keyboard", action="store_true", help="drive the sims by hand instead of auto mode")
    ap.add_argument("--tempo", type=float, default=96.0, help="auto drum tempo")
    ap.add_argument("--mood", type=int, choices=range(1, 6), help="auto mood dial value")
    ap.add_argument("--arrive-after", type=float, default=3.0, help="auto presence after N s (-1 never)")
    ap.add_argument("--two", action="store_true", help="sensors: two people walk up (camera sees two faces)")
    ap.add_argument("--every", type=float, default=300.0, help="glasses/laptop/phone: seconds between posts (auto)")
    ap.add_argument("--phq9", action="store_true", help="laptop: also send a PHQ-9 at start")
    ap.add_argument("--phq9-item9", action="store_true", help="laptop: PHQ-9 with item 9 > 0 (+ safety_flag)")
    args = ap.parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(amain([n.strip() for n in args.nodes.split(",") if n.strip()], args.keyboard, args))


if __name__ == "__main__":
    main()
