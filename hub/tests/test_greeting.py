"""See -> greet -> talk through the Hub: voice lines (cloud cache + fallback), companion session, Live config,
attention-driven ritual offer, "not now"."""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from kaiku_hub.cloudlink import CloudLink
from kaiku_hub.devices.unoq_yolo import box_to_face
from kaiku_hub.live.base import OffMusic, Voice
from kaiku_hub.live.gemini_live import live_config, tool_config
from kaiku_hub.live.lines import LinePlayer
from kaiku_hub.live.tools import TOOLS
from kaiku_hub.main import Hub


class RecordingVoice(Voice):
    name = "rec"

    def __init__(self):
        self.said = []

    async def say(self, text):
        self.said.append(text)

TZ = timezone(timedelta(hours=2))


def T(h, m=0, s=0.0):
    return datetime(2026, 11, 14, h, m, tzinfo=TZ) + timedelta(seconds=s)


def transport(handler):
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------- voice lines
async def test_line_from_cloud_cache_then_memory():
    calls = []

    def h(req):
        calls.append(req.url.path)
        return httpx.Response(200, content=b"RIFF....", headers={"content-type": "audio/wav"})

    lp = LinePlayer(cloud_url="http://cloud", transport=transport(h))
    assert await lp.say_line("greet.morning", "en") == "Good morning. I'm glad you're here."
    assert lp.last_source == "cloud" and calls == ["/v1/voice/greet.morning"]
    await lp.say_line("greet.morning", "en")
    assert lp.last_source == "cache" and len(calls) == 1


@pytest.mark.parametrize("status", [404, 503])
async def test_line_falls_back_to_text_when_cloud_has_no_audio(status):
    lp = LinePlayer(cloud_url="http://cloud", transport=transport(lambda r: httpx.Response(status, json={})))
    assert await lp.say_line("greet.evening", "fi") == "Hyvää iltaa. Mukava nähdä sinua."
    assert lp.last_source == "text"


async def test_line_offline_and_unknown_keys():
    def boom(req):
        raise httpx.ConnectError("down")

    lp = LinePlayer(cloud_url="http://cloud", transport=transport(boom))
    assert await lp.say_line("greet.two", "en") == "Oh, hello you two!"  # local fallback text
    assert lp.last_source == "text"
    assert LinePlayer(cloud_url=None).text("no.such.key") == "no.such.key"


# ---------------------------------------------------------------- companion session + Live config
async def test_companion_session_404_and_ok():
    cl = CloudLink(url="http://cloud", home_id="h", transport=transport(lambda r: httpx.Response(404)))
    assert await cl.companion_session() is None
    body = {"system_instruction": "You are Kaiku.", "tools": [], "model": "gemini-3.8-live", "voice": "Sulafat"}

    def ok(req):
        assert req.url.path == "/v1/companion/session"
        assert b'"surface":"robot"' in req.content and b'"intent":"ritual"' in req.content
        return httpx.Response(200, json=body)

    cl = CloudLink(url="http://cloud", home_id="h", transport=transport(ok))
    assert (await cl.companion_session())["voice"] == "Sulafat"
    assert await CloudLink(url=None, home_id="h").companion_session() is None


def test_live_config_fields():
    cfg = live_config("sys", TOOLS, "Sulafat")
    assert not cfg.get("enable_affective_dialog", False)
    assert "proactivity" not in cfg
    assert cfg["speech_config"]["voice_config"]["prebuilt_voice_config"]["voice_name"] == "Sulafat"
    assert cfg["tools"][0]["function_declarations"][0]["name"] == "record_dial"
    assert cfg["input_audio_transcription"] == {} and cfg["response_modalities"] == ["AUDIO"]  # no language given
    assert live_config("sys", TOOLS, "Sulafat", language="en")["input_audio_transcription"] == {"language_codes": ["en-US"]}
    blocks = [{"function_declarations": [{"name": "x"}]}]
    assert tool_config(blocks) == blocks and tool_config([]) == []


def test_unoq_box_to_face():
    f = box_to_face(480, 120, 640, 280, 640, 480, 0.91)
    assert f == {"x_norm": 0.75, "y_norm": -0.167, "size": 0.25, "confidence": 0.91}


# ---------------------------------------------------------------- hub: attention -> greeting -> offer
@pytest.fixture
def hub(settings):
    settings.demo_mode = False
    return Hub(settings, voice=RecordingVoice(), music=OffMusic(), read_stdin=False)


async def _approach(hub, start, faces=1, source_x=(0.2, -0.5)):
    for i in range(16):
        t = start + timedelta(seconds=0.2 * i)
        for k in range(faces):
            hub.attention.add_face({"x_norm": source_x[k], "y_norm": 0.0, "size": 0.05 + 0.02 * i,
                                    "confidence": 0.9}, t)
        await hub.attention_step(t)


async def test_person_approaching_greets_and_offers_ritual(hub, capsys):
    await _approach(hub, T(8))
    await asyncio.sleep(0.05)
    assert hub.attention.state == "at_desk"
    assert hub.machine.running and hub.ritual_reason == "attention"
    assert "Good morning" in capsys.readouterr().err  # English demo greeting by default
    assert any("check-in" in s for s in hub.voice.said)  # GREET step offers instead of greeting twice
    await hub.on_utterance("not now")
    await asyncio.sleep(0.05)
    assert not hub.machine.running and hub.attention.is_quiet(datetime.now().astimezone())
    assert any(e.type == "obs.ritual" and e.payload.status == "skipped" for e in hub.emitted)
    await hub.machine.abort()


async def test_two_people_no_offer(hub, capsys):
    await _approach(hub, T(8), faces=2)
    assert "hello you two" in capsys.readouterr().err
    assert not hub.machine.running


async def test_ritual_done_today_no_offer(hub, capsys):
    hub.state.mark_ritual_done(T(8).date())
    await _approach(hub, T(8))
    assert "Good morning" in capsys.readouterr().err
    assert not hub.machine.running


async def test_own_face_echo_ignored(hub):
    from kaiku_contracts import make, parse_topic

    env = make("raw.hub.face", {"x_norm": 0, "y_norm": 0, "size": 0.3, "confidence": 0.9}, source="hub",
               home_id=hub.settings.home_id)
    await hub.on_raw(parse_topic(f"kaiku/v1/{hub.settings.home_id}/raw/hub/face"), env)
    assert not hub.attention.faces_seen
    env = make("raw.hub.face", {"x_norm": 0, "y_norm": 0, "size": 0.3, "confidence": 0.9}, source="sensors",
               home_id=hub.settings.home_id)
    await hub.on_raw(parse_topic(f"kaiku/v1/{hub.settings.home_id}/raw/hub/face"), env)
    assert hub.attention.faces_seen


def test_live_config_validates_against_installed_sdk():
    types = pytest.importorskip("google.genai.types")
    c = types.LiveConnectConfig(**live_config("sys", TOOLS, "Sulafat", language="en"))
    assert c.input_audio_transcription.language_codes == ["en-US"]
    assert not c.enable_affective_dialog and c.proactivity is None
    assert c.speech_config.voice_config.prebuilt_voice_config.voice_name == "Sulafat"
