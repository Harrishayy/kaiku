"""Hub-level behaviour without a broker (bus offline -> publishes are dropped, obs still queued)."""

import asyncio
import sys

import pytest
from kaiku_contracts import OBS, example, make, parse_topic, validate
from kaiku_hub.live.base import OffMusic, Voice
from kaiku_hub.main import Hub


class RecordingVoice(Voice):
    name = "rec"

    def __init__(self):
        self.said, self.verbatim, self.interrupted = [], [], 0

    async def say(self, text):
        self.said.append(text)

    async def say_verbatim(self, text):
        self.verbatim.append(text)

    async def interrupt(self):
        self.interrupted += 1


@pytest.fixture
def hub(settings):
    settings.breathe_s = 10
    return Hub(settings, voice=RecordingVoice(), music=OffMusic(), read_stdin=False)


def types(hub):
    return [e.type for e in hub.emitted]


async def test_crisis_phrase_aborts_ritual_and_flags(hub):
    hub.start_ritual("test")
    await asyncio.sleep(0.05)
    assert hub.machine.running
    await hub.on_utterance("honestly I want to die")
    assert not hub.machine.running
    assert hub.voice.verbatim and "09 2525 0111" in hub.voice.verbatim[0]
    assert hub.voice.interrupted == 1
    flag = [e for e in hub.emitted if e.type == "obs.safety_flag"][0]
    assert flag.payload.trigger == "phrase" and flag.payload.handled_locally
    assert any(e.type == "obs.ritual" and e.payload.status == "aborted" for e in hub.emitted)
    # safety flag is first in the uplink queue
    assert hub.uplink._next_batch()[0][1].find("obs.safety_flag") > 0


async def test_crisis_does_not_load_llm_modules(hub):
    before = {m for m in sys.modules if m.startswith(("google", "kaiku_hub.live.gemini", "kaiku_hub.live.lyria"))}
    await hub.on_utterance("itsemurha")
    after = {m for m in sys.modules if m.startswith(("google", "kaiku_hub.live.gemini", "kaiku_hub.live.lyria"))}
    assert after == before


PHQ9_POS = {"total": 14, "items": [2, 2, 2, 2, 2, 1, 1, 1, 1], "item9_positive": True, "mode": "laptop"}


async def test_phq9_item9_from_local_producer(hub):
    env = validate({"home_id": hub.settings.home_id, "source": "laptop", "type": "obs.phq9", "payload": PHQ9_POS})
    await hub.on_obs(parse_topic(f"kaiku/v1/{hub.settings.home_id}/obs/phq9"), env)
    assert [e.payload.trigger for e in hub.emitted if e.type == "obs.safety_flag"] == ["phq9_item9"]
    assert hub.uplink.size() >= 1  # relayed to the cloud too


async def test_spoken_phq9_item9_runs_crisis_from_emit(hub):
    hub.settings.phq9_mode = "spoken"
    hub.state.phq9_due = True
    hub.start_ritual("test")
    await asyncio.sleep(0.05)
    await hub.emit("obs.phq9", {**PHQ9_POS, "mode": "spoken"})
    await asyncio.sleep(0.1)
    flags = [e for e in hub.emitted if e.type == "obs.safety_flag"]
    assert [f.payload.trigger for f in flags] == ["phq9_item9"]
    assert not hub.machine.running and hub.voice.verbatim


async def test_cmd_phq9_due_and_tools(hub):
    t = parse_topic(f"kaiku/v1/{hub.settings.home_id}/cmd/hub")
    await hub.on_cmd(t, validate({"home_id": hub.settings.home_id, "source": "cloud", "type": "cmd.hub",
                                  "payload": {"phq9_due": True}}))
    assert hub.state.phq9_due
    hub.state.phq9_due = False
    assert (await hub.on_tool("start_phq9", {}))["ok"] and hub.state.phq9_due
    assert (await hub.on_tool("log_mood", {"value": 3}))["ok"] is False  # v1 tool name is gone


