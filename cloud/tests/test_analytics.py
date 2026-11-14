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
    # scripted days test the state rule itself; the young-record guard has its own tests below
    return [r.state for r in replay(data, tuned(**{"state.min_history_days_for_stable": 0}), END, NOW)]


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
    good = '{"source_order": ["robot", "laptop", "wearable", "glasses"], "focus_metrics": []}'
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


def test_explanation_uses_verified_directions_and_group_labels_only():
    ctx = _ctx()
    for source in ctx["sources"]:
        source["evidence"] = [{"metric": "hr", "direction": "up", "days": 3, "z": 2.0,
                               "summary": "Resting heart rate higher than usual on three recent days"}] if source["source"] == "robot" else []
    ctx["sources"][0]["verdict"] = "worse"
    raw = '{"source_order": ["robot", "laptop", "wearable", "glasses"], "focus_metrics": ["hr"], "text": "Heart rate is lower and glasses are connected."}'
    ex = explain._from_llm(raw, ctx, "gemma_hosted")
    text = ex.model_dump_json()
    assert "higher than usual" in text and "Heart rate is lower" not in text and "glasses are connected" not in text
    assert "Check-ins & robot" in text and "Walks & outings" in text


# ---------------------------------------------------------------- calibration (make calibrate; docs/validation.md)
def _daily(n, value_of):
    start = END - timedelta(days=n - 1)
    return {start + timedelta(days=i): float(value_of(i)) for i in range(n)}


def _young_person(n=16, dip=range(8, 12)):
    """A 16-day record: three daily robot signals + two daily app signals, lower on the dip days."""
    from kaiku_cloud.analytics.data import PatientData

    robot = ("mood", "energy", "sleep")
    series = {m: _daily(n, lambda i: 2 if i in dip else 4) for m in robot}
    series["active_min"] = _daily(n, lambda i: 150 if i in dip else 320 + (i % 3) * 5)
    series["communication_min"] = _daily(n, lambda i: 20 if i in dip else 70 + (i % 2) * 3)
    days = {d: [0.95] for d in series["mood"]}
    return PatientData(home_id="young", series=series, source_days={s: (dict(days) if s in ("robot", "laptop") else {})
                                                                     for s in CONSENSUS_SOURCES},
                       last_data_at={}, rule_readings={}, safety_flags=[], acks=[], last_activity_at=None, sim=True,
                       first_day=min(days))


def test_young_record_is_never_stable_and_a_dip_is_scored_with_an_early_baseline_label():
    res = replay(_young_person(), CRIT, END, NOW)
    states = [r.state for r in res]
    assert len(res) == 16 and "stable" not in states
    assert all(r.agreement == "low_coverage" for r in res[:8])  # days 1–8: nothing to compare with yet
    assert states[:10] == ["watch"] * 10  # day 9–10: two low days are not yet a pattern (3 of 5)
    assert states[10] == "needs_call"  # day 11: third low day, two groups agree
    worse = [v for v in res[10].verdicts if v.verdict == "worse"]
    assert {v.source for v in worse} == {"robot", "laptop"}
    assert all("early baseline" in e.summary and "lower confidence" in e.summary for v in worse for e in v.evidence)
    fine = replay(_young_person(dip=()), CRIT, END, NOW)
    assert {r.state for r in fine} == {"watch"} and fine[-1].agreement == "low_coverage"
    assert not any(v.verdict == "worse" for r in fine for v in r.verdicts)
    # the same record, three weeks old, may be stable; and the provisional baseline is gone
    old = replay(_young_person(n=30, dip=()), CRIT, END, NOW)
    assert old[-1].state == "stable" and [r.state for r in old[:20]] == ["watch"] * 20


def test_early_baseline_can_be_switched_off_in_criteria():
    off = tuned(**{"defaults.early_baseline_min_days": 0})
    res = replay(_young_person(), off, END, NOW)
    assert all(v.verdict == "insufficient" for v in res[10].verdicts) and "stable" not in {r.state for r in res}
    with pytest.raises(ValueError):
        tuned(**{"defaults.early_baseline_min_days": 9})  # must not exceed baseline_min_days


def test_new_metric_blocks_never_break_or_bias_a_verdict():
    """A games/robot agent adds [[metric]] blocks: without data they change nothing; with weight 0 they are
    observe-only (no vote, and cannot make a source look sufficient on their own)."""
    _, data = _demo("demo-aino")
    before = {v.model.source: v.model.verdict for v in (verdict_for(data, s, END, CRIT, NOW) for s in CONSENSUS_SOURCES)}
    raw = CRIT.model_dump(mode="json", by_alias=True)
    raw["metric"].append({"name": "pebbles_span", "label": "Memory span", "obs": "obs.play_session", "field": "span_max",
                          "where": {"game": "pebbles"}, "worse_when": "down", "weight": 0.5, "family": "cognition"})
    grown = Criteria.model_validate(raw)
    assert grown.rule_version != CRIT.rule_version
    after = {s: verdict_for(data, s, END, grown, NOW).model.verdict for s in CONSENSUS_SOURCES}
    assert after == before  # no data for the new signal -> insufficient metric -> no effect
    # observe-only: a source whose only data is a weight-0 signal stays insufficient even when it drifts
    raw["metric"][-1]["weight"] = 0
    observe = Criteria.model_validate(raw)
    from kaiku_cloud.analytics.data import PatientData

    span = _daily(30, lambda i: 2 if i >= 24 else 5)
    lone = PatientData(home_id="h", series={"pebbles_span": span},
                       source_days={s: ({d: [1.0] for d in span} if s == "laptop" else {}) for s in CONSENSUS_SOURCES},
                       last_data_at={}, rule_readings={}, safety_flags=[], acks=[], last_activity_at=None, sim=True,
                       first_day=min(span))
    assert drift_for(observe.metric("pebbles_span"), span, END, observe).status == "drifting"
    v = verdict_for(lone, "laptop", END, observe, NOW).model
    assert v.verdict == "insufficient" and v.evidence == []
    raw["metric"][-1]["weight"] = 1.0  # once it has a weight it votes like any other signal
    assert verdict_for(lone, "laptop", END, Criteria.model_validate(raw), NOW).model.verdict == "worse"


