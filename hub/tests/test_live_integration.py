"""Exercise the production Live adapter and Hub controller with injected audio/model edges."""

import asyncio
import json
from types import SimpleNamespace as NS

import httpx
import pytest
from kaiku_contracts import make, parse_topic
from kaiku_hub.live.gemini_live import GeminiLiveVoice
from kaiku_hub.main import Hub
from kaiku_hub.rituals.machine import Event


class Stream:
    def __init__(self, **kwargs):
        self.callback = kwargs.get("callback")
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True


class Audio:
    def __init__(self):
        self.inputs, self.outputs = [], []

    def RawInputStream(self, **kwargs):
        stream = Stream(**kwargs)
        self.inputs.append(stream)
        return stream

    def RawOutputStream(self, **kwargs):
        stream = Stream(**kwargs)
        self.outputs.append(stream)
        return stream


class Meter:
    def __init__(self, *args):
        self.stopped = False

    def open(self):
        pass

    def start(self, callback):
        pass

    def stop(self):
        self.stopped = True


class Session:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.audio = []
        self.responses = []

    async def send_realtime_input(self, **kwargs):
        self.audio.append(kwargs)

    async def send_client_content(self, **kwargs):
        pass

    async def send_tool_response(self, **kwargs):
        self.responses.append(kwargs)

    async def receive(self):
        while True:
            msg = await self.incoming.get()
            if isinstance(msg, Exception):
                raise msg
            yield msg


class Connection:
    def __init__(self, session):
        self.session = session
        self.closed = False

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *args):
        await asyncio.sleep(0)  # reproduces the old receive-task self-cancellation
        self.closed = True


class Client:
    def __init__(self):
        self.connections = []
        self.aio = NS(live=self)

    def connect(self, **kwargs):
        conn = Connection(Session())
        self.connections.append(conn)
        return conn


async def settle(predicate, timeout=2):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


def speech(text):
    return NS(server_content=NS(input_transcription=NS(text=text)))


def finished_speech(text=""):
    return NS(server_content=NS(input_transcription=NS(text=text, finished=True)))


def pcm(data=b"\x01\x00" * 30):
    return NS(server_content=NS(model_turn=NS(parts=[NS(inline_data=NS(data=data))])))


@pytest.fixture
def rig(settings):
    settings.cloud_url = "http://cloud"
    settings.hub_transcripts = True
    settings.greet_s = 10
    client, audio = Client(), Audio()
    voice = GeminiLiveVoice("fake-live", client=client, audio=audio, meter_factory=Meter, stall_s=0.001)
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/session"):
            return httpx.Response(200, json={"system_instruction": "Test persona", "session_id": "test-session"})
        if request.url.path.endswith("/episode"):
            return httpx.Response(200, json={"ok": True, "id": "test-session"})
        return httpx.Response(503)

    hub = Hub(settings, voice=voice, transport=httpx.MockTransport(handler), read_stdin=False)
    return hub, voice, client, audio, requests


async def test_invitation_never_opens_mic_until_press_and_timeout_is_no(rig):
    hub, voice, client, audio, _ = rig
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.machine.steps[0].timeout_s = 0.08
    hub.start_ritual("attention")
    await asyncio.sleep(0.02)
    hub.machine.feed(Event("ear", {"pressed": False}))
    hub.machine.feed(Event("utterance", {"text": "what time is it?"}))
    await settle(lambda: not hub.machine.running)
    assert not client.connections and not audio.inputs
    assert hub.machine.results == {"greet": "skipped"}
    hub.machine.steps[0].timeout_s = 10
    hub.start_ritual("command")
    await asyncio.sleep(0.01)
    hub.machine.feed(Event("ear", {"pressed": True}))
    await settle(lambda: bool(audio.inputs))
    audio.inputs[-1].callback(b"\x00\x00" * 160, 160, None, None)
    await settle(lambda: bool(client.connections[-1].session.audio))
    assert hub.conversation_consented
    await hub.end_ritual()
    assert audio.inputs[-1].closed


