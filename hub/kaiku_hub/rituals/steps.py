"""The ritual steps (handoff §5.3). Steps only use RitualContext (no bus, no HTTP), so they're unit-testable.

    GREET -> DIAL(mood, energy, sleep) -> BREATHE -> DRUM(+ post-activity mood) -> [PHQ9 if due] -> NUDGE -> CLOSE

Add a step: subclass Step (name must be a contracts RitualStep), add it to default_steps(). See hub/AGENTS.md.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime
from typing import Any

from kaiku_contracts.payloads import DIAL_ITEMS

from ..perception.hrv import HrvResult, PpgBuffer
from ..perception.taps import TapAnalyzer
from .machine import Event, RitualContext, Status, Step

YES = re.compile(r"\b(yes|yeah|yep|sure|ok|okay|kyllä|joo|juu|ja|gärna)\b", re.I)
NO = re.compile(r"\b(no|nope|not today|not now|ei|nej)\b", re.I)
NUMBER_1_5 = re.compile(r"\b([1-5])\b")
NUMBER_0_3 = re.compile(r"\b([0-3])\b")

GREETINGS = {"fi": "Huomenta!", "en": "Good morning!", "sv": "God morgon!"}

DIAL_QUESTIONS = {
    "mood": "How are you today? Turn my ear: one is heavy, five is light. Press it when it feels right.",
    "energy": "And your energy? One is empty, five is full. Turn and press.",
    "sleep": "How did you sleep last night? One is badly, five is well.",
}
# Same questions for the button build (config [robot] dial_input = "button"): presses within a few seconds = the value.
DIAL_QUESTIONS_BUTTON = {
    "mood": "How are you today? Press my button once for heavy, up to five times for light. Or just say a number.",
    "energy": "And your energy? Once is empty, five times is full.",
    "sleep": "How did you sleep last night? Once is badly, five times is well.",
}
POST_MOOD_LINE = {"ear": "That was great. How do you feel now? Turn my ear and press.",
                  "button": "That was great. How do you feel now? Press my button, one to five times."}

NUDGE_LINES = {
    "breathe": "Maybe one more slow breathing minute later today?",
    "drum": "How about a little drumming session this afternoon?",
    "daylight_walk": "How about a short walk in the daylight today?",
    "friend_ping": "Shall I light up your friend's lamp to say hello?",
    "icbt_exercise": "There's a short exercise waiting in your programme. Want to try it today?",
}

# PHQ-9, standard wording (Kroenke, Spitzer & Williams; public domain). Item 9 is handled by the safety path.
PHQ9_INTRO = ("A few questions I ask every two weeks. Over the last two weeks, how often have you been bothered "
              "by each of these? Say zero for not at all, one for several days, two for more than half the days, "
              "or three for nearly every day.")
PHQ9_ITEMS = (
    "Little interest or pleasure in doing things",
    "Feeling down, depressed, or hopeless",
    "Trouble falling or staying asleep, or sleeping too much",
    "Feeling tired or having little energy",
    "Poor appetite or overeating",
    "Feeling bad about yourself, or that you are a failure or have let yourself or your family down",
    "Trouble concentrating on things, such as reading the newspaper or watching television",
    "Moving or speaking so slowly that other people could have noticed, or the opposite, being so fidgety "
    "or restless that you have been moving around a lot more than usual",
    "Thoughts that you would be better off dead, or of hurting yourself in some way",
)
PHQ9_WORDS = (
    (re.compile(r"not at all|never|ei lainkaan", re.I), 0),
    (re.compile(r"several days|some days|muutamana", re.I), 1),
    (re.compile(r"more than half", re.I), 2),
    (re.compile(r"nearly every|almost every|every day|lähes joka", re.I), 3),
)


def _button(ctx: RitualContext) -> bool:
    """True on the button build (config [robot] dial_input = "button"): answers are press counts, not ear turns."""
    return getattr(getattr(ctx, "settings", None), "dial_input", "ear") == "button"


async def _chime(ctx: RitualContext, name: str) -> None:
    """Short cue on the UNO Q buzzer (cmd.sensors chime). Nodes without a buzzer ignore it."""
    sensors = getattr(ctx, "sensors", None)
    if sensors is not None:
        await sensors(chime=name)


KNOCK_CLICK = 0.6  # music click loudness for taps without a force (knock switch)


def _today() -> date:
    return datetime.now().astimezone().date()


def _clamp_1_5(v: Any) -> int:
    return max(1, min(5, int(v)))


OFFER_LINE = "Shall we do our little check-in together? Press my ear to turn on our conversation."
OFFER_LINE_BUTTON = "Shall we do our little check-in together? Press my button to turn on our conversation."


class Greet(Step):
    """Greets, or, when the attention ladder already greeted (ctx.ritual_reason == "attention"), offers the
    ritual. Any answer or ear press goes on; "no" / "not today" ends the ritual politely (never pushes)."""

    name = "greet"

    async def enter(self, ctx: RitualContext) -> None:
        self._last_look = 0.0
        self._needs_consent = not getattr(ctx, "conversation_consented", True)
        if self._needs_consent:
            await ctx.head(eyes="listening", pan_mode="track")
            await ctx.say(OFFER_LINE_BUTTON if _button(ctx) else OFFER_LINE)
            return
        await _chime(ctx, "wake")
        await ctx.head(eyes="wide", pan_mode="track")
        g = GREETINGS.get(ctx.settings.greeting_language, GREETINGS["en"])
        await ctx.say(f"{g} It's good to see you.")

    async def handle(self, event: Event, ctx: RitualContext) -> Status | None:
        if event.kind == "face":
            now = time.monotonic()
            if now - self._last_look > 0.2:
                self._last_look = now
                await ctx.head(look={"x": event.data["x_norm"], "y": event.data["y_norm"]})
            return None
        if event.kind == "utterance" and NO.search(event.data.get("text", "")) and not YES.search(
                event.data.get("text", "")):
            self.stop_ritual = True
            await ctx.say("That's fine. Not today.")
            return "skipped"
        affirmative = (event.kind == "ear" and event.data.get("pressed", False)) or (
            event.kind == "utterance" and YES.search(event.data.get("text", "")))
        if affirmative:
            if self._needs_consent:
                ctx.accept_conversation()
                self._needs_consent = False
            return "completed"
        if not self._needs_consent and event.kind == "utterance":
            return "completed"
        return None

    def on_timeout(self) -> Status:
        if self._needs_consent:
            self.stop_ritual = True
            return "skipped"
        return "completed"


class Dial(Step):
    """Three questions answered by turning + pressing the ear (or saying 1-5, or the record_dial tool).

    Protocol (head firmware and head_sim follow it): each ear *press* answers the current question with the
    dial position at that moment; turns without a press only move the dial. Answers go in order
    mood -> energy -> sleep. Each answer emits obs.self_report immediately. On timeout, a turned-but-not-pressed
    dial still counts for the current question.
    """

    name = "dial"

    def __init__(self, timeout_s: float | None = None, items: tuple[str, ...] = DIAL_ITEMS):
        super().__init__(timeout_s)
        self.items = items
        self.answers: dict[str, int] = {}
        self.current: int | None = None

    @property
    def item(self) -> str | None:
        return next((i for i in self.items if i not in self.answers), None)

    async def enter(self, ctx: RitualContext) -> None:
        self.answers, self.current = {}, None
        await ctx.head(eyes="listening", pan_mode="still")
        await ctx.say((DIAL_QUESTIONS_BUTTON if _button(ctx) else DIAL_QUESTIONS)[self.items[0]])

    async def _answer(self, ctx: RitualContext, item: str, value: int) -> Status | None:
        self.answers[item] = _clamp_1_5(value)
        self.current = None
        await ctx.emit("obs.self_report", {"item": item, "value": self.answers[item], "context": "ritual"})
        await _chime(ctx, "ok")
        nxt = self.item
        if nxt is None:
            return "completed"
        await ctx.say((DIAL_QUESTIONS_BUTTON if _button(ctx) else DIAL_QUESTIONS)[nxt])
        return None

    async def handle(self, event: Event, ctx: RitualContext) -> Status | None:
        item = self.item
        if item is None:
            return "completed"
        if event.kind == "ear":
            self.current = _clamp_1_5(event.data.get("value", 3))
            if event.data.get("pressed"):
                return await self._answer(ctx, item, self.current)
        elif event.kind == "utterance" and not event.data.get("live"):
            m = NUMBER_1_5.search(event.data.get("text", ""))
            if m:
                return await self._answer(ctx, item, int(m.group(1)))
        elif event.kind == "tool" and event.data.get("name") == "record_dial":
            args = event.data.get("args", {})
            target = args.get("item", item)
            if target in self.items and target not in self.answers and "value" in args:
                return await self._answer(ctx, target, int(args["value"]))
        return None

    def on_timeout(self) -> Status:
        return "completed" if (self.answers or self.current is not None) else "skipped"

    async def exit(self, ctx: RitualContext, status: Status) -> None:
        if status == "aborted":
            return
        item = self.item
        if item is not None and self.current is not None:  # turned but never pressed
            await self._answer(ctx, item, self.current)
        if not self.answers:
            return
        outcome = ctx.state.record_dial(_today(), mood=self.answers.get("mood"), energy=self.answers.get("energy"),
                                        sleep=self.answers.get("sleep"))
        if outcome:
            await ctx.emit("obs.nudge_outcome", outcome)
        await ctx.say("Thank you for telling me.")


def _measures(r: HrvResult | None) -> dict[str, float]:
    if r is None or not r.ok:
        return {}
    return {k: v for k, v in (("rmssd_ms", r.rmssd_ms), ("hr_bpm", r.hr_bpm)) if v is not None}


def _delta(pre: dict[str, float], post: dict[str, float]) -> dict[str, float]:
    return {k: round(post[k] - pre[k], 2) for k in pre if k in post}


def closing_line(delta: dict[str, float]) -> str:
    """Only say the heart settled when the numbers say so (HR down >= 2 bpm or RMSSD up >= 3 ms)."""
    if delta.get("hr_bpm", 0) <= -2 or delta.get("rmssd_ms", 0) >= 3:
        return "Lovely. Your heart settled nicely."
    return "Thank you for breathing with me."


class Breathe(Step):
    """30 s PPG -> HRV pre; paced breathing with chest glow; 30 s PPG -> HRV post.
    Emits obs.hrv_session and obs.intervention_response{activity: breathe}."""

    name = "breathe"

    def __init__(self, timeout_s: float | None = None, bpm: float = 6.0, window_s: float = 30.0):
        super().__init__(timeout_s)
        self.bpm = bpm
        self.window_s = window_s
        self.buf = PpgBuffer()

    async def enter(self, ctx: RitualContext) -> None:
        self.buf = PpgBuffer()
        await ctx.head(chest="breathe", bpm=self.bpm, eyes="soft")
        await ctx.sensors(ppg="start")
        await ctx.say("Rest your finger on my chest and breathe with my light. In as it brightens, out as it fades.")

    async def handle(self, event: Event, ctx: RitualContext) -> Status | None:
        if event.kind == "ppg":
            self.buf.add(event.data["fs_hz"], event.data["samples"],
                         t0_ms=event.data.get("t0_ms"), quality=event.data.get("quality"))
        return None

    async def exit(self, ctx: RitualContext, status: Status) -> None:
        await ctx.sensors(ppg="stop")
        await ctx.head(chest="glow")
        if status != "completed":
            return
        s = ctx.settings
        payload, quality, pre, post = self.buf.session(self.bpm, time.monotonic() - self.t0, s.ppg_band_hz,
                                                       s.ppg_min_clean_ratio, window_s=self.window_s,
                                                       quality_min=getattr(s, "quality_min", 0.5))
        if not payload:
            # Not measured: nothing is emitted and nothing is guessed. The reason is kept locally (session store).
            note = getattr(ctx, "note", None)
            if note is not None:
                note("pulse_not_measured", reason=self.buf.reason, seconds=round(self.buf.seconds, 1),
                     method=self.buf.method, restarts=self.buf.restarts)
            await ctx.say("Thank you for breathing with me.")
            return
        await ctx.emit("obs.hrv_session", payload, quality=quality)
        pre_m, post_m = _measures(pre), _measures(post)
        d: dict[str, float] = {}
        if pre_m and post_m:
            d = _delta(pre_m, post_m)
            await ctx.emit("obs.intervention_response",
                           {"activity": "breathe", "pre": pre_m, "post": post_m, "delta": d}, quality=quality)
        await ctx.say(closing_line(d))


class Drum(Step):
    """Two phases. 1) drumming: taps -> music + sway; ends after idle_end_s without taps (or timeout_s);
    emits obs.drum_session at that moment. 2) post-activity mood: "how do you feel now?" -> one ear press ->
    obs.self_report{context: post_activity} + obs.intervention_response{activity: drum, pre/post mood}."""

    name = "drum"

    def __init__(self, timeout_s: float | None = None, idle_end_s: float = 6.0, refractory_ms: float = 80,
                 force_max_g: float = 4.0, min_taps: int = 4, post_s: float = 15.0, sway: bool = True):
        super().__init__(timeout_s)
        self.sway = sway  # off when the drum is a knock switch: motor vibration would trigger it
        self.idle_end_s = idle_end_s
        self.refractory_ms = refractory_ms
        self.force_max_g = force_max_g
        self.min_taps = min_taps
        self.post_s = post_s
        self._reset()

    def _reset(self) -> None:
        self.taps = TapAnalyzer(self.refractory_ms, self.force_max_g)
        self._last_tap = 0.0
        self._last_sway = 0.0
        self.phase = "drum"
        self._post_t0 = 0.0
        self.pre_mood: int | None = None
        self.post_mood: int | None = None
        self.drum_emitted = False

    def deadline(self) -> float:
        if self.phase == "post":
            return self._post_t0 + self.post_s
        d = self.t0 + self.timeout_s
        if self.taps.count >= self.min_taps:
            d = min(d, self._last_tap + self.idle_end_s)
        return d

    async def enter(self, ctx: RitualContext) -> None:
        self._reset()
        self.pre_mood = ctx.state.today_mood(_today())
        await ctx.head(eyes="happy")
        await ctx.music.start(self.pre_mood)
        await _chime(ctx, "start_drum")
        await ctx.say("Now drum on my head. Any rhythm you like. I'll follow you.")

    async def _emit_drum(self, ctx: RitualContext) -> None:
        if self.drum_emitted or self.taps.count < self.min_taps:
            return
        self.drum_emitted = True
        duration = (self.taps.times[-1] - self.taps.times[0]) / 1000 if self.taps.count > 1 else 0.0
        payload = {k: v for k, v in self.taps.summary(duration).items() if v is not None or k == "force_mean"}
        await ctx.emit("obs.drum_session", payload, quality=self.taps.quality())

    async def _stop_music(self, ctx: RitualContext) -> None:
        await ctx.music.stop()
        await ctx.head(pan_mode="still")

    async def on_deadline(self, ctx: RitualContext) -> Status | None:
        if self.phase == "post":
            return "completed"
        if self.taps.count < self.min_taps:
            return "skipped"
        await self._stop_music(ctx)
        await _chime(ctx, "end_drum")
        await self._emit_drum(ctx)
        self.phase, self._post_t0 = "post", time.monotonic()
        await ctx.head(eyes="listening")
        await ctx.say(POST_MOOD_LINE["button" if _button(ctx) else "ear"])
        return None

    async def handle(self, event: Event, ctx: RitualContext) -> Status | None:
        if self.phase == "post":
            if event.kind == "ear":
                self.post_mood = _clamp_1_5(event.data.get("value", 3))
                return "completed" if event.data.get("pressed") else None
            if event.kind == "utterance" and not event.data.get("live"):
                m = NUMBER_1_5.search(event.data.get("text", ""))
                if m:
                    self.post_mood = int(m.group(1))
                    return "completed"
            if (event.kind == "tool" and event.data.get("name") == "record_dial"
                    and event.data.get("args", {}).get("item", "mood") == "mood"
                    and "value" in event.data.get("args", {})):
                self.post_mood = _clamp_1_5(event.data["args"]["value"])
                return "completed"
            return None
        if event.kind != "tap":
            return None
        force = event.data.get("force")
        if not self.taps.add(int(event.data["t_ms"]), None if force is None else float(force)):
            return None
        self._last_tap = time.monotonic()
        await ctx.music.click(KNOCK_CLICK if force is None else min(1.0, force / self.force_max_g))
        if self.taps.count >= self.min_taps and self._last_tap - self._last_sway > 1.0:
            self._last_sway = self._last_tap
            bpm = self.taps.tempo_bpm()
            if bpm > 0:
                fm = self.taps.force_mean()
                await ctx.music.set_tempo(bpm, KNOCK_CLICK if fm is None else fm)
                if self.sway:
                    await ctx.head(pan_mode="sway", bpm=round(min(300.0, bpm), 1))
        return None

    def on_timeout(self) -> Status:
        return "completed" if self.taps.count >= self.min_taps else "skipped"

    async def exit(self, ctx: RitualContext, status: Status) -> None:
        await self._stop_music(ctx)
        if status != "completed":
            return
        await self._emit_drum(ctx)
        if self.post_mood is None:
            return
        await ctx.emit("obs.self_report", {"item": "mood", "value": self.post_mood, "context": "post_activity"})
        pre = {"mood": self.pre_mood} if self.pre_mood is not None else {}
        post = {"mood": self.post_mood}
        await ctx.emit("obs.intervention_response",
                       {"activity": "drum", "pre": pre, "post": post, "delta": _delta(pre, post)})


class Phq9(Step):
    """Spoken PHQ-9 (only when due and [ritual] phq9_mode is spoken|both). Answers 0-3 by voice/text, or
    by ear press (dial 1->0, 2->1, 3->2, 4-5->3). Emits obs.phq9{mode: spoken} only when all 9 are answered.
    Item 9 > 0: the hub's emit() runs the deterministic crisis path; this step also stops the ritual."""

    name = "phq9"

    def __init__(self, timeout_s: float | None = None):
        super().__init__(timeout_s)
        self.answers: list[int] = []

    def applies(self, ctx: RitualContext) -> bool:
        s = ctx.settings
        return s.phq9_mode in ("spoken", "both") and ctx.state.phq9_is_due(_today(), s.phq9_every_days)

    async def enter(self, ctx: RitualContext) -> None:
        self.answers = []
        await ctx.head(eyes="listening", pan_mode="still")
        await ctx.say(PHQ9_INTRO)
        await ctx.say(PHQ9_ITEMS[0] + "?")

    @staticmethod
    def parse(event: Event) -> int | None:
        if event.kind == "ear" and event.data.get("pressed"):
            return min(3, _clamp_1_5(event.data.get("value", 1)) - 1)
        if event.kind == "utterance":
            text = event.data.get("text", "")
            for pat, v in PHQ9_WORDS:
                if pat.search(text):
                    return v
            m = NUMBER_0_3.search(text)
            if m:
                return int(m.group(1))
        return None

    async def handle(self, event: Event, ctx: RitualContext) -> Status | None:
        v = self.parse(event)
        if v is None:
            return None
        self.answers.append(v)
        if len(self.answers) < len(PHQ9_ITEMS):
            await ctx.say(PHQ9_ITEMS[len(self.answers)] + "?")
            return None
        items = self.answers
        positive = items[8] > 0
        if positive:
            self.stop_ritual = True  # safety path takes over (hub.emit sees item9_positive)
        await ctx.emit("obs.phq9", {"total": sum(items), "items": items, "item9_positive": positive,
                                    "mode": "spoken"})
        ctx.state.phq9_done(_today())
        return "completed"

    def on_timeout(self) -> Status:
        return "skipped"  # never emit a partial PHQ-9


