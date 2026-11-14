"""`raw.hub.trace`: what Kaiku says and does, live, for the "Kaiku bot" tab of the person's own apps on the home
network. Kaiku's own lines and the names of the tools the voice called. Never the person's words, a system
instruction, a tool's arguments or its result; never anything after a crisis but the script line; and it never
holds up or fails the ritual."""

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace as NS

import numpy as np
import pytest
from kaiku_contracts import ContractError, make
from kaiku_contracts.registry import TRACE_EXAMPLES, UPLINKABLE
from kaiku_contracts.topics import qos_for, retain_for, topic_for
from kaiku_hub.main import Hub, _answered_by
from kaiku_hub.rituals import tap_back

from hub.tests.fakes import Songs
from hub.tests.test_follow_voice import CRISIS, PATIENT, Rig
from hub.tests.test_live_integration import finished_speech, settle

HER_WORDS = "I slept badly and my sister Liisa is in hospital"
REPLY = "That sounds heavy. I am here with you."


def reply(text=REPLY):
    """A finished spoken reply of the Live voice: its audio, and its own words as the output transcription."""
    parts = [NS(inline_data=NS(data=np.full(2400, 8000, dtype="<i2").tobytes()))]
    return NS(server_content=NS(model_turn=NS(parts=parts), output_transcription=NS(text=text, finished=True),
                                turn_complete=True))


def traces(sent):
    return [p for t, p in sent if t == "raw.hub.trace"]


def of(sent, kind):
    return [p for p in traces(sent) if p["kind"] == kind]


async def test_a_ritual_with_the_voice_is_traced_and_her_words_are_in_none_of_it(settings):
    r = Rig(settings, music=Songs(), **PATIENT)
    hub = r.hub
    session = await r.greeted_and_pressed()
    await settle(lambda: of(r.sent, "session") == [{"kind": "session", "detail": "open"}])

    await session.incoming.put(reply())                                # Kaiku answers aloud
    await settle(lambda: {"kind": "said", "text": REPLY, "by": "live"} in traces(r.sent))
    await session.incoming.put(finished_speech(HER_WORDS))             # she speaks: only THAT she spoke
    await settle(lambda: of(r.sent, "heard") == [{"kind": "heard"}])
    out = await hub.on_tool("feel", {"kind": "sad_news", "heard": {"valence": "low", "via": "voice"},
                                     "about": "her sister", "said": HER_WORDS})   # the voice calls a tool
    assert out["ok"]
    await settle(lambda: len(of(r.sent, "tool")) == 1)
    (tool,) = of(r.sent, "tool")
    assert {k: v for k, v in tool.items() if k != "ms"} == {"kind": "tool", "tool": "feel", "ok": True, "by": "rule"}
    assert isinstance(tool["ms"], int) and tool["ms"] >= 0
    await hub.on_tool("record_dial", {"item": "mood", "value": 3})     # refused on this head: traced as not ok
    await settle(lambda: len(of(r.sent, "tool")) == 2)
    assert of(r.sent, "tool")[-1]["tool"] == "record_dial" and of(r.sent, "tool")[-1]["ok"] is False

    for v in (7, 4, 9):
        await r.press(v)
    await r.health("breathe")
    await r.chime("start_drum")                                        # Tap it back, in the same ritual
    await settle(lambda: hub._game is not None, timeout=3)
    await asyncio.wait_for(r.play([0.01, 0.07, 0.02]), 10)
    await settle(lambda: r.heads() and r.heads()[-1].get("drum") == "end", timeout=3)
    await settle(lambda: of(r.sent, "music")[-1]["detail"] == "stop", timeout=3)   # (a trace is sent in its own time)
    game = [(p["detail"], p.get("bpm")) for p in of(r.sent, "game")]
    levels = [lv.bpm for lv in tap_back.level_plan(datetime.now().astimezone().date(), settings.tap_back)]
    plan = [(f"level:{i + 1}", float(b)) for i, b in enumerate(levels)]
    started = [g for g in game if g[0].startswith("level:")]           # a level may be played twice ("again")
    assert list(dict.fromkeys(started)) == plan
    turns = [g[0] for g in game if g[0] == "your_turn"]
    bands = [g[0] for g in game if g[0].startswith("band:")]
    assert len(turns) == len(started) == len(bands) >= 3
    assert set(bands) <= {"band:perfect", "band:great", "band:nice", "band:again"}
    music = [(p["detail"], p.get("bpm")) for p in of(r.sent, "music")]
    assert [m for m in music if m[0] == "song"] == [("song", bpm) for _name, bpm in started]
    assert music[0][0] == "start" and music[-1][0] == "stop" and ("hush", None) in music

    await r.chime("end_drum")                                          # the head is done: the talk closes
    await settle(lambda: of(r.sent, "session")[-1] == {"kind": "session", "detail": "close"}, timeout=5)

    everything = json.dumps(traces(r.sent))
    for private in ("Liisa", "slept badly", "hospital", "her sister", "Test persona", "sad_news", "valence"):
        assert private not in everything, private                      # her words, the instruction, a tool's result
    for p in traces(r.sent):                                           # every one is a valid, local-only message
        env = make("raw.hub.trace", p, source="hub", home_id=r.home)
        assert qos_for(env) == 0 and not retain_for(env) and topic_for(env) == f"kaiku/v1/{r.home}/raw/hub/trace"
        assert ("text" not in p or p["kind"] == "said") and (p["kind"] != "heard" or p == {"kind": "heard"})
    assert "raw.hub.trace" not in UPLINKABLE and not [e for e in hub.emitted if e.type.startswith("raw.")]


