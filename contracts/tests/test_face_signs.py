"""obs.face_signs (D52): movements of the face counted on the person's own device during a task, never an emotion;
the criteria state "shown, not scored"; and the wording rule that Kaiku never speaks about a face or a camera."""
import hashlib
import json
import tomllib
from typing import get_args

import pytest
from kaiku_contracts import make, validate, wording
from kaiku_contracts.criteria import Criteria, criteria_path, load_criteria, parse_criteria
from kaiku_contracts.payloads import FACE_SIGNS, FACE_TASKS, FaceSigns, FaceTask, PlayGame, PlaySession
from kaiku_contracts.registry import EXAMPLES, FACE_EXAMPLES, UPLINKABLE, ContractError
from kaiku_contracts.sources import SOURCE_OF
from pydantic import ValidationError

EXAMPLE = EXAMPLES["obs.face_signs"]
FACE_METRICS = ("face_range", "face_smiles", "face_blinks", "face_range_chat", "face_smiles_chat", "face_range_landmarks",
                "face_range_chat_landmarks")


def _raw():
    return tomllib.loads(criteria_path().read_text())


# ---------------------------------------------------------------------------------------------------- the payload
def test_tasks_are_every_game_plus_the_check_in_and_it_sits_beside_the_task():
    assert get_args(FaceTask) == (*get_args(PlayGame), "check_in") == FACE_TASKS
    assert SOURCE_OF["obs.face_signs"] == SOURCE_OF["obs.play_session"] == "laptop"
    assert "obs.face_signs" in UPLINKABLE


@pytest.mark.parametrize("payload", [EXAMPLE, *FACE_EXAMPLES.values()])
def test_examples_round_trip_as_an_envelope(payload):
    env = make("obs.face_signs", payload, source="phone", quality=payload["coverage"], sim=True)
    again = validate(env.model_dump(mode="json", exclude_none=True))
    assert again.payload.model_dump(exclude_none=True) == FaceSigns.model_validate(payload).model_dump(exclude_none=True)
    assert again.quality == payload["coverage"]


def test_a_sign_the_method_cannot_measure_is_absent_never_a_zero():
    landmarks = FaceSigns.model_validate(FACE_EXAMPLES["landmarks"])
    for name in ("smile_share", "smiles", "brow_raise_share", "brow_furrow_share", "gaze_on_share"):
        assert getattr(landmarks, name) is None, name  # what the landmark method (Mac, other iPhones) never sends
    for name in ("mouth_open_share", "blinks_per_min", "head_movement", "expression_range"):
        assert getattr(landmarks, name) is not None, name  # sent by both methods, on scales that differ


def test_no_face_in_view_keeps_its_provenance_and_carries_no_sign():
    quiet = FaceSigns.model_validate(FACE_EXAMPLES["no_face"])
    assert quiet.coverage == 0 and all(getattr(quiet, name) is None for name in FACE_SIGNS)
    for name in FACE_SIGNS:
        with pytest.raises(ValidationError, match="no usable face"):
            FaceSigns.model_validate({**FACE_EXAMPLES["no_face"], name: 0})


@pytest.mark.parametrize("bad", [
    {"samples": 0}, {"coverage": 1.2}, {"coverage": -0.1}, {"smile_share": 1.5}, {"expression_range": 2.0},
    {"blinks_per_min": -1}, {"head_movement": -0.1}, {"method": "mediapipe_blendshapes"}, {"method": "yolo"},
    {"task": "drum"}, {"device": "robot"}, {"ref": ""},
])
def test_out_of_range_and_unknown_values_are_rejected(bad):
    with pytest.raises(ValidationError):
        FaceSigns.model_validate({**EXAMPLE, **bad})


@pytest.mark.parametrize("field", ["emotion", "mood", "sad", "happy", "valence", "label", "frames", "image", "jpeg",
                                   "video", "landmarks", "blendshapes", "embedding", "identity"])
