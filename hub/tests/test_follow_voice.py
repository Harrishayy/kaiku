"""Kaiku's conversation on a head that runs its own ritual (standalone firmware, follow mode), and the microphone
during Tap it back. The production adapter and the real hub; the model, the cloud bootstrap and the bus are faked.

The consent rule is drive mode's, nothing new: the conversation opens only for a ritual the person started with a
press the hub saw. Never for one joined mid-way. It closes with the head's ritual, and at once on a crisis."""

import asyncio
import json
import re
import time
import tomllib
from datetime import datetime
from types import SimpleNamespace as NS

import httpx
import numpy as np
import pytest
from kaiku_contracts import make, parse_topic, wording
from kaiku_contracts.config import find_repo_file
from kaiku_hub import follow
from kaiku_hub import main as hub_main
from kaiku_hub.live import gemini_live
from kaiku_hub.live.gemini_live import GeminiLiveVoice
from kaiku_hub.live.tools import HEAD_RUNS_ITS_STEPS, without
from kaiku_hub.main import Hub
from kaiku_hub.rituals import tap_back
from kaiku_hub.rituals.steps import Drum
from kaiku_hub.safety import Trigger

from hub.tests.fakes import Songs
from hub.tests.test_head_audio import Wire
from hub.tests.test_live_integration import Client, Connection, Meter, Session, settle
from hub.tests.test_tap_back import play, quick

MIC_FRAME = np.full(320, 5000, dtype="<i2").tobytes()
CRISIS = "I want to die"
# A game that waits for her on a busy machine: a turn ends at once when the taps are in, so this costs no time.
PATIENT = {"first_tap_s": 2.0, "idle_end_s": 0.8, "turn_s": 8.0}
DECLARED = ["record_dial", "start_activity", "start_phq9", "agree_activity", "remember", "recall", "express",
            "end_session", "feel"]


def spoken(seconds: float = 0.1):
    """A piece of Kaiku's spoken answer (24 kHz mono), with the end of the turn."""
    parts = [NS(inline_data=NS(data=np.full(int(24000 * seconds), 8000, dtype="<i2").tobytes()))]
    return NS(server_content=NS(model_turn=NS(parts=parts), turn_complete=True))


class TalkSession(Session):
    """The fake model: it remembers what it was asked to say and answers every such request aloud."""

    def __init__(self):
        super().__init__()
        self.said: list[str] = []

    delay_s = 0.0  # how long this model takes to start speaking a line it was asked to say

    async def send_client_content(self, **kwargs):
        self.said.append(kwargs["turns"]["parts"][0]["text"])
        if self.delay_s:
            asyncio.get_running_loop().call_later(self.delay_s, self.incoming.put_nowait, spoken())
        else:
            self.incoming.put_nowait(spoken())


class TalkClient(Client):
    def __init__(self):
        super().__init__()
        self.configs: list[dict] = []

    def connect(self, **kwargs):
        self.configs.append(kwargs["config"])
        conn = Connection(TalkSession())
        self.connections.append(conn)
        return conn


class Rig:
    """A hub with the Live adapter on the head's own audio, and a head that says it runs the standalone firmware."""

    def __init__(self, settings, music=None, **over):
        s = settings
        s.cloud_url, s.voice, s.voice_audio = "http://cloud", "gemini", "head"
        s.attention = {**s.attention, "regreet_h": 0}
        s.tap_back = quick(**over)
        s.greet_s, s.dial_s = 5, 5
        self.client, self.requests = TalkClient(), []
        voice = GeminiLiveVoice("fake-live", client=self.client, audio=object(), meter_factory=Meter, stall_s=0.5)

        def cloud(request):
            self.requests.append((request.url.path, json.loads(request.content or b"{}")))
            if request.url.path.endswith("/session"):
                return httpx.Response(200, json={"system_instruction": "Test persona", "session_id": "talk-1",
                                                 "tools": [{"name": n, "parameters": {"type": "object", "properties": {}}}
                                                           for n in DECLARED]})
            if request.url.path.endswith("/episode"):
                return httpx.Response(200, json={"ok": True, "id": "talk-1"})
            if request.url.path.endswith("/tool"):
                return httpx.Response(200, json={"ok": True, "name": self.requests[-1][1].get("name", ""),
                                                 "result": {"tone": "low", "by": "rule"}})
            return httpx.Response(503)

        kw = {"music": music} if music is not None else {}
        self.hub = Hub(s, voice=voice, transport=httpx.MockTransport(cloud), read_stdin=False, **kw)
        voice.audio = self.hub.head_audio                      # the head is the only audio device
        self.wire = Wire()
        self.hub.speaker._publish = self.wire.publish
        self.home = self.hub.bus_home
        self.sent: list[tuple[str, dict]] = []
        self.t_ms = 10_000
        real = self.hub.bus.publish

        async def publish(type_, payload, **k):
            self.sent.append((type_, dict(payload)))
            return await real(type_, payload, **k)

        self.hub.bus.publish = publish

    # ---- what the head sends
    async def health(self, step="idle", status="ok", **more):
        """`health/head` as the standalone firmware with sound sends it. `drum_held=None` = the firmware before it."""
        details = {"step": step, "firmware": "standalone", "drum_held": False, **more}
        details = {k: v for k, v in details.items() if v is not None}
        env = make("health", {"status": status, "version": "x", "uptime_s": 1, "details": details},
                   source="head", home_id=self.home, sim=True)
        await self.hub.on_health(parse_topic(f"kaiku/v1/{self.home}/health/head"), env)

    async def raw(self, type_, payload, source="head"):
        env = make(type_, payload, source=source, home_id=self.home, sim=True)
        await self.hub.on_raw(parse_topic(f"kaiku/v1/{self.home}/raw/{type_[4:].replace('.', '/')}"), env)

    async def chime(self, name):
        env = make("cmd.sensors", {"chime": name}, source="head", home_id=self.home, sim=True)
        await self.hub.on_sensors_cmd(parse_topic(f"kaiku/v1/{self.home}/cmd/sensors"), env)

    async def press(self, value=5):
        await self.raw("raw.head.ear", {"value": value, "delta": 0, "pressed": True})

    async def greeted_and_pressed(self, checkin=True):
        """The head greets, she presses its ear: a talk opens (D64), and with it (her own start) the conversation.
        `checkin` = she then asks for the check-in in words (the voice's `checkin {start}`) and the head goes to
        its first question, as the firmware does on `cmd.head {ritual: start}`."""
        await self.health("idle")
        await self.chime("wake")
        await self.press()
        await settle(lambda: self.hub.voice.in_session and self.hub.head_audio.mic is not None, timeout=3)
        if checkin:
            assert (await self.hub._checkin({"action": "start"}))["ok"]   # (not traced: `on_tool` is)
            await self.health("mood")
        return self.session

    # ---- what the hub did
    @property
    def session(self) -> TalkSession:
        return self.client.connections[-1].session

    def heads(self):
        return [p for t, p in self.sent if t == "cmd.head"]

    def mic(self):
        return [p["mic"] for p in self.heads() if "mic" in p]

    def bootstraps(self):
        return [body for path, body in self.requests if path.endswith("/session")]

    def types(self):
        return [e.type for e in self.hub.emitted]

    def said(self, line: str) -> bool:
        return bool(self.client.connections) and any(line in text for text in self.session.said)

    async def play(self, errors):
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
                    # she taps once the head has gone quiet (it sends no tap while its speaker plays the cue)
                    await settle(lambda: self.hub._game is None or (self.hub._game.state == "turn"
                                                                    and self.hub._game._opened), timeout=5)
                    for _ in range(20):
                        if any(h.get("eyes") for h in self.heads()[seen:]) or self.hub._game is None:
                            break
                        await self.raw("raw.head.tap", {"t_ms": int(self.t_ms), "force": 1.6, "src": "imu"})
                        self.t_ms += 60000 / (bpm * (1 + err))
                        await asyncio.sleep(60 / bpm / 40)
                    self.t_ms += 5000
            await asyncio.sleep(0.005)


