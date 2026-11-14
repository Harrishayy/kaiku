"""D51: `obs.tap_back`, the two optional `cmd.head` fields (`drum`, `mic`) and the head's binary audio topics, which
are NOT envelopes: nothing that validates, stores, prints or uplinks messages may ever treat them as one."""

import asyncio

import pytest
from kaiku_contracts import ContractError, example, is_audio_topic, make, validate
from kaiku_contracts.bus import Bus
from kaiku_contracts.payloads import TapBack, TapBackLevel
from kaiku_contracts.registry import HEAD_EXAMPLES
from kaiku_contracts.sources import SOURCE_OF
from kaiku_contracts.topics import (
    AUDIO_FRAME_BYTES,
    AUDIO_FRAME_MS,
    AUDIO_FRAME_SAMPLES,
    AUDIO_RATE_HZ,
    audio_topic,
    parse_topic,
)
from pydantic import ValidationError


def level(**over):
    return {"level": 1, "target_bpm": 100, "tapped_bpm": 102.0, "error_pct": 2.0, "steadiness": 0.95, "taps": 8,
            "band": "perfect", "tries": 1, **over}


def game(levels, **over):
    passed = sum(lv["band"] != "again" for lv in levels)
    return {"levels": levels, "levels_played": len(levels), "levels_passed": passed, "error_pct": 2.0,
            "steadiness": 0.95, "taps": 8 * len(levels), "duration_s": 60.0, **over}


# ------------------------------------------------------------------------------------------------ obs.tap_back
def test_tap_back_example_is_the_robots_and_counts_toward_no_consensus_metric():
    env = example("obs.tap_back")
    p = env.payload
    assert isinstance(p, TapBack) and [lv.band for lv in p.levels] == ["perfect", "great", "perfect"]
    assert p.levels[2].tries == 2 and p.song == "music" and p.levels_passed == 3
    assert SOURCE_OF["obs.tap_back"] == "robot"
    from kaiku_contracts.criteria import load_criteria

    assert not [m.name for m in load_criteria().metrics if m.obs == "obs.tap_back"]   # a game, not a signal (D51)


def test_a_level_without_a_tempo_is_always_again_and_tempo_and_error_come_together():
    TapBackLevel(**level(tapped_bpm=None, error_pct=None, steadiness=None, taps=2, band="again"))
    with pytest.raises(ValidationError):
        TapBackLevel(**level(tapped_bpm=None, error_pct=None, band="nice"))        # nothing measured cannot be a match
    with pytest.raises(ValidationError):
        TapBackLevel(**level(error_pct=None))                                      # a tempo without its error
    with pytest.raises(ValidationError):
        TapBackLevel(**level(band="wonderful"))
    with pytest.raises(ValidationError):
        TapBackLevel(**level(score=87))                                            # no extra fields, no points


def test_the_games_counts_must_agree_with_its_levels():
    two = [level(), level(level=2, band="again", error_pct=22.0, tapped_bpm=122.0)]
    assert make("obs.tap_back", game(two), source="hub").payload.levels_passed == 1
    with pytest.raises(ContractError):
        make("obs.tap_back", game(two, levels_passed=2), source="hub")
    with pytest.raises(ContractError):
        make("obs.tap_back", game(two, levels_played=3), source="hub")
    with pytest.raises(ContractError):
        make("obs.tap_back", game([]), source="hub")
    assert make("obs.tap_back", game([level()], song="beat"), source="hub").payload.song == "beat"
    with pytest.raises(ContractError):
        make("obs.tap_back", game([level()], song="radio"), source="hub")


# ------------------------------------------------------------------------------- cmd.head: drum and mic
def test_cmd_head_takes_the_drum_hold_and_the_microphone_hold_and_nothing_else_there():
    held = make("cmd.head", {"drum": "hold", "eyes": "soft", "pan_mode": "sway", "bpm": 96.0}, source="hub").payload
    assert held.drum == "hold" and held.mic is None
    assert make("cmd.head", {"drum": "end", "pan_mode": "still"}, source="hub").payload.drum == "end"
    assert make("cmd.head", {"mic": "open"}, source="hub").payload.mic == "open"
    assert make("cmd.head", {"mic": "close"}, source="hub").payload.mic == "close"
    assert "drum" not in make("cmd.head", {"eyes": "happy"}, source="hub").payload.model_dump(exclude_none=True)
    for bad in ({"drum": "start"}, {"mic": "on"}, {"mic": True}):
        with pytest.raises(ContractError):
            make("cmd.head", bad, source="hub")


