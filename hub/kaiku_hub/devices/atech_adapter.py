"""Atech head adapter (KAIKU_HEAD=atech) — only needed if Atech firmware can't run an MQTT client (D6).

TODO(A/B): after the Phase 0 Atech spike, implement:
  - read the head's native Wi-Fi/BLE/serial API -> publish raw.head.tap / raw.head.ear / raw.head.pan
  - subscribe cmd/head -> translate to Atech calls (eyes, pan, chest, purr)
  - publish health/head on the head's behalf (bus heartbeat does this when node="head")
If Atech CAN speak MQTT directly, this adapter is unused: the firmware publishes the same topics.
"""

from __future__ import annotations

from kaiku_contracts.jlog import get_logger

log = get_logger("hub")


class AtechAdapter:
    async def start(self) -> None:
        log.warning("atech_adapter_todo", "KAIKU_HEAD=atech but the adapter is not implemented yet (see docstring)")

    async def stop(self) -> None:
        return None
