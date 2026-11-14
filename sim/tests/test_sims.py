import asyncio
import time

import numpy as np
import pytest
from kaiku_contracts.bus import Bus

from sim.nodes.head_sim import HeadSim
from sim.nodes.sensors_sim import SensorsSim
from sim.nodes.signals import PpgSynth, approach_curve


def _peaks(x: np.ndarray, fs: float) -> np.ndarray:
    x = x - np.convolve(x, np.ones(int(fs)) / fs, mode="same")
    thr = np.percentile(x, 90) * 0.5
    idx = [i for i in range(1, len(x) - 1) if x[i] > thr and x[i] >= x[i - 1] and x[i] > x[i + 1]]
    out = []
    for i in idx:  # 450 ms refractory (skips the dicrotic wave)
        if not out or i - out[-1] > 0.45 * fs:
            out.append(i)
    return np.array(out)


def test_ppg_heart_rate_and_rsa():
    fs = 100.0
    calm = PpgSynth(hr_bpm=70, seed=1)
    x = np.array(calm.samples(int(60 * fs)), dtype=float)
    ibi = (np.diff(_peaks(x, fs)) / fs)[1:-1]  # drop detrend edge artefacts
    assert abs(60 / ibi.mean() - 70) < 4
    paced = PpgSynth(hr_bpm=70, breath_bpm=6, rsa_ms=80, seed=1)
    y = np.array(paced.samples(int(60 * fs)), dtype=float)
    ibi2 = (np.diff(_peaks(y, fs)) / fs)[1:-1]
    assert ibi2.std() > ibi.std()  # paced breathing -> more variability
    assert 12000 < x.min() and x.max() < 21000


def test_approach_curve_monotonic():
    vals = [approach_curve(t / 10) for t in range(40)]
    assert vals[0] == 200 and abs(vals[-1] - 50) < 1e-6
    assert all(a >= b for a, b in zip(vals, vals[1:], strict=False))


async def test_head_sim_dial_drum_and_post_mood(broker, monkeypatch):
    monkeypatch.setenv("KAIKU_RITUAL_DRUM_S", "3")
    from kaiku_contracts.config import load_config
    load_config.cache_clear()
    taps, ears = [], []

    async def on_raw(t, env):
        (taps if env.type == "raw.head.tap" else ears).append(env)

    stop = asyncio.Event()
    head = HeadSim(tempo_bpm=120, mood=4, seed=3, dial="ear", drum="imu")
    task = asyncio.create_task(head.run(stop))
    obs = Bus("hub", heartbeat=False)
    obs.on("raw/head/tap", on_raw)
    obs.on("raw/head/ear", on_raw)
    async with obs:
        await head.bus.connected.wait()
        await obs.publish("obs.ritual", {"step": "dial", "status": "started"})
        for _ in range(100):
            if sum(e.payload.pressed for e in ears) >= 3:
                break
            await asyncio.sleep(0.1)
        await obs.publish("obs.ritual", {"step": "drum", "status": "started"})
        await asyncio.sleep(2.0)
        n_taps = len(taps)
        await obs.publish("obs.drum_session", {"tempo_bpm": 120, "force_mean": 0.5, "duration_s": 2, "regularity": 0.9,
                                               "taps": n_taps})
        await asyncio.sleep(2.5)
    stop.set()
    await task
    load_config.cache_clear()
    presses = [e.payload.value for e in ears if e.payload.pressed]
    assert len(presses) == 4 and presses[0] == 4  # mood, energy, sleep, then post-activity mood
    assert presses[3] == 5  # post-activity: mood + 1
    assert n_taps >= 3
    assert len(taps) <= n_taps + 1  # drumming stopped on obs.drum_session


async def test_head_sim_button_build_presses_and_knocks(broker, monkeypatch):
    """Button build: a dial answer is n short presses on raw/head/button; drum taps are knocks without force."""
    monkeypatch.setenv("KAIKU_ROBOT_PRESS_WINDOW_S", "0.3")
    from kaiku_contracts.config import load_config
    load_config.cache_clear()
    buttons, taps = [], []

    async def on_raw(t, env):
        (taps if env.type == "raw.head.tap" else buttons).append(env)

    stop = asyncio.Event()
    head = HeadSim(tempo_bpm=150, mood=3, seed=1, dial="button", drum="knock")
    task = asyncio.create_task(head.run(stop))
    obs = Bus("hub", heartbeat=False)
    obs.on("raw/head/button", on_raw)
    obs.on("raw/head/tap", on_raw)
    async with obs:
        await head.bus.connected.wait()
        await head._answer(3, first_delay=0)
        await head.tap()
        await asyncio.sleep(0.3)
    stop.set()
    await task
    load_config.cache_clear()
    downs = [e for e in buttons if e.payload.pressed]
    assert len(downs) == 3 and all(e.payload.id == "head" for e in downs)
    assert taps and taps[0].payload.src == "knock" and taps[0].payload.force is None


