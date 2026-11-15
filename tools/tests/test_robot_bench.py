"""Robot bench: the pure parts (which steps run, what counts as evidence, what a command looks like). No broker."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from kaiku_contracts import ContractError, validate
from kaiku_contracts.topics import AUDIO_FRAME_BYTES

from tools import robot_bench as rb
from tools.robot_bench import Seen


def test_the_default_run_needs_no_person_no_sound_and_no_made_up_face():
    assert rb.select([]) == ["parts", "ring", "turn", "buzzer", "camera", "face-signs"]
    assert rb.select(["arm", "parts"]) == ["parts", "arm"]            # the bench's own order, whatever was typed
    with pytest.raises(ValueError, match="no such step: spin"):
        rb.select(["spin"])


def test_only_this_homes_messages_are_looked_at_and_never_audio_or_her_words():
    assert rb.name_of("kaiku/v1/demo-aino/raw/head/pan", "demo-aino") == "raw/head/pan"
    assert rb.name_of("kaiku/v1/other/raw/head/pan", "demo-aino") is None
    assert rb.name_of("kaiku/v1/demo-aino/audio/head/mic", "demo-aino") is None
    assert rb.name_of("kaiku/v1/demo-aino/audio/phone/mic", "demo-aino") is None
    assert rb.name_of("kaiku/v1/demo-aino/raw/hub/transcript", "demo-aino") is None
    assert not any("audio" in f or "transcript" in f or f in ("#", "raw/#") for f in rb.FILTERS)


def test_every_command_the_bench_sends_is_a_valid_contract_message():
    sent = [("cmd.head", {"color": "#ffffff"}), ("cmd.head", {"pan": {"target_deg": -30.0, "speed": 0.6}}),
            ("cmd.head", {"activity": "drum"}), ("cmd.head", {"ritual": "end"}), ("cmd.sensors", {"chime": "ok"}),
            ("cmd.sensors", {"camera_enable": False}), ("cmd.sensors", {"face_signs_s": 5})]
    for type_, payload in sent:
        topic, body = rb.command(type_, payload, "demo-aino")
        env = validate(json.loads(body))
        assert env.source == "hub" and env.type == type_ and topic == f"kaiku/v1/demo-aino/{type_.replace('.', '/')}"
    topic, body = rb.command("raw.hub.face", {"x_norm": 0.8, "y_norm": 0.0, "size": 0.2, "confidence": 0.9},
                             "demo-aino", source="sensors")
    assert topic.endswith("/raw/hub/face") and json.loads(body)["source"] == "sensors"
    with pytest.raises(ContractError):
        rb.command("cmd.head", {"color": "white"}, "demo-aino")       # not a hex colour: never sent


def test_a_heartbeat_counts_only_when_it_is_live_and_not_down():
    now = datetime(2026, 11, 15, 2, 0, tzinfo=UTC)
    beat = {"status": "ok", "version": "atech-head-standalone-0.8.0", "details": {"step": "idle"}}
    ok, n = rb.health_check([Seen(1.0, "health/head", "head", beat, now - timedelta(seconds=3))], "head", now)
    assert ok and n == {"status": "ok", "version": "atech-head-standalone-0.8.0", "age_s": 3.0, "step": "idle"}
    old = Seen(1.0, "health/head", "head", beat, now - timedelta(hours=2), retained=True)
    assert rb.health_check([old], "head", now)[0] is False            # a retained message from hours ago
    down = Seen(1.0, "health/head", "head", {**beat, "status": "down"}, now)
    assert rb.health_check([down], "head", now)[0] is False           # the last will
    assert rb.health_check([], "sensors", now) == (False, {"heard": False})
    hub = {"status": "ok", "version": "0.1.0", "details": {"talk": "closed", "mic_source": "phone", "uplink_queue": 0}}
    assert rb.health_check([Seen(1.0, "health/hub", "hub", hub, now)], "hub", now)[1]["mic_source"] == "phone"


def test_a_turn_is_proven_by_moving_then_still_after_the_command():
    def pan(t, moving, source="head"):
        return Seen(t, "raw/head/pan", source, {"deg": 0, "homed": True, "moving": moving})

    ok, n = rb.pan_evidence([pan(9.0, True), pan(10.4, True), pan(11.1, False)], t0=10.0)
    assert ok and n == {"pan_messages": 2, "moving_after_s": 0.4, "still_after_s": 1.1}
    assert rb.pan_evidence([pan(10.4, False), pan(11.0, False)], t0=10.0)[0] is False   # it never moved
    assert rb.pan_evidence([pan(14.0, True), pan(15.0, False)], t0=10.0)[0] is False    # too late to be this turn
    assert rb.pan_evidence([pan(10.4, True)], t0=10.0)[0] is False                      # it never said it stopped
    assert rb.pan_evidence([pan(10.4, True, "sim"), pan(11.0, False, "sim")], t0=10.0)[0] is False


def test_the_tone_is_the_speakers_wire_format_and_quiet():
    frames = rb.tone_frames(2.0)
    assert len(frames) == 100 and all(len(f) == AUDIO_FRAME_BYTES for f in frames)
    assert max(abs(int.from_bytes(frames[3][i:i + 2], "little", signed=True)) for i in range(0, 640, 2)) <= 2500


def test_following_is_judged_by_the_configured_sign():
    assert rb.follow_sign_ok({"target_deg": 10.0, "speed": 0.35}, x=0.8, sign=1)
    assert not rb.follow_sign_ok({"target_deg": -10.0, "speed": 0.35}, x=0.8, sign=1)
    assert rb.follow_sign_ok({"target_deg": -10.0, "speed": 0.35}, x=0.8, sign=-1)


def test_the_summary_counts_each_kind_and_only_a_fail_fails():
    out = rb.render([rb.Result("parts", "PASS", "head: alive", {"age_s": 1.0}), rb.Result("ring", "LOOK", "white"),
                     rb.Result("turn", "FAIL", "no movement"), rb.Result("follow", "SKIP", "by hand")])
    assert "1 passed, 1 failed, 1 to look at or hear, 1 skipped" in out and '{"age_s": 1.0}' in out
