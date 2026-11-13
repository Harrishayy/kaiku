"""Consensus criteria: HOW each data input is used to decide a person's state. Tune in config/criteria.toml.

Everything that changes the outcome lives in that one file and is validated here:
  - [defaults]           baseline window, drift rule, noise floor, quality gate (per-metric overrides allowed)
  - [sources.<name>]     per-source vote: enabled, weight needed for "worse"/"better", expected data, min confidence
  - [state]              how source verdicts combine into stable / watch / needs_call (+ hysteresis, caveats)
  - [[metric]]           one entry per measured signal: obs type + field (+ filter), daily aggregation, which
                         direction is "worse", weight, enabled, and any per-metric thresholds
  - [[rule]]             direct triggers that make a source "worse" (e.g. PHQ-9 rise >= 5, PHQ-9 >= 10)

The consensus source of a metric is NOT configured here: it comes from the obs type via `sources.py`, so there is
exactly one place that says "outing counts toward glasses".

`Criteria.rule_version` = "<name>+<hash of the criteria>": any edit is visible on the dashboard and in /eval,
with no manual version bump to forget.
"""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import find_repo_file
from .registry import OBS
from .sources import CONSENSUS_SOURCES, SOURCE_OF

Agg = Literal["mean", "median", "min", "max", "sum", "first", "last", "count"]
# Derived fields (not in the payload): "@count" = number of observations that day,
# "@local_minutes" = minutes after local midnight of the envelope ts (e.g. get-up time from first presence).
# Nested payload fields use a dot: "category_min.communication" (obs.screen_activity).
DERIVED_FIELDS: frozenset[str] = frozenset({"@count", "@local_minutes"})


def field_exists(model: type[BaseModel], path: str) -> bool:
    """True if `path` ("a" or "a.b") names a field of `model` (one level of nesting into a sub-model)."""
    head, _, rest = path.partition(".")
    f = model.model_fields.get(head)
    if f is None:
        return False
    if not rest:
        return True
    sub = f.annotation
    return isinstance(sub, type) and issubclass(sub, BaseModel) and field_exists(sub, rest)
Scalar = str | int | float | bool


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Defaults(_M):
    timezone: str = "Europe/Helsinki"
    baseline_days: int = Field(14, ge=3, le=90, description="rolling median + MAD window")
    baseline_min_days: int = Field(7, ge=2, description="fewer days of data -> metric 'insufficient'")
    z_threshold: float = Field(1.5, gt=0, description="|robust z| in the worse direction")
    drift_days: int = Field(3, ge=1, description="drifting if beyond threshold on >= drift_days ...")
    drift_window: int = Field(5, ge=1, description="... of the last drift_window available days")
    min_mad: float = Field(0.0, ge=0, description="noise floor for MAD in metric units (avoids huge z on flat data)")
    quality_min: float = Field(0.5, ge=0, le=1, description="ignore readings with envelope.quality below this")
    baseline_lag_days: int = Field(7, ge=0, description="baseline ends this many days before today, so a slow "
                                   "drift doesn't drag its own baseline along")
    rule_max_age_days: int = Field(21, ge=1, description="[[rule]] observations older than this no longer fire")

    @model_validator(mode="after")
    def _window(self):
        if self.drift_days > self.drift_window:
            raise ValueError("drift_days must be <= drift_window")
        if self.baseline_min_days > self.baseline_days:
            raise ValueError("baseline_min_days must be <= baseline_days")
        return self


class SourceSpec(_M):
    enabled: bool = True
    worse_min_weight: float = Field(2.0, gt=0, description="sum of drifting-metric weights needed for 'worse'")
    better_min_weight: float = Field(2.0, gt=0, description="sum of improving-metric weights needed for 'better'")
    expected_per_week: float = Field(7, gt=0, description="days with data per week expected (confidence)")
    min_confidence: float = Field(0.4, ge=0, le=1, description="below -> 'insufficient' (excluded from the vote)")


