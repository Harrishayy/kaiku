"""Hub-level behaviour without a broker (bus offline -> publishes are dropped, obs still queued)."""

import asyncio
import sys

import pytest
from kaiku_contracts import OBS, example, parse_topic, validate
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
    await hub.on_raw(lt, light)
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