async def test_spoken_crisis_finishes_flag_and_removes_transcript(rig, capsys):
    hub, voice, client, audio, _ = rig
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.start_ritual("text")
    await settle(lambda: bool(audio.inputs))
    session = client.connections[0].session
    await session.incoming.put(speech("I want"))
    await session.incoming.put(speech(" to die"))
    await settle(lambda: any(e.type == "obs.safety_flag" for e in hub.emitted))
    assert not hub.machine.running and voice._session is None
    assert audio.inputs[0].closed and audio.outputs[0].closed
    assert client.connections[0].closed
    assert "***" in capsys.readouterr().err
    payload = json.loads(hub.episodes.db.execute("SELECT payload FROM episodes").fetchone()[0])
    assert payload["outcome"] == "crisis" and payload["transcript"] is None


async def test_interim_transcription_crisis_stops_before_final_text(rig):
    hub, voice, client, audio, _ = rig
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.start_ritual("text")
    await settle(lambda: bool(audio.inputs))
    session = client.connections[0].session
    await session.incoming.put(NS(server_content=NS(interim_input_transcription=NS(text="I want to die"))))
    await settle(lambda: any(e.type == "obs.safety_flag" for e in hub.emitted))
    assert not hub.machine.running and voice._session is None
    payload = json.loads(hub.episodes.db.execute("SELECT payload FROM episodes").fetchone()[0])
    assert payload["outcome"] == "crisis" and payload["transcript"] is None


async def test_tool_end_stops_all_steps_and_activity_jumps_exactly(rig):
    hub, voice, _, audio, _ = rig
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.start_ritual("text")
    await settle(lambda: bool(audio.inputs))
    result = await hub.on_tool("start_activity", {"kind": "drum"})
    assert result["ok"]
    await settle(lambda: hub.machine.state == "drum")
    assert "dial" not in hub.machine.results and "breathe" not in hub.machine.results
    result = await hub.on_tool("end_session", {})
    assert result["ok"] and not hub.machine.running and voice._session is None
    await asyncio.sleep(0.02)
    assert hub.machine.state == "idle"
    assert "nudge" not in hub.machine.results


async def test_barge_in_clears_buffer_while_cloud_tool_is_blocked(rig):
    hub, voice, client, audio, _ = rig
    blocked = asyncio.Event()

    async def tool(name, args):
        await blocked.wait()
        return {"ok": True}

    await voice.start(hub.on_utterance, tool)
    hub.start_ritual("text")
    await settle(lambda: bool(audio.outputs))
    session = client.connections[0].session
    await session.incoming.put(NS(tool_call=NS(function_calls=[NS(id="1", name="recall", args={})])))
    await session.incoming.put(pcm())
    await settle(lambda: bool(voice._pcm))
    await session.incoming.put(NS(server_content=NS(interrupted=True)))
    await settle(lambda: not voice._pcm)
    out = bytearray(60)
    audio.outputs[0].callback(out, 30, None, None)
    assert out == bytes(60)
    blocked.set()
    await settle(lambda: bool(session.responses))
    await hub.end_ritual()


async def test_bootstrap_auth_failure_never_connects(rig):
    hub, voice, client, audio, _ = rig
    hub.cloud.transport = httpx.MockTransport(lambda request: httpx.Response(401))
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.start_ritual("text")
    await asyncio.sleep(0.05)
    assert not client.connections and not audio.inputs
    await hub.end_ritual()


async def test_command_ack_retries_without_reapplying(rig):
    hub, _, _, _, requests = rig
    command = make("cmd.hub", {"phq9_due": True}, source="cloud", home_id=hub.settings.home_id)
    await hub._republish_cloud_cmd(command)
    hub.state.phq9_due = False
    await hub._republish_cloud_cmd(command)
    assert not hub.state.phq9_due
    assert len([r for r in requests if r.url.path.endswith("/ack")]) == 2


async def test_ppg_envelope_quality_reaches_step(rig):
    hub, _, _, _, _ = rig
    hub.start_ritual("test")
    await asyncio.sleep(0.01)
    hub.machine.jump_to("breathe")
    await settle(lambda: hub.machine.state == "breathe")
    env = make("raw.sensors.ppg", {"t0_ms": 1000, "fs_hz": 100, "samples": [1] * 50},
               source="sensors", home_id=hub.settings.home_id, quality=0.1)
    await hub.on_raw(parse_topic(f"kaiku/v1/{hub.settings.home_id}/raw/sensors/ppg"), env)
    await asyncio.sleep(0.01)
    step = next(s for s in hub.machine.steps if s.name == "breathe")
    assert step.buf.quality == 0.1 and step.buf.next_ms == 1500
    await hub.end_ritual()