async def test_scripted_lines_are_traced_as_said_with_how_they_were_spoken(settings):
    settings.voice = "text"
    hub = Hub(settings, read_stdin=False)
    sent = []

    async def publish(type_, payload, **k):
        sent.append((type_, dict(payload)))

    hub.bus.publish = publish
    await hub.say("Now breathe with my light.")
    await hub.say("x" * 400)                                           # cut, never refused
    await asyncio.sleep(0.02)
    said = of(sent, "said")
    assert said[0] == {"kind": "said", "text": "Now breathe with my light.", "by": "script"}
    assert said[1]["text"] == "x" * 300 and make("raw.hub.trace", said[1], source="hub")
    hub.settings.local_tts = True                                      # the cached Gemini voice speaks the lines
    await hub.say("Your turn.")
    await asyncio.sleep(0.02)
    assert of(sent, "said")[-1] == {"kind": "said", "text": "Your turn.", "by": "cached_voice"}


async def test_after_a_crisis_only_the_script_line_is_traced_until_she_starts_a_new_ritual(settings):
    r = Rig(settings)
    hub = r.hub
    session = await r.greeted_and_pressed()
    await settle(lambda: of(r.sent, "session"))
    before = len(traces(r.sent))
    await session.incoming.put(finished_speech(CRISIS))                # she says it aloud
    await settle(lambda: r.types().count("obs.safety_flag") == 1, timeout=3)
    await hub.say("Shall we go on?")                                   # whatever still tries to speak or act
    await hub.on_tool("recall", {"about": "anything"})
    await hub.on_live_utterance("are you there")
    await asyncio.sleep(0.1)
    after = traces(r.sent)[before:]
    assert after == [{"kind": "said", "text": hub.script.text(settings.language)[:300], "by": "script"}]
    assert "die" not in json.dumps(traces(r.sent)) and of(r.sent, "heard") == []   # not even that she spoke

    await r.health("idle")                                             # the next ritual she starts herself
    await r.chime("wake")
    await r.press()
    await settle(lambda: of(r.sent, "session")[-1:] == [{"kind": "session", "detail": "open"}]
                 and len(of(r.sent, "session")) == 2, timeout=3)
    await hub.voice.close_session()


async def test_the_trace_never_holds_up_or_fails_what_kaiku_does(settings):
    settings.voice = "text"
    hub = Hub(settings, read_stdin=False)

    async def stuck(type_, payload, **k):
        if type_ == "raw.hub.trace":
            await asyncio.sleep(30)

    hub.bus.publish = stuck
    await asyncio.wait_for(hub.say("One."), 0.5)                       # returns at once: nobody waits for the trace

    async def broken(type_, payload, **k):
        raise ContractError("no")

    hub.bus.publish = broken
    await hub.say("Two.")
    assert (await hub.on_tool("express", {"feeling": "happy"}))["ok"] is False   # (no conversation) but no exception
    hub.trace("said", text=None, by="live")                           # odd input is dropped by the contract, quietly
    hub.trace("heard", text="her words")                              # ... and this can never be published at all
    await asyncio.sleep(0.02)

    sent = []

    async def publish(type_, payload, **k):
        make(type_, payload, source="hub")                             # the real bus validates like this
        sent.append((type_, dict(payload)))

    hub.bus.publish = publish
    hub.trace("heard", text="her words")
    await asyncio.sleep(0.02)
    assert sent == []                                                  # refused by the contract, never sent
    hub.settings.trace = False                                         # [hub] trace = false: nothing at all
    await hub.say("Three.")
    await asyncio.sleep(0.02)
    assert sent == []
    for t in list(hub._trace_tasks):
        t.cancel()


def test_who_answered_a_tool_is_told_only_in_the_traces_own_words():
    assert _answered_by("rule") == "rule" and _answered_by("gemma-4-27b-it") == "gemma"
    assert _answered_by("gemini-3-flash") == "flash" and _answered_by("notebook") == "notebook"
    assert _answered_by("some-other-model") is None and _answered_by(None) is None and _answered_by({"x": 1}) is None


@pytest.mark.parametrize("bad", [{"kind": "heard", "text": "her words"}, {"kind": "heard", "detail": "x"},
                                 {"kind": "tool", "tool": "feel", "text": "an argument"},
                                 {"kind": "said", "text": "x" * 301}, {"kind": "said", "text": "hi", "by": "gemma"},
                                 {"kind": "game", "tool": "feel"}, {"kind": "said", "args": {"said": "her words"}},
                                 {"kind": "thought", "text": "x"}])
def test_the_contract_refuses_a_trace_that_could_carry_her_words(bad):
    with pytest.raises(ContractError):
        make("raw.hub.trace", bad, source="hub")


@pytest.mark.parametrize("name", sorted(TRACE_EXAMPLES))
def test_every_trace_example_is_valid(name):
    env = make("raw.hub.trace", TRACE_EXAMPLES[name], source="hub")
    assert env.payload.model_dump(mode="json", exclude_none=True) == TRACE_EXAMPLES[name]