def test_calibration_regression_thresholds():
    """Loose bounds around the numbers in docs/validation.md (n=40 there, n=16 here): a rule or criteria change
    that makes the rule much noisier, much blinder, or lets thin data read as stable fails here."""
    from kaiku_cloud.analytics import calibration as cal

    r = cal.run_calibration(CRIT, n=16, effects=("moderate",))
    h = r["headline"]
    assert r["sim"] is True and r["rule_version"] == CRIT.rule_version
    assert h["false_flags_per_person_week_fine"] <= 0.15  # measured 0.08: about one false flag per 3 person-months
    assert max(c["false_calls_per_person_week"] for c in r["fine"]) <= 0.03
    assert h["sensitivity_flag_moderate"] >= 0.85 and h["sensitivity_call_moderate"] >= 0.55
    assert h["sensitivity_flag_moderate"] > h["chance_flag_in_detect_window"] + 0.5
    by = {c["trajectory"]: c for c in r["unwell"]}
    assert by["sudden drop, stays low"]["delay_flag_days"] <= 4
    assert by["gradual decline (14-day slide)"]["delay_flag_days"] <= 11
    # a new person: nothing before day 9, never "stable" within 16 days, yet a dip on days 9–12 is usually seen
    early = r["early_days"]
    for label in ("fine", "dip days 9–12 (moderate)"):
        seen = early[label]["practitioner_sees_on_day"]
        assert set(seen["3"]) == set(seen["7"]) == {"not enough data"}
        assert not any("stable" in day for day in seen.values())
    assert early["fine"]["ever_flagged"] <= 0.15 and early["dip days 9–12 (moderate)"]["ever_flagged"] >= 0.4
    assert early["first_day_any_source_can_vote"] <= 12
    short = {c["trajectory"]: c for c in r["short_history"]}
    assert set(short["16 days, fine"]["final_state"]) == {"watch"}
    # no single robot/app/watch signal may flip its group; the walks group is the documented exception
    assert {s: m for s, m in r["single_metric_flippers"].items() if m} == {"glasses": ["outing_min"]}
    # the learner's known confound stays visible: two no-effect activities do not score the same
    assert r["bandit_no_effect_arms"]["drum"] > r["bandit_no_effect_arms"]["breathe"]


def test_calibration_cli(capsys, tmp_path):
    from kaiku_cloud.analytics.calibration import main

    assert main(["--n", "3"]) == 0
    out = capsys.readouterr().out
    assert "not clinical accuracy" in out and "New person" in out and CRIT.rule_version in out
    bad = tmp_path / "bad.toml"
    bad.write_text("name = 1")
    assert main(["--criteria", str(bad)]) == 2


@pytest.mark.parametrize("tail", [(2, 2, 2, 3, 3), (2, 2, 2, 4, 4), (2, 2, 2, 5, 5)])
def test_evidence_direction_z_and_wording_come_from_the_days_that_voted(tail):
    """Whole-number dials, constant usual 4 (zero spread -> min_mad floor), three low days, then partly/fully
    back: the group is still worse (3 of 5), and its evidence must say LOWER with a negative z — never
    "higher ... z=0" because the latest day happens to sit at or above the usual."""
    from kaiku_cloud.analytics.data import PatientData

    n = 16
    series = {m: _daily(n, lambda i: tail[i - (n - 5)] if i >= n - 5 else 4) for m in ("mood", "energy", "sleep")}
    days = {d: [0.95] for d in series["mood"]}
    data = PatientData(home_id="h", series=series, source_days={s: (days if s == "robot" else {}) for s in CONSENSUS_SOURCES},
                       last_data_at={}, rule_readings={}, safety_flags=[], acks=[], last_activity_at=None, sim=True,
                       first_day=min(days))
    v = verdict_for(data, "robot", END, CRIT, NOW).model
    assert v.verdict == "worse" and len(v.evidence) == 3
    for e in v.evidence:
        assert e.direction == "down" and e.z is not None and e.z <= -CRIT.defaults.z_threshold and e.days >= 3
        assert " lower than usual on " in e.summary and "higher" not in e.summary
    d = drift_for(CRIT.metric("mood"), series["mood"], END, CRIT)
    assert d.status == "drifting" and d.flag_direction == "down" and d.z_flag >= CRIT.defaults.z_threshold
    # improving mirrors it: direction and z from the better days
    up = {day: 6 - val for day, val in series["mood"].items()}  # usual 2, three days at 4
    imp = drift_for(CRIT.metric("mood"), up, END, CRIT)
    assert imp.status == "improved" and imp.flag_direction == "up" and imp.z_flag <= -CRIT.defaults.z_threshold
