from datetime import UTC, date, datetime, timedelta

import pytest
from kaiku_cloud.analytics import bandit, consensus
from kaiku_cloud.analytics.consensus import (
    compute,
    correlated_only,
    open_safety,
    raw_state,
    replay,
    worse_count,
)
from kaiku_cloud.analytics.data import build
from kaiku_cloud.analytics.drift import drift_for
from kaiku_cloud.analytics.verdict import VerdictResult, rule_fires, verdict_for
from kaiku_cloud.jobs.simulate import run_eval
from kaiku_cloud.jobs.synth import DEMO_PATIENTS, generate
from kaiku_cloud.llm import explain
from kaiku_cloud.llm.errors import LlmUnavailable
from kaiku_cloud.llm.template import template_explanation
from kaiku_cloud.settings import Settings
from kaiku_contracts.api import SourceVerdict, VerdictEvidence
from kaiku_contracts.criteria import Criteria, load_criteria
from kaiku_contracts.sources import CONSENSUS_SOURCES

CRIT = load_criteria()
END = date(2026, 11, 14)
NOW = datetime(2026, 11, 14, 21, 0, tzinfo=UTC)


def tuned(**changes) -> Criteria:
    """A copy of config/criteria.toml with dotted-path edits, e.g. tuned(**{"sources.robot.worse_min_weight": 9})."""
    data = CRIT.model_dump(mode="json", by_alias=True)
    for path, value in changes.items():
        *parents, leaf = path.split(".")
        node = data
        for k in parents:
            node = next(m for m in node if m["name"] == k) if isinstance(node, list) else node[k]
        node[leaf] = value
    return Criteria.model_validate(data)


def _pad(verdicts):
    """Scripted rows name robot, glasses, laptop; the optional wearable (no watch) is insufficient."""
    return (*verdicts, *["insufficient"] * (len(CONSENSUS_SOURCES) - len(verdicts)))


def V(source, verdict, families=()):
    model = SourceVerdict(home_id="h", source=source, verdict=verdict, confidence=0.9 if verdict != "insufficient" else 0.1,
                          evidence=[VerdictEvidence(metric="m", z=-2.0, direction="down", days=3)], computed_at=NOW)
    return VerdictResult(model, set(families))


# ---------------------------------------------------------------- criteria drive the metrics
def test_every_source_has_enabled_metrics_in_criteria():
    for s in CONSENSUS_SOURCES:
        assert CRIT.metrics_for(s), f"{s} has no enabled metrics in config/criteria.toml"


# ---------------------------------------------------------------- drift
def _series(stable_days=24, drift_days=6, base=40.0, drop=15.0):
    start = END - timedelta(days=stable_days + drift_days - 1)
    s = {}
    for i in range(stable_days + drift_days):
        wiggle = (i % 3 - 1) * 1.5
        s[start + timedelta(days=i)] = base + wiggle - (drop if i >= stable_days else 0)
    return s


def _metric(worse_when="down", **kw):
    from kaiku_contracts.criteria import MetricSpec

    return MetricSpec(name="x", label="X", obs="obs.hrv_session", field="rmssd_pre_ms", worse_when=worse_when,
                      min_mad=3.0, **kw)


def test_drift_detects_sustained_worse_change():
    d = drift_for(_metric(), _series(), END, CRIT)
    assert d.status == "drifting" and d.worse_days >= 3 and d.direction == "down"


def test_drift_improved_and_normal_and_insufficient():
    assert drift_for(_metric(), _series(drop=-15), END, CRIT).status == "improved"
    assert drift_for(_metric(), _series(drop=0), END, CRIT).status == "normal"
    short = dict(list(_series().items())[-5:])
    assert drift_for(_metric(), short, END, CRIT).status == "insufficient"


def test_drift_direction_aware_and_per_metric_override():
    assert drift_for(_metric("up"), _series(drop=10), END, CRIT).status == "improved"  # lower is fine if "up" is worse
    assert drift_for(_metric(z_threshold=50.0), _series(), END, CRIT).status == "normal"  # override wins over defaults


# ---------------------------------------------------------------- verdict per source
def _demo(home, crit=CRIT):
    spec = next(p for p in DEMO_PATIENTS if p.home_id == home)
    return spec, build(home, generate(spec, end=END), crit)


def _state(home, crit=CRIT):
    return compute(_demo(home, crit)[1], crit, END, NOW)[0]


def test_verdict_per_source_on_aino():
    _, data = _demo("demo-aino")
    got = {s: verdict_for(data, s, END, CRIT).model.verdict for s in CONSENSUS_SOURCES}
    assert got == {"robot": "worse", "glasses": "as_usual", "laptop": "worse", "wearable": "worse"}


