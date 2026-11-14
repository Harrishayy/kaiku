
from kaiku_cloud.jobs.synth import DEMO_PATIENTS, generate
from kaiku_cloud.llm.explain import contains_banned
from kaiku_contracts import example, make
from kaiku_contracts.api import EvalResult, StateScore

PATIENT = {p.home_id: p for p in DEMO_PATIENTS}


def env_json(type_, payload=None, home="t-home", source="hub", **kw):
    if payload is None:
        return example(type_, home_id=home).model_dump(mode="json", exclude_none=True)
    return make(type_, payload, source=source, home_id=home, **kw).model_dump(mode="json", exclude_none=True)


def seed(client, *homes, headers=None):
    for h in homes:
        ev = generate(PATIENT[h])
        for i in range(0, len(ev), 200):
            r = client.post("/v1/events", json={"events": ev[i:i + 200]}, headers=headers or {})
            assert r.status_code == 200 and not r.json()["rejected"], r.text


MOOD = {"item": "mood", "value": 3}


def test_healthz(client):
    r = client.get("/healthz").json()
    assert r["status"] == "ok" and r["db"] is True and r["schema_version"] == 1


def test_ingest_dedupe_and_rejections(client):
    e = env_json("obs.self_report", MOOD)
    assert client.post("/v1/events", json={"events": [e, e]}).json() == {"accepted": 1, "duplicates": 1, "rejected": []}
    raw, cmd = env_json("raw.head.tap"), env_json("cmd.head")
    bad = {**env_json("obs.self_report", MOOD), "payload": {"item": "mood", "value": 99}}
    old = {**env_json("obs.self_report", MOOD), "type": "obs.mood_dial", "payload": {"value": 3}}
    r = client.post("/v1/events", json={"events": [raw, cmd, bad, old]}).json()
    assert r["accepted"] == 0 and len(r["rejected"]) == 4
    assert "not uplinkable" in r["rejected"][0]["error"]
    assert client.post("/v1/events", json={"nope": 1}).status_code == 400


def test_pairing_token_required_for_every_source(make_client):
    c = make_client(home_token="secret", admin_token="adm", home_id="t-home")
    auth = {"Authorization": "Bearer secret"}
    for src, t, p in (("hub", "obs.self_report", MOOD),
                      ("laptop", "obs.laptop_session", None), ("glasses", "obs.outing", None)):
        e = env_json(t, p, source=src) if p else {**env_json(t), "source": src}
        assert c.post("/v1/events", json={"events": [e]}).status_code == 401, src  # no exemption any more
        assert c.post("/v1/events", json={"events": [e]}, headers=auth).json()["accepted"] == 1, src
    assert c.get("/v1/commands", params={"home_id": "t-home"}).status_code == 401
    assert c.get("/v1/commands", params={"home_id": "t-home"}, headers=auth).status_code == 200
    assert c.post("/v1/admin/recompute").status_code == 401
    assert c.post("/v1/admin/recompute", headers={"Authorization": "Bearer adm"}).status_code == 200
    rep = {"nodes": {}, "uplink_queue": 0, "reported_at": "2026-11-14T08:00:00Z"}
    assert c.put("/v1/health/t-home", json=rep).status_code == 401
    assert c.get("/v1/patients").status_code == 401
    assert c.get("/v1/patients", headers={"Authorization": "Bearer adm"}).status_code == 200


def test_auth_off_accepts_everything(client):
    assert client.post("/v1/events", json={"events": [env_json("obs.outing")]}).json()["accepted"] == 1