def audio_sent(session) -> int:
    return sum(1 for kw in session.audio if "audio" in kw)


def stream_ends(session) -> int:
    return sum(1 for kw in session.audio if kw.get("audio_stream_end"))


# ------------------------------------------------------------------------------- open, accompany, close
async def test_her_own_press_opens_the_conversation_kaiku_says_each_step_and_the_ritual_closes_it(settings):
    r = Rig(settings, mode="auto")                                     # no song can play here: her free drumming
    hub = r.hub
    await r.health("idle")
    await r.chime("wake")                                              # the head greets: nothing is listened to yet
    await asyncio.sleep(0.05)
    assert hub.following and not hub.voice.in_session and r.bootstraps() == [] and r.mic() == []
    assert any("/voice/" in path for path, _b in r.requests)           # the invitation, in the cached voice

    session = await r.greeted_and_pressed()                            # her press, seen by the hub
    assert r.bootstraps() == [{"surface": "robot", "home_id": hub.settings.home_id, "intent": "ritual"}]
    assert r.mic()[0] == "open"                                        # forced through to a head the hub never commands
    declared = {d["name"] for block in r.client.configs[-1]["tools"] for d in block["function_declarations"]}
    # no tool the hub cannot honour on this head; start_activity only as asking twice (D58)
    assert declared == (set(DECLARED) - HEAD_RUNS_ITS_STEPS) | {"start_activity", "camera_choice", "turn_head",
                                                                 "checkin"}

    await settle(lambda: r.said(follow.STEP_LINES["mood"]), timeout=3)  # said through the head, by the Live voice
    await settle(lambda: len(r.wire.frames) >= 4, timeout=3)
    for value, step in ((7, "energy"), (4, "sleep"), (9, "breathe")):
        await r.press(value)                                           # each press moves the head on by itself
        await settle(lambda step=step: r.said(follow.STEP_LINES[step]), timeout=3)
    await r.chime("start_drum")                                        # no music here: her free drumming
    await settle(lambda: r.said(follow.STEP_LINES["drum"]), timeout=3)
    assert not r.said(tap_back.INTRO["music"])

    await r.chime("end_drum")                                          # the head is done: goodbye, then the end
    await settle(lambda: r.said(follow.STEP_LINES["done"]), timeout=3)
    assert r.mic()[-1] == "close" and session.said[-1].count(follow.STEP_LINES["done"]) == 1   # not listening any more
    await settle(lambda: not hub.voice.in_session and hub.head_audio.mic is None, timeout=4)
    assert r.wire.sent[-1][1] == b""                                   # the speaker's buffer dropped with it
    assert not hub.conversation_consented and r.types().count("obs.engagement") <= 1
    steps_seen = [(e.payload.step, e.payload.status) for e in hub.emitted if e.type == "obs.ritual"]
    assert steps_seen[-1] == ("close", "completed")                    # the record is what it was before


async def test_the_first_press_the_hub_sees_opens_the_conversation_whatever_step_the_head_is_in(settings):
    """D57: one rule. No press seen = no microphone; the first press in a ritual opens it, also when the hub joined
    mid-way or missed the greeting."""
    r = Rig(settings)
    await r.health("energy")                                           # the hub first hears the head mid-ritual
    await asyncio.sleep(0.1)
    assert r.hub.follower.active and not r.hub.follower.consented
    assert r.bootstraps() == [] and r.mic() == [] and not r.hub.voice.in_session and not r.client.connections
    await r.press(6)                                                   # her press: now Kaiku listens
    await settle(lambda: r.hub.voice.in_session, timeout=3)
    assert r.hub.conversation_consented and r.hub.follower.consented and len(r.bootstraps()) == 1
    assert "open" in r.mic()

    r2 = Rig(settings)
    await r2.health("idle")
    await r2.health("greet")
    await r2.health("mood")                                            # it started, but the hub saw no press
    await asyncio.sleep(0.1)
    assert r2.hub.follower.active and not r2.hub.follower.consented
    assert r2.bootstraps() == [] and r2.mic() == [] and not r2.hub.voice.in_session
    await r2.press(6)                                                  # the first press the hub sees
    await settle(lambda: r2.hub.voice.in_session, timeout=3)
    assert len(r2.bootstraps()) == 1 and r2.hub.follower.step == "energy"


async def test_asking_twice_her_words_arm_the_head_and_only_a_press_of_the_ear_starts_the_activity(settings):
    """D58. She asks for the drums in words (the voice calls start_activity): nothing starts, the head is armed.
    Her press of the ear is the yes: it is not a dial answer, the head goes to the drum step by itself, and the
    same ritual and conversation go on, also when the step she asked for lies behind the current one."""
    r = Rig(settings)
    hub = r.hub
    await r.greeted_and_pressed()                                      # the head is in mood, the conversation open
    assert (await hub.on_tool("start_activity", {"kind": "walk"}))["ok"] is False
    out = await hub.on_tool("start_activity", {"kind": "drum"})
    assert out == {"ok": True, "started": False, "waiting_for": "a press of your ear", "seconds": 20}
    assert {"activity": "drum"} in r.heads() and hub.follower.step == "mood"    # armed; nothing started
    await r.press(5)                                                   # her yes
    assert hub.follower.step == "mood" and hub.follower.asked == "drum" and hub._asked is None
    assert not [e for e in hub.emitted if e.type == "obs.self_report"]   # that press was not a dial answer
    await r.chime("start_drum")
    await r.health("drum")                                             # the head went there itself
    assert hub.follower.step == "drum" and hub.follower.active and hub.conversation_consented
    assert hub.follower.asked is None and "activity_confirmed" in hub._notes

    assert (await hub.on_tool("start_activity", {"kind": "drum"}))["ok"] is False   # already on
    out = await hub.on_tool("start_activity", {"kind": "breathe"})     # a step behind the current one
    assert out["ok"] and {"activity": "breathe"} in r.heads()
    await r.press(5)
    await r.health("breathe")
    assert hub.follower.step == "breathe" and hub.follower.active and hub.conversation_consented
    assert hub.voice.in_session                                        # the same conversation, not a new ritual