@pytest.mark.parametrize("feeling,eyes", [
    ("happy", "happy"), ("curious", "listening"), ("sleepy", "sleepy"),
    ("cozy", "soft"), ("proud", "happy"),
])
async def test_express_maps_to_valid_eyes_without_changing_ritual_body(hub, feeling, eyes):
    hub.start_ritual("test")
    await asyncio.sleep(0.01)
    commands = []

    async def capture(type_, payload):
        commands.append(make(type_, payload, source="hub"))

    hub._cmd = capture
    assert await hub.on_tool("express", {"feeling": feeling}) == {"ok": True}
    assert commands[0].type == "cmd.head"
    assert commands[0].payload.model_dump(exclude_none=True) == {"eyes": eyes}
    assert hub._eyes == eyes
    await hub.end_ritual()


async def test_express_rejects_invalid_unconsented_and_post_crisis_calls(hub):
    commands = []

    async def capture(type_, payload):
        commands.append(make(type_, payload, source="hub"))

    hub._cmd = capture
    assert not (await hub.on_tool("express", {"feeling": "happy"}))["ok"]
    assert not commands
    hub.start_ritual("test")
    await asyncio.sleep(0.01)
    commands.clear()
    for args in ({}, {"feeling": "angry"}, {"feeling": 1}, {"feeling": "happy", "extra": "ignored"}):
        assert not (await hub.on_tool("express", args))["ok"]
    assert not commands
    await hub.on_utterance("I want to die")
    assert commands[-1].payload.eyes == "soft"
    commands.clear()
    assert not (await hub.on_tool("express", {"feeling": "happy"}))["ok"]
    assert not commands and hub._eyes == "soft"


async def test_express_preserves_thinking_priority_and_updates_restore_target(hub):
    hub.start_ritual("test")
    await asyncio.sleep(0.01)
    commands = []

    async def capture(type_, payload):
        commands.append(make(type_, payload, source="hub"))

    hub._cmd = capture
    hub.thinking = 1
    assert (await hub.on_tool("express", {"feeling": "curious"}))["ok"]
    assert not commands and hub._eyes == "listening"
    hub.thinking = 0
    await hub.end_ritual()


async def test_button_long_press_and_short_press(hub):
    t = parse_topic(f"kaiku/v1/{hub.settings.home_id}/raw/sensors/button")

    def btn(pressed):
        return validate({"home_id": hub.settings.home_id, "source": "sensors", "type": "raw.sensors.button",
                         "payload": {"id": "top", "pressed": pressed}, "sim": True})

    await hub.on_raw(t, btn(True))
    await hub.on_raw(t, btn(False))  # short press -> ritual starts
    assert hub.machine.running
    hub.button.hold_s = 0.1
    await hub.on_raw(t, btn(True))
    await asyncio.sleep(0.3)  # watcher fires while still held
    assert [e.payload.trigger for e in hub.emitted if e.type == "obs.safety_flag"] == ["manual"]
    assert not hub.machine.running
    assert all(e.sim for e in hub.emitted)  # derived from sim inputs -> flagged sim


async def test_head_button_build_dial_by_press_count(hub):
    """Button build: idle short press starts a ritual; a run of presses answers the dial; long press = safety."""
    hub.settings.dial_input = "button"
    hub.presses.window_s = 1.0
    t = parse_topic(f"kaiku/v1/{hub.settings.home_id}/raw/head/button")

    def btn(pressed):
        return validate({"home_id": hub.settings.home_id, "source": "head", "type": "raw.head.button",
                         "payload": {"id": "head", "pressed": pressed}, "sim": True})

    async def press_run(n):
        for _ in range(n):
            await hub.on_raw(t, btn(True))
            await hub.on_raw(t, btn(False))
        await asyncio.sleep(1.25)

    await press_run(1)  # idle -> ritual starts
    assert hub.machine.running
    await press_run(1)  # greet: any answer goes on
    await press_run(3)  # dial: mood = 3
    moods = [e.payload.value for e in hub.emitted if e.type == "obs.self_report" and e.payload.item == "mood"]
    assert moods == [3]
    assert any("button" in x for x in hub.voice.said)  # button wording, not "turn my ear"
    hub.button.hold_s = 0.1
    await hub.on_raw(t, btn(True))
    await asyncio.sleep(0.3)
    assert [e.payload.trigger for e in hub.emitted if e.type == "obs.safety_flag"] == ["manual"]


