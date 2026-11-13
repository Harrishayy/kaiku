"""Attention ladder: who is in front of the robot, and what the body does about it. Pure + deterministic.

    nobody -> appeared -> approaching -> at_desk          (plan 03 §5.1)

Inputs: face detections (`raw.hub.face` payloads, from the laptop camera or the UNO Q YOLO adapter; one message
per face, several faces = several messages in the same ~frame), distance presence, quiet mode, local time,
"ritual done today", "ritual running". Output: a list of actions the hub executes:

    ("head", {...cmd.head payload...})   glance / track (pan + eyes) / purr / home
    ("say", "greet.morning")             a keyed line from config/voice_lines.toml
    ("offer", None)                      offer today's ritual (the hub starts it; GREET asks, "no" ends it)

Ladder per visit: glance (eyes, appeared) -> purr (approaching) -> spoken greeting by time of day (at desk)
-> offer the ritual if not done today. Rules (numbers in config/kaiku.toml [attention]):
- a face lost for < lost_s doesn't reset the visit (detector flicker);
- greet at most once per regreet_h;
- no purr/greeting in quiet mode ("not now") or in the night window [night_start, night_end), unless the person
  started it (spoke / pressed first);
- two or more faces -> "hello you two" (greet.two), never a ritual offer (privacy);
- while a ritual runs, the ritual owns the body: the ladder only keeps its state.
No I/O, no clocks: every call takes `now` (an aware local datetime).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

Action = tuple[str, Any]

STATES = ("nobody", "appeared", "approaching", "at_desk")


def _hhmm(s: str | time) -> time:
    if isinstance(s, time):  # env overrides are parsed as TOML: KAIKU_ATTENTION_NIGHT_START=00:00 is a time
        return s.replace(second=0, microsecond=0)
    h, m = str(s).split(":")[:2]
    return time(int(h), int(m))


@dataclass
class AttentionConfig:
    lost_s: float = 2.0             # face gone this long (and nobody near) -> the visit is over
    approach_size: float = 0.12     # face width / frame width that counts as "coming closer"
    at_desk_size: float = 0.22      # ... and as "at the desk"
    frame_s: float = 0.3            # detections this close in time belong to one camera frame
    two_face_min_sep: float = 0.25  # two detections further apart than this (x_norm) are two people
    camera_hfov_deg: float = 60.0   # fixed camera: x_norm -1..1 maps to -hfov/2..+hfov/2 pan
    pan_deadband_deg: float = 4.0   # don't move the head for smaller changes (no twitching)
    pan_smoothing: float = 0.4      # EMA weight of the newest face position
    pan_speed: float = 0.4
    track_hz: float = 5.0           # max head commands per second while tracking
    regreet_h: float = 3.0
    night_start: str | time = "23:00"      # night window [start, end); equal values disable it
    night_end: str | time = "07:00"
    quiet_h: float = 2.0            # "not now" keeps Kaiku quiet this long

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AttentionConfig:
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def greet_key(now: datetime) -> str:
    h = now.hour
    if 5 <= h < 12:
        return "greet.morning"
    if 12 <= h < 17:
        return "greet.afternoon"
    if 17 <= h < 23:
        return "greet.evening"
    return "greet.night"


@dataclass
class _Det:
    at: datetime
    x: float
    y: float
    size: float


@dataclass
class Attention:
    cfg: AttentionConfig = field(default_factory=AttentionConfig)
    state: str = "nobody"
    present: bool = False                 # distance sensor says someone is near
    faces_seen: bool = False              # a face source exists (else presence alone means "at desk")
    last_greet: datetime | None = None
    quiet_until: datetime | None = None
    person_started_at: datetime | None = None
    _dets: list[_Det] = field(default_factory=list)
    _last_face: datetime | None = None
    _max_faces: int = 0                   # most faces seen at once during this visit
    _greeted_visit: bool = False
    _purred: bool = False
    _pan: float | None = None             # smoothed target (deg)
    _pan_sent: float | None = None
    _last_track: datetime | None = None

    # ------------------------------------------------------------------ inputs
    def add_face(self, payload: dict[str, Any], now: datetime) -> None:
        self.faces_seen = True
        self._dets.append(_Det(now, float(payload["x_norm"]), float(payload["y_norm"]), float(payload["size"])))
        self._last_face = now

    def set_present(self, present: bool) -> None:
        self.present = present

    def quiet(self, now: datetime) -> None:
        """'not now' / 'quiet': no purrs or greetings for quiet_h."""
        self.quiet_until = now + timedelta(hours=self.cfg.quiet_h)

    def person_started(self, now: datetime) -> None:
        """The person spoke or pressed first: greeting is allowed even at night / in quiet mode."""
        self.person_started_at = now

    # ------------------------------------------------------------------ rules
    def is_night(self, now: datetime) -> bool:
        start, end = _hhmm(self.cfg.night_start), _hhmm(self.cfg.night_end)
        t = now.time().replace(second=0, microsecond=0)
        if start == end:
            return False
        if start < end:
            return start <= t < end
        return t >= start or t < end

    def is_quiet(self, now: datetime) -> bool:
        return self.quiet_until is not None and now < self.quiet_until

    def _person_started_recently(self, now: datetime) -> bool:
        return self.person_started_at is not None and now - self.person_started_at < timedelta(minutes=5)

    def may_speak(self, now: datetime) -> bool:
        if self._person_started_recently(now):
            return True
        return not self.is_quiet(now) and not self.is_night(now)

    def _greet_cooled(self, now: datetime) -> bool:
        return self.last_greet is None or now - self.last_greet >= timedelta(hours=self.cfg.regreet_h)

    def face_count(self, now: datetime) -> int:
        """Distinct people in the latest frame (detections within frame_s, separated by two_face_min_sep)."""
        recent = [d for d in self._dets if (now - d.at).total_seconds() <= self.cfg.frame_s]
        xs: list[float] = []
        for d in sorted(recent, key=lambda d: d.x):
            if not xs or d.x - xs[-1] > self.cfg.two_face_min_sep:
                xs.append(d.x)
        return len(xs)

    def _biggest(self, now: datetime) -> _Det | None:
        recent = [d for d in self._dets if (now - d.at).total_seconds() <= self.cfg.frame_s]
        return max(recent, key=lambda d: d.size) if recent else None

    # ------------------------------------------------------------------ the ladder
    def tick(self, now: datetime, *, ritual_done_today: bool = False, ritual_running: bool = False) -> list[Action]:
        cfg = self.cfg
        horizon = max(cfg.frame_s, cfg.lost_s)
        self._dets = [d for d in self._dets if (now - d.at).total_seconds() <= horizon]
        face_now = self._biggest(now)
        face_recent = self._last_face is not None and (now - self._last_face).total_seconds() < cfg.lost_s
        out: list[Action] = []

        # ---- visit over? (face lost >= lost_s and nobody near)
        if not face_recent and not self.present:
            if self.state != "nobody":
                self._reset_visit()
                if not ritual_running:
                    out.append(("head", {"home": True, "eyes": "neutral"}))
            return out

        # ---- the ladder only goes up during a visit
        n = self.face_count(now)
        self._max_faces = max(self._max_faces, n, 1 if self.present else 0)
        level = STATES.index(self.state)
        if face_now is not None:
            if face_now.size >= cfg.at_desk_size:
                level = max(level, 3)
            elif face_now.size >= cfg.approach_size:
                level = max(level, 2)
            else:
                level = max(level, 1)
        if self.present and (face_recent or not self.faces_seen):
            level = 3
        elif self.present:
            level = max(level, 2)
        new_state = STATES[level]
        speak_ok = self.may_speak(now)

        if not ritual_running:
            if self.state == "nobody" and level >= 1:
                out.append(("head", {"eyes": "wide"}))                       # glance
            if level >= 2 and not self._purred and speak_ok:
                self._purred = True
                out.append(("head", {"purr": {"ms": 400}, "eyes": "happy"}))  # soft purr
            if face_now is not None:
                track = self._track(face_now, now)
                if track:
                    out.append(("head", track))
        self.state = new_state

        # ---- greeting + offer, once per visit
        if level == 3 and not self._greeted_visit and not ritual_running and speak_ok:
            self._greeted_visit = True  # once per visit (a night/quiet visit waits: the person may start it)
            if self._greet_cooled(now):
                self.last_greet = now
                if self._max_faces >= 2:
                    out.append(("say", "greet.two"))
                else:
                    out.append(("say", greet_key(now)))
                    if not ritual_done_today:
                        out.append(("head", {"eyes": "listening"}))  # ear up / attentive (see hub/AGENTS.md)
                        out.append(("offer", None))
        return out

    def _track(self, face: _Det, now: datetime) -> dict[str, Any] | None:
        cfg = self.cfg
        if self._last_track is not None and (now - self._last_track).total_seconds() < 1.0 / cfg.track_hz:
            return None
        target = face.x * cfg.camera_hfov_deg / 2  # + = toward the image's right (firmware maps to its motor sign)
        self._pan = target if self._pan is None else self._pan + cfg.pan_smoothing * (target - self._pan)
        cmd: dict[str, Any] = {"look": {"x": round(face.x, 3), "y": round(face.y, 3)}}
        if self._pan_sent is None or abs(self._pan - self._pan_sent) >= cfg.pan_deadband_deg:
            self._pan_sent = round(self._pan, 1)
            cmd["pan"] = {"target_deg": self._pan_sent, "speed": cfg.pan_speed}
        self._last_track = now
        return cmd

    def _reset_visit(self) -> None:
        self.state = "nobody"
        self._max_faces = 0
        self._greeted_visit = False
        self._purred = False
        self._pan = None
        self._pan_sent = None
        self._last_track = None
        self._dets.clear()
        self._last_face = None
