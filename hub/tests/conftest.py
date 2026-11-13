"""Hub test fixtures: synthetic PPG, a fake RitualContext, isolated settings."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from kaiku_contracts import make
from kaiku_hub.live.base import OffMusic
from kaiku_hub.settings import Settings
from kaiku_hub.state import HubState


def synth_ppg(ibis_ms: list[float], fs: float = 100.0, noise: float = 30.0, seed: int = 0) -> np.ndarray:
    """PPG-like signal (int ADC ~16000) with beats at the given inter-beat intervals."""
    rng = np.random.default_rng(seed)
    beats = np.cumsum([500.0, *ibis_ms]) / 1000.0
    dur = beats[-1] + 0.6
    t = np.arange(0, dur, 1 / fs)
    x = np.zeros_like(t)
    for b in beats:
        x += np.exp(-((t - b) ** 2) / (2 * 0.06**2)) + 0.3 * np.exp(-((t - b - 0.25) ** 2) / (2 * 0.05**2))
    x = 16000 + 2000 * x + 300 * np.sin(2 * np.pi * 0.1 * t) + rng.normal(0, noise, t.size)
    return x.astype(int)


@pytest.fixture
def ppg():
    return synth_ppg


@pytest.fixture
def settings(tmp_path) -> Settings:
    s = Settings.load()
    s.cloud_url = None
    s.queue_path = tmp_path / "q.sqlite"
    s.state_path = tmp_path / "state.json"
    return s


class FakeCtx:
    """Records everything a step does; emit() validates against contracts like the real hub."""

    def __init__(self, settings: Settings, tmp_path):
        self.settings = settings
        self.state = HubState(tmp_path / "state.json")
        self.music = OffMusic()
        self.said: list[str] = []
        self.heads: list[dict] = []
        self.sensor_cmds: list[dict] = []
        self.obs: list[Any] = []
        self.nudge = ("daylight_walk", "test")

    async def say(self, text: str) -> None:
        self.said.append(text)

    async def head(self, **cmd: Any) -> None:
        make("cmd.head", cmd, source="hub")
        self.heads.append(cmd)

    async def sensors(self, **cmd: Any) -> None:
        make("cmd.sensors", cmd, source="hub")
        self.sensor_cmds.append(cmd)

    async def emit(self, type_: str, payload: dict, quality: float | None = None):
        env = make(type_, payload, source="hub", quality=quality)  # raises ContractError if invalid
        self.obs.append(env)
        return env

    async def get_nudge(self):
        return self.nudge

    def of(self, type_: str) -> list[Any]:
        return [e for e in self.obs if e.type == type_]


@pytest.fixture
def ctx(settings, tmp_path) -> FakeCtx:
    return FakeCtx(settings, tmp_path)
