"""Bounded GPU-result waits, cancellation and spend admission without contacting Modal or a model."""
import itertools
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

    def spawn(prompt, *, max_tokens):
        assert seen[:2] == ["guard", "charge"]
        seen.append("spawn")
        call.max_tokens = max_tokens  # Deliberately retain no prompt text in the test telemetry.
        return call

    def from_name(*_args):
        seen.append("lookup")
        return lambda: SimpleNamespace(generate=SimpleNamespace(spawn=spawn))

    monkeypatch.setitem(sys.modules, "modal", SimpleNamespace(Cls=SimpleNamespace(from_name=from_name)))
    clock = itertools.chain((10.,), itertools.repeat(12.))
    monkeypatch.setattr(gemma_vllm, "_last_answer", None)
    monkeypatch.setattr(gemma_vllm.time, "monotonic", lambda: next(clock))
    return call, seen, store


def test_result_wait_uses_remaining_deadline_after_lookup_and_spawn(invocation):
    _call, seen, store = invocation
    assert gemma_vllm.generate("private input", timeout_s=5) == "verified selection"
    assert seen == ["guard", "charge", "lookup", "spawn", ("get", 3.)]
    assert _call.max_tokens == 1200  # [gemma_modal].max_output_tokens when the caller names no cap
    rows = store.model_calls("2000-01-01")
    assert len(rows) == 1 and rows[0]["ok"]
    assert "private input" not in str(rows) and "verified selection" not in str(rows)


@pytest.mark.parametrize("cancel_error", [None, RuntimeError("private provider details")])
def test_timeout_cancels_best_effort_keeps_charge_and_records_failure(invocation, cancel_error, monkeypatch):
    call, seen, store = invocation
    monkeypatch.setattr(gemma_vllm, "_last_answer", 11.)  # answered a second ago: the container is up
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


def test_callers_cap_reaches_the_gpu_and_a_warm_container_reserves_less(invocation, monkeypatch):
    call, seen, _store = invocation
    reserved = []
    monkeypatch.setattr(budget, "charge", lambda _p, _m, usd, **_kw: (seen.append("charge"), reserved.append(usd)))
    monkeypatch.setattr(gemma_vllm.time, "monotonic", lambda: 100.)
    gemma_vllm.generate("private input", timeout_s=5, max_output_tokens=2400)
    assert call.max_tokens == 2400
    seen.clear()
    gemma_vllm.generate("private input", timeout_s=5)  # answered a moment ago: no cold start in the reservation
    assert reserved[1] < reserved[0] / 2


def test_timeout_on_a_cold_gpu_leaves_the_call_that_starts_it(invocation):
    call, seen, _store = invocation
    call.error = TimeoutError()
    with pytest.raises(LlmUnavailable, match="TimeoutError"):
        gemma_vllm.generate("private input", timeout_s=5)
    assert seen == ["guard", "charge", "lookup", "spawn", ("get", 3.)]  # no cancel: the GPU keeps starting
