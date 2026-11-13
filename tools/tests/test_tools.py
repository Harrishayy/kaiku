import asyncio
import json

from kaiku_contracts import example, to_json
from kaiku_contracts.bus import Bus

from tools.bus_tail import fmt
from tools.record import record
from tools.replay import prepare, replay


def test_fmt_valid_and_invalid():
    env = example("obs.drum_session")
    line = fmt("kaiku/v1/demo-aino/obs/drum_session", to_json(env).encode(), color=False)
    assert "obs/drum_session" in line and "SIM" in line and "tempo_bpm" in line
    bad = fmt("kaiku/v1/demo-aino/obs/mood_dial", b'{"nope": 1}', color=False)
    assert "INVALID" in bad


def test_prepare_restamps_and_rejects_invalid():
    env = example("raw.head.tap")
    row = {"t": 0, "topic": "x", "msg": json.loads(to_json(env))}
    topic, body, qos = prepare(row, keep_ids=False, home="other-home")
    assert topic == "kaiku/v1/other-home/raw/head/tap" and qos == 0
    assert json.loads(body)["id"] != str(env.id)
    assert prepare({"t": 0, "topic": "x", "msg": {"bad": 1}}, keep_ids=False, home=None) is None


async def test_record_then_replay_round_trip(broker, tmp_path):
    out = tmp_path / "rec.jsonl"
    rec = asyncio.create_task(record("kaiku/v1/#", out, seconds=1.5))
    await asyncio.sleep(0.3)
    async with Bus("head", home_id="t1", heartbeat=False, sim=True) as b:
        for i in range(3):
            await b.publish("raw.head.tap", {"t_ms": i, "force": 1.0})
    assert await rec == 3
    got = []

    async def on_tap(t, env):
        got.append(env)

    listener = Bus("hub", home_id="t1", heartbeat=False)
    listener.on("raw/head/tap", on_tap)
    async with listener:
        assert await replay(out, speed=10, only=None, keep_ids=False, home=None, verbatim=False, loop=False) == 3
        await asyncio.sleep(0.3)
    assert [e.payload.t_ms for e in got] == [0, 1, 2]
