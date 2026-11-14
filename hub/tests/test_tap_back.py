"""Tap it back (D51): the numbers (bands, the day's levels), the words, and the whole flow of the drum step on fakes."""

import asyncio
import time
from datetime import date, timedelta

import pytest
from kaiku_contracts import wording
from kaiku_contracts.config import load_config
from kaiku_hub.live.base import Music
from kaiku_hub.perception.tap_back import (
    BANDS,
    LevelResult,
    OneTapSource,
    TapBackConfig,
    Try,
    band_of,
    better,
    level_plan,
    payload,
    score_try,
)
from kaiku_hub.rituals import Event, RitualMachine, tap_back
from kaiku_hub.rituals.steps import POST_MOOD_LINE, Drum

from hub.tests.fakes import Songs

DAY = date(2026, 11, 14)


def taps_at(bpm: float, n: int, start: int = 1000, jitter: tuple[int, ...] = (0,)) -> list[int]:
    gap = 60000 / bpm
    return [int(round(start + i * gap + jitter[i % len(jitter)])) for i in range(n)]


def quick(**over) -> TapBackConfig:
    """The game's config with every wait shrunk, so a whole game takes well under a second."""
    base = dict(mode="tap_back", listen_s=0.06, replay_listen_s=0.04, song_wait_s=0.15, first_tap_s=0.25,
                idle_end_s=0.12, turn_s=1.0, cue_clear_s=0.0, result_s=0.02, word_s=0.0, max_s=20.0,
                level_vary_bpm=(0, 0, 0))
    return TapBackConfig.from_dict({**base, **over})


# ------------------------------------------------------------------------------------------------ the numbers
def test_bands_and_their_edges():
    cfg = TapBackConfig()
    assert [band_of(e, 0.95, cfg) for e in (0.0, 4.0, 4.1, 8.0, 8.1, 15.0, 15.1, 60.0)] == [
        "perfect", "perfect", "great", "great", "nice", "nice", "again", "again"]
    # the tempo fits but the taps wander: one band lower, and never below nice for that
    assert [band_of(e, 0.5, cfg) for e in (2.0, 6.0, 12.0, 20.0)] == ["great", "nice", "nice", "again"]
    assert band_of(2.0, cfg.steady_min, cfg) == "perfect"


def test_a_try_is_scored_by_the_tempo_of_the_taps():
    cfg = TapBackConfig()
    exact = score_try(100, taps_at(100, 8), cfg)
    assert (exact.tapped_bpm, exact.error_pct, exact.band, exact.beat) == (100.0, 0.0, "perfect", "beat")
    assert exact.steadiness == pytest.approx(1.0)
    assert score_try(100, taps_at(102, 8), cfg).band == "perfect"          # 2 % fast
    seven = score_try(126, taps_at(126 * 1.07, 8), cfg)
    assert seven.band == "great" and seven.error_pct == pytest.approx(7.0, abs=0.4)
    assert score_try(76, taps_at(76 * 1.12, 12), cfg).band == "nice"
    far = score_try(76, taps_at(76 * 1.22, 12), cfg)
    assert far.band == "again" and far.error_pct == pytest.approx(22, abs=0.6) and far.measured
    slow = score_try(100, taps_at(93, 8), cfg)                              # slower counts like faster
    assert slow.band == "great" and slow.tapped_bpm == pytest.approx(93, abs=0.2)


def test_the_median_gap_decides_so_one_stumble_does_not():
    cfg = TapBackConfig()
    times = taps_at(100, 9)
    times[4] += 150                                                         # one late tap
    r = score_try(100, times, cfg)
    assert r.tapped_bpm == pytest.approx(100, abs=0.5) and r.error_pct < 1
    assert r.steadiness >= cfg.steady_min and r.band == "perfect"           # one stumble is forgiven
    wandering = score_try(100, taps_at(100, 9, jitter=(0, 110, -20, 90, 0, -100)), cfg)
    assert wandering.error_pct <= cfg.great_pct and wandering.steadiness < cfg.steady_min
    assert wandering.band == BANDS[BANDS.index(band_of(wandering.error_pct, 1.0, cfg)) + 1]   # the gate: one band lower


