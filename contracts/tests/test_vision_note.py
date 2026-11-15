"""obs.vision_note (D65): what Kaiku's own model noted from a few pictures. Closed word lists only: no picture, no
free text, no feeling; always marked as not a diagnosis; no vote."""
import pytest
from kaiku_contracts import UPLINKABLE, ContractError, make
from kaiku_contracts.payloads import VisionNote
from kaiku_contracts.registry import EXAMPLES
from kaiku_contracts.sources import CONSENSUS_SOURCES, SOURCE_OF

EXAMPLE = EXAMPLES["obs.vision_note"]


def test_the_example_is_valid_and_has_no_vote():
    env = make("obs.vision_note", EXAMPLE, source="cloud", quality=EXAMPLE["confidence"])
    assert env.payload.not_a_diagnosis is True and "obs.vision_note" in UPLINKABLE
    assert SOURCE_OF["obs.vision_note"] not in CONSENSUS_SOURCES


def test_no_field_can_hold_a_picture_a_text_or_a_feeling():
    fields = VisionNote.model_fields
    assert set(fields) == {"task", "device", "model", "frames_n", "face_visible", "expression", "gaze", "posture",
                           "lighting", "confidence", "not_a_diagnosis", "ref"}
    for extra in ({"image": "aGVsbG8="}, {"frames": ["x"]}, {"note": "looked sad"}, {"emotion": "sad"}):
        with pytest.raises(ContractError):
            make("obs.vision_note", {**EXAMPLE, **extra}, source="cloud")
    for field, value in (("expression", "sad"), ("expression", "depressed"), ("gaze", "avoidant"),
                         ("not_a_diagnosis", False), ("frames_n", 0), ("frames_n", 9), ("confidence", 1.2)):
        with pytest.raises(ContractError):
            make("obs.vision_note", {**EXAMPLE, field: value}, source="cloud")
