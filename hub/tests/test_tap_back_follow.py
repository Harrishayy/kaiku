"""Tap it back while the hub FOLLOWS a head that runs its own ritual (D44 + D51): `cmd.head {drum: hold | end}`, taps
from either board counted once, and the fall back to simply following the head's free drumming."""

import asyncio
from datetime import UTC, datetime

import pytest
from kaiku_contracts import make, parse_topic
from kaiku_hub.follow import HeadFollower
from kaiku_hub.live.base import OffMusic, Voice
from kaiku_hub.main import Hub
from kaiku_hub.perception.tap_back import TapBackConfig
from kaiku_hub.rituals import tap_back
from kaiku_hub.safety import Trigger

from hub.tests.fakes import Songs

TS = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def quick_game(monkeypatch):
    monkeypatch.setattr(tap_back, "FADE_OUT_S", 0.0)
    monkeypatch.setattr(tap_back, "TICK_S", 0.01)


def quick(**over) -> TapBackConfig:
    base = dict(mode="auto", listen_s=0.06, replay_listen_s=0.04, song_wait_s=0.15, first_tap_s=0.3, idle_end_s=0.15,
                turn_s=1.0, cue_clear_s=0.0, result_s=0.02, word_s=0.0, max_s=20.0, level_vary_bpm=(0, 0, 0),
                hold_every_s=0.05)
    return TapBackConfig.from_dict({**base, **over})


# ------------------------------------------------------------------------------------------ the follower alone
def to_drum(f: HeadFollower, now: float = 100.0) -> list:
    out = f.on_health("ok", {"step": "idle", "firmware": "standalone"}, now)
    out += f.on_chime("wake", now)
    out += f.on_ear(5, True, TS, now + 1)
    for i, v in enumerate((7, 4, 9)):
        out += f.on_ear(v, True, TS, now + 2 + i)
    out += f.on_chime("start_drum", now + 10)
    return out


def test_the_follower_offers_the_drum_step_and_keeps_her_given_tempo_out_of_a_drum_session():
    f = HeadFollower(unanswered_gap_s=0)
    out = to_drum(f)
    assert ("drum_open",) in out and f.step == "drum" and not f.game
    assert f.on_tap(1000) and f.on_tap(1500)             # free drumming until the hub says a game runs
    f.game_started()
    assert [f.on_tap(2000 + i * 500) for i in range(8)] == [False] * 8   # the game's taps are not the follower's
    f.game_levels = 2
    done = f.on_chime("end_drum", 150.0)
    assert done[0] == ("game_end", True)                 # first: the game's record comes before the step's closing line
    assert not [a for a in done if a[0] == "emit" and a[1] == "obs.drum_session"]
    assert [(a[2]["step"], a[2]["status"]) for a in done if a[0] == "emit" and a[1] == "obs.ritual"][0] == ("drum", "completed")
    assert not f.game


def test_a_game_nobody_tapped_in_is_a_skipped_drum_step_and_a_lost_head_records_nothing():
    f = HeadFollower(unanswered_gap_s=0)
    to_drum(f)
    f.game_started()
    done = f.on_chime("end_drum", 150.0)
    assert done[0] == ("game_end", True)
    assert ("drum", "skipped") in [(a[2]["step"], a[2]["status"]) for a in done if a[0] == "emit" and a[1] == "obs.ritual"]
    f = HeadFollower(unanswered_gap_s=0)
    to_drum(f)
    f.game_started()
    f.game_levels = 1
    gone = f.lost(160.0, "head reported down")
    assert gone[0] == ("game_end", False)                # an aborted step records nothing, as with a drum session
    assert ("drum", "aborted") in [(a[2]["step"], a[2]["status"]) for a in gone if a[0] == "emit" and a[1] == "obs.ritual"]


def test_free_drumming_before_and_no_game_is_exactly_as_before():
    f = HeadFollower(unanswered_gap_s=0)
    to_drum(f)
    for i in range(8):
        f.on_tap(1000 + i * 500)
    done = f.on_chime("end_drum", 150.0)
    assert not [a for a in done if a[0] == "game_end"]
    assert [a[1] for a in done if a[0] == "emit"][:2] == ["obs.drum_session", "obs.ritual"]


# ------------------------------------------------------------------------------------------- through the Hub
class QuietVoice(Voice):
    name = "rec"

    def __init__(self):
        self.said: list[str] = []

    async def say(self, text):
        self.said.append(text)

    async def say_verbatim(self, text):
        pass


