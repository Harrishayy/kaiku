"""Kaiku's own model looks at a few pictures of the camera during a check-in (D65).

    device --a few small JPEGs, once--> POST /v1/vision/look --in memory--> Gemma --strict JSON--> obs.vision_note

With the person's separate opt-in on their device, the app sends at most `[vision_look] frames` downscaled pictures
of one check-in. This module hands them, in memory, to the Gemma named in `[models].gemma_hosted` (the one model the
person was told about: `llm/gemma.look`; there is no fallback to another model) with a fixed prompt, validates what
comes back against the closed lists of `VisionNote`, and stores ONLY that as `obs.vision_note`.

The pictures are never kept. Everything here is written so that a picture's bytes cannot reach a disk, a database
row, a log line, an exception text or a retry:
- the route reads the request body itself (no request model, so no validation error can echo a picture back);
- pictures live in local variables of `look` and of the adapter call it makes, and nowhere else;
- every failure is turned into a short fixed reason; no exception text is passed on, because a library's message
  could quote its request;
- nothing is queued: a model that is down, a spend cap, a bad answer = nothing stored, and the device does not
  send the same pictures again.
`cloud/tests/test_vision.py` puts a marker in a picture and looks for it in the database file, the logs and the
answer.

It decides nothing. The note is a description of pictures, a reason to ask: shown and citable, never scored.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from kaiku_contracts import ContractError, make
from kaiku_contracts.config import get
from kaiku_contracts.jlog import get_logger
from kaiku_contracts.payloads import FACE_TASKS, VisionNote

from .llm import gemma
from .llm.errors import LlmUnavailable
from .store.db import Store

log = get_logger("cloud")

DEVICES = ("phone", "mac", "robot")
JPEG = b"\xff\xd8\xff"
FIELDS = ("face_visible", "expression", "gaze", "posture", "lighting", "confidence")

PROMPT = (
    "You are shown {n} small still picture{s} taken by a person's own device during a short check-in. Describe ONLY "
    "what can be seen. Do not guess what the person feels, thinks or is going through, do not judge their health, "
    "and do not identify them. Answer with ONE JSON object and nothing else, with exactly these keys:\n"
    '{{"face_visible": true|false, "expression": "neutral"|"smiling"|"lowered"|"tense"|"unclear", '
    '"gaze": "toward_camera"|"away"|"unclear", "posture": "upright"|"leaning"|"slumped"|"unclear", '
    '"lighting": "bright"|"dim"|"dark"|"unclear", "confidence": 0.0-1.0}}\n'
    "expression: neutral = a resting face; smiling = the mouth corners are up; lowered = mouth corners down or "
    "inner brows raised; tense = brows drawn together, lips pressed or eyes narrowed; unclear = no face, or it "
    "cannot be read. Use unclear whenever you are not sure. Across several pictures, give what holds for most of "
    "them. confidence is how sure you are of this description as a whole."
)


def cfg(key: str, default: Any) -> Any:
    return get("vision_look", key, default)


def enabled() -> bool:
    return bool(cfg("enabled", True))


def rules() -> dict[str, Any]:
    """What a device needs to pick its pictures (`VisionLookRules`)."""
    return {"frames": int(cfg("frames", 3)), "settle_s": float(cfg("settle_s", 6)),
            "min_interval_s": float(cfg("min_interval_s", 12)), "max_edge_px": int(cfg("max_edge_px", 256)),
            "jpeg_quality": float(cfg("jpeg_quality", 0.6))}


class Refused(Exception):
    """The request cannot be looked at. `status` is the HTTP status; the text is fixed and holds nothing of the body."""

    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


def pictures(body: Any) -> tuple[str, str, str | None, list[bytes]]:
    """(task, device, ref, pictures) out of the request body, or `Refused`. Nothing of the body is put in a message."""
    if not isinstance(body, dict):
        raise Refused(400, "body must be a JSON object")
    task, device, ref, frames = body.get("task"), body.get("device"), body.get("ref"), body.get("frames")
    if task not in FACE_TASKS or device not in DEVICES:
        raise Refused(422, "task or device not known")
    if ref is not None and not (isinstance(ref, str) and 1 <= len(ref) <= 64):
        raise Refused(422, "ref must be a short id")
    limit = int(cfg("frames", 3))
    if not isinstance(frames, list) or not 1 <= len(frames) <= limit:
        raise Refused(422, f"frames: 1 to {limit} pictures")
    out: list[bytes] = []
    top = int(cfg("max_frame_bytes", 80_000))
    for f in frames:
        if not isinstance(f, str) or len(f) > top * 4 // 3 + 8:
            raise Refused(413, "a picture is too large")
        try:
            data = base64.b64decode(f, validate=True)
        except (binascii.Error, ValueError):
            raise Refused(422, "a picture is not base64") from None
        if len(data) > top or not data.startswith(JPEG):
            raise Refused(422, "a picture is not a small JPEG")
        out.append(data)
    return str(task), str(device), ref, out


def parse(text: str) -> dict[str, Any] | None:
    """The model's answer as the six fields, or None. Only the closed lists pass (`VisionNote` checks them again)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        raw = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(raw, dict) or any(k not in raw for k in FIELDS):
        return None
    out = {k: raw[k] for k in FIELDS}
    if not isinstance(out["face_visible"], bool) or isinstance(out["confidence"], bool):
        return None
    try:
        out["confidence"] = round(min(1.0, max(0.0, float(out["confidence"]))), 2)
    except (TypeError, ValueError):
        return None
    if not out["face_visible"]:
        out["expression"] = out["gaze"] = "unclear"  # no face: nothing about a face can have been seen
    return out


