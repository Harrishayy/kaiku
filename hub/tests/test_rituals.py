import asyncio
from datetime import date

import pytest
from kaiku_hub.rituals import Event, RitualMachine, Step, default_steps
from kaiku_hub.rituals.steps import Breathe, Dial, Drum, Nudge, Phq9


def fast(settings, **over):
    settings.greet_s, settings.dial_s, settings.breathe_s = 0.05, 0.3, 0.3
    settings.drum_s, settings.drum_idle_end_s, settings.nudge_s, settings.post_mood_s = 0.5, 0.1, 0.1, 0.2
    for k, v in over.items():
        setattr(settings, k, v)
    return settings


def statuses(ctx):
    return [(e.payload.step, e.payload.status) for e in ctx.of("obs.ritual")]


def ear(value, pressed=False):
    return Event("ear", {"value": value, "delta": 0, "pressed": pressed})


async def run_with(ctx, steps, events, settle=0.03, timeout=3):
    m = RitualMachine(ctx, steps)
    task = asyncio.create_task(m.run())
    await asyncio.sleep(settle)
    for ev in events:
        if isinstance(ev, (int, float)):
            await asyncio.sleep(ev)
        else:
            m.feed(ev)
    return await asyncio.wait_for(task, timeout)


async def test_full_ritual_order_with_timeouts(ctx):
    m = RitualMachine(ctx, default_steps(fast(ctx.settings)))
    results = await m.run()
    order = [s for s, st in statuses(ctx) if st == "started"]
    assert order == ["greet", "dial", "breathe", "drum", "nudge", "close"]  # phq9 not due -> not run at all
    assert results == {"greet": "completed", "dial": "skipped", "breathe": "completed", "drum": "skipped",
                       "nudge": "completed", "close": "completed"}
    assert m.state == "idle"
    assert {"ppg": "start"} in ctx.sensor_cmds and {"ppg": "stop"} in ctx.sensor_cmds
    assert ctx.of("obs.nudge_offered")[0].payload.arm == "daylight_walk"
    assert all(e.payload.duration_s is not None for e in ctx.of("obs.ritual") if e.payload.status != "started")


async def test_dial_three_questions_by_ear(ctx):
    res = await run_with(ctx, [Dial(5)], [ear(5), ear(7), ear(4, True), ear(2, True), 0.02, ear(3), ear(5, True)])
    assert res == {"dial": "completed"}
    got = [(e.payload.item, e.payload.value, e.payload.context) for e in ctx.of("obs.self_report")]
    assert got == [("mood", 4, "ritual"), ("energy", 2, "ritual"), ("sleep", 5, "ritual")]
    assert ctx.state.today_mood(date.today()) == 4 and ctx.state.today_energy(date.today()) == 2
    assert sum("energy" in s for s in ctx.said) == 1 and sum("sleep" in s for s in ctx.said) == 1


async def test_dial_voice_tool_and_timeout_with_turned_dial(ctx):
    # mood by utterance, energy by tool, sleep turned but never pressed -> counted at timeout
    res = await run_with(ctx, [Dial(0.4)], [Event("utterance", {"text": "maybe a 3"}),
                                            Event("tool", {"name": "record_dial", "args": {"item": "energy", "value": 2}}),
                                            ear(4)])
    assert res == {"dial": "completed"}
    assert [(e.payload.item, e.payload.value) for e in ctx.of("obs.self_report")] == [
        ("mood", 3), ("energy", 2), ("sleep", 4)]


async def test_dial_no_input_skipped(ctx):
    assert await run_with(ctx, [Dial(0.1)], []) == {"dial": "skipped"}
    assert not ctx.of("obs.self_report")


async def test_skip_event(ctx):
    res = await run_with(ctx, [Dial(5), Nudge(5)], [Event("skip"), 0.05, Event("utterance", {"text": "yes please"})])
    assert res == {"dial": "skipped", "nudge": "completed"}
    assert ctx.state.data["pending_nudge"]["accepted"] is True


async def test_drum_session_then_post_activity_mood(ctx):
    ctx.state.record_dial(date.today(), mood=2, energy=3)
    taps = [Event("tap", {"t_ms": 1000 + i * 500, "force": 2.0}) for i in range(8)]
    res = await run_with(ctx, [Drum(10, idle_end_s=0.2, post_s=2)], [*taps, 0.4, ear(4), ear(5, True)])
    assert res == {"drum": "completed"}  # drumming ended on idle, then the post-activity dial
    d = ctx.of("obs.drum_session")[0].payload
    assert d.tempo_bpm == pytest.approx(120) and d.taps == 8 and d.force_mean == pytest.approx(0.5)
    post = ctx.of("obs.self_report")[0].payload
    assert (post.item, post.value, post.context) == ("mood", 5, "post_activity")
    ir = ctx.of("obs.intervention_response")[0].payload
    assert ir.activity == "drum" and ir.pre.mood == 2 and ir.post.mood == 5 and ir.delta.mood == 3
    assert any(h.get("pan_mode") == "sway" for h in ctx.heads)
    assert {"pan_mode": "still"} in ctx.heads
    # drum_session is emitted BEFORE the post-activity question (head_sim answers on obs.drum_session)
    order = [e.type for e in ctx.obs if e.type != "obs.ritual"]
    assert order.index("obs.drum_session") < order.index("obs.self_report")


async def test_drum_post_mood_timeout_keeps_drum_session(ctx):
    taps = [Event("tap", {"t_ms": 1000 + i * 400, "force": 1.0}) for i in range(6)]
    res = await run_with(ctx, [Drum(10, idle_end_s=0.1, post_s=0.2)], taps)
    assert res == {"drum": "completed"}
    assert len(ctx.of("obs.drum_session")) == 1
    assert not ctx.of("obs.intervention_response")  # nothing measured after -> no response emitted


