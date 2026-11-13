"""PPG -> heart rate + RMSSD with a quality gate.

Pipeline: detrend -> band-pass (~0.7-3.5 Hz) -> peak detection (sub-sample, parabolic) ->
IBI cleaning (physiological range + within 25% of median) -> RMSSD over consecutive clean IBIs.
Rejected (ok=False) if fewer than `min_clean_ratio` of beats are clean.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, filtfilt, find_peaks

MIN_SECONDS = 6.0


@dataclass
class HrvResult:
    ok: bool
    hr_bpm: float | None
    rmssd_ms: float | None
    clean_ratio: float
    n_beats: int
    reason: str = ""


def _refine(y: np.ndarray, i: int) -> float:
    """Parabolic interpolation of a peak position (sub-sample accuracy)."""
    if 0 < i < len(y) - 1:
        a, b, c = y[i - 1], y[i], y[i + 1]
        denom = a - 2 * b + c
        if denom != 0:
            return i + 0.5 * (a - c) / denom
    return float(i)


def analyze_ppg(
    samples: np.ndarray | list[int],
    fs: float,
    band: tuple[float, float] = (0.7, 3.5),
    min_clean_ratio: float = 0.7,
    invert: bool = False,
) -> HrvResult:
    x = np.asarray(samples, dtype=float)
    if x.size < fs * MIN_SECONDS:
        return HrvResult(False, None, None, 0.0, 0, f"need >= {MIN_SECONDS:.0f}s of signal")
    if invert:
        x = -x
    nyq = fs / 2
    hi = min(band[1], nyq * 0.95)
    b, a = butter(2, [band[0] / nyq, hi / nyq], btype="band")
    y = filtfilt(b, a, x - np.mean(x))
    if np.std(y) == 0:
        return HrvResult(False, None, None, 0.0, 0, "flat signal")
    peaks, _ = find_peaks(y, distance=max(1, int(0.33 * fs)), prominence=0.3 * np.std(y))
    if peaks.size < 4:
        return HrvResult(False, None, None, 0.0, int(peaks.size), "too few beats")
    t = np.array([_refine(y, int(p)) for p in peaks]) / fs * 1000.0
    ibis = np.diff(t)
    physio = (ibis > 300) & (ibis < 2000)
    if not physio.any():
        return HrvResult(False, None, None, 0.0, int(peaks.size), "no physiological intervals")
    med = float(np.median(ibis[physio]))
    clean = physio & (np.abs(ibis - med) < 0.25 * med)
    ratio = float(clean.sum() / ibis.size)
    if ratio < min_clean_ratio or clean.sum() < 3:
        return HrvResult(False, None, None, ratio, int(peaks.size), "quality gate: too few clean beats")
    hr = 60000.0 / float(np.mean(ibis[clean]))
    pair = clean[1:] & clean[:-1]
    d = np.diff(ibis)[pair]
    rmssd = float(np.sqrt(np.mean(d**2))) if d.size else None
    return HrvResult(True, round(hr, 1), None if rmssd is None else round(rmssd, 1), round(ratio, 3), int(peaks.size))


class PpgBuffer:
    """Accumulates raw/sensors/ppg batches (assumed contiguous) for one breathing session."""

    def __init__(self) -> None:
        self.samples: list[int] = []
        self.fs: float | None = None

    def add(self, fs_hz: float, samples: list[int]) -> None:
        if self.fs is not None and abs(self.fs - fs_hz) > 1e-6:  # rate changed: restart
            self.samples.clear()
        self.fs = fs_hz
        self.samples.extend(samples)

    @property
    def seconds(self) -> float:
        return len(self.samples) / self.fs if self.fs else 0.0

    def pre_post(self, window_s: float, band: tuple[float, float], min_clean_ratio: float
                 ) -> tuple[HrvResult, HrvResult]:
        """HRV in the first and last `window_s` (handoff §5.3: 30 s before / after breathing).
        If the session is shorter than 2 windows, use the two halves instead."""
        if not self.fs or not self.samples:
            empty = HrvResult(False, None, None, 0.0, 0, "no signal")
            return empty, empty
        n = int(window_s * self.fs)
        if len(self.samples) < 2 * n:
            n = len(self.samples) // 2
        return (analyze_ppg(self.samples[:n], self.fs, band, min_clean_ratio),
                analyze_ppg(self.samples[-n:], self.fs, band, min_clean_ratio))

    def session(
        self, breath_bpm: float, duration_s: float, band: tuple[float, float], min_clean_ratio: float,
        window_s: float = 30.0,
    ) -> tuple[dict | None, float, HrvResult | None, HrvResult | None]:
        """obs.hrv_session payload + quality (clean ratio) + the pre/post window results.
        Payload is None if the whole recording fails the quality gate."""
        if not self.fs or not self.samples:
            return None, 0.0, None, None
        whole = analyze_ppg(self.samples, self.fs, band, min_clean_ratio)
        if not whole.ok or whole.hr_bpm is None:
            return None, whole.clean_ratio, None, None
        pre, post = self.pre_post(window_s, band, min_clean_ratio)
        payload = {
            "hr_bpm": whole.hr_bpm,
            "rmssd_pre_ms": pre.rmssd_ms if pre.ok else None,
            "rmssd_post_ms": post.rmssd_ms if post.ok else None,
            "duration_s": round(duration_s, 1),
            "breath_bpm": breath_bpm,
        }
        return {k: v for k, v in payload.items() if v is not None}, whole.clean_ratio, pre, post