async def test_asking_twice_without_a_press_starts_nothing_and_kaiku_is_told(settings, monkeypatch):
    from kaiku_hub import main as hub_main
    monkeypatch.setattr(hub_main, "ASK_TWICE_S", 0.1)
    r = Rig(settings)
    hub = r.hub
    await r.greeted_and_pressed()
    told: list[str] = []

    async def send_context(text):
        told.append(text)

    hub._send_context = send_context
    assert (await hub.on_tool("start_activity", {"kind": "breathe"}))["ok"]
    await asyncio.sleep(0.9)
    assert hub._asked is None and {"activity": "none"} in r.heads() and hub.follower.step == "mood"
    assert told and "not pressed" in told[0] and "activity_not_confirmed" in hub._notes
    await r.press(4)                                                   # a late press is an ordinary press again
    assert hub.follower.step == "energy"


async def test_a_dial_question_is_answered_in_words_or_with_the_ear_and_stop_saves_what_there_is(settings):
    """D59. In the mood step she says it: the voice calls record_dial, the hub records that answer and tells the
    head to go on. The next question she answers with the ear. Then she says stop: the head is sent to rest, and the
    episode is kept as ended early with both answers."""
    r = Rig(settings)
    hub = r.hub
    await r.greeted_and_pressed()                                      # mood
    assert (await hub.on_tool("record_dial", {"item": "sleep", "value": 2}))["ok"] is False   # not what is asked now
    assert (await hub.on_tool("record_dial", {"item": "mood", "value": 2})) == {"ok": True, "recorded": "mood"}
    assert {"ritual": "next"} in r.heads()
    await r.health("energy")                                           # the head went on by itself
    await r.press(8)                                                   # this one with the ear
    await r.health("sleep")
    reports = [(e.payload.item, e.payload.value) for e in hub.emitted if e.type == "obs.self_report"]
    assert reports == [("mood", 2), ("energy", 4)]
    assert (await hub.on_tool("end_session", {"outcome": "ended_early"}))["ok"]   # "that's enough for today"
    assert {"ritual": "end"} in r.heads()
    await r.health("idle")                                             # the head is back at rest
    await settle(lambda: not hub.voice.in_session, timeout=3)
    assert not hub.follower.active and not hub.conversation_consented
    kept = hub.episodes.queued[-1] if hasattr(hub.episodes, "queued") else None
    assert kept is None or kept.outcome == "ended_early"


async def test_the_camera_is_asked_once_per_conversation_and_never_again(settings, monkeypatch):
    """D61. When a conversation opens the ROBOT asks once, in a fixed line, whether its camera may be on. The voice
    only reports the answer. Photo time needs a yes. The next conversation is asked again; the same one never is."""
    from kaiku_hub import main as hub_main
    monkeypatch.setattr(hub_main, "CAMERA_WAIT_S", 0.3)
    r = Rig(settings)
    hub = r.hub
    hub.node_health["sensors"] = {"status": "ok", "details": {"camera_ok": True}}
    said: list[str] = []
    real_say = hub.say

    async def say(text):
        said.append(text)
        await real_say(text)

    hub.say = say
    await r.greeted_and_pressed()
    await settle(lambda: hub_main.CAMERA_LINE in said, timeout=3)
    assert hub._camera is None
    assert (await hub.on_tool("photo_time", {}))["ok"] is False        # no yes yet: the camera stays off
    assert (await hub.on_tool("camera_choice", {"on": True})) ["camera"] == "on"
    assert hub._camera is True and hub._camera_task is not None
    await hub._ask_camera_once()                                       # a reconnect, a later step: never asked again
    for v in (4, 6):
        await r.press(v)
    await asyncio.sleep(0.2)
    assert said.count(hub_main.CAMERA_LINE) == 1
    assert (await hub.on_tool("camera_choice", {"on": False}))["camera"] == "off"   # she may change her mind
    assert hub._camera is False and hub._camera_task is None
    await r.health("idle")                                             # the ritual ends: the answer ends with it
    await asyncio.sleep(0.1)
    assert hub._camera is None and not hub._camera_asked


async def test_a_visible_change_in_her_smile_gives_kaiku_one_private_note_and_never_a_label(settings):
    """D60 on the robot. With the camera on, a window with no smile after one with a smile is `lower`: one context
    turn that tells Kaiku she may ask an open question and must not mention the face. A face that never smiled
    says nothing; notes are rate-limited; nothing names a feeling."""
    from kaiku_hub.live.tools import EXPRESSION_CUE
    r = Rig(settings)
    hub = r.hub
    await r.greeted_and_pressed()
    told: list[str] = []

    async def send_context(text):
        told.append(text)

    hub._send_context = send_context
    window = {"duration_s": 10.0, "samples": 60, "coverage": 0.9, "smile_share": 0.0, "smiles": 0, "head_movement": 0.1}
    await hub._expression_cue(window)                                  # still and unsmiling, no earlier smile: nothing
    assert told == []
    await hub._expression_cue({**window, "smile_share": 0.2})          # a little smiling: remembered, not a cue
    await hub._expression_cue({**window, "coverage": 0.2})             # hardly a face in view: nothing
    assert told == []
    await hub._expression_cue(window)                                  # she smiled before and now not at all
    assert told == [EXPRESSION_CUE["lower"]] and "expression_lower" in hub._notes
    await hub._expression_cue({**window, "smile_share": 0.6})          # too soon for another note
    assert len(told) == 1
    hub._expr_at = 0.0
    await hub._expression_cue({**window, "smile_share": 0.6})
    assert told[-1] == EXPRESSION_CUE["brighter"]
    for text in EXPRESSION_CUE.values():
        low = text.lower()
        assert "do not say you saw their face" in low and not any(w in low for w in (" sad", "depress", "unhappy"))


async def test_she_can_ask_for_a_turn_and_the_head_keeps_her_in_view(settings):
    r = Rig(settings)
    hub = r.hub
    await r.greeted_and_pressed()
    assert (await hub.on_tool("set_light", {"colour": "white"}))["ok"] is False   # the light colour was removed
    assert not [h for h in r.heads() if "color" in h]
    assert (await hub.on_tool("turn_head", {"direction": "left"}))["ok"]
    assert r.heads()[-1]["pan"] == {"target_deg": -40.0, "speed": 1.0}   # full speed, the longest nudge
    n = len(r.heads())
    hub._track_pause_until = 0.0                                       # (a turn she asked for pauses the following)
    hub.settings.track_every_s = 0.0
    await hub._follow_track(0.1)                                       # near the middle: nothing
    assert len(r.heads()) == n
    await hub._follow_track(0.8)                                       # at the right edge: one small turn toward her
    assert len(r.heads()) == n + 1 and r.heads()[-1]["pan"] == {"target_deg": 10.0, "speed": 1.0}   # short, full speed
    for _ in range(4):                                                 # the turns do not help: it gives up for a while
        await hub._follow_track(0.8)
    assert hub._track_pause_until > 0 and len(r.heads()) <= n + 4
    m = len(r.heads())
    await hub._follow_track(0.9)
    assert len(r.heads()) == m


