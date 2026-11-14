"""Plan 06 edge cases: ask_mind routing + grounding, conflicts, prompt hygiene, crisis, usage ledger, graph memory,
Embedding-2 vs FTS recall, constellation, postcards, weekly brief, nightly mind.

Every model call is mocked at the SDK client (`gemini._client`), so the real adapters (budget guard, ledger) run but
nothing leaves the machine; the spend ledger points at a temp file. No key needed, never a real call.
"""

import json
import re
import zlib
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from kaiku_cloud.analytics import bandit
from kaiku_cloud.api.main import create_app
from kaiku_cloud.jobs.synth import DEMO_PATIENTS, generate
from kaiku_cloud.llm import gemini, gemma_hosted, ledger
from kaiku_cloud.mind import graph, router
from kaiku_cloud.settings import Settings
from kaiku_contracts import make
from kaiku_contracts.config import load_config

FLASH, ARGON = gemini.model_for("fast"), gemini.model_for("flagship")
EMBED, IMAGE = gemini.embedding_model(), gemini.image_model()


def bow(text: str, dim: int = 768) -> list[float]:
    """Deterministic bag-of-words vector (stand-in for Gemini Embedding 2)."""
    v = np.zeros(dim, dtype=np.float32)
    body = text.split("query: ", 1)[-1].split("text: ", 1)[-1]
    for w in re.findall(r"\w+", body.lower()):
        if len(w) > 2:
            v[zlib.crc32(w[:5].encode()) % dim] += 1.0
    n = float(np.linalg.norm(v)) or 1.0
    return list(v / n)


class Fake:
    """Fake google-genai client. `replies[model]` = str | Exception | callable(prompt) -> str."""

    def __init__(self):
        self.replies: dict[str, object] = {}
        self.calls: list[dict] = []
        self.interactions = SimpleNamespace(create=self._create)
        self.models = SimpleNamespace(embed_content=self._embed)

    def _create(self, **kw):
        self.calls.append(kw)
        r = self.replies.get(kw["model"], RuntimeError("no reply configured"))
        if isinstance(r, Exception):
            raise r
        if kw["model"] == IMAGE:
            return SimpleNamespace(output_image=SimpleNamespace(data="iVBORw0KGgo=", mime_type="image/png"))
        text = r(kw["input"]) if callable(r) else r
        return SimpleNamespace(output_text=text)

    def _embed(self, model, contents, config=None):
        self.calls.append({"model": model, "input": contents})
        return SimpleNamespace(embeddings=[SimpleNamespace(values=bow(contents))])

    def models_called(self):
        """Text/image models asked (embedding calls for recall are left out)."""
        return [c["model"] for c in self.calls if c["model"] != EMBED]


