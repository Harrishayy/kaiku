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


MIN_BAND_SNR = 3.0  # heart-band power density / out-of-band power density; white noise ~ 1


def band_snr(x: np.ndarray, fs: float, band: tuple[float, float]) -> float | None:
    """Power density inside the heart band over the density just above it (to 20 Hz or Nyquist).
    None when the sampling rate leaves no room above the band to measure noise."""
    top = min(20.0, fs / 2)
    if top - band[1] < 1.0:
        return None
    spec = np.abs(np.fft.rfft((x - np.mean(x)) * np.hanning(x.size))) ** 2
    f = np.fft.rfftfreq(x.size, 1 / fs)
    inside, above = spec[(f >= band[0]) & (f <= band[1])], spec[(f > band[1] + 0.5) & (f <= top)]
    if inside.size == 0 or above.size == 0:
        return None
    noise = float(above.mean())
    return float("inf") if noise == 0 else float(inside.mean() / noise)


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
    snr = band_snr(x, fs, (band[0], hi))
    if snr is not None and snr < MIN_BAND_SNR:
        # Band-passed noise always shows "beats"; a pulse concentrates its power in the heart band.
        return HrvResult(False, None, None, 0.0, 0, f"no pulse above the noise (band SNR {snr:.1f})")
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


CAMERA_MAX_FS = 50.0  # below this the batch is the camera backup (~15 Hz, measured rate); the KY-039 sends 100 Hz
CAMERA_FS_TOLERANCE = 0.25  # the camera's frame rate wobbles batch to batch; within this it is the same stream
ARTEFACT_RMSSD_MS = 5.0  # a resting heart is not this metronomic over >= 8 beats; mains light flicker is (D39).
#                           A heuristic from one bench artefact, never checked against a real finger recording; the
#                           robot as built has no finger sensor (D54), so only the camera backup reaches this code.
ARTEFACT_MIN_BEATS = 8


class PpgBuffer:
    """Accumulates raw/sensors/ppg batches for one breathing session and decides whether it is a pulse at all.

    Finger (KY-039, fixed 100 Hz grid): batches must be contiguous at the same rate, else the window restarts.
    Camera backup (variable ~15 Hz): each batch is resampled onto the first batch's rate, so small frame-rate
    changes don't throw the recording away; gives heart rate only, never RMSSD.
    A switch between the two mid-session (the UNO Q's auto fallback) restarts the window: sources are never mixed.
    `reason` says why a session was not measured (it is then missing, never guessed).
    """

    def __init__(self) -> None:
        self.samples: list[int] = []
        self.fs: float | None = None
        self.next_ms: float | None = None
        self.quality = 1.0
        self.restarts = 0
        self.reason = "no signal"

    @property
    def method(self) -> str | None:
        return None if self.fs is None else ("camera" if self.fs < CAMERA_MAX_FS else "finger")

    def add(self, fs_hz: float, samples: list[int], *, t0_ms: float | None = None,
            quality: float | None = None) -> None:
        camera = fs_hz < CAMERA_MAX_FS and (self.fs is None or self.fs < CAMERA_MAX_FS)
        gap_tol = (2.5 if camera else 1.0) * 1000 / fs_hz
        discontinuous = (t0_ms is not None and self.next_ms is not None
                         and abs(t0_ms - self.next_ms) > gap_tol)
        fs_tol = CAMERA_FS_TOLERANCE * self.fs if (camera and self.fs) else 1e-6
        if self.samples and (discontinuous or (self.fs is not None and abs(self.fs - fs_hz) > fs_tol)):
            self.samples.clear()
            self.quality = 1.0
            self.fs = None
            self.restarts += 1
        if quality is not None:
            self.quality = min(self.quality, quality)
        self.next_ms = t0_ms + len(samples) / fs_hz * 1000 if t0_ms is not None else None
        if self.fs is None:
            self.fs = fs_hz
        elif camera and abs(self.fs - fs_hz) > 1e-6 and len(samples) > 1:
            n = max(1, int(round(len(samples) / fs_hz * self.fs)))
            samples = [int(round(v)) for v in np.interp(np.linspace(0, len(samples) - 1, n),
                                                        np.arange(len(samples)), samples)]
        self.samples.extend(samples)

    @property
    def seconds(self) -> float:
        return len(self.samples) / self.fs if self.fs else 0.0

    def _window(self, samples: list[int], band: tuple[float, float], min_clean_ratio: float) -> HrvResult:
        r = analyze_ppg(samples, self.fs or 1.0, band, min_clean_ratio)
        if r.ok and self.method == "camera":
            r.rmssd_ms = None  # frame timing is too coarse for beat-to-beat variability
        return r

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
        return (self._window(self.samples[:n], band, min_clean_ratio),
                self._window(self.samples[-n:], band, min_clean_ratio))

    def session(
        self, breath_bpm: float, duration_s: float, band: tuple[float, float], min_clean_ratio: float,
        window_s: float = 30.0, quality_min: float = 0.5,
    ) -> tuple[dict | None, float, HrvResult | None, HrvResult | None]:
        """obs.hrv_session payload + quality + the pre/post window results.

        Payload is None ("not measured", see `self.reason`) when: no signal, the recording fails the clean-beat
        gate, the sensor's own quality is below `quality_min`, or a finger recording is too metronomic to be a
        heart (periodic light artefact). Quality = min(clean-beat ratio, sensor quality): the camera backup can
        never look better than its 0.6."""
        if not self.fs or not self.samples:
            self.reason = "no signal"
            return None, 0.0, None, None
        whole = self._window(self.samples, band, min_clean_ratio)
        if not whole.ok or whole.hr_bpm is None:
            self.reason = whole.reason or "quality gate"
            return None, whole.clean_ratio, None, None
        if self.quality < quality_min:
            self.reason = f"sensor quality {self.quality:.2f} below {quality_min:.2f}"
            return None, min(whole.clean_ratio, self.quality), None, None
        if (self.method == "finger" and whole.n_beats >= ARTEFACT_MIN_BEATS
                and whole.rmssd_ms is not None and whole.rmssd_ms < ARTEFACT_RMSSD_MS):
            self.reason = "too regular to be a pulse (periodic light artefact?)"
            return None, 0.0, None, None
        self.reason = ""
        pre, post = self.pre_post(window_s, band, min_clean_ratio)
        payload = {
            "hr_bpm": whole.hr_bpm,
            "rmssd_pre_ms": pre.rmssd_ms if pre.ok else None,
            "rmssd_post_ms": post.rmssd_ms if post.ok else None,
            "duration_s": round(duration_s, 1),
            "breath_bpm": breath_bpm,
            "method": self.method,
            "beats": whole.n_beats,
        }
        return {k: v for k, v in payload.items() if v is not None}, min(whole.clean_ratio, self.quality), pre, post