def test_missing_source_is_insufficient_not_as_usual():
    _, data = _demo("sim-kaisa")
    v = verdict_for(data, "laptop", END, CRIT).model
    assert v.verdict == "insufficient" and v.confidence == 0.0


def test_rules_from_criteria_fire():
    _, data = _demo("demo-aino")
    fired = {r.name for r in CRIT.rules_for("laptop") if rule_fires(r, data, END, CRIT)}
    assert fired, "PHQ-9 rules in criteria.toml should fire for Aino"
    _, calm = _demo("sim-eero")
    assert not [r for r in CRIT.rules_for("laptop") if rule_fires(r, calm, END, CRIT)]


# ---------------------------------------------------------------- consensus rule
@pytest.mark.parametrize("verdicts,safety,state,agreement", [
    (("worse", "worse", "as_usual"), False, "needs_call", "disagree"),
    (("worse", "worse", "worse"), False, "needs_call", "agree"),
    (("worse", "as_usual", "as_usual"), False, "watch", "disagree"),
    (("as_usual", "as_usual", "better"), False, "stable", "agree"),
    (("better", "as_usual", "insufficient"), False, "stable", "agree"),
    (("as_usual", "insufficient", "insufficient"), False, "watch", "low_coverage"),
    (("insufficient", "insufficient", "insufficient"), False, "watch", "low_coverage"),  # never "stable"
    (("worse", "insufficient", "insufficient"), False, "watch", "low_coverage"),
    (("as_usual", "as_usual", "as_usual"), True, "safety", "agree"),
])
def test_raw_state_table(verdicts, safety, state, agreement):
    vs = [V(s, v) for s, v in zip(CONSENSUS_SOURCES, _pad(verdicts), strict=True)]
    assert raw_state(vs, safety, CRIT.state) == (state, agreement)


def _scripted(monkeypatch, plan: dict[int, tuple[str, str, str]], acks=()):
    """Replay with scripted verdicts per day index; returns final states per day."""
    _, data = _demo("sim-eero")
    data.acks = [(t, "Dr K") for t in acks]
    start = END - timedelta(days=len(plan) - 1)
    data.first_day = start

    def fake(_data, day, _crit, _now=None):
        return [V(s, v) for s, v in zip(CONSENSUS_SOURCES, _pad(plan[(day - start).days]), strict=True)]

    monkeypatch.setattr(consensus, "all_verdicts", fake)
    return [r.state for r in replay(data, CRIT, END, NOW)]


WW, OK = ("worse", "worse", "as_usual"), ("as_usual", "as_usual", "as_usual")
ONE = ("worse", "as_usual", "as_usual")


def test_hysteresis_holds_needs_call_until_three_stable_days(monkeypatch):
    plan = dict(enumerate([OK, WW, WW, OK, OK, OK, OK]))
    assert _scripted(monkeypatch, plan) == ["stable", "needs_call", "needs_call", "needs_call", "needs_call",
                                            "stable", "stable"]


def test_hysteresis_watch_does_not_release(monkeypatch):
    plan = dict(enumerate([WW, ONE, ONE, ONE, ONE]))
    assert _scripted(monkeypatch, plan) == ["needs_call"] * 5


def test_acknowledge_releases_held_needs_call(monkeypatch):
    start = END - timedelta(days=4)
    ack = datetime.combine(start + timedelta(days=1), datetime.min.time(), UTC) + timedelta(hours=12)
    plan = dict(enumerate([WW, WW, ONE, ONE, ONE]))
    assert _scripted(monkeypatch, plan, acks=[ack]) == ["needs_call", "needs_call", "watch", "watch", "watch"]


def test_open_safety_closed_by_acknowledge():
    _, data = _demo("sim-lauri")
    assert open_safety(data, NOW) is not None
    data.acks = [(NOW - timedelta(minutes=1), "Dr K")]
    assert open_safety(data, NOW) is None


def test_independence_caveat_and_count_as_one():
    sr = [V("robot", "worse", ["self_report"]), V("laptop", "worse", ["self_report"]), V("glasses", "as_usual")]
    mixed = [V("robot", "worse", ["physiology", "self_report"]), V("laptop", "worse", ["self_report"])]
    assert correlated_only(sr, CRIT.state) == ["self_report"]
    assert correlated_only(mixed, CRIT.state) == []
    assert worse_count(sr, CRIT.state) == 2
    one = tuned(**{"state.count_correlated_as_one": True})
    assert worse_count(sr, one.state) == 1 and worse_count(mixed, one.state) == 2
    assert raw_state(sr, False, CRIT.state)[0] == "needs_call"
    assert raw_state(sr, False, one.state)[0] == "watch"
    ctx = {"display_name": "X", "state": "needs_call", "agreement": "agree", "notes": ["correlated_only"],
           "correlated_families": ["self_report"],
           "sources": [r.model.model_dump(mode="json") for r in sr]}
    assert "not independent" in template_explanation(ctx).caveats


