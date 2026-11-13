"""Crisis phrase check for the evals. The matcher lives in `kaiku_contracts.safety` (shared with the cloud);
`tools/tests/test_companion_evals.py` checks it agrees with the hub gate on `fixtures/safety_cases.json`."""

from kaiku_contracts.safety import Hit, SafetyCheck, normalise, version

__all__ = ["Hit", "SafetyCheck", "normalise", "version"]
