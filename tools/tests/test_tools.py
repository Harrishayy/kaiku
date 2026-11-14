import asyncio
import json

from kaiku_contracts import example, to_json
from kaiku_contracts.bus import Bus

from tools.bus_tail import fmt
from tools.record import record
from tools.replay import load, prepare, replay


def test_fmt_valid_and_invalid():
    env = example("obs.drum_session")
    line = fmt("kaiku/v1/demo-aino/obs/drum_session", to_json(env).encode(), color=False)
    assert "obs/drum_session" in line and "SIM" in line and "tempo_bpm" in line
    bad = fmt("kaiku/v1/demo-aino/obs/mood_dial", b'{"nope": 1}', color=False)
    assert "INVALID" in bad


def test_prepare_restamps_and_rejects_invalid():
    env = example("raw.head.tap")
    row = {"t": 0, "topic": "x", "msg": json.loads(to_json(env))}
    topic, body, qos = prepare(row, keep_ids=False, home="other-home")
    assert topic == "kaiku/v1/other-home/raw/head/tap" and qos == 0
    assert json.loads(body)["id"] != str(env.id)
    assert prepare({"t": 0, "topic": "x", "msg": {"bad": 1}}, keep_ids=False, home=None) is None


async def test_record_then_replay_round_trip(broker, tmp_path):
    out = tmp_path / "rec.jsonl"
    rec = asyncio.create_task(record("kaiku/v1/#", out, seconds=1.5))
    await asyncio.sleep(0.3)
    async with Bus("head", home_id="t1", heartbeat=False, sim=True) as b:
        for i in range(3):
            await b.publish("raw.head.tap", {"t_ms": i, "force": 1.0})
    assert await rec == 3
    got = []

    async def on_tap(t, env):
        got.append(env)

    listener = Bus("hub", home_id="t1", heartbeat=False)
    listener.on("raw/head/tap", on_tap)
    async with listener:
        assert await replay(out, speed=10, only=None, keep_ids=False, home=None, verbatim=False, loop=False) == 3
        await asyncio.sleep(0.3)
    assert [e.payload.t_ms for e in got] == [0, 1, 2]


