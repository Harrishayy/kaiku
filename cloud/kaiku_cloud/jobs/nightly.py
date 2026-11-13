"""Recompute job: every patient's consensus (every 15 min on Modal) and, nightly, the simulation.

Runs inside the API process (single SQLite writer). On Modal, a Cron function calls
POST /v1/admin/recompute?eval=true on the deployed API (see cloud/app.py).
"""

from __future__ import annotations

from ..service import active_criteria, recompute_all
from ..settings import Settings
from ..store.db import Store
from .simulate import run_eval


def run(store: Store, settings: Settings, with_eval: bool = True, eval_runner=None) -> dict:
    """eval_runner(criteria) -> EvalResult (Modal passes a .map fan-out); defaults to an in-process run."""
    n = recompute_all(store, settings)
    result = {"recomputed": n}
    if with_eval:
        crit = active_criteria(store)
        ev = eval_runner(crit) if eval_runner else run_eval(criteria=crit)
        store.kv_set("eval", ev.model_dump(mode="json"))
        result["eval"] = ev.model_dump(mode="json")
    return result