async def test_cmd_hub_say_goes_through_gate_and_start(hub):
    t = parse_topic(f"kaiku/v1/{hub.settings.home_id}/cmd/hub")
    cmd = validate({"home_id": hub.settings.home_id, "source": "cloud", "type": "cmd.hub",
                    "payload": {"say": "en jaksa enää"}})
    await hub.on_cmd(t, cmd)
    await hub.on_cmd(t, cmd)  # duplicate id ignored
    assert len([e for e in hub.emitted if e.type == "obs.safety_flag"]) == 1
    s = validate({"home_id": hub.settings.home_id, "source": "cloud", "type": "cmd.hub",
                  "payload": {"suggest_nudge": {"arm": "friend_ping"}, "clinician_message": {"text": "Hi Aino"}}})
    await hub.on_cmd(t, s)
    assert (await hub.get_nudge())[0] == "friend_ping"
    assert any("Hi Aino" in x for x in hub.voice.said)


async def test_adhoc_mood_and_light(hub):
    hub.settings.light_enabled = True
    hub.light.window_min = 0.0001
    from datetime import timedelta

    hub.light.window = timedelta(milliseconds=1)
    ear = validate({"home_id": hub.settings.home_id, "source": "head", "type": "raw.head.ear",
                    "payload": {"value": 2, "delta": 0, "pressed": True}})
    await hub.on_raw(parse_topic(f"kaiku/v1/{hub.settings.home_id}/raw/head/ear"), ear)
    light = example("raw.sensors.light", home_id=hub.settings.home_id)
    lt = parse_topic(f"kaiku/v1/{hub.settings.home_id}/raw/sensors/light")
    await hub.on_raw(lt, light)
    await asyncio.sleep(0.01)
    from datetime import UTC, datetime
    await hub.on_raw(lt, light.model_copy(update={"ts": datetime.now(UTC)}))
    assert "obs.self_report" in types(hub) and "obs.light_level" in types(hub)
    adhoc = next(e for e in hub.emitted if e.type == "obs.self_report").payload
    assert (adhoc.item, adhoc.value, adhoc.context) == ("mood", 2, "adhoc")


def test_every_emitted_type_is_a_registered_obs():
    """Contract test: grep the hub for emitted types; all must be registered obs types."""
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "kaiku_hub"
    found = set()
    for f in src.rglob("*.py"):
        found |= set(re.findall(r'emit\(\s*"(obs\.[a-z_]+)"', f.read_text()))
    assert found, "no emits found"
    assert found <= set(OBS), found - set(OBS)


# ---------------------------------------------------------------- cloud tool forwarding (plan 03 §3)
class FakeCloud:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    async def companion_tool(self, name, args, session_id=None, timeout_s=4.0):
        self.calls.append((name, args, session_id))
        return self.reply


async def test_memory_tool_is_forwarded_to_cloud(hub):
    hub.cloud = FakeCloud({"ok": True, "name": "remember", "result": {"id": 7}})
    hub._session_id = "s1"
    out = await hub.on_tool("remember", {"category": "people", "text": "sister is Maija"})
    assert out == {"ok": True, "id": 7}
    assert hub.cloud.calls == [("remember", {"category": "people", "text": "sister is Maija"}, "s1")]


