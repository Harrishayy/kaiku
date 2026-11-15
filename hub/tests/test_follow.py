"""Follow mode (D44): a standalone head runs the ritual itself; the hub records it from the head's own messages
(firmware/atech-head/standalone/src/main.cpp + kaiku_net.cpp) and never fights it with cmd.head."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from kaiku_contracts import ContractError, make, parse_topic
from kaiku_hub.follow import HeadFollower, scale_5
from kaiku_hub.live.base import OffMusic, Voice
from kaiku_hub.main import Hub
from kaiku_hub.store import list_sessions, open_readonly, read_session

TS = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)


# ---------------------------------------------------------------- the follower alone (pure)
def emits(actions, type_=None):
    return [a for a in actions if a[0] == "emit" and (type_ is None or a[1] == type_)]


def ritual(actions):
    return [(a[2]["step"], a[2]["status"]) for a in emits(actions, "obs.ritual")]


class Head:
    """Feeds a follower the way the firmware publishes: the press first, then whatever the step change sends."""

    def __init__(self, **kw):
        self.f = HeadFollower(unanswered_gap_s=0, **kw)
        self.now = 100.0
        self.out: list[tuple] = []

    def at(self, dt):
        self.now += dt
        return self

    def health(self, step, status="ok"):
        self.out += (got := self.f.on_health(status, {"step": step, "firmware": "standalone"}, self.now))
        return got

    def chime(self, name):
        self.out += (got := self.f.on_chime(name, self.now))
        return got

    def press(self, value=5, checkin=True):
        """A press of the ear. At the greeting it opens a talk (D66); `checkin` = she then asks for the check-in in
        words and the head goes to its first question (what `cmd.head {ritual: start}` makes it do)."""
        was = self.f.step
        self.out += (got := self.f.on_ear(value, True, TS, self.now))
        if was == "greet" and checkin and self.f.step == "talk":
            self.out += (more := self.f.on_health("ok", {"step": "mood", "firmware": "standalone"}, self.now))
            got = got + more
        return got

    def knocks(self, n, every_ms=500, start=1000):
        return [self.f.on_tap(start + i * every_ms) for i in range(n)]


def test_scale_maps_the_heads_ten_point_dial_onto_the_contract():
    assert [scale_5(v) for v in range(1, 11)] == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    make("obs.self_report", {"item": "mood", "value": 4, "scale_10": 7}, source="hub")
    with pytest.raises(ContractError):
        make("obs.self_report", {"item": "mood", "value": 5, "scale_10": 7}, source="hub")


def test_a_whole_ritual_on_the_head_becomes_the_same_observations():
    h = Head()
    h.health("idle")
    assert h.out == []
    h.chime("wake")                                  # the head greets
    assert h.out == [] and h.f.step == "greet"       # an offer, not a record yet
    h.at(2).press()                                  # person presses: ritual starts on the head
    assert h.out[0] == ("begin", "follow") and h.f.consented
    assert ritual(h.out) == [("greet", "started"), ("greet", "completed"), ("dial", "started")]
    assert h.out[1][4] == pytest.approx(2.0)         # greeting stamped when it happened, 2 s ago
    h.at(3).press(7)                                 # mood 7/10
    h.at(2).press(4)                                 # energy 4/10
    assert not emits(h.out, "obs.self_report")       # held until the head confirms the hub's shadow
    h.at(1).health("sleep")
    reports = [a[2] for a in emits(h.out, "obs.self_report")]
    assert reports == [{"item": "mood", "value": 4, "context": "ritual", "channel": "robot", "scale_10": 7},
                       {"item": "energy", "value": 2, "context": "ritual", "channel": "robot", "scale_10": 4}]
    assert all(a[4] == TS for a in emits(h.out, "obs.self_report"))   # the head's own press time
    h.at(2).press(9)                                 # sleep 9/10 -> breathe
    assert ("sensors", {"ppg": "start"}) in h.out    # asked of the UNO Q; the head never asks
    h.at(60).chime("start_drum")                     # breathing ran its full time
    assert ("sensors", {"ppg": "stop"}) in h.out and h.f.step == "drum"
    assert [a[2]["scale_10"] for a in emits(h.out, "obs.self_report")] == [7, 4, 9]
    assert ("breathe", "completed") in ritual(h.out)
    assert [a for a in h.out if a[0] == "note" and a[1] == "pulse_not_measured"]   # no pulse arrived: not guessed
    assert not emits(h.out, "obs.hrv_session")
    assert all(h.knocks(12))
    h.at(21).chime("end_drum")
    (drum,) = emits(h.out, "obs.drum_session")
    assert drum[2]["taps"] == 12 and drum[2]["tempo_bpm"] == 120 and drum[2]["force_mean"] is None and drum[3] == 1.0
    make("obs.drum_session", drum[2], source="hub", quality=drum[3])
    assert ritual(h.out)[-4:] == [("drum", "started"), ("drum", "completed"), ("close", "started"), ("close", "completed")]
    assert h.out[-1] == ("end", "completed", True, {"mood": 4, "energy": 2, "sleep": 5})
    assert not h.f.active and h.f.step == "done"
    # what the head never asks or sends is never recorded
    assert not [a for a in emits(h.out, "obs.self_report") if a[2]["context"] != "ritual"]
    assert {a[1] for a in emits(h.out)} == {"obs.ritual", "obs.self_report", "obs.drum_session"}
    for a in emits(h.out):
        make(a[1], a[2], source="hub", quality=a[3])
    assert h.at(8).health("idle") == [] and h.press() == []      # goodbye over; a press in idle records nothing


def test_press_skips_breathing_and_ends_drumming_early():
    h = Head()
    h.chime("wake")
    h.press()
    for v in (5, 5, 5):
        h.press(v)
    h.at(3).press()                                   # skip the breathing
    h.chime("start_drum")                             # the head's chime follows its own step change
    assert ("breathe", "skipped") in ritual(h.out)
    h.knocks(3)
    h.at(2).press()                                   # end drumming with 3 knocks: too few for a session
    h.chime("end_drum")
    assert ("drum", "skipped") in ritual(h.out) and not emits(h.out, "obs.drum_session")
    assert [a for a in h.out if a[0] == "note" and a[1] == "drum_not_recorded"]
    assert h.out[-1][:2] == ("end", "completed")


def test_a_lost_press_drops_the_answers_instead_of_relabelling_them():
    h = Head()
    h.chime("wake")
    h.press()
    # the mood press (3) is lost on the Wi-Fi; the hub only receives the energy and sleep presses
    h.press(8)                                        # really energy; the hub's shadow still says mood
    h.press(2)                                        # really sleep
    assert h.f.step == "sleep"
    h.health("breathe")                               # the head disagrees with the hub's shadow
    assert not emits(h.out, "obs.self_report")
    (note,) = [a for a in h.out if a[0] == "note" and a[1] == "dial_unattributed"]
    assert note[2]["items"] == ["mood", "energy"] and h.f.step == "breathe"
    h.chime("start_drum")
    h.knocks(6)
    h.chime("end_drum")
    assert h.out[-1] == ("end", "completed", True, {})   # ritual recorded, dial honestly empty


def test_head_disappearing_mid_drum_is_a_partial_ritual():
    h = Head()
    h.chime("wake")
    h.press()
    h.press(6)
    h.health("energy")                                 # mood confirmed
    h.press(6)
    h.press(6)
    h.chime("start_drum")                              # the chime the hub expected: confirms energy and sleep too
    h.knocks(8)
    assert h.f.tick(h.now + 10) == []
    gone = h.f.tick(h.now + 16)                        # three heartbeats missed
    assert ritual(gone) == [("drum", "aborted")] and not emits(gone, "obs.drum_session")
    assert gone[-1] == ("end", "ended_early", True, {"mood": 3, "energy": 3, "sleep": 3})
    assert [a for a in gone if a[0] == "note" and a[1] == "ritual_cut_short"]
    assert h.f.step is None and not h.f.active
    # last will instead of silence
    h2 = Head()
    h2.chime("wake")
    h2.press()
    down = h2.health("mood", status="down")
    assert ritual(down) == [("dial", "aborted")] and down[-1][:2] == ("end", "ended_early")
    # the head comes back mid-ritual: the rest is recorded, but nobody consented in the hub's sight
    back = h2.health("breathe")
    assert back[0] == ("begin", "follow-joined") and not h2.f.consented


def test_unanswered_greetings_are_recorded_at_most_once_per_gap():
    f = HeadFollower(unanswered_gap_s=3600)
    out = f.on_chime("wake", 0.0) + f.on_health("idle", {"step": "idle"}, 61.0)
    assert ritual(out) == [("greet", "started"), ("greet", "skipped")] and out[-1][:2] == ("end", "skipped")
    assert out[1][4] == pytest.approx(61.0)
    again = f.on_chime("wake", 70.0) + f.on_health("idle", {"step": "idle"}, 131.0)   # the head greets every minute
    assert again == [] and f.unanswered == 2
    later = f.on_chime("wake", 4000.0) + f.on_health("idle", {"step": "idle"}, 4061.0)
    assert ritual(later) == [("greet", "started"), ("greet", "skipped")]


def test_knocks_only_count_in_drum_and_not_while_the_motor_runs():
    h = Head()
    assert h.knocks(2) == [False, False]               # idle: a knock wakes the head, it is not drumming
    h.chime("wake")
    h.press()
    for v in (5, 5, 5):
        h.press(v)
    h.chime("start_drum")
    h.f.on_pan(True)
    assert h.knocks(3) == [False] * 3 and h.f.muted_taps == 3
    h.f.on_pan(False)
    assert all(h.knocks(5, start=5000))


def test_stale_retained_health_and_unknown_steps_are_ignored():
    f = HeadFollower()
    assert f.on_health("ok", {"step": "drum"}, 1.0, age_s=3600) == [] and f.step is None
    assert f.on_health("ok", {"step": "dancing"}, 1.0) == [] and f.on_health("ok", {}, 1.0) == []
    assert f.on_chime("alert", 1.0) == [] and f.on_ear(11, True, None, 1.0) == []
    assert f.on_health("ok", {"step": "done"}, 2.0) == [] and not f.active   # joining at the goodbye is no ritual


# ---------------------------------------------------------------- through the Hub
class QuietVoice(Voice):
    name = "rec"

    async def say(self, text):
        pass

    async def say_verbatim(self, text):
        pass


class Rig:
    def __init__(self, settings, **kw):
        s = settings
        s.greet_s, s.dial_s, s.breathe_s, s.drum_s, s.nudge_s, s.post_mood_s = 0.05, 0.2, 0.1, 0.1, 0.05, 0.05
        s.attention = {**s.attention, "regreet_h": 0}
        for k, v in kw.items():
            setattr(s, k, v)
        self.hub = Hub(s, voice=QuietVoice(), music=OffMusic(), read_stdin=False)
        self.home = self.hub.bus_home
        self.sent: list[tuple[str, dict]] = []
        real = self.hub.bus.publish

        async def publish(type_, payload, **k):
            self.sent.append((type_, dict(payload)))
            return await real(type_, payload, **k)

        self.hub.bus.publish = publish

    async def health(self, step="idle", *, firmware="standalone", status="ok", source="head"):
        details = {"step": step, "rssi": -50, "reconnects": 1}
        if firmware:
            details["firmware"] = firmware
        env = make("health", {"status": status, "version": "x", "uptime_s": 1, "details": details},
                   source=source, home_id=self.home, sim=True)
        await self.hub.on_health(parse_topic(f"kaiku/v1/{self.home}/health/{source}"), env)

    async def raw(self, type_, payload, source="head"):
        env = make(type_, payload, source=source, home_id=self.home, sim=True)
        await self.hub.on_raw(parse_topic(f"kaiku/v1/{self.home}/raw/{type_[4:].replace('.', '/')}"), env)

    async def chime(self, name, source="head"):
        env = make("cmd.sensors", {"chime": name}, source=source, home_id=self.home, sim=True)
        await self.hub.on_sensors_cmd(parse_topic(f"kaiku/v1/{self.home}/cmd/sensors"), env)

    async def press(self, value=5, checkin=True):
        """A press of the ear. At the greeting it opens a talk (D66); `checkin` = she then asks for the check-in and
        the head goes to its first question, as the firmware does on `cmd.head {ritual: start}`."""
        was = self.hub.follower.step
        await self.raw("raw.head.ear", {"value": value, "delta": 0, "pressed": True})
        if was == "greet" and checkin and self.hub.follower.step == "talk":
            await self.health("mood")

    async def whole_ritual(self):
        await self.health("idle")
        await self.chime("wake")
        await self.press()
        for value in (7, 4, 9):
            await self.raw("raw.head.ear", {"value": value, "delta": 1, "pressed": False})
            await self.press(value)
        await self.health("breathe")
        await self.chime("start_drum")
        for i in range(10):
            await self.raw("raw.head.tap", {"t_ms": 2000 + i * 400, "src": "knock"}, source="sensors")
        await self.chime("end_drum")
        await asyncio.sleep(0.05)

    def types(self):
        return [e.type for e in self.hub.emitted]

    def cmds(self, type_="cmd.head"):
        return [p for t, p in self.sent if t == type_]


async def test_hub_follows_a_standalone_head_and_sends_it_nothing(settings):
    r = Rig(settings, home_id="aino", robot_home_id="demo-aino")
    hub = r.hub
    assert not hub.following and hub.bus_home == "demo-aino"
    await r.health("idle")
    assert hub.following
    await r.raw("raw.hub.face", {"x_norm": 0.0, "y_norm": 0.0, "size": 0.3, "confidence": 0.9}, source="sensors")
    for _ in range(3):
        await hub.attention_step()                      # the hub's own reflexes stay quiet: the head greets itself
    assert hub.start_ritual("button") is False and not hub.machine.running
    await r.whole_ritual()
    assert r.cmds() == []                               # no cmd.head at all during the head's ritual
    await hub.head(eyes="wide", pan={"target_deg": 20.0})   # anything in the hub that tries is held back
    assert r.cmds() == [] and hub.head_cmds_held == 1
    assert r.cmds("cmd.sensors") == [{"ppg": "start"}, {"ppg": "stop"}]
    t = r.types()
    assert t.count("obs.self_report") == 3 and t.count("obs.drum_session") == 1 and t.count("obs.engagement") == 1
    assert "obs.hrv_session" not in t and "obs.intervention_response" not in t and "obs.nudge_offered" not in t
    reports = {e.payload.item: (e.payload.value, e.payload.scale_10, e.payload.context)
               for e in hub.emitted if e.type == "obs.self_report"}
    assert reports == {"mood": (4, 7, "ritual"), "energy": (2, 4, "ritual"), "sleep": (5, 9, "ritual")}
    steps = [(e.payload.step, e.payload.status) for e in hub.emitted if e.type == "obs.ritual"]
    assert steps == [("greet", "started"), ("greet", "completed"), ("dial", "started"), ("dial", "completed"),
                     ("breathe", "started"), ("breathe", "completed"), ("drum", "started"), ("drum", "completed"),
                     ("close", "started"), ("close", "completed")]
    # every observation is the person's record ("aino"), flagged sim, and queued for the cloud before anything else
    assert all(e.home_id == "aino" and e.sim for e in hub.emitted) and hub.uplink.size() == len(hub.emitted)
    eng = next(e for e in hub.emitted if e.type == "obs.engagement").payload
    cues = {c.cue: c for c in eng.cues}
    assert cues["dial"].available and cues["drum"].available and not cues["pulse"].available
    assert hub.episodes.size() == 1 and hub.state.today_mood(datetime.now().astimezone().date()) == 4
    hub.store.flush()
    db = open_readonly(settings.store_path)
    (session,) = list_sessions(db)
    _s, samples, linked = read_session(db, session["id"])
    assert session["outcome"] == "completed" and session["reason"] == "follow" and session["home_id"] == "aino"
    assert sum(x["type"] == "raw.head.tap" for x in samples) == 10 and sum(x["type"] == "raw.head.ear" for x in samples) == 7
    assert {o["id"] for o in linked} == {str(e.id) for e in hub.emitted}
    assert session["summary"]["notes"]["pulse_not_measured"]["reason"] == "no signal"


async def test_a_press_outside_a_dial_step_is_not_an_answer(settings):
    r = Rig(settings)
    await r.health("idle")
    await r.press(9)                                    # idle press: the head wakes; 9 is a stale dial value
    await r.chime("wake")
    assert r.types() == []
    await r.health("idle")                              # greeting timed out; recorded as an unanswered offer
    assert [(e.payload.step, e.payload.status) for e in r.hub.emitted] == [("greet", "started"), ("greet", "skipped")]
    assert "obs.self_report" not in r.types() and "obs.engagement" not in r.types()


@pytest.mark.parametrize("firmware", [None, "kaiku_link"])
async def test_falls_back_to_driving_the_ritual_for_the_mqtt_firmware_and_the_sim_head(settings, firmware):
    r = Rig(settings)
    await r.health("idle", firmware=firmware)
    hub = r.hub
    assert not hub.following and hub.head_firmware == "mqtt"
    await r.press(4)                                    # drive mode: an idle ear press is the ad-hoc mood (1-5)
    assert r.types() == ["obs.self_report"] and hub.emitted[0].payload.context == "adhoc"
    assert hub.start_ritual("test") is True
    await asyncio.sleep(0.1)
    assert r.cmds() and any(c.get("eyes") for c in r.cmds())   # the hub drives the head again
    await hub.end_ritual()


async def test_head_mode_switch_overrides_auto(settings):
    drive = Rig(settings, head_mode="drive")
    await drive.health("mood")
    assert not drive.hub.following and drive.types() == []
    follow = Rig(settings, head_mode="follow")
    assert follow.hub.following and follow.hub.start_ritual("button") is False
    await follow.health("idle", firmware=None)          # forced: follows even a head that doesn't say standalone
    assert follow.hub.following


async def test_standalone_head_appearing_ends_a_hub_driven_ritual_and_changing_back_closes_the_record(settings):
    r = Rig(settings)
    hub = r.hub
    assert hub.start_ritual("test")
    await asyncio.sleep(0.02)
    await r.health("idle")                              # the standalone head comes up: never two rituals at once
    assert hub.following and not hub.machine.running
    await r.chime("wake")
    await r.press()
    assert hub.follower.active
    await r.health("idle", firmware=None)               # reflashed with the MQTT firmware mid-ritual
    assert not hub.following and not hub.follower.active
    assert ("dial", "aborted") in [(e.payload.step, e.payload.status) for e in hub.emitted if e.type == "obs.ritual"]


async def test_head_lost_mid_ritual_records_the_partial_ritual(settings):
    r = Rig(settings)
    hub = r.hub
    await r.health("idle")
    await r.chime("wake")
    await r.press()
    await r.press(8)
    await r.health("energy")
    await r.health("energy", status="down")             # the head's last will
    steps = [(e.payload.step, e.payload.status) for e in hub.emitted if e.type == "obs.ritual"]
    assert steps == [("greet", "started"), ("greet", "completed"), ("dial", "started"), ("dial", "aborted")]
    assert [(e.payload.item, e.payload.scale_10) for e in hub.emitted if e.type == "obs.self_report"] == [("mood", 8)]
    hub.store.flush()
    (session,) = list_sessions(open_readonly(settings.store_path))
    assert session["outcome"] == "ended_early" and "ritual_cut_short" in session["summary"]["notes"]
    assert hub.following and hub.start_ritual("button") is False   # a dead standalone head is not driven either
    # silence instead of a last will
    r2 = Rig(settings)
    await r2.health("idle")
    await r2.chime("wake")
    await r2.press()
    r2.hub.follower.last_health -= 20
    await r2.hub.attention_step()
    assert ("dial", "aborted") in [(e.payload.step, e.payload.status) for e in r2.hub.emitted if e.type == "obs.ritual"]


async def test_crisis_in_follow_mode_stops_the_record_and_only_calms_the_eyes(settings):
    r = Rig(settings)
    hub = r.hub
    await r.health("idle")
    await r.chime("wake")
    await r.press()
    await hub.on_utterance("I want to die")
    assert r.types().count("obs.safety_flag") == 1 and "obs.engagement" not in r.types()
    # the two commands a standalone head takes without fighting: calm eyes, then its help screen (the helpline's
    # numbers from its own firmware; never a sound)
    assert r.cmds() == [{"eyes": "soft"}, {"show": "help"}]
    await r.press(6)                                    # the head goes on by itself: nothing more is recorded
    await r.health("energy")
    assert "obs.self_report" not in r.types() and not hub.follower.active
    hub.store.flush()
    (session,) = list_sessions(open_readonly(settings.store_path))
    assert session["outcome"] == "crisis"


async def test_a_head_on_another_home_is_reported_once(settings, caplog):
    r = Rig(settings, home_id="aino")
    env = make("health", {"status": "ok", "version": "x", "uptime_s": 1, "details": {"firmware": "standalone"}},
               source="head", home_id="demo-aino")
    for _ in range(2):
        await r.hub.on_any_head(parse_topic("kaiku/v1/demo-aino/health/head"), env)
    assert caplog.text.count("KAIKU_HUB_ROBOT_HOME_ID=demo-aino") == 1 and not r.hub.following


def test_health_ts_far_in_the_past_is_not_the_present(settings):
    f = HeadFollower()
    assert f.on_health("ok", {"step": "mood"}, 5.0, age_s=(timedelta(hours=2)).total_seconds()) == []
