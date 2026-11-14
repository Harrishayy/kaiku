"""Durable idempotent robot episode completion. No raw audio; transcripts require explicit consent."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from kaiku_contracts.api import EpisodeIn
from kaiku_contracts.jlog import get_logger

from .cloudlink import CloudLink

log = get_logger("hub")


class EpisodeOutbox:
    def __init__(self, path: Path, cloud: CloudLink):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS episodes (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.db.commit()
        self.cloud = cloud
        self.wake = asyncio.Event()

    def enqueue(self, episode: EpisodeIn) -> None:
        if not episode.id:
            raise ValueError("durable episodes require an id")
        self.db.execute("INSERT OR REPLACE INTO episodes VALUES (?, ?)",
                        (episode.id, episode.model_dump_json()))
        self.db.commit()
        self.wake.set()

    def size(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0])

    async def flush(self) -> int:
        if not self.cloud.url:
            return 0
        sent = 0
        for id_, payload in self.db.execute("SELECT id, payload FROM episodes ORDER BY rowid LIMIT 20").fetchall():
            try:
                async with self.cloud._client() as client:
                    response = await client.post("/v1/companion/episode", content=payload,
                                                 headers={"Content-Type": "application/json"})
                if response.status_code == 422:
                    episode = json.loads(payload)
                    if episode.get("open_thread"):
                        # The cloud owns notebook policy. A refused follow-up must not permanently
                        # block this completion or later episodes; retry its metadata without it.
                        episode["open_thread"] = None
                        self.db.execute("UPDATE episodes SET payload = ? WHERE id = ?",
                                        (json.dumps(episode), id_))
                        self.db.commit()
                        log.warning("episode_follow_up_refused", "retrying completion without follow-up")
                if response.status_code != 200 or not response.json().get("ok"):
                    break
            except Exception:
                break
            self.db.execute("DELETE FROM episodes WHERE id = ?", (id_,))
            self.db.commit()
            sent += 1
        return sent

    async def run(self) -> None:
        delay = 2
        while True:
            self.wake.clear()
            sent = await self.flush()
            delay = 2 if sent else min(60, delay * 2)
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=delay)
            except TimeoutError:
                pass
