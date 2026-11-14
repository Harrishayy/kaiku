"""UNO Q node on a laptop: FakeBridge for the STM32, no camera, real throwaway broker."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kaiku_contracts.bus import Bus  # noqa: E402
from kaiku_unoq.bridge import FakeBridge  # noqa: E402
from kaiku_unoq.node import SensorsNode  # noqa: E402
from kaiku_unoq.vision import Box, distance_cm, face_payload, light_payload  # noqa: E402


def test_face_payload_and_distance():
    f = face_payload(Box(x=480, y=180, w=96, h=96), 640, 480)
    assert f["x_norm"] == 0.65 and f["size"] == 0.15 and -1 <= f["y_norm"] <= 1
    assert distance_cm(0.15, 9.0, 300) == 60.0
    assert distance_cm(None, 9.0, 300) == 300  # nobody seen -> far
    assert distance_cm(0.01, 9.0, 300) == 300  # capped
    assert light_payload(300.0, 2.0) == {"raw": 255, "lux_est": 510.0}


async def test_node_bridges_knock_hall_light_and_chimes(broker, monkeypatch):
    monkeypatch.setenv("KAIKU_UNOQ_LIGHT_EVERY_S", "0.2")
    from kaiku_contracts.config import load_config
    load_config.cache_clear()
    bridge = FakeBridge()
    node = SensorsNode(bridge, camera=False, sim=True)
    got = []

    async def on(t, env):
        got.append(env)

    stop = asyncio.Event()
    task = asyncio.create_task(node.run(stop))
    hub = Bus("hub", heartbeat=False)
    hub.on("raw/#", on)
    async with hub:
        await node.bus.connected.wait()
        await asyncio.sleep(0.2)
        bridge.knock(1234)
        bridge.hall(True)
        await hub.publish("cmd.sensors", {"chime": "ok"})
        await hub.publish("raw.head.pan", {"deg": 5.0, "homed": True, "moving": True})
        await asyncio.sleep(0.5)
    stop.set()
    await task
    load_config.cache_clear()
    taps = [e for e in got if e.type == "raw.head.tap"]
    assert len(taps) == 1 and taps[0].payload.src == "knock" and taps[0].payload.force is None
    assert taps[0].source == "sensors"
    assert [e.payload.at_home for e in got if e.type == "raw.sensors.hall"] == [True]
    light = [e for e in got if e.type == "raw.sensors.light"]
    assert light and light[0].payload.raw == 1200 and light[0].payload.lux_est == 300.0
    assert ("buzz_pattern", ("ok",)) in bridge.calls and ("motor_moving", (1,)) in bridge.calls
    assert ("status_set", ("ok",)) in bridge.calls
    assert bridge.calls[0][0] == "ping" and node.mcu_fw == "fake-0.2.0"
    assert not any(c[0].startswith("eyes") for c in bridge.calls)  # the eyes are the Atech display now


def test_ppg_signal_check():
    from kaiku_unoq.vision import forehead, parse_csv_samples, ppg_signal_ok

    assert ppg_signal_ok([8000, 8100, 7950, 8200], 30, 16000)
    assert not ppg_signal_ok([8000] * 25, 30, 16000)  # flat: no LED / unwired
    assert not ppg_signal_ok([16383] * 20 + [16000] * 5, 30, 16000)  # pinned at the rail
    assert parse_csv_samples("1,2, 3,x") == [1, 2, 3]
    f = forehead(Box(100, 100, 80, 100))
    assert f.x == 120 and f.w == 40 and f.y == 110


class StubCamera:
    def __init__(self):
        self.ppg_on = asyncio.Event()  # same set/clear/is_set API as threading.Event
        self.enabled = asyncio.Event()
        self.ok = True

    def start(self):
        pass

    def stop(self):
        pass


async def test_pulse_ky039_first_then_camera_backup(broker, monkeypatch):
    monkeypatch.setenv("KAIKU_UNOQ_PPG_FALLBACK_S", "0.6")
    from kaiku_contracts.config import load_config
    load_config.cache_clear()
    bridge = FakeBridge()
    node = SensorsNode(bridge, camera=False, sim=True)
    node.camera = StubCamera()
    got = []

    async def on(t, env):
        got.append(env)

    stop = asyncio.Event()
    task = asyncio.create_task(node.run(stop))
    hub = Bus("hub", heartbeat=False)
    hub.on("raw/sensors/ppg", on)
    async with hub:
        await node.bus.connected.wait()
        await asyncio.sleep(0.2)
        await hub.publish("cmd.sensors", {"ppg": "start"})
        await asyncio.sleep(0.2)
        assert node.ppg_active == "ky039" and ("ppg_start", ()) in bridge.calls
        bridge.ppg(1000, [8000 + (i % 5) * 40 for i in range(25)])  # clean beat-like batch
        await asyncio.sleep(0.2)
        bridge.ppg(1250, [8000] * 25)  # then flat (finger gone / unwired) ...
        await asyncio.sleep(1.2)  # ... longer than the fallback window
        assert node.ppg_active == "camera" and node.camera.ppg_on.is_set()
        await node.camera_batch(5000, 14.8, [12000, 12010, 11990] * 5)
        await hub.publish("cmd.sensors", {"ppg": "stop"})
        await asyncio.sleep(0.3)
    stop.set()
    await task
    load_config.cache_clear()
    assert node.ppg_active is None and not node.camera.ppg_on.is_set()
    ky = [e for e in got if e.payload.fs_hz == 100]
    cam = [e for e in got if e.payload.fs_hz == 14.8]
    assert len(ky) == 2 and ky[0].quality == 0.9
    assert len(cam) == 1 and cam[0].quality == 0.6
