"""USB camera access lives in perception/face.py (in-memory only, never stored).

This module exists so device selection stays in devices/: enable/disable the camera from presence
and the physical shutter. TODO(A): wire the status LED (cmd/sensors camera_enable) to this state.
"""

from __future__ import annotations

from ..perception.face import FaceTracker, available

__all__ = ["FaceTracker", "available"]
