"""T5 live context events (plan 06 §4) + the thinking body during cloud tool calls."""

import asyncio
import random
import re

import pytest
from kaiku_hub.live.base import OffMusic, OffVoice, Voice
from kaiku_hub.live.context_events import (
    STATE_WORDS,
    VOCAB,
    ContextEvents,
    DrumFeel,
    breathing_calmer,
    late_key,
    light_key,
)
from kaiku_hub.live.text import TextVoice
from kaiku_hub.main import Hub


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make_events(**kw):
    sent: list[str] = []

    async def sink(text):
        sent.append(text)

    clock = Clock()
    ev = ContextEvents(sink, clock=clock, **kw)
    return ev, sent, clock


# ------------------------------------------------------------------ vocabulary / format
def test_vocab_format():
    for key, text in VOCAB.items():
        assert re.fullmatch(r"\[[a-z' ·]+\]", text), text
        assert len(text) <= 40
        assert key.split(".")[0] in {"drum", "breathe", "people", "light", "time"}
    assert VOCAB["drum.lively"] == "[drumming · lively]"
    assert VOCAB["breathe.calmer"] == "[breathing · heart calmer]"


def test_no_digits_or_state_words_in_any_event():
    """Property: whatever the producers see, every event that reaches the sink is digit- and state-word-free."""
    rng = random.Random(7)
    ev, sent, clock = make_events(min_gap_s=0, max_per_session=10_000)
    ev.open_session()
    feel = DrumFeel()

    async def run():
        t = 0
        for _ in range(3000):
            t += rng.randint(-50, 900)
            ev.sent.clear()  # disable dedupe to see every possible output
            await ev.notice(feel.add(t, rng.uniform(0, 8)) or "")
            ev.sent.clear()
            await ev.notice(light_key(rng.uniform(0, 5000)) or "")
            ev.sent.clear()
            await ev.notice(late_key(rng.randint(0, 23)) or "")
            ev.sent.clear()
            await ev.notice(rng.choice([*VOCAB, "free text 42", "[mood · low]"]))

    asyncio.run(run())
    assert sent and set(sent) <= set(VOCAB.values())
    for text in [*sent, *VOCAB.values()]:
        assert not re.search(r"\d", text)
        words = set(re.findall(r"[a-z'-]+", text.lower()))
        assert not words & STATE_WORDS, text


# ------------------------------------------------------------------ rate limit + dedupe
async def test_rate_limit_boundary_19_vs_20_s():
    ev, sent, clock = make_events()
    ev.open_session()
    assert await ev.notice("drum.steady")
    clock.t += 19.0
    assert not await ev.notice("drum.lively")
    clock.t += 1.0  # exactly 20 s after the first
    assert await ev.notice("drum.lively")
    assert sent == ["[drumming · steady]", "[drumming · lively]"]


async def test_dedupe_and_ninth_event_dropped():
    ev, sent, clock = make_events(max_per_session=8)
    ev.open_session()
    assert await ev.notice("light.dim")
    clock.t += 30
    assert not await ev.notice("light.dim")  # same event once per session
    keys = [k for k in VOCAB if k != "light.dim"]
    for k in keys[:7]:
        clock.t += 30
        assert await ev.notice(k)
    assert len(sent) == 8
    clock.t += 30
    assert not await ev.notice(keys[7])  # 9th dropped
    assert len(sent) == 8
    ev.open_session()  # new session: counters reset
    assert await ev.notice(keys[7])


async def test_no_session_is_silent_noop():
    ev, sent, clock = make_events()
    assert not await ev.notice("drum.lively")
    ev.open_session()
    ev.close_session()
    assert not await ev.notice("drum.lively")
    assert not await ev.notice("not.a.key")
    assert sent == []


async def test_sink_failure_never_raises():
    async def boom(text):
        raise RuntimeError("voice down")

    ev = ContextEvents(boom)
    ev.open_session()
    assert await ev.notice("drum.steady")


# ------------------------------------------------------------------ producers
def taps(feel, n, start, gap_ms, force):
    out = None
    for i in range(n):
        out = feel.add(start + i * gap_ms, force)
    return out, start + n * gap_ms


def test_drum_feel_relative_to_ritual_start():
    feel = DrumFeel(window=6)
    assert feel.add(0, 1.0) is None
    first, t = taps(feel, 5, 500, 500, 1.0)
    assert first == "drum.steady"  # first window = the baseline
    lively, t = taps(feel, 6, t, 300, 2.0)
    assert lively == "drum.lively"
    gentle, t = taps(feel, 8, t, 900, 0.5)
    assert gentle == "drum.gentle"
    feel.reset()  # a gentle person who is ALWAYS gentle is steady relative to themselves
    out, _ = taps(feel, 12, 0, 900, 0.5)
    assert out == "drum.steady"


def test_drum_feel_knock_switch_has_no_force():
    """KY-031 knock (current build) sends no force: tempo alone decides, never a crash."""
    feel = DrumFeel(window=6)
    first, t = taps(feel, 6, 0, 600, None)
    assert first == "drum.steady"
    lively, _ = taps(feel, 6, t, 400, None)
    assert lively == "drum.lively"


