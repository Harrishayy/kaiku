"""Uplink: obs/* -> POST /v1/events. Batches every `batch_s`, survives cloud outages.

- SQLite offline queue (survives hub restarts); id = UUIDv7 = idempotency key (INSERT OR IGNORE).
- Priority lane: obs.safety_flag is flushed immediately and always first.
- Never uplinks anything that isn't obs.* (raw/cmd/health stay home).
- Exponential backoff with jitter on network/5xx/auth errors; 4xx poison batches are dropped + logged.
"""

from __future__ import annotations

import asyncio
import json
import random
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx
from kaiku_contracts import UPLINKABLE, Envelope, to_json
from kaiku_contracts.jlog import get_logger

log = get_logger("hub")

PRIORITY_TYPES = {"obs.safety_flag"}


class Uplink:
    def __init__(
        self,
        *,
        url: str | None,
        token: str | None = None,
        queue_path: Path | str = ":memory:",
        batch_s: float = 2.0,
        max_batch: int = 200,
        timeout_s: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.url = url.rstrip("/") if url else None
        self.token = token
        self.batch_s = batch_s
        self.max_batch = max_batch
        self.timeout_s = timeout_s
        self.transport = transport
        if str(queue_path) != ":memory:":
            Path(queue_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(queue_path), isolation_level=None, check_same_thread=False)
        if str(queue_path) != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS queue (id TEXT PRIMARY KEY, priority INTEGER NOT NULL, "
            "created REAL NOT NULL, type TEXT NOT NULL, body TEXT NOT NULL)"
        )
        self._wake = asyncio.Event()
        self.failures = 0
        self.last_error: str | None = None
        self.last_success: float | None = None
        self.sent = 0
        self._warned_offline = False

    # ------------------------------------------------------------------ queue
    def enqueue(self, env: Envelope[Any]) -> bool:
        if env.type not in UPLINKABLE:
            log.warning("uplink_refused", "only obs.* may leave the home", type=env.type)
            return False
        prio = 0 if env.type in PRIORITY_TYPES else 1
        cur = self.db.execute(
            "INSERT OR IGNORE INTO queue (id, priority, created, type, body) VALUES (?,?,?,?,?)",
            (str(env.id), prio, time.time(), env.type, to_json(env)),
        )
        if prio == 0:
            self._wake.set()
        return cur.rowcount == 1

    def size(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM queue").fetchone()[0])

    def lag_s(self) -> float | None:
        row = self.db.execute("SELECT MIN(created) FROM queue").fetchone()
        return round(time.time() - row[0], 1) if row and row[0] else None

    def _next_batch(self) -> list[tuple[str, str]]:
        return self.db.execute(
            "SELECT id, body FROM queue ORDER BY priority, created LIMIT ?", (self.max_batch,)
        ).fetchall()

    def _delete(self, ids: list[str]) -> None:
        self.db.executemany("DELETE FROM queue WHERE id = ?", [(i,) for i in ids])

    # ------------------------------------------------------------------ send
    def _client(self) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        return httpx.AsyncClient(base_url=self.url or "", headers=headers, timeout=self.timeout_s,
                                 transport=self.transport)

    async def flush_once(self) -> bool:
        """Send one batch. True if the batch was handled (sent or dropped as poison) or queue empty."""
        batch = self._next_batch()
        if not batch:
            return True
        if not self.url:
            if not self._warned_offline:
                log.warning("uplink_offline", "KAIKU_CLOUD_URL not set; queueing locally")
                self._warned_offline = True
            return False
        ids = [i for i, _ in batch]
        body = {"events": [json.loads(b) for _, b in batch]}
        try:
            async with self._client() as client:
                r = await client.post("/v1/events", json=body)
        except httpx.HTTPError as e:
            return self._fail(f"{type(e).__name__}: {e}")
        if r.status_code < 300:
            try:
                res = r.json()
                for rej in res.get("rejected", []):
                    log.error("uplink_rejected", str(rej.get("error", ""))[:300], id=rej.get("id"))
            except ValueError:
                pass
            self._delete(ids)
            self.sent += len(ids)
            self.failures = 0
            self.last_error = None
            self.last_success = time.time()
            return True
        if r.status_code in (401, 403, 408, 429) or r.status_code >= 500:
            return self._fail(f"HTTP {r.status_code}")
        # other 4xx: the batch itself is bad; keep the queue moving
        log.error("uplink_poison_batch", f"HTTP {r.status_code}: {r.text[:300]}", dropped=len(ids))
        self._delete(ids)
        return True

    def _fail(self, err: str) -> bool:
        self.failures += 1
        self.last_error = err
        if self.failures in (1, 5) or self.failures % 20 == 0:
            log.warning("uplink_failed", err, failures=self.failures, queued=self.size())
        return False

    def backoff_s(self) -> float:
        if self.failures == 0:
            return self.batch_s
        return min(60.0, self.batch_s * 2 ** min(self.failures, 6)) * random.uniform(0.8, 1.2)

    async def run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.backoff_s())
            except TimeoutError:
                pass
            self._wake.clear()
            try:
                while self.size() and await self.flush_once():
                    pass
            except Exception as e:  # never let the uplink die
                self._fail(f"{type(e).__name__}: {e}")