def test_too_few_taps_give_no_tempo_and_no_made_up_number():
    cfg = TapBackConfig()
    for times in ([], [1000], taps_at(100, 3), [1000, 5000, 9000, 13000]):  # the last: four taps, every gap a pause
        r = score_try(100, times, cfg)
        assert not r.measured and r.band == "again" and r.error_pct is None and r.steadiness is None
    assert score_try(100, taps_at(100, 4), cfg).measured


def test_every_other_beat_or_two_to_a_beat_is_in_time():
    cfg = TapBackConfig()
    half = score_try(126, taps_at(63, 8), cfg)
    assert (half.band, half.beat, half.tapped_bpm) == ("perfect", "half", 63.0)
    assert score_try(76, taps_at(152, 12), cfg).beat == "double"
    strict = TapBackConfig(half_double=False)
    assert score_try(126, taps_at(63, 8), strict).band == "again"


def test_the_days_levels_are_the_same_on_a_rerun_and_different_the_next_day():
    cfg = TapBackConfig()
    today = level_plan(DAY, cfg)
    assert today == level_plan(DAY, cfg) and [lv.number for lv in today] == [1, 2, 3]
    assert [lv.taps for lv in today] == [8, 8, 12]
    for d in range(60):
        a, b = level_plan(DAY + timedelta(days=d), cfg), level_plan(DAY + timedelta(days=d + 1), cfg)
        assert all(x.bpm != y.bpm for x, y in zip(a, b, strict=True))       # every level moves every day
        for lv, mid, vary in zip(a, cfg.level_bpm, cfg.level_vary_bpm, strict=True):
            assert abs(lv.bpm - mid) <= vary
        assert a[1].bpm > a[0].bpm > a[2].bpm                               # faster, then slow: harder each level
    assert len({level_plan(DAY + timedelta(days=d), cfg)[0].bpm for d in range(13)}) == 13   # all 13 tempos come up


def test_levels_stay_inside_the_tempo_range_the_music_can_play():
    cfg = TapBackConfig.from_dict({"level_bpm": [58, 205, 76], "level_vary_bpm": [0, 0, 0]}, bpm_min=60, bpm_max=200)
    assert [lv.bpm for lv in level_plan(DAY, cfg)] == [60, 200, 76]


def test_config_values_are_read_and_a_bad_one_keeps_its_default():
    cfg = TapBackConfig.from_dict({"mode": "nonsense", "listen_s": "ten", "level_bpm": [90, 120], "retries": 2,
                                   "level_taps": [6, 6, 10], "half_double": False})
    assert cfg.mode == "auto" and cfg.listen_s == 8.0 and cfg.retries == 2 and cfg.half_double is False
    assert cfg.level_bpm == (90.0, 120.0) and cfg.level_taps == (6, 6) and cfg.level_vary_bpm == (6.0, 8.0)
    file = TapBackConfig.from_dict(load_config()["tap_back"])
    assert file.mode == "auto" and len(file.level_bpm) == 3 and file.perfect_pct < file.great_pct < file.nice_pct