# ------------------------------------------------------------------------------------- the audio topics
def test_audio_topics_have_one_fixed_format_and_are_not_message_topics():
    assert (AUDIO_RATE_HZ, AUDIO_FRAME_MS, AUDIO_FRAME_SAMPLES, AUDIO_FRAME_BYTES) == (16000, 20, 320, 640)
    assert audio_topic("home1") == "kaiku/v1/home1/audio/head/speaker"
    assert audio_topic("home1", "mic") == "kaiku/v1/home1/audio/head/mic"
    with pytest.raises(ValueError):
        audio_topic("home1", "camera")
    assert is_audio_topic("kaiku/v1/home1/audio/head/speaker") and is_audio_topic("kaiku/v1/h/audio/head/mic")
    for not_audio in ("kaiku/v1/home1/obs/tap_back", "kaiku/v1/home1/raw/head/tap", "kaiku/v1/home1/cmd/head",
                      "kaiku/v1/home1/health/head", "other/v1/home1/audio/head/speaker", "kaiku/v1/audio"):
        assert not is_audio_topic(not_audio), not_audio
    with pytest.raises(ContractError):
        validate(bytes(AUDIO_FRAME_BYTES))                                         # a frame is never an envelope
    assert parse_topic("kaiku/v1/home1/audio/head/speaker").kind == "audio"        # and "audio" is no message kind:
    from kaiku_contracts.topics import QOS

    assert "audio" not in QOS                                                      # no type maps onto it


async def test_audio_frames_cross_the_bus_as_bytes_and_never_reach_a_message_handler(broker):
    frames: dict[str, list[bytes]] = {"speaker": [], "mic": []}
    messages: list[str] = []

    async def on_message(t, env):
        messages.append(env.type)

    head = Bus("head", home_id="t9", heartbeat=False)
    hub = Bus("hub", home_id="t9", heartbeat=False)
    spy = Bus("sim", home_id="t9", heartbeat=False)
    spy.on("audio/#", on_message)                                                  # someone asks for the audio topics
    for kind in ("raw", "obs", "cmd", "health", "log"):                            # as if they were messages; and
        head.on(f"{kind}/#", on_message)                                           # every kind of message there is
        hub.on(f"{kind}/#", on_message)
    head.on_audio("speaker", frames["speaker"].append)
    hub.on_audio("mic", frames["mic"].append)
    async with head, hub, spy:
        await asyncio.sleep(0.2)
        frame = bytes(range(256)) * 2 + bytes(128)
        assert len(frame) == AUDIO_FRAME_BYTES
        assert await hub.publish_audio(frame) and await hub.publish_audio(b"")     # a frame, then "drop your buffer"
        assert await head.publish_audio(frame, stream="mic")
        await hub.publish("cmd.head", {"mic": "open"})
        for _ in range(40):
            if len(frames["speaker"]) == 2 and frames["mic"] and "cmd.head" in messages:
                break
            await asyncio.sleep(0.05)
    assert frames["speaker"] == [frame, b""] and frames["mic"] == [frame]          # byte for byte, in order
    assert set(messages) == {"cmd.head"}                                           # the PCM was never parsed as one
    assert spy.last_error is None                                                  # nor did the spy choke on it
    assert head.audio_dropped == 0 and hub.audio_dropped == 0


async def test_audio_is_dropped_quietly_when_the_broker_is_away(monkeypatch):
    monkeypatch.setenv("MQTT_PORT", "1")
    async with Bus("hub", home_id="t9", heartbeat=False) as hub:
        assert await hub.publish_audio(bytes(AUDIO_FRAME_BYTES)) is False          # never queued: late audio is noise
        assert hub.audio_dropped == 1


@pytest.mark.parametrize("name", sorted(HEAD_EXAMPLES))
def test_every_new_head_command_example_is_a_valid_command_and_says_nothing_more(name):
    env = make("cmd.head", HEAD_EXAMPLES[name], source="hub")
    assert env.payload.model_dump(mode="json", exclude_none=True) == HEAD_EXAMPLES[name]


def test_the_help_screen_is_one_of_two_words_and_never_free_text():
    """`show` puts constants compiled into the firmware on the head's screen: the hub can never send it a number,
    a name or any other text to show (the crisis path stays deterministic, D-safety)."""
    assert make("cmd.head", {"show": "help"}, source="hub").payload.show == "help"
    assert make("cmd.head", {"show": "none"}, source="hub").payload.show == "none"
    assert make("cmd.head", {"eyes": "soft"}, source="hub").payload.show is None      # optional: old senders still fit
    for bad in ("116 123", "crisis", "", True, {"text": "call"}):
        with pytest.raises((ContractError, ValidationError)):
            make("cmd.head", {"show": bad}, source="hub")
    with pytest.raises((ContractError, ValidationError)):
        make("cmd.head", {"show": "help", "text": "call 112"}, source="hub")             # no field carries words
