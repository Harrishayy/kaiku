"""The robot head's own speaker and microphone, as the hub sees them (plan 07 section 4). No sound device on the hub.

    hub --PCM frames--> kaiku/v1/<home>/audio/head/speaker --> the head's I2S speaker
    hub <--PCM frames-- kaiku/v1/<home>/audio/head/mic     <-- the head's microphone (only while the hub holds it open)

Wire format (fixed with the head firmware; `kaiku_contracts.topics`): signed 16-bit little-endian mono at 16 kHz, one
MQTT message = 20 ms = 320 samples = 640 bytes, QoS 0, not retained, never an envelope. A zero-length message on the
speaker topic = "drop what you have buffered, now".

`HeadSpeaker` is the one sender. Everything that wants the speaker (the drum music and its chimes, Kaiku's Live
voice) opens a stream on it; a stream holds the speaker while it is sending and for `release_ms` after, and another
stream's audio WAITS for it (it is delayed, never mixed in), so frames of two sources cannot interleave. One
exception to waiting: Kaiku's voice (a callback stream, `priority` 1) never waits behind music (a write stream,
priority 0): it takes the speaker at once, the head is told to drop the music it has buffered, and the music waits
until the voice is done. The head keeps only a short ring buffer and plays silence when it runs dry, so the hub is
the clock: one frame every 20 ms, `lead_ms` ahead of real time (4 frames at once when a sound starts, then steady).

Both stream shapes of `sounddevice` are offered, so the adapters need no other code path:
    write mode      out = speaker.RawOutputStream(samplerate=48000, channels=2, dtype="int16"); out.start()
                    out.write(pcm)   # blocks for as long as the audio lasts, like a sound card (call it off the loop)
    callback mode   with speaker.RawOutputStream(samplerate=24000, channels=1, dtype="int16", callback=fill): ...
                    with head.RawInputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1600, callback=cb): ...
The microphone is half-duplex on the head (no frames while its speaker plays and about 250 ms after): there is no
voice barge-in on the robot, and a gap in the frames is a gap, never silence (nothing is made up to fill it).
Nothing here stores, logs or forwards audio; only counts and timings are kept (`HeadSpeaker.stats()`).
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections.abc import Awaitable, Callable
from math import gcd
from typing import Any

import numpy as np
from kaiku_contracts.jlog import get_logger
from kaiku_contracts.topics import AUDIO_FRAME_BYTES, AUDIO_FRAME_MS, AUDIO_FRAME_SAMPLES, AUDIO_RATE_HZ

log = get_logger("hub")

FRAME_S = AUDIO_FRAME_MS / 1000
Publish = Callable[[bytes], Awaitable[Any]]


class Resampler:
    """Streaming rational resampler for mono float samples: zero-stuff by `up`, one windowed-sinc low-pass, keep
    every `down`-th sample. 48 kHz -> 16 kHz is up 1 / down 3 (97 taps: flat to about 6.5 kHz, more than 60 dB down
    from 8.5 kHz, so nothing above the 8 kHz the head can play folds back); 24 kHz -> 16 kHz is up 2 / down 3."""

    def __init__(self, rate_in: int, rate_out: int, taps_per_phase: int = 32):
        g = gcd(rate_in, rate_out)
        self.up, self.down = rate_out // g, rate_in // g
        n = taps_per_phase * max(self.up, self.down) + 1
        fs = rate_in * self.up
        cutoff = 0.45 * min(rate_in, rate_out)  # Hz; the transition band ends just above the lower Nyquist
        k = np.arange(n) - (n - 1) / 2
        h = np.sinc(2 * cutoff / fs * k) * np.kaiser(n, 6.0)
        self.h = (h / h.sum() * self.up)[::-1].copy()  # reversed once: a window of the input dotted with it
        self.n = n
        self.reset()

    def reset(self) -> None:
        self._hist = np.zeros(self.n - 1)
        self._phase = 0

    def process(self, x: np.ndarray) -> np.ndarray:
        if x.size == 0:
            return np.zeros(0)
        if self.up > 1:
            xu = np.zeros(x.size * self.up)
            xu[::self.up] = x
        else:
            xu = x
        buf = np.concatenate([self._hist, xu])
        win = np.lib.stride_tricks.sliding_window_view(buf, self.n)[self._phase::self.down]
        y = win @ self.h
        self._phase = self._phase + len(win) * self.down - xu.size
        self._hist = buf[-(self.n - 1):]
        return y


class HeadPcm:
    """PCM of any source format (s16le, `rate` Hz, 1 or 2 channels) -> whole 640-byte frames for the head. Stereo is
    mixed down, `gain` leaves headroom for the small speaker, the remainder of a frame waits for the next call."""

    def __init__(self, rate: int, channels: int, gain: float = 0.8):
        self.channels, self.gain = channels, gain
        self._rs = Resampler(rate, AUDIO_RATE_HZ) if rate != AUDIO_RATE_HZ else None
        self._carry = np.zeros(0, dtype=np.int16)

    def reset(self) -> None:
        if self._rs is not None:
            self._rs.reset()
        self._carry = np.zeros(0, dtype=np.int16)

    def feed(self, data: bytes) -> list[bytes]:
        x = np.frombuffer(data, dtype="<i2").astype(np.float64)
        if self.channels > 1:
            x = x[:x.size - x.size % self.channels].reshape(-1, self.channels).mean(axis=1)
        y = self._rs.process(x) if self._rs is not None else x
        pcm = np.clip(np.rint(y * self.gain), -32768, 32767).astype("<i2")
        buf = np.concatenate([self._carry, pcm]) if self._carry.size else pcm
        whole = buf.size - buf.size % AUDIO_FRAME_SAMPLES
        self._carry = buf[whole:]
        return [buf[i:i + AUDIO_FRAME_SAMPLES].tobytes() for i in range(0, whole, AUDIO_FRAME_SAMPLES)]

    def tail(self) -> bytes | None:
        """The waiting remainder as one last frame padded with silence (the end of a sound)."""
        if not self._carry.size:
            return None
        out = np.zeros(AUDIO_FRAME_SAMPLES, dtype="<i2")
        out[:self._carry.size] = self._carry
        self._carry = np.zeros(0, dtype=np.int16)
        return out.tobytes()


class HeadSpeaker:
    """The head's speaker: one sender at a time, frames paced on the hub's clock. See the module docstring."""

    def __init__(self, publish: Publish, *, lead_ms: float = 80, gain: float = 0.8, release_ms: float = 150):
        self._publish = publish
        self.lead_s, self.gain, self.release_s = min(lead_ms, 120) / 1000, gain, release_ms / 1000
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._owner: object | None = None
        self._owner_priority = 0
        self._play_until = 0.0  # when the head will have played everything sent so far (hub clock)
        self._last_send = 0.0
        self.reset_stats()

    # ------------------------------------------------------------ numbers only: how the pacing went
    def reset_stats(self) -> None:
        self.frames = self.drops = self.restarts = self.switches = self.catch_up = self.taken = 0
        self._gap_n = 0
        self._gap_sum = self._gap_sq = self._gap_max = self.ahead_max_s = 0.0

    def stats(self) -> dict[str, float]:
        n = max(1, self._gap_n)
        mean = self._gap_sum / n
        return {"frames": self.frames, "frames_sent_at_once": self.catch_up, "drop_messages": self.drops,
                "clock_restarts": self.restarts, "taken_by_voice": self.taken,
                "sender_changes": self.switches, "lead_ms": round(self.lead_s * 1000, 1),
                "ahead_max_ms": round(self.ahead_max_s * 1000, 1), "interval_mean_ms": round(mean * 1000, 2),
                "interval_sd_ms": round(max(0.0, self._gap_sq / n - mean * mean) ** 0.5 * 1000, 2),
                "interval_max_ms": round(self._gap_max * 1000, 1)}

    @property
    def playing(self) -> bool:
        """True while the head still has sound of ours to play (its microphone sends nothing then)."""
        return time.monotonic() < self._play_until

    # ------------------------------------------------------------ the one way a frame leaves
    def _bind(self) -> None:
        with contextlib.suppress(RuntimeError):
            self._loop = asyncio.get_running_loop()

    def _post(self, data: bytes) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        with contextlib.suppress(RuntimeError):  # the loop is shutting down
            asyncio.run_coroutine_threadsafe(self._publish(data), loop)

    def play(self, who: object, frame: bytes, abort: Callable[[], bool] | None = None) -> bool:
        """Send one frame in its 20 ms slot. Blocks (call from a worker thread) while another sender holds the
        speaker and until the slot comes. False = not sent, because `abort()` said so."""
        while True:
            if abort is not None and abort():
                return False
            now = time.monotonic()
            with self._lock:
                mine = self._owner is who
                free = self._owner is None or now >= self._play_until + self.release_s
                if not mine and not free and getattr(who, "priority", 0) > self._owner_priority:
                    # Kaiku's voice never waits behind the music: the head drops the music it has buffered
                    self._play_until = self._last_send = 0.0
                    self.drops += 1
                    self.taken += 1
                    self._post(b"")
                    free = True
                if mine or free:
                    if not mine:
                        self._owner, self._owner_priority = who, getattr(who, "priority", 0)
                        self.switches += 1
                    if now > self._play_until:  # the head has run dry (a start, a gap, a stall): the clock restarts
                        self._play_until = now
                        self._last_send = 0.0
                        self.restarts += 1
                    wait = self._play_until - self.lead_s - now
                    if wait <= 0:
                        self._play_until += FRAME_S
                        self.frames += 1
                        self.ahead_max_s = max(self.ahead_max_s, self._play_until - now)
                        steady = wait > -FRAME_S / 2  # in its own slot (not one of the frames that build the cushion)
                        if steady and self._last_send:
                            gap = now - self._last_send
                            self._gap_n += 1
                            self._gap_sum += gap
                            self._gap_sq += gap * gap
                            self._gap_max = max(self._gap_max, gap)
                        if not steady:
                            self.catch_up += 1
                        self._last_send = now
                        self._post(frame)
                        return True
                else:
                    wait = 0.01
            time.sleep(min(wait, 0.02))

    def drop(self, who: object | None = None) -> None:
        """The zero-length message: the head forgets what it has buffered. The speaker is free at once."""
        with self._lock:
            if who is not None and self._owner is not None and self._owner is not who:
                return  # another sender is playing: its sound is not ours to cut
            self._owner = None
            self._play_until = 0.0
            self._last_send = 0.0
            self.drops += 1
            self._post(b"")

    def release(self, who: object) -> None:
        with self._lock:
            if self._owner is who:
                self._owner = None

    def RawOutputStream(self, samplerate: int, channels: int, dtype: str = "int16",  # noqa: N802 (sounddevice's name)
                        callback: Callable[..., None] | None = None, **_kw: Any) -> HeadStream:
        self._bind()
        return HeadStream(self, samplerate, channels, callback)


class HeadStream:
    """One source's stream on the head's speaker (`sounddevice.RawOutputStream` in both of its shapes)."""

    def __init__(self, speaker: HeadSpeaker, rate: int, channels: int, callback: Callable[..., None] | None):
        self.speaker, self.rate, self.channels, self.callback = speaker, rate, channels, callback
        self.pcm = HeadPcm(rate, channels, speaker.gain)
        self.priority = 1 if callback is not None else 0  # the voice (callback stream) goes before the music
        self._closed = False
        self._cut = 0  # counts flushes: a frame pulled before one is never sent after it
        self._thread: threading.Thread | None = None

    # ---- write mode (the music player)
    def start(self) -> None:
        self._closed = False

    def write(self, data: bytes) -> None:
        for frame in self.pcm.feed(data):
            if not self.speaker.play(self, frame, lambda: self._closed):
                return

    def flush(self) -> None:
        """After the faded end of a sound: send what is left of it, let the head play it out, then tell the head
        to drop its buffer, so the next sound starts on an empty one."""
        tail = self.pcm.tail()
        if tail is not None:
            self.speaker.play(self, tail, lambda: self._closed)
        time.sleep(max(0.0, self.speaker._play_until - time.monotonic()) + FRAME_S)
        self.pcm.reset()
        if not self._closed:
            self.speaker.drop(self)

    def stop(self) -> None:
        """Now: whatever is in flight is not sent and the head drops its buffer (the end of the music, a crisis)."""
        self._closed = True
        self.pcm.reset()
        self.speaker.drop(self)

    # ---- callback mode (the Live voice): the hub's clock pulls the audio, 20 ms at a time
    def cut(self) -> None:
        """Barge-in / the adapter cleared its audio: nothing already pulled is sent, the head drops its buffer."""
        self._cut += 1
        self.pcm.reset()
        self.speaker.drop(self)

    def _pull(self) -> None:
        n = self.rate * AUDIO_FRAME_MS // 1000
        buf = bytearray(n * 2 * self.channels)
        speaking = False
        while not self._closed:
            self.callback(buf, n, None, None)  # type: ignore[misc]
            if not any(buf):  # nothing to say: send nothing (the head plays silence by itself and may listen)
                if speaking:
                    speaking = False
                    tail = self.pcm.tail()
                    if tail is not None:
                        self.speaker.play(self, tail, lambda: self._closed)
                    # not released here: the speaker stays the voice's for `release_ms` after its last frame, so
                    # the music does not slip into the breath between two sentences
                time.sleep(FRAME_S / 2)
                continue
            speaking = True
            cut = self._cut
            for frame in self.pcm.feed(bytes(buf)):
                if not self.speaker.play(self, frame, lambda c=cut: self._closed or self._cut != c):
                    break

    def __enter__(self) -> HeadStream:
        self._closed = False
        self._thread = threading.Thread(target=self._pull, name="head-speaker", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._closed = True
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.speaker.drop(self)


class HeadMic:
    """The head's microphone as a `sounddevice.RawInputStream`: frames from the audio topic, regrouped into
    `blocksize` blocks for the callback. While it is open the hub tells the head so (`cmd.head {mic: open}`, again
    every `renew_s`); the head stops by itself when it no longer hears that. A gap in the frames (the head is
    speaking, a lost packet) stays a gap."""

    def __init__(self, head: HeadAudio, blocksize: int, callback: Callable[..., None]):
        self.head, self.block_bytes, self.callback = head, blocksize * 2, callback
        self._buf = bytearray()
        self._task: asyncio.Task | None = None
        self._held = True  # False: closed inside the open conversation (`hold(False)`), the head is told `mic: close`
        self.frames = 0

    def feed(self, data: bytes) -> None:
        if len(data) != AUDIO_FRAME_BYTES or not self._held:
            return  # not a frame of ours (never guess at its format), or one that left before the head closed
        self.frames += 1
        self._buf += data
        while len(self._buf) >= self.block_bytes:
            block = bytes(self._buf[:self.block_bytes])
            del self._buf[:self.block_bytes]
            self.callback(block, self.block_bytes // 2, None, None)

    async def _hold(self) -> None:
        while True:
            await self.head.command(mic="open")
            await asyncio.sleep(self.head.renew_s)

    def hold(self, on: bool) -> None:
        """Close or reopen the head's microphone while the conversation stays open (call on the event loop)."""
        if on == self._held or self.head.mic is not self:
            return
        self._held = on
        self._buf.clear()
        loop = asyncio.get_running_loop()
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if on:
            self._task = loop.create_task(self._hold(), name="head-mic")
        else:
            loop.create_task(self.head.command(mic="close"), name="head-mic-close")

    def __enter__(self) -> HeadMic:
        self.head.mic = self
        self._task = asyncio.get_running_loop().create_task(self._hold(), name="head-mic")
        return self

    def __exit__(self, *exc: object) -> None:
        if self.head.mic is self:
            self.head.mic = None
        if self._task is not None:
            self._task.cancel()
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().create_task(self.head.command(mic="close"), name="head-mic-close")


