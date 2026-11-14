"""Bridge adapter: the UNO Q RPC router between this Linux app and the STM32 sketch.

RouterBridge wraps `arduino.app_utils.Bridge` (only importable on the board, inside App Lab).
FakeBridge stands in on a laptop (`--fake-bridge`): calls are logged, and `ppg()`/`hall()`/`ready()` simulate the sketch.

Sketch provides (we call):  buzz_pattern(name) · ppg_start() · ppg_stop() · light_read() -> int ·
                            status_set(name) · ping() -> fw version
Sketch notifies (we provide): on_ppg(t0_ms, fs_hz, "csv samples") · on_hall(at_home, t_ms) ·
                              mcu_ready()
VERIFY on the board: argument types the router accepts (ints/strings are safe) and whether `provide` callbacks
run on a router thread (we assume yes and hop onto the asyncio loop).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class BridgeLike(Protocol):
    def call(self, name: str, *args: Any) -> Any: ...
    def notify(self, name: str, *args: Any) -> None: ...
    def provide(self, name: str, fn: Callable[..., Any]) -> None: ...


class RouterBridge:
    def __init__(self) -> None:
        from arduino.app_utils import Bridge  # type: ignore[import-not-found]  # App Lab only

        self._b = Bridge

    def call(self, name: str, *args: Any) -> Any:
        return self._b.call(name, *args)

    def notify(self, name: str, *args: Any) -> None:
        self._b.notify(name, *args)

    def provide(self, name: str, fn: Callable[..., Any]) -> None:
        self._b.provide(name, fn)


class FakeBridge:
    """Laptop stand-in. `calls` records every call (tests read it)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.provided: dict[str, Callable[..., Any]] = {}
        self.light = 1200  # what light_read returns

    def call(self, name: str, *args: Any) -> Any:
        self.calls.append((name, args))
        if name == "ping":
            return "fake-0.2.0"
        if name == "light_read":
            return self.light
        return None

    def notify(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))

    def provide(self, name: str, fn: Callable[..., Any]) -> None:
        self.provided[name] = fn

    def ppg(self, t0_ms: int, samples: list[int], fs_hz: int = 100) -> None:
        self.provided["on_ppg"](t0_ms, fs_hz, ",".join(str(x) for x in samples))

    def hall(self, at_home: bool, t_ms: int = 0) -> None:
        self.provided["on_hall"](int(at_home), t_ms)

    def ready(self) -> None:
        self.provided["mcu_ready"]()