class StateSpec(_M):
    needs_call_min_worse: int = Field(2, ge=1, description="sufficient sources 'worse' needed for needs_call")
    watch_min_worse: int = Field(1, ge=1, description="sufficient sources 'worse' needed for watch")
    watch_if_single_sufficient: bool = Field(True, description="only one source has enough data -> watch")
    min_sufficient_for_stable: int = Field(2, ge=1, description="fewer sufficient sources can never be 'stable'")
    hysteresis_stable_days: int = Field(3, ge=0, description="needs_call holds until acknowledged or N stable days")
    correlated_families: list[str] = Field(
        default_factory=lambda: ["self_report"],
        description="if every 'worse' source is worse only via one of these families, add the independence caveat",
    )
    count_correlated_as_one: bool = Field(
        False, description="if true, sources worse only via the same correlated family count as ONE worse source"
    )


class MetricSpec(_M):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    unit: str = ""
    family: str = Field("behaviour", description="e.g. self_report | physiology | behaviour | voice | cognition")
    obs: str = Field(description="obs type, e.g. obs.hrv_session")
    field: str = Field(description="payload field (nested with a dot, e.g. category_min.communication), "
                                   "or @count / @local_minutes")
    where: dict[str, Scalar | list[Scalar]] = Field(default_factory=dict, description="payload filters (equality / any-of)")
    agg: Agg = "mean"
    worse_when: Literal["up", "down"]
    weight: float = Field(1.0, ge=0, description="counts toward the source's worse/better weight")
    enabled: bool = True
    counts_for_better: bool = True
    missing: Literal["skip", "zero"] = Field("skip", description="days without data: ignore, or count as 0 (sum/count metrics)")
    # optional per-metric overrides of [defaults]
    z_threshold: float | None = Field(None, gt=0)
    drift_days: int | None = Field(None, ge=1)
    drift_window: int | None = Field(None, ge=1)
    baseline_days: int | None = Field(None, ge=3)
    baseline_min_days: int | None = Field(None, ge=2)
    min_mad: float | None = Field(None, ge=0)
    quality_min: float | None = Field(None, ge=0, le=1)
    note: str = ""
    person_hard: str = Field("", max_length=160, description="plain, gentle sentence shown to the PERSON on /me "
                             "('Your days') for a day this metric was beyond the usual in its worse direction; "
                             "empty = never shown. Wording rules: root AGENTS.md (no clinical words)")

    @model_validator(mode="after")
    def _check_against_contracts(self):
        if self.obs not in OBS:
            raise ValueError(f"metric {self.name}: unknown obs type {self.obs!r}")
        fields = OBS[self.obs].model_fields
        if not field_exists(OBS[self.obs], self.field) and self.field not in DERIVED_FIELDS:
            raise ValueError(f"metric {self.name}: {self.obs} has no field {self.field!r} "
                             f"(fields: {', '.join(fields)}; derived: {', '.join(sorted(DERIVED_FIELDS))})")
        bad = [k for k in self.where if k not in fields]
        if bad:
            raise ValueError(f"metric {self.name}: filter on unknown field(s) {bad}")
        if SOURCE_OF.get(self.obs) not in CONSENSUS_SOURCES:
            raise ValueError(f"metric {self.name}: {self.obs} feeds no consensus source "
                             f"({SOURCE_OF.get(self.obs)!r}); map it in sources.py first")
        if self.missing == "zero" and self.agg not in ("sum", "count"):
            raise ValueError(f"metric {self.name}: missing='zero' only makes sense with agg sum/count")
        return self

    @property
    def source(self) -> str:
        return SOURCE_OF[self.obs]