async def test_refused_memory_tool_returns_error_not_crash(hub):
    hub.cloud = FakeCloud({"ok": False, "name": "remember", "error": "not something I keep"})
    out = await hub.on_tool("remember", {"category": "health", "text": "x"})
    assert out["ok"] is False and out["error"]


async def test_crisis_in_tool_args_runs_the_deterministic_crisis_path(hub):
    hub.cloud = FakeCloud({"ok": False, "name": "remember", "crisis": True, "result": {}})
    await hub.on_tool("remember", {"category": "plans", "text": "..."})
    assert hub.voice.verbatim, "scripted crisis message must be spoken verbatim"
    assert "obs.safety_flag" in types(hub)


async def test_cloud_offline_tool_degrades_softly(hub):
    hub.cloud = FakeCloud(None)
    assert (await hub.on_tool("recall", {"topic": "walk"}))["ok"] is False
    assert (await hub.on_tool("end_session", {}))["ok"] is True  # still ends politely


async def test_camera_light_summary_keeps_capture_time_and_quality(hub):
    hub.settings.light_enabled = True
    from datetime import UTC, datetime, timedelta

    capture = datetime(2026, 11, 10, 10, tzinfo=UTC)
    hub.light.window = timedelta(seconds=60)
    topic = parse_topic(f'kaiku/v1/{hub.settings.home_id}/raw/sensors/light')
    for offset, value, quality in [(0, 100, .8), (30, 200, .6), (61, 300, .9)]:
        sample = make('raw.sensors.light', {'raw': value, 'lux_est': value}, source='sensors', home_id=hub.settings.home_id,
                      ts=capture + timedelta(seconds=offset), quality=quality)
        await hub.on_raw(topic, sample)
    result = next(e for e in hub.emitted if e.type == 'obs.light_level')
    assert result.ts == capture + timedelta(seconds=30) and result.quality == .6
    assert result.payload.lux_est == 150


async def test_default_light_disabled_produces_no_observation_or_context(hub):
    from datetime import UTC, datetime, timedelta

    assert not hub.settings.light_enabled
    topic = parse_topic(f'kaiku/v1/{hub.settings.home_id}/raw/sensors/light')
    captured = datetime.now(UTC)
    for offset in (0, 3700):
        sample = make('raw.sensors.light', {'raw': 10, 'lux_est': 10}, source='sensors',
                      home_id=hub.settings.home_id, ts=captured + timedelta(seconds=offset))
        await hub.on_raw(topic, sample)
    assert hub.light._values == []
    assert not any(e.type == 'obs.light_level' for e in hub.emitted)


def test_timings_moved_to_config_keep_their_values():
    """Numbers that used to be constants in the code are read from config/kaiku.toml with the same values."""
    from kaiku_hub.live import meter
    from kaiku_hub.live.tools import ASK_TWICE_TOOL, ask_twice_tool
    from kaiku_hub.settings import Settings

    s = Settings.load()
    got = (s.crisis_dedupe_s, s.help_screen_s, s.think_timeout_s, s.attention_hz, s.long_press_s, s.ask_twice_s,
           s.camera_wait_s, s.turn_deg, s.turn_pulse_s, s.turn_pause_s, s.track_better_min, s.face_signs_quality,
           s.photo_wait_extra_s, s.cloud_timeout_s, s.nudge_timeout_s, s.session_timeout_s, s.command_poll_s,
           s.health_report_s, s.session_attempts, s.session_backoff_s)
    assert got == (60, 600, 8, 5, 2, 20, 12, 40, 0.45, 20, 0.08, 0.6, 6, 5, 3, 4, 3, 10, 3, 0.5)
    assert meter.open_estimate_min() == 5
    bare = Settings()                                           # the built-in defaults say the same
    assert (bare.ask_twice_s, bare.think_timeout_s, bare.face_signs_quality) == (20, 8, 0.6)
    assert ask_twice_tool(20) is ASK_TWICE_TOOL                 # the voice is told the wait the hub really keeps
    assert "the next 9 seconds" in ask_twice_tool(9)["description"]
