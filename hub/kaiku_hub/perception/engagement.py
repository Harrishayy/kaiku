"""Multi-cue engagement summary for one ritual (obs.engagement). Pure and deterministic: numbers in, numbers out.

"How animated was this session?" is never read off the face alone. Every cue that was actually captured gives a
0-1 level on a FIXED reference range (not a personal baseline: the cloud owns baselines) with its own confidence:

    cue     level                                              confidence
    dial    mean of mood + energy answers, (v - 1) / 4         1.0 (both) / 0.7 (one)
    voice   1 - pause ratio of consented speech turns          seconds of speech / 10, capped at 1
    drum    taps per second / 3 (180 bpm = full scale)         drum quality (bounce share, short sessions)
    face    share of looks with exactly one face in view       looks / 50, x mean detector confidence
    pulse   (HR - 50) / 60                                     the HRV observation's quality
    ritual  steps completed / steps started                    1.0

Rules (tested in hub/tests/test_engagement.py):
- A cue with no usable evidence is `available: false` with a reason. Missing is never a zero (D37).
- Face coverage under 20 % of looks, or two faces for more than 20 % of them, makes the face cue missing.
- Fused level = sum(share x level) over available cues, share ~ weight x confidence, where the face share may never
  exceed `FACE_MAX_SHARE` (0.25) and, with 3 or more cues, no cue's share may exceed `MAX_SHARE` (0.5).
- Fewer than 2 available cues -> level is None ("not enough cues"): no single cue decides anything.
- `agreement` = 1 - (max - min) of the available levels: low agreement means the cues disagree, read with care.

It is an observation feature with provenance: not an emotion, not a diagnosis, and it feeds no verdict. Face
numbers are box positions from `raw.hub.face`; the hub never sees an image. Speech numbers are the pace/pause
summaries of `obs.speech_features`; no audio or words. Only computed for a ritual whose conversation the person
accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, pstdev

WEIGHTS: dict[str, float] = {"dial": 0.30, "voice": 0.20, "drum": 0.20, "face": 0.15, "pulse": 0.10, "ritual": 0.05}
ORDER: tuple[str, ...] = ("dial", "voice", "drum", "face", "pulse", "ritual")
MAX_SHARE = 0.5
FACE_MAX_SHARE = 0.25
MIN_CUES = 2
FACE_MIN_COVERAGE = 0.2
FACE_MIN_LOOKS = 10
TWO_FACE_MAX_SHARE = 0.2
DRUM_FULL_TAPS_PER_S = 3.0
HR_REF_BPM = (50.0, 110.0)
SPEECH_FULL_S = 10.0


def _clip(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _missing(cue: str, why: str) -> dict:
    return {"cue": cue, "available": False, "confidence": 0.0, "basis": why[:120]}


def _cue(cue: str, level: float, confidence: float, basis: str) -> dict:
    if confidence <= 0:
        return _missing(cue, f"no confidence: {basis}")
    return {"cue": cue, "available": True, "level": round(_clip(level), 3), "confidence": round(_clip(confidence), 3),
            "basis": basis[:120]}


def fuse(cues: list[dict]) -> tuple[float | None, float, float | None]:
    """(level, confidence, agreement) from cue dicts. Level is None with fewer than MIN_CUES usable cues."""
    usable = [c for c in cues if c["available"]]
    if len(usable) < MIN_CUES:
        return None, 0.0, None
    raw = {c["cue"]: WEIGHTS[c["cue"]] * c["confidence"] for c in usable}
    others_cap = MAX_SHARE if len(raw) >= 3 else 1.0  # with two cues one of them necessarily holds >= half
    caps = {k: (FACE_MAX_SHARE if k == "face" else others_cap) for k in raw}
    share = {k: v / sum(raw.values()) for k, v in raw.items()}
    fixed: set[str] = set()
    for _ in range(len(share)):  # capping one cue raises the others' shares, so repeat until none is over
        over = {k for k, v in share.items() if v > caps[k] + 1e-9}
        if not over:
            break
        fixed |= over
        left = 1.0 - sum(caps[k] for k in fixed)
        base = sum(raw[k] for k in share if k not in fixed)
        share = {k: (caps[k] if k in fixed else (left * raw[k] / base if base else 0.0)) for k in share}
    level = sum(share[c["cue"]] * c["level"] for c in usable) / (sum(share.values()) or 1.0)
    confidence = sum(raw.values()) / sum(WEIGHTS.values())
    levels = [c["level"] for c in usable]
    return round(_clip(level), 3), round(_clip(confidence), 3), round(_clip(1.0 - (max(levels) - min(levels))), 3)


@dataclass
class EngagementTracker:
    """Collects one ritual's cues as they happen (Hub feeds it; nothing here does I/O)."""

    looks: int = 0
    one_face: int = 0
    two_faces: int = 0
    _conf: list[float] = field(default_factory=list)
    _xs: list[float] = field(default_factory=list)
    _ys: list[float] = field(default_factory=list)
    dial: dict[str, int] = field(default_factory=dict)
    speech: list[dict] = field(default_factory=list)
    drum: dict | None = None
    drum_quality: float = 0.0
    hrv: dict | None = None
    hrv_quality: float = 0.0
    hrv_reason: str = "not measured"
    steps_started: int = 0
    steps_completed: int = 0
    camera_seen: bool = False

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]

    # ------------------------------------------------------------ inputs
    def look(self, faces: int, face: dict | None = None) -> None:
        """One sample per attention tick while the ritual runs: how many faces the camera has right now."""
        self.looks += 1
        if faces == 1:
            self.one_face += 1
            if face:
                self._conf.append(float(face.get("confidence", 0.0)))
                self._xs.append(float(face.get("x_norm", 0.0)))
                self._ys.append(float(face.get("y_norm", 0.0)))
        elif faces >= 2:
            self.two_faces += 1

    def on_obs(self, type_: str, payload: dict, quality: float | None) -> None:
        """Feed every observation the hub emits during the ritual."""
        if type_ == "obs.self_report" and payload.get("context", "ritual") == "ritual":
            self.dial[payload["item"]] = int(payload["value"])
        elif type_ == "obs.speech_features":
            self.speech.append(payload)
        elif type_ == "obs.drum_session":
            self.drum, self.drum_quality = payload, 1.0 if quality is None else quality
        elif type_ == "obs.hrv_session":
            self.hrv, self.hrv_quality = payload, 0.0 if quality is None else quality
        elif type_ == "obs.ritual":
            if payload.get("status") == "started":
                self.steps_started += 1
            elif payload.get("status") == "completed":
                self.steps_completed += 1

    # ------------------------------------------------------------ cues
    def _dial(self) -> dict:
        vals = [self.dial[k] for k in ("mood", "energy") if k in self.dial]
        if not vals:
            return _missing("dial", "no mood or energy answer")
        said = ", ".join(f"{k} {self.dial[k]}" for k in ("mood", "energy") if k in self.dial)
        return _cue("dial", (mean(vals) - 1) / 4, 1.0 if len(vals) == 2 else 0.7, said)

    def _voice(self) -> dict:
        secs = sum(float(f.get("duration_s", 0)) for f in self.speech)
        if not self.speech or secs <= 0:
            return _missing("voice", "no usable consented speech")
        pause = sum(float(f["pause_ratio"]) * float(f.get("duration_s", 0)) for f in self.speech) / secs
        return _cue("voice", 1.0 - pause, secs / SPEECH_FULL_S, f"{len(self.speech)} turns, {secs:.0f} s, pauses {pause:.0%}")

    def _drum(self) -> dict:
        d = self.drum
        if not d or not d.get("taps"):
            return _missing("drum", "no drum session")
        rate = d.get("taps_per_s")
        if rate is None:
            rate = (d.get("tempo_bpm") or 0) / 60
        return _cue("drum", rate / DRUM_FULL_TAPS_PER_S, self.drum_quality, f"{rate:.1f} taps/s, {d['taps']} taps")

    def _face(self) -> dict:
        if not self.camera_seen:
            return _missing("face", "no camera data")
        if self.looks < FACE_MIN_LOOKS:
            return _missing("face", "too few looks")
        if self.two_faces / self.looks > TWO_FACE_MAX_SHARE:
            return _missing("face", "more than one person in view")
        coverage = self.one_face / self.looks
        if coverage < FACE_MIN_COVERAGE:
            return _missing("face", f"face in view only {coverage:.0%} of {self.looks} looks")
        move = (pstdev(self._xs) + pstdev(self._ys)) / 2 if len(self._xs) > 1 else 0.0
        conf = min(1.0, self.looks / 50) * (mean(self._conf) if self._conf else 0.0)
        return _cue("face", coverage, conf, f"face in view {coverage:.0%} of {self.looks} looks, movement {move:.2f}")

    def _pulse(self) -> dict:
        h = self.hrv
        if not h:
            return _missing("pulse", f"not measured: {self.hrv_reason}" if self.hrv_reason else "not measured")
        lo, hi = HR_REF_BPM
        return _cue("pulse", (h["hr_bpm"] - lo) / (hi - lo), self.hrv_quality,
                    f"{h['hr_bpm']:.0f} bpm ({h.get('method') or 'finger'})")

    def _ritual(self) -> dict:
        if not self.steps_started:
            return _missing("ritual", "no step started")
        return _cue("ritual", self.steps_completed / self.steps_started, 1.0,
                    f"{self.steps_completed} of {self.steps_started} steps completed")

    def summary(self, session_id: str | None = None) -> dict:
        """obs.engagement payload."""
        cues = [getattr(self, f"_{name}")() for name in ORDER]
        level, confidence, agreement = fuse(cues)
        out: dict = {"confidence": confidence, "cues_available": sum(c["available"] for c in cues), "cues": cues,
                     "method": "robot-multicue-v1"}
        if session_id:
            out["session_id"] = session_id[:64]
        if level is not None:
            out["level"] = level
            out["agreement"] = agreement
        return out