class HeadAudio:
    """What the Live voice adapter gets instead of the `sounddevice` module when the robot is its own body: the
    head's speaker (shared with the music through the one `HeadSpeaker`) and the head's microphone."""

    name = "head"

    def __init__(self, speaker: HeadSpeaker, command: Callable[..., Awaitable[None]], *, renew_s: float = 2.0,
                 phone_tail_ms: float = 400, phone_fresh_s: float = 2.0):
        self.speaker, self.command, self.renew_s = speaker, command, renew_s
        self.mic: HeadMic | None = None
        self.mic_frames = 0
        # A phone beside the robot standing in for the head's microphone (audio/phone/mic, D56)
        self.phone_tail_s, self.phone_fresh_s = phone_tail_ms / 1000, phone_fresh_s
        self.phone_frames = self.phone_muted = 0
        self._phone_at = 0.0  # when the phone's last frame came (hub clock); 0 = never

    @property
    def phone_listening(self) -> bool:
        """A phone is sending its microphone right now: it is the robot's ear, and the head's own frames are not."""
        return bool(self._phone_at) and time.monotonic() - self._phone_at < self.phone_fresh_s

    @property
    def mic_source(self) -> str:
        return "phone" if self.phone_listening else "head"

    def on_mic_frame(self, data: bytes) -> None:
        """Bus handler for audio/head/mic. Frames that arrive while no conversation holds the microphone open are
        dropped here, unread; so are the head's while a phone is the ear (two microphones are never mixed)."""
        if self.mic is not None and not self.phone_listening:
            self.mic_frames += 1
            self.mic.feed(data)

    def on_phone_frame(self, data: bytes) -> None:
        """Bus handler for audio/phone/mic: the same frames from a phone beside the robot. Dropped unread while no
        conversation holds the microphone open. The head keeps its own microphone shut while its speaker plays; a
        phone cannot know, so that is done here: nothing it heard while the head's speaker has sound of ours, or
        `phone_tail_ms` after (the head's buffer and the room), is passed on. Kaiku never hears herself."""
        if len(data) != AUDIO_FRAME_BYTES:
            return
        now = time.monotonic()
        self._phone_at = now
        if self.mic is None:
            return
        if now < self.speaker._play_until + self.phone_tail_s:
            self.phone_muted += 1
            return
        self.phone_frames += 1
        self.mic.feed(data)

    def RawOutputStream(self, **kw: Any) -> HeadStream:  # noqa: N802
        return self.speaker.RawOutputStream(**kw)

    def RawInputStream(self, samplerate: int, channels: int, dtype: str, blocksize: int,  # noqa: N802
                       callback: Callable[..., None], **_kw: Any) -> HeadMic:
        if samplerate != AUDIO_RATE_HZ or channels != 1:
            raise ValueError("the head's microphone is 16 kHz mono")
        return HeadMic(self, blocksize, callback)


class AutoAudio:
    """`[voice] audio = "auto"`: the head's speaker and microphone when a head is alive on the bus at the moment a
    conversation opens, this machine's sound card otherwise. Decided per conversation, for both directions at
    once (the microphone is opened first), so a conversation never listens on one body and speaks on the other."""

    def __init__(self, head: HeadAudio, local: Any, head_alive: Callable[[], bool]):
        self.head, self.local, self.head_alive = head, local, head_alive
        self.using: Any = None

    @property
    def name(self) -> str:
        return "head" if self.using is self.head else "local" if self.using is self.local else "auto"

    def RawInputStream(self, **kw: Any) -> Any:  # noqa: N802
        self.using = self.head if self.head_alive() else self.local
        return self.using.RawInputStream(**kw)

    def RawOutputStream(self, **kw: Any) -> Any:  # noqa: N802
        if self.using is None:
            self.using = self.head if self.head_alive() else self.local
        return self.using.RawOutputStream(**kw)