def test_patients_ranked_and_consensus_views(client):
    seed(client, "sim-eero", "demo-aino", "sim-helmi", "sim-kaisa")
    body = client.get("/v1/patients").json()
    assert body["rule_version"].startswith("consensus-v1+")
    pts = body["patients"]
    assert [p["id"] for p in pts] == ["demo-aino", "sim-helmi", "sim-kaisa", "sim-eero"]  # needs_call, watch…, stable
    aino = pts[0]
    assert aino["state"] == "needs_call" and aino["agreement"] == "disagree" and aino["sim"] is True
    assert {b["source"]: b["verdict"] for b in aino["sources"]} == {"robot": "worse", "glasses": "as_usual",
                                                                     "laptop": "worse", "wearable": "worse"}
    assert next(p for p in pts if p["id"] == "sim-kaisa")["agreement"] == "low_coverage"

    c = client.get("/v1/patients/demo-aino/consensus").json()
    assert c["state"] == "needs_call" and c["rule_version"] == body["rule_version"] and len(c["sources"]) == 4
    robot = next(s for s in c["sources"] if s["source"] == "robot")
    assert robot["evidence"] and robot["confidence"] > 0.4
    ex = c["explanation"]
    assert ex["by"] == "template" and ex["disagreement_note"] and ex["suggested_actions"][0] == "check_in_call"
    assert contains_banned(str(c)) is None
    assert client.get("/v1/patients/nobody/consensus").status_code == 404
    brief = client.get("/v1/patients/demo-aino/brief").json()  # plan 06 weekly brief (template until generated)
    assert brief["by"] == "template" and brief["state"] == "needs_call"

    # one enabled metric per source, taken from config/criteria.toml (no names hard-coded here)
    from kaiku_contracts.criteria import load_criteria

    crit = load_criteria()
    pick = {src: crit.metrics_for(src)[0] for src in ("robot", "glasses", "laptop", "wearable")}
    tl = client.get("/v1/patients/demo-aino/timeline",
                    params={"metrics": ",".join(m.name for m in pick.values())}).json()
    series = {s["metric"]: s for s in tl["series"]}
    assert set(series) == {m.name for m in pick.values()}
    for src, m in pick.items():
        assert series[m.name]["source"] == src and series[m.name]["worse_when"] == m.worse_when
        assert series[m.name]["label"] == m.label
    mood = series[pick["robot"].name]
    assert len(mood["points"]) == 30 and any(p["band_low"] is not None for p in mood["points"])
    full = client.get("/v1/patients/demo-aino/timeline").json()["series"]
    assert {s["source"] for s in full} == {"robot", "glasses", "laptop", "wearable"}

    phq = client.get("/v1/patients/demo-aino/phq9").json()
    assert len(phq["entries"]) == 4 and phq["entries"][-1]["total"] >= 10 and phq["next_due"]

    ev = client.get("/v1/events", params={"home_id": "demo-aino", "limit": 5}).json()["events"]
    assert len(ev) == 5 and ev[0]["ts"] >= ev[-1]["ts"]


def test_me_and_nudge(client):
    seed(client, "sim-eero")
    me = client.get("/v1/me", params={"home_id": "sim-eero"}).json()
    assert me["summary"].startswith("Your recent days") and me["what_helps"] and me["next_suggestion"]["arm"]
    assert me["sim"] is True and contains_banned(str(me)) is None
    empty = client.get("/v1/me", params={"home_id": "nobody-yet"}).json()
    assert empty["phq9_due"] is True  # works for a brand-new home
    n = client.get("/v1/nudge", params={"home_id": "sim-eero"}).json()
    assert n["arm"] in n["probs"] and abs(sum(n["probs"].values()) - 1) < 0.01


def test_safety_then_acknowledge(client):
    seed(client, "sim-eero")
    flag = env_json("obs.safety_flag", {"trigger": "phq9_item9", "handled_locally": True}, home="sim-eero",
                    source="laptop")
    assert client.post("/v1/events", json={"events": [flag]}).json()["accepted"] == 1
    p = next(p for p in client.get("/v1/patients").json()["patients"] if p["id"] == "sim-eero")
    assert p["state"] == "safety" and p["safety_since"]
    c = client.get("/v1/patients/sim-eero/consensus").json()
    assert c["explanation"]["suggested_actions"][0] == "check_in_call"
    r = client.post("/v1/patients/sim-eero/actions", json={"action": "acknowledge", "by": "Dr K"}).json()
    assert r["ok"] and r["state"] == "stable"


