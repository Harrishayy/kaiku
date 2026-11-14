"""Transcription completion is independent of audio generation completion; older records remain valid."""

import pytest
from kaiku_contracts.api import EpisodeIn, TranscriptsResponse, TranscriptTurn
from pydantic import ValidationError


@pytest.mark.parametrize("status", [None, True, False])
def test_completion_status_survives_upload_and_readback_without_changing_words(status):
    words = "I was saying—"
    turn = {"role": "person", "text": words, "complete": status}
    episode = EpisodeIn.model_validate({"home_id": "synthetic", "surface": "iphone", "id": "episode",
                                       "start": "2026-11-14T00:00:00Z", "transcript": [turn]})
    response = TranscriptsResponse.model_validate({"home_id": episode.home_id, "transcripts": [{
        "episode_id": episode.id, "surface": episode.surface, "intent": episode.intent, "start": episode.start,
        "turns": [t.model_dump() for t in episode.transcript]}]})
    stored = response.transcripts[0].turns[0]
    assert stored.text == words and stored.complete is status
    assert TranscriptTurn.model_validate_json(stored.model_dump_json()) == stored


def test_legacy_turn_completion_is_unknown_instead_of_assumed_finished():
    old = TranscriptTurn.model_validate({"role": "kaiku", "text": "Hello."})
    assert old.complete is None


@pytest.mark.parametrize("extra", [{"audio": "raw"}, {"frames": []}, {"finished_at": "invented"}])
def test_completion_metadata_does_not_admit_raw_media_or_unknown_fields(extra):
    with pytest.raises(ValidationError):
        TranscriptTurn.model_validate({"role": "kaiku", "text": "Hello.", "complete": True, **extra})
