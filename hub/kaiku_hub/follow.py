"""Follow a head that runs the ritual itself (standalone firmware, D44) and turn what it sends into observations.

Pure state machine: messages in, a list of actions out (`Hub._follow_do` executes them). No I/O, no clock of its own.

What the standalone head sends over MQTT (firmware/atech-head/standalone/src/main.cpp + kaiku_net.cpp):

    health/head        every 5 s, retained: details.step = idle|greet|mood|energy|sleep|breathe|drum|done,
                       details.firmware = "standalone"; last will = status down
    raw.head.ear       {value, delta, pressed:false}  a knob turn, ONLY while a dial step is open; value = dial 1-10
                       {value, 0, pressed:true}       every knob press in ANY step (value = the last dial value):
                         idle -> greet · greet -> mood (starts the ritual) · mood/energy/sleep -> confirms that dial
                         with `value` and moves on · breathe -> skips to drum · drum -> ends it · done -> idle
    cmd.sensors{chime} wake = the head entered greet · start_drum = entered drum · end_drum = drum over, now done
    raw.head.pan       {deg 0, homed, moving}: on change + every 2 s (the UNO Q mutes knocks while the motor runs)
  and from the UNO Q, unchanged: raw.head.tap (knock, no force), raw.hub.face, raw.sensors.distance, raw.sensors.ppg.

The head never sends the ritual's results (mood/energy/sleep, the drum summary, breathing completed): those go to
USB serial only. So the follower keeps a shadow of the head's step and derives:

    obs.ritual         greet / dial (mood+energy+sleep) / breathe / drum / close: started + completed|skipped|aborted
    obs.self_report    one per confirmed dial press: `scale_10` = the value as dialled, `value` = ceil(scale_10 / 2)
    obs.drum_session   from the UNO Q knocks received while the head is in drum (>= min_taps; not while it moves)
    obs.hrv_session    only if the UNO Q pulse passes every gate (the hub asks the UNO Q for it during breathe)

Honesty rules:
- A dial answer is held until the head itself confirms the hub's shadow (the next health with the same step, or a
  chime the shadow expected). If they disagree (a lost press, a USB-serial command), the held answers are dropped
  with a note, never relabelled: a value is only ever recorded under the item it was dialled for.
- Not derivable, so never emitted: a post-drum mood (the head doesn't ask), drum force and the head's own
  motion-sensor taps (serial only), PHQ-9, a suggestion.
- A greeting is an offer, not a ritual: it is recorded when the person presses to start (then `greet` started /
  completed carry its real times). An unanswered greeting is recorded (`greet` skipped) at most once per
  `unanswered_gap_s`, because the head greets again whenever it sees a face.
- The head disappears (health `down`, or silent for `stale_s`): the open step is `aborted`, the ritual `ended_early`.
- A ritual the hub did not see start by a press (joined mid-way) is recorded but not consented: no engagement summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .perception.hrv import HrvResult, PpgBuffer
from .perception.taps import TapAnalyzer

HEAD_STEPS: tuple[str, ...] = ("idle", "greet", "mood", "energy", "sleep", "breathe", "drum", "done")
DIAL: tuple[str, ...] = ("mood", "energy", "sleep")
RITUAL_STEP: dict[str, str] = {"greet": "greet", "mood": "dial", "energy": "dial", "sleep": "dial",
                               "breathe": "breathe", "drum": "drum", "done": "close"}
AFTER_PRESS: dict[str, str] = {"greet": "mood", "mood": "energy", "energy": "sleep", "sleep": "breathe",
                               "breathe": "drum", "drum": "done", "done": "idle"}
# chime -> (the step the head just entered, shadow steps from which that is what the hub expected)
CHIMES: dict[str, tuple[str, tuple[str | None, ...]]] = {
    "wake": ("greet", (None, "idle", "done", "greet")),
    "start_drum": ("drum", ("breathe", "drum")),
    "end_drum": ("done", ("drum", "done")),
}
HEAD_BREATH_BPM = 6.0  # main.cpp: 4 s in + 6 s out
HEALTH_MAX_AGE_S = 60.0  # an older health/head is a retained leftover, not the head's present step

Action = tuple[Any, ...]
# ("begin", reason) · ("end", outcome, consented, dial{item: 1-5}) · ("emit", type, payload, quality, when)
#   when = None (now) | datetime (the head's own timestamp) | float (seconds ago)
# ("sensors", {cmd}) · ("note", event, {fields})


def scale_5(value_10: int) -> int:
    """The head's 1-10 dial on the contract's 1-5 scale: 1-2 -> 1, 3-4 -> 2, 5-6 -> 3, 7-8 -> 4, 9-10 -> 5."""
    return (int(value_10) + 1) // 2


def _measures(r: HrvResult | None) -> dict[str, float]:
    if r is None or not r.ok:
        return {}
    return {k: v for k, v in (("rmssd_ms", r.rmssd_ms), ("hr_bpm", r.hr_bpm)) if v is not None}


@dataclass
class HeadFollower:
    refractory_ms: float = 80
    force_max_g: float = 4.0
    min_taps: int = 4
    stale_s: float = 15.0
    unanswered_gap_s: float = 3 * 3600.0  # an unanswered greeting is recorded at most this often
    ppg_band_hz: tuple[float, float] = (0.7, 3.5)
    ppg_min_clean_ratio: float = 0.7
    hrv_window_s: float = 30.0
    quality_min: float = 0.5

    step: str | None = None          # shadow of the head's step; None = not heard (or lost)
    active: bool = False             # a ritual is being recorded
    consented: bool = False          # the hub saw the person press to start this ritual
    last_health: float | None = None
    pan_moving: bool = False
    muted_taps: int = 0
    unanswered: int = 0              # greetings nobody answered since the hub started
    _greet_at: float | None = None   # the head is greeting; not a record until the person answers
    _last_unanswered: float | None = None
    _t0: float = 0.0                 # when the open ritual step started
    _held: list[tuple[str, int, datetime | None]] = field(default_factory=list)  # dial answers awaiting confirmation
    _dial: dict[str, int] = field(default_factory=dict)                          # confirmed, 1-5
    _dial_presses: int = 0
    _taps: TapAnalyzer = field(default_factory=TapAnalyzer)
    _ppg: PpgBuffer = field(default_factory=PpgBuffer)

    # ------------------------------------------------------------ inputs
    def on_health(self, status: str, details: dict, now: float, age_s: float = 0.0) -> list[Action]:
        if status == "down":
            return self.lost(now, "head reported down")
        step = details.get("step")
        if step not in HEAD_STEPS or age_s > HEALTH_MAX_AGE_S:
            return []
        self.last_health = now
        if step == self.step:
            return self._confirm()
        out = self._drop_held(f"head is in {step}, hub expected {self.step}")
        return out + self._goto(step, now, cause="health")

    def on_chime(self, name: str, now: float) -> list[Action]:
        if name not in CHIMES:
            return []
        target, expected = CHIMES[name]
        out = self._confirm() if self.step in expected else self._drop_held(f"{name} chime while hub expected {self.step}")
        if name == "wake" and self.step == "greet":
            if not self.active:
                self._greet_at = now  # the greeting timed out silently and started again
            return out
        return out + self._goto(target, now, cause="chime")

    def on_ear(self, value: int, pressed: bool, ts: datetime | None, now: float) -> list[Action]:
        if not pressed:
            return []  # a turn only moves the dial; the press carries the answer
        step = self.step
        if step not in AFTER_PRESS:
            return []  # idle / unknown: the wake chime or the next health says what the press did
        out: list[Action] = []
        if step == "greet":
            self.consented = True  # the person started the ritual themselves
        elif step in DIAL:
            self._dial_presses += 1
            if 1 <= int(value) <= 10:
                self._held.append((step, int(value), ts))
            else:
                out.append(("note", "dial_value_out_of_range", {"item": step, "value": int(value)}))
        return out + self._goto(AFTER_PRESS[step], now, cause="press")

    def on_tap(self, t_ms: int, force: float | None = None) -> bool:
        """A UNO Q knock. Counted only while the head is in drum and its motor is still."""
        if self.step != "drum" or not self.active:
            return False
        if self.pan_moving:
            self.muted_taps += 1
            return False
        return self._taps.add(int(t_ms), force)

    def on_pan(self, moving: bool) -> None:
        self.pan_moving = bool(moving)

    def on_ppg(self, fs_hz: float, samples: list[int], t0_ms: float | None, quality: float | None) -> None:
        if self.step == "breathe" and self.active:
            self._ppg.add(fs_hz, samples, t0_ms=t0_ms, quality=quality)

    def tick(self, now: float) -> list[Action]:
        if self.step is not None and self.last_health is not None and now - self.last_health > self.stale_s:
            return self.lost(now, f"no health/head for {self.stale_s:.0f} s")
        return []

    def lost(self, now: float, reason: str) -> list[Action]:
        """The head is gone (or stopped being a standalone head): record honestly what was open."""
        out = self._abort(now, "ended_early", reason) if self.active else []
        self.step, self.last_health, self._held, self._greet_at = None, None, [], None
        return out

    def abort(self, now: float, outcome: str, reason: str) -> list[Action]:
        """The hub ends the recording (crisis). The head keeps its own ritual; nothing more is recorded until the
        next greeting."""
        return self._abort(now, outcome, reason) if self.active else []

    # ------------------------------------------------------------ held dial answers
    def _confirm(self) -> list[Action]:
        out: list[Action] = []
        for item, v10, ts in self._held:
            self._dial[item] = scale_5(v10)
            out.append(("emit", "obs.self_report", {"item": item, "value": scale_5(v10), "context": "ritual",
                                                    "channel": "robot", "scale_10": v10}, None, ts))
        self._held = []
        return out if self.active else []

    def _drop_held(self, why: str) -> list[Action]:
        if not self._held:
            return []
        dropped, self._held = [i for i, _v, _t in self._held], []
        return [("note", "dial_unattributed", {"reason": why, "items": dropped})]

    # ------------------------------------------------------------ transitions
    def _ritual_obs(self, step: str, status: str, now: float) -> Action:
        payload: dict[str, Any] = {"step": RITUAL_STEP[step], "status": status}
        if status != "started":
            payload["duration_s"] = round(max(0.0, now - self._t0), 1)
        return ("emit", "obs.ritual", payload, None, None)

    def _close(self, old: str, new: str | None, now: float, cause: str) -> list[Action]:
        """Close the ritual step the head just left. `new` None = the head is gone or the hub stopped recording."""
        out: list[Action] = []
        forward = new is not None and new != "idle" and HEAD_STEPS.index(new) > HEAD_STEPS.index(old)
        status = "completed" if forward else "aborted"
        if old == "greet":
            status = "completed" if forward else ("skipped" if new == "idle" else "aborted")
        elif old in DIAL:
            if forward and not self._dial_presses:
                status = "skipped"
        elif old == "breathe":
            out.append(("sensors", {"ppg": "stop"}))
            if forward and cause == "press":
                status = "skipped"  # the person pressed to skip the breathing (main.cpp: breathe completed false)
            elif forward:
                out += self._pulse(now)
        elif old == "drum":
            if forward and self._taps.count >= self.min_taps:
                dur = (self._taps.times[-1] - self._taps.times[0]) / 1000 if self._taps.count > 1 else 0.0
                payload = {k: v for k, v in self._taps.summary(dur).items() if v is not None or k == "force_mean"}
                out.append(("emit", "obs.drum_session", payload, self._taps.quality(), None))
            elif forward:
                status = "skipped"
                out.append(("note", "drum_not_recorded", {"reason": f"{self._taps.count} knocks reached the hub "
                                                                    f"(need {self.min_taps})", "muted": self.muted_taps}))
        out.append(self._ritual_obs(old, status, now))
        return out

    def _pulse(self, now: float) -> list[Action]:
        payload, quality, pre, post = self._ppg.session(
            HEAD_BREATH_BPM, now - self._t0, self.ppg_band_hz, self.ppg_min_clean_ratio,
            window_s=self.hrv_window_s, quality_min=self.quality_min)
        if not payload:
            return [("note", "pulse_not_measured", {"reason": self._ppg.reason, "seconds": round(self._ppg.seconds, 1),
                                                    "method": self._ppg.method, "restarts": self._ppg.restarts})]
        out: list[Action] = [("emit", "obs.hrv_session", payload, quality, None)]
        pre_m, post_m = _measures(pre), _measures(post)
        if pre_m and post_m:
            delta = {k: round(post_m[k] - pre_m[k], 2) for k in pre_m if k in post_m}
            out.append(("emit", "obs.intervention_response",
                        {"activity": "breathe", "pre": pre_m, "post": post_m, "delta": delta}, quality, None))
        return out

    def _open(self, new: str, now: float) -> list[Action]:
        self._t0 = now
        out: list[Action] = [self._ritual_obs(new, "started", now)]
        if new in DIAL:
            self._dial_presses = 0
        elif new == "breathe":
            self._ppg = PpgBuffer()
            out.append(("sensors", {"ppg": "start"}))  # to the UNO Q; the head never asks for the pulse
        elif new == "drum":
            self._taps = TapAnalyzer(self.refractory_ms, self.force_max_g)
            self.muted_taps = 0
        return out

    def _end(self, outcome: str) -> Action:
        self.active = False
        return ("end", outcome, self.consented and outcome != "crisis", dict(self._dial))

    def _abort(self, now: float, outcome: str, reason: str) -> list[Action]:
        out = self._drop_held(reason)
        if self.step in RITUAL_STEP:
            out += self._close(self.step, None, now, "lost")
        out.append(("note", "ritual_cut_short", {"reason": reason, "at_step": self.step}))
        out.append(self._end(outcome))
        return out

    def _fresh(self, reason: str) -> Action:
        self.active = True
        self._held, self._dial, self._dial_presses = [], {}, 0
        return ("begin", reason)

    def _goto(self, new: str, now: float, *, cause: str) -> list[Action]:
        old = self.step
        if new == old:
            return []
        out: list[Action] = []
        if self.active and old is not None and new != "idle" and HEAD_STEPS.index(new) < HEAD_STEPS.index(old):
            # the head went backwards (a `greet` / `ritual` serial command, or a reboot into a new ritual)
            out += self._abort(now, "ended_early", f"head went from {old} back to {new}")
        if not self.active and old == "greet" and self._greet_at is not None:
            # The greeting resolves. A greeting is only an offer: it becomes a record when the person answers it,
            # and an unanswered one is recorded at most once per `unanswered_gap_s` (the head re-greets whenever
            # it sees a face, about once a minute).
            greet_at, self._greet_at = self._greet_at, None
            answered = new != "idle"
            if not answered:
                self.unanswered += 1
            if answered or self._last_unanswered is None or now - self._last_unanswered >= self.unanswered_gap_s:
                if not answered:
                    self._last_unanswered = now
                out.append(self._fresh("follow"))
                self._t0 = greet_at
                out.append(("emit", "obs.ritual", {"step": "greet", "status": "started"}, None, now - greet_at))
        old_r, new_r = (RITUAL_STEP.get(old) if old else None), RITUAL_STEP.get(new)
        if self.active and old in RITUAL_STEP and old_r != new_r:
            out += self._close(old, new, now, cause)
        self.step = new
        if self.active and new == "idle":  # the ritual stopped before its end
            out.append(self._end("skipped" if old == "greet" else "ended_early"))
            return out
        if not self.active and new == "greet":
            self._greet_at, self.consented = now, False
            return out
        if not self.active and new_r and old is None and new != "done":
            # the hub first hears the head in the middle of a ritual: record the rest, without consent
            self.consented = False
            out.append(self._fresh("follow-joined"))
            old_r = None
        if self.active and new_r and new_r != old_r:
            out += self._open(new, now)
            if new == "done":  # the head's goodbye: nothing more to wait for
                out.append(self._ritual_obs("done", "completed", now))
                out.append(self._end("completed"))
        return out