async def test_sensors_sim_ppg_only_when_started(broker):
    got, unsupported = [], []

    async def on_ppg(t, env):
        got.append(env)

    async def on_unsupported(t, env):
        unsupported.append(env)

    stop = asyncio.Event()
    s = SensorsSim(arrive_after_s=None, seed=2, ppg_fixture=True)
    task = asyncio.create_task(s.run(stop))
    ctl = Bus("hub", heartbeat=False)
    ctl.on("raw/sensors/ppg", on_ppg)
    ctl.on("raw/sensors/light", on_unsupported)
    ctl.on("raw/sensors/hall", on_unsupported)
    async with ctl:
        await s.bus.connected.wait()
        await asyncio.sleep(0.6)
        assert not got
        await ctl.publish("cmd.sensors", {"ppg": "start"})
        await asyncio.sleep(1.1)
    stop.set()
    await task
    assert len(got) >= 3 and len(got[0].payload.samples) == 25
    assert unsupported == []


def _mock(record, status=200):
    import httpx

    def handler(req):
        record.append(req)
        return httpx.Response(status, json={"accepted": 1, "duplicates": 0, "rejected": []})

    return httpx.MockTransport(handler)


async def test_glasses_and_laptop_post_valid_envelopes(monkeypatch):
    import json

    from kaiku_contracts import validate

    from sim.nodes.glasses_sim import GlassesSim
    from sim.nodes.laptop_sim import LaptopSim

    monkeypatch.setenv("KAIKU_HOME_TOKEN", "t0k")
    reqs = []
    g = GlassesSim(seed=1, transport=_mock(reqs), url="http://cloud")
    lap = LaptopSim(seed=1, transport=_mock(reqs), url="http://cloud")
    assert await g.walk_done()
    assert await lap.session()
    assert await lap.phq9(item9=True)
    assert all(r.url.path == "/v1/events" and r.headers["authorization"] == "Bearer t0k" for r in reqs)
    envs = [validate(e) for r in reqs for e in json.loads(r.content)["events"]]
    by_type = {e.type: e for e in envs}
    assert {e.source for e in envs} == {"glasses", "laptop"} and all(e.sim for e in envs)
    out = by_type["obs.outing"].payload
    assert out.method == "steps" and out.steps
    assert out.cadence_spm is None and out.gait_regularity is None and out.head_up_ratio is None
    assert out.daylight_min is None
    assert by_type["obs.intervention_response"].payload.activity == "walk"
    assert by_type["obs.laptop_session"].payload.reaction_ms_median > 0
    assert by_type["obs.phq9"].payload.item9_positive and by_type["obs.phq9"].payload.mode == "laptop"
    assert by_type["obs.safety_flag"].payload.trigger == "phq9_item9"


async def test_mac_and_phone_twins_post_plan02_obs():
    import json

    from kaiku_contracts import validate

    from sim.nodes.laptop_sim import LaptopSim
    from sim.nodes.phone_sim import PhoneSim

    reqs = []
    lap = LaptopSim(seed=3, transport=_mock(reqs), url="http://cloud")
    assert await lap.mac_hour(hour=2)
    phone = PhoneSim(seed=3, transport=_mock(reqs), url="http://cloud")
    assert await phone.morning() and await phone.play()
    no_watch = PhoneSim(seed=4, watch=False, transport=_mock(reqs), url="http://cloud")
    assert await no_watch.morning()
    envs = [validate(e) for r in reqs for e in json.loads(r.content)["events"]]
    screen = next(e for e in envs if e.type == "obs.screen_activity")
    assert screen.source == "laptop" and screen.payload.late_night_min == screen.payload.active_min  # 02:00
    wear = [e for e in envs if e.type == "obs.wearable_daily"]
    assert {e.source for e in wear} == {"phone"} and {w.payload.device for w in wear} == {"apple_watch", "phone_only"}
    assert next(w for w in wear if w.payload.device == "phone_only").payload.sleep_min is None
    dial = [e for e in envs if e.type == "obs.self_report"]
    assert len(dial) == 6 and all(e.payload.channel == "phone" for e in dial)
    assert {e.payload.device for e in envs if e.type == "obs.play_session"} == {"mac", "phone"}
    assert all(e.sim for e in envs)
    assert all(e.payload.camera_method is None and e.payload.camera_samples is None
               and e.payload.expressivity_index is None for e in envs if e.type == "obs.play_session")
    pebbles = next(e for e in envs if e.type == "obs.play_session" and e.payload.game == "pebbles")
    assert pebbles.payload.span_max >= 2 and 0 <= pebbles.payload.accuracy <= 1
    # measured games: one of each, with the trial record, provenance and an envelope quality
    games = {e.payload.game: e for e in envs if e.type == "obs.play_session" and e.payload.trials_n}
    assert {"lantern", "seeds", "watering"} <= set(games)
    for e in games.values():
        p = e.payload
        assert e.quality is not None and e.quality >= 0.6 and p.valid and p.warmup is False and p.input == "touch"
        assert len(p.rt_ms) == len(p.trial_codes) == p.trials_n
    assert games["lantern"].payload.response_speed > 2 and 0 <= games["watering"].payload.hard_choice_ratio <= 1
    doubtful = PhoneSim(seed=5, url="http://cloud").lantern(valid=False)[1]
    assert doubtful["valid"] is False and PhoneSim.game_quality(doubtful) == 0.2
    slow, usual = PhoneSim(seed=6, url="http://cloud"), PhoneSim(seed=6, url="http://cloud")
    assert slow.lantern(slowing=1.0)[1]["response_speed"] < usual.lantern()[1]["response_speed"]