async def test_resumption_and_explicit_stop_cancel_reconnect(rig):
    hub, voice, client, audio, _ = rig
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.start_ritual("text")
    await settle(lambda: bool(audio.inputs))
    first = client.connections[0].session
    await first.incoming.put(NS(session_resumption_update=NS(resumable=True, new_handle="synthetic-handle")))
    await first.incoming.put(ConnectionError("synthetic disconnect"))
    await settle(lambda: len(client.connections) == 2)
    assert audio.inputs[0].closed
    await settle(lambda: len(audio.inputs) == 2)
    await client.connections[1].session.incoming.put(ConnectionError("synthetic disconnect"))
    await settle(lambda: voice._session is None)
    await hub.end_ritual()
    await asyncio.sleep(2.1)
    assert len(client.connections) == 2 and voice._session is None


async def test_session_duration_closes_microphone(rig):
    hub, voice, _, audio, _ = rig
    voice.max_seconds = 0.05
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.start_ritual("text")
    await settle(lambda: bool(audio.inputs))
    await settle(lambda: audio.inputs[0].closed)
    assert voice._session is None
    await hub.end_ritual()


async def test_normal_episode_keeps_only_opted_in_transcript(rig):
    hub, voice, client, audio, requests = rig
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.start_ritual("text")
    await settle(lambda: bool(audio.inputs))
    await client.connections[0].session.incoming.put(speech("Hello synthetic companion"))
    await settle(lambda: bool(voice.transcript))
    await hub.end_ritual()
    assert await hub.episodes.flush() == 1
    posted = json.loads(next(r.content for r in requests if r.url.path.endswith("/episode")))
    assert posted["transcript"] == [{"role": "person", "text": "Hello synthetic companion", "complete": None}]
    assert posted["outcome"] == "ended_early" and posted["id"] == "test-session"


@pytest.mark.parametrize("interrupted_final_frame", [False, True])
async def test_transcript_completion_uses_speaker_markers_not_audio_boundary(rig, interrupted_final_frame):
    hub, voice, client, audio, requests = rig
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.start_ritual("text")
    await settle(lambda: bool(audio.inputs))
    session = client.connections[0].session
    await session.incoming.put(speech("Exact received words"))
    await session.incoming.put(NS(server_content=NS(turn_complete=True)))
    await settle(lambda: bool(voice.transcript))
    assert voice.transcript[0]["complete"] is None
    await session.incoming.put(finished_speech())
    await session.incoming.put(NS(server_content=NS(output_transcription=NS(text="Exact reply", finished=True))))
    if interrupted_final_frame:
        await session.incoming.put(NS(server_content=NS(
            output_transcription=NS(text="Interrupted reply", finished=True), interrupted=True)))
    else:
        await session.incoming.put(NS(server_content=NS(output_transcription=NS(text="Interrupted reply"))))
        await session.incoming.put(NS(server_content=NS(interrupted=True)))
    await settle(lambda: len(voice.transcript) == 3 and voice.transcript[-1]["complete"] is False)
    await hub.end_ritual()
    assert await hub.episodes.flush() == 1
    posted = json.loads(next(r.content for r in requests if r.url.path.endswith("/episode")))
    assert posted["transcript"] == [
        {"role": "person", "text": "Exact received words", "complete": True},
        {"role": "kaiku", "text": "Exact reply", "complete": True},
        {"role": "kaiku", "text": "Interrupted reply", "complete": False},
    ]


async def test_final_marker_cannot_hide_transcript_truncation(rig):
    _, voice, _, _, _ = rig
    voice._remember("person", "x" * 2100)
    voice._finish_transcript("person", True)
    assert voice.transcript == [{"role": "person", "text": "x" * 2000, "complete": False}]


