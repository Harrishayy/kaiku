import json
from datetime import UTC, datetime

import httpx
from kaiku_contracts.api import EpisodeIn
from kaiku_hub.cloudlink import CloudLink
from kaiku_hub.episodes import EpisodeOutbox
from kaiku_hub.perception.hrv import PpgBuffer


async def test_episode_survives_restart_and_failed_delivery(tmp_path):
    attempts = []

    def handler(request):
        attempts.append(json.loads(request.content))
        return httpx.Response(503 if len(attempts) == 1 else 200, json={"ok": True})

    link = CloudLink(url="http://cloud", home_id="test", transport=httpx.MockTransport(handler))
    path = tmp_path / "episodes.sqlite"
    box = EpisodeOutbox(path, link)
    box.enqueue(EpisodeIn(id="stable-id", home_id="test", surface="robot", start=datetime.now(UTC),
                          transcript=[{"role": "person", "text": "Synthetic test conversation"}]))
    assert await box.flush() == 0
    box.db.close()
    again = EpisodeOutbox(path, link)
    assert await again.flush() == 1
    assert attempts[0] == attempts[1]
    assert again.db.execute("SELECT count(*) FROM episodes").fetchone()[0] == 0


async def test_follow_up_survives_restart_and_retries_with_same_episode(tmp_path):
    attempts = []

    def handler(request):
        attempts.append(json.loads(request.content))
        return httpx.Response(503 if len(attempts) == 1 else 200, json={"ok": True})

    link = CloudLink(url="http://cloud", home_id="test", transport=httpx.MockTransport(handler))
    path = tmp_path / "episodes.sqlite"
    box = EpisodeOutbox(path, link)
    follow_up = {"skill": "walk_companion", "topic": "the park path"}
    box.enqueue(EpisodeIn(id="stable-id", home_id="test", surface="robot", start=datetime.now(UTC),
                          open_thread=follow_up, outcome="completed"))
    assert await box.flush() == 0
    box.db.close()
    again = EpisodeOutbox(path, link)
    assert await again.flush() == 1
    assert attempts[0] == attempts[1]
    assert attempts[1]["open_thread"] == follow_up and attempts[1]["outcome"] == "completed"


async def test_refused_follow_up_cannot_block_episode_completions(tmp_path):
    attempts = []

    def handler(request):
        episode = json.loads(request.content)
        attempts.append(episode)
        return httpx.Response(422 if episode.get("open_thread") else 200, json={"ok": True})

    link = CloudLink(url="http://cloud", home_id="test", transport=httpx.MockTransport(handler))
    box = EpisodeOutbox(tmp_path / "episodes.sqlite", link)
    box.enqueue(EpisodeIn(id="stable-id", home_id="test", surface="robot", start=datetime.now(UTC),
                          open_thread={"skill": "walk_companion", "topic": "a refused topic"}))
    assert await box.flush() == 0
    assert await box.flush() == 1
    assert attempts[0]["id"] == attempts[1]["id"] == "stable-id"
    assert attempts[1]["open_thread"] is None
    assert box.db.execute("SELECT count(*) FROM episodes").fetchone()[0] == 0


def test_ppg_gap_discards_noncontiguous_signal():
    buf = PpgBuffer()
    buf.add(100, [1] * 100, t0_ms=0, quality=0.9)
    buf.add(100, [2] * 100, t0_ms=1000, quality=0.8)
    assert buf.seconds == 2 and buf.quality == 0.8
    buf.add(100, [3] * 100, t0_ms=4000, quality=0.95)
    assert buf.seconds == 1 and buf.samples == [3] * 100 and buf.quality == 0.95