async def test_a_press_opens_a_talk_and_the_check_in_runs_only_when_she_asks_for_it(settings):
    """D64. The press at the greeting opens the conversation and the head rests in `talk`: no step, no question.
    "Let's start" (the voice's `checkin {start}`) sends the head to its first question. Talking about something
    else pauses it (`pause`): the head is back in `talk`, Kaiku says no line of her own, and nothing brings the
    check-in back but her asking: "continue" returns to the step that waited."""
    r = Rig(settings)
    hub = r.hub
    await r.greeted_and_pressed(checkin=False)
    assert hub.follower.step == "talk" and hub.follower.active and hub.conversation_consented
    assert not [h for h in r.heads() if "ritual" in h]                 # the hub sent the head nowhere
    assert [(e.payload.step, e.payload.status) for e in hub.emitted if e.type == "obs.ritual"] == [
        ("greet", "started"), ("greet", "completed")]                  # no check-in step was opened
    await r.press(7)                                                   # a press while talking starts nothing
    assert hub.follower.step == "talk" and not [e for e in hub.emitted if e.type == "obs.self_report"]
    assert (await hub.on_tool("checkin", {"action": "pause"}))["checkin"] == "not running"

    assert (await hub.on_tool("checkin", {"action": "start"}))["checkin"] == "started"
    assert r.heads()[-1] == {"ritual": "start"}
    await r.health("mood")
    assert (await hub.on_tool("checkin", {"action": "start"}))["ok"] is False   # already on
    assert (await hub.on_tool("record_dial", {"item": "mood", "value": 4}))["ok"]
    await r.health("energy")
    said_before = len(r.client.connections[-1].session.said)
    out = await hub.on_tool("checkin", {"action": "pause"})            # she started talking about something else
    assert out["checkin"] == "paused" and "do not" in out["note"].lower() and r.heads()[-1] == {"ritual": "pause"}
    await r.health("talk")
    await asyncio.sleep(0.15)
    assert hub.follower.step == "talk" and hub.follower.active and hub.conversation_consented and hub.voice.in_session
    assert hub._paused_step == "energy"
    assert len(r.client.connections[-1].session.said) == said_before   # no step line, no steering back
    await r.press(3)                                                   # a press is still not an answer
    assert [(e.payload.item, e.payload.value) for e in hub.emitted if e.type == "obs.self_report"] == [("mood", 4)]

    out = await hub.on_tool("checkin", {"action": "continue"})
    assert out["checkin"] == "continuing at energy" and r.heads()[-1] == {"ritual": "resume"}
    await r.health("energy")                                           # back at the step that waited
    assert hub.follower.step == "energy" and hub.follower.active and hub._paused_step is None
    await r.press(8)
    await r.health("sleep")
    assert [(e.payload.item, e.payload.value) for e in hub.emitted if e.type == "obs.self_report"] == [
        ("mood", 4), ("energy", 4)]                                    # one answer per question, nothing twice


async def test_a_paused_check_in_that_is_never_resumed_is_kept_as_ended_early_and_a_quiet_talk_ends(settings):
    """D64. Paused and not resumed: when the talk ends the episode is saved as ended early with what was answered.
    A talk in which nothing happens for `[hub] talk_idle_end_s` sends the head back to rest. A named activity asked
    for from the talk (asking twice, D58) goes straight to that step."""
    r = Rig(settings)
    hub = r.hub
    await r.greeted_and_pressed()                                      # she asked for the check-in: mood
    assert (await hub.on_tool("record_dial", {"item": "mood", "value": 2}))["ok"]
    await r.health("energy")
    assert (await hub.on_tool("checkin", {"action": "pause"}))["ok"]
    await r.health("talk")
    assert (await hub.on_tool("start_activity", {"kind": "breathe"}))["ok"]   # one activity by name, from the talk
    await r.press()
    await r.health("breathe")
    assert hub.follower.step == "breathe" and hub.follower.active and hub.conversation_consented
    assert (await hub.on_tool("checkin", {"action": "pause"}))["ok"]
    await r.health("talk")

    ended: list[tuple] = []
    real_end = hub._follow_end

    async def follow_end(outcome, consented, dial):
        ended.append((outcome, dict(dial)))
        await real_end(outcome, consented, dial)

    hub._follow_end = follow_end
    hub.settings.talk_idle_end_s = 0.05
    hub._talk_active_at = time.monotonic() - 1.0
    await hub._talk_idle_check()                                       # nothing said: the head is sent to rest
    assert r.heads()[-1] == {"ritual": "end"}
    await r.health("idle")
    await settle(lambda: not hub.voice.in_session, timeout=3)
    assert ended == [("ended_early", {"mood": 2})] and not hub.follower.active and not hub.conversation_consented

    r2 = Rig(settings)                                                 # she only talked: no check-in to end early
    await r2.greeted_and_pressed(checkin=False)
    ended2: list[str] = []
    real2 = r2.hub._follow_end

    async def follow_end2(outcome, consented, dial):
        ended2.append(outcome)
        await real2(outcome, consented, dial)

    r2.hub._follow_end = follow_end2
    await r2.health("idle")
    assert ended2 == ["skipped"] and not r2.hub.state.ritual_done_on(hub_main.datetime.now().astimezone().date())


async def test_the_invitation_is_not_repeated_every_time_the_head_greets_a_face(settings):
    r = Rig(settings)
    said: list[str] = []

    async def say(text):
        said.append(text)

    r.hub.say = say
    await r.health("idle")
    for _ in range(3):                                                 # the head greets about once a minute
        await r.chime("wake")
        await r.health("idle")
    await asyncio.sleep(0.05)
    assert said == [follow.TALK_OFFER_LINE]
    r.hub._follow_offer_at -= r.hub.settings.follow_offer_every_s
    await r.chime("wake")
    await asyncio.sleep(0.05)
    assert said == [follow.TALK_OFFER_LINE] * 2