def test_needs_call_hysteresis_released_by_acknowledge(client):
    seed(client, "demo-aino")
    assert client.post("/v1/patients/demo-aino/actions", json={"action": "flag_booster"}).json()["state"] == "needs_call"
    r = client.post("/v1/patients/demo-aino/actions", json={"action": "acknowledge", "by": "Dr K"}).json()
    assert r["state"] == "needs_call"  # still two sources worse today
    c = client.get("/v1/patients/demo-aino/consensus").json()
    assert c["acknowledged_by"] == "Dr K"
    assert next(p for p in client.get("/v1/patients").json()["patients"] if p["id"] == "demo-aino")["acknowledged"]


def test_commands_message_and_phq9_due(client, monkeypatch):
    from kaiku_contracts.config import load_config

    seed(client, "sim-eero")
    client.post("/v1/patients/sim-eero/actions", json={"action": "send_message", "note": "Calling you at 2pm"})
    cmds = client.get("/v1/commands", params={"home_id": "sim-eero"}).json()["commands"]
    assert cmds[0]["type"] == "cmd.hub" and cmds[0]["payload"]["clinician_message"]["text"] == "Calling you at 2pm"
    assert client.get("/v1/commands", params={"home_id": "sim-eero"}).json()["commands"] == cmds
    for cmd in cmds:
        assert client.post(f"/v1/commands/{cmd['id']}/ack?home_id=sim-eero").status_code == 200
    assert client.get("/v1/commands", params={"home_id": "sim-eero"}).json()["commands"] == []

    # spoken PHQ-9 mode: a home whose last PHQ-9 is ≥ 14 days old gets exactly one cmd.hub {phq9_due}
    monkeypatch.setenv("KAIKU_RITUAL_PHQ9_MODE", "spoken")
    monkeypatch.setenv("KAIKU_RITUAL_PHQ9_EVERY_DAYS", "0")  # due immediately
    load_config.cache_clear()
    try:
        cmds = client.get("/v1/commands", params={"home_id": "sim-eero"}).json()["commands"]
        assert [c["payload"] for c in cmds] == [{"phq9_due": True}]
        for cmd in cmds:
            assert client.post(f"/v1/commands/{cmd['id']}/ack?home_id=sim-eero").status_code == 200
        assert client.get("/v1/commands", params={"home_id": "sim-eero"}).json()["commands"] == []
    finally:
        load_config.cache_clear()


def test_eval_and_health(make_client):
    from kaiku_contracts.criteria import load_criteria

    stub = EvalResult(n_patients=4, rule_version=load_criteria().rule_version, per_state={"stable": StateScore(precision=1, recall=1)},
                      false_needs_call_per_patient_month=0.0, median_lead_time_days=5.0,
                      ablation={"robot": StateScore(precision=0.5, recall=0.2)}, generated_at="2026-11-14T00:00:00Z")
    client = make_client(eval_runner=lambda criteria: stub)
    ev = client.get("/v1/eval").json()
    assert ev["n_patients"] == 4 and ev["sim"] is True and "robot" in ev["ablation"]
    rep = {"nodes": {"head": {"status": "ok", "version": "0.1.0", "uptime_s": 3.0}}, "uplink_queue": 2,
           "reported_at": "2026-11-14T08:00:00Z"}
    assert client.put("/v1/health/t-home", json=rep).json() == {"ok": True}
    assert client.get("/v1/health").json()["homes"]["t-home"]["uplink_queue"] == 2


def test_reset_deletes_only_sim(client):
    seed(client, "sim-onni")
    client.post("/v1/events", json={"events": [env_json("obs.self_report", MOOD, home="live-judge")]})
    assert client.post("/v1/admin/reset").json()["deleted"] > 0
    pts = client.get("/v1/patients").json()["patients"]
    assert [p["id"] for p in pts] == ["live-judge"]
    assert pts[0]["state"] == "watch" and pts[0]["agreement"] == "low_coverage"  # thin data is never "stable"


def test_static_web_served_but_api_wins(make_client, tmp_path):
    web = tmp_path / "out"
    (web / "clinician").mkdir(parents=True)
    (web / "index.html").write_text("<h1>home</h1>")
    (web / "clinician" / "index.html").write_text("<h1>clinician</h1>")
    c = make_client(web_dir=str(web))
    assert "home" in c.get("/").text
    assert "clinician" in c.get("/clinician/").text
    assert c.get("/healthz").json()["status"] == "ok"