def test_there_is_no_field_for_an_emotion_a_picture_or_raw_tracking_data(field):
    """extra=forbid: a producer cannot send a label, a frame or the per-frame coefficients even by accident."""
    assert field not in FaceSigns.model_fields
    with pytest.raises(ContractError):
        make("obs.face_signs", {**EXAMPLE, field: "x"}, source="phone")
    names = " ".join(FaceSigns.model_fields)
    assert not any(word in names for word in ("emotion", "mood", "sad", "happy", "affect", "feeling"))


def test_the_play_session_keeps_its_older_camera_fields():
    for name in ("expressivity_index", "face_movement", "camera_face_coverage", "camera_samples", "camera_method"):
        assert name in PlaySession.model_fields
    PlaySession.model_validate(EXAMPLES["obs.play_session"])


# ------------------------------------------------------------------------------- shown, not scored (criteria state)
def test_every_face_metric_is_shown_tied_to_one_method_and_gated_on_the_capture():
    c = load_criteria()
    mine = [m for m in c.metrics if m.obs == "obs.face_signs"]
    assert tuple(m.name for m in mine) == FACE_METRICS
    for m in mine:
        assert m.role == "shown" and m.enabled and not m.votes, m.name
        assert m.where["method"] in ("arkit_blendshapes", "vision_landmarks"), m.name  # never the two pooled
        if m.where["method"] == "vision_landmarks":  # that method sends no smile, brow or gaze sign at all
            assert m.field in ("expression_range", "blinks_per_min", "head_movement", "mouth_open_share"), m.name
        assert m.where["task"] == "check_in" or "check_in" not in m.where["task"], m.name  # games and chats apart
        assert not {"tell", "breathe"} & set([m.where["task"]] if isinstance(m.where["task"], str) else m.where["task"])
        # one usable face in most frames, 20 s of sampling, and at least half the frames the method takes in that
        # time (30 looks a second with ARKit, 15 with Vision landmarks)
        half = 300 if m.where["method"] == "arkit_blendshapes" else 150
        assert m.at_least == {"coverage": 0.6, "samples": half, "duration_s": 20}, m.name
        assert not m.counts_for_better and not m.person_hard and c.param(m, "z_threshold") == 2.0
        assert c.param(m, "min_mad") > 0 and c.param(m, "baseline_min_days") == 5
    assert c.shown_types == frozenset({"obs.face_signs"})
    assert [m.name for m in c.shown_for("laptop")] == list(FACE_METRICS)
    assert not [m for m in c.metrics_for("laptop") if m.obs == "obs.face_signs"]  # the verdict never sees one
    assert c.metric("face_blinks").weight == 0 and c.metric("face_blinks").worse_when == "up"
    # even with every role line deleted, the camera alone could not turn the Apps group worse
    assert sum(m.weight for m in mine) < c.sources["laptop"].worse_min_weight