async def test_default_laptop_round_omits_retired_browser_features():
    import json

    from sim.nodes.laptop_sim import LaptopSim

    reqs = []
    lap = LaptopSim(seed=3, transport=_mock(reqs), url="http://cloud")
    await lap.run(once=True)
    events = [e for r in reqs for e in json.loads(r.content)["events"]]
    assert {e["type"] for e in events} == {"obs.screen_activity", "obs.play_session"}
    assert all(e["sim"] for e in events)


async def test_legacy_sensors_require_explicit_bench_opt_in():
    from kaiku_contracts import make

    class CaptureBus:
        def __init__(self):
            self.events = []

        async def publish(self, type_, payload):
            self.events.append(make(type_, payload, source="sensors", sim=True))

    for enabled in (False, True):
        sensor = SensorsSim(arrive_after_s=None, light=enabled, hall=enabled, ppg_fixture=enabled)
        await sensor._on_cmd(None, make("cmd.sensors", {"ppg": "start"}, source="hub", sim=True))
        assert sensor.ppg_on is enabled
        sensor.bus = CaptureBus()
        task = asyncio.create_task(sensor._slow_loop())
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert {e.type for e in sensor.bus.events} == ({"raw.sensors.light", "raw.sensors.hall"} if enabled else set())


async def test_http_sims_fail_soft_when_cloud_down():
    import httpx

    from sim.nodes.laptop_sim import LaptopSim

    def boom(req):
        raise httpx.ConnectError("down")

    lap = LaptopSim(seed=2, transport=httpx.MockTransport(boom), url="http://cloud")
    lap.http.retries = 2
    assert await lap.session() is False  # logged, not raised
    assert lap.http.failed == 1
    reqs = []
    lap2 = LaptopSim(seed=2, transport=_mock(reqs, status=422), url="http://cloud")
    assert await lap2.session() is False and len(reqs) == 1  # 4xx is not retried


def test_sensors_face_boxes_grow_as_person_approaches():
    from kaiku_contracts import make

    s = SensorsSim(arrive_after_s=None, seed=3)
    assert s.face_boxes(200.0, 0.0) == []                     # too far for the camera
    far, near = s.face_boxes(170.0, 0.0), s.face_boxes(55.0, 0.0)
    assert len(far) == len(near) == 1 and near[0]["size"] > far[0]["size"] > 0
    s.toggle_second_person()
    two = s.face_boxes(60.0, 0.0)
    assert len(two) == 2 and abs(two[0]["x_norm"] - two[1]["x_norm"]) > 0.5
    for box in far + near + two:
        make("raw.hub.face", box, source="sensors")
    assert SensorsSim(arrive_after_s=None, faces=False).face_boxes(60.0, 0.0) == []


# ---------------------------------------------------------------- twins of the merged firmware (D39)
class _Capture:
    def __init__(self):
        from kaiku_contracts.jlog import get_logger
        self.events = []
        self.log = get_logger("sim-test")

    async def publish(self, type_, payload, quality=None, **_kw):
        from kaiku_contracts import make
        self.events.append(make(type_, payload, source="sensors", sim=True, quality=quality))

    def of(self, type_):
        return [e for e in self.events if e.type == type_]