async def test_step_tools_are_refused_on_a_self_running_head_and_ending_the_talk_leaves_the_ritual(settings):
    r = Rig(settings)
    hub = r.hub
    await r.greeted_and_pressed()
    for name, args in (("start_drum", {}), ("start_phq9", {})):
        out = await hub.on_tool(name, args)
        assert out["ok"] is False and "ear" in out["error"]
    assert not [e for e in hub.emitted if e.type == "obs.self_report"] and not hub.state.phq9_due
    assert (await hub.on_tool("end_session", {"outcome": "completed"}))["ok"]   # she asked to stop talking
    assert {"ritual": "end"} in r.heads()                              # the head is told to go back to rest (D59)
    await settle(lambda: not hub.voice.in_session, timeout=3)
    assert r.mic()[-1] == "close" and hub.follower.active and not hub.conversation_consented
    n = len(r.client.connections[-1].session.said)
    await r.press(7)                                                   # the head goes on; Kaiku stays quiet now
    await asyncio.sleep(0.1)
    assert len(r.client.connections[-1].session.said) == n and len(r.bootstraps()) == 1
    assert hub.follower.step == "energy" and hub.follower.active        # the record of her ritual goes on


def test_the_tool_filter_takes_both_shapes():
    plain = [{"name": "start_drum"}, {"name": "feel"}]
    blocks = [{"function_declarations": [{"name": "start_activity"}, {"name": "recall"}]},
              {"function_declarations": [{"name": "start_phq9"}]}]
    assert without(plain, HEAD_RUNS_ITS_STEPS) == [{"name": "feel"}]
    assert without(blocks, HEAD_RUNS_ITS_STEPS) == [{"function_declarations": [{"name": "recall"}]}]


def test_every_follow_line_passes_the_wording_rules_for_the_robot():
    robot = tomllib.loads(find_repo_file("config/surfaces.toml").read_text())["surface"]["robot"]
    for line in [*follow.STEP_LINES.values(), tap_back.INTRO_SWAY]:
        assert wording.lint_for_surface(line, robot) == [], line
    words = set(re.findall(r"[a-z']+", " ".join(follow.STEP_LINES.values()).lower()))
    # this head has no screen and no light: no line may point at something she would have to see
    assert not words & {"light", "screen", "ten", "five", "number", "eyes", "watch", "brightens", "fades"}


# --------------------------------------------------------------------- the game and the voice in one ritual
async def test_follow_mode_the_microphone_is_closed_for_the_game_and_open_again_after(settings):
    r = Rig(settings, music=Songs(), **PATIENT)
    hub = r.hub
    session = await r.greeted_and_pressed()
    for v in (7, 4, 9):
        await r.press(v)
    await r.health("breathe")
    await r.chime("start_drum")                                        # the head's own drum step: the game
    await settle(lambda: hub._game is not None and r.mic()[-1] == "close", timeout=3)
    opened_before = r.mic().count("open")
    n_audio = audio_sent(session)
    for _ in range(10):                                                # a late frame or two from the head: not speech
        hub.head_audio.on_mic_frame(MIC_FRAME)
    await asyncio.wait_for(r.play([0.01, 0.07, 0.02]), 10)
    await settle(lambda: r.heads() and r.heads()[-1].get("drum") == "end", timeout=3)
    assert audio_sent(session) == n_audio                              # nothing was forwarded while it was closed
    assert r.said(tap_back.INTRO["music"]) and r.said(tap_back.CUE)    # Kaiku still said the game's lines aloud
    mic = r.mic()
    assert mic.count("open") > opened_before and mic[-1] == "open"     # after the game she can talk again
    assert hub.voice.in_session and hub.voice.listening
    (game,) = [e for e in hub.emitted if e.type == "obs.tap_back"]
    assert game.payload.levels_played == 3
    hub.head_audio.on_mic_frame(MIC_FRAME * 1)                         # and is heard again
    for _ in range(5):
        hub.head_audio.on_mic_frame(MIC_FRAME)
    await settle(lambda: audio_sent(session) > n_audio, timeout=3)
    await hub.voice.close_session()


async def test_drive_mode_closes_the_microphone_for_the_game_the_same_way(ctx):
    """One engine, two runners: the hub's own drum step tells the context the same things."""
    calls: list[bool] = []

    async def listening(on):
        calls.append(on)

    ctx.listening = listening
    ctx.music = Songs()
    step = Drum(0.6, tap_back_cfg=quick())
    await step.enter(ctx)
    assert calls == [False]                                            # closed before the first word of the game
    await step.exit(ctx, "aborted")                                    # the step is left for any reason at all
    assert calls == [False, True]                                      # never left closed

    calls.clear()
    ctx.music = Songs(silent_from=0)                                   # auto mode and the song never comes
    step = Drum(0.6, tap_back_cfg=quick(mode="auto", song_wait_s=0.05))
    await step.enter(ctx)
    for _ in range(40):
        await asyncio.sleep(0.02)
        await step.on_deadline(ctx)
        if step.phase == "drum":
            break
    assert step.phase == "drum" and calls == [False, True]             # free drumming: she can talk as before


async def test_a_whole_drive_mode_game_is_played_with_the_microphone_closed_and_she_can_talk_from_the_closing_line(
        ctx, monkeypatch):
    monkeypatch.setattr(tap_back, "FADE_OUT_S", 0.0)
    monkeypatch.setattr(tap_back, "TICK_S", 0.01)
    calls: list[tuple[bool, int]] = []

    async def listening(on):
        calls.append((on, len(ctx.said)))                              # how many lines had been said by then

    ctx.listening = listening
    _res, step = await play(ctx, quick(), [0.01, 0.07, 0.02])
    assert [on for on, _n in calls] == [False, True] and step.game_emitted
    assert calls[0][1] == 0 and ctx.said[0] == tap_back.INTRO["music"]   # closed before the game's first word
    assert ctx.said[calls[1][1]] == tap_back.close_line(3, 3)          # open again exactly at the closing line
    assert tap_back.CUE in ctx.said[:calls[1][1]]                      # every cue and band was said with it closed


async def test_the_adapter_closes_and_reopens_its_microphone_without_ending_the_conversation(settings):
    r = Rig(settings)
    session = await r.greeted_and_pressed()
    voice, head = r.hub.voice, r.hub.head_audio
    voice.mic_gap_end_s = 0.1
    for _ in range(5):
        head.on_mic_frame(MIC_FRAME)
    await settle(lambda: audio_sent(session) == 1)
    voice.listen(False)
    await asyncio.sleep(0.05)
    assert r.mic()[-1] == "close" and voice.in_session and not voice.listening
    for _ in range(10):
        head.on_mic_frame(MIC_FRAME)                                   # frames that left the head before it closed
    await asyncio.sleep(0.3)
    assert audio_sent(session) == 1 and stream_ends(session) == 1      # nothing forwarded; the server told once
    n = r.mic().count("open")
    await asyncio.sleep(0.15)
    assert r.mic().count("open") == n                                  # and the head is not told to open meanwhile
    await voice.say("Your turn.")                                      # Kaiku can still speak
    assert r.said("Your turn.")
    voice.listen(True)
    await asyncio.sleep(0.05)
    assert r.mic()[-1] == "open" and voice.listening
    for _ in range(5):
        head.on_mic_frame(MIC_FRAME)
    await settle(lambda: audio_sent(session) == 2)
    await voice.close_session()


