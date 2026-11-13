import asyncio

import pytest
from kaiku_contracts.bus import Bus


async def test_publish_subscribe_and_heartbeat(broker):
    got = []

    async def on_tap(t, env):
        got.append((t.type, env))

    listener = Bus("hub", home_id="t1", heartbeat=False)
    listener.on("raw/head/#", on_tap)
    listener.on("health/#", on_tap)
    async with listener:
        async with Bus("head", home_id="t1", sim=True) as head:
            await head.publish("raw.head.tap", {"t_ms": 5, "force": 1.5})
            for _ in range(50):
                if any(k == "raw.head.tap" for k, _ in got) and any(k == "health" for k, _ in got):
                    break
                await asyncio.sleep(0.05)
    types = [k for k, _ in got]
    assert "raw.head.tap" in types and "health" in types
    tap = next(e for k, e in got if k == "raw.head.tap")
    assert tap.sim is True and tap.payload.force == 1.5


async def test_offline_publish_is_dropped_not_raised(monkeypatch):
    monkeypatch.setenv("MQTT_PORT", "1")  # nothing listens here
    async with Bus("head", home_id="t1") as head:
        ok = await head.publish_env(__import__("kaiku_contracts").example("raw.head.tap", home_id="t1"))
    assert ok is False


async def test_invalid_publish_raises(broker):
    from kaiku_contracts import ContractError

    async with Bus("head", home_id="t1") as head:
        with pytest.raises(ContractError):
            await head.publish("raw.head.tap", {"t_ms": -1, "force": 1})
