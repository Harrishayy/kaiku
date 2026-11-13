"""Speech features from local mic audio: energy-VAD pause ratio + syllable-rate estimate.

No audio or transcript is stored or transmitted; only these numbers are (obs.speech_features).
Rough by design — good enough to track change from a person's own baseline, not absolute rate.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import find_peaks


def speech_features(audio: np.ndarray, sr: int, frame_ms: int = 20) -> dict | None:
    x = np.asarray(audio, dtype=float).ravel()
    if x.size < sr:  # < 1 s
        return None
    n = int(sr * frame_ms / 1000)
    frames = x[: x.size // n * n].reshape(-1, n)
    energy = np.sqrt(np.mean(frames**2, axis=1))
    if energy.max() <= 0:
        return {"pause_ratio": 1.0, "duration_s": round(x.size / sr, 1)}
    thresh = max(np.percentile(energy, 20) * 2.0, energy.max() * 0.05)
    voiced = energy > thresh
    pause_ratio = float(1.0 - voiced.mean())
    # syllable nuclei ~ peaks in the smoothed voiced energy envelope, >= 100 ms apart
    env = np.convolve(energy * voiced, np.ones(5) / 5, mode="same")
    peaks, _ = find_peaks(env, distance=max(1, int(100 / frame_ms)), prominence=thresh * 0.5)
    voiced_s = voiced.sum() * frame_ms / 1000
    sps = float(peaks.size / voiced_s) if voiced_s > 0 else 0.0
    return {
        "syllables_per_s": round(sps, 2),
        "pause_ratio": round(min(1.0, max(0.0, pause_ratio)), 3),
        "duration_s": round(x.size / sr, 1),
    }