class RuleSpec(_M):
    """A direct trigger: when it fires, the metric's source counts as 'worse' regardless of baselines."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    family: str = "self_report"
    obs: str
    field: str
    kind: Literal["at_least", "at_most", "rise_vs_previous", "drop_vs_previous"] = Field(
        description="at_least: value >= threshold · at_most: value <= threshold · "
                    "rise/drop_vs_previous: change vs the previous observation >= threshold")
    threshold: float
    enabled: bool = True
    note: str = ""

    @model_validator(mode="after")
    def _check(self):
        if self.obs not in OBS or self.field not in OBS[self.obs].model_fields:
            raise ValueError(f"rule {self.name}: unknown obs/field {self.obs}.{self.field}")
        if SOURCE_OF.get(self.obs) not in CONSENSUS_SOURCES:
            raise ValueError(f"rule {self.name}: {self.obs} feeds no consensus source")
        return self

    @property
    def source(self) -> str:
        return SOURCE_OF[self.obs]


class Criteria(_M):
    name: str = "consensus-v1"
    defaults: Defaults = Field(default_factory=Defaults)
    sources: dict[str, SourceSpec]
    state: StateSpec = Field(default_factory=StateSpec)
    metrics: list[MetricSpec] = Field(alias="metric", default_factory=list)
    rules: list[RuleSpec] = Field(alias="rule", default_factory=list)

    # always (de)serialise as `metric` / `rule` — the same keys as config/criteria.toml and the TS types
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    @field_validator("sources")
    @classmethod
    def _known_sources(cls, v: dict[str, SourceSpec]) -> dict[str, SourceSpec]:
        unknown = set(v) - set(CONSENSUS_SOURCES)
        missing = set(CONSENSUS_SOURCES) - set(v)
        if unknown or missing:
            raise ValueError(f"[sources.*] must cover exactly {list(CONSENSUS_SOURCES)} "
                             f"(unknown: {sorted(unknown)}, missing: {sorted(missing)})")
        return v

    @model_validator(mode="after")
    def _unique(self):
        names = [m.name for m in self.metrics] + [r.name for r in self.rules]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate metric/rule names: {sorted(dupes)}")
        return self

    # ------------------------------------------------------------------ helpers
    def param(self, metric: MetricSpec, key: str) -> Any:
        """Per-metric override if set, else [defaults]."""
        v = getattr(metric, key, None)
        return v if v is not None else getattr(self.defaults, key)

    def metrics_for(self, source: str, *, enabled_only: bool = True) -> list[MetricSpec]:
        return [m for m in self.metrics if m.source == source and (m.enabled or not enabled_only)]

    def rules_for(self, source: str, *, enabled_only: bool = True) -> list[RuleSpec]:
        return [r for r in self.rules if r.source == source and (r.enabled or not enabled_only)]

    def active_sources(self) -> list[str]:
        return [s for s in CONSENSUS_SOURCES if self.sources[s].enabled]

    def metric(self, name: str) -> MetricSpec:
        return next(m for m in self.metrics if m.name == name)

    @property
    def fingerprint(self) -> str:
        canon = json.dumps(self.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon.encode()).hexdigest()[:8]

    @property
    def rule_version(self) -> str:
        return f"{self.name}+{self.fingerprint}"


def parse_criteria(data: dict[str, Any] | str) -> Criteria:
    """From a dict (JSON body) or TOML text. Raises pydantic.ValidationError with a readable message."""
    if isinstance(data, str):
        data = tomllib.loads(data)
    return Criteria.model_validate(data)


def criteria_path() -> Path | None:
    env = os.environ.get("KAIKU_CRITERIA")
    return Path(env) if env else find_repo_file("config/criteria.toml")


def load_criteria(path: str | os.PathLike[str] | None = None) -> Criteria:
    """Load + validate config/criteria.toml (or $KAIKU_CRITERIA, or `path`)."""
    p = Path(path) if path else criteria_path()
    if p is None or not p.is_file():
        raise FileNotFoundError("config/criteria.toml not found (set KAIKU_CRITERIA)")
    return parse_criteria(p.read_text())