# ---------------------------------------------------------------- live criteria tuning
def _crit_json(**edits):
    from kaiku_contracts.criteria import load_criteria

    data = load_criteria().model_dump(mode="json", by_alias=True)
    for path, value in edits.items():
        a, b, c = path.split(".")
        data[a][b][c] = value
    return data


def test_criteria_get_preview_apply_reset(client):
    seed(client, "demo-aino", "sim-eero")
    cur = client.get("/v1/admin/criteria").json()
    assert cur["origin"] == "file" and cur["rule_version"].startswith("consensus-v1+")
    cand = {"criteria": _crit_json(**{"sources.robot.worse_min_weight": 99.0,
                                      "sources.wearable.worse_min_weight": 99.0}), "by": "tuner"}

    pv = client.post("/v1/admin/criteria/preview", json=cand).json()
    assert pv["candidate_rule_version"] != pv["current_rule_version"]
    ch = {c["patient_id"]: c for c in pv["changes"]}
    assert ch["demo-aino"]["from_state"] == "needs_call" and ch["demo-aino"]["to_state"] == "watch"
    assert ch["demo-aino"]["to_sources"]["robot"] == "as_usual" and pv["unchanged"] == 1 and pv["eval"] is None
    assert client.get("/v1/admin/criteria").json()["origin"] == "file"  # preview saved nothing

    applied = client.put("/v1/admin/criteria", json=cand).json()
    assert applied["origin"] == "override" and applied["updated_by"] == "tuner"
    pts = {p["id"]: p for p in client.get("/v1/patients").json()["patients"]}
    assert pts["demo-aino"]["state"] == "watch"  # recomputed immediately, no restart
    assert client.get("/v1/patients").json()["rule_version"] == applied["rule_version"]

    reset = client.put("/v1/admin/criteria", json={"criteria": None}).json()
    assert reset["origin"] == "file" and reset["rule_version"] == cur["rule_version"]
    assert next(p for p in client.get("/v1/patients").json()["patients"] if p["id"] == "demo-aino")["state"] == "needs_call"


def test_criteria_preview_with_eval(client):
    seed(client, "sim-eero")
    pv = client.post("/v1/admin/criteria/preview", params={"eval": "1"}, json={"criteria": None}).json()
    assert pv["eval"]["n_patients"] > 0 and set(pv["eval"]["ablation"]) == {"robot", "glasses", "laptop", "wearable"}


def test_invalid_criteria_is_422(client):
    bad = _crit_json(**{"sources.robot.min_confidence": 7})
    r = client.put("/v1/admin/criteria", json={"criteria": bad})
    assert r.status_code == 422 and "min_confidence" in r.text
    data = _crit_json()
    data["metric"][0]["field"] = "no_such_field"
    r = client.post("/v1/admin/criteria/preview", json={"criteria": data})
    assert r.status_code == 422 and "no_such_field" in r.text
    assert client.get("/v1/admin/criteria").json()["origin"] == "file"


def test_criteria_admin_token(make_client):
    c = make_client(admin_token="adm")
    assert c.get("/v1/admin/criteria").status_code == 401
    assert c.get("/v1/admin/criteria", headers={"Authorization": "Bearer adm"}).status_code == 200
    assert c.put("/v1/admin/criteria", json={"criteria": None}).status_code == 401


def test_file_edit_is_picked_up_without_restart(make_client, tmp_path, monkeypatch):
    from kaiku_contracts.criteria import criteria_path

    src = criteria_path().read_text()
    f = tmp_path / "criteria.toml"
    f.write_text(src)
    monkeypatch.setenv("KAIKU_CRITERIA", str(f))
    c = make_client()
    v1 = c.get("/v1/admin/criteria").json()["rule_version"]
    import os
    import time

    f.write_text(src.replace("z_threshold = 1.5", "z_threshold = 1.7", 1))
    os.utime(f, (time.time() + 5, time.time() + 5))  # make sure the mtime moves
    assert c.get("/v1/admin/criteria").json()["rule_version"] != v1
