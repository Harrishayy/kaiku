"""Friend-link LoRa gateway over USB serial (firmware/friendlink/gateway). Optional dep: pyserial.

Line protocol (115200 baud, '\\n'-terminated):
  hub -> gateway:  PING <pattern>        (from cmd/friendlink {ping:{pattern}})
  gateway -> hub:  ACK                   (friend's lamp acknowledged) -> obs.friend_link sent ack=true
                   PING <pattern>        (friend pressed their button) -> obs.friend_link received
Port from KAIKU_LORA_PORT (e.g. /dev/tty.usbserial-0001). Disabled if unset.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Awaitable, Callable

from kaiku_contracts.jlog import get_logger

log = get_logger("hub")

try:
    import serial  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    serial = None

ACK_TIMEOUT_S = 5.0


class LoraSerialAdapter:
    def __init__(self, emit: Callable[[str, dict], Awaitable[object]], port: str | None = None, baud: int = 115200):
        self.emit = emit
        self.port = port or os.environ.get("KAIKU_LORA_PORT")
        self.baud = baud
        self._ser = None
        self._ack = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def enabled(self) -> bool:
        return self._ser is not None

    async def start(self) -> None:
        if not self.port:
            return
        if serial is None:
            log.warning("lora_disabled", "pyserial not installed (uv sync --extra lora)")
            return
        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=1)
        except Exception as e:
            log.warning("lora_open_failed", str(e), port=self.port)
            return
        self._loop = asyncio.get_running_loop()
        threading.Thread(target=self._reader, daemon=True, name="lora").start()

    def _reader(self) -> None:  # pragma: no cover - hardware
        while self._ser is not None:
            try:
                line = self._ser.readline().decode(errors="ignore").strip()
            except Exception as e:
                log.warning("lora_read_failed", str(e))
                return
            if line and self._loop:
                self._loop.call_soon_threadsafe(self.on_line, line)

    def on_line(self, line: str) -> None:
        if line == "ACK":
            self._ack.set()
        elif line.startswith("PING") and self._loop:
            self._loop.create_task(self.emit("obs.friend_link", {"direction": "received", "ack": True}))

    async def ping(self, pattern: str = "glow") -> None:
        if self._ser is None:
            log.info("friendlink_offline", "no LoRa gateway; ping not sent")
            await self.emit("obs.friend_link", {"direction": "sent", "ack": False})
            return
        self._ack.clear()
        self._ser.write(f"PING {pattern}\n".encode())
        try:
            await asyncio.wait_for(self._ack.wait(), ACK_TIMEOUT_S)
            ack = True
        except TimeoutError:
            ack = False
        await self.emit("obs.friend_link", {"direction": "sent", "ack": ack})

    async def stop(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            ser.close()
