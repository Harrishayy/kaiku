"""One person's first sixteen days at home with Kaiku, authored day by day (all envelopes `sim: true`).

Aino, 58, a retired teacher, comes home after a course of TMS. The record always ends YESTERDAY (timestamps are
relative to the day you run it), so today is empty and waiting for live recordings from her iPhone, Mac or robot.

    days 1-8    her usual settles: robot ritual ~07:20, an afternoon lake walk, evening video call with her sister
    day 9       the first late night on the Mac; no call that evening
    days 10-12  short nights, later mornings, low dials, flat drumming, hardly out, slower reaction game
    day 12      the daily signals alone are enough: the consensus flags "needs a call" (no questionnaire yet)
    day 13      the care team rings the next morning; the PHQ-9 that evening confirms what the signals showed
    day 14      a morning walk with a friend, the sister calls again; still below her usual
    days 15-16  dials and walks back near her usual; resting pulse and reaction game recover last

Every value is derived from one table (`DAYS`), so the sources agree with each other on the same day: a short night
gives a later first visit to the robot, a lower sleep dial and a slower game. Roughly one cell in ten is missing
(watch left on the charger, no Mac that day, no game, drum skipped), as in a real record.

Today's path games are in it as the apps send them: the lantern every evening but one (24 lights, the summary
computed from the trial record), then the game whose turn it is by the calendar (seed shelf, pebble path, watering:
`ROTATION`), each with `session_index`, the first three sessions of a game marked `warmup`, trials, validity and the
envelope quality the app derives from them. The lantern's first rounds that count (days 4-8) come before the short
nights, so it has a usual to be compared with; it reads slower on days 10-13 and is back by day 15. These games add
measures to Trends and to the person's History; in this record they never carry a verdict
(`test_the_new_games_are_charted_and_decide_nothing`).

She has "Camera during activities" switched on, so every game and every check-in on the phone also has what the
camera counted of her face (`obs.face_signs`, the phone's own face tracking; numbers only, D52): `QUIET` says how
far below her usual her face moved each day. It is quieter on days 10-13 (fewer smiles, a narrower range of
expression, more blinking), half-way back on day 14 and at her usual again on days 15-16. One session has too
little of her face in view to count, and in one her face was never in view, so there is no face record for that
game at all, as the apps do (`FACE_GAPS`); both happen with a phone lying on a table.
These measures are shown and cited; the rule cannot see them, so no state and no verdict moves on any day
(`test_face_signs_are_in_the_story_and_decide_nothing`).

What the consensus makes of it is NOT written here: the real rule (config/criteria.toml) decides, and
cloud/tests/test_single_person.py pins the day-by-day states it reaches.

    uv run python -m kaiku_cloud.jobs.single_person --url http://127.0.0.1:8000        # seed a local API
    uv run python -m kaiku_cloud.jobs.single_person --url http://127.0.0.1:8000 --reset  # drop simulated data first
    uv run python -m kaiku_cloud.jobs.single_person --out /private/tmp/kaiku-aino      # export only (JSONL + views)

Seeding goes through the real routes (events, companion tool/episode, sharing, care action, nightly mind, weekly
brief). It refuses anything but an explicit local API in credential-free mode and never touches another home.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import random
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from statistics import NormalDist
from typing import Any
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

import httpx
from kaiku_contracts import registry, validate
from kaiku_contracts.api import CareSharing, EpisodeIn, ThreadIn, TranscriptTurn

from .. import service, week
from ..mind import memory
from ..mind import nightly as mind_nightly
from ..mind.session import record_episode
from ..settings import TZ, Settings
from ..store.db import Store

HOME = "aino"
N_DAYS = 16
CARE_DAY = 13  # the day after the flag on day 12
CARE_BY = "Riitta Salo"
WARMUP_SESSIONS = 3  # as the apps count them (GameHistory.warmupSessions)
ROTATION = ("seeds", "pebbles", "watering")  # today's second game by day of the year (apps: GameRotation.cycle)
# Camera during activities (D52). How far below her usual her face moved, per day: 0 = her usual, 1 = the quietest.
QUIET = (0, 0, 0, 0, 0, 0, 0, 0, 0, .8, 1.0, .9, .8, .5, .15, .05)
# (day index, task) -> share of frames with her face in view, where the phone was not looking at her properly
FACE_GAPS = {(3, "firefly"): 0.0, (5, "pebbles"): 0.41}
FACE_FPS = 30  # looks a second with the phone's face tracking (arkit_blendshapes); the landmark method takes 15
CARE_NOTE = ("Rang Aino after four short nights and very little time outside. Agreed: a morning walk with her "
             "friend, the evening call with her sister, keep the drum ritual. PHQ-9 repeated; review in a week.")

# What Kaiku's notebook holds (person-facing only; written through the same rules as a live conversation).
NOTES = (
    ("name", "Aino"),
    ("people", "Sister Maija rings most evenings"),
    ("people", "Friend Leena lives two streets away"),
    ("people", "Grandson Eetu visits on Sundays"),
    ("places", "The lake loop past the old sauna"),
    ("places", "The market hall on Saturdays"),
    ("likes", "Cardamom buns with coffee"),
    ("likes", "Sibelius on the radio"),
    ("likes", "Knitting wool socks for Eetu"),
    ("what_helps", "A morning walk with Leena"),
    ("what_helps", "Calling Maija in the evening"),
    ("what_helps", "Drumming with Kaiku before breakfast"),
    ("preference", "A quiet start to the morning"),
    ("plans", "The long lake loop with Leena on Saturday"),
)

# The same sixteen days of numbers under another home id (`--home`), for a team member who then records on real
# devices: today's real takes land on a record that already has a usual to be compared with. Only what is true of
# that person is written into the notebook; Aino's conversations, people and places are not copied over, and the
# care note names nobody. Every seeded envelope stays `sim: true`.
OTHER_NOTES: dict[str, tuple[tuple[str, str], ...]] = {
    "harrish": (
        ("name", "Harrish"),
        ("plans", "Eating more protein this week"),   # the two things the glasses walk in the video turns on:
        ("likes", "Chips, the easy snack to grab"),   # what he reaches for, and what he said he wants instead
    ),
}
OTHER_CARE_NOTE = ("Rang after four short nights and very little time outside. Agreed: a morning walk, an evening "
                   "call, keep the drum ritual. PHQ-9 repeated; review in a week.")


def notes_for(home_id: str) -> tuple[tuple[str, str], ...]:
    if home_id == HOME:
        return NOTES
    if home_id not in OTHER_NOTES:
        raise ValueError(f"no notebook is written for {home_id!r}: add it to OTHER_NOTES (only what is true of them)")
    return OTHER_NOTES[home_id]


def care_note_for(home_id: str) -> str:
    return CARE_NOTE if home_id == HOME else OTHER_CARE_NOTE


def _hm(text: str) -> int:
    """'23:10' -> minutes after midnight; a bedtime before midnight is written as the evening before ('-23:10')."""
    neg = text.startswith("-")
    h, m = text.lstrip("-").split(":")
    return int(h) * 60 + int(m) - (1440 if neg else 0)


@dataclass(frozen=True)
class Day:
    """One authored day. `None` = that capture is missing that day."""

    note: str
    bed: str                                  # fell asleep ('-23:10' = the evening before)
    wake: str
    dial: tuple[int, int, int]                # morning mood, energy, last night's sleep (1-5)
    ritual: str | None = "full"               # full | no_drum | None (did not come to the robot)
    drum: tuple[float, float, float] | None = None      # tempo bpm, seconds, regularity
    speech: tuple[float, float] | None = None           # syllables/s, pause ratio
    walk: tuple[str, float, int] | None = None          # start, minutes, steps per minute
    errand: tuple[str, float] | None = None             # a second short outing
    evening: tuple[int, int] | None = None              # phone weather check: mood, energy
    mac: str | None = "usual"                 # usual | late | easing | None (Mac not opened)
    call: bool = True                         # evening video call with her sister on the Mac
    late: int = 0                             # Mac minutes after midnight (the night that began this day)
    firefly: tuple[float, float, int, int] | None = None  # median ms, IQR ms, lapses, false taps
    pebbles: tuple[int, float] | None = None  # span, accuracy
    lantern: tuple[int, int, int, int] | None = None  # median ms, spread ms, lights missed, early taps
    tell: tuple[float, float, float] | None = None       # syllables/s, pause ratio, pitch variability
    watch: tuple[float, float, int, int] | None = None   # resting HR, HRV SDNN, steps, exercise minutes
    efficiency: float = 0.92                  # asleep / in bed
    phq9: tuple[int, ...] | None = None
    nudge: str | None = None                  # arm offered that day
    accepted: bool = True
    lift: tuple[int, int] | None = None       # mood, energy change after the suggested activity
    talk: str | None = None                   # key into TALKS


DAYS: tuple[Day, ...] = (
    Day("Home routine starts: ritual, lake walk, call with Maija.", "-23:05", "06:50", (4, 3, 4),
        drum=(102, 46, .81), speech=(4.2, .20), walk=("14:40", 34, 104), firefly=(392, 78, 2, 1),
        pebbles=(5, .80), watch=(61, 43, 7400, 33), nudge="daylight_walk", lift=(1, 1),
        lantern=(332, 44, 1, 1)),
    Day("Usual day; first PHQ-9 at home.", "-23:15", "06:55", (4, 4, 4), drum=(106, 50, .84), speech=(4.3, .19),
        walk=("15:05", 38, 106), firefly=(386, 72, 2, 0), pebbles=(5, .83),
        watch=(60, 45, 6900, 30), phq9=(1, 1, 1, 1, 0, 0, 1, 0, 0), nudge="breathe", lift=(0, 0),
        lantern=(324, 42, 0, 1)),
    Day("Whole lake loop and the library; tells Kaiku about it.", "-22:55", "06:40", (4, 4, 5),
        drum=(104, 52, .83), speech=(4.1, .21), walk=("14:30", 41, 105), errand=("11:05", 14),
        evening=(4, 4), firefly=(379, 70, 1, 1), pebbles=(6, .86), tell=(4.1, .21, 2.8),
        watch=(62, 41, 7800, 38), nudge="daylight_walk", lift=(1, 0), talk="loop",
        lantern=(319, 40, 1, 0)),
    Day("Grey, wet day: shorter walk, quieter drumming.", "-23:20", "07:05", (3, 3, 4), drum=(98, 41, .78),
        speech=(4.0, .22), walk=("15:20", 26, 100), firefly=(384, 74, 2, 0), watch=(61, 44, 5900, 22),
        nudge="drum", lift=(1, 0),
        lantern=(316, 38, 0, 0)),
    Day("Usual day.", "-23:10", "06:50", (4, 4, 4), drum=(105, 49, .82),
        speech=(4.2, .20), walk=("14:50", 36, 105),
        firefly=(372, 66, 1, 0), pebbles=(5, .83), watch=(60, 42, 7300, 34), nudge="daylight_walk", lift=(1, 1),
        lantern=(312, 37, 0, 1)),
    Day("Market hall with Leena, the best day so far.", "-22:50", "06:45", (5, 4, 4), drum=(109, 55, .86),
        speech=(4.4, .18), walk=("11:10", 44, 103), evening=(5, 4), firefly=(368, 64, 1, 0),
        pebbles=(6, .88), watch=(61, 46, 8600, 41), nudge="breathe", lift=(0, 0),
        lantern=(310, 36, 0, 0)),
    Day("Out most of the day with Eetu; Mac stays shut.", "-23:25", "07:00", (4, 4, 3), drum=(103, 47, .80),
        speech=(4.1, .21), walk=("14:45", 35, 104), errand=("10:40", 12), mac=None, call=False, firefly=(374, 69, 1, 1), pebbles=(5, .80),
        tell=(4.2, .20, 2.9), watch=(62, 40, 7100, 31), nudge="daylight_walk", lift=(0, 1),
        lantern=(315, 38, 1, 0)),
    Day("Usual day; stays on the Mac after the call.", "-23:10", "06:55", (4, 4, 4), drum=(105, 50, .83),
        speech=(4.3, .19), walk=("15:00", 37, 105), late=42,
        watch=(61, 43, 7500, 35), nudge="drum", lift=(0, 0),
        lantern=(313, 37, 0, 0)),
    Day("First late night; up at the usual time, no call with Maija.", "00:45", "07:15", (4, 4, 3),
        drum=(101, 45, .80), speech=(4.1, .21), walk=("16:10", 33, 101), mac="late",
        call=False, late=71, firefly=(389, 80, 2, 1), watch=(62, 41, 6600, 26), efficiency=.90,
        nudge="daylight_walk", lift=(0, 0), talk="late",
        lantern=(321, 40, 0, 1)),
    Day("Short night, late morning, did not go out.", "01:20", "08:15", (2, 2, 2), drum=(87, 27, .65),
        speech=(3.5, .31), evening=(2, 1), mac="late", call=False, late=88, firefly=(431, 104, 5, 2),
        pebbles=(4, .67), watch=(65, 34, 2400, 5), efficiency=.86, nudge="daylight_walk", accepted=False,
        lantern=(358, 58, 2, 1)),
    Day("Stayed in bed, skipped the robot; a phone check-in at lunch. Watch left on the charger.", "01:55", "08:50",
        (2, 2, 1), ritual=None, walk=("15:40", 9, 90), mac="late", call=False, late=96,
        firefly=(447, 118, 6, 2), pebbles=(4, .60), nudge="breathe", accepted=False),
    Day("Third short night; hardly out. No questionnaire, no call yet: the daily signals speak for themselves.",
        "01:35", "08:25", (2, 2, 2), ritual="no_drum",
        speech=(3.4, .33), walk=("16:20", 11, 91), mac="late", call=False, late=9,
        watch=(67, 29, 2700, 6), efficiency=.86, nudge="drum", accepted=False,
        lantern=(366, 62, 2, 2)),
    Day("The care team rings in the morning, the day after the flag; PHQ-9 in the evening.", "01:05", "08:10",
        (2, 2, 2), ritual="no_drum", speech=(3.5, .32), walk=("16:00", 13, 92), mac="late", call=False, late=14,
        firefly=(440, 112, 5, 2), watch=(66, 30, 3100, 8), efficiency=.86,
        phq9=(2, 2, 2, 2, 1, 1, 1, 0, 0), nudge="breathe", accepted=False, talk="call",
        lantern=(362, 60, 2, 1)),
    Day("Morning walk with Leena; Maija calls again.", "00:25", "07:40", (3, 3, 4), drum=(99, 43, .76),
        speech=(3.95, .24), walk=("09:35", 27, 100), evening=(3, 3), mac="easing",
        firefly=(438, 110, 5, 1), pebbles=(4, .67), watch=(66, 31, 5200, 18), efficiency=.87,
        nudge="daylight_walk", lift=(1, 1), talk="walked",
        lantern=(332, 46, 1, 1)),
    Day("Earlier night; a proper afternoon drum.", "-23:35", "07:10", (4, 4, 4), drum=(101, 45, .79),
        speech=(4.0, .23), walk=("09:30", 36, 104), mac="easing", firefly=(396, 80, 2, 1),
        pebbles=(5, .80), watch=(63, 38, 6700, 29), efficiency=.90, nudge="drum", lift=(1, 0),
        lantern=(321, 40, 0, 0)),
    Day("Close to her usual: lake loop, library, scheduled PHQ-9.", "-23:25", "07:05", (4, 4, 4),
        drum=(103, 48, .81), speech=(4.1, .21), walk=("09:35", 36, 104), errand=("15:30", 12),
        firefly=(388, 76, 2, 0), pebbles=(5, .83), tell=(4.0, .22, 2.7), watch=(63, 39, 7200, 32),
        efficiency=.91, phq9=(1, 1, 2, 2, 1, 0, 1, 0, 0), nudge="daylight_walk", lift=(1, 1), talk="ahead",
        lantern=(315, 38, 0, 1)),
)
assert len(DAYS) == N_DAYS

# Short, warm conversations Aino chose to keep (opt-in transcripts; person-facing only, never on a care route).
TALKS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "loop": ("iphone", "18:40", (
        "Evening, Kaiku. I walked the whole lake loop today.",
        "The whole loop! How was the light out there?",
        "Soft and golden. Leena wants to go to the market hall on Saturday.",
        "That sounds lovely. I will remember the market hall with Leena.",
        "Do. I will bring the buns.",
        "Then it is a plan. Enjoy your evening, Aino.")),
    "late": ("mac", "23:48", (
        "Still up. I cannot seem to switch off tonight.",
        "It is late, Aino. Shall we slow down together for a minute, or would quiet company be better?",
        "Just company. I will watch one more episode.",
        "All right, I am here. Maybe a glass of water on the way to bed.",
        "Maybe.")),
    "call": ("iphone", "19:40", (
        "The clinic rang today. It was good to talk, actually.",
        "I am glad you had that call. How is this evening going?",
        "Slow. I have hardly been out this week.",
        "That happens. Would a small walk tomorrow feel possible?",
        "Leena offered to come by at half past nine. I said yes.",
        "A morning walk with Leena. I will ask you how it went.")),
    "walked": ("iphone", "19:45", (
        "We did the walk. Leena brought buns.",
        "Cardamom buns by the lake! How was it to be out?",
        "Cold, but better than staying in. And Maija called after.",
        "Two good things in one day. Same time tomorrow with Leena?",
        "I think so.")),
    "ahead": ("iphone", "18:50", (
        "I drummed properly this morning. It felt a bit more like me.",
        "I noticed. You kept a lovely steady beat.",
        "Leena and I are doing the long loop on Saturday.",
        "The long loop with Leena on Saturday. I will remember. Coffee after?",
        "Always.")),
}
# Short reflections with Kaiku, by day index: (local time, outcome, her line, Kaiku's reply). She keeps these
# transcripts and shares their summary level (how it sounded, what it was about) with her care team. The labels are
# never written here: the cloud's own labeller reads the words (mind/affect.py), as it would for anyone.
REFLECTIONS: dict[int, tuple[tuple[str, str, str, str], ...]] = {
    0: (("20:10", "completed", "A calm day. I enjoyed the walk by the lake.", "That sounds like a good one."),),
    1: (("20:15", "completed", "An ordinary day, nothing much to tell.", "Ordinary days count too."),),
    4: (("20:05", "completed", "A good day. I felt rested after the walk.", "I am glad to hear it."),),
    6: (("20:20", "completed", "Nothing special today. The usual things.", "The usual things, then."),),
    7: (("20:10", "completed", "A nice day, I was glad to be outside.", "Outside suits you."),),
    9: (("20:30", "completed", "I barely slept and I have no energy. I felt lonely all day.",
         "That is a heavy day. I am here."),),
    10: (("08:20", "completed", "A rough night again. I am exhausted and I didn't want to get up.",
          "Thank you for telling me. No hurry this morning."),
         ("20:40", "ended_early", "Not now, Kaiku. Leave me be.", "Of course. I will be here.")),
    11: (("08:15", "completed", "Another bad night, I couldn't sleep. I can't be bothered with anything and nobody "
                                "is around.", "That sounds hard. One small thing at a time."),),
    12: (("08:25", "completed", "Still bad. I couldn't sleep and I feel empty, alone in the flat.",
          "I hear you. I am staying close today."),),
    14: (("20:10", "completed", "A good day. I enjoyed the walk outside with my friend Leena.",
          "A walk with Leena. That is a good day."),),
    15: (("08:10", "completed", "Nice and calm this morning. My sister Maija called me yesterday.",
          "Maija called. Lovely."),),
}
THREADS = {"call": ("walk_companion", "the morning walk with Leena"),
           "ahead": ("walk_companion", "the long lake loop with Leena on Saturday")}
REASONS = {"daylight_walk": "A short walk while it is light?", "breathe": "A slow breathing round?",
           "drum": "Another few minutes of drumming this afternoon?"}
ACTIVITY = {"daylight_walk": "walk", "breathe": "breathe", "drum": "drum"}
QUALITY = {"hub": .9, "phone": .95, "laptop": .97}


def _has(obs: str, field: str | None = None) -> bool:
    """Contracts grow while this record stays valid: only use an obs type / optional field that exists."""
    model = registry.REGISTRY.get(obs)
    return model is not None and (field is None or field in model.model_fields)


class _Builder:
    def __init__(self, end: date, home_id: str):
        self.end, self.home, self.rows = end, home_id, []
        self.first = end - timedelta(days=N_DAYS - 1)

    def jitter(self, key: str, spread: float) -> float:
        """Deterministic small irregularity (same record on every run)."""
        return random.Random(f"{self.home}:{key}").uniform(-spread, spread)

    def emit(self, i: int, minute: float, kind: str, payload: dict[str, Any], source: str, suffix: str = "",
             quality: float | None = None, day: date | None = None) -> dict[str, Any] | None:
        if not _has(kind):
            return None
        day = day or self.first + timedelta(days=i)
        minute = max(0.0, min(1439.0, minute))
        stamp = datetime.combine(day, time(int(minute // 60), int(minute % 60), int(minute * 60 % 60)), TZ)
        q = quality if quality is not None else QUALITY[source] + self.jitter(f"{i}:{kind}:{suffix}:q", .03)
        env = validate({"id": str(uuid5(NAMESPACE_URL, f"kaiku-record:{self.home}:{self.end}:{i}:{kind}:{suffix}")),
                        "ts": stamp.astimezone(UTC), "home_id": self.home, "source": source, "type": kind,
                        "payload": payload, "sim": True, "quality": round(min(1.0, q), 2)})
        row = env.model_dump(mode="json", exclude_none=True)
        self.rows.append(row)
        return row


def _mac_blocks(d: Day, b: _Builder, i: int, late_before: int) -> list[tuple[float, dict[str, int], int, float]]:
    """Hourly Mac summaries for one day: (minute stamped, category minutes, late-night minutes, switches/h)."""
    blocks: list[tuple[float, dict[str, int], int, float]] = []
    left = late_before  # minutes after midnight carried over from the evening before
    for hour in (1, 2):
        part = min(left, 52 if hour == 1 else 60)
        if part > 0:
            blocks.append((hour * 60, {"video": round(part * .6), "social": round(part * .25),
                                       "news": part - round(part * .6) - round(part * .25)}, part, 24))
            left -= part
    if d.mac is None:
        return blocks
    if d.mac == "late":
        day = [(11, {"news": 10, "other": 4}), (14, {"communication": 5, "news": 7}),
               (17, {"video": 18, "other": 4}), (22, {"video": 22, "social": 6})]
    else:
        scale = .85 if d.mac == "easing" else 1.0
        talk = {"communication": 30, "other": 6} if d.call else {"communication": 6, "social": 10}
        day = [(9, {"news": 14, "communication": 8}), (10, {"work": 26, "communication": 8, "other": 4}),
               (11, {"work": 28, "other": 6}), (14, {"communication": 10, "news": 8, "other": 8}),
               (18, {"social": 8, "other": 10}), (20, talk), (21, {"video": 30, "other": 4}),
               (22, {"video": 14, "social": 6})]
        day = [(h, {k: v * scale for k, v in c.items()}) for h, c in day]
    for hour, cats in day:
        out = {k: max(0, round(v * (1 + b.jitter(f"{i}:mac:{hour}:{k}", .15)))) for k, v in cats.items()}
        blocks.append((hour * 60, out, 0, 12 + b.jitter(f"{i}:mac:{hour}:sw", 3)))
    if d.late:  # the evening runs on towards midnight (the minutes after midnight land on tomorrow)
        blocks.append((23 * 60, {"video": 24, "social": 8}, 0, 20))
        blocks.append((23 * 60 + 59, {"video": 30, "social": 12}, 0, 24))
    return blocks


# ---------------------------------------------------------------------- measured games, as the apps send them
def _spread(n: int, centre: float, spread: float) -> list[float]:
    """n values around a centre with exactly this median: evenly placed points of a normal curve."""
    return [centre + spread * NormalDist().inv_cdf((k + .5) / n) for k in range(n)]


def _emit_game(b: _Builder, i: int, minute: float, payload: dict[str, Any]) -> None:
    """Envelope quality as the apps set it (GameHistory.quality): the share of usable trials, never below 0.6."""
    quality = round(max(.6, min(1.0, payload["valid_n"] / payload["trials_n"])), 2)
    row = b.emit(i, minute, "obs.play_session", payload, "phone", payload["game"], quality=quality)
    _face(b, i, minute, payload["game"], payload["duration_s"], row)


def health_extras(steps: int, resting_hr: float, in_bed: float, asleep: float, outdoors: float, wobble: Any
                  ) -> dict[str, Any]:
    """More of the day from Apple Health, as the phone sends it beside the daily summary (D53): distance walked,
    time in daylight, walking heart rate, the night's sleep stages and the time awake in it. All of it follows what
    the day already holds: the steps, the minutes outside, how much of the time in bed was sleep. A poor night
    (less of the time in bed asleep) has less deep and REM sleep and more time awake; a day indoors has little
    daylight. `in_bed`: minutes from first falling asleep to the last waking. `wobble(key, spread)`: the small
    day-to-day irregularity. There is no sleep score: Apple gives apps none, and none is made up here."""
    efficiency = asleep / in_bed if in_bed else 0.0
    deep = max(0.09, min(0.19, 0.17 - (0.92 - efficiency) + wobble("deep", 0.008))) * asleep
    rem = max(0.14, min(0.26, 0.22 - (0.92 - efficiency) * 0.5 + wobble("rem", 0.010))) * asleep
    return {"distance_km": round(max(0.0, steps * (0.00066 + wobble("stride", 0.00002))), 2),
            "daylight_min": float(round(max(0.0, outdoors + 12 * (steps / 7000) + wobble("light", 4)))),
            "walking_hr_bpm": round(resting_hr + 37 + wobble("walking_hr", 1.5), 1),
            "sleep_deep_min": float(round(deep)), "sleep_rem_min": float(round(rem)),
            "sleep_core_min": float(round(asleep) - round(deep) - round(rem)),
            "sleep_awake_min": float(max(0, round(in_bed - asleep + wobble("awake", 4))))}


def face_payload(task: str, seconds: float, quiet: float, coverage: float, wobble: Any, talking: bool = False
                 ) -> dict[str, Any]:
    """One task's face signs as the phone's face tracking counts them (ARKit blendshapes). `quiet`: 0 = her usual,
    1 = her quietest day. A talking face (the check-in) smiles and moves more than a playing one. `wobble(key,
    spread)`: the small session-to-session irregularity. As the apps do: blinks need 20 s of face time, head
    movement 2 s and the range of expression 10 face frames, otherwise that sign is left out."""
    seconds = float(round(seconds))
    samples = round(seconds * FACE_FPS)
    payload: dict[str, Any] = {"task": task, "device": "phone", "method": "arkit_blendshapes",
                               "duration_s": seconds, "samples": samples, "coverage": coverage}
    if coverage <= 0:
        return payload
    face_s, face_frames = coverage * seconds, coverage * samples
    smile = max(0.0, (.21 if talking else .14) - (.16 if talking else .12) * quiet + wobble("smile", .012))
    spread = max(0.0, (.50 if talking else .34) - (.20 if talking else .16) * quiet + wobble("range", .015))
    signs = {
        "smile_share": round(smile, 3), "smiles": round(smile * seconds / 3.5),
        "brow_raise_share": round(max(0.0, (.10 if talking else .05) - .03 * quiet + wobble("raise", .008)), 3),
        "brow_furrow_share": round(max(0.0, .06 + .05 * quiet + wobble("furrow", .008)), 3),
        "mouth_open_share": round(max(0.0, (.36 if talking else .03) - (.08 if talking else 0) * quiet + wobble("mouth", .01)), 3),
        "blinks_per_min": round(max(0.0, (17.0 if talking else 14.0) + 9.0 * quiet + wobble("blink", .8)), 1),
        "gaze_on_share": round(min(1.0, (.84 if talking else .92) - .06 * quiet + wobble("gaze", .015)), 3),
        "head_movement": round(max(0.0, (.32 if talking else .22) - .09 * quiet + wobble("head", .015)), 3),
        "expression_range": round(spread, 3)}
    if face_s < 20:
        del signs["blinks_per_min"]
    if face_s < 2:
        del signs["head_movement"]
    if face_frames < 10:
        del signs["expression_range"]
    return payload | signs


def _face(b: _Builder, i: int, minute: float, task: str, seconds: float, of: dict[str, Any] | None = None) -> None:
    """What the camera counted during one task that day (only when the contract has it). The envelope quality is
    the share of frames with her face in view, as the app sets it."""
    if not _has("obs.face_signs"):
        return
    coverage = FACE_GAPS.get((i, task), round(min(.99, .93 + b.jitter(f"{i}:face:{task}:cov", .04)), 2))
    if coverage <= 0:
        return  # no face in view for the whole task: the apps send no observation at all
    payload = face_payload(task, seconds, QUIET[i], coverage, lambda key, spread: b.jitter(f"{i}:face:{task}:{key}", spread),
                           talking=task == "check_in")
    if of:
        payload["ref"] = of["id"]
    b.emit(i, minute + seconds / 60, "obs.face_signs", payload, "phone", f"face-{task}", quality=coverage)


def _lantern(b: _Builder, i: int, nth: int, ms: int, spread: int, missed: int, early: int) -> dict[str, Any]:
    """Simple reaction time, 24 lights. The summary numbers are computed from the trial record, as the app does
    (LanternGame.session): median, IQR, SD / mean, mean of 1000 / RT; a lapse is 500 ms or slower, or a miss."""
    rng = random.Random(f"{b.home}:{i}:lantern")
    hits = [max(180, round(x)) for x in _spread(24 - missed - early, ms, spread)]
    if spread >= 55:
        hits[-1] += 60  # a short night has its one long blank
    trials = [("l" if x >= 500 else "h", x) for x in hits] + [("m", 0)] * missed + [("a", 0)] * early
    rng.shuffle(trials)
    usual = statistics.quantiles(hits, n=4, method="inclusive")
    return {"game": "lantern", "device": "phone", "duration_s": round(92 + b.jitter(f"{i}:lantern:s", 4), 1),
            "reaction_ms_median": round(float(statistics.median(hits)), 1), "reaction_ms_iqr": round(usual[2] - usual[0], 1),
            "reaction_ms_cv": round(statistics.stdev(hits) / statistics.fmean(hits), 3),
            "response_speed": round(statistics.fmean(1000 / x for x in hits), 3),
            "lapses": sum(1 for code, _x in trials if code in "lm"), "false_starts": early, "trials_n": 24,
            "valid_n": len(hits), "input": "touch", "session_index": nth, "warmup": nth <= WARMUP_SESSIONS,
            "valid": True, "rt_ms": [x for _code, x in trials], "trial_codes": "".join(code for code, _x in trials)}


def _seeds(b: _Builder, i: int, nth: int, slow: float) -> dict[str, Any]:
    """Symbol and digit, 90 seconds: how many were right per minute."""
    rng = random.Random(f"{b.home}:{i}:seeds")
    n = 41 - round(9 * slow) + (nth <= WARMUP_SESSIONS) * (nth - 4)  # the first tries are slower: learning the key
    wrong = 2 + (slow > .5)
    codes = ["x"] * wrong + ["c"] * (n - wrong)
    rng.shuffle(codes)
    rts = [max(900, round(x)) for x in _spread(n, 90_000 / n, 380)]
    rng.shuffle(rts)
    right = [x for x, code in zip(rts, codes, strict=True) if code == "c"]
    usual = statistics.quantiles(right, n=4, method="inclusive")
    return {"game": "seeds", "device": "phone", "duration_s": round(106 + b.jitter(f"{i}:seeds:s", 3), 1),
            "throughput_per_min": round(len(right) / 1.5, 2), "accuracy": round(len(right) / n, 3),
            "reaction_ms_median": round(float(statistics.median(right)), 1), "reaction_ms_iqr": round(usual[2] - usual[0], 1),
            "trials_n": n, "valid_n": len(right), "input": "touch", "session_index": nth,
            "warmup": nth <= WARMUP_SESSIONS, "valid": True, "rt_ms": rts, "trial_codes": "".join(codes)}


def _watering(b: _Builder, i: int, nth: int, slow: float) -> dict[str, Any]:
    """Eight rounds: the bigger plant that takes more taps, or the small easy one."""
    rng = random.Random(f"{b.home}:{i}:watering")
    hard = round(5.6 - 2.6 * slow + b.jitter(f"{i}:watering:h", .45))
    codes = ["H"] * hard + ["E"] * (8 - hard)
    rng.shuffle(codes)
    rts = [max(500, round(x)) for x in _spread(8, 1300 + 250 * slow, 260)]
    rng.shuffle(rts)
    return {"game": "watering", "device": "phone", "duration_s": round(82 + b.jitter(f"{i}:watering:s", 5), 1),
            "hard_choice_ratio": round(hard / 8, 3), "tap_rate_hz": round(5.3 - .9 * slow + b.jitter(f"{i}:watering:t", .15), 2),
            "trials_n": 8, "valid_n": 8, "input": "touch", "session_index": nth, "warmup": nth <= WARMUP_SESSIONS,
            "valid": True, "rt_ms": rts, "trial_codes": "".join(codes)}


def build(end: date, home_id: str = HOME) -> list[dict]:
    """The sixteen days ending on `end` as validated obs envelopes, oldest first. Deterministic."""
    b = _Builder(end, home_id)
    played = {"lantern": 0, "seeds": 0, "watering": 0}  # finished sessions per game so far (1-3 are practice)
    for i, d in enumerate(DAYS):
        bed, wake = _hm(d.bed), _hm(d.wake)
        mood, energy, slept = d.dial
        up = wake + 27 + b.jitter(f"{i}:up", 5)  # at the robot about half an hour after waking

        # ------------------------------------------------------------ check-ins & robot ritual
        if d.ritual:
            b.emit(i, up, "obs.presence", {"distance_cm": round(56 + b.jitter(f"{i}:dist", 8), 1),
                                           "first_of_day": True, "dwell_s": round(24 + b.jitter(f"{i}:dw", 6), 1)}, "hub")
            for k, (item, value) in enumerate((("mood", mood), ("energy", energy), ("sleep", slept))):
                b.emit(i, up + 1.5 + k * .4, "obs.self_report",
                       {"item": item, "value": value, "context": "ritual", "channel": "robot"}, "hub", item)
            # guided breathing with the glowing chest; the robot's pulse reading is not part of this record
            b.emit(i, up + 4, "obs.ritual", {"step": "breathe", "status": "completed", "duration_s": 90.0}, "hub", "breathe")
            if d.drum and d.ritual == "full":
                tempo, seconds, regular = d.drum
                b.emit(i, up + 6, "obs.drum_session", {"tempo_bpm": tempo, "duration_s": seconds, "regularity": regular,
                                                       "taps": round(tempo * seconds / 60)}, "hub")
            else:
                b.emit(i, up + 6, "obs.ritual", {"step": "drum", "status": "skipped"}, "hub", "drum")
            if d.speech:
                b.emit(i, up + 7, "obs.speech_features", {"syllables_per_s": d.speech[0], "pause_ratio": d.speech[1],
                                                          "duration_s": 30.0}, "hub")
            _engagement(b, i, d, up + 8)
            b.emit(i, up + 8.5, "obs.ritual", {"step": "close", "status": "completed",
                                               "duration_s": round((190 if d.drum else 120) + b.jitter(f"{i}:rit", 20))}, "hub")
        else:  # no robot that morning: a weather check on the phone around lunch
            for k, (item, value) in enumerate((("mood", mood), ("energy", energy), ("sleep", slept))):
                b.emit(i, 13 * 60 + 8 + k * .4, "obs.self_report",
                       {"item": item, "value": value, "context": "adhoc", "channel": "phone"}, "phone", item)
            _face(b, i, 13 * 60 + 7, "check_in", 95 + b.jitter(f"{i}:chat:s", 20))
        if d.evening:
            at = 20 * 60 + 35 + b.jitter(f"{i}:eve", 12)
            for k, (item, value) in enumerate((("mood", d.evening[0]), ("energy", d.evening[1]))):
                b.emit(i, at + k * .4, "obs.self_report",
                       {"item": item, "value": value, "context": "adhoc", "channel": "phone"}, "phone", f"eve-{item}")
            _face(b, i, at - 1, "check_in", 110 + b.jitter(f"{i}:chat:s", 25))  # the check-in chat on the phone

        # ------------------------------------------------------------ walks & outings (phone walk companion)
        for name, outing in (("walk", d.walk), ("errand", d.errand)):
            if outing:
                minutes = outing[1]
                pace = outing[2] if name == "walk" else 96
                b.emit(i, _hm(outing[0]) + minutes, "obs.outing",
                       {"minutes": float(minutes), "steps": round(minutes * pace), "method": "steps"}, "phone", name)

        # ------------------------------------------------------------ apps: Mac rhythm, games, PHQ-9
        for minute, cats, late, switches in _mac_blocks(d, b, i, DAYS[i - 1].late if i else 0):
            active = sum(cats.values())
            b.emit(i, minute, "obs.screen_activity", {
                "period_min": 60.0, "active_min": float(active), "late_night_min": float(late),
                "category_min": {k: float(v) for k, v in cats.items()}, "switches_per_hour": round(switches, 1),
                "longest_stretch_min": float(round(active * .6)), "breaks": max(0, round((60 - active) / 15)),
                "paused": False}, "laptop", str(int(minute)))
        play = 18 * 60 + 25 + b.jitter(f"{i}:play", 15) + (150 if d.mac == "late" else 0)
        if d.firefly:
            rt, iqr, lapses, false = d.firefly
            row = b.emit(i, play, "obs.play_session", {"game": "firefly", "device": "phone", "duration_s": 60.0,
                         "reaction_ms_median": float(rt), "reaction_ms_iqr": float(iqr), "lapses": lapses,
                         "false_taps": false}, "phone", "firefly")
            _face(b, i, play, "firefly", 60.0, row)
        if d.pebbles:
            # the first sessions of a game are practice, marked as the app marks them (criteria: warmup = false)
            nth = sum(1 for x in DAYS[:i + 1] if x.pebbles)
            row = b.emit(i, play + 3, "obs.play_session", {"game": "pebbles", "device": "phone", "duration_s": 75.0,
                         "span_max": d.pebbles[0], "accuracy": d.pebbles[1], "session_index": nth,
                         "warmup": nth <= WARMUP_SESSIONS}, "phone", "pebbles")
            _face(b, i, play + 3, "pebbles", 75.0, row)
        if d.lantern:
            # Today's path (apps: GameRotation): the lantern every day, then the game whose turn it is by the
            # calendar. Pebble path keeps its own authored days above; seed shelf and watering come by rotation.
            # She does the path in the evening, just before the games she already played then.
            path = play - 8
            slow = min(1.0, max(0.0, (d.lantern[0] - 316) / 50))  # how far the day's reactions are from her usual
            played["lantern"] += 1
            _emit_game(b, i, path, _lantern(b, i, played["lantern"], *d.lantern))
            turn = ROTATION[(b.first + timedelta(days=i)).timetuple().tm_yday % len(ROTATION)]
            if turn in ("seeds", "watering"):
                played[turn] += 1
                _emit_game(b, i, path + 3, (_seeds if turn == "seeds" else _watering)(b, i, played[turn], slow))
        if d.tell:
            row = b.emit(i, play + 6, "obs.play_session", {"game": "tell", "device": "phone", "duration_s": 45.0,
                         "speech_rate": d.tell[0], "pause_ratio": d.tell[1], "pitch_variability": d.tell[2]},
                         "phone", "tell")
            _face(b, i, play + 6, "tell", 45.0, row)  # stored and listed; no metric reads a talking task
        if d.phq9:
            b.emit(i, 19 * 60 + 5, "obs.phq9", {"items": list(d.phq9), "total": sum(d.phq9),
                                                 "item9_positive": d.phq9[8] > 0, "mode": "laptop"}, "phone")

        # ------------------------------------------------------------ watch (daily summary from Apple Health)
        if d.watch:
            rhr, sdnn, steps, exercise = d.watch
            asleep = float(round((wake - bed) * d.efficiency))
            summary = {"date": str(b.first + timedelta(days=i)), "device": "apple_watch",
                       "sleep_min": asleep, "sleep_midpoint_min": float((bed + wake) // 2),
                       "resting_hr_bpm": float(rhr), "hrv_sdnn_ms": float(sdnn), "steps": steps,
                       "exercise_min": float(exercise)}
            if _has("obs.wearable_daily", "sleep_deep_min"):  # the rest of her day from Apple Health (D53)
                outdoors = (d.walk[1] if d.walk else 0.0) + (d.errand[1] if d.errand else 0.0)
                summary |= health_extras(steps, rhr, wake - bed, asleep, outdoors,
                                         lambda key, spread, i=i: b.jitter(f"{i}:health:{key}", spread))
            b.emit(i, 23 * 60 + 40, "obs.wearable_daily", summary, "phone", quality=.93)

        # ------------------------------------------------------------ suggestion -> what happened -> next morning
        if d.nudge:
            act = ACTIVITY[d.nudge]
            offered = (up + 8.2) if d.ritual else 13 * 60 + 12
            b.emit(i, offered, "obs.nudge_offered", {"arm": d.nudge, "reason": REASONS[d.nudge]},
                   "hub" if d.ritual else "phone")
            if not d.accepted:
                b.emit(i, offered + 1, "obs.nudge_outcome", {"arm": d.nudge, "accepted": False},
                       "hub" if d.ritual else "phone", "declined")
                continue
            done = _hm(d.walk[0]) + d.walk[1] + 2 if act == "walk" and d.walk else 11 * 60 + 20 if act == "breathe" \
                else 16 * 60 + 40
            if act == "breathe":
                b.emit(i, done - 2, "obs.play_session", {"game": "breathe", "device": "phone", "duration_s": 90.0,
                       }, "phone", "breathe")
            elif act == "drum":
                tempo, seconds, regular = d.drum or (96, 30, .74)
                b.emit(i, done - 1, "obs.drum_session", {"tempo_bpm": tempo + 2, "duration_s": round(seconds * .7),
                       "regularity": regular, "taps": round((tempo + 2) * seconds * .7 / 60)}, "hub", "afternoon")
            pre = {"mood": mood, "energy": energy}
            lift = d.lift or (0, 0)
            post = {"mood": min(5, mood + lift[0]), "energy": min(5, energy + lift[1])}
            b.emit(i, done, "obs.intervention_response", {"activity": act, "pre": pre, "post": post,
                   "delta": {k: float(post[k] - pre[k]) for k in pre}}, "hub" if act == "drum" else "phone")
            if i + 1 < N_DAYS:
                nxt = DAYS[i + 1]
                outside = sum(o[1] for o in (nxt.walk, nxt.errand) if o)
                at = _hm(nxt.wake) + 40 if nxt.ritual else 13 * 60 + 10
                b.emit(i + 1, at, "obs.nudge_outcome", {"arm": d.nudge, "accepted": True, "next_day": {
                    "mood": nxt.dial[0], "energy": nxt.dial[1], "activity": float(outside)}},
                    "hub" if nxt.ritual else "phone", "followup")
    return sorted(b.rows, key=lambda e: (e["ts"], e["id"]))


def _engagement(b: _Builder, i: int, d: Day, minute: float) -> None:
    """The robot's own end-of-ritual summary, from the same numbers (only when the contract has it)."""
    if not _has("obs.engagement"):
        return
    cues = [{"cue": "dial", "available": True, "level": round((d.dial[0] + d.dial[1] - 2) / 8, 2), "confidence": 1.0,
             "basis": f"mood {d.dial[0]}, energy {d.dial[1]}"}]
    if d.drum and d.ritual == "full":
        rate = d.drum[0] / 60
        cues.append({"cue": "drum", "available": True, "level": round(min(1.0, rate / 3), 2), "confidence": .9,
                     "basis": f"{rate:.1f} taps/s, {round(d.drum[0] * d.drum[1] / 60)} taps"})
    else:
        cues.append({"cue": "drum", "available": False, "basis": "drum step skipped"})
    if d.speech:
        cues.append({"cue": "voice", "available": True, "level": round(min(1.0, d.speech[0] / 6), 2), "confidence": .7,
                     "basis": f"{d.speech[0]} syllables/s, pauses {round(d.speech[1] * 100)}%"})
    cues.append({"cue": "face", "available": False, "basis": "camera off"})
    cues.append({"cue": "pulse", "available": False, "basis": "not measured"})
    levels = [c["level"] for c in cues if c["available"]]
    b.emit(i, minute, "obs.engagement", {
        "level": round(sum(levels) / len(levels), 2) if len(levels) >= 2 else None,
        "confidence": .7 if len(levels) >= 3 else .5, "cues_available": len(levels),
        "agreement": round(1 - (max(levels) - min(levels)), 2) if len(levels) >= 2 else None, "cues": cues}, "hub")


