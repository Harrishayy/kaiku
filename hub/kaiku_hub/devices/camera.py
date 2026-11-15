"""USB camera access lives in perception/face.py (in-memory only, never stored).

This module only re-exports it, so device selection stays in devices/. That is the hub machine's own camera
(`[attention] face_source = "laptop"`), started and stopped by presence in `Hub._on_distance`. The robot's camera
is on the UNO Q: `cmd.sensors {camera_enable}` opens and closes that device itself (its own light shows it), and
there is no separate status LED.
"""

from __future__ import annotations

from ..perception.face import FaceTracker, available

__all__ = ["FaceTracker", "available"]