async def _run_loop(coro, seconds):
    task = asyncio.create_task(coro)
    await asyncio.sleep(seconds)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_sensors_distance_comes_from_the_face_box_like_the_firmware():
    """No distance sensor on the build: distance = k / face size, and far_cm whenever no face is seen."""
    s = SensorsSim(arrive_after_s=None, seed=1)
    s.bus = _Capture()
    await _run_loop(s._distance_loop(), 0.3)
    assert s.bus.of("raw.sensors.distance")[-1].payload.cm == s.far_cm == 300 and not s.bus.of("raw.hub.face")
    s._arrived_at = time.monotonic() - 10  # at the desk
    s.bus.events.clear()
    await _run_loop(s._distance_loop(), 0.3)
    face, dist = s.bus.of("raw.hub.face")[-1].payload, s.bus.of("raw.sensors.distance")[-1].payload
    assert dist.cm == pytest.approx(s.k_cm / face.size, abs=0.5) and dist.cm < 45 and face.size >= 0.22
    s.face_hidden = True  # the person is there, the camera can't find a face: the build cannot know they are near
    s.bus.events.clear()
    await _run_loop(s._distance_loop(), 0.3)
    assert s.bus.of("raw.sensors.distance")[-1].payload.cm == 300 and not s.bus.of("raw.hub.face")
    s.camera_ok = False  # camera unplugged: no distance messages at all
    s.bus.events.clear()
    await _run_loop(s._distance_loop(), 0.3)
    assert not s.bus.events


@pytest.mark.parametrize("mode", ["flat", "noisy", "flicker", "camera", "auto"])
async def test_sensors_pulse_fixtures_match_firmware_shapes(mode, monkeypatch):
    from kaiku_contracts import make
    monkeypatch.setenv("KAIKU_UNOQ_PPG_FALLBACK_S", "0.3")
    from kaiku_contracts.config import load_config
    load_config.cache_clear()
    s = SensorsSim(arrive_after_s=None, seed=4, ppg_fixture=mode)
    load_config.cache_clear()
    s._arrived_at = time.monotonic() - 10
    s.bus = _Capture()
    await s._on_cmd(None, make("cmd.sensors", {"ppg": "start"}, source="hub"))
    await _run_loop(s._ppg_loop(), 2.6)
    got = s.bus.of("raw.sensors.ppg")
    cam = [e for e in got if e.payload.fs_hz < 50]
    ky = [e for e in got if e.payload.fs_hz == 100]
    if mode == "camera":
        assert cam and not ky and all(e.quality == 0.6 for e in cam) and len({e.payload.fs_hz for e in cam}) > 1
        assert s.ppg_active == "camera"
    elif mode == "auto":
        assert ky and cam and got.index(cam[0]) > got.index(ky[-1]) and s.ppg_active == "camera"
    else:
        assert ky and not cam and all(e.quality == 0.9 and len(e.payload.samples) == 25 for e in ky)
        t0 = [e.payload.t0_ms for e in ky]
        assert all(b - a == 250 for a, b in zip(t0, t0[1:], strict=False))  # fixed sample grid
        if mode == "flat":
            assert len({v for e in ky for v in e.payload.samples}) == 1
    with pytest.raises(ValueError):
        SensorsSim(ppg_fixture="guess")


async def test_head_pan_moves_only_on_targets_and_knocks_are_muted_while_moving():
    from kaiku_contracts import make
    head = HeadSim(auto=False, drum="knock", seed=1)
    head.bus = _Capture()
    await head._on_cmd(None, make("cmd.head", {"pan_mode": "track", "eyes": "wide"}, source="hub"))
    assert not head.moving  # pan_mode track/sway are ignored by the firmware: tracking arrives as pan targets
    await head.tap()
    await head.tap()  # 0 ms later: inside the knock debounce
    assert len(head.bus.of("raw.head.tap")) == 1 and head.muted_knocks == 1
    await head._on_cmd(None, make("cmd.head", {"pan": {"target_deg": 200.0, "speed": 1.0}}, source="hub"))
    assert head.target_deg == 80.0 and head.moving  # soft limit +-80 deg
    await asyncio.sleep(0.05)
    await head.tap()
    assert len(head.bus.of("raw.head.tap")) == 1 and head.muted_knocks == 2  # motor vibration: knock ignored
    await _run_loop(head._pan_loop(), 1.2)
    pans = head.bus.of("raw.head.pan")
    assert pans[0].payload.moving and not pans[-1].payload.moving and pans[-1].payload.deg == 80.0
    await head._on_cmd(None, make("cmd.head", {"gesture": "shake"}, source="hub"))
    assert head.target_deg == 0.0  # home after every gesture