def test_the_closer_try_counts_and_the_record_is_what_was_measured():
    again, good = Try(8, 92.0, 22.0, 0.95, "again"), Try(8, 78.3, 3.0, 0.96, "perfect")
    assert better(again, good) is good and better(good, again) is good
    assert better(Try(8, 92.0, 22.0, 0.9, "again"), Try(8, 95.0, 25.0, 0.9, "again")).error_pct == 22.0
    levels = level_plan(DAY, TapBackConfig())
    results = [LevelResult(levels[0], [Try(8, 101.0, 1.0, 0.97, "perfect")]),
               LevelResult(levels[1], [Try(8, 135.0, 7.0, 0.93, "great", rejected=1)]),
               LevelResult(levels[2], [again, good])]
    body, quality = payload(results, 71.26, "music")
    assert (body["levels_played"], body["levels_passed"], body["taps"], body["rejected_taps"]) == (3, 3, 32, 1)
    assert body["error_pct"] == pytest.approx((1 + 7 + 3) / 3, abs=0.06) and body["duration_s"] == 71.3
    assert [(lv["band"], lv["tries"]) for lv in body["levels"]] == [("perfect", 1), ("great", 1), ("perfect", 2)]
    assert quality == pytest.approx(32 / 33, abs=0.001) and body["song"] == "music"
    assert payload([LevelResult(levels[0], [Try(2)])], 5, "") is None           # nothing measured: nothing recorded
    part, _q = payload([LevelResult(levels[0], [Try(2), Try(1)]), LevelResult(levels[1], [good])], 30, "")
    assert part["levels"][0] == {"level": 1, "target_bpm": float(levels[0].bpm), "taps": 2, "band": "again",
                                 "tries": 2, "beat": "beat"} and part["song"] == "light" and part["levels_passed"] == 1


def test_one_tap_felt_by_two_boards_is_counted_once():
    """The knock switch and the head's motion sensor both report a tap, each on its own clock."""
    src = OneTapSource(hold_s=3.0)
    kept = []
    for i in range(6):
        now = 10.0 + i * 0.5
        kept.append((src.accept("sensors/knock", now), src.accept("head/imu", now + 0.004)))
    assert kept == [(True, False)] * 6 and src.dropped == 6
    assert src.accept("head/imu", 20.0)                                     # the first one fell silent: the other takes over
    assert not src.accept("sensors/knock", 20.5) and src.accept("head/imu", 21.0)


# -------------------------------------------------------------------------------------------------- the words
def test_every_line_passes_the_wording_rules_for_the_robot():
    import tomllib

    from kaiku_contracts.config import find_repo_file

    robot = tomllib.loads(find_repo_file("config/surfaces.toml").read_text())["surface"]["robot"]
    lines = tap_back.all_lines()
    assert len(lines) > 20
    for line in lines:
        assert wording.lint_for_surface(line, robot) == [], line
        assert not any(ch.isdigit() for ch in line), line                   # a band is a word; no number is ever said
    for harsh in ("wrong", "fail", "bad", "missed", "lost the", "no good", "should", "try harder", "oh no"):
        assert not any(harsh in line.lower() for line in lines if line != tap_back.FALLBACK_LINE), harsh


def test_the_closing_line_names_how_it_went():
    assert tap_back.close_line(3, 3) == "Three songs, and you found the beat in every one."
    assert tap_back.close_line(3, 2) == "Three songs, and you found the beat in two of them."
    assert tap_back.close_line(3, 1) == "Three songs, and you found the beat in one of them."
    assert "tricky" in tap_back.close_line(3, 0) and "Thank you" in tap_back.close_line(3, 0)
    assert tap_back.close_line(1, 1) == "One song, and you found its beat."


# ----------------------------------------------------------------------------------------------- the whole flow
@pytest.fixture(autouse=True)
def no_fade_wait(monkeypatch):
    monkeypatch.setattr(tap_back, "FADE_OUT_S", 0.0)
    monkeypatch.setattr(tap_back, "TICK_S", 0.01)


