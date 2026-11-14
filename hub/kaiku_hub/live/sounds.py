"""The few sounds the hub makes itself, as PCM (48 kHz stereo 16-bit, what the music player takes): the cues of
Tap it back, and a plain beat for when no generated song can play. Tones only, never a voice (Kaiku speaks with
its one Gemini voice or stays silent)."""

from __future__ import annotations

from functools import cache, lru_cache

import numpy as np

RATE = 48000

# name -> notes (Hz) played one after the other. Short, soft, and never a "wrong answer" buzzer: `again` is one
# low, gentle note.
CHIMES: dict[str, tuple[float, ...]] = {
    "your_turn": (880.0, 880.0),
    "perfect": (523.25, 659.25, 783.99, 1046.5),
    "great": (523.25, 659.25, 783.99),
    "nice": (523.25, 659.25),
    "again": (392.0,),
}
NOTE_S = 0.13
LAST_NOTE_S = 0.28


def _note(freq: float, seconds: float, level: float) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    wave = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(2 * np.pi * 2 * freq * t)
    env = np.minimum(1.0, t / 0.008) * np.exp(-t / (seconds * 0.45))
    env[-int(RATE * 0.01):] *= np.linspace(1.0, 0.0, int(RATE * 0.01))  # ends on silence: no click
    return wave * env * level


def _stereo(x: np.ndarray) -> bytes:
    pcm = np.clip(np.rint(x * 32767), -32768, 32767).astype("<i2")
    return np.repeat(pcm, 2).tobytes()


@cache
def chime(name: str, level: float = 0.35) -> bytes:
    """The cue `name` as PCM; b"" for a name that has none."""
    notes = CHIMES.get(name)
    if not notes:
        return b""
    return _stereo(np.concatenate([_note(f, LAST_NOTE_S if i == len(notes) - 1 else NOTE_S, level)
                                   for i, f in enumerate(notes)]))


def seconds(pcm: bytes) -> float:
    return len(pcm) / (RATE * 4)


@lru_cache(maxsize=8)
def beat(bpm: float, beats: int = 4, level: float = 0.5) -> bytes:
    """One bar of a plain beat at `bpm`: a soft wooden tick per beat, the first a little higher. Played again and
    again it is a steady beat (a bar is a whole number of samples per beat, so the repeats join without a jump)."""
    gap = int(round(RATE * 60.0 / bpm))
    out = np.zeros(gap * beats)
    for i in range(beats):
        tick = _note(1320.0 if i % 4 == 0 else 880.0, 0.07, level)
        seg = out[i * gap:i * gap + tick.size]
        seg += tick[:seg.size]
    return _stereo(out)