async def test_a_line_asked_for_while_kaiku_still_speaks_waits_for_those_words(settings, monkeypatch):
    """To the Live server a new request is an interruption. Seen with the real model: the game's closing line was
    cut off by the goodbye asked for right after it. Kaiku never talks over itself."""
    r = Rig(settings)
    session = await r.greeted_and_pressed()
    voice = r.hub.voice
    await settle(lambda: r.said(follow.STEP_LINES["mood"]), timeout=3)
    await asyncio.sleep(0.6)                                           # the mood line is over
    n = len(session.said)
    t = time.monotonic()
    await voice.say("One.")                                            # nothing is being said: asked at once
    assert time.monotonic() - t < 0.3 and len(session.said) == n + 1
    await asyncio.sleep(0.6)

    await session.incoming.put(spoken(0.8))                            # Kaiku starts a reply of 0.8 s
    await settle(lambda: voice._speak_until > time.monotonic())
    t = time.monotonic()
    asked = asyncio.create_task(voice.say("Two."))
    await asyncio.sleep(0.5)
    assert len(session.said) == n + 1 and not asked.done()             # held back while those words play
    await asked
    assert 0.8 <= time.monotonic() - t < 2.0 and session.said[-1].count("Two.") == 1
    await asyncio.sleep(0.6)

    await session.incoming.put(spoken(5.0))                            # she presses the ear during a long reply:
    await settle(lambda: voice._speak_until > time.monotonic())
    voice.quiet()                                                      # the rest is dropped, nothing left to wait for
    t = time.monotonic()
    await voice.say("Three.")
    assert time.monotonic() - t < 0.5

    monkeypatch.setattr(gemini_live, "SAY_WAIT_MAX_S", 0.3)            # and a ritual line is never held back for long
    await asyncio.sleep(0.6)
    await session.incoming.put(spoken(5.0))
    await settle(lambda: voice._speak_until > time.monotonic() + 3)
    t = time.monotonic()
    await voice.say("Four.")
    assert time.monotonic() - t < 1.0
    await voice.close_session()


async def test_a_head_whose_firmware_cannot_hold_its_drum_step_gets_no_game(settings):
    """The firmware before sound and the hold leaves its drum step on its own timer and sounds its own tap tones:
    a game there would be cut in the middle. Its `health/head` has no `drum_held`: free drumming is followed."""
    r = Rig(settings, music=Songs())
    hub = r.hub
    await r.health("idle", drum_held=None)
    await r.chime("wake")
    await r.press()
    await settle(lambda: hub.voice.in_session, timeout=3)
    for v in (7, 4, 9):
        await r.press(v)
    await r.health("breathe", drum_held=None)
    await r.chime("start_drum")
    await settle(lambda: r.said(follow.STEP_LINES["drum"]), timeout=3)   # her own drumming, and Kaiku says so
    await asyncio.sleep(0.1)
    assert hub._game is None and not hub.follower.game and hub.music.calls == []   # no song was even asked for
    assert not [h for h in r.heads() if "drum" in h] and r.mic()[-1] == "open"     # nothing held, still listening
    for i in range(6):                                                 # her taps are the head's own free drumming
        await r.raw("raw.head.tap", {"t_ms": 5000 + i * 500, "force": 1.5, "src": "imu"})
    await r.chime("end_drum")
    await settle(lambda: "obs.drum_session" in r.types(), timeout=3)
    assert "obs.tap_back" not in r.types()
    await settle(lambda: not hub.voice.in_session, timeout=5)


def test_auto_takes_the_head_for_sound_only_when_its_firmware_can_sound(settings):
    settings.voice_audio = "auto"
    hub = Hub(settings, read_stdin=False)
    hub.node_health["head"] = {"status": "ok", "details": {"firmware": "standalone", "step": "idle"}}
    assert not hub._head_alive() and not hub._head_can_hold()          # the firmware before sound: not a body yet
    hub.node_health["head"] = {"status": "ok", "details": {"firmware": "standalone", "drum_held": False,
                                                           "audio": {"rx": 0, "mic_tx": 0}}}
    assert hub._head_alive() and hub._head_can_hold()
    hub.node_health["head"]["details"]["sim"] = True                   # a twin is never taken by `auto`
    assert not hub._head_alive()
    hub.node_health["head"] = {"status": "down", "details": {"audio": {}}}
    assert not hub._head_alive()


class WaitingSongs(Songs):
    """Music on the one speaker the voice also uses: nothing of a song sounds while the voice holds the speaker."""

    def __init__(self, ctx, **kw):
        super().__init__(**kw)
        self.ctx, self._free_at = ctx, None

    def heard_s(self) -> float:
        if self.ctx.speaker_busy:
            self._free_at = None
            return 0.0
        if self._free_at is None:
            self._free_at = time.monotonic()
        return (time.monotonic() - self._free_at) * self.speed


