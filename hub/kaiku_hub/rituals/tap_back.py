"""Tap it back: the robot's drum as a three-level rhythm game (D51). The flow; the numbers are `perception/tap_back.py`.

    intro  ->  level n:  LISTEN (the song plays at the level's tempo; the head listens, sways and blinks the beat)
                         -> the song goes quiet, the cue  ->  HER TURN (she taps the beat from memory)
                         -> the band: a word, a face, a chime  ->  again once, or the next level
           ->  one line that says how it went

`Game` only uses the ritual context (say / head / sensors / music), like every step, and has no clock of its own:
whoever runs it calls `tick` when `deadline` has come and `on_tap` for every tap. Two runners: the hub's own drum
step (`steps.Drum`), and the hub while it follows a head that runs its own ritual (`Hub._follow_game`, `hold=True`:
every `cmd.head` then carries `drum: "hold"`, again at least every `hold_every_s`).

Every cue lands three ways, so the game can be played with the voice off: the eyes, a chime on the same speaker as
the song (`live/sounds.py`), and the UNO Q's buzzer (`cmd.sensors chime`).

The microphone of an open conversation is closed for the whole game (`ctx.listening(False)` at the start, open again
when the game is over or falls back to free drumming), in both runners alike. The song and her taps are not speech,
and the gaps between the levels are under two seconds: a half-heard word there would make Kaiku answer over the next
song, and the head sends no tap while it speaks. Kaiku still says the game's own lines; she can talk again as soon
as the closing line starts.

Wording: these are people recovering from depression. A band is a warm word, a miss is "not quite" once and then
we move on; nothing is counted against her and no number is ever said. Every line passes `kaiku_contracts.wording`
with the robot's caps (tested).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

from ..perception.tap_back import Level, LevelResult, TapBackConfig, Try, level_plan, payload, score_try
from ..perception.taps import TapAnalyzer

TICK_S = 0.2
FADE_OUT_S = 0.4  # after `hush`: the quarter second being played, its fade, and what the speaker still holds

INTRO: dict[str, str] = {
    "music": "I'll play you a little song. Listen first, then tap its beat back on my head.",
    "beat": "I'll tap out a beat for you. Listen first, then tap it back on my head.",
    "": "Watch my light blink a beat. Then tap that beat back on my head.",
}
# No sound at all on a head that runs its own ritual: that head shows no chest light for the hub, it sways.
INTRO_SWAY = "Watch me sway to a beat. Then tap that beat back on my head."
CUE = "Your turn."
BAND_LINE: dict[str, str] = {
    "perfect": "Perfect! You kept its beat.",
    "great": "Great! That was very close.",
    "nice": "Nice! You caught its feel.",
}
AGAIN_LINE = "Oh, not quite. Let's try that one again."
NO_TAPS_LINE = "No rush. Listen once more, then tap when you're ready."
MOVE_ON_LINE = "That one was tricky. Let's leave it there."
FALLBACK_LINE = "My song got lost. Let's just drum together, any rhythm you like."
NEXT_LINE: dict[tuple[bool, bool], str] = {  # (last level, faster than the one before)
    (False, True): "Here's the next one. It's a little faster.",
    (False, False): "Here's the next one. It's a little slower.",
    (True, True): "Last one. It's a little faster.",
    (True, False): "Last one. It's slower, so take your time.",
}
EYES: dict[str, str] = {"perfect": "happy", "great": "happy", "nice": "soft", "again": "neutral"}
# A head that runs its own ritual (the standalone firmware, `hold`) has five faces: `listening` is its wide eyes and
# `soft` its calm face. So there the song gets the calm face (wide eyes are kept for "your turn") and every band
# she matched gets the happy one.
SONG_EYES: dict[bool, str] = {False: "listening", True: "soft"}
HELD_EYES: dict[str, str] = {**EYES, "nice": "happy"}
SOUND_WAIT_S = 6.0  # at most this long past the planned opening for the head's speaker to go quiet
WORDS_WAIT_S = 15.0  # at most this long past the room left for a spoken line, for Kaiku to finish saying it
BUZZER: dict[str, str] = {"perfect": "ok", "great": "ok", "nice": "ok", "again": "end_drum"}
NUMBER: tuple[str, ...] = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def close_line(played: int, passed: int) -> str:
    """How it went, in words. Counts only what happened; a level she did not match is never named as a miss."""
    if played <= 0:
        return "Thank you for listening with me."
    songs = f"{NUMBER[played].capitalize()} song{'s' if played != 1 else ''}"
    if played == 1:
        return f"{songs}, and you found its beat." if passed else f"{songs} today. Thank you for trying it with me."
    if passed == played:
        return f"{songs}, and you found the beat in every one."
    if passed == 0:
        return f"{songs} today, and tricky ones. Thank you for playing with me."
    return f"{songs}, and you found the beat in {NUMBER[passed]} of them."


def all_lines() -> list[str]:
    """Every line the game can say (for the wording test)."""
    return [*INTRO.values(), INTRO_SWAY, CUE, *BAND_LINE.values(), AGAIN_LINE, NO_TAPS_LINE, MOVE_ON_LINE, FALLBACK_LINE,
            *NEXT_LINE.values(), *(close_line(p, k) for p in range(0, 4) for k in range(0, p + 1))]


def words(line: str) -> int:
    return len(line.split())


def _today() -> date:
    return datetime.now().astimezone().date()


class Game:
    def __init__(self, cfg: TapBackConfig, *, day: date | None = None, sway: bool = True, refractory_ms: float = 80,
                 force_max_g: float = 4.0, hold: bool = False):
        self.cfg, self.sway, self.hold = cfg, sway, hold
        self.refractory_ms, self.force_max_g = refractory_ms, force_max_g
        self.levels: list[Level] = level_plan(day or _today(), cfg)
        self.results: list[LevelResult] = [LevelResult(lv) for lv in self.levels]
        self.strict = cfg.mode == "auto"  # auto: without a generated song this is not the game (free drumming)
        self.state = "new"  # wait | listen | turn | done | fallback
        self.deadline = 0.0
        self.i = 0
        self.sound = ""          # what gives the tempo of the level being played: music | beat | "" (the light)
        self.gave = ""           # the best of them over the whole game (for the record)
        self.taps = TapAnalyzer(refractory_ms, force_max_g)
        self.early_taps = 0      # taps before her turn was open: never counted
        self.last: Try | None = None
        self._then: Callable[[Any], Awaitable[None]] | None = None
        self._t0: float | None = None
        self._began = self._end = 0.0
        self._listen0 = self._listen_for = self._turn0 = self._open = 0.0
        self._last_tap: float | None = None
        self._last_hold = -1e9
        self._opened = True  # her turn is open: the head's speaker is quiet, taps reach the hub
        self._listen_asked = 0.0  # when the level's song was asked for
        self._waited_for_words = False
        self._mic_open = True  # the conversation's microphone as this game left it
        self._sound_ran_long = False

    # ------------------------------------------------------------ small helpers
    @property
    def running(self) -> bool:
        return self.state not in ("new", "done", "fallback")

    @property
    def level(self) -> Level:
        return self.levels[self.i]

    @property
    def played(self) -> list[LevelResult]:
        return [r for r in self.results if r.tries]

    def next_deadline(self) -> float:
        """When `tick` must be called next (a `hold` is due earlier than the game's own deadline, in follow mode)."""
        return min(self.deadline, self._last_hold + self.cfg.hold_every_s) if self.hold else self.deadline

    def _speak_s(self, ctx: Any, line: str) -> float:
        """Room for a spoken line, only when a voice really speaks it (text and off need none)."""
        return words(line) * self.cfg.word_s if getattr(ctx, "voice_audible", False) else 0.0

    async def _say(self, ctx: Any, line: str) -> float:
        """Say a line. Returns the room still to leave for it: the Live voice returns when it starts speaking,
        a scripted line in the cached voice only when it has been heard to its end (then none is left)."""
        t = time.monotonic()
        await ctx.say(line)
        room = self._speak_s(ctx, line)
        if room and time.monotonic() - t >= room / 2 and getattr(ctx, "speaker_busy", None) is False:
            return 0.0  # it went through the head's speaker while we waited, and the speaker is quiet again
        return room

    async def _mic(self, ctx: Any, on: bool) -> None:
        """Close the open conversation's microphone for the game, open it again after (see the module docstring)."""
        listening = getattr(ctx, "listening", None)
        if listening is not None and on != self._mic_open:
            self._mic_open = on
            await listening(on)

    @staticmethod
    def _trace(ctx: Any, detail: str, bpm: float | None = None) -> None:
        """A cue or a band for the apps' "Kaiku bot" tab (`raw.hub.trace`, on the home network only), when whoever
        runs the game offers one. Never her taps, never a number about her."""
        trace = getattr(ctx, "trace", None)
        if trace is not None:
            trace("game", detail=detail, bpm=bpm)

    async def _head(self, ctx: Any, **cmd: Any) -> None:
        if self.hold:
            cmd["drum"] = "hold"
            self._last_hold = time.monotonic()
        if cmd:
            await ctx.head(**cmd)

    def _wait(self, seconds: float, then: Callable[[Any], Awaitable[None]]) -> None:
        self.state, self._then, self.deadline = "wait", then, time.monotonic() + max(0.0, seconds)

    async def leave(self, ctx: Any) -> None:
        """Whoever runs the game calls this when it stops for any reason (done, the step was left, an abort): a
        microphone the game closed is never left closed."""
        await self._mic(ctx, True)

    def payload(self) -> tuple[dict[str, Any], float] | None:
        end = self._end or time.monotonic()
        return payload(self.results, end - self._t0 if self._t0 is not None else 0.0, self.gave)

    # ------------------------------------------------------------ the flow
    async def begin(self, ctx: Any) -> None:
        self._began = time.monotonic()
        await self._mic(ctx, False)
        await ctx.music.hush()  # a music adapter starts with its own opening groove: not before the first song
        kind = ctx.music.tempo_by() if hasattr(ctx.music, "tempo_by") else ""
        line = INTRO_SWAY if self.hold and not kind else INTRO.get(kind, INTRO[""])
        await self._head(ctx, eyes=SONG_EYES[self.hold], pan_mode="still")
        self._wait(await self._say(ctx, line), self._start_level)

    async def _start_level(self, ctx: Any) -> None:
        lv, replay = self.level, bool(self.results[self.i].tries)
        self.sound = await ctx.music.song(lv.bpm)
        if not self.sound and self.strict:
            await self._mic(ctx, True)
            self.state = "fallback"
            return
        if self.sound == "music" or not self.gave:
            self.gave = self.sound or self.gave
        now = time.monotonic()
        if self._t0 is None:
            self._t0 = now
        self._trace(ctx, f"level:{lv.number}", float(lv.bpm))
        await self._head(ctx, eyes=SONG_EYES[self.hold], chest="pulse", bpm=float(lv.bpm),
                         **({"pan_mode": "sway"} if self.sway else {}))
        self.state, self._listen0, self._listen_asked = "listen", now, now
        self._listen_for = self.cfg.replay_listen_s if replay else self.cfg.listen_s
        self.deadline = now + TICK_S

    async def _listen_tick(self, ctx: Any, now: float) -> None:
        waited = now - self._listen0
        heard = ctx.music.heard_s() if self.sound else waited
        if heard >= self._listen_for:
            await self._your_turn(ctx)
            return
        if self.sound and heard <= 0 and getattr(ctx, "speaker_busy", False) and now - self._listen_asked < WORDS_WAIT_S:
            # nothing of the song has sounded and the speaker is busy with something else (Kaiku is still
            # speaking): the song is waiting its turn, not lost. Its clock starts when the speaker is free.
            self._listen0, self.deadline = now, now + TICK_S
            return
        silent = heard <= 0 and waited > self.cfg.song_wait_s
        stalled = waited > self._listen_for + self.cfg.song_wait_s
        if self.sound and stalled and heard >= self._listen_for / 2:
            await self._your_turn(ctx)  # most of it was heard: go on
        elif self.sound and (silent or stalled):  # the song is not coming
            if self.strict:
                await ctx.music.hush()
                await self._mic(ctx, True)
                self.state = "fallback"
                return
            self.sound, self._listen0 = "", now  # forced mode: the light alone gives the beat from here
            self.deadline = now + TICK_S
        else:
            self.deadline = now + TICK_S

    async def _your_turn(self, ctx: Any) -> None:
        await ctx.music.hush()
        self._trace(ctx, "your_turn")
        await self._head(ctx, eyes="wide", pan_mode="still", chest="glow")
        t = time.monotonic()
        chime_s = await ctx.music.chime("your_turn")
        await ctx.sensors(chime="start_drum")
        room = await self._say(ctx, CUE)
        now = time.monotonic()
        self.taps = TapAnalyzer(self.refractory_ms, self.force_max_g)
        self._last_tap, self._turn0 = None, now
        # The speaker sits next to the head's motion sensor, and the head sends no tap while its speaker plays or
        # its motor moves (and for a moment after): a tap counts only once the song has faded and the cue (chime,
        # spoken words) is over. `_open` is the plan; `_open_turn` then waits for the speaker to really be quiet.
        sounds_end = t + (FADE_OUT_S if self.sound else 0.0) + chime_s  # the song's fade, then the chime
        self._open = max(sounds_end, now) + room + self.cfg.cue_clear_s
        self.state, self._opened, self._sound_ran_long = "turn", False, False
        self.deadline = self._open

    def _open_turn(self, ctx: Any, now: float) -> None:
        """Her time starts only when she can be heard: while the head's speaker still has sound of ours (a spoken
        cue that ran long), the opening moves on, so none of that time is counted against her."""
        if getattr(ctx, "speaker_busy", False) and now < min(self._turn0 + self.cfg.turn_s, self._open + SOUND_WAIT_S):
            self._sound_ran_long = True
            self.deadline = now + TICK_S
            return
        if self._sound_ran_long:  # the margin after the last sound still applies
            self._open = now + self.cfg.cue_clear_s
        self._opened = True
        self._turn_deadline()

    def _turn_deadline(self) -> None:
        wait = self.cfg.idle_end_s if self.taps.count else self.cfg.first_tap_s
        base = self._last_tap if self._last_tap is not None else self._open
        self.deadline = min(base + wait, self._turn0 + self.cfg.turn_s)

    async def on_tap(self, data: dict[str, Any], ctx: Any) -> None:
        """Every tap that reaches the hub. Only taps of her turn count; the rest are not hers to be judged on."""
        now = time.monotonic()
        if self.state != "turn" or not self._opened or now < self._open:
            self.early_taps += 1
            return
        if self.taps.count >= self.level.taps:
            return  # she has made the taps asked for; the band is on its way
        force = data.get("force")
        if not self.taps.add(int(data["t_ms"]), None if force is None else float(force)):
            return
        self._last_tap = now
        if self.taps.count >= self.level.taps:
            self.deadline = now  # enough: the band comes at once
        else:
            self._turn_deadline()

    async def _score(self, ctx: Any) -> None:
        r = self.results[self.i]
        t = score_try(self.level.bpm, list(self.taps.times), self.cfg, rejected=self.taps.rejected)
        r.tries.append(t)
        self.last = t
        self._end = time.monotonic()
        self._trace(ctx, f"band:{t.band}")
        await self._head(ctx, eyes=(HELD_EYES if self.hold else EYES)[t.band])
        chime_s = await ctx.music.chime(t.band)
        await ctx.sensors(chime=BUZZER[t.band])
        gave_up = len(r.tries) >= 2 and not any(x.measured for x in r.tries[-2:])  # two turns with no taps
        last_level = self.i + 1 >= len(self.levels)
        out_of_time = time.monotonic() - self._began > self.cfg.max_s
        if t.band != "again":
            line, nxt = BAND_LINE[t.band], "advance"
        elif gave_up:
            line, nxt = "", "finish"
        elif len(r.tries) <= self.cfg.retries and not out_of_time:
            line, nxt = (AGAIN_LINE if t.measured else NO_TAPS_LINE), "replay"
        else:
            line, nxt = MOVE_ON_LINE, "advance"
        t = time.monotonic()
        room = await self._say(ctx, line) if line else 0.0
        # the band's chime and words, then a breath (the chime may already be over when a line was heard to its end)
        pause = max(0.0, chime_s - (time.monotonic() - t)) + room + self.cfg.result_s
        if nxt == "replay":
            self._wait(pause, self._start_level)
        elif nxt == "finish" or last_level or out_of_time:
            self._wait(pause, self._finish)
        else:
            self._wait(pause, self._announce)

    async def _announce(self, ctx: Any) -> None:
        prev = self.level.bpm
        self.i += 1
        line = NEXT_LINE[(self.i + 1 >= len(self.levels), self.level.bpm > prev)]
        self._wait(await self._say(ctx, line), self._start_level)

    async def _finish(self, ctx: Any) -> None:
        await ctx.music.hush()
        await self._mic(ctx, True)  # the game is over: she can talk again, from the closing line on
        played = self.played
        await self._head(ctx, eyes="happy", pan_mode="still", chest="glow")
        await ctx.say(close_line(len(played), sum(r.passed for r in played)))
        self.state, self.deadline = "done", time.monotonic()

    async def tick(self, ctx: Any) -> str:
        """Call when `next_deadline()` has come. Returns "running", "done" or "fallback" (no song: free drumming)."""
        now = time.monotonic()
        if self.hold and self.running and now - self._last_hold >= self.cfg.hold_every_s:
            await self._head(ctx)
        if self.running and now >= self.deadline:
            if self.state == "wait" and self._then is not None:
                # Room for a spoken line is an estimate; on the head the real end is known. The next thing (a song,
                # the next line) waits for Kaiku's words: music waits for the voice on the one speaker, and a song
                # that cannot sound yet must not be taken for a song that is not coming.
                if getattr(ctx, "speaker_busy", False) and now < self.deadline + WORDS_WAIT_S:
                    self._waited_for_words = True
                    return "running"
                then, self._then = self._then, None
                await then(ctx)
            elif self.state == "listen":
                if now - self._began > self.cfg.max_s:
                    await self._finish(ctx)
                else:
                    await self._listen_tick(ctx, now)
            elif self.state == "turn" and not self._opened:
                self._open_turn(ctx, now)
            elif self.state == "turn":
                await self._score(ctx)
        return self.state if self.state in ("done", "fallback") else "running"