class Rig:
    def __init__(self, settings, music=None, **cfg):
        s = settings
        s.attention = {**s.attention, "regreet_h": 0}
        s.tap_back = quick(**cfg)
        self.music = music if music is not None else Songs()
        self.hub = Hub(s, voice=QuietVoice(), music=self.music, read_stdin=False)
        self.home = self.hub.bus_home
        self.sent: list[tuple[str, dict]] = []
        self.t_ms = 10_000
        real = self.hub.bus.publish

        async def publish(type_, payload, **k):
            self.sent.append((type_, dict(payload)))
            return await real(type_, payload, **k)

        self.hub.bus.publish = publish

    async def health(self, step="idle", status="ok"):
        env = make("health", {"status": status, "version": "x", "uptime_s": 1,
                              "details": {"step": step, "firmware": "standalone", "drum_held": False}},
                   source="head", home_id=self.home, sim=True)
        await self.hub.on_health(parse_topic(f"kaiku/v1/{self.home}/health/head"), env)

    async def raw(self, type_, payload, source="head"):
        env = make(type_, payload, source=source, home_id=self.home, sim=True)
        await self.hub.on_raw(parse_topic(f"kaiku/v1/{self.home}/raw/{type_[4:].replace('.', '/')}"), env)

    async def chime(self, name):
        env = make("cmd.sensors", {"chime": name}, source="head", home_id=self.home, sim=True)
        await self.hub.on_sensors_cmd(parse_topic(f"kaiku/v1/{self.home}/cmd/sensors"), env)

    async def to_drum(self):
        await self.health("idle")
        await self.chime("wake")
        await self.raw("raw.head.ear", {"value": 5, "delta": 0, "pressed": True})
        for v in (7, 4, 9):
            await self.raw("raw.head.ear", {"value": v, "delta": 0, "pressed": True})
        await self.health("breathe")
        await self.chime("start_drum")

    def heads(self):
        return [p for t, p in self.sent if t == "cmd.head"]

    async def wait_for(self, what, timeout=3.0):
        for _ in range(int(timeout / 0.005)):
            if what():
                return True
            await asyncio.sleep(0.005)
        return False

    async def play(self, errors, both_boards=False):
        """The person: on every "your turn" (wide eyes) tap the tempo the head showed, until the band's face."""
        seen = turn = 0
        bpm = 0.0
        while self.hub._game is not None or seen == 0:
            heads = self.heads()
            while seen < len(heads):
                cmd = heads[seen]
                seen += 1
                bpm = cmd.get("bpm") or bpm
                if cmd.get("eyes") == "wide":
                    err = errors[min(turn, len(errors) - 1)]
                    turn += 1
                    for _ in range(20):
                        if any(h.get("eyes") for h in self.heads()[seen:]) or self.hub._game is None:
                            break  # the band's face (a bare `hold` in between is not one)
                        await self.raw("raw.head.tap", {"t_ms": int(self.t_ms), "src": "knock"}, source="sensors")
                        if both_boards:  # the head's motion sensor feels the same tap, on its own clock
                            await self.raw("raw.head.tap", {"t_ms": int(self.t_ms) + 7_000_000, "force": 1.8, "src": "imu"})
                        self.t_ms += 60000 / (bpm * (1 + err))
                        await asyncio.sleep(60 / bpm / 40)
                    self.t_ms += 5000
            await asyncio.sleep(0.005)

    def steps(self):
        return [(e.payload.step, e.payload.status) for e in self.hub.emitted if e.type == "obs.ritual"]


