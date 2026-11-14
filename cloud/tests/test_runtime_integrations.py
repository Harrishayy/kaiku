"""Production routes, actual envelopes and durable SQLite: isolation, offline retries and time passing."""
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from kaiku_cloud import service
from kaiku_cloud.api.main import create_app
from kaiku_cloud.jobs.synth import DEMO_PATIENTS, generate
from kaiku_cloud.mind import live_token
from kaiku_cloud.settings import Settings
from kaiku_contracts import budget, make


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def event(home="a", ts=None):
    return make("obs.self_report", {"item": "mood", "value": 3, "context": "adhoc"},
                source="phone", home_id=home, **({"ts": ts} if ts else {})).model_dump(mode="json")


def episode(home="a", eid="offline-1", outcome="completed"):
    return {"id": eid, "home_id": home, "surface": "iphone", "intent": "talk",
            "start": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(), "outcome": outcome,
            "transcript": [{"role": "person", "text": "I enjoyed the park."},
                           {"role": "kaiku", "text": "That sounds peaceful."}]}


def test_deployment_closed_and_credentials_override_demo(make_client):
    c = make_client(demo_mode=False)
    assert c.get("/healthz").status_code == 200
    for path in ("/v1/me?home_id=a", "/v1/patients", "/v1/health", "/v1/admin/criteria"):
        assert c.get(path).status_code == 401
    c = make_client(demo_mode=True, home_tokens={"a": "alpha"})
    assert c.get("/v1/me?home_id=a").status_code == 401
    assert c.get("/v1/me?home_id=a", headers=auth("alpha")).status_code == 200


@pytest.mark.parametrize("settings,mode", [
    ({"demo_mode": True}, "demo"),
    ({"demo_mode": False}, "unconfigured"),
    ({"demo_mode": True, "home_tokens": {"private-home": "private-token"}}, "authenticated"),
    ({"demo_mode": True, "clinician_token": "private-care-token"}, "authenticated"),
])
def test_public_discovery_never_exposes_or_weakens_authorization(make_client, settings, mode):
    c = make_client(**settings)
    response = c.get("/v1/discovery")
    assert response.status_code == 200
    assert response.json() == {"service": "kaiku-api", "schema_version": 1, "mode": mode,
                               "auth_required": mode != "demo",
                               "capabilities": ["companion_voice", "observations", "monitoring"]}
    assert "private" not in response.text
    if mode != "demo":
        assert c.get("/v1/me?home_id=new-installation").status_code == 401
        assert c.post("/v1/companion/session", json={"home_id": "new-installation", "surface": "iphone"}).status_code == 401


