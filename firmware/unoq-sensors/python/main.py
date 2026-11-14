"""App Lab entry point for the UNO Q Linux side (see ../AGENTS.md).

On the board:  App Lab runs this file; `make unoq-app` first copies kaiku_contracts + config into ./vendor.
On a laptop:   uv run python firmware/unoq-sensors/python/main.py --fake-bridge [--no-camera]
               (laptop webcam stands in for the USB camera; keys: r = sketch ready, q = quit)
Env: MQTT_HOST / MQTT_PORT / MQTT_USER / MQTT_PASS (broker on the hub laptop today), KAIKU_HOME_ID.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (HERE, HERE / "vendor"):  # vendor/ = copied kaiku_contracts + config (gitignored)
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

from kaiku_contracts.config import load_dotenv  # noqa: E402
from kaiku_unoq.bridge import FakeBridge, RouterBridge  # noqa: E402
from kaiku_unoq.node import SensorsNode  # noqa: E402


def _keyboard(bridge: FakeBridge, stop: asyncio.Event, loop: asyncio.AbstractEventLoop) -> None:
    for line in sys.stdin:
        ch = line.strip()[:1]
        if ch == "r":
            bridge.ready()
        elif ch == "q":
            loop.call_soon_threadsafe(stop.set)
            return


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fake-bridge", action="store_true", help="no STM32: log Bridge calls, sketch-ready from the keyboard")
    ap.add_argument("--no-camera", action="store_true")
    a = ap.parse_args()

    if a.fake_bridge:
        bridge = FakeBridge()

        async def run() -> None:
            stop = asyncio.Event()
            threading.Thread(target=_keyboard, args=(bridge, stop, asyncio.get_running_loop()), daemon=True).start()
            await SensorsNode(bridge, camera=not a.no_camera).run(stop)

        asyncio.run(run())
        return

    # On the board: App Lab owns the main thread (App.run); our asyncio node runs beside it.
    from arduino.app_utils import App  # type: ignore[import-not-found]

    node = SensorsNode(RouterBridge(), camera=not a.no_camera)
    threading.Thread(target=lambda: asyncio.run(node.run()), name="kaiku-node", daemon=True).start()
    App.run(user_loop=lambda: time.sleep(1))  # VERIFY: App.run signature on the current App Lab release


if __name__ == "__main__":
    main()
