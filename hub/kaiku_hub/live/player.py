"""Playing music through an output: the queue, the quarter-second writes, the cut between two tempos, the cues.

`PlayedMusic` is what `LyriaMusic` (generated music) and `LocalMusic` (the hub's own plain beat) share. The output is
anything with sounddevice's write-mode stream (`RawOutputStream(samplerate, channels, dtype)` -> `start()`,
`write(bytes)` that blocks for as long as the audio lasts, `stop()`): the head's speaker over MQTT
(`head_audio.HeadSpeaker`), a sound card (`sounddevice`), or a WAV file (`WavOut`). Config `[music] out` picks it.

Playback rules (measured with Lyria RealTime on 2026-11-14): the model sends about 4 s ahead of real time and a
fresh burst after every tempo change, so audio queued before a change is dropped, the cut gets 30 ms fades, and a
write is a quarter second, off the event loop: a new tempo, or silence, is at most that far away.
"""

from __future__ import annotations

import asyncio
import os
import time
import wave
from array import array
from typing import Any

from kaiku_contracts.jlog import get_logger

from . import sounds
from .base import Music

log = get_logger("hub")

SLICE_BYTES = 48000 * 4 // 4  # a quarter second of 48 kHz stereo 16-bit: how long a tempo change waits at most
FADE_MS = 30
FADE_BYTES = 48 * FADE_MS * 4
SECOND_BYTES = 48000 * 4


def faded(piece: bytes, rising: bool, ms: int = FADE_MS) -> bytes:
    """The piece with a short ramp at its start (`rising`) or its end, so a cut between two tempos does not click."""
    n = min(len(piece) // 4, 48 * ms)
    if n < 2:
        return piece
    a = array("h", piece)
    for i in range(n):
        g = i / n
        j = i if rising else len(a) // 2 - 1 - i
        a[2 * j] = int(a[2 * j] * g)
        a[2 * j + 1] = int(a[2 * j + 1] * g)
    return a.tobytes()


class WavOut:
    """The speaker's stand-in when the music goes to a file (`[music] out = "file"`, `KAIKU_MUSIC_FILE`): a hub
    without a speaker, a clean track for a recording, a check that needs no sound in the room.

    `realtime` makes the file a record of what would have been heard and when: a write takes as long as its audio
    lasts, like a sound card, and time in which nothing was written is silence in the file."""

    def __init__(self, path: str, realtime: bool = False):
        self.path, self.realtime = path, realtime
        self._clock: float | None = None
        self._frame = 4

    def RawOutputStream(self, samplerate: int, channels: int, dtype: str) -> WavOut:  # noqa: N802 (sounddevice's name)
        self._w = wave.open(self.path, "wb")
        self._w.setnchannels(channels)
        self._w.setsampwidth(2)
        self._w.setframerate(samplerate)
        self._frame, self._rate = 2 * channels, samplerate
        return self

    def start(self) -> None:
        return None

    def write(self, data: bytes) -> None:
        if not self.realtime:
            self._w.writeframes(data)
            return
        now = time.monotonic()
        if self._clock is None:
            self._clock = now
        if now - self._clock > 0.02:  # nothing was playing: that time is silence
            self._w.writeframes(bytes(int((now - self._clock) * self._rate) * self._frame))
            self._clock = now
        self._w.writeframes(data)
        self._clock += len(data) / (self._rate * self._frame)
        if self._clock > time.monotonic():
            time.sleep(self._clock - time.monotonic())

    def stop(self) -> None:
        self._w.close()


class PlayedMusic(Music):
    """Music with a player. Subclasses put PCM (48 kHz stereo 16-bit) on the queue with `_put`."""

    def __init__(self, audio: Any = None):
        self.audio = audio
        self._player: asyncio.Task | None = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._gen = 0  # counts cuts (a tempo change, a new song, a hush): audio queued under an older count is not played
        self._heard = 0  # bytes of the current count handed to the output
        self._sound = ""  # what gives the tempo now: "music" | "beat" | ""

    # ------------------------------------------------------------ the player
    def _start_player(self) -> bool:
        if self.audio is None:
            return False
        if self._player is None or self._player.done():
            self._queue, self._gen, self._heard = asyncio.Queue(), 0, 0
            self._player = asyncio.create_task(self._play_loop(), name=f"music-{self.name}")
        return True

    def _stop_player(self) -> None:
        if self._player is not None:
            self._player.cancel()
        self._player = None

    def _put(self, data: bytes) -> None:
        self._queue.put_nowait((self._gen, data))

    async def _play_loop(self) -> None:
        """Plays what was queued, a quarter second at a time. Audio from before a cut is dropped (`_drop_queued`):
        otherwise a new tempo is heard 4 s late, and later with each change."""
        out = self.audio.RawOutputStream(samplerate=48000, channels=2, dtype="int16")
        out.start()
        fade_in = False
        try:
            while True:
                gen, data = await self._queue.get()
                for i in range(0, len(data), SLICE_BYTES):
                    if gen != self._gen:  # a cut came: the rest of this chunk is the old sound
                        tail = data[i:i + FADE_BYTES]
                        if tail:
                            await asyncio.to_thread(out.write, faded(tail, rising=False))
                            if hasattr(out, "flush"):  # the head's speaker: play the fade out, then an empty buffer
                                await asyncio.to_thread(out.flush)
                        fade_in = True
                        break
                    piece = data[i:i + SLICE_BYTES]
                    if fade_in:
                        piece, fade_in = faded(piece, rising=True), False
                    # a speaker write blocks until the device takes the samples: never on the hub's event loop,
                    # or taps, the sway and the bus wait behind the music
                    await asyncio.to_thread(out.write, piece)
                    if gen == self._gen:
                        self._heard += len(piece)
        finally:
            out.stop()

    def _drop_queued(self) -> int:
        """Forget audio received before a cut. Returns the bytes dropped."""
        self._gen += 1
        self._heard = 0
        dropped = 0
        while not self._queue.empty():
            dropped += len(self._queue.get_nowait()[1])
        return dropped

    # ------------------------------------------------------------ Music: what Tap it back needs
    def tempo_by(self) -> str:
        return "music" if self.can_play_songs else "beat" if self.audio is not None else ""

    def heard_s(self) -> float:
        return self._heard / SECOND_BYTES

    async def _beat(self, bpm: float) -> str:
        """The hub's own plain beat at `bpm`, when there is an output and no generated song."""
        if not self._start_player():
            return ""
        self._drop_queued()
        bar = sounds.beat(float(bpm))  # four beats, synthesised once and queued again and again
        for _ in range(max(2, int(bpm) // 4)):  # about a minute: `hush` cuts it
            self._put(bar)
        self._sound = "beat"
        return "beat"

    async def hush(self) -> None:
        self._drop_queued()
        self._sound = ""

    async def chime(self, name: str) -> float:
        pcm = sounds.chime(name)
        if not pcm or self._player is None or self._player.done():
            return 0.0
        self._put(pcm)
        return sounds.seconds(pcm)


def default_file() -> str | None:
    return os.environ.get("KAIKU_MUSIC_FILE") or None