def test_demo_fresh_installation_bootstraps_without_robot_or_seed(make_client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    c = make_client()
    home = "installation-6fab9abc-c7bf-4720-afdc-54f6f2ee9b7f"
    assert c.app.state.store.home_ids() == []
    response = c.post("/v1/companion/session", json={"home_id": home, "surface": "iphone"})
    assert response.status_code == 200
    body = response.json()
    assert body["live_token"] is None  # Discovery does not bypass provider readiness/budget gates.
    assert body["max_session_seconds"] > 0
    assert c.app.state.store.episode(body["session_id"])["home_id"] == home
    assert c.post("/v1/events", json={"events": [event(home)]}).json()["accepted"] == 1
    assert c.get(f"/v1/me?home_id={home}").status_code == 200


def test_atomic_home_scope_and_care_roles(make_client):
    c = make_client(home_tokens={"a": "alpha", "b": "beta"}, clinician_token="care", admin_token="admin")
    a, b = event(), event("b")
    assert c.post("/v1/events", json={"events": [a, b]}, headers=auth("alpha")).status_code == 403
    assert c.app.state.store.events_for_home("a") == []
    assert c.post("/v1/events", json={"events": [a]}, headers=auth("alpha")).json()["accepted"] == 1
    assert c.post("/v1/events", json={"events": [a]}, headers=auth("alpha")).json()["duplicates"] == 1
    for token in ("beta", "care", "admin"):
        for path in ("/v1/me?home_id=a", "/v1/me/memories?home_id=a", "/v1/me/transcripts?home_id=a",
                     "/v1/me/graph?home_id=a", "/v1/me/sharing?home_id=a"):
            assert c.get(path, headers=auth(token)).status_code == 403
        assert c.delete("/v1/me/transcripts?home_id=a", headers=auth(token)).status_code == 403
    assert c.get("/v1/events", headers=auth("alpha")).status_code == 403
    assert c.get("/v1/patients", headers=auth("alpha")).status_code == 403
    assert c.get("/v1/patients", headers=auth("care")).status_code == 200
    assert c.post("/v1/admin/recompute", headers=auth("care")).status_code == 403
    assert c.post("/v1/patients/a/actions", headers=auth("alpha"), json={"action": "acknowledge"}).status_code == 403
    assert c.post("/v1/patients/a/actions", headers=auth("care"), json={"action": "acknowledge"}).status_code == 200


def test_command_delivery_survives_lost_response_and_restart(tmp_path):
    settings = Settings(db_path=str(tmp_path / "db.sqlite"), web_dir=None, home_tokens={"a": "alpha", "b": "beta"},
                        clinician_token="care")
    c = TestClient(create_app(settings))
    c.post("/v1/events", headers=auth("alpha"), json={"events": [event()]})
    c.post("/v1/patients/a/actions", headers=auth("care"), json={"action": "send_message", "note": "Please call us."})
    first = c.get("/v1/commands?home_id=a", headers=auth("alpha")).json()["commands"]
    restarted = TestClient(create_app(settings))
    assert restarted.get("/v1/commands?home_id=a&since=2099-01-01", headers=auth("alpha")).json()["commands"] == first
    cid = first[0]["id"]
    assert restarted.post(f"/v1/commands/{cid}/ack?home_id=b", headers=auth("beta")).status_code == 404
    assert restarted.post(f"/v1/commands/{cid}/ack?home_id=a", headers=auth("alpha")).json() == {"ok": True, "id": cid}
    assert restarted.post(f"/v1/commands/{cid}/ack?home_id=a", headers=auth("alpha")).status_code == 200
    assert restarted.get("/v1/commands?home_id=a", headers=auth("alpha")).json()["commands"] == []


def test_crisis_and_deletion_are_monotonic_across_offline_retry_and_restart(tmp_path):
    settings = Settings(db_path=str(tmp_path / "db.sqlite"), web_dir=None, home_tokens={"a": "alpha"})
    c = TestClient(create_app(settings))
    headers = auth("alpha")
    initial = episode()
    assert c.post("/v1/companion/episode", headers=headers, json=initial).json()["transcript_stored"]
    crisis = {**initial, "outcome": "crisis"}
    assert not c.post("/v1/companion/episode", headers=headers, json=crisis).json()["transcript_stored"]
    c = TestClient(create_app(settings))
    assert not c.post("/v1/companion/episode", headers=headers, json=initial).json()["transcript_stored"]
    assert c.app.state.store.episode(initial["id"])["outcome"] == "crisis"
    second = episode(eid="offline-2")
    assert c.post("/v1/companion/episode", headers=headers, json=second).json()["transcript_stored"]
    c.delete("/v1/me/transcripts/offline-2?home_id=a", headers=headers)
    assert not c.post("/v1/companion/episode", headers=headers, json=second).json()["transcript_stored"]
    third = episode(eid="offline-3")
    c.post("/v1/companion/episode", headers=headers, json=third)
    c.delete("/v1/me/transcripts?home_id=a", headers=headers)
    assert not c.post("/v1/companion/episode", headers=headers, json=third).json()["transcript_stored"]
    assert c.get("/v1/me/transcripts?home_id=a", headers=headers).json()["transcripts"] == []


def test_tool_and_reconnect_cannot_cross_home_or_surface(make_client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    c = make_client(home_tokens={"a": "alpha", "b": "beta"})
    body = {"home_id": "a", "surface": "iphone"}
    session = c.post("/v1/companion/session", json=body, headers=auth("alpha")).json()
    assert session["max_session_seconds"] == 300
    sid = session["session_id"]
    resumed = c.post("/v1/companion/session", json={**body, "resume_session_id": sid}, headers=auth("alpha")).json()
    assert resumed["session_id"] == sid and len(c.app.state.store.episodes("a")) == 1
    for home, surface, token in (("b", "iphone", "beta"), ("a", "web", "alpha")):
        req = {"home_id": home, "surface": surface, "resume_session_id": sid}
        assert c.post("/v1/companion/session", json=req, headers=auth(token)).status_code == 422
        tool = {"home_id": home, "surface": surface, "session_id": sid, "name": "end_session",
                "args": {"outcome": "completed"}}
        assert c.post("/v1/companion/tool", json=tool, headers=auth(token)).json()["ok"] is False
    ep = c.app.state.store.episode(sid)
    c.app.state.store.episode_upsert({**ep, "end": datetime.now(UTC).isoformat(), "outcome": "completed"})
    assert c.post("/v1/companion/session", json={**body, "resume_session_id": sid}, headers=auth("alpha")).status_code == 422


def test_stale_data_recomputed_on_read_and_offline_ingest_cannot_refresh_it(client, monkeypatch):
    patient = next(p for p in DEMO_PATIENTS if p.home_id == "sim-eero")
    rows = generate(patient)
    for i in range(0, len(rows), 500):
        assert client.post("/v1/events", json={"events": rows[i:i + 500]}).status_code == 200
    current = client.get("/v1/patients/sim-eero/consensus").json()
    assert current["state"] == "stable"
    future = service.today_local() + timedelta(days=10)
    monkeypatch.setattr(service, "today_local", lambda: future)
    stale = client.get("/v1/patients/sim-eero/consensus").json()
    assert stale["state"] != "stable" and all(s["verdict"] == "insufficient" for s in stale["sources"])
    retry = client.post("/v1/events", json={"events": rows[:1]}).json()
    assert retry["duplicates"] == 1
    assert client.get("/v1/patients/sim-eero/consensus").json()["state"] != "stable"


def test_adhoc_phone_envelope_reaches_monitored_metric(client):
    e = event()
    assert client.post("/v1/events", json={"events": [e]}).json()["accepted"] == 1
    data = service.patient_data(client.app.state.store, "a", service.active_criteria(client.app.state.store))
    assert 3.0 in data.series["mood"].values()


def test_live_admission_budget_and_usage_are_real_boundaries(client, tmp_path, monkeypatch):
    monkeypatch.setenv("KAIKU_SPEND_DB", str(tmp_path / "spend.sqlite"))
    monkeypatch.setenv("KAIKU_BUDGET_TOTAL_USD", "0.6")
    monkeypatch.setenv("KAIKU_BUDGET_DAILY_USD", "0.6")
    requests = []
    def provider(request):
        requests.append(request)
        return httpx.Response(200, json={"name": "ephemeral-test-token"})
    transport = httpx.MockTransport(provider)
    assert live_token.mint("gemini-3.8-live", api_key="test", transport=transport, home_id="a")
    assert live_token.mint("gemini-3.8-live", api_key="test", transport=transport, home_id="a") is None
    assert len(requests) == 1 and budget.spent() == pytest.approx(budget.estimate("gemini-3.8-live", audio_min=5))
    usage = client.get("/v1/health/intelligence").json()
    rows = [r for r in usage["rows"] if r["task"] == "live_reservation"]
    assert rows[0]["calls"] == 2 and rows[0]["ok"] == 1


def test_failed_live_mint_reserves_before_provider_and_cannot_retry_over_cap(client, tmp_path, monkeypatch):
    monkeypatch.setenv("KAIKU_SPEND_DB", str(tmp_path / "spend.sqlite"))
    estimate = budget.estimate("gemini-3.8-live", audio_min=5)
    monkeypatch.setenv("KAIKU_BUDGET_TOTAL_USD", str(estimate))
    monkeypatch.setenv("KAIKU_BUDGET_DAILY_USD", str(estimate))
    attempts = []

    def provider(request):
        attempts.append(request)
        assert budget.spent() == pytest.approx(estimate)
        return httpx.Response(500)

    transport = httpx.MockTransport(provider)
    for _ in range(2):
        assert live_token.mint("gemini-3.8-live", api_key="test", transport=transport, home_id="a") is None
    assert len(attempts) == 1 and budget.spent() == pytest.approx(estimate)


def test_daily_watch_snapshots_keep_target_day_and_latest_capture_even_out_of_order(client):
    today = service.today_local()
    target = today - timedelta(days=1)
    snapshots = []
    for hour, steps in ((12, 2000), (8, 500)):
        snapshots.append(make("obs.wearable_daily", {"date": target.isoformat(), "device": "apple_watch", "steps": steps},
                              source="phone", home_id="a", ts=datetime.combine(today, datetime.min.time(), UTC)
                              + timedelta(hours=hour)).model_dump(mode="json"))
    for snapshot in snapshots:
        assert client.post("/v1/events", json={"events": [snapshot]}).json()["accepted"] == 1
    data = service.patient_data(client.app.state.store, "a", service.active_criteria(client.app.state.store))
    steps = next(m.name for m in service.active_criteria(client.app.state.store).metrics
                 if m.obs == "obs.wearable_daily" and m.field == "steps")
    assert data.series[steps] == {target: 2000.0}
    assert set(data.source_days["wearable"]) == {target}


def test_future_dated_source_never_advances_consensus(client):
    later = datetime.now(UTC) + timedelta(days=30)
    assert client.post("/v1/events", json={"events": [event(ts=later)]}).json()["accepted"] == 1
    consensus = client.get("/v1/patients/a/consensus").json()
    assert consensus["state"] == "watch" and consensus["agreement"] == "low_coverage"
    assert all(v["verdict"] == "insufficient" for v in consensus["sources"])


def test_robot_bootstrap_does_not_reserve_app_token(client, monkeypatch):
    from kaiku_cloud.mind import session
    calls = []
    req = session.CompanionSessionRequest(home_id="a", surface="robot")
    result = session.start_session(client.app.state.store, client.app.state.settings, req,
                                   mint=lambda *a, **kw: calls.append(kw))
    assert result.live_token is None and result.max_session_seconds == 300 and calls == []


def test_success_waits_for_durable_commit_and_failed_commit_is_retryable(make_client):
    commits = []
    def commit():
        commits.append(True)
    c = make_client(after_write=commit)
    e = event()
    assert c.post("/v1/events", json={"events": [e]}).status_code == 200
    assert commits == [True]
    def unavailable():
        raise OSError("volume offline")
    failed = make_client(after_write=unavailable)
    assert failed.post("/v1/events", json={"events": [event()]}).status_code == 503


def test_explanation_cache_ignores_arrival_time_and_cools_down_failures(make_client, monkeypatch):
    from kaiku_cloud.llm.template import template_explanation
    c = make_client(llm="gemma_hosted")
    calls = []
    def unavailable(context, *args):
        calls.append(context)
        return template_explanation(context)
    monkeypatch.setattr(service, "make_explanation", unavailable)
    c.post("/v1/events", json={"events": [event()]})
    path = "/v1/patients/a/consensus"
    assert c.get(path).status_code == 200
    c.post("/v1/events", json={"events": [event()]})
    assert c.get(path).status_code == 200 and len(calls) == 1
    row = c.app.state.store.home_summary("a")
    row["consensus"]["sources"][0]["confidence"] = .4
    c.app.state.store.save_home_summary("a", row["summary"]["state"], row)
    assert c.get(path).status_code == 200 and len(calls) == 1
    cached_hash, cached_ex = c.app.state.store.get_explanation("a")
    cached_ex["generated_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    c.app.state.store.save_explanation("a", cached_hash, cached_ex)
    assert c.get(path).status_code == 200 and len(calls) == 2


def test_readiness_rejects_invalid_stale_criteria(client):
    client.app.state.store.kv_set(service.OVERRIDE_KEY, {"criteria": {"unknown_old_schema": True}})
    response = client.get("/healthz")
    assert response.status_code == 503 and response.json()["status"] == "degraded"
    assert "unknown_old_schema" not in response.text
    client.app.state.store.kv_delete(service.OVERRIDE_KEY)
    assert client.get("/healthz").status_code == 200