class Player:
    """Someone at the robot: when the eyes go wide ("your turn") they tap the tempo the head just showed (the `bpm`
    of its listening face), off by the next entry of `errors` (None = they do not tap at all that turn), and stop
    when the band's face comes."""

    def __init__(self, ctx, machine, errors, taps: int = 20, speed: float = 40.0):
        self.ctx, self.m, self.errors, self.n, self.speed = ctx, machine, list(errors), taps, speed
        self.turn = 0
        self.t_ms = 10_000
        self._seen = 0
        self.bpm = 0.0

    async def run(self):
        while self.m.running or self._seen == 0:
            heads = self.ctx.heads
            while self._seen < len(heads):
                cmd = heads[self._seen]
                self._seen += 1
                if cmd.get("bpm"):
                    self.bpm = cmd["bpm"]
                if cmd.get("eyes") == "wide":
                    await self._turn()
            await asyncio.sleep(0.005)

    async def _turn(self):
        err = self.errors[min(self.turn, len(self.errors) - 1)]
        self.turn += 1
        if err is None:
            return
        bpm = self.bpm * (1 + err)
        for _ in range(self.n):
            if len(self.ctx.heads) > self._seen:  # the band's face: stop
                break
            self.m.feed(Event("tap", {"t_ms": int(self.t_ms), "src": "knock"}))
            self.t_ms += 60000 / bpm
            await asyncio.sleep(60 / bpm / self.speed)
        self.t_ms += 5000


async def play(ctx, cfg, errors, *, music=None, after=(), timeout=8, drum_kw=None):
    ctx.music = music or Songs()
    ctx.settings.tap_back = cfg
    step = Drum(0.6, idle_end_s=0.15, post_s=0.3, tap_back_cfg=cfg, **(drum_kw or {}))
    m = RitualMachine(ctx, [step])
    task = m.start()
    player = asyncio.create_task(Player(ctx, m, errors).run())
    for ev in after:
        if isinstance(ev, (int, float)):
            await asyncio.sleep(ev)
        else:
            m.feed(ev)
    res = await asyncio.wait_for(task, timeout)
    player.cancel()
    return res, step


def said_after(ctx, line):
    return ctx.said[ctx.said.index(line) + 1]


async def test_the_whole_game_listen_hush_taps_band_next_level_close_and_the_mood_question(ctx):
    ctx.state.record_dial(date.today(), mood=2, energy=3)
    cfg = quick()

    async def answer():
        while POST_MOOD_LINE["ear"] not in ctx.said:
            await asyncio.sleep(0.005)
        m.feed(Event("ear", {"value": 4, "delta": 0, "pressed": True}))

    ctx.music = music = Songs()
    step = Drum(0.6, idle_end_s=0.15, post_s=2.0, tap_back_cfg=cfg)
    m = RitualMachine(ctx, [step])
    task = m.start()
    player = asyncio.create_task(Player(ctx, m, [0.01, 0.07, 0.03]).run())
    mood = asyncio.create_task(answer())
    assert await asyncio.wait_for(task, 8) == {"drum": "completed"}
    player.cancel()
    mood.cancel()
    levels = level_plan(date.today(), cfg)

    # the song: asked at each level's tempo in order, hushed before each turn, stopped at the end
    assert music.bpms == [lv.bpm for lv in levels]
    assert music.calls[:2] == ["start", "hush"]                           # no opening groove before the first song
    order = [c for c in music.calls if c.startswith(("song", "hush", "chime"))]
    assert order[1:5] == [f"song {levels[0].bpm}", "hush", "chime your_turn", "chime perfect"]
    assert [c for c in music.calls if c.startswith("chime")] == [
        "chime your_turn", "chime perfect", "chime your_turn", "chime great", "chime your_turn", "chime perfect"]
    assert music.calls[-1] == "stop" or "stop" in music.calls

    # the body: listening + the beat while the song plays, wide eyes for her turn, a face for the band
    listen = [h for h in ctx.heads if h.get("chest") == "pulse"]
    assert [h["bpm"] for h in listen] == [float(lv.bpm) for lv in levels]
    assert all(h["eyes"] == "listening" and h["pan_mode"] == "sway" for h in listen)
    assert sum(h.get("eyes") == "wide" and h.get("pan_mode") == "still" for h in ctx.heads) == 3
    assert [h["eyes"] for h in ctx.heads if h.get("eyes") in ("happy", "soft", "neutral")][1:4] == ["happy"] * 3
    assert not any("drum" in h for h in ctx.heads)                        # `drum: hold` is for a head with its own ritual
    chimes = [c["chime"] for c in ctx.sensor_cmds if "chime" in c]
    assert chimes == ["start_drum", "ok", "start_drum", "ok", "start_drum", "ok"]

    # the words, in order
    assert ctx.said[0] == tap_back.INTRO["music"]
    assert ctx.said.count(tap_back.CUE) == 3
    assert said_after(ctx, tap_back.BAND_LINE["great"]).startswith("Last one.")
    assert ctx.said[-2:] == ["Three songs, and you found the beat in every one.", POST_MOOD_LINE["ear"]]

    # the record: one obs.tap_back, NO obs.drum_session, then the mood exactly as after free drumming
    assert not ctx.of("obs.drum_session")
    (obs,) = ctx.of("obs.tap_back")
    p = obs.payload
    assert [(lv.level, lv.target_bpm, lv.band, lv.tries, lv.taps) for lv in p.levels] == [
        (1, levels[0].bpm, "perfect", 1, 8), (2, levels[1].bpm, "great", 1, 8), (3, levels[2].bpm, "perfect", 1, 12)]
    assert p.levels[1].error_pct == pytest.approx(7.0, abs=0.5) and p.levels_passed == 3 and p.song == "music"
    assert obs.quality == 1.0 and p.duration_s > 0
    order = [e.type for e in ctx.obs if e.type != "obs.ritual"]
    assert order == ["obs.tap_back", "obs.self_report", "obs.intervention_response"]   # the record BEFORE the question
    post, ir = ctx.of("obs.self_report")[0].payload, ctx.of("obs.intervention_response")[0].payload
    assert (post.item, post.value, post.context) == ("mood", 4, "post_activity")
    assert ir.activity == "drum" and ir.pre.mood == 2 and ir.post.mood == 4 and ir.delta.mood == 2