def test_the_rule_version_is_the_one_the_file_had_before_the_face_metrics():
    """The hash covers what can decide a state. Take the shown metrics out again (the face signs, D52; more of the
    day from Apple Health, D53) and hash the file the old way (every metric, every field it had then): the same
    eight characters."""
    c = load_criteria()
    raw = _raw()
    assert {m["obs"] for m in raw["metric"] if m.get("role") == "shown"} == {"obs.face_signs", "obs.wearable_daily"}
    raw["metric"] = [m for m in raw["metric"] if m.get("role") != "shown"]
    before = Criteria.model_validate(raw)
    old = before.model_dump(mode="json", by_alias=True)
    for m in old["metric"]:
        del m["role"], m["at_least"]
    legacy = hashlib.sha256(json.dumps(old, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:8]
    assert c.fingerprint == before.fingerprint == legacy
    assert c.rule_version == f"consensus-v1+{legacy}"


def test_a_shown_metric_can_change_or_go_without_a_new_rule_version_and_voting_changes_it():
    c = load_criteria()
    raw = _raw()
    block = next(m for m in raw["metric"] if m["name"] == "face_smiles")
    block.update(min_mad=0.09, z_threshold=3.0, label="Smiles", weight=0.9, at_least={"coverage": 0.9})
    assert parse_criteria(raw).rule_version == c.rule_version  # retuned: the rule cannot see it
    raw["metric"].remove(block)
    assert parse_criteria(raw).rule_version == c.rule_version  # removed
    one_line = _raw()
    del next(m for m in one_line["metric"] if m["name"] == "face_smiles")["role"]  # the one line
    voting = parse_criteria(one_line)
    assert voting.rule_version != c.rule_version
    smiles = voting.metric("face_smiles")
    assert smiles.votes and smiles.weight == 0.2 and smiles in voting.metrics_for("laptop")
    assert voting.shown_types == frozenset()  # a type a scored metric reads counts toward its group again
    scored_edit = _raw()
    next(m for m in scored_edit["metric"] if m["name"] == "mood")["at_least"] = {"value": 1}
    assert parse_criteria(scored_edit).rule_version != c.rule_version  # a new knob on a scored metric is an edit


def test_role_and_minimums_are_validated():
    raw = _raw()
    next(m for m in raw["metric"] if m["name"] == "face_smiles")["at_least"] = {"sharpness": 0.5}
    with pytest.raises(ValidationError, match="unknown field"):
        Criteria.model_validate(raw)
    raw = _raw()
    next(m for m in raw["metric"] if m["name"] == "face_smiles")["role"] = "hidden"
    with pytest.raises(ValidationError):
        Criteria.model_validate(raw)
    raw = _raw()  # a shown metric may not move the day its type's other metrics are counted on
    raw["metric"].append({"name": "sleep_shown", "label": "x", "obs": "obs.wearable_daily", "field": "sleep_min",
                          "worse_when": "down", "role": "shown"})
    with pytest.raises(ValidationError, match="share one day_field"):
        Criteria.model_validate(raw)


def test_votes_is_the_one_question():
    c = load_criteria()
    assert c.metric("mood").votes and not c.metric("drum_force").votes  # scored / switched off
    assert not c.metric("face_range").votes                              # shown
    raw = _raw()
    next(m for m in raw["metric"] if m["name"] == "mood")["weight"] = 0
    assert not parse_criteria(raw).metric("mood").votes                  # the older observe-only form


def test_the_retired_expressivity_metric_is_untouched_and_off():
    old = load_criteria().metric("expressivity")
    assert not old.enabled and old.obs == "obs.laptop_session" and old.role == "scored"


# ------------------------------------------------------------------------------------- Kaiku never speaks about it
@pytest.mark.parametrize("line", [
    "You looked tired during the game.", "I noticed you weren't smiling much today.", "You didn't smile once.",
    "Your face seemed quieter in the lantern game.", "The camera showed you were blinking a lot.",
    "I saw you on the camera earlier.", "I could see your face drop.", "You look a bit flat today.",
    "I was watching you play.", "That put a smile on your face.", "Your expression changed.",
])
def test_remarks_about_a_face_or_a_watching_camera_are_flagged(line):
    assert "face_talk" in wording.codes(wording.lint(line))


@pytest.mark.parametrize("line", [
    "Close your eyes if you like, and breathe out slowly.", "The camera is off, so I can't see it.",
    "Good to see you. I'm around later.", "I can hear the smile in that.", "You looked at the lake this morning?",
    "I can't see your face, or you at all.", "No, I never see your face.", "You look after everyone, don't you.",
    "I can't see you. If Camera during activities is on, your phone counts how the face moves during games, "
    "keeps numbers only, and you can switch it off under You.",
])
def test_honest_and_ordinary_lines_are_not(line):
    assert "face_talk" not in wording.codes(wording.lint(line, max_questions=None))
