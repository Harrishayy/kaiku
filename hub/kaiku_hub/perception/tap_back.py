"""Tap it back: the numbers of the robot's rhythm game (D51). Pure: no I/O, no clock.

Kaiku plays a short song at a tempo, the song goes quiet, she taps its beat from memory. One try is scored by how
close the tempo of her taps (the median gap between them) is to the song's, with the steadiness of the gaps as a
gate on the two top bands. Bands are words, never a number said to her: perfect / great / nice / again.

    plan = level_plan(date.today(), cfg)                 # today's three songs: the same on a rerun, others tomorrow
    r = score_try(plan[0].bpm, tap_times_ms, cfg)        # -> Try(tapped_bpm, error_pct, steadiness, band, beat)

The tempo is given to her, so this is not her own spontaneous tempo: it never becomes `obs.drum_session`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import gcd
from typing import Any

import numpy as np

from .taps import PAUSE_MS, TapAnalyzer

BANDS: tuple[str, ...] = ("perfect", "great", "nice", "again")
MODES: tuple[str, ...] = ("auto", "free", "tap_back")
BEAT_LEVELS: tuple[tuple[str, float], ...] = (("beat", 1.0), ("half", 0.5), ("double", 2.0))


@dataclass
class TapBackConfig:
    """config/kaiku.toml [tap_back]. Every number of the game lives there."""

    mode: str = "auto"                 # auto: the game when a generated song can play | free: never | tap_back: always
    level_bpm: tuple[float, ...] = (100.0, 126.0, 76.0)
    level_vary_bpm: tuple[float, ...] = (6.0, 8.0, 4.0)  # each day's tempo is the level's, plus or minus up to this
    level_taps: tuple[int, ...] = (8, 8, 12)
    listen_s: float = 8.0              # how much of the song she hears before it goes quiet
    replay_listen_s: float = 6.0       # the same level again: a little shorter
    song_wait_s: float = 6.0           # no sound of the song this long after asking for it = it is not coming
    first_tap_s: float = 8.0           # her turn ends when no tap comes this long after the cue
    idle_end_s: float = 2.5            # ... or this long after her last tap
    turn_s: float = 25.0               # ... or after this long whatever happens
    cue_clear_s: float = 0.4           # taps count only this long after the cue has sounded (the head mutes its tap sensor around its speaker)
    min_taps: int = 4                  # fewer taps than this give no tempo
    perfect_pct: float = 4.0           # tempo error bands, in percent of the song's tempo
    great_pct: float = 8.0
    nice_pct: float = 15.0
    steady_min: float = 0.85           # steadiness below this: perfect counts as great, great as nice
    half_double: bool = True           # tapping every other beat, or two to a beat, is in time with the song
    retries: int = 1                   # replays of a level after `again`
    word_s: float = 0.3                # time allowed per spoken word before the song or her turn starts (0 = none)
    result_s: float = 0.8              # a breath after the band's chime and words, before the next thing
    hold_every_s: float = 3.0          # follow mode: `cmd.head {drum: hold}` at least this often
    max_s: float = 170.0               # the whole game ends kindly after this long
    bpm_min: float = 60.0              # filled from [music]
    bpm_max: float = 200.0

    @classmethod
    def from_dict(cls, d: dict[str, Any], *, bpm_min: float = 60.0, bpm_max: float = 200.0) -> TapBackConfig:
        out = cls(bpm_min=bpm_min, bpm_max=bpm_max)
        for key, default in vars(cls()).items():
            if key not in d:
                continue
            try:
                value = d[key]
                if isinstance(default, tuple):
                    value = tuple(type(default[0])(v) for v in value)
                elif isinstance(default, bool):
                    value = bool(value)
                else:
                    value = type(default)(value)
            except (TypeError, ValueError):
                continue  # a bad value keeps the default: the ritual must still start
            setattr(out, key, value)
        if out.mode not in MODES:
            out.mode = "auto"
        n = min(len(out.level_bpm), len(out.level_taps))
        out.level_bpm, out.level_taps = out.level_bpm[:n], out.level_taps[:n]
        out.level_vary_bpm = (tuple(out.level_vary_bpm) + (0.0,) * n)[:n]
        return out


@dataclass(frozen=True)
class Level:
    number: int   # 1-based
    bpm: int      # today's tempo of this level's song
    taps: int     # taps asked for


def level_plan(day: date, cfg: TapBackConfig) -> list[Level]:
    """Today's levels. Each level's tempo moves around its configured one by whole beats per minute, by the date
    alone: the same day gives the same three songs, the next day always gives three other tempos."""
    out = []
    for i, (bpm, vary, taps) in enumerate(zip(cfg.level_bpm, cfg.level_vary_bpm, cfg.level_taps, strict=False)):
        span = 2 * int(vary) + 1
        offset = 0
        if span > 1:
            step = next(s for s in range(max(2, round(span * 0.38)), span + 2) if gcd(s, span) == 1)
            offset = ((day.toordinal() + 7 * i) * step) % span - int(vary)  # every day a different one of `span`
        out.append(Level(i + 1, int(round(min(cfg.bpm_max, max(cfg.bpm_min, bpm + offset)))), max(cfg.min_taps, int(taps))))
    return out


@dataclass
class Try:
    """One try at one level, as measured."""

    taps: int
    tapped_bpm: float | None = None   # None = too few taps to call a tempo
    error_pct: float | None = None    # against the beat level in `beat`
    steadiness: float | None = None
    band: str = "again"
    beat: str = "beat"                # beat | half | double
    rejected: int = 0

    @property
    def measured(self) -> bool:
        return self.tapped_bpm is not None


def band_of(error_pct: float, steadiness: float, cfg: TapBackConfig) -> str:
    """The word for a try. Edges belong to the better band (exactly 4 % is still perfect)."""
    if error_pct <= cfg.perfect_pct:
        band = "perfect"
    elif error_pct <= cfg.great_pct:
        band = "great"
    elif error_pct <= cfg.nice_pct:
        band = "nice"
    else:
        return "again"
    if steadiness < cfg.steady_min and band != "nice":  # the tempo fits but the taps wander: one band lower
        band = BANDS[BANDS.index(band) + 1]
    return band


def score_try(target_bpm: float, times_ms: list[int], cfg: TapBackConfig, *, rejected: int = 0) -> Try:
    """Score the taps of one try (device-clock milliseconds, already past the refractory filter)."""
    n = len(times_ms)
    iv = np.diff(np.asarray(times_ms, dtype=float)) if n >= 2 else np.array([])
    iv = iv[(iv > 0) & (iv <= PAUSE_MS)]
    if n < cfg.min_taps or iv.size < cfg.min_taps - 1:
        return Try(taps=n, rejected=rejected)
    tapped = float(min(400.0, 60000.0 / np.median(iv)))
    steadiness = float(np.clip(1.0 - np.std(iv) / np.mean(iv), 0.0, 1.0))
    levels = BEAT_LEVELS if cfg.half_double else BEAT_LEVELS[:1]
    beat, error = min(((name, abs(tapped - target_bpm * k) / (target_bpm * k) * 100) for name, k in levels),
                      key=lambda x: x[1])
    return Try(taps=n, tapped_bpm=round(tapped, 1), error_pct=round(error, 1), steadiness=round(steadiness, 3),
               band=band_of(round(error, 1), steadiness, cfg), beat=beat, rejected=rejected)


def better(a: Try, b: Try) -> Try:
    """The try that counts for a level played twice: the better band, then the smaller error."""
    ka = (BANDS.index(a.band), a.error_pct if a.error_pct is not None else 1e9)
    kb = (BANDS.index(b.band), b.error_pct if b.error_pct is not None else 1e9)
    return b if kb < ka else a


@dataclass
class LevelResult:
    level: Level
    tries: list[Try] = field(default_factory=list)

    @property
    def best(self) -> Try:
        out = self.tries[0]
        for t in self.tries[1:]:
            out = better(out, t)
        return out

    @property
    def passed(self) -> bool:
        return self.best.band != "again"


def payload(results: list[LevelResult], duration_s: float, song: str) -> tuple[dict[str, Any], float] | None:
    """`obs.tap_back` for the levels played, and its quality (as the drum's: the share of triggers that were real
    taps, scaled down for very few taps). None when no level has a measured try: nothing is recorded then."""
    played = [r for r in results if r.tries]
    if not any(t.measured for r in played for t in r.tries):
        return None
    levels = []
    for r in played:
        b = r.best
        row: dict[str, Any] = {"level": r.level.number, "target_bpm": float(r.level.bpm), "taps": b.taps,
                               "band": b.band, "tries": len(r.tries), "beat": b.beat}
        if b.measured:
            row.update(tapped_bpm=b.tapped_bpm, error_pct=b.error_pct, steadiness=b.steadiness)
        levels.append(row)
    errors = [lv["error_pct"] for lv in levels if "error_pct" in lv]
    steady = [lv["steadiness"] for lv in levels if "steadiness" in lv]
    taps = sum(t.taps for r in played for t in r.tries)
    rejected = sum(t.rejected for r in played for t in r.tries)
    out = {"levels": levels, "levels_played": len(levels), "levels_passed": sum(lv["band"] != "again" for lv in levels),
           "error_pct": round(float(np.mean(errors)), 1) if errors else None,
           "steadiness": round(float(np.mean(steady)), 3) if steady else None,
           "taps": taps, "rejected_taps": rejected, "duration_s": round(max(0.0, duration_s), 1),
           "song": song if song in ("music", "beat") else "light"}
    quality = round(taps / max(1, taps + rejected) * min(1.0, taps / 8), 3)
    return {k: v for k, v in out.items() if v is not None}, quality


@dataclass
class OneTapSource:
    """Two boards can feel one tap: the UNO Q's knock switch (`src: knock`) and the head's motion sensor
    (`src: imu`). Each stamps `t_ms` with its own clock, so their times cannot be compared and the refractory window
    cannot tell that the two reports are one tap. A run of taps is therefore taken from ONE of them: the first to
    report holds the drum until it has been quiet for `hold_s`; the other's reports are dropped meanwhile."""

    hold_s: float = 3.0
    src: str | None = None
    last: float = -1e9
    dropped: int = 0

    def accept(self, src: str, now: float) -> bool:
        if self.src is None or src == self.src or now - self.last > self.hold_s:
            self.src, self.last = src, now
            return True
        self.dropped += 1
        return False


def analyzer(refractory_ms: float, force_max_g: float) -> TapAnalyzer:
    return TapAnalyzer(refractory_ms, force_max_g)