class Nudge(Step):
    name = "nudge"

    def __init__(self, timeout_s: float | None = None):
        super().__init__(timeout_s)
        self.arm: str | None = None
        self.accepted: bool | None = None

    async def enter(self, ctx: RitualContext) -> None:
        self.accepted = None
        self.arm, reason = await ctx.get_nudge()
        await ctx.emit("obs.nudge_offered", {"arm": self.arm, "reason": reason[:280]})
        await ctx.head(eyes="thinking")
        await ctx.say(NUDGE_LINES.get(self.arm, "Shall we try one small thing today?"))

    async def handle(self, event: Event, ctx: RitualContext) -> Status | None:
        text = event.data.get("text", "") if event.kind == "utterance" else ""
        if event.kind == "ear" and event.data.get("pressed"):
            self.accepted = True
        elif NO.search(text):
            self.accepted = False
        elif YES.search(text):
            self.accepted = True
        return "completed" if self.accepted is not None else None

    async def exit(self, ctx: RitualContext, status: Status) -> None:
        if self.arm is None or status == "aborted":
            return
        today = _today()
        ctx.state.set_pending_nudge(self.arm, bool(self.accepted), ctx.state.today_mood(today),
                                    ctx.state.today_energy(today), today)
        if self.accepted:
            await ctx.say("Wonderful. I'll ask you tomorrow how it went.")


class Close(Step):
    name = "close"
    timeout_s = 0.0

    async def enter(self, ctx: RitualContext) -> None:
        await ctx.head(eyes="happy", chest="glow", purr={"ms": 600})
        await ctx.say("See you tomorrow. Kiitos!")


def default_steps(settings: Any) -> list[Step]:
    s = settings
    return [
        Greet(s.greet_s),
        Dial(s.dial_s),
        Breathe(s.breathe_s, bpm=s.breathe_bpm, window_s=s.hrv_window_s),
        Drum(s.drum_s, idle_end_s=s.drum_idle_end_s, refractory_ms=s.tap_refractory_ms, force_max_g=s.tap_force_max_g,
             post_s=s.post_mood_s, sway=getattr(s, "drum_sway", True)),
        Phq9(s.step_timeout_s),
        Nudge(s.nudge_s),
        Close(),
    ]
