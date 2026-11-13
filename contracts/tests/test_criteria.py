import tomllib

import pytest
from kaiku_contracts.criteria import Criteria, criteria_path, load_criteria, parse_criteria
from pydantic import ValidationError


def _raw():
    return tomllib.loads(criteria_path().read_text())


def test_repo_criteria_file_is_valid():
    c = load_criteria()
    assert c.rule_version.startswith(c.name + "+")
    for s in ("robot", "glasses", "laptop", "wearable"):
        assert c.sources[s].enabled
        assert c.metrics_for(s), f"no enabled metrics for {s}"


def test_any_edit_changes_rule_version():
    a = parse_criteria(_raw())
    raw = _raw()
    raw["defaults"]["z_threshold"] = 1.6
    assert parse_criteria(raw).rule_version != a.rule_version


def test_per_metric_override_falls_back_to_defaults():
    c = load_criteria()
    m = c.metric("mood")
    assert c.param(m, "z_threshold") == c.defaults.z_threshold
    assert c.param(m, "min_mad") == 0.5


@pytest.mark.parametrize("patch,err", [
    (lambda r: r["metric"][0].update(field="nope"), "has no field"),
    (lambda r: r["metric"][0].update(obs="obs.ritual", field="duration_s", where={}), "feeds no consensus source"),
    (lambda r: r["metric"][0].update(where={"colour": "red"}), "unknown field"),
    (lambda r: r["metric"][0].update(worse_when="sideways"), "worse_when"),
    (lambda r: r["sources"].pop("glasses"), "must cover exactly"),
    (lambda r: r["defaults"].update(drift_days=9), "drift_days must be"),
    (lambda r: r["metric"].append(dict(r["metric"][0])), "duplicate"),
    (lambda r: r["rule"][0].update(field="items"), None),
])
def test_bad_criteria_rejected_with_a_readable_error(patch, err):
    raw = _raw()
    patch(raw)
    if err is None:  # items exists on obs.phq9, so this one is valid
        parse_criteria(raw)
        return
    with pytest.raises(ValidationError) as e:
        Criteria.model_validate(raw)
    assert err in str(e.value)


def test_serialises_with_toml_keys_even_when_nested():
    from kaiku_contracts.api import CriteriaResponse

    c = load_criteria()
    assert set(c.model_dump(mode="json")) >= {"metric", "rule"}
    r = CriteriaResponse(criteria=c, rule_version=c.rule_version, origin="file")
    assert "metric" in r.model_dump(mode="json")["criteria"]
