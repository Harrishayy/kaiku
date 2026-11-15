"""Atech head adapter (KAIKU_HEAD=atech): a stub that does nothing, kept so the switch has a place to land.

It was planned for a head that could not run an MQTT client (D6). The Atech head does speak MQTT (D44: both its
firmwares publish the contract topics themselves), so nothing here is needed and nothing is implemented:
`KAIKU_HEAD=atech` only logs one line at start. A head with a vendor-only API would get its translation here
(native API -> raw.head.* and health/head; cmd/head -> vendor calls).
"""

from __future__ import annotations

from kaiku_contracts.jlog import get_logger

log = get_logger("hub")


class AtechAdapter:
    async def start(self) -> None:
        log.info("atech_adapter_stub", "KAIKU_HEAD=atech selects a stub: the head speaks MQTT itself (D44), nothing to adapt")

    async def stop(self) -> None:
        return None
