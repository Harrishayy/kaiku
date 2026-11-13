"""The hub uses the shared bus client from contracts (validates, reconnects, heartbeats)."""

from kaiku_contracts.bus import Bus, Handler

__all__ = ["Bus", "Handler"]