# ---------------------------------------------------------------- scenarios (the demo depends on these)
@pytest.mark.parametrize("spec", DEMO_PATIENTS, ids=lambda p: p.home_id)
def test_demo_patient_lands_in_intended_state(spec):
    c = _state(spec.home_id)
    assert c.state == spec.expected_state, [(v.source, v.verdict, [e.metric for e in v.evidence]) for v in c.sources]
    assert c.rule_version == CRIT.rule_version and c.rule_version.startswith("consensus-v1+")


def test_aino_disagreement_and_low_coverage_agreements():
    assert _state("demo-aino").agreement == "disagree"
    assert _state("sim-kaisa").agreement == "low_coverage"


# ---------------------------------------------------------------- tuning: criteria values alone change outcomes
def test_raising_worse_min_weight_turns_needs_call_into_watch():
    # Aino is worse on robot, laptop and watch: muting two of them leaves one worse source -> watch
    assert _state("demo-aino", tuned(**{"sources.robot.worse_min_weight": 99.0})).state == "needs_call"
    assert _state("demo-aino", tuned(**{"sources.robot.worse_min_weight": 99.0,
                                        "sources.wearable.worse_min_weight": 99.0})).state == "watch"


def test_disabling_a_source_removes_it_from_the_vote():
    c = _state("demo-aino", tuned(**{"sources.laptop.enabled": False, "sources.wearable.enabled": False}))
    assert c.state == "watch" and {v.source for v in c.sources} == {"robot", "glasses"}


def disabled(*, metrics=(), rules=()) -> Criteria:
    """config/criteria.toml with some [[metric]] / [[rule]] blocks set to enabled = false."""
    data = CRIT.model_dump(mode="json", by_alias=True)
    for block, names in (("metric", metrics), ("rule", rules)):
        for x in data[block]:
            if x["name"] in names:
                x["enabled"] = False
    return Criteria.model_validate(data)


def test_disabling_metrics_and_rules_changes_the_verdict():
    no_glasses_metrics = disabled(metrics=[m.name for m in CRIT.metrics_for("glasses")])
    glasses = next(v for v in _state("sim-mirja", no_glasses_metrics).sources if v.source == "glasses")
    assert glasses.verdict == "insufficient"  # glasses-only drift is no longer measurable
    no_rules = disabled(rules=[r.name for r in CRIT.rules])
    laptop = next(v for v in _state("demo-aino", no_rules).sources if v.source == "laptop")
    assert {e.metric for e in laptop.evidence}.isdisjoint(r.name for r in CRIT.rules)


def test_rule_version_changes_with_any_edit():
    assert tuned(**{"defaults.z_threshold": 2.0}).rule_version != CRIT.rule_version
    assert tuned(**{"defaults.z_threshold": 1.5}).rule_version == CRIT.rule_version


# ---------------------------------------------------------------- explanations
@pytest.mark.parametrize("spec", DEMO_PATIENTS, ids=lambda p: p.home_id)
def test_template_never_uses_banned_words(spec):
    from kaiku_cloud.service import explain_ctx

    data = build(spec.home_id, generate(spec, end=END), CRIT)
    c, last = compute(data, CRIT, END, NOW)
    ex = template_explanation(explain_ctx(spec.home_id, c, last.notes, True, last.correlated_families))
    assert explain.contains_banned(ex.model_dump_json()) is None
    assert ex.by == "template"


def _ctx():
    from kaiku_cloud.service import explain_ctx

    data = build("demo-aino", generate(DEMO_PATIENTS[0], end=END), CRIT)
    c, last = compute(data, CRIT, END, NOW)
    return explain_ctx("demo-aino", c, last.notes, True)


def test_llm_valid_json_is_used(monkeypatch):
    good = ('{"headline": "Aino: robot and laptop show change from usual", "text": "Two sources worse.", '
            '"per_source": [{"source": "robot", "summary": "Lower HRV."}], "disagreement_note": "Glasses as usual.", '
            '"suggested_actions": ["check_in_call"], "caveats": "Ordinary causes possible."}')
    monkeypatch.setitem(explain.BACKENDS, "gemma_hosted", lambda prompt: good)
    ex = explain.make_explanation(_ctx(), Settings(llm="gemma_hosted"))
    assert ex.by == "gemma" and ex.headline.startswith("Aino")


