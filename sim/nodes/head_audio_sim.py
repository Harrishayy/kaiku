"""Twin of the head's speaker and microphone on the audio topics (plan 07 section 4; `kaiku_contracts.topics`).

    kaiku/v1/<home>/audio/head/speaker   640-byte frames (16 kHz mono 16-bit, 20 ms); zero-length = drop the buffer
    kaiku/v1/<home>/audio/head/mic       the same frames, only while `cmd.head {mic: open}` holds (10 s without one
                                         = closed), and never while the speaker plays or 250 ms after (half-duplex)

`SpeakerTwin` does what the firmware's speaker does (firmware/atech-head/kaiku_link/head_audio.cpp): a ring buffer
of half a second, played at 16 kHz on its own clock; playback starts once 120 ms is buffered or 120 ms after the
first frame; silence when it runs dry (the next sound buffers again); the newest frame dropped when the ring is
full; a zero-length message empties the ring, but the 120 ms already handed to the audio driver still play. With
`KAIKU_SIM_HEAD_AUDIO=<path.wav>` everything that reached the speaker goes into that WAV on the wall clock (silence
included), and the counts and timings into `<path>.json`: the proof from the HEAD's side that a song arrived in
real time and went quiet for her turn.

`MicTwin` is the microphone and a person's voice: with `KAIKU_SIM_HEAD_MIC=<path.wav>` (16 kHz mono 16-bit) that
recording is what the microphone hears, once: the person starts `KAIKU_SIM_HEAD_MIC_DELAY_S` after the microphone
first opened AND once the speaker has been quiet for a second (nobody talks over Kaiku), and then keeps talking in
real time (words said while the speaker plays are lost, as on the head); a quiet room after it. Frames leave as the
firmware sends them: in bursts of one or two every 32 ms (512-sample capture blocks), not evenly every 20 ms.
Nothing here ever plays sound or opens a real microphone.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import wave
from collections import deque
from typing import Any

from kaiku_contracts.topics import AUDIO_FRAME_BYTES, AUDIO_FRAME_MS, AUDIO_RATE_HZ

FRAME_S = AUDIO_FRAME_MS / 1000
RING_FRAMES = int(0.5 / FRAME_S)  # the head's ring buffer: half a second
START_FRAMES = 6  # playback starts once 120 ms is buffered (or 120 ms after the first frame)
DRIVER_FRAMES = 6  # about 128 ms are already in the audio driver: a drop message does not reach them
MIC_AFTER_SPEAKER_S = 0.25
MIC_BLOCK_S = 0.032  # the firmware captures 512 samples at a time
PERSON_WAITS_QUIET_S = 1.0
MIC_HOLD_S = 10.0
SILENCE = bytes(AUDIO_FRAME_BYTES)


class SpeakerTwin:
    def __init__(self, path: str | None = None):
        self.path = path
        self.ring: deque[bytes] = deque()
        self.driver: deque[bytes | None] = deque([None] * DRIVER_FRAMES)
        self._started = False  # the ring is feeding the driver
        self._run_rx = 0.0  # when the first frame of this stretch came
        self.frames = self.flushes = self.overflows = self.bad = self.glitches = self.max_fill = 0
        self.played = 0  # frames of real audio that reached the "speaker"
        self.last_real = -1e9  # when the speaker last played real audio (the microphone is closed around it)
        self._gap_n = 0
        self._gap_sum = self._gap_sq = self._gap_max = 0.0
        self._last_rx = 0.0
        self._t0: float | None = None
        self._w: Any = None
        self._dropped = False  # a drop message came since the last frame played: the quiet after it is meant
        self.spans: list[list[float]] = []  # [start s, end s] of every stretch of sound, on the WAV's clock
        self.glitch_at: list[float] = []

    def on_frame(self, data: bytes) -> None:
        now = time.monotonic()
        if not data:  # "drop what you have buffered, now"
            self.flushes += 1
            self.ring.clear()
            self._last_rx = 0.0
            self._dropped = True
            return
        if len(data) != AUDIO_FRAME_BYTES:
            self.bad += 1
            return
        if self._last_rx and now - self._last_rx < 0.2:  # inside one stream: how evenly do the frames come?
            gap = now - self._last_rx
            self._gap_n += 1
            self._gap_sum += gap
            self._gap_sq += gap * gap
            self._gap_max = max(self._gap_max, gap)
        self._last_rx = now
        self.frames += 1
        if len(self.ring) >= RING_FRAMES:
            self.overflows += 1  # full: the newest frame is dropped (as the firmware does)
            return
        if not self.ring and not self._started:
            self._run_rx = now
        self.ring.append(data)
        self.max_fill = max(self.max_fill, len(self.ring))
        if self._t0 is None:
            self._t0 = now

    def quiet_s(self, now: float) -> float:
        """How long the speaker has been quiet: 0 while it has anything buffered or sounding (the firmware's
        speakerBusy / speakerQuietMs)."""
        if self.ring or self._started or any(f is not None for f in self.driver):
            return 0.0
        return now - self.last_real

    def playing(self, now: float) -> bool:
        return self.quiet_s(now) < MIC_AFTER_SPEAKER_S

    def stats(self) -> dict[str, Any]:
        n = max(1, self._gap_n)
        mean = self._gap_sum / n
        return {"frames_received": self.frames, "frames_played": self.played, "drop_messages": self.flushes,
                "overflows": self.overflows, "wrong_size": self.bad, "glitches": self.glitches,
                "max_buffered_ms": self.max_fill * AUDIO_FRAME_MS, "interval_mean_ms": round(mean * 1000, 2),
                "interval_sd_ms": round(max(0.0, self._gap_sq / n - mean * mean) ** 0.5 * 1000, 2),
                "interval_max_ms": round(self._gap_max * 1000, 1), "sound_spans_s": self.spans,
                "glitch_at_s": self.glitch_at}

    async def run(self) -> None:
        """The speaker's own clock: one frame every 20 ms from the first one on, real audio or silence."""
        k, dry, fed_dry, fed_any = 0, 0, 0, False
        try:
            while True:
                if self._t0 is None:
                    await asyncio.sleep(0.005)
                    continue
                if self._w is None and self.path:
                    self._w = wave.open(self.path, "wb")
                    self._w.setnchannels(1)
                    self._w.setsampwidth(2)
                    self._w.setframerate(AUDIO_RATE_HZ)
                due = self._t0 + k * FRAME_S
                now = time.monotonic()
                if now < due:
                    await asyncio.sleep(due - now)
                    continue
                if not self._started and self.ring and (len(self.ring) >= START_FRAMES or now - self._run_rx >= 0.12):
                    self._started = True
                fed = self.ring.popleft() if self._started and self.ring else None
                if fed is None:
                    self._started = False  # ran dry: the next sound buffers 120 ms again
                    fed_dry += 1
                else:
                    if fed_dry and fed_any and fed_dry < 10 and not self._dropped:
                        self.glitches += 1  # the ring ran dry for less than 200 ms inside a sound
                        self.glitch_at.append(round((k + DRIVER_FRAMES) * FRAME_S, 2))
                    self._dropped, fed_dry, fed_any = False, 0, True
                self.driver.append(fed)
                frame = self.driver.popleft()  # what leaves the speaker now went into the driver 120 ms ago
                if frame is not None:
                    if dry or not self.spans:
                        self.spans.append([round(k * FRAME_S, 2), round(k * FRAME_S, 2)])
                    self.spans[-1][1] = round((k + 1) * FRAME_S, 2)
                    dry = 0
                    self.played += 1
                    self.last_real = now
                else:
                    dry += 1
                if self._w is not None:
                    self._w.writeframes(frame or SILENCE)
                k += 1
        finally:
            self.close()

    def close(self) -> None:
        if self._w is not None:
            self._w.close()
            self._w = None
            with open(self.path + ".json", "w") as f:  # type: ignore[operator]
                json.dump(self.stats(), f, indent=1)