def test_drum_feel_ignores_double_triggers():
    feel = DrumFeel(window=2)
    assert feel.add(0, 1.0) is None
    assert feel.add(30, 1.0) is None  # refractory
    assert len(feel.times) == 1


def test_breathing_calmer_rule():
    assert breathing_calmer({"activity": "breathe", "delta": {"hr_bpm": -3.0, "rmssd_ms": 4.0}})
    assert breathing_calmer({"activity": "breathe", "delta": {"rmssd_ms": 2.0}})
    assert not breathing_calmer({"activity": "breathe", "delta": {"hr_bpm": 2.0, "rmssd_ms": 4.0}})
    assert not breathing_calmer({"activity": "breathe", "delta": {}})
    assert not breathing_calmer({"activity": "drum", "delta": {"hr_bpm": -3.0}})


def test_light_and_late():
    assert light_key(10) == "light.dim" and light_key(2000) == "light.bright" and light_key(300) is None
    assert late_key(23) == "time.late" and late_key(2) == "time.late"
    assert late_key(22) is None and late_key(8) is None


# ------------------------------------------------------------------ voices
async def test_voice_send_context_noops_and_text_prints(capsys):
    await Voice().send_context("[drumming · lively]")
    await OffVoice().send_context("[drumming · lively]")
    await TextVoice(read_stdin=False).send_context("[drumming · lively]")
    assert "[drumming · lively]" in capsys.readouterr().err


# ------------------------------------------------------------------ hub wiring
class CtxVoice(Voice):
    name = "rec"

    def __init__(self):
        self.said, self.verbatim, self.context = [], [], []

    async def say(self, text):
        self.said.append(text)

    async def say_verbatim(self, text):
        self.verbatim.append(text)

    async def send_context(self, text):
        self.context.append(text)


@pytest.fixture
def hub(settings):
    h = Hub(settings, voice=CtxVoice(), music=OffMusic(), read_stdin=False)
    h.heads = []
    orig = h._cmd

    async def rec(type_, payload):
        if type_ == "cmd.head":
            h.heads.append(dict(payload))
        await orig(type_, payload)

    h._cmd = rec
    return h


async def test_hub_breathing_event_from_its_own_obs(hub):
    await hub.emit("obs.intervention_response", {"activity": "breathe", "pre": {"hr_bpm": 70.0},
                                                 "post": {"hr_bpm": 66.0}, "delta": {"hr_bpm": -4.0}})
    assert hub.voice.context == []  # no ritual = no session = dropped
    hub.start_ritual("test")
    await asyncio.sleep(0.02)
    hub.context._last = -1e18  # ignore a possible "[it's late]" at session start
    await hub.emit("obs.intervention_response", {"activity": "breathe", "pre": {"hr_bpm": 70.0},
                                                 "post": {"hr_bpm": 66.0}, "delta": {"hr_bpm": -4.0}})
    assert hub.voice.context[-1] == "[source: robot] [breathing · heart calmer]"
    await hub.machine.abort()


async def test_thinking_set_and_cleared(hub):
    async def slow(name, args, sid=None, timeout_s=4.0):
        assert hub.thinking == 1 and hub.heads[-1]["eyes"] == "thinking"
        return {"ok": True, "result": {"answer": "hi"}}

    hub.cloud.companion_tool = slow
    await hub.head(eyes="listening")
    res = await hub.on_tool("recall", {"query": "sister"})
    assert res["ok"] and res["answer"] == "hi"
    assert hub.thinking == 0 and hub.heads[-1]["eyes"] == "listening"


async def test_thinking_timeout_says_scripted_line_and_ritual_continues(hub):
    async def hang(name, args, sid=None, timeout_s=4.0):
        await asyncio.sleep(10)

    hub.cloud.companion_tool = hang
    hub.think_timeout_s = 0.05
    hub.start_ritual("test")
    await asyncio.sleep(0.02)
    await hub.head(eyes="soft")
    res = await hub.on_tool("recall", {"query": "x"})
    await asyncio.sleep(0.02)
    assert not res["ok"] and "later" in res["error"]
    assert "Let me think about that later." in hub.voice.said
    assert hub.thinking == 0 and hub.heads[-1]["eyes"] == "soft"
    assert hub.machine.running
    await hub.machine.abort()


async def test_thinking_not_restored_after_crisis(hub):
    async def crisis_result(name, args, sid=None, timeout_s=4.0):
        return {"ok": False, "crisis": True}

    hub.cloud.companion_tool = crisis_result
    await hub.head(eyes="happy")
    res = await hub.on_tool("recall", {"query": "x"})
    assert res["error"] == "stopped" and hub.voice.verbatim
    assert hub.thinking == 0
    assert hub.heads[-1]["eyes"] == "soft"  # the crisis body stays; thinking doesn't overwrite it


async def test_crisis_during_thinking_keeps_crisis_body(hub):
    async def slow(name, args, sid=None, timeout_s=4.0):
        await hub.on_utterance("I want to die")
        return {"ok": True, "result": {}}

    hub.cloud.companion_tool = slow
    hub.start_ritual("test")
    await asyncio.sleep(0.02)
    await hub.on_tool("recall", {"query": "x"})
    assert hub.heads[-1]["eyes"] == "soft" and hub.thinking == 0
    assert not hub.context.active  # crisis closes the context session too