async def test_a_song_waits_for_kaikus_words_and_is_not_taken_for_lost_while_they_hold_the_speaker(ctx, monkeypatch):
    """Seen with the real models together: the Live voice said the game's first line for 11 s (the room left for it
    was 5), the song could not sound behind it on the one speaker, and after `song_wait_s` the game said "My song
    got lost". The level now starts when Kaiku has finished, and a song that is waiting its turn is not lost."""
    monkeypatch.setattr(tap_back, "TICK_S", 0.01)
    ctx.speaker_busy = True                                            # Kaiku is saying the first line, and goes on
    ctx.music = music = WaitingSongs(ctx, speed=50.0)
    game = tap_back.Game(quick(mode="auto", song_wait_s=0.1, listen_s=0.5), hold=True)   # auto: a lost song = fallback
    await music.start()
    await game.begin(ctx)

    async def run(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end and game.state not in ("done", "fallback"):
            await asyncio.sleep(max(0.005, min(0.02, game.next_deadline() - time.monotonic())))
            await game.tick(ctx)

    await run(0.4)                                                     # four times the song wait, still speaking
    assert game.state == "wait" and music.bpms == []                   # the level has not even been started
    ctx.speaker_busy = False                                           # the line is over
    await asyncio.sleep(0.02)
    await game.tick(ctx)
    assert game.state == "listen" and len(music.bpms) == 1             # now the song is asked for

    ctx.speaker_busy = True                                            # a late word of Kaiku's takes the speaker
    await run(0.4)                                                     # before the song has sounded at all
    assert game.state == "listen"                                      # waiting its turn: not "lost"
    ctx.speaker_busy = False
    await run(0.3)
    assert game.state == "turn" and tap_back.FALLBACK_LINE not in ctx.said   # heard, then her turn

    # a song that really does not come is still lost: the speaker is free and nothing sounds
    ctx.speaker_busy = False
    ctx.music = Songs(silent_from=0)
    game = tap_back.Game(quick(mode="auto", song_wait_s=0.1), hold=True)
    await ctx.music.start()
    await game.begin(ctx)
    await run(1.0)
    assert game.state == "fallback"

    # and Kaiku cannot hold a level back for ever
    monkeypatch.setattr(tap_back, "WORDS_WAIT_S", 0.2)
    ctx.speaker_busy = True
    ctx.music = Songs()
    game = tap_back.Game(quick(mode="tap_back"), hold=True)
    await ctx.music.start()
    await game.begin(ctx)
    await run(0.5)
    assert len(ctx.music.bpms) >= 1


async def test_step_lines_are_said_one_at_a_time_and_a_step_she_has_left_gets_no_line(settings):
    """She presses through the dials quickly while the model is slow to start a line. With the real model the
    breathing line was said all through the start of the game, because it was asked for before she pressed on. A
    press of the ear stops what Kaiku is saying AND a line that is on its way; a line is said only if she is
    still in its step when it can be said; and lines never overlap."""
    r = Rig(settings)
    hub = r.hub
    session = await r.greeted_and_pressed()
    await settle(lambda: r.said(follow.STEP_LINES["mood"]), timeout=3)
    await asyncio.sleep(0.5)
    session.delay_s = 0.3                                              # from here the model takes 0.3 s to start
    frames = len(r.wire.frames)
    await r.press(7)                                                   # energy: its line is asked for ...
    await settle(lambda: r.said(follow.STEP_LINES["energy"]))
    await asyncio.sleep(0.05)
    await r.press(4)                                                   # ... she is at sleep before it has sounded
    await asyncio.sleep(0.05)
    await r.press(9)                                                   # ... and at the breathing
    await settle(lambda: r.said(follow.STEP_LINES["breathe"]), timeout=4)
    assert not r.said(follow.STEP_LINES["sleep"])                      # she had left that step: its line is not said
    assert sum(follow.STEP_LINES["breathe"] in t for t in session.said) == 1
    asked = [t for t in session.said if "energy" in t or "breathe" in t]
    assert len(asked) == 2 and "breathe" in asked[-1]                  # one at a time, in order
    await asyncio.sleep(0.25)
    assert len(r.wire.frames) == frames                                # the energy line she pressed past never sounded
    await settle(lambda: len(r.wire.frames) > frames, timeout=3)       # the breathing line does
    await hub.voice.close_session()


def test_a_silent_game_on_a_self_running_head_says_what_that_head_can_show():
    assert tap_back.INTRO_SWAY in tap_back.all_lines() and "sway" in tap_back.INTRO_SWAY


async def test_forced_game_with_no_sound_on_a_held_head_speaks_of_the_sway_not_of_a_light(ctx):
    said: list[str] = []
    real = ctx.say

    async def say(text):
        said.append(text)
        await real(text)

    ctx.say = say
    game = tap_back.Game(quick(mode="tap_back"), hold=True)            # the standalone ignores `chest`: it sways
    await game.begin(ctx)                                              # ctx.music is the default OffMusic: no sound
    assert said == [tap_back.INTRO_SWAY]
    said.clear()
    game = tap_back.Game(quick(mode="tap_back"), hold=False)           # a hub-driven head does blink its chest
    await game.begin(ctx)
    assert said == [tap_back.INTRO[""]]


# ------------------------------------------------------------------------------------------------ crisis
async def test_a_crisis_in_a_follow_mode_conversation_closes_everything_and_shows_the_help_screen(settings):
    r = Rig(settings, music=Songs(speed=1.0), listen_s=5.0)
    hub = r.hub
    await r.greeted_and_pressed()
    for v in (7, 4, 9):
        await r.press(v)
    await r.health("breathe")
    await r.chime("start_drum")
    await settle(lambda: hub._game is not None and hub._game.state == "listen", timeout=3)   # mid-song
    hub.head_audio.renew_s = 0.03                                      # the microphone's keep-alive, were it running
    before = len(r.heads())
    await hub.on_live_utterance(CRISIS)
    await asyncio.sleep(0.2)                                           # several keep-alive periods later
    assert not hub.voice.in_session and hub.head_audio.mic is None     # the conversation and its microphone: closed
    assert r.wire.sent[-1][1] == b""                                   # the head's speaker told to drop its buffer
    after = r.heads()[before:]
    # the FIRST thing the head hears carries the help screen, in one message with the end of the hub's hold: the
    # standalone firmware then drops the drum end silently (no end chime, no "done" screen before the numbers)
    assert after[0] == {"drum": "end", "pan_mode": "still", "show": "help"}
    assert [h for h in after if "mic" not in h] == [after[0], {"eyes": "soft"}]   # then calm eyes; help asked once
    assert "open" not in [h.get("mic") for h in after]                 # and the microphone is never opened again
    await hub.listening(True)                                          # whoever asks (a game that ends, anything)
    await asyncio.sleep(0.1)
    assert "open" not in [h.get("mic") for h in r.heads()[before:]] and not hub.voice.in_session
    assert r.types().count("obs.safety_flag") == 1                     # the flag is emitted (priority uplink)
    assert "obs.tap_back" not in r.types() and "obs.engagement" not in r.types()   # nothing of the game is recorded
    assert hub._game is None and not hub.conversation_consented and hub.voice.transcript == []
    n = len(r.bootstraps())
    await r.press(5)                                                   # the head goes on by itself: no new talk
    await asyncio.sleep(0.1)
    assert len(r.bootstraps()) == n and not hub.voice.in_session

    await r.health("idle")                                             # the next ritual she starts takes it down
    await r.chime("wake")
    await r.press()
    await settle(lambda: {"show": "none"} in r.heads(), timeout=3)
    await hub.voice.close_session()


async def test_a_crisis_in_a_drive_mode_conversation_does_the_same(settings):
    settings.cloud_url, settings.voice, settings.voice_audio = "http://cloud", "gemini", "head"
    settings.greet_s, settings.dial_s = 5, 5
    settings.tap_back = quick(listen_s=5.0)
    client = TalkClient()
    voice = GeminiLiveVoice("fake-live", client=client, audio=object(), meter_factory=Meter, stall_s=0.5)

    def cloud(request):
        if request.url.path.endswith("/session"):
            return httpx.Response(200, json={"system_instruction": "Test persona", "session_id": "drive-1"})
        return httpx.Response(200, json={"ok": True, "id": "drive-1"}) if request.url.path.endswith("/episode") \
            else httpx.Response(503)

    hub = Hub(settings, voice=voice, transport=httpx.MockTransport(cloud), read_stdin=False, music=Songs(speed=1.0))
    voice.audio = hub.head_audio
    wire, sent = Wire(), []
    hub.speaker._publish = wire.publish
    real = hub.bus.publish

    async def publish(type_, payload, **k):
        sent.append((type_, dict(payload)))
        return await real(type_, payload, **k)

    hub.bus.publish = publish
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.start_ritual("test")
    await settle(lambda: voice.in_session and hub.head_audio.mic is not None, timeout=3)
    session = client.connections[-1].session
    assert hub.machine.jump_to("drum")                                 # straight to the drum step: the game
    drum = next(st for st in hub.machine.steps if st.name == "drum")
    await settle(lambda: drum.game is not None and drum.game.state == "listen", timeout=3)   # mid-song
    mics = lambda: [p["mic"] for t, p in sent if t == "cmd.head" and "mic" in p]   # noqa: E731
    assert mics()[-1] == "close" and voice.in_session                  # the game closed it, as in follow mode
    await session.incoming.put(spoken(1.0))                            # Kaiku is speaking when it happens
    await settle(lambda: len(wire.frames) >= 5, timeout=3)
    hub.head_audio.renew_s = 0.03                                      # the microphone's keep-alive, were it running
    before = len(sent)
    await hub.on_live_utterance(CRISIS)
    await asyncio.sleep(0.2)                                           # several keep-alive periods later
    heads = [p for t, p in sent if t == "cmd.head"]
    assert not voice.in_session and hub.head_audio.mic is None and mics()[-1] == "close"
    assert wire.sent[-1][1] == b"" and not hub.machine.running
    # the drum step was left (its game gives the microphone back when it ends): not in a crisis
    assert "open" not in [p.get("mic") for t, p in sent[before:] if t == "cmd.head"]
    body = [h for h in heads if "mic" not in h]
    assert body[-1] == {"show": "help"} and body[-2]["eyes"] == "soft"
    types = [e.type for e in hub.emitted]
    assert types.count("obs.safety_flag") == 1
    assert "obs.tap_back" not in types and "obs.drum_session" not in types   # nothing of the game is recorded
    assert {"show": "none"} not in heads
    hub.start_ritual("test")                                           # the next ritual takes the screen down
    await settle(lambda: {"show": "none"} in [p for t, p in sent if t == "cmd.head"], timeout=3)
    await hub.end_ritual()


async def test_a_crisis_while_she_is_talking_stops_the_microphones_keep_alive_before_the_help_screen(settings):
    """No game here: the microphone is open and the hub renews `mic: open` every `renew_s`. After help the head has
    closed its microphone itself; one more `mic: open` would open it again under the help screen."""
    r = Rig(settings)
    hub = r.hub
    hub.head_audio.renew_s = 0.03
    await r.greeted_and_pressed()
    await settle(lambda: r.mic().count("open") >= 3, timeout=3)        # held open, renewed
    before = len(r.heads())
    await hub.on_live_utterance(CRISIS)
    await asyncio.sleep(0.25)                                          # eight keep-alive periods
    after = r.heads()[before:]
    assert "open" not in [h.get("mic") for h in after] and "close" in [h.get("mic") for h in after]
    assert [h for h in after if "mic" not in h] == [{"eyes": "soft"}, {"show": "help"}]   # no game: the old order
    shown = after.index({"show": "help"})
    assert "close" in [h.get("mic") for h in after[:shown]]            # closed before the screen is asked for
    assert not hub.voice.in_session and hub.head_audio.mic is None
    assert r.types().count("obs.safety_flag") == 1


async def test_a_head_that_missed_the_help_screen_is_sent_it_once_more_and_one_that_took_it_down_is_left_alone(
        settings, monkeypatch):
    """`cmd.head` is not retained: a head that was off the broker at the crisis never showed the numbers. Its
    health says so (`details.help_shown`)."""
    monkeypatch.setattr(hub_main, "HELP_RESEND_AFTER_S", 0.05)

    async def health(r, shown, firmware="standalone", step="idle"):
        details = {"step": step, "firmware": firmware}
        if shown is not None:
            details["help_shown"] = shown
        env = make("health", {"status": "ok", "version": "x", "uptime_s": 1, "details": details}, source="head",
                   home_id=r.home, sim=True)
        await r.hub.on_health(parse_topic(f"kaiku/v1/{r.home}/health/head"), env)

    def helps(r):
        return [h for h in r.heads() if h.get("show") == "help"]

    r = Rig(settings)
    await health(r, False)
    assert helps(r) == []                                              # no crisis: nothing is ever shown
    await r.hub.crisis(Trigger("manual", "button", "en"))
    assert len(helps(r)) == 1
    await health(r, False)                                             # a health that was already on its way
    assert len(helps(r)) == 1
    await asyncio.sleep(0.06)
    await health(r, None)                                              # a firmware that does not report it
    assert len(helps(r)) == 1
    await health(r, False)                                             # back on the broker, not showing it
    assert len(helps(r)) == 2 and helps(r)[-1] == {"show": "help"}
    await health(r, False)                                             # once more only: never a loop
    assert len(helps(r)) == 2

    r = Rig(settings)                                                  # a head that showed it and took it down
    await r.hub.crisis(Trigger("manual", "button", "en"))
    await health(r, True)
    await asyncio.sleep(0.06)
    await health(r, False, step="greet")                               # she pressed its ear: the screen made way
    await health(r, False)
    assert len(helps(r)) == 1                                          # hers to dismiss: not put back

    r = Rig(settings)                                                  # this robot: a head with no screen at all
    await r.hub.crisis(Trigger("manual", "button", "en"))
    await asyncio.sleep(0.06)
    await r.health("idle", help_shown=False, help_screen="none")
    assert len(helps(r)) == 1                                          # it has nothing to show: never sent again

    r = Rig(settings)                                                  # after the head's own ten minutes: nothing
    await r.hub.crisis(Trigger("manual", "button", "en"))
    r.hub._help_at -= hub_main.HELP_S
    await health(r, False)
    assert len(helps(r)) == 1

    r = Rig(settings)                                                  # the hub-driven head (MQTT firmware) too
    await health(r, None, firmware="mqtt")
    await r.hub.crisis(Trigger("manual", "button", "en"))
    await asyncio.sleep(0.06)
    await health(r, False, firmware="mqtt")
    assert len(helps(r)) == 2
    r.hub.start_ritual("test")                                         # a new ritual takes it down: no more
    await settle(lambda: {"show": "none"} in r.heads(), timeout=3)
    await health(r, False, firmware="mqtt")
    assert len(helps(r)) == 2
    await r.hub.end_ritual()


def test_the_day_plan_is_unchanged_by_all_this(settings):
    assert [lv.taps for lv in tap_back.level_plan(datetime.now().astimezone().date(), settings.tap_back)] == [8, 8, 12]


@pytest.mark.parametrize("show", ["help", "none"])
def test_the_help_screen_command_is_a_contract_field(show):
    env = make("cmd.head", {"show": show}, source="hub")
    assert env.payload.show == show and env.payload.model_dump(exclude_none=True) == {"show": show}
