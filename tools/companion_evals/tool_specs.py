"""Companion tool schemas for the evals. Ground truth: `kaiku_contracts.companion_tools` (what the cloud serves)."""

from __future__ import annotations

from typing import Any

from kaiku_contracts.companion_tools import TOOLS, validate_args

__all__ = ["TOOLS", "load", "validate_args"]


def load() -> dict[str, dict[str, Any]]:
    return TOOLS
