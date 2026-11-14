"""Shared poster for the sources that talk HTTPS, not MQTT (glasses, laptop): POST /v1/events.

Fail soft: timeouts + bounded retries with backoff; a dead cloud is logged, never raised.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from kaiku_contracts import Envelope, make, to_json
from kaiku_contracts.envelope import Source
from kaiku_contracts.jlog import get_logger


class HttpSource:
    def __init__(self, source: Source, *, url: str | None = None, home_id: str | None = None,
                 token: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 timeout_s: float = 5.0, retries: int = 3):
        self.source = source
        self.url = (url or os.environ.get("KAIKU_CLOUD_URL") or "http://localhost:8000").rstrip("/")
        self.home_id = home_id or os.environ.get("KAIKU_HOME_ID", "demo-aino")
        self.token = token if token is not None else (os.environ.get("KAIKU_HOME_TOKEN") or None)
        self.transport = transport
        self.timeout_s = timeout_s
        self.retries = retries
        self.log = get_logger(f"{source}-sim")
        self.sent = 0
        self.failed = 0

    def envelope(self, type_: str, payload: dict[str, Any], quality: float | None = None) -> Envelope[Any]:
        return make(type_, payload, source=self.source, home_id=self.home_id, sim=True, quality=quality)

    async def post(self, items: list[tuple[Any, ...]]) -> bool:
        """Validate + send one batch of (type, payload) or (type, payload, quality). True if the cloud accepted it."""
        envs = [self.envelope(*item) for item in items]  # raises ContractError on a bad payload (a sim bug)
        body = '{"events":[' + ",".join(to_json(e) for e in envs) + "]}"
        headers = {"content-type": "application/json"}
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        delay = 0.5
        for attempt in range(1, self.retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_s, transport=self.transport) as c:
                    r = await c.post(f"{self.url}/v1/events", content=body, headers=headers)
                if r.status_code < 300:
                    self.sent += len(envs)
                    self.log.info("posted", f"{len(envs)} events", types=[e.type for e in envs])
                    return True
                if 400 <= r.status_code < 500:  # our fault: retrying won't help
                    self.log.warning("rejected", f"HTTP {r.status_code}: {r.text[:200]}")
                    break
                self.log.warning("post_failed", f"HTTP {r.status_code} (attempt {attempt})")
            except httpx.HTTPError as e:
                self.log.warning("cloud_unreachable", f"{type(e).__name__} (attempt {attempt}) {self.url}")
            await asyncio.sleep(delay)
            delay *= 2
        self.failed += len(envs)
        return False