async def test_again_replays_the_level_once_and_then_the_closer_try_counts(ctx):
    cfg = quick()
    res, step = await play(ctx, cfg, [0.01, 0.07, 0.22, 0.03])
    assert res == {"drum": "completed"}
    levels = step.game.levels
    assert ctx.music.bpms == [levels[0].bpm, levels[1].bpm, levels[2].bpm, levels[2].bpm]   # the third one twice
    assert tap_back.AGAIN_LINE in ctx.said and said_after(ctx, tap_back.AGAIN_LINE) == tap_back.CUE
    p = ctx.of("obs.tap_back")[0].payload
    assert [(lv.band, lv.tries) for lv in p.levels] == [("perfect", 1), ("great", 1), ("perfect", 2)]
    assert p.levels[2].error_pct == pytest.approx(3.0, abs=0.6) and p.levels_passed == 3
    bands = [c for c in ctx.music.calls if c.startswith("chime") and "turn" not in c]
    assert bands == ["chime perfect", "chime great", "chime again", "chime perfect"]
    assert [c["chime"] for c in ctx.sensor_cmds if "chime" in c][-3:] == ["end_drum", "start_drum", "ok"]
    assert [h["eyes"] for h in ctx.heads if h.get("eyes") == "neutral"] == ["neutral"]      # the face for "again"


async def test_a_second_miss_moves_on_kindly_and_never_a_third_try(ctx):
    cfg = quick()
    res, step = await play(ctx, cfg, [0.30, 0.25, 0.01, 0.02])
    levels = step.game.levels
    assert ctx.music.bpms == [levels[0].bpm, levels[0].bpm, levels[1].bpm, levels[2].bpm]
    assert said_after(ctx, tap_back.MOVE_ON_LINE) == tap_back.NEXT_LINE[(False, True)]
    p = ctx.of("obs.tap_back")[0].payload
    assert [(lv.band, lv.tries) for lv in p.levels] == [("again", 2), ("perfect", 1), ("perfect", 1)]
    assert p.levels[0].error_pct == pytest.approx(25, abs=1) and p.levels_passed == 2      # the closer of the two
    assert "Three songs, and you found the beat in two of them." in ctx.said
    assert res == {"drum": "completed"}