@pytest.mark.parametrize("reply", ['{"headline": "Relapse detected", "text": "x", "suggested_actions": ["none"], '
                                   '"caveats": "c"}', "not json at all"])
def test_llm_bad_output_falls_back_to_template(monkeypatch, reply):
    calls = []
    monkeypatch.setitem(explain.BACKENDS, "gemma_hosted", lambda prompt: calls.append(1) or reply)
    ex = explain.make_explanation(_ctx(), Settings(llm="gemma_hosted"))
    assert ex.by == "template" and len(calls) == 2  # retried once


def test_llm_unavailable_falls_back(monkeypatch):
    def down(prompt):
        raise LlmUnavailable("no gpu")

    monkeypatch.setitem(explain.BACKENDS, "gemma_modal", down)
    assert explain.make_explanation(_ctx(), Settings(llm="gemma_modal")).by == "template"


# ---------------------------------------------------------------- bandit
def test_bandit_reward_combines_immediate_and_next_day():
    imm = {"walk": 0.5}  # good immediate effect (→ 0.75 on 0..1)
    good = {"arm": "daylight_walk", "accepted": True, "next_day": {"mood": 5, "energy": 5}}
    bad = {"arm": "daylight_walk", "accepted": True, "next_day": {"mood": 1, "energy": 1}}
    assert bandit.reward_of(good, imm) > bandit.reward_of(bad, imm)
    assert bandit.reward_of({"arm": "drum", "accepted": False}) == 0.0
    # the hub's reward is next-day only: blended 50/50 with the immediate effect when one exists
    hub = {"arm": "daylight_walk", "accepted": True, "reward": 0.25}
    assert bandit.reward_of(hub) == 0.25
    assert bandit.reward_of(hub, imm) == 0.5
    assert 0 <= bandit.reward_of(good, imm) <= 1


def test_bandit_learns_favourite():
    import random

    outcomes = [{"arm": "drum", "accepted": True, "next_day": {"mood": 5, "energy": 5}}] * 12
    outcomes += [{"arm": "breathe", "accepted": False}] * 12
    probs = bandit.choose(outcomes, rng=random.Random(1), draws=4000)["probs"]
    assert max(probs, key=probs.get) == "drum"  # untried arms still get explored (Thompson)
    assert min(probs, key=probs.get) == "breathe"


# ---------------------------------------------------------------- simulation
def test_simulation_reports_states_and_ablation():
    from kaiku_cloud.jobs.synth import SCENARIOS

    n = len(SCENARIOS)  # one patient per scenario
    r = run_eval(n_patients=n, shards=1, criteria=CRIT)
    assert r.n_patients == n and r.sim is True and r.rule_version == CRIT.rule_version
    assert set(r.per_state) == {"stable", "watch", "needs_call", "safety"}
    assert set(r.ablation) == set(CONSENSUS_SOURCES)
    assert r.per_state["safety"].recall == 1.0
    # every source's ablation has needs_call cases to score (incl. a drift the robot doesn't see)
    assert all(sc.recall is not None for sc in r.ablation.values())


def test_eval_cohort_has_needs_call_without_robot_and_demo_is_unchanged():
    from kaiku_cloud.jobs.synth import DEMO_PATIENTS, cohort

    specs = cohort(20, seed=7)
    assert any(p.expected_state == "needs_call" and "robot" not in p.drift for p in specs)
    assert [p.home_id for p in DEMO_PATIENTS] == ["demo-aino", "sim-eero", "sim-juho", "sim-helmi", "sim-kaisa",
                                                  "sim-lauri", "sim-mirja", "sim-onni"]


def test_simulate_cli_compare_and_invalid(tmp_path, capsys):
    from kaiku_cloud.jobs.simulate import main

    path = tmp_path / "cand.toml"
    src = (__import__("kaiku_contracts.criteria", fromlist=["x"]).criteria_path()).read_text()
    path.write_text(src.replace("z_threshold = 1.5", "z_threshold = 2.5", 1))
    assert main(["--compare", str(path), "--n", "10"]) == 0
    out = capsys.readouterr().out
    assert "needs_call recall" in out and CRIT.rule_version in out
    bad = tmp_path / "bad.toml"
    bad.write_text(src.replace('worse_when = "down"', 'worse_when = "sideways"', 1))
    assert main(["--criteria", str(bad)]) == 2
