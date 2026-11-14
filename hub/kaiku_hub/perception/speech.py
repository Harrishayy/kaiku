"""Speech features from local mic audio: energy-VAD pause ratio + syllable-rate estimate.

No audio or transcript is stored or transmitted; only these numbers are (obs.speech_features).
Rough by design — good enough to track change from a person's own baseline, not absolute rate.
"""

from __future__ import annotations

from collections import deque

import numpy as np
from kaiku_contracts.config import get
from scipy.signal import find_peaks


def speech_features(audio: np.ndarray, sr: int, frame_ms: int = 20) -> dict | None:
    x = np.asarray(audio, dtype=float).ravel()
    if x.size < sr:  # < 1 s
        return None
    n = int(sr * frame_ms / 1000)
    frames = x[: x.size // n * n].reshape(-1, n)
    energy = np.sqrt(np.mean(frames**2, axis=1))
    return _from_energy(energy, frame_ms)


def _from_energy(energy: np.ndarray, frame_ms: int) -> dict | None:
    # Silence, constant hum and unusable samples are missing evidence, not slowing speech.
    if len(energy) < 1000 // frame_ms or not np.isfinite(energy).all() or energy.max() <= 0:
        return None
    thresh = max(np.percentile(energy, 20) * 2.0, energy.max() * 0.05)
    voiced = energy > thresh
    pause_ratio = float(1.0 - voiced.mean())
    # syllable nuclei ~ peaks in the smoothed voiced energy envelope, >= 100 ms apart
    env = np.convolve(energy * voiced, np.ones(5) / 5, mode="same")
    peaks, _ = find_peaks(env, distance=max(1, int(100 / frame_ms)), prominence=thresh * 0.5)
    voiced_s = voiced.sum() * frame_ms / 1000
    sps = float(peaks.size / voiced_s) if voiced_s > 0 else 0.0
    if voiced_s < float(get("perception", "speech_min_voiced_s", 1.0)) or peaks.size < 2:
        return None
    return {
        "syllables_per_s": round(sps, 2),
        "pause_ratio": round(min(1.0, max(0.0, pause_ratio)), 3),
        "duration_s": round(len(energy) * frame_ms / 1000, 1),
    }


class SpeechWindow:
    """Bounded per-turn energy summaries. PCM is reduced immediately and never retained.

    Incomplete frames, overflow/device gaps, clipping and speaker overlap invalidate a turn.
    Requires a completed input transcription to distinguish a user turn from room noise.
    The 30-second bound is a memory limit, not a clinically calibrated task duration.
    """

    def __init__(self, sr: int = 16000):
        self.sr = sr
        self.frame = sr // 50
        self.energy: deque[float] = deque(maxlen=max(1, int(float(get("perception", "speech_window_s", 30)) * 50)))
        self.invalid = False

    def reset(self) -> None:
        self.energy.clear()
        self.invalid = False

    def add(self, pcm: bytes, *, usable: bool = True) -> None:
        if not usable or len(pcm) % (self.frame * 2):
            self.invalid = True
            return
        samples = np.frombuffer(pcm, dtype="<i2")
        if samples.size == 0:
            return
        if np.mean(np.abs(samples.astype(float)) >= 32760) > float(get("perception", "speech_clip_fraction", 0.01)):
            self.invalid = True
        frames = samples.astype(float).reshape(-1, self.frame) / 32768
        values = np.sqrt(np.mean(frames ** 2, axis=1))
        if len(self.energy) + len(values) > self.energy.maxlen:
            self.invalid = True
        self.energy.extend(values.tolist())

    def finish(self, *, heard: bool) -> dict | None:
        result = _from_energy(np.asarray(self.energy), 20) if heard and not self.invalid else None
        self.reset()
        return result