async def test_nobody_taps_one_gentle_replay_then_the_step_is_skipped_and_nothing_is_recorded(ctx):
    res, _step = await play(ctx, quick(), [None])
    assert res == {"drum": "skipped"}
    assert ctx.said.count(tap_back.NO_TAPS_LINE) == 1 and len(ctx.music.bpms) == 2
    assert not ctx.of("obs.tap_back") and not ctx.of("obs.drum_session") and not ctx.of("obs.self_report")
    assert tap_back.AGAIN_LINE not in ctx.said                             # "not quite" is never said to silence


async def test_taps_outside_her_turn_are_never_counted(ctx):
    """Taps while the song plays (or the sway motor shaking the sensor) are not hers to be judged on."""
    cfg = quick(listen_s=0.25)
    ctx.music = Songs(speed=1.0)
    step = Drum(0.6, tap_back_cfg=cfg)
    await step.enter(ctx)
    game = step.game
    await game.tick(ctx)                                                   # intro over: the first song starts
    assert game.state == "listen"
    for i in range(6):
        await step.handle(Event("tap", {"t_ms": 1000 + i * 100}), ctx)
    assert game.taps.count == 0 and game.early_taps == 6
    await asyncio.sleep(0.3)
    await game.tick(ctx)
    assert game.state == "turn"
    game._open = game.deadline = time.monotonic() + 0.05                   # the cue is still sounding
    await step.handle(Event("tap", {"t_ms": 5000}), ctx)
    assert game.taps.count == 0
    await asyncio.sleep(0.06)
    await game.tick(ctx)                                                   # the planned opening has come
    await step.handle(Event("tap", {"t_ms": 5600}), ctx)
    assert game.taps.count == 1 and game.early_taps == 7


async def test_her_turn_opens_only_once_the_heads_speaker_is_quiet_and_that_wait_is_not_counted_against_her(ctx):
    """The head sends no tap while its speaker plays (and about 0.3 s after). A cue that runs long (a spoken
    "Your turn." from the Live voice) must not eat her time: the first-tap clock starts when the speaker is quiet."""
    cfg = quick(listen_s=0.1, first_tap_s=0.3, cue_clear_s=0.1)
    ctx.music = Songs(speed=1.0)
    ctx.speaker_busy = False
    step = Drum(0.6, tap_back_cfg=cfg)
    await step.enter(ctx)
    game = step.game
    await game.tick(ctx)
    await asyncio.sleep(0.15)
    ctx.speaker_busy = True                                                # the cue is being spoken, and goes on
    await game.tick(ctx)
    assert game.state == "turn" and not game._opened
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.5:                                     # longer than first_tap_s: no band yet
        await asyncio.sleep(0.02)
        if time.monotonic() >= game.next_deadline():
            await game.tick(ctx)
        await step.handle(Event("tap", {"t_ms": 9000}), ctx)               # (the head would not even send these)
    assert game.state == "turn" and not game._opened and game.taps.count == 0 and not game.results[0].tries
    ctx.speaker_busy = False                                               # the last frame has played
    await asyncio.sleep(0.03)
    await game.tick(ctx)
    assert game._opened and game._open - time.monotonic() == pytest.approx(0.1, abs=0.03)   # the margin after it
    assert game.deadline - game._open == pytest.approx(0.3, abs=0.01)     # her whole first-tap time, from there
    await step.handle(Event("tap", {"t_ms": 20000}), ctx)
    assert game.taps.count == 0                                            # inside the margin: still muted on the head
    await asyncio.sleep(0.11)
    await step.handle(Event("tap", {"t_ms": 20600}), ctx)
    assert game.taps.count == 1