@pytest.fixture(autouse=True)
def _spend(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIKU_SPEND_DB", str(tmp_path / "spend.sqlite"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("KAIKU_MIND_PRIMARY", "gemini")  # these tests exercise the Gemini fallback chain
    load_config.cache_clear()
    yield
    load_config.cache_clear()  # config env overrides set by a test must not leak


def setcfg(monkeypatch, name, value):
    """KAIKU_<SECTION>_<KEY> override (load_config is cached, so clear it)."""
    monkeypatch.setenv(name, value)
    load_config.cache_clear()


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(gemini, "_client", lambda key, timeout_s: f)
    monkeypatch.setattr(gemma_hosted, "generate", lambda *a, **kw: json.dumps({"diffs": []}))
    return f


@pytest.fixture
def app(tmp_path):
    a = create_app(Settings(demo_mode=True, db_path=str(tmp_path / "t.sqlite"), web_dir=None))
    return a


@pytest.fixture
def c(app):
    return TestClient(app)


def remember(c, text, category="people", home="h1"):
    r = c.post("/v1/companion/tool", json={"home_id": home, "surface": "iphone", "name": "remember",
                                           "args": {"category": category, "text": text}})
    assert r.json()["ok"], r.text
    return r.json()["result"]["id"]


def ask(c, question, kind, home="h1"):
    r = c.post("/v1/companion/tool", json={"home_id": home, "surface": "robot", "name": "ask_mind",
                                           "args": {"question": question, "kind": kind}})
    assert r.status_code == 200, r.text
    return r.json()


def reply(answer, confidence=0.9, cites=None):
    return json.dumps({"answer": answer, "confidence": confidence, "cites": cites or []})


def aino(c):
    return {"sister": remember(c, "Her sister is Maija"),
            "lake": remember(c, "Likes walking by the lake", "places"),
            "tea": remember(c, "A cup of tea on the balcony helps", "what_helps")}


def rows(app):
    return app.state.store.model_calls("")


# ------------------------------------------------------------------ routing
def test_ask_mind_is_a_cloud_tool_on_every_surface(c):
    from kaiku_contracts.companion_tools import SURFACES, TOOLS, for_surface

    assert TOOLS["ask_mind"]["executor"] == "cloud"
    assert all("ask_mind" in {t["name"] for t in for_surface(s)} for s in SURFACES)
    bad = c.post("/v1/companion/tool", json={"home_id": "h1", "surface": "robot", "name": "ask_mind",
                                             "args": {"question": "hi", "kind": "gossip"}}).json()
    assert not bad["ok"] and "kind" in bad["error"]


def test_memory_hit_answers_without_a_model(app, c, fake):
    ids = aino(c)
    fake.calls.clear()
    res = ask(c, "What's my sister's name?", "memory")["result"]
    assert res["route"] == "memory" and "Maija" in res["answer"] and res["cites"] == [f"mem:{ids['sister']}"]
    assert fake.calls == []  # no text model or query embedding for an exact local notebook hit
    outcome = [r for r in rows(app) if r["task"] == "ask_mind.route"]
    assert [(r["model"], r["route"]) for r in outcome] == [("deterministic", "memory")]


def test_stateless_interactions_disable_provider_conversation_storage(fake, monkeypatch):
    from kaiku_contracts import genai_client

    monkeypatch.setattr(genai_client, "backend", lambda: "developer")
    monkeypatch.setattr(genai_client, "available", lambda: True)
    fake.replies[FLASH] = "Synthetic answer"
    fake.replies[IMAGE] = "image"
    assert gemini.generate("synthetic input") == "Synthetic answer"
    assert gemini.image("synthetic illustration")[0]
    assert len(fake.calls) == 2 and all(c["store"] is False for c in fake.calls)


def test_low_flash_confidence_escalates_to_argon(app, c, fake):
    ids = aino(c)
    fake.replies[FLASH] = reply(f"Maybe the lake [mem:{ids['lake']}]", 0.3)
    fake.replies[ARGON] = reply(f"The lake walk and tea both sound good [mem:{ids['lake']}] [mem:{ids['tea']}].", 0.9)
    res = ask(c, "Tell me about the lake and tea", "fact")["result"]
    assert res["route"] == "argon" and res["model"] == ARGON
    assert "[" not in res["answer"] and set(res["cites"]) == {f"mem:{ids['lake']}", f"mem:{ids['tea']}"}
    assert fake.models_called() == [FLASH, ARGON]


def test_confident_flash_stays_on_flash(c, fake):
    ids = aino(c)
    fake.replies[FLASH] = reply(f"You like the lake [mem:{ids['lake']}] and tea [mem:{ids['tea']}].", 0.8)
    res = ask(c, "Tell me about the lake and tea", "fact")["result"]
    assert res["route"] == "flash" and ARGON not in fake.models_called()


def test_care_kind_goes_to_argon_first(c, fake):
    fake.replies[ARGON] = reply("Extra sessions are something to talk about with your care team [doc:booster].", 0.9)
    res = ask(c, "Could I get extra sessions later?", "care")["result"]
    assert res["route"] == "argon" and res["cites"] == ["doc:booster"]
    assert fake.models_called()[0] == ARGON and FLASH not in fake.models_called()


def test_argon_over_budget_uses_flash_only(c, fake, monkeypatch):
    setcfg(monkeypatch, "KAIKU_BUDGET_ARGON_PER_HOME_DAY", "0")
    fake.replies[ARGON] = reply("should never be asked [doc:booster]", 0.9)
    fake.replies[FLASH] = reply("That's one for your care team [doc:booster].", 0.5)
    res = ask(c, "Could I get extra sessions later?", "care")["result"]
    assert res["route"] == "flash" and ARGON not in fake.models_called()


def test_argon_budget_counts_per_home_per_day(app, c, fake, monkeypatch):
    setcfg(monkeypatch, "KAIKU_BUDGET_ARGON_PER_HOME_DAY", "2")
    fake.replies[ARGON] = reply("Your care team can tell you [doc:booster].", 0.9)
    fake.replies[FLASH] = reply("Ask your care team [doc:booster].", 0.9)
    routes = [ask(c, "Could I get extra sessions later?", "care")["result"]["route"] for _ in range(3)]
    assert routes == ["argon", "argon", "flash"]
    assert ask(c, "Could I get extra sessions later?", "care", home="h2")["result"]["route"] == "argon"


def test_both_models_down_gives_the_scripted_line(app, c, fake):
    aino(c)
    res = ask(c, "Tell me about the lake and tea", "fact")["result"]  # no replies configured: both raise
    assert res["route"] == "fallback" and res["answer"] == router.SCRIPTED["fact"] and res["confidence"] == 0
    care = ask(c, "Who do I ask about my medicines?", "care")["result"]
    assert care["route"] == "fallback" and care["cites"] == ["doc:care_team"]  # best approved passage, verbatim


def test_no_key_at_all_is_scripted_and_free(app, c):
    res = ask(c, "How are you today?", "emotional")["result"]
    assert res["route"] == "fallback" and res["answer"] == router.SCRIPTED["emotional"]
    assert [r["model"] for r in rows(app)] == ["scripted"]


# ------------------------------------------------------------------ grounding
ALLOWED = {"mem:1", "doc:booster"}


def test_grounding_rejects_a_fake_id():
    with pytest.raises(router.Rejected, match="unverifiable"):
        router.validate(reply("Her sister is Maija [mem:999]", cites=["mem:999"]), "memory", ALLOWED, [], "flash", "m")


def test_grounding_rejects_a_missing_cite():
    with pytest.raises(router.Rejected, match="missing cite"):
        router.validate(reply("Her sister is Maija."), "memory", ALLOWED, [], "flash", "m")
    # emotional answers may be uncited (nothing factual)
    assert router.validate(reply("I'm here with you."), "emotional", ALLOWED, [], "flash", "m").answer


def test_grounding_keeps_and_strips_a_real_id():
    a = router.validate(reply("Her sister is Maija [mem:1].", cites=["mem:1"]), "memory", ALLOWED, [], "argon", "m")
    assert a.answer == "Her sister is Maija." and a.cites == ["mem:1"]


@pytest.mark.parametrize("text", ["Your score looks lower this week [mem:1].", "Your heart rate was calmer [mem:1].",
                                  "Take a smaller dose tonight [mem:1].", "Everything will be fine [mem:1]."])
def test_grounding_rejects_unsafe_wording(text):
    with pytest.raises(router.Rejected, match="wording"):
        router.validate(reply(text, cites=["mem:1"]), "fact", ALLOWED, [], "flash", "m")


def test_unverifiable_model_answer_falls_back(c, fake):
    aino(c)
    fake.replies[FLASH] = reply("Your sister Anna visits on Sundays [mem:777].", 0.9)
    fake.replies[ARGON] = reply("Anna visits [kg:4242].", 0.9)
    res = ask(c, "Tell me about the lake and tea", "fact")["result"]
    assert res["route"] == "fallback" and "Anna" not in res["answer"]


# ------------------------------------------------------------------ conflicting memories
def test_conflicting_memories_escalate_and_ask_never_pick(c, fake):
    a, b = remember(c, "Her sister is Maija"), remember(c, "Her sister is Mia")
    fake.replies[ARGON] = reply(f"Your sister is Maija [mem:{a}].", 0.95)  # picks one -> rejected
    fake.replies[FLASH] = reply(f"It's Mia [mem:{b}].", 0.95)
    res = ask(c, "What's my sister called?", "memory")["result"]
    assert fake.models_called()[0] == ARGON  # conflict -> Argon first, no deterministic answer
    assert res["route"] == "fallback" and res["ask_person"] is True and res["answer"] == router.CONFLICT_LINE
    assert set(res["cites"]) == {f"mem:{a}", f"mem:{b}"}


def test_conflict_answer_that_asks_with_both_notes_is_kept(c, fake):
    a, b = remember(c, "Her sister is Maija"), remember(c, "Her sister is Mia")
    fake.replies[ARGON] = reply(f"I have Maija [mem:{a}] and Mia [mem:{b}] written down. Which is right?", 0.7)
    res = ask(c, "What's my sister called?", "memory")["result"]
    assert res["route"] == "argon" and res["ask_person"] is True and res["answer"].endswith("?")


def test_same_sister_twice_is_not_a_conflict(c, fake):
    remember(c, "Her sister is Maija")
    remember(c, "Her sister Maija lives in Turku")
    res = ask(c, "What's my sister called?", "memory")["result"]
    assert res["ask_person"] is False


# ------------------------------------------------------------------ prompt hygiene (property over seeded patients)
@pytest.fixture(scope="module")
def cohort(tmp_path_factory):
    s = Settings(demo_mode=True, db_path=str(tmp_path_factory.mktemp("router") / "t.sqlite"), web_dir=None)
    a = create_app(s)
    cl = TestClient(a)
    for p in DEMO_PATIENTS:
        ev = generate(p)
        for i in range(0, len(ev), 400):
            assert cl.post("/v1/events", json={"events": ev[i:i + 400]}).status_code == 200
    return a, cl


STATE_OR_WEARABLE = re.compile(r"needs_call|needs a call|\bstable\b|\bwatch\b|consensus|verdict|phq|\bhrv\b|rmssd|"
                               r"resting_hr|sleep|steps|heart|score|baseline|wearable|low_coverage|safety|worse", re.I)


def test_prompts_never_contain_state_numbers_or_wearable_data(cohort, fake, monkeypatch):
    a, cl = cohort
    from kaiku_cloud.llm import ledger as led

    led.bind(a.state.store)
    prompts: list[str] = []

    def capture(prompt):
        prompts.append(prompt)
        return reply("I'm not sure.", 0.1)

    fake.replies[FLASH] = capture
    fake.replies[ARGON] = capture
    questions = [("Tell me about the lake and my friend", "fact"), ("How am I doing lately?", "emotional"),
                 ("What did I do today and yesterday?", "fact"), ("Could I get extra sessions later?", "care"),
                 ("What are we doing this weekend?", "plan")]
    for p in DEMO_PATIENTS:
        home = p.home_id
        for text, cat in [("Likes walking by the lake", "places"), ("Her friend Eeva calls on Sundays", "people"),
                          ("Walks 5 km with the dog at 7", "places")]:
            cl.post("/v1/companion/tool", json={"home_id": home, "surface": "iphone", "name": "remember",
                                                "args": {"category": cat, "text": text}})
        for q, kind in questions:
            cl.post("/v1/companion/tool", json={"home_id": home, "surface": "robot", "name": "ask_mind",
                                                "args": {"question": q, "kind": kind}})
    assert prompts, "the models were never asked"
    sent = [c["input"] for c in fake.calls if c["model"] in (FLASH, ARGON)]
    assert len(sent) >= len(DEMO_PATIENTS) * 3
    for s in sent:
        for f in json.loads(s)["facts"]:
            assert not re.search(r"\d", f["text"]), f
            assert not STATE_OR_WEARABLE.search(f["text"]), f
        body = re.sub(r"(?:mem|kg|doc):[\w-]+", "", s)
        assert not re.search(r"\d", body), body
        assert not re.search(r"needs_call|stable|consensus|phq|rmssd|resting_hr|low_coverage", body, re.I), body


# ------------------------------------------------------------------ crisis
def test_crisis_phrase_inside_ask_mind(app, c, fake):
    res = ask(c, "I want to die, what's the point", "emotional")
    assert res["crisis"] is True and res["result"]["stop_session"] and "112" in res["result"]["script"]
    assert fake.calls == []  # no model saw it
    flags = app.state.store.events_for_home("h1", ["obs.safety_flag"])
    assert len(flags) == 1 and not [r for r in rows(app) if r["task"].startswith("ask_mind")]


# ------------------------------------------------------------------ usage ledger
def test_ledger_counts_are_exact_and_contentless(app, c, fake):
    ids = aino(c)
    fake.replies[FLASH] = reply(f"Maybe the lake [mem:{ids['lake']}]", 0.2)
    fake.replies[ARGON] = reply(f"The lake [mem:{ids['lake']}] and tea [mem:{ids['tea']}].", 0.9)
    ask(c, "What's my sister's name?", "memory")    # deterministic
    ask(c, "Tell me about the lake and tea", "fact")  # flash -> argon
    fake.replies.pop(ARGON)
    fake.replies[FLASH] = RuntimeError("down")
    ask(c, "Tell me about the lake and tea", "fact")  # flash fails, argon fails -> scripted
    h = c.get("/v1/health/intelligence?days=1").json()
    assert h["routes"] == {"memory": 1, "argon": 1, "fallback": 1}
    per_model = dict(h["per_model"])
    assert per_model.pop(EMBED) >= 3  # memory vectors on write + query vectors (key set)
    assert per_model == {"deterministic": 1, FLASH: 2, ARGON: 2, "scripted": 1}
    by = {(r["model"], r["task"]): r for r in h["rows"]}
    assert by[(FLASH, "ask_mind")]["calls"] == 2 and by[(FLASH, "ask_mind")]["ok"] == 1
    assert by[(ARGON, "ask_mind")]["ok"] == 1 and by[("scripted", "ask_mind.route")]["fallbacks"] == 1
    assert h["fallback_rate"] == round(1 / h["calls"], 3) and h["p50_ms"] is not None
    cols = set(app.state.store.model_calls("")[0])
    assert cols == {"seq", "ts", "home_id", "model", "task", "route", "latency_ms", "ok", "fallback"}


def test_spend_cap_reached_means_fallback_not_error(c, fake, monkeypatch):
    monkeypatch.setenv("KAIKU_BUDGET_TOTAL_USD", "0")
    fake.replies[ARGON] = reply("x [doc:booster]", 0.9)
    res = ask(c, "Could I get extra sessions later?", "care")["result"]
    assert res["route"] == "fallback" and fake.calls == []


# ------------------------------------------------------------------ graph + recall
def test_fts_fallback_finds_the_same_top_hit_as_embeddings(app, c, fake, monkeypatch):
    ids = aino(c)
    store = app.state.store
    graph.index(store, "h1")
    assert {f"mem:{i}" for i in ids.values()} <= set(store.embeddings("h1", EMBED))
    vec = graph.recall(store, "h1", "walking by the lake")
    assert vec[0]["via"] == "vector" and vec[0]["ref"] == f"mem:{ids['lake']}"
    monkeypatch.delenv("GEMINI_API_KEY")  # vectors stored but no key: FTS
    fts = graph.recall(store, "h1", "walking by the lake")
    assert fts[0]["via"] == "fts" and fts[0]["ref"] == vec[0]["ref"]


def test_recall_expands_one_hop_to_the_activity(app, c):
    ids = aino(c)
    hits = graph.recall(app.state.store, "h1", "lake", k=3)
    assert hits[0]["ref"] == f"mem:{ids['lake']}"
    hop = [h for h in hits if h["via"] == "hop"]
    assert hop and hop[0]["text"] == "walks"


def test_memory_write_embeds_when_a_key_exists(app, c, fake):
    mid = remember(c, "Loves the smell of rain", "likes")
    assert f"mem:{mid}" in app.state.store.embeddings("h1", EMBED)
    c.delete(f"/v1/me/memories/{mid}?home_id=h1")
    assert f"mem:{mid}" not in app.state.store.embeddings("h1", EMBED)


def test_helped_edge_weight_comes_from_the_bandit(app, c):
    store = app.state.store
    evs = [make("obs.nudge_outcome", {"arm": "drum", "accepted": True, "reward": r}, source="hub", home_id="h1")
           .model_dump(mode="json", exclude_none=True) for r in (1.0, 0.8, 0.9)]
    evs.append(make("obs.nudge_outcome", {"arm": "breathe", "accepted": True, "reward": 0.1}, source="hub",
                    home_id="h1").model_dump(mode="json", exclude_none=True))
    assert c.post("/v1/events", json={"events": evs}).json()["accepted"] == 4
    graph.rebuild(store, "h1")
    from kaiku_cloud import service

    data = service.patient_data(store, "h1", service.active_criteria(store))
    want = {h["activity"]: h["mean_effect"] for h in bandit.help_stats(data.nudge_outcomes, data.interventions)}
    w = graph.helped_weights(store, "h1")
    assert w == {"drum": round(want["drum"], 3)}  # breathe (0.1) didn't help -> no edge
    edge = next(e for e in store.kg_edges("h1") if e["rel"] == "helped")
    assert set(edge["evidence"]) == {e["id"] for e in evs[:3]}


def test_constellation_has_no_health_phq_or_state(cohort):
    a, cl = cohort
    home = "demo-aino"
    for text, cat in [("Her sister is Maija", "people"), ("Likes walking by the lake", "places"),
                      ("A cup of tea on the balcony helps", "what_helps")]:
        cl.post("/v1/companion/tool", json={"home_id": home, "surface": "iphone", "name": "remember",
                                            "args": {"category": cat, "text": text}})
    refused = cl.post("/v1/companion/tool", json={"home_id": home, "surface": "iphone", "name": "remember",
                                                  "args": {"category": "likes", "text": "My meds help me sleep"}})
    assert not refused.json()["ok"]
    body = cl.get(f"/v1/me/constellation?home_id={home}").json()
    labels = " ".join(n["label"] for n in body["nodes"])
    assert {"Her sister is Maija", "Likes walking by the lake"} <= {n["label"] for n in body["nodes"]}
    assert "Maija" in labels
    text = json.dumps(body).lower()
    for bad in ("phq", "needs_call", "stable", "consensus", "hrv", "rmssd", "sleep", "heart", "score", "meds",
                "evidence", "icbt", "verdict"):
        assert bad not in text, bad
    assert {n["type"] for n in body["nodes"]} <= {"me", "person", "place", "like", "helper", "plan", "activity"}


def test_consolidation_diffs_are_validated(app, c, fake):
    remember(c, "Likes walking by the lake", "places")
    remember(c, "walking by the lake", "places")
    remember(c, "Her sister is Maija")
    store = app.state.store
    graph.rebuild(store, "h1")
    nodes = {n["norm"]: n["id"] for n in store.kg_nodes("h1")}
    fake.replies[ARGON] = json.dumps({"diffs": [
        {"op": "merge", "keep": "kg:9999", "drop": f"kg:{nodes['her sister is maija']}"},     # unknown id
        {"op": "merge", "keep": f"kg:{nodes['her sister is maija']}", "drop": f"kg:{nodes['walking by the lake']}"},
        {"op": "expire", "node": f"kg:{nodes['her sister is maija']}"},                         # not a plan
        {"op": "delete_everything"}]})
    out = c.post("/v1/admin/nightly-mind?home_id=h1").json()
    cons = out["homes"]["h1"]["consolidation"]
    assert cons["diffs"] == [{"op": "merge", "keep": f"kg:{nodes['likes walking by the lake']}",
                              "drop": f"kg:{nodes['walking by the lake']}"}]  # only the rule's same-type merge
    assert "skipped" in out["judge"] and out["homes"]["h1"]["prerender"] == 0
    assert len(c.get("/v1/me/memories?home_id=h1").json()["memories"]) == 3  # memories untouched
    recalled = [h["text"] for h in graph.recall(store, "h1", "walking lake", k=5)]
    assert "walking by the lake" not in recalled


# ------------------------------------------------------------------ postcard
def test_postcard_without_key_is_503_with_hint(c):
    r = c.post("/v1/companion/postcard", json={"home_id": "h1", "minutes": 20, "finds": ["green"],
                                               "weather_word": "sunny"})
    assert r.status_code == 503 and "static" in r.json()["hint"]


def test_postcard_is_generated_once_cached_and_served(app, c, fake, tmp_path, monkeypatch):
    setcfg(monkeypatch, "KAIKU_MIND_POSTCARD_DIR", str(tmp_path / "pc"))
    fake.replies[IMAGE] = "image"
    body = {"home_id": "h1", "minutes": 20, "finds": ["green", "bird", "I want to die", "Kill myself"],
            "weather_word": "sunny"}
    first = c.post("/v1/companion/postcard", json=body).json()
    second = c.post("/v1/companion/postcard", json=body).json()
    assert first["cached"] is False and second["cached"] is True and first["id"] == second["id"]
    prompt = next(x["input"] for x in fake.calls if x["model"] == IMAGE)
    assert "green, bird" in prompt and "die" not in prompt and "no faces" in prompt and not re.search(r"\d", prompt)
    img = c.get(first["url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert c.get("/v1/me/postcards/notanid").status_code == 404


def test_postcard_daily_cap(c, fake, tmp_path, monkeypatch):
    setcfg(monkeypatch, "KAIKU_MIND_POSTCARD_DIR", str(tmp_path / "pc"))
    setcfg(monkeypatch, "KAIKU_BUDGET_IMAGES_PER_HOME_DAY", "1")
    fake.replies[IMAGE] = "image"
    assert c.post("/v1/companion/postcard", json={"home_id": "h1", "minutes": 5}).status_code == 200
    r = c.post("/v1/companion/postcard", json={"home_id": "h1", "minutes": 50})
    assert r.status_code == 503 and "limit" in r.json()["reason"]


# ------------------------------------------------------------------ weekly brief
def test_weekly_brief_grounded_in_metric_ids_else_template(cohort, fake):
    a, cl = cohort
    ledger.bind(a.state.store)
    cons = cl.get("/v1/patients/demo-aino/consensus").json()
    metric = next(e["metric"] for s in cons["sources"] for e in s["evidence"])
    fake.replies[ARGON] = json.dumps({"sections": [{"text": "Diagnosis: relapse.", "metrics": [metric]}]})
    cl.post("/v1/admin/weekly?home_id=demo-aino")
    assert cl.get("/v1/patients/demo-aino/brief").json()["by"] == "template"
    fake.replies[ARGON] = json.dumps({"sections": [{"text": "Change from usual worth a check-in.",
                                                    "metrics": ["made_up_metric"]}]})
    cl.post("/v1/admin/weekly?home_id=demo-aino")
    assert cl.get("/v1/patients/demo-aino/brief").json()["by"] == "template"
    fake.replies[ARGON] = json.dumps({"sections": [
        {"text": "Several sources show a change from their usual; worth a check-in.", "metrics": [metric]}]})
    cl.post("/v1/admin/weekly?home_id=demo-aino")
    b = cl.get("/v1/patients/demo-aino/brief").json()
    assert b["by"] == "model" and b["sections"][0]["metrics"] == [metric] and b["state"] == cons["state"]
