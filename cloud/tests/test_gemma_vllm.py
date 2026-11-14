"""Bounded GPU-result waits, cancellation and spend admission without contacting Modal or a model."""
import sys
from types import SimpleNamespace

import pytest
from kaiku_cloud.llm import gemma_vllm, ledger
from kaiku_cloud.llm.errors import LlmUnavailable
from kaiku_cloud.store.db import Store
from kaiku_contracts import budget


@pytest.fixture
def invocation(monkeypatch):
    seen = []
    store = Store(":memory:")
    monkeypatch.setattr(ledger, "_store", store)
    monkeypatch.setattr(budget, "guard", lambda *a, **kw: seen.append("guard"))
    monkeypatch.setattr(budget, "charge", lambda *a, **kw: seen.append("charge"))

    class Call:
        error = None
        cancel_error = None

        def get(self, *, timeout):
            seen.append(("get", timeout))
            if self.error:
                raise self.error
            return "verified selection"

        def cancel(self, *, terminate_containers):
            seen.append(("cancel", terminate_containers))
            if self.cancel_error:
                raise self.cancel_error

    call = Call()

    def spawn(prompt):
        assert seen[:2] == ["guard", "charge"]
        seen.append("spawn")  # Deliberately retain no prompt text in the test telemetry.
        return call

    def from_name(*_args):
        seen.append("lookup")
        return lambda: SimpleNamespace(generate=SimpleNamespace(spawn=spawn))

    monkeypatch.setitem(sys.modules, "modal", SimpleNamespace(Cls=SimpleNamespace(from_name=from_name)))
    clock = iter((10., 12.))
    monkeypatch.setattr(gemma_vllm.time, "monotonic", lambda: next(clock))
    return call, seen, store


def test_result_wait_uses_remaining_deadline_after_lookup_and_spawn(invocation):
    _call, seen, store = invocation
    assert gemma_vllm.generate("private input", timeout_s=5) == "verified selection"
    assert seen == ["guard", "charge", "lookup", "spawn", ("get", 3.)]
    rows = store.model_calls("2000-01-01")
    assert len(rows) == 1 and rows[0]["ok"]
    assert "private input" not in str(rows) and "verified selection" not in str(rows)


@pytest.mark.parametrize("cancel_error", [None, RuntimeError("private provider details")])
def test_timeout_cancels_best_effort_keeps_charge_and_records_failure(invocation, cancel_error):
    call, seen, store = invocation
    call.error = TimeoutError("private input must never enter logs")
    call.cancel_error = cancel_error
    with pytest.raises(LlmUnavailable, match="gemma_modal failed: TimeoutError") as error:
        gemma_vllm.generate("private input", timeout_s=5)
    assert seen == ["guard", "charge", "lookup", "spawn", ("get", 3.), ("cancel", False)]
    assert "private" not in str(error.value)
    rows = store.model_calls("2000-01-01")
    assert len(rows) == 1 and not rows[0]["ok"] and "private" not in str(rows)


def test_budget_rejection_never_dispatches(invocation, monkeypatch):
    _call, seen, _store = invocation

    def denied(*_a, **_kw):
        raise budget.BudgetExceeded("spent")

    monkeypatch.setattr(budget, "charge", denied)
    with pytest.raises(LlmUnavailable, match="BudgetExceeded"):
        gemma_vllm.generate("private input", timeout_s=5)
    assert seen == ["guard"]


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_deadline_never_reserves_or_dispatches(invocation, timeout):
    _call, seen, _store = invocation
    with pytest.raises(LlmUnavailable, match="finite positive timeout"):
        gemma_vllm.generate("private input", timeout_s=timeout)
    assert seen == []