async def test_the_hub_holds_the_heads_drum_step_plays_the_game_and_gives_it_back(settings):
    r = Rig(settings)
    hub = r.hub
    await r.to_drum()
    assert await r.wait_for(lambda: hub._game is not None)
    assert r.music.calls[:2] == ["start", "hush"] and hub.follower.game
    await asyncio.wait_for(r.play([0.01, 0.07, 0.02], both_boards=True), 8)
    assert await r.wait_for(lambda: r.heads() and r.heads()[-1].get("drum") == "end")

    heads = r.heads()
    assert all("drum" in h for h in heads)                # the only cmd.head a self-running head ever gets from the hub
    assert heads[-1] == {"drum": "end", "pan_mode": "still"} and all(h["drum"] == "hold" for h in heads[:-1])
    levels = hub._tasks and tap_back.level_plan(datetime.now().astimezone().date(), settings.tap_back)
    listen = [h for h in heads if h.get("chest") == "pulse"]
    assert [h["bpm"] for h in listen] == [float(lv.bpm) for lv in levels]
    assert all(h["eyes"] == "soft" and h["pan_mode"] == "sway" for h in listen)   # the standalone's calm face: its
    assert heads[0]["drum"] == "hold"                     # wide eyes are kept for "your turn"
    assert sum(h.get("eyes") == "wide" and h.get("pan_mode") == "still" for h in heads) == 3
    assert {"drum": "hold"} in heads                      # the bare one that keeps the head held between the others
    chimes = [p["chime"] for t, p in r.sent if t == "cmd.sensors" and "chime" in p]
    assert chimes == ["start_drum", "ok"] * 3             # "your turn" and the band on the UNO Q's buzzer too

    (obs,) = [e for e in hub.emitted if e.type == "obs.tap_back"]
    p = obs.payload
    assert [(lv.band, lv.taps) for lv in p.levels] == [("perfect", 8), ("great", 8), ("perfect", 12)]
    assert p.levels_passed == 3 and p.taps == 28 and p.rejected_taps == 0   # two boards, every tap counted once
    assert obs.home_id == settings.home_id and "stop" in r.music.calls
    assert hub.voice.said[0] == tap_back.INTRO["music"] and hub.voice.said[-1].startswith("Three songs")
    assert hub._game is None

    await r.chime("end_drum")                             # the head obeys `end` and leaves its drum step
    await asyncio.sleep(0.02)
    types = [e.type for e in hub.emitted]
    assert "obs.drum_session" not in types and types.count("obs.tap_back") == 1
    assert r.steps()[-4:] == [("drum", "started"), ("drum", "completed"), ("close", "started"), ("close", "completed")]
    assert types.index("obs.tap_back") < len(types) - 1 - types[::-1].index("obs.ritual")
    hub.store.flush()


async def test_no_song_no_game_the_head_drums_freely_and_gets_no_command(settings):
    for music, mode in ((OffMusic(), "auto"), (Songs(generated=False, kind="beat"), "auto"), (Songs(), "free")):
        r = Rig(settings, music=music, mode=mode)
        await r.to_drum()
        await asyncio.sleep(0.05)
        assert r.hub._game is None and r.heads() == []    # nothing is sent: the head's own drum step, as before
        for i in range(10):
            await r.raw("raw.head.tap", {"t_ms": 2000 + i * 400, "src": "knock"}, source="sensors")
        await r.chime("end_drum")
        await asyncio.sleep(0.02)
        types = [e.type for e in r.hub.emitted]
        assert types.count("obs.drum_session") == 1 and "obs.tap_back" not in types
        r.hub.store.flush()


async def test_the_head_leaves_its_drum_step_mid_game_what_was_played_is_kept(settings):
    r = Rig(settings)
    hub = r.hub
    await r.to_drum()
    player = asyncio.create_task(r.play([0.0]))
    assert await r.wait_for(lambda: hub.follower.game_levels >= 1)
    await r.chime("end_drum")                             # a knob press ended the drum on the head (or its own timer did)
    await asyncio.sleep(0.03)
    player.cancel()
    assert hub._game is None and "stop" in r.music.calls
    assert not any(h.get("drum") == "end" for h in r.heads())   # the head already went on: nothing to tell it
    types = [e.type for e in hub.emitted]
    assert types.count("obs.tap_back") == 1 and "obs.drum_session" not in types
    p = next(e for e in hub.emitted if e.type == "obs.tap_back").payload
    assert 1 <= p.levels_played <= 2 and p.levels[0].band == "perfect"
    assert ("drum", "completed") in r.steps()
    assert types.index("obs.tap_back") < [i for i, e in enumerate(hub.emitted)
                                          if e.type == "obs.ritual" and e.payload.step == "drum"][-1]
    hub.store.flush()


async def test_the_song_never_comes_the_hub_lets_go_and_follows_free_drumming(settings):
    r = Rig(settings, music=Songs(silent_from=1))
    hub = r.hub
    await r.to_drum()
    assert await r.wait_for(lambda: hub._game is not None)
    assert await r.wait_for(lambda: hub._game is None)    # song_wait_s passed with no sound
    assert not hub.follower.game and "stop" in r.music.calls
    held = len(r.heads())
    await asyncio.sleep(0.15)
    assert len(r.heads()) == held and not any(h.get("drum") == "end" for h in r.heads())   # no more `hold`: the head's timer
    for i in range(10):
        await r.raw("raw.head.tap", {"t_ms": 2000 + i * 400, "src": "knock"}, source="sensors")
    await r.chime("end_drum")
    await asyncio.sleep(0.02)
    types = [e.type for e in hub.emitted]
    assert types.count("obs.drum_session") == 1 and "obs.tap_back" not in types
    assert tap_back.CUE not in hub.voice.said
    hub.store.flush()


