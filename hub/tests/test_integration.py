"""End-to-end over a real mosquitto: fake head/sensors (acting like the sims) + hub -> full v2 ritual.

Head protocol (same as sim/nodes/head_sim.py): on obs.ritual dial started -> three ear presses
(mood, energy, sleep); on obs.drum_session -> one ear press (post-activity mood)."""

import asyncio

import pytest
from kaiku_contracts.bus import Bus
from kaiku_hub.live.base import OffMusic, OffVoice
from kaiku_hub.main import Hub

HOME = "it-home"


async def test_full_ritual_over_mqtt(broker, settings, ppg):
    s = settings
    s.home_id = HOME
    s.greet_s, s.dial_s, s.breathe_s, s.drum_s, s.drum_idle_end_s, s.nudge_s = 0.3, 8, 3, 4, 1, 0.5
    s.post_mood_s = 5
    seen: list = []
    fake = Bus("sensors", home_id=HOME, sim=True, heartbeat=False)
    head = Bus("head", home_id=HOME, sim=True)
    ppg_on = asyncio.Event()
    sig = ppg([800, 850] * 40)

    async def on_obs(t, env):
        seen.append(env)
        if env.type == "obs.ritual" and env.payload.status == "started":
            if env.payload.step == "greet":
                asyncio.create_task(answer_dial([3]))
            elif env.payload.step == "dial":
                asyncio.create_task(answer_dial([4, 2, 5]))
            elif env.payload.step == "drum":
                asyncio.create_task(drum())
        elif env.type == "obs.drum_session":
            asyncio.create_task(answer_dial([5]))

    async def on_sensors_cmd(t, env):
        if env.payload.ppg == "start":
            ppg_on.set()
            asyncio.create_task(stream_ppg())
        elif env.payload.ppg == "stop":
            ppg_on.clear()

    async def answer_dial(values):
        for v in values:
            await asyncio.sleep(0.15)
            await head.publish("raw.head.ear", {"value": v, "delta": 1})
            await head.publish("raw.head.ear", {"value": v, "delta": 0, "pressed": True})

    async def drum():
        await asyncio.sleep(0.1)
        for i in range(10):
            await head.publish("raw.head.tap", {"t_ms": 10_000 + i * 500, "force": 2.4})
            await asyncio.sleep(0.05)

    async def stream_ppg():
        i = 0
        while ppg_on.is_set() and i + 25 <= len(sig):  # ~5x real time
            await fake.publish("raw.sensors.ppg", {"t0_ms": i * 10, "fs_hz": 100.0, "samples": sig[i:i + 25].tolist()})
            i += 25
            await asyncio.sleep(0.05)

    fake.on("obs/#", on_obs)
    fake.on("cmd/sensors", on_sensors_cmd)
    hub = Hub(s, voice=OffVoice(), music=OffMusic(), read_stdin=False)
    stop = asyncio.Event()
    async with fake, head:
        hub_task = asyncio.create_task(hub.run(stop))
        await asyncio.wait_for(hub.bus.connected.wait(), 5)
        await fake.publish("cmd.hub", {"start_ritual": True}, source="cloud")
        for _ in range(300):
            if any(e.type == "obs.ritual" and e.payload.step == "close" and e.payload.status == "completed" for e in seen):
                break
            await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(hub_task, 5)

    types = {e.type for e in seen}
    done = {e.payload.step: e.payload.status for e in seen if e.type == "obs.ritual" and e.payload.status != "started"}
    assert done.get("close") == "completed", done
    assert {"obs.self_report", "obs.hrv_session", "obs.drum_session", "obs.intervention_response",
            "obs.nudge_offered"} <= types, types
    dial = [(e.payload.item, e.payload.value, e.payload.context) for e in seen if e.type == "obs.self_report"]
    assert dial == [("mood", 4, "ritual"), ("energy", 2, "ritual"), ("sleep", 5, "ritual"),
                    ("mood", 5, "post_activity")]
    drum_ir = next(e for e in seen if e.type == "obs.intervention_response" and e.payload.activity == "drum")
    assert drum_ir.payload.pre.mood == 4 and drum_ir.payload.post.mood == 5 and drum_ir.payload.delta.mood == 1
    drum_obs = next(e for e in seen if e.type == "obs.drum_session")
    assert drum_obs.payload.tempo_bpm == pytest.approx(120) and drum_obs.payload.taps == 10
    assert all(e.sim for e in seen if e.source == "hub")  # inputs were sim -> obs flagged sim
    assert hub.uplink.size() >= len([e for e in seen if e.source == "hub"])  # all queued for the cloud