async def test_auto_mode_plays_the_game_only_when_a_generated_song_can_play(ctx):
    cfg = quick(mode="auto")
    # no music at all (the default OffMusic): exactly today's free drumming
    step = Drum(0.3, idle_end_s=0.1, post_s=0.1, tap_back_cfg=cfg)
    m = RitualMachine(ctx, [step])
    task = m.start()
    await asyncio.sleep(0.02)
    for i in range(8):
        m.feed(Event("tap", {"t_ms": 1000 + i * 500, "force": 2.0}))
    assert await asyncio.wait_for(task, 3) == {"drum": "completed"}
    assert step.game is None and ctx.said[0] == "Now drum on my head. Any rhythm you like. I'll follow you."
    assert ctx.of("obs.drum_session")[0].payload.tempo_bpm == pytest.approx(120) and not ctx.of("obs.tap_back")
    # a local beat is not a generated song: still free drumming in auto ...
    ctx.said.clear()
    res, step = await play(ctx, cfg, [0.0], music=Songs(kind="beat", generated=False))
    assert step.game is None and tap_back.INTRO["beat"] not in ctx.said
    # ... and `free` never plays it, whatever the music can do
    res, step = await play(ctx, quick(mode="free"), [0.0], music=Songs())
    assert step.game is None


async def test_the_song_never_comes_auto_falls_back_to_free_drumming(ctx):
    """The adapter said yes but no sound reached the output (network, a dead stream): fail soft, drum freely."""
    cfg = quick(mode="auto")
    ctx.music = Songs(silent_from=1)
    step = Drum(0.5, idle_end_s=0.1, post_s=0.1, tap_back_cfg=cfg)
    m = RitualMachine(ctx, [step])
    task = m.start()
    while tap_back.FALLBACK_LINE not in ctx.said:
        await asyncio.sleep(0.01)
    assert step.phase == "drum" and {"chime": "start_drum"} in ctx.sensor_cmds
    for i in range(8):
        m.feed(Event("tap", {"t_ms": 1000 + i * 600}))
    assert await asyncio.wait_for(task, 3) == {"drum": "completed"}
    assert ctx.of("obs.drum_session")[0].payload.tempo_bpm == pytest.approx(100) and not ctx.of("obs.tap_back")
    assert tap_back.CUE not in ctx.said                                    # she was never asked to tap back a song she did not hear


async def test_a_song_lost_after_the_first_level_keeps_that_level_and_goes_on_free(ctx):
    cfg = quick(mode="auto")
    ctx.music = Songs(silent_from=2)
    res, step = await play(ctx, cfg, [0.0], music=ctx.music, after=[])
    assert step.phase in ("drum", "post") and tap_back.FALLBACK_LINE in ctx.said
    p = ctx.of("obs.tap_back")[0].payload
    assert p.levels_played == 1 and p.levels[0].band == "perfect"          # what was played is kept
    assert res == {"drum": "completed"} and not ctx.of("obs.drum_session")


async def test_forced_mode_plays_with_the_hubs_own_beat_or_the_light_alone(ctx):
    res, step = await play(ctx, quick(), [0.02], music=Songs(kind="beat", generated=False))
    assert res == {"drum": "completed"} and ctx.said[0] == tap_back.INTRO["beat"]
    assert ctx.of("obs.tap_back")[0].payload.song == "beat"
    for kept in (ctx.said, ctx.obs, ctx.heads):
        kept.clear()
    res, step = await play(ctx, quick(listen_s=0.03), [0.02], music=Music())   # no music adapter at all
    assert res == {"drum": "completed"} and ctx.said[0] == tap_back.INTRO[""]
    p = ctx.of("obs.tap_back")[0].payload
    assert p.song == "light" and p.levels_passed == 3                      # the light's beat is enough to play
    assert [h["bpm"] for h in ctx.heads if h.get("chest") == "pulse"] == [float(lv.bpm) for lv in step.game.levels]