# ---------------------------------------------------------------------- today (the live comparison)
def today_events(day: date, kind: str, home_id: str = HOME, now: datetime | None = None) -> list[dict]:
    """What a `good` or a `rough` day would post for `day` from the phone, watch and Mac (sim: true). Used by
    scripts/live_day.py and the tests to show that the next recordings move the comparison either way."""
    good = kind == "good"
    if kind not in ("good", "rough"):
        raise ValueError("kind is good or rough")
    dial = (4, 4, 4) if good else (2, 2, 2)
    wake = _hm("06:55" if good else "08:40")
    bed = _hm("-23:10" if good else "01:50")
    rows = []

    def emit(minute: float, kind_: str, payload: dict[str, Any], source: str, suffix: str = "") -> None:
        stamp = datetime.combine(day, time(int(minute // 60), int(minute % 60)), TZ)
        if now is not None and stamp > now:
            stamp = now - timedelta(minutes=max(1, 30 - len(rows)))
        env = validate({"id": str(uuid5(NAMESPACE_URL, f"kaiku-record:{home_id}:today:{day}:{kind}:{kind_}:{suffix}")),
                        "ts": stamp.astimezone(UTC), "home_id": home_id, "source": source, "type": kind_,
                        "payload": payload, "sim": True, "quality": .95})
        rows.append(env.model_dump(mode="json", exclude_none=True))

    if not good:
        emit(60, "obs.screen_activity", {"period_min": 60.0, "active_min": 52.0, "late_night_min": 52.0,
             "category_min": {"video": 32.0, "social": 20.0}, "switches_per_hour": 26.0, "longest_stretch_min": 30.0,
             "breaks": 0, "paused": False}, "laptop", "60")
        emit(120, "obs.screen_activity", {"period_min": 60.0, "active_min": 34.0, "late_night_min": 34.0,
             "category_min": {"video": 24.0, "social": 10.0}, "switches_per_hour": 24.0, "longest_stretch_min": 20.0,
             "breaks": 1, "paused": False}, "laptop", "120")
    asleep = float(round((wake - bed) * (.92 if good else .85)))
    summary = {"date": str(day), "device": "apple_watch", "sleep_min": asleep,
               "sleep_midpoint_min": float((bed + wake) // 2),
               "resting_hr_bpm": 61.0 if good else 67.0, "hrv_sdnn_ms": 43.0 if good else 30.0,
               "steps": 4200 if good else 600, "exercise_min": 30.0 if good else 2.0}
    if _has("obs.wearable_daily", "sleep_deep_min"):  # the day so far and last night, from Apple Health (D53)
        summary |= health_extras(summary["steps"], summary["resting_hr_bpm"], wake - bed, asleep,
                                 36.0 if good else 4.0, lambda _key, _spread: 0.0)
    emit(wake + 20, "obs.wearable_daily", summary, "phone")
    for k, item in enumerate(("mood", "energy", "sleep")):
        emit(wake + 35 + k, "obs.self_report", {"item": item, "value": dial[k], "context": "adhoc",
                                                "channel": "phone"}, "phone", item)
    walk = 36.0 if good else 9.0
    emit(wake + 150, "obs.outing", {"minutes": walk, "steps": round(walk * (104 if good else 90)), "method": "steps"},
         "phone")
    emit(wake + 200, "obs.play_session", {"game": "firefly", "device": "phone", "duration_s": 60.0,
         "reaction_ms_median": 374.0 if good else 452.0, "reaction_ms_iqr": 68.0 if good else 120.0,
         "lapses": 1 if good else 6, "false_taps": 0 if good else 2}, "phone", "firefly")
    if _has("obs.face_signs"):  # the camera's count of that game: her usual face on a good day, a quiet one on a rough day
        emit(wake + 201, "obs.face_signs", face_payload("firefly", 60.0, 0.0 if good else 0.95, 0.95, lambda _k, _s: 0.0)
             | {"ref": rows[-1]["id"]}, "phone", "face-firefly")
    if good:
        emit(wake + 230, "obs.screen_activity", {"period_min": 60.0, "active_min": 58.0, "late_night_min": 0.0,
             "category_min": {"communication": 48.0, "news": 10.0}, "switches_per_hour": 11.0,
             "longest_stretch_min": 24.0, "breaks": 1, "paused": False}, "laptop", "day")
    return rows


# ---------------------------------------------------------------------- private continuity
def episodes(end: date, home_id: str = HOME) -> list[EpisodeIn]:
    """Finished sessions as the devices would upload them. Talk episodes carry the transcript she chose to keep."""
    first = end - timedelta(days=N_DAYS - 1)
    out: list[EpisodeIn] = []

    def add(i: int, kind: str, surface: str, intent: str, start_min: float, minutes: float, tools: list[str],
            **extra: Any) -> None:
        start = datetime.combine(first + timedelta(days=i), time(int(start_min // 60) % 24, int(start_min % 60)), TZ)
        out.append(EpisodeIn(home_id=home_id, surface=surface, intent=intent,  # type: ignore[arg-type]
                             id=str(uuid5(NAMESPACE_URL, f"kaiku-record:{home_id}:{end}:{i}:episode:{kind}")),
                             start=start, end=start + timedelta(minutes=minutes), outcome="completed",
                             tools_used=tools, **extra))

    for i, d in enumerate(DAYS):
        if d.ritual:
            add(i, "ritual", "robot", "ritual", _hm(d.wake) + 27, 6 if d.drum else 4,
                ["record_dial", "start_activity", "end_session"])
        else:
            add(i, "checkin", "iphone", "checkin", 13 * 60 + 7, 2, ["record_dial"])
        if d.evening:
            add(i, "evening", "iphone", "checkin", 20 * 60 + 34, 2, ["record_dial"])
        if d.walk and d.walk[1] >= 20 and i in (1, 4, 7, 13, 15):  # some walks with Kaiku in her ear
            add(i, "walk", "glasses", "walk", _hm(d.walk[0]), d.walk[1], ["start_activity", "log_walk_moment"])
        if home_id != HOME:
            continue  # what Aino said is hers: another person's record gets the sessions, never her words
        if d.talk:
            surface, at, lines = TALKS[d.talk]
            thread = THREADS.get(d.talk)
            add(i, f"talk-{d.talk}", surface, "talk", _hm(at), 4, ["recall", "remember"],
                transcript=[TranscriptTurn(role="person" if k % 2 == 0 else "kaiku", text=text, complete=True)
                            for k, text in enumerate(lines)],
                open_thread=ThreadIn(skill=thread[0], topic=thread[1]) if thread else None)  # type: ignore[arg-type]
        for k, (at, outcome, said, reply) in enumerate(REFLECTIONS.get(i, ())):
            add(i, f"reflection-{k}", "iphone" if _hm(at) > 12 * 60 else "robot", "talk", _hm(at), 2, [],
                transcript=[TranscriptTurn(role="person", text=said, complete=True),
                            TranscriptTurn(role="kaiku", text=reply, complete=True)])
            out[-1].outcome = outcome  # type: ignore[assignment]
    return out


def populate(store: Store, rows: list[dict], end: date, now: datetime | None = None) -> dict:
    """Load the record into a store in-process through the same functions the routes call, then compute the views
    as of the morning after `end`. Safe to repeat."""
    home = rows[0]["home_id"]
    now = now or datetime.combine(end + timedelta(days=1), time(6, 0), TZ)
    fresh, _dupes = store.insert_events(rows)
    for category, text in notes_for(home):
        memory.remember(store, home, category, text, now=now)
    for episode in episodes(end, home):
        record_episode(store, episode)
    week.set_sharing(store, home, CareSharing(share_with_care_team=True))
    if fresh and not any(a["action"] == "acknowledge" and a["note"] == care_note_for(home) for a in store.actions(home)):
        store.log_action(home, "acknowledge", care_note_for(home), CARE_BY, care_ts(end))
    settings = Settings(db_path=":memory:", llm="template")
    mind_nightly.run(store, [home], now=now, gen=_no_model)
    row = service.recompute_home(store, settings, home, today=end + timedelta(days=1))
    return {
        "home_id": home, "days": N_DAYS, "first_day": str(end - timedelta(days=N_DAYS - 1)), "last_day": str(end),
        "story": [d.note for d in DAYS],
        "week": week.week(store, settings, home, "care_team", now=now).model_dump(mode="json"),
        "graph": week.graph(store, settings, home, "care_team", now=now).model_dump(mode="json"),
        "consensus": row["consensus"],
    }


def _no_model(*_args: Any, **_kwargs: Any) -> str:
    from ..llm.errors import LlmUnavailable

    raise LlmUnavailable("the export never calls a model")


# ---------------------------------------------------------------------- seeding a local API
class SeedError(RuntimeError):
    """Something a person can fix; the message says how."""


def _local(url: str) -> None:
    parsed = urlsplit(url)
    clean = not (parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"))
    # Our own deployed demonstration API: only when named explicitly in KAIKU_SEED_REMOTE and with its admin
    # credential, over https. The API must still answer mode "demo" (checked in seed()).
    if (clean and parsed.scheme == "https" and os.environ.get("KAIKU_ADMIN_TOKEN")
            and url.rstrip("/") == os.environ.get("KAIKU_SEED_REMOTE", "").rstrip("/")):
        return
    if (parsed.scheme not in ("http", "https") or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
            or not clean):
        raise ValueError("Choose an explicit local API origin for the authored record")


def care_ts(end: date) -> str:
    """The care team's call on day 13 of the sixteen: the morning after the consensus flagged (UTC, ms, Z)."""
    at = datetime.combine(end - timedelta(days=N_DAYS - CARE_DAY), time(10, 15), TZ).astimezone(UTC)
    return at.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def seed(url: str, rows: list[dict], reset: bool = False, jobs: bool = True, client: Any = None) -> dict[str, Any]:
    """Post the record through the real routes of a local credential-free API. Idempotent: a second run adds
    nothing. A record anchored to an earlier day is refused (use reset=True, which drops THIS person's simulated data on
    that API first; live recordings stay). `client`: an already open httpx-style client (in-process runs)."""
    _local(url)
    home = rows[0]["home_id"]
    ids = {row["id"] for row in rows}
    end = max(datetime.fromisoformat(row["ts"].replace("Z", "+00:00")).astimezone(TZ).date() for row in rows)
    with contextlib.ExitStack() as stack:
        client = client or stack.enter_context(
            httpx.Client(base_url=url, timeout=120, transport=httpx.HTTPTransport(retries=2)))

        admin = os.environ.get("KAIKU_ADMIN_TOKEN")

        def call(method: str, path: str, **kwargs: Any) -> Any:
            if admin and path.startswith("/v1/admin/"):  # a deployed demo keeps its admin routes closed
                kwargs["headers"] = {"Authorization": f"Bearer {admin}"}
            response = client.request(method, path, **kwargs)
            if response.status_code >= 400:
                raise SeedError(f"{method} {path} answered {response.status_code}: {response.text[:200]}")
            return response.json()

        try:
            descriptor = call("GET", "/v1/discovery")
        except httpx.HTTPError as error:
            raise SeedError(f"no Kaiku API at {url} ({type(error).__name__}). Start one with `make demo` "
                            "or `make cloud-local`.") from None
        if descriptor.get("mode") != "demo":
            raise ValueError("Seeding requires an explicitly configured demonstration API")
        if reset:  # this person only: everyone else on that API stays as they were
            call("POST", "/v1/admin/reset", params={"home_id": home})
        else:
            old = [e for e in call("GET", "/v1/events", params={"home_id": home, "limit": 1000})["events"]
                   if e.get("sim") and e["id"] not in ids and ":today:" not in e["id"]]
            stale = [e for e in old if datetime.fromisoformat(e["ts"].replace("Z", "+00:00")).astimezone(TZ).date() <= end]
            if stale:
                raise SeedError(f"{home} already holds {len(stale)} simulated observations from an earlier run, so "
                                "the sixteen days would no longer end yesterday. Run `make demo-reset` (drops "
                                "simulated data on this API, keeps live recordings) and try again.")
        accepted = 0
        for start in range(0, len(rows), 400):
            result = call("POST", "/v1/events", json={"events": rows[start:start + 400]})
            if result.get("rejected"):
                raise SeedError(f"the API rejected observations: {result['rejected'][:2]}. Is it running the same "
                                "code as this checkout? Restart it.")
            accepted += result["accepted"]
        for category, text in notes_for(home):
            result = call("POST", "/v1/companion/tool", json={"home_id": home, "surface": "iphone", "name": "remember",
                                                              "args": {"category": category, "text": text}})
            if not result.get("ok"):
                raise SeedError(f"notebook entry refused ({result.get('error')})")
        for episode in episodes(end, home):
            call("POST", "/v1/companion/episode", json=episode.model_dump(mode="json"))
        call("PUT", "/v1/me/sharing", params={"home_id": home}, json={"share_with_care_team": True})
        if accepted:  # first time only: the care team's call, recorded the way the dashboard records it
            call("POST", f"/v1/patients/{home}/actions", json={"action": "acknowledge", "note": care_note_for(home),
                                                             "by": CARE_BY, "ts": care_ts(end)})
        done = {"home_id": home, "accepted": accepted, "duplicates": len(rows) - accepted, "jobs": {}}
        if jobs:
            call("POST", "/v1/admin/recompute")
            for name in ("nightly-mind", "weekly"):
                try:
                    call("POST", f"/v1/admin/{name}", params={"home_id": home})
                    done["jobs"][name] = "ok"
                except (SeedError, httpx.HTTPError) as error:  # the record is complete without them
                    done["jobs"][name] = f"skipped: {str(error)[:120]}"
        done["state"] = call("GET", f"/v1/patients/{home}/consensus")["state"]
    return done


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, help="write events.jsonl + record.json (the computed views) here")
    parser.add_argument("--url", help="local API to seed, e.g. http://127.0.0.1:8000")
    parser.add_argument("--reset", action="store_true", help="drop this person's simulated data on that API first")
    parser.add_argument("--no-jobs", action="store_true", help="skip the nightly-mind and weekly jobs")
    parser.add_argument("--home", default=HOME, help="home id to write the record under (aino, or a name in OTHER_NOTES)")
    parser.add_argument("--end", type=date.fromisoformat, default=datetime.now(TZ).date() - timedelta(days=1))
    args = parser.parse_args()
    if not args.out and not args.url:
        parser.error("give --url (seed a local API) and/or --out (export)")
    notes_for(args.home)
    rows = build(args.end, args.home)
    summary: dict[str, Any] = {"home_id": args.home, "days": N_DAYS, "events": len(rows), "last_day": str(args.end)}
    if args.out:
        result = populate(Store(":memory:"), rows, args.end)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in rows))
        (args.out / "record.json").write_text(json.dumps(result, indent=2))
        summary["out"] = str(args.out)
    if args.url:
        try:
            summary.update(seed(args.url, rows, reset=args.reset, jobs=not args.no_jobs))
        except (SeedError, ValueError) as error:
            print(f"could not seed {args.url}: {error}", file=sys.stderr)
            return 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