async def test_streaming_transcription_dispatches_only_completed_utterances(rig):
    hub, voice, client, audio, _ = rig
    completed = []

    async def capture(text):
        completed.append(text)

    voice.on_completed_utterance = capture
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.start_ritual("text")
    await settle(lambda: bool(audio.inputs))
    session = client.connections[0].session
    await session.incoming.put(speech("3"))
    await session.incoming.put(speech(" today"))
    await settle(lambda: voice._input_text == "3 today")
    assert completed == []
    await session.incoming.put(finished_speech(" I think"))
    await settle(lambda: len(completed) == 1)
    await session.incoming.put(NS(server_content=NS(turn_complete=True)))
    await session.incoming.put(speech("2"))
    await session.incoming.put(speech(" yesterday"))
    await session.incoming.put(NS(server_content=NS(turn_complete=True)))
    await settle(lambda: len(completed) == 2)
    assert completed == ["3 today I think", "2 yesterday"]
    await hub.end_ritual()


@pytest.mark.parametrize("tool_first", [False, True])
async def test_live_dial_answer_is_written_once_in_both_tool_transcript_orders(rig, tool_first):
    hub, voice, client, audio, _ = rig
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.start_ritual("text")
    await settle(lambda: bool(audio.inputs))
    hub.machine.jump_to("dial")
    await settle(lambda: hub.machine.state == "dial")
    session = client.connections[0].session

    async def record_mood():
        await session.incoming.put(NS(tool_call=NS(function_calls=[
            NS(id="mood", name="record_dial", args={"item": "mood", "value": 3})])))
        await settle(lambda: bool(session.responses))

    if tool_first:
        await record_mood()
    for chunk in ("3", " today", " I think"):
        await session.incoming.put(speech(chunk))
    await session.incoming.put(finished_speech())
    await session.incoming.put(NS(server_content=NS(turn_complete=True)))
    await settle(lambda: voice._input_text == "")
    if not tool_first:
        await record_mood()
    await settle(lambda: any(e.type == "obs.self_report" for e in hub.emitted))
    await asyncio.sleep(0.02)
    reports = [e.payload for e in hub.emitted if e.type == "obs.self_report"]
    assert [(r.item, r.value) for r in reports] == [("mood", 3)]
    assert hub.machine.state == "dial"
    # A provider retry of the same named tool cannot fill energy or sleep either.
    await record_mood()
    await asyncio.sleep(0.02)
    assert len([e for e in hub.emitted if e.type == "obs.self_report"]) == 1
    await hub.end_ritual()


async def test_streamed_phq9_answer_is_consumed_once_and_crisis_still_scans_partials(rig):
    hub, voice, client, audio, _ = rig
    hub.settings.phq9_mode = "spoken"
    hub.state.phq9_due = True
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.start_ritual("text")
    await settle(lambda: bool(audio.inputs))
    hub.machine.jump_to("phq9")
    await settle(lambda: hub.machine.state == "phq9")
    phq9 = next(s for s in hub.machine.steps if s.name == "phq9")
    session = client.connections[0].session
    for chunk in ("1", " several", " days"):
        await session.incoming.put(speech(chunk))
    await settle(lambda: voice._input_text == "1 several days")
    assert phq9.answers == []
    await session.incoming.put(finished_speech())
    await session.incoming.put(NS(server_content=NS(turn_complete=True)))
    await settle(lambda: phq9.answers == [1])
    await session.incoming.put(speech("I want"))
    await session.incoming.put(speech(" to die"))
    await settle(lambda: any(e.type == "obs.safety_flag" for e in hub.emitted))
    assert not any(e.type == "obs.phq9" for e in hub.emitted)
    assert not hub.machine.running and voice._session is None


@pytest.mark.parametrize("outcome", ["completed", "skipped", "ended_early"])
async def test_end_session_stops_immediately_and_queues_outcome_with_follow_up(rig, outcome):
    hub, voice, _, audio, _ = rig
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.start_ritual("text")
    await settle(lambda: bool(audio.inputs))
    follow_up = {"skill": "walk_companion", "topic": "the park path"}
    result = await hub.on_tool("end_session", {"outcome": outcome, "follow_up": follow_up})
    assert result == {"ok": True, "follow_up_queued": True}
    assert not hub.machine.running and voice._session is None and audio.inputs[0].closed
    payload = json.loads(hub.episodes.db.execute("SELECT payload FROM episodes").fetchone()[0])
    assert payload["id"] == "test-session" and payload["outcome"] == outcome
    assert payload["open_thread"] == follow_up


