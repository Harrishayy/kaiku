"""Pure camera maths (no OpenCV import here, so it is testable anywhere).

Frames never leave this process: callers pass arrays in and get numbers out.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int


def face_payload(box: Box, frame_w: int, frame_h: int, confidence: float = 0.9) -> dict:
    """RawFace payload: centre in -1..1 (x right, y down), size = face width / frame width."""
    cx = (box.x + box.w / 2) / frame_w
    cy = (box.y + box.h / 2) / frame_h
    return {
        "x_norm": round(max(-1.0, min(1.0, cx * 2 - 1)), 3),
        "y_norm": round(max(-1.0, min(1.0, cy * 2 - 1)), 3),
        "size": round(max(0.0, min(1.0, box.w / frame_w)), 3),
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
    }


def distance_cm(size: float | None, k_cm: float, far_cm: float) -> float:
    """Rough distance from face width ratio (pinhole: d ~ k / size). No face -> far_cm."""
    if not size or size <= 0:
        return far_cm
    return round(min(far_cm, k_cm / size), 1)


def light_payload(mean_y: float, lux_per_unit: float) -> dict:
    """RawLight payload from the mean luminance (0-255) of a frame taken with exposure + gain locked."""
    raw = int(round(max(0.0, min(255.0, mean_y))))
    return {"raw": raw, "lux_est": round(raw * lux_per_unit, 1)}


def biggest(boxes: list[Box]) -> Box | None:
    return max(boxes, key=lambda b: b.w * b.h) if boxes else None


def forehead(box: Box) -> Box:
    """Camera pulse (backup): the forehead patch (upper-middle of the face box) has the cleanest green signal."""
    return Box(box.x + box.w // 4, box.y + box.h // 10, max(1, box.w // 2), max(1, box.h // 5))


def ppg_signal_ok(samples: list[int], min_range: int, max_value: int) -> bool:
    """KY-039 batch looks like a real signal: not flat (unwired / no LED) and not pinned at the rail."""
    if not samples:
        return False
    lo, hi = min(samples), max(samples)
    return hi - lo >= min_range and hi < max_value and lo > 0


def parse_csv_samples(csv: str) -> list[int]:
    return [int(x) for x in csv.split(",") if x.strip().lstrip("-").isdigit()]
