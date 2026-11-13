import asyncio
import json

import httpx
from kaiku_contracts import example
from kaiku_hub.uplink import Uplink


def recorder(statuses):
    """MockTransport answering with the given status codes in order (last one repeats)."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append({"ids": [e["id"] for e in body["events"]], "types": [e["type"] for e in body["events"]],
                      "auth": request.headers.get("authorization")})
        code = statuses[min(len(calls) - 1, len(statuses) - 1)]
        return httpx.Response(code, json={"accepted": len(body["events"]), "duplicates": 0, "rejected": []})

    return calls, httpx.MockTransport(handler)


def test_only_obs_and_dedupe(tmp_path):
    up = Uplink(url=None, queue_path=tmp_path / "q.sqlite")
    e = example("obs.self_report")
    assert up.enqueue(e) is True
    assert up.enqueue(e) is False  # same id -> ignored
    assert up.enqueue(example("raw.head.tap")) is False
    assert up.enqueue(example("health")) is False
    assert up.size() == 1


async def test_offline_queue_persists_then_flushes(tmp_path):
    q = tmp_path / "q.sqlite"
    up = Uplink(url=None, queue_path=q)
    for _ in range(3):
        up.enqueue(example("obs.drum_session"))
    assert await up.flush_once() is False  # no URL: stays queued
    # "restart" the hub with the cloud now reachable
    calls, transport = recorder([200])
    up2 = Uplink(url="http://cloud", token="tok", queue_path=q, transport=transport)
    assert up2.size() == 3
    assert await up2.flush_once() is True
    assert up2.size() == 0 and len(calls[0]["ids"]) == 3 and calls[0]["auth"] == "Bearer tok"


async def test_retry_with_backoff_on_5xx_and_network(tmp_path):
    calls, transport = recorder([503, 200])
    up = Uplink(url="http://cloud", queue_path=tmp_path / "q.sqlite", transport=transport, batch_s=0.01)
    up.enqueue(example("obs.presence"))
    assert await up.flush_once() is False and up.failures == 1 and up.size() == 1
    assert up.backoff_s() > 0.01
    assert await up.flush_once() is True and up.size() == 0 and up.failures == 0

    def boom(request):
        raise httpx.ConnectError("down")

    up3 = Uplink(url="http://cloud", queue_path=tmp_path / "q3.sqlite", transport=httpx.MockTransport(boom))
    up3.enqueue(example("obs.presence"))
    assert await up3.flush_once() is False and up3.size() == 1


async def test_auth_failure_keeps_data_poison_batch_dropped(tmp_path):
    calls, transport = recorder([401])
    up = Uplink(url="http://cloud", queue_path=tmp_path / "q.sqlite", transport=transport)
    up.enqueue(example("obs.presence"))
    assert await up.flush_once() is False and up.size() == 1
    calls, transport = recorder([422])
    up.transport = transport
    assert await up.flush_once() is True and up.size() == 0


async def test_safety_flag_priority_and_immediate(tmp_path):
    calls, transport = recorder([200])
    up = Uplink(url="http://cloud", queue_path=tmp_path / "q.sqlite", transport=transport, batch_s=30, max_batch=2)
    for _ in range(3):
        up.enqueue(example("obs.drum_session"))
    task = asyncio.create_task(up.run())
    await asyncio.sleep(0.05)
    assert calls == []  # normal lane waits for the 30 s batch window
    up.enqueue(example("obs.safety_flag"))
    for _ in range(50):
        if calls:
            break
        await asyncio.sleep(0.02)
    task.cancel()
    assert calls[0]["types"][0] == "obs.safety_flag"  # first in the first batch