async def test_drum_too_few_taps_skipped(ctx):
    res = await run_with(ctx, [Drum(0.2)], [Event("tap", {"t_ms": 1, "force": 1.0})])
    assert res == {"drum": "skipped"} and not ctx.of("obs.drum_session")


async def test_breathe_emits_hrv_and_intervention_response(ctx, ppg):
    m = RitualMachine(ctx, [Breathe(0.3, bpm=6, window_s=30)])
    task = asyncio.create_task(m.run())
    await asyncio.sleep(0.02)
    sig = ppg([800, 850] * 30)
    for i in range(0, len(sig) - 25, 25):
        m.feed(Event("ppg", {"t0_ms": i * 10, "fs_hz": 100.0, "samples": sig[i:i + 25].tolist()}))
    await task
    hrv = ctx.of("obs.hrv_session")
    assert hrv and hrv[0].payload.breath_bpm == 6 and hrv[0].quality and hrv[0].quality > 0.7
    ir = ctx.of("obs.intervention_response")[0].payload
    assert ir.activity == "breathe" and ir.pre.rmssd_ms and ir.post.rmssd_ms and ir.pre.hr_bpm
    assert ir.delta.rmssd_ms == pytest.approx(ir.post.rmssd_ms - ir.pre.rmssd_ms, abs=0.01)


async def test_phq9_not_run_unless_due_and_spoken(ctx):
    ctx.settings.phq9_mode = "laptop"
    ctx.state.phq9_due = True
    assert await RitualMachine(ctx, [Phq9(1)]).run() == {}
    assert not ctx.of("obs.ritual")


async def test_phq9_spoken_complete(ctx):
    ctx.settings.phq9_mode = "spoken"
    ctx.state.phq9_due = True
    answers = ["not at all", "1", "several days", "2", "0", "nearly every day", "1", "0", "0"]
    res = await run_with(ctx, [Phq9(5), Nudge(0.05)], [Event("utterance", {"text": a}) for a in answers])
    assert res["phq9"] == "completed" and "nudge" in res
    p = ctx.of("obs.phq9")[0].payload
    assert p.items == [0, 1, 1, 2, 0, 3, 1, 0, 0] and p.total == 8 and not p.item9_positive and p.mode == "spoken"
    assert not ctx.state.phq9_due


async def test_phq9_item9_positive_stops_ritual(ctx):
    ctx.settings.phq9_mode = "both"
    ctx.state.phq9_due = True
    answers = [ear(1, True)] * 8 + [ear(2, True)]  # dial 2 -> item score 1
    res = await run_with(ctx, [Phq9(5), Nudge(5)], answers)
    assert res == {"phq9": "completed"}  # nudge never runs
    p = ctx.of("obs.phq9")[0].payload
    assert p.item9_positive and p.items[8] == 1 and p.total == 1


async def test_phq9_partial_never_emitted(ctx):
    ctx.settings.phq9_mode = "spoken"
    ctx.state.phq9_due = True
    res = await run_with(ctx, [Phq9(0.2)], [Event("utterance", {"text": "2"})])
    assert res == {"phq9": "skipped"} and not ctx.of("obs.phq9")


async def test_abort_emits_aborted_and_cleans_up(ctx):
    m = RitualMachine(ctx, [Breathe(10)])
    m.start()
    await asyncio.sleep(0.05)
    assert m.running and m.state == "breathe"
    await m.abort()
    assert not m.running and m.state == "idle"
    assert ("breathe", "aborted") in statuses(ctx)
    assert {"ppg": "stop"} in ctx.sensor_cmds
    assert not ctx.of("obs.hrv_session")


async def test_broken_step_is_skipped_not_fatal(ctx):
    class Boom(Step):
        name = "greet"

        async def enter(self, c):
            raise RuntimeError("boom")

    res = await RitualMachine(ctx, [Boom(1), Dial(0.05)]).run()
    assert res == {"greet": "skipped", "dial": "skipped"}


async def test_hard_step_timeout_caps(ctx):
    res = await asyncio.wait_for(RitualMachine(ctx, [Dial(100)], step_timeout_s=0.1).run(), 1)
    assert res == {"dial": "skipped"}


async def test_nudge_outcome_next_day(ctx):
    ctx.state.set_pending_nudge("daylight_walk", True, 2, 3, date(2020, 1, 1))
    await run_with(ctx, [Dial(5)], [Event("utterance", {"text": "I'd say 4"}), Event("utterance", {"text": "4"}),
                                    Event("utterance", {"text": "3"})])
    out = ctx.of("obs.nudge_outcome")[0].payload
    assert out.arm == "daylight_walk" and out.accepted
    assert out.next_day.mood == 4 and out.next_day.energy == 4
    assert out.reward == pytest.approx(0.5 + 0.125 * 1.5, abs=1e-3)


def test_breathe_closing_line_only_claims_what_the_data_shows():
    from kaiku_hub.rituals.steps import closing_line

    settled = "Lovely. Your heart settled nicely."
    assert closing_line({"hr_bpm": -3.0}) == settled
    assert closing_line({"rmssd_ms": 4.0, "hr_bpm": 1.0}) == settled
    assert closing_line({"hr_bpm": -1.0, "rmssd_ms": 1.0}) != settled  # tiny change: no claim
    assert closing_line({"hr_bpm": 2.0}) != settled
    assert closing_line({}) != settled  # no clean pre/post: no claim