def test_session_tool_rederives_and_exports_a_stored_ritual(tmp_path, capsys):
    """tools/session.py: a stored session re-derives to the same drum numbers; the replay file is valid + sim."""
    from datetime import UTC, datetime, timedelta

    from kaiku_contracts import make
    from kaiku_hub.perception.taps import TapAnalyzer
    from kaiku_hub.store import SessionStore

    from tools import session as tool

    t0 = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
    path = tmp_path / "s.sqlite"
    st = SessionStore(path)
    st.begin("ritual-1", "button", home_id="home-x", now=t0)
    st.add_obs(make("obs.ritual", {"step": "drum", "status": "started"}, source="hub", ts=t0))
    taps = TapAnalyzer()
    for i in range(12):
        t_ms = 500 + i * 450
        taps.add(t_ms)
        st.add_raw(make("raw.head.tap", {"t_ms": t_ms, "src": "knock"}, source="sensors",
                        ts=t0 + timedelta(milliseconds=t_ms)))
    summary = {k: v for k, v in taps.summary((taps.times[-1] - taps.times[0]) / 1000).items() if v is not None}
    st.add_obs(make("obs.drum_session", summary, source="hub", ts=t0 + timedelta(seconds=9)))
    st.add_obs(make("obs.ritual", {"step": "drum", "status": "completed"}, source="hub", ts=t0 + timedelta(seconds=10)))
    st.end(outcome="completed", episode_id="ep-9", now=t0 + timedelta(seconds=11))
    st.close()

    assert tool.main(["--store", str(path), "rederive", "ep-9"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["drum"]["match"] is True and res["drum"]["stored_taps"] == 12 and res["pulse"]["match"] is None
    out = tmp_path / "replay.jsonl"
    assert tool.main(["--store", str(path), "replay-file", "last", "-o", str(out)]) == 0
    rows = load(out)
    assert len(rows) == 12 and rows[0]["topic"] == "kaiku/v1/home-x/raw/head/tap" and rows[-1]["t"] > rows[0]["t"]
    assert all(r["msg"]["sim"] is True for r in rows) and prepare(rows[0], keep_ids=False, home=None) is not None
    assert tool.main(["--store", str(path), "export", "ritual", "-o", str(tmp_path / "e.json")]) == 0
    assert len(json.loads((tmp_path / "e.json").read_text())["samples"]) == 12
    assert tool.main(["--store", str(path), "list"]) == 0 and "ritual-1" in capsys.readouterr().out
    assert tool.main(["--store", str(path), "show", "nope"]) == 1
    assert tool.main(["--store", str(tmp_path / "missing.sqlite"), "list"]) == 1


# ------------------------------------------------------------------ the head's audio topics are never stored or shown
async def test_record_never_writes_the_heads_audio_whatever_the_filter(broker, tmp_path):
    """`kaiku/v1/<home>/audio/head/{speaker,mic}` carry PCM (the microphone: a person's voice). A recording holds
    messages only, even when someone asks for exactly the audio topic."""
    frame = bytes(range(256)) * 2 + bytes(128)
    for i, topic in enumerate(("kaiku/v1/#", "kaiku/v1/t1/audio/#")):
        out = tmp_path / f"rec{i}.jsonl"
        rec = asyncio.create_task(record(topic, out, seconds=1.2))
        await asyncio.sleep(0.3)
        async with Bus("head", home_id="t1", heartbeat=False, sim=True) as b:
            for _ in range(5):
                assert await b.publish_audio(frame, stream="mic")
                assert await b.publish_audio(frame, stream="speaker")
            await b.publish_audio(b"")
            await b.publish("raw.head.tap", {"t_ms": 1, "force": 1.0})
        assert await rec == (1 if i == 0 else 0)
        text = out.read_text() if out.exists() else ""
        assert "audio" not in text and text.count("\n") == (1 if i == 0 else 0)


def test_tail_counts_audio_frames_and_never_prints_what_is_in_them():
    from tools.bus_tail import AudioCount

    count = AudioCount()
    count.t0 = 100.0
    assert count.add("kaiku/v1/t1/audio/head/mic", 640, 100.2) is None
    assert count.add("kaiku/v1/t1/audio/head/speaker", 0, 100.4) is None
    line = count.add("kaiku/v1/t1/audio/head/mic", 640, 101.3)
    assert "audio (not shown)" in line and "t1/audio/head/mic 2 frames 1280 bytes" in line
    assert "t1/audio/head/speaker 1 frames 0 bytes 1 flush" in line and count.frames == {}


async def test_replay_skips_an_audio_row_even_in_a_hand_made_file(broker, tmp_path):
    tap = example("raw.head.tap", home_id="t1")
    rows = [{"t": 0.0, "topic": "kaiku/v1/t1/audio/head/mic", "msg": "AAAA"},
            {"t": 0.01, "topic": "kaiku/v1/t1/raw/head/tap", "msg": json.loads(to_json(tap))}]
    path = tmp_path / "hand.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert await replay(path, speed=10, only=None, keep_ids=True, home=None, verbatim=False, loop=False) == 1


# ------------------------------------------------------------------ what Kaiku said (raw.hub.trace) is never stored
async def test_record_keeps_that_kaiku_spoke_but_never_what_it_said(broker, tmp_path):
    """`raw.hub.trace` is live, for the "Kaiku bot" tab of the apps. A recording keeps its kind and machine words
    (enough to debug the flow) and never the line itself."""
    out = tmp_path / "rec.jsonl"
    rec = asyncio.create_task(record("kaiku/v1/#", out, seconds=1.2))
    await asyncio.sleep(0.3)
    async with Bus("hub", home_id="t1", heartbeat=False, sim=True) as b:
        await b.publish("raw.hub.trace", {"kind": "said", "text": "How are you today, Aino?", "by": "live"})
        await b.publish("raw.hub.trace", {"kind": "tool", "tool": "feel", "ms": 40, "ok": True, "by": "rule"})
        await b.publish("raw.hub.trace", {"kind": "heard"})
    assert await rec == 3
    text = out.read_text()
    assert "Aino" not in text and "How are you" not in text and '"text"' not in text
    rows = [json.loads(line)["msg"]["payload"] for line in text.splitlines()]
    assert rows == [{"kind": "said", "by": "live"}, {"kind": "tool", "tool": "feel", "ms": 40, "ok": True, "by": "rule"},
                    {"kind": "heard"}]
    assert await replay(out, speed=10, only=None, keep_ids=True, home=None, verbatim=False, loop=False) == 3


def test_replay_drops_the_words_of_a_trace_in_a_hand_made_file_and_tail_may_show_them(tmp_path):
    said = example("raw.hub.trace", home_id="t1")
    rows = [{"t": 0.0, "topic": "kaiku/v1/t1/raw/hub/trace", "msg": json.loads(to_json(said))},
            {"t": 0.1, "topic": "kaiku/v1/t1/raw/hub/trace", "msg": "not a message: someone's words"},
            {"t": 0.2, "topic": "kaiku/v1/t1/raw/head/tap", "msg": json.loads(to_json(example("raw.head.tap")))}]
    path = tmp_path / "hand.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    loaded = load(path)
    assert [r["topic"].rsplit("/", 1)[-1] for r in loaded] == ["trace", "tap"]
    assert loaded[0]["msg"]["payload"] == {"kind": "said", "by": "live"} and said.payload.text   # the words are gone
    assert prepare(loaded[0], keep_ids=True, home=None) is not None                  # and what is left still fits
    line = fmt("kaiku/v1/t1/raw/hub/trace", to_json(said).encode(), color=False)     # the live tail is not a store
    assert said.payload.text in line