async def test_end_session_rejects_invalid_args_and_never_queues_crisis_follow_up(rig):
    hub, voice, _, audio, _ = rig
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.start_ritual("text")
    await settle(lambda: bool(audio.inputs))
    invalid = await hub.on_tool("end_session", {"outcome": "invalid"})
    assert not invalid["ok"] and hub.machine.running
    crisis = await hub.on_tool("end_session", {
        "follow_up": {"skill": "walk_companion", "topic": "I want to die"}})
    assert not crisis["ok"] and voice._session is None
    payload = json.loads(hub.episodes.db.execute("SELECT payload FROM episodes").fetchone()[0])
    assert payload["outcome"] == "crisis"
    assert payload["open_thread"] is None and payload["transcript"] is None


async def test_stop_during_reconnect_handshake_never_reopens_mic(rig):
    hub, voice, client, audio, _ = rig
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.start_ritual("text")
    await settle(lambda: bool(audio.inputs))
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowConnection(Connection):
        async def __aenter__(self):
            entered.set()
            await release.wait()
            return self.session

    slow = SlowConnection(Session())
    client.connect = lambda **kwargs: slow
    first = client.connections[0].session
    await first.incoming.put(NS(session_resumption_update=NS(resumable=True, new_handle="synthetic")))
    await first.incoming.put(ConnectionError("synthetic disconnect"))
    await asyncio.wait_for(entered.wait(), 2)
    await hub.end_ritual()
    release.set()
    await settle(lambda: slow.closed)
    assert voice._session is None and len(audio.inputs) == 1


def test_live_developer_key_does_not_inherit_enterprise_backend(monkeypatch):
    from kaiku_hub.live import gemini_live
    calls = []
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-placeholder-not-a-key")
    monkeypatch.setenv("KAIKU_GENAI_BACKEND", "platform")
    monkeypatch.setattr(gemini_live.genai, "Client", lambda **kwargs: calls.append(kwargs) or object())
    GeminiLiveVoice("synthetic-live-model", audio=Audio(), meter_factory=Meter)
    assert calls[0]["http_options"]["api_version"] == "v1beta"
    assert "enterprise" not in calls[0]


async def test_actual_mic_callback_emits_numeric_speech_and_persists_no_words(rig):
    import numpy as np
    from kaiku_hub.uplink import Uplink

    hub, voice, client, audio, _ = rig
    await voice.start(hub.on_utterance, hub.on_tool)
    hub.start_ritual('text')
    await settle(lambda: bool(audio.inputs))
    session = client.connections[0].session
    t = np.arange(16000 * 3) / 16000
    pcm = (10000 * np.sin(2 * np.pi * 200 * t) * (np.sin(2 * np.pi * 4 * t) > 0)).astype('<i2').tobytes()
    for i in range(0, len(pcm), 3200):
        audio.inputs[0].callback(pcm[i:i+3200], 1600, None, None)
    await settle(lambda: len(session.audio) >= 30)
    await session.incoming.put(finished_speech('A synthetic test utterance'))
    await settle(lambda: any(e.type == 'obs.speech_features' for e in hub.emitted))
    features = [e for e in hub.emitted if e.type == 'obs.speech_features']
    assert len(features) == 1 and features[0].payload.duration_s == 3
    assert 0.2 < features[0].payload.pause_ratio < 0.8
    recovered = Uplink(url=None, queue_path=hub.settings.queue_path)
    body = recovered.db.execute("SELECT body FROM queue WHERE type='obs.speech_features'").fetchone()[0]
    assert 'synthetic test utterance' not in body and 'samples' not in body and 'audio' not in body
    assert json.loads(body)['source'] == 'hub'
    await session.incoming.put(finished_speech())
    await asyncio.sleep(.02)
    assert len([e for e in hub.emitted if e.type == 'obs.speech_features']) == 1
    # Speaker output/echo cannot become the person's numeric evidence.
    voice._pcm.extend(bytes(4800))
    for i in range(0, len(pcm), 3200):
        audio.inputs[0].callback(pcm[i:i+3200], 1600, None, None)
    await settle(lambda: len(session.audio) >= 60)
    await session.incoming.put(finished_speech('Another synthetic utterance'))
    await asyncio.sleep(.02)
    assert len([e for e in hub.emitted if e.type == 'obs.speech_features']) == 1
    await hub.end_ritual()
    await hub.on_speech_features(features[0].payload.model_dump())
    assert len([e for e in hub.emitted if e.type == 'obs.speech_features']) == 1