async def test_taps_while_the_head_sways_are_not_hers(settings):
    r = Rig(settings, listen_s=5.0)
    hub = r.hub
    await r.to_drum()
    assert await r.wait_for(lambda: hub._game is not None and hub._game.state == "listen")
    await r.raw("raw.head.pan", {"deg": 0, "homed": True, "moving": True})
    for i in range(5):
        await r.raw("raw.head.tap", {"t_ms": 1000 + i * 300, "force": 1.0, "src": "imu"})
    assert hub._game.early_taps == 0 and hub._game.taps.count == 0      # not even looked at while the motor runs
    await r.raw("raw.head.pan", {"deg": 0, "homed": True, "moving": False})
    await r.raw("raw.head.tap", {"t_ms": 9000, "force": 1.0, "src": "imu"})
    assert hub._game.early_taps == 1 and hub._game.taps.count == 0      # still the song: not counted
    await hub.stop()


async def test_a_crisis_ends_the_game_gives_the_head_its_step_back_and_records_nothing(settings):
    r = Rig(settings)
    hub = r.hub
    await r.to_drum()
    player = asyncio.create_task(r.play([0.0]))
    assert await r.wait_for(lambda: hub.follower.game_levels >= 1)
    await hub.crisis(Trigger("manual", "button", "en"))
    player.cancel()
    await asyncio.sleep(0.03)
    assert hub._game is None and "stop" in r.music.calls
    # one message gives the head its step back AND shows the help screen: the standalone firmware then drops the
    # drum end silently (no end chime, no "done" screen before the helpline's numbers); then its eyes are calmed
    assert r.heads()[-2:] == [{"drum": "end", "pan_mode": "still", "show": "help"}, {"eyes": "soft"}]
    assert [h for h in r.heads() if "show" in h] == [r.heads()[-2]]   # the help screen is asked for once
    types = [e.type for e in hub.emitted]
    assert "obs.tap_back" not in types and types[-1] == "obs.safety_flag"
    hub.store.flush()


async def test_two_boards_feeling_one_tap_do_not_double_free_drumming_either(settings):
    """Follow mode, no game: the UNO Q's knock and the head's own motion sensor both report every tap."""
    r = Rig(settings, music=OffMusic())
    await r.to_drum()
    for i in range(12):
        await r.raw("raw.head.tap", {"t_ms": 2000 + i * 500, "src": "knock"}, source="sensors")
        await r.raw("raw.head.tap", {"t_ms": 9_000_000 + i * 500, "force": 2.0, "src": "imu"})
    await r.chime("end_drum")
    await asyncio.sleep(0.02)
    d = next(e for e in r.hub.emitted if e.type == "obs.drum_session").payload
    assert d.taps == 12 and d.tempo_bpm == pytest.approx(120) and r.hub.tap_source.dropped == 12
    r.hub.store.flush()


async def test_the_hub_driven_drum_step_counts_one_tap_from_two_boards_once(settings):
    settings.drum_s, settings.drum_idle_end_s, settings.post_mood_s, settings.greet_s = 2, 0.2, 0.05, 0.05
    settings.dial_s, settings.breathe_s, settings.nudge_s = 0.05, 0.05, 0.05
    hub = Hub(settings, voice=QuietVoice(), music=OffMusic(), read_stdin=False)

    async def raw(payload, source):
        env = make("raw.head.tap", payload, source=source, home_id=hub.bus_home, sim=True)
        await hub.on_raw(parse_topic(f"kaiku/v1/{hub.bus_home}/raw/head/tap"), env)

    hub.start_ritual("test")
    for _ in range(400):
        if hub.machine.state == "drum":
            break
        await asyncio.sleep(0.005)
    await asyncio.sleep(0.02)
    for i in range(10):
        await raw({"t_ms": 2000 + i * 600, "src": "knock"}, "sensors")
        await raw({"t_ms": 8_000_000 + i * 600, "force": 2.0, "src": "imu"}, "head")
        await asyncio.sleep(0.005)
    for _ in range(400):
        if any(e.type == "obs.drum_session" for e in hub.emitted):
            break
        await asyncio.sleep(0.005)
    d = next(e for e in hub.emitted if e.type == "obs.drum_session").payload
    assert d.taps == 10 and d.tempo_bpm == pytest.approx(100)
    await hub.end_ritual()
    hub.store.flush()