async def test_the_knock_build_sways_only_while_the_song_plays_and_a_voice_gets_room_to_speak(ctx):
    """`[robot] drum_sway = false` keeps the head still while she DRUMS (the motor would trigger the knock switch).
    In the game it sways with the song and is still again before her turn."""
    ctx.voice_audible = True
    cfg = quick(word_s=0.01)
    res, step = await play(ctx, cfg, [0.0], drum_kw={"sway": False})
    assert res == {"drum": "completed"}
    modes = [h["pan_mode"] for h in ctx.heads if "pan_mode" in h]
    assert modes.count("sway") == 3
    for i, h in enumerate(ctx.heads):
        if h.get("eyes") == "wide":                                        # every turn starts with the head still
            assert h["pan_mode"] == "still" and "sway" not in [x.get("pan_mode") for x in ctx.heads[i:i + 1]]
    still_before_turn = [ctx.heads[i - 1].get("pan_mode") for i, h in enumerate(ctx.heads) if h.get("eyes") == "wide"]
    assert still_before_turn == ["sway"] * 3                               # the command before "your turn" was the song's


async def test_the_game_may_run_longer_than_the_rituals_step_cap_and_ends_itself(ctx):
    cfg = quick(max_s=0.25, listen_s=0.1)
    ctx.music = Songs(speed=1.0)
    step = Drum(0.2, post_s=0.05, tap_back_cfg=cfg)
    m = RitualMachine(ctx, [step], step_timeout_s=0.1)                     # the ritual's cap is shorter than one level
    task = m.start()
    player = asyncio.create_task(Player(ctx, m, [0.0]).run())
    assert await asyncio.wait_for(task, 5) == {"drum": "completed"}
    player.cancel()
    p = ctx.of("obs.tap_back")[0].payload
    assert 1 <= p.levels_played < 3                                        # max_s ended it kindly after a level
    assert any(line.startswith("One song") or line.startswith("Two songs") for line in ctx.said)
    assert step.hard_cap_s(0.1) > cfg.max_s and Drum(1).hard_cap_s(0.1) == 0.1


async def test_abort_stops_the_music_and_records_nothing(ctx):
    ctx.music = Songs(speed=1.0)
    m = RitualMachine(ctx, [Drum(5, tap_back_cfg=quick(listen_s=5))])
    m.start()
    await asyncio.sleep(0.05)
    await m.abort()
    assert "stop" in ctx.music.calls and not ctx.of("obs.tap_back")
    assert [(e.payload.step, e.payload.status) for e in ctx.of("obs.ritual")] == [("drum", "started"), ("drum", "aborted")]


def test_the_hub_emits_only_registered_types_and_the_example_is_what_the_game_makes():
    from kaiku_contracts import EXAMPLES, make

    env = make("obs.tap_back", EXAMPLES["obs.tap_back"], source="hub", quality=0.9)
    assert env.payload.levels_passed == 3 and env.payload.levels[2].tries == 2


async def test_a_line_already_heard_to_its_end_gets_no_second_wait(ctx):
    """The Live voice returns from `say` when it starts speaking, so the game leaves room for the words. A scripted
    line in the cached voice returns only when it has been heard through the head's speaker: no room is added twice."""
    cfg = quick(word_s=0.05)
    game = tap_back.Game(cfg)
    ctx.voice_audible = True
    line = tap_back.INTRO["music"]                                         # 16 words: 0.8 s of room
    assert await game._say(ctx, line) == pytest.approx(0.8)                # a voice that returned at once
    real = ctx.say

    async def spoken_to_the_end(text):
        await real(text)
        await asyncio.sleep(0.45)

    ctx.say = spoken_to_the_end
    ctx.speaker_busy = True                                                # still sounding: the room stays
    assert await game._say(ctx, line) == pytest.approx(0.8)
    ctx.speaker_busy = None                                                # sound not through the head: not known
    assert await game._say(ctx, line) == pytest.approx(0.8)
    ctx.speaker_busy = False                                               # heard, and the head is quiet again
    assert await game._say(ctx, line) == 0.0
    ctx.voice_audible = False                                              # text or off: no room at all
    assert await game._say(ctx, line) == 0.0