class MicTwin:
    def __init__(self, bus: Any, speaker: SpeakerTwin, path: str | None = None, delay_s: float = 1.0):
        self.bus, self.speaker, self.delay_s = bus, speaker, delay_s
        self.speech: list[bytes] = []
        if path:
            with wave.open(path) as w:
                if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (AUDIO_RATE_HZ, 1, 2):
                    raise ValueError(f"{path}: the microphone twin needs 16 kHz mono 16-bit")
                pcm = w.readframes(w.getnframes())
            pcm += bytes(-len(pcm) % AUDIO_FRAME_BYTES)
            self.speech = [pcm[i:i + AUDIO_FRAME_BYTES] for i in range(0, len(pcm), AUDIO_FRAME_BYTES)]
        self.open_until = 0.0
        self.opened_at: float | None = None
        self.sent = self.muted = self.lost = 0
        self.said_at: tuple[float, float] | None = None  # wall-clock (monotonic) start and end of the recording

    def on_cmd(self, mic: str | None) -> None:
        if mic == "open":
            now = time.monotonic()
            if now > self.open_until:
                self.opened_at = self.opened_at or now
            self.open_until = now + MIC_HOLD_S
        elif mic == "close":
            self.open_until = 0.0

    async def run(self) -> None:
        """One capture block every 32 ms; whole 20 ms frames leave as they fill up (one or two at a time)."""
        i = 0  # the frame of the recording the person is at
        t_prev: float | None = None
        owed = 0.0  # captured seconds not sent yet
        while True:
            await asyncio.sleep(MIC_BLOCK_S)
            now = time.monotonic()
            is_open = now <= self.open_until
            heard = is_open and not self.speaker.playing(now)  # half-duplex: nothing while the head speaks
            if self.speech and self.said_at is None and heard and self.opened_at is not None and \
                    now - self.opened_at >= self.delay_s and self.speaker.quiet_s(now) >= PERSON_WAITS_QUIET_S:
                self.said_at = (now, now)  # the person starts talking
            talking = self.said_at is not None and i < len(self.speech)
            if not heard:  # closed, or the head is speaking: nothing leaves the head
                if is_open:
                    self.muted += 1
                if talking and t_prev is not None:  # she keeps talking: those words are lost
                    lost = int((now - t_prev) / FRAME_S)
                    i, self.lost = min(len(self.speech), i + lost), self.lost + lost
                t_prev, owed = now, 0.0
                continue
            owed += min(now - t_prev, 0.2) if t_prev is not None else MIC_BLOCK_S
            t_prev = now
            while owed >= FRAME_S:
                owed -= FRAME_S
                if self.said_at is not None and i < len(self.speech):
                    frame, i = self.speech[i], i + 1
                    self.said_at = (self.said_at[0], now)
                else:
                    frame = SILENCE
                await self.bus.publish_audio(frame, stream="mic")
                self.sent += 1


def from_env(bus: Any) -> tuple[SpeakerTwin, MicTwin]:
    """The twins a head sim runs with: the speaker always (it is what closes the microphone), files only when asked."""
    speaker = SpeakerTwin(os.environ.get("KAIKU_SIM_HEAD_AUDIO") or None)
    mic = MicTwin(bus, speaker, os.environ.get("KAIKU_SIM_HEAD_MIC") or None,
                  float(os.environ.get("KAIKU_SIM_HEAD_MIC_DELAY_S", "1.0")))
    bus.on_audio("speaker", speaker.on_frame)
    return speaker, mic
