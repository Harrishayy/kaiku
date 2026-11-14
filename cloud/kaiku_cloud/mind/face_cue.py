"""Going a little gentler after a quiet face during a task (D52).

With the person's opt-in "Camera during activities", the phone or Mac counts movements of the face while a game or
the check-in chat runs and sends numbers only (`obs.face_signs`). The practitioner sees those numbers against the
person's own usual. The companion never does: all that reaches it is which of today's kinds of task
(`games`, `check_in`) read clearly below that usual, as an enum on the context card (`ContextCard.quieter_in`) and
as a words-only `manner` on a `feel` plan. `assemble.render_card` turns the enum into "go gently, and never mention
their face or a camera". No number, no state and no word about how they looked crosses.

The rule, all of it from config (`config/kaiku.toml [face_cue]`, metrics from `config/criteria.toml`):
a kind of task is "quieter" today when, among its cue metrics that have a reading today and an ESTABLISHED usual
(a full baseline of at least `min_baseline_days` of her own days, never the provisional early one), at least one is
`z` spreads or more below that usual and none is above it. Readings already carry the criteria's own minimums
(one usable face in most frames, enough frames, long enough), so a thin capture can never set it.

It is a cue for Kaiku's manner. It reads no verdict, changes no state and is not shown to anyone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from kaiku_contracts.config import get
from kaiku_contracts.criteria import Criteria

from .. import service
from ..analytics.data import PatientData
from ..analytics.drift import baseline_of, worse_z
from ..settings import TZ
from ..store.db import Store

KINDS = ("games", "check_in")  # the order the card lists them in


def cfg(key: str, default: Any) -> Any:
    return get("face_cue", key, default)


def quieter(crit: Criteria, data: PatientData, now: datetime) -> list[str]:
    """Today's kinds of task in which the counted face signs were clearly below this person's own usual. Pure."""
    if not cfg("enabled", True):
        return []
    today = now.astimezone(TZ).date()
    need, floor = float(cfg("z", 2.0)), int(cfg("min_baseline_days", 7))
    by_name = {m.name: m for m in crit.metrics if m.enabled}
    table = cfg("metrics", {}) or {}
    out = []
    for kind in KINDS:
        zs = []
        for name in table.get(kind, []) if isinstance(table, dict) else []:
            m, series = by_name.get(name), data.series.get(name) or {}
            if m is None or today not in series:
                continue
            base = baseline_of(m, series, today, crit)
            if base is None or base.early or base.n < floor:
                continue  # no established usual of her own yet: nothing to be "below"
            zs.append(worse_z(series[today], base, m.worse_when))
        if zs and max(zs) >= need and min(zs) > 0:
            out.append(kind)
    return out


def quieter_in(store: Store, home_id: str, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    if home_id not in store.home_ids():
        return []
    crit = service.active_criteria(store)
    return quieter(crit, service.patient_data(store, home_id, crit), now)