def _today_count(store: Store, home_id: str, now: datetime) -> int:
    since = (now - timedelta(hours=24)).isoformat()
    return sum(1 for e in store.events_for_home(home_id) if e["type"] == "obs.vision_note" and str(e["ts"]) >= since)


def look(store: Store, home_id: str, body: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """One look. Returns the `VisionLookResult` fields. Raises `Refused` for a request that is not one."""
    now = now or datetime.now(UTC)
    if not enabled():
        raise Refused(503, "looking at pictures is switched off on this service")
    task, device, ref, frames = pictures(body)
    n = len(frames)
    if _today_count(store, home_id, now) >= int(cfg("max_per_day", 12)):
        del frames
        return {"ok": True, "stored": False, "reason": "enough looks for today"}
    t0 = time.monotonic()
    try:
        text = gemma.look(PROMPT.format(n=n, s="" if n == 1 else "s"), frames, task="vision_look", home_id=home_id,
                          timeout_s=float(cfg("timeout_s", 30)))
    except LlmUnavailable:
        # never the exception's own text: a library's message may quote what it was sent
        log.info("vision_look", "model unavailable", home=home_id, frames=n)
        return {"ok": True, "stored": False, "reason": "the model is not available right now"}
    finally:
        del frames  # the pictures end here, whatever happened
    fields = parse(text)
    if fields is None:
        log.info("vision_look", "answer not usable", home=home_id, frames=n)
        return {"ok": True, "stored": False, "reason": "the model's answer could not be used"}
    payload = {"task": task, "device": device, "model": gemma.model_name(), "frames_n": n, **fields,
               "not_a_diagnosis": True, **({"ref": ref} if ref else {})}
    try:
        VisionNote(**payload)
        env = make("obs.vision_note", payload, source="cloud", home_id=home_id, quality=fields["confidence"])
    except (ContractError, ValueError):
        log.info("vision_look", "answer outside the closed lists", home=home_id, frames=n)
        return {"ok": True, "stored": False, "reason": "the model's answer could not be used"}
    store.insert_events([env.model_dump(mode="json", exclude_none=True)])
    log.info("vision_look", "noted", home=home_id, frames=n, ms=int((time.monotonic() - t0) * 1000),
             expression=fields["expression"])
    return {"ok": True, "stored": True, "note": payload}
