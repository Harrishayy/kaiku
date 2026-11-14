"""Graph memory (plan 06 §3): a small knowledge graph built BY CODE, plus recall over memories and nodes.

Built (idempotent, `rebuild`) from:
- confirmed memories: category -> node type (people -> person, places -> place, likes -> like,
  what_helps -> helper, plans -> plan); edge me -rel-> node with evidence [mem:<id>]. `name` labels the me node;
  `preference` stays out of the graph.
- episodes: completed sessions -> activity nodes, edge me -did-> activity (weight = share of recent sessions,
  evidence = episode ids).
- bandit outcomes: activity with mean reward > 0.5 -> edge me -helped-> activity, weight = the bandit's mean effect,
  evidence = the obs event ids it rests on. (iCBT is care, not a constellation activity: left out.)
- memory nodes that mention an activity link to it (`about`), so recall can expand one hop.
Consolidation diffs (nightly) only flag nodes `merged` / `expired`; the person's memories are never edited by a model.

Recall = Gemini Embedding 2 cosine over memory + activity-node vectors when vectors exist and a key is set, else
FTS5 (bm25) over memories + word match on node labels; then 1-hop expansion over `about` edges; rank; top k.
Person-facing only — never health data, scores or states (no clinician route reads these tables).
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from kaiku_contracts.config import get

from .. import service
from ..analytics import bandit
from ..llm import gemini
from ..llm.errors import LlmUnavailable
from ..store.db import Store
from . import memory

NODE_OF = {"people": ("person", "knows"), "places": ("place", "goes_to"), "likes": ("like", "likes"),
           "what_helps": ("helper", "helped_by"), "plans": ("plan", "plans")}
ACTIVITY_LABEL = {"walk": "walks", "breathe": "breathing together", "drum": "drumming",
                  "friend_ping": "lighting a friend's lamp", "ritual": "the morning ritual",
                  "checkin": "weather checks"}
INTENT_ACTIVITY = {"walk": "walk", "breathe": "breathe", "break": "breathe", "ritual": "ritual",
                   "checkin": "checkin"}
ACTIVITY_TERMS = {"walk": ("walk", "lake", "park", "forest", "outside", "path"), "drum": ("drum",),
                  "breathe": ("breath",), "friend_ping": ("lamp",), "ritual": ("morning",)}
EPISODE_DAYS = 35
STOP = {"what", "whats", "who", "whos", "where", "when", "which", "how", "the", "and", "you", "your", "my", "me",
        "did", "does", "was", "were", "is", "are", "her", "his", "their", "name", "called", "remember", "tell",
        "know", "again", "about", "that", "this", "with", "for", "have", "has", "had", "kaiku", "today", "do"}


def _now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds")


def terms(text: str) -> list[str]:
    return [w for w in re.findall(r"\w+", memory.norm(text).replace("'s", "")) if len(w) > 2 and w not in STOP]


def _activity_of(text: str) -> list[str]:
    words = re.findall(r"\w+", memory.norm(text))
    return [a for a, ts in ACTIVITY_TERMS.items() if any(w.startswith(t) for w in words for t in ts)]


# ------------------------------------------------------------------ build
def rebuild(store: Store, home_id: str, now: datetime | None = None) -> dict[str, int]:
    """Recompute every code-derived node/edge for one home from its sources (idempotent; statuses kept)."""
    now = now or datetime.now(UTC)
    ts = _now_iso(now)
    memory.expire(store, home_id, now)
    keep_n: set[int] = set()
    keep_e: set[tuple[int, int, str]] = set()

    def edge(src: int, dst: int, rel: str, weight: float, evidence: list[str]) -> None:
        store.kg_upsert_edge(home_id, src, dst, rel, round(max(0.0, min(1.0, weight)), 3), evidence, ts)
        keep_e.add((src, dst, rel))

    me = store.kg_upsert_node(home_id, "me", memory.first_name(store, home_id) or "you", "me", "self", ts)
    keep_n.add(me)
    activity: dict[str, int] = {}

    def act(key: str, origin: str) -> int:
        if key not in activity:
            activity[key] = store.kg_upsert_node(home_id, "activity", ACTIVITY_LABEL[key], key, origin, ts)
            keep_n.add(activity[key])
        return activity[key]

    mem_nodes: list[tuple[int, dict[str, Any]]] = []
    for m in store.memories(home_id):
        if m["category"] not in NODE_OF:
            continue
        typ, rel = NODE_OF[m["category"]]
        nid = store.kg_upsert_node(home_id, typ, m["text"], memory.norm(m["text"]), f"memory:{m['id']}", ts)
        keep_n.add(nid)
        edge(me, nid, rel, 1.0, [f"mem:{m['id']}"])
        mem_nodes.append((nid, m))

    since = (now - timedelta(days=EPISODE_DAYS)).astimezone(UTC).isoformat()
    done = [e for e in store.episodes(home_id, since) if e["outcome"] == "completed" and e["intent"] in INTENT_ACTIVITY]
    by_act: dict[str, list[str]] = defaultdict(list)
    for e in done:
        by_act[INTENT_ACTIVITY[e["intent"]]].append(e["id"])
    for key, ids in by_act.items():
        edge(me, act(key, "episode"), "did", len(ids) / max(len(done), 1), ids[-5:])

    if home_id in store.home_ids():
        data = service.patient_data(store, home_id, service.active_criteria(store))
        evidence = _bandit_evidence(store, home_id)
        for h in bandit.help_stats(data.nudge_outcomes, data.interventions):
            if h["activity"] in ACTIVITY_LABEL and h["mean_effect"] is not None and h["mean_effect"] > 0.5:
                edge(me, act(h["activity"], "bandit"), "helped", h["mean_effect"], evidence.get(h["activity"], [])[-5:])

    for nid, m in mem_nodes:
        for key in _activity_of(m["text"]):
            edge(nid, act(key, "memory"), "about", 1.0, [f"mem:{m['id']}"])

    store.kg_prune(home_id, keep_n, keep_e)
    store.embedding_delete_missing(home_id, {f"mem:{m['id']}" for m in store.memories(home_id)}
                                   | {f"kg:{n}" for n in keep_n})  # a deleted memory takes its vector with it
    return {"nodes": len(keep_n), "edges": len(keep_e)}


def _bandit_evidence(store: Store, home_id: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for e in store.events_for_home(home_id, ["obs.nudge_outcome", "obs.intervention_response"]):
        p = e["payload"]
        a = bandit.ARM_ACTIVITY.get(p.get("arm", "")) if e["type"] == "obs.nudge_outcome" else p.get("activity")
        if a:
            out[a].append(e["id"])
    return out


def helped_weights(store: Store, home_id: str) -> dict[str, float]:
    nodes = {n["id"]: n for n in store.kg_nodes(home_id)}
    return {nodes[e["dst"]]["norm"]: e["weight"] for e in store.kg_edges(home_id) if e["rel"] == "helped"}


# ------------------------------------------------------------------ embeddings
def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _items(store: Store, home_id: str) -> list[dict[str, Any]]:
    """Recall candidates: active memories (not merged/expired in the graph) + activity nodes."""
    nodes = store.kg_nodes(home_id)
    inactive = {n["origin"] for n in nodes if n["status"] != "active"}
    items = [{"ref": f"mem:{m['id']}", "text": m["text"], "category": m["category"], "id": m["id"]}
             for m in store.memories(home_id) if f"memory:{m['id']}" not in inactive and m["category"] != "name"]
    items += [{"ref": f"kg:{n['id']}", "text": n["label"], "category": "activity", "id": n["id"]}
              for n in nodes if n["type"] == "activity" and n["status"] == "active"]
    return items


def index(store: Store, home_id: str, limit: int | None = None) -> int:
    """Embed memories/nodes whose vector is missing or stale (Gemini Embedding 2). 0 without a key; never raises."""
    if not gemini.available():
        return 0
    model = gemini.embedding_model()
    have = store.embeddings(home_id, model)
    items = _items(store, home_id)
    store.embedding_delete_missing(home_id, {i["ref"] for i in items})
    n = 0
    for it in items:
        if limit is not None and n >= limit:
            break
        h = _hash(it["text"])
        if it["ref"] in have and have[it["ref"]][0] == h:
            continue
        try:
            vec = gemini.embed(it["text"], query=False, task="embed_memory", home_id=home_id)
        except LlmUnavailable:
            return n
        store.embedding_put(home_id, it["ref"], model, h, np.asarray(vec, dtype=np.float32).tobytes())
        n += 1
    return n


def on_memory_write(store: Store, home_id: str) -> None:
    """After a stored memory: graph + (when a key exists) its vector. Fail-soft."""
    try:
        rebuild(store, home_id)
        index(store, home_id, limit=3)
    except Exception:  # never break a remember call
        pass


def _query_vector(store: Store, home_id: str, query: str, cache: bool) -> np.ndarray | None:
    model = gemini.embedding_model()
    key = f"qvec:{model}:{_hash(query)}"
    if cache and (v := store.kv_get(key)):
        return np.asarray(v, dtype=np.float32)
    try:
        vec = gemini.embed(query, query=True, task="embed_query", home_id=home_id)
    except LlmUnavailable:
        return None
    if cache:
        store.kv_set(key, vec)
    return np.asarray(vec, dtype=np.float32)


# ------------------------------------------------------------------ recall
def recall(store: Store, home_id: str, query: str, *, k: int | None = None, cache_query: bool = False,
           now: datetime | None = None) -> list[dict[str, Any]]:
    """Top-k items {ref, text, category, score, via: vector|fts|hop} for the query. Vectors when present, else FTS."""
    k = k or int(get("mind", "recall_k", 3))
    memory.expire(store, home_id, now or datetime.now(UTC))
    items = _items(store, home_id)
    by_ref = {i["ref"]: i for i in items}
    scored: dict[str, tuple[float, str]] = {}
    vecs = store.embeddings(home_id, gemini.embedding_model()) if gemini.available() else {}
    qv = _query_vector(store, home_id, query, cache_query) if vecs and query.strip() else None
    if qv is not None:
        for ref, (_h, blob) in vecs.items():
            if ref in by_ref:
                v = np.frombuffer(blob, dtype=np.float32)
                if v.shape == qv.shape:
                    denom = float(np.linalg.norm(v) * np.linalg.norm(qv)) or 1.0
                    scored[ref] = (float(v @ qv) / denom, "vector")
    else:
        q = terms(query)
        for rank, m in enumerate(store.memory_search(home_id, q, 20)):
            ref = f"mem:{m['id']}"
            if ref in by_ref:
                scored[ref] = (1.0 / (rank + 1), "fts")
        for it in items:
            if it["ref"].startswith("kg:") and set(terms(it["text"])) & set(q):
                scored.setdefault(it["ref"], (0.5, "fts"))
    top = sorted(scored.items(), key=lambda kv: -kv[1][0])[:k]
    # 1-hop: a memory node that is `about` an activity brings the activity along (half its score × edge weight)
    nodes = {n["id"]: n for n in store.kg_nodes(home_id)}
    mem_node = {int(n["origin"].split(":")[1]): nid for nid, n in nodes.items() if n["origin"].startswith("memory:")}
    edges = store.kg_edges(home_id)
    hops: dict[str, float] = {}
    for ref, (score, _via) in top:
        if ref.startswith("mem:"):
            nid = mem_node.get(int(ref[4:]))
            for e in edges:
                if e["src"] == nid and e["rel"] == "about" and f"kg:{e['dst']}" in by_ref:
                    hops[f"kg:{e['dst']}"] = max(hops.get(f"kg:{e['dst']}", 0.0), 0.5 * score * e["weight"])
    merged = dict(top)
    for ref, s in hops.items():
        if ref not in merged:
            merged[ref] = (s, "hop")
    ranked = sorted(merged.items(), key=lambda kv: -kv[1][0])[:k]
    return [{**by_ref[ref], "score": round(s, 4), "via": via} for ref, (s, via) in ranked]


def card_memories(store: Store, home_id: str, intent: str, now: datetime) -> list[dict[str, Any]]:
    """≤ 3 memories for the context card. With vectors: Embedding-2 recall for the intent's words (query vector
    cached); otherwise exactly the plan-04 FTS rule (memory.recall)."""
    exclude = ("name", "preference")
    inactive = {n["origin"] for n in store.kg_nodes(home_id) if n["status"] != "active"}
    if gemini.available() and store.embeddings(home_id, gemini.embedding_model()):
        q = " ".join([intent, *memory.INTENT_TERMS.get(intent, [])])
        hits = [h for h in recall(store, home_id, q, k=6, cache_query=True, now=now)
                if h["ref"].startswith("mem:") and h["category"] not in exclude]
        if hits:
            ids = {h["id"] for h in hits}
            rest = [m for m in store.memories(home_id) if m["id"] not in ids and m["category"] not in exclude
                    and f"memory:{m['id']}" not in inactive]
            out = [{"id": h["id"], "category": h["category"], "text": h["text"]} for h in hits] + rest
            return out[:memory.CARD_MEMORIES]
    inactive = {n["origin"] for n in store.kg_nodes(home_id) if n["status"] != "active"}
    candidates = memory.recall(store, home_id, "", intent=intent, fill=True, exclude=exclude, now=now,
                               limit=len(store.memories(home_id)))
    return [m for m in candidates if f"memory:{m['id']}" not in inactive][:memory.CARD_MEMORIES]


# ------------------------------------------------------------------ conflicts
RELATIONS = ("sister", "brother", "mother", "mum", "mom", "father", "dad", "daughter", "son", "wife", "husband",
             "partner", "friend", "neighbour", "neighbor", "dog", "cat", "grandchild", "grandson", "granddaughter")
_NOT_NAME = {"Her", "His", "My", "Their", "The", "A", "An", "She", "He", "I", "Is", "Called", "Named"}


def _names(text: str) -> set[str]:
    return {w for w in re.findall(r"\b[A-ZÄÖÅ][a-zäöå]+\b", text) if w not in _NOT_NAME}


def conflicts(store: Store, home_id: str, question: str) -> list[dict[str, Any]]:
    """People memories about the same relation (asked about) sharing no name ("sister Maija" vs "sister Mia"):
    Kaiku must ask, not pick. "sister Maija" + "sister Maija lives in Turku" share a name -> no conflict."""
    rels = [r for r in RELATIONS if re.search(rf"\b{r}", memory.norm(question))]
    out: list[dict[str, Any]] = []
    for r in rels:
        same = [m for m in store.memories(home_id) if m["category"] == "people"
                and re.search(rf"\b{r}", memory.norm(m["text"])) and _names(m["text"])]
        clash = {m["id"]: m for a in same for b in same if not _names(a["text"]) & _names(b["text"])
                 for m in (a, b)}
        out += [m for m in clash.values() if m not in out]
    return out


# ------------------------------------------------------------------ consolidation (nightly, validated diffs)
def rule_diffs(store: Store, home_id: str) -> list[dict[str, Any]]:
    """Deterministic proposals: same-type nodes where one label contains the other -> merge into the longer."""
    nodes = [n for n in store.kg_nodes(home_id) if n["status"] == "active" and n["type"] in
             {t for t, _ in NODE_OF.values()}]
    diffs = []
    for a in nodes:
        for b in nodes:
            if a["id"] < b["id"] and a["type"] == b["type"] and (a["norm"] in b["norm"] or b["norm"] in a["norm"]):
                keep, drop = (a, b) if len(a["norm"]) >= len(b["norm"]) else (b, a)
                diffs.append({"op": "merge", "keep": f"kg:{keep['id']}", "drop": f"kg:{drop['id']}"})
    return diffs


def validate_diffs(store: Store, home_id: str, raw: list[Any], max_diffs: int = 10) -> list[dict[str, Any]]:
    """Keep only diffs that name this home's active nodes and make sense: merge = same type, two different nodes;
    expire = a plan. Anything else is dropped (never raises)."""
    nodes = {f"kg:{n['id']}": n for n in store.kg_nodes(home_id) if n["status"] == "active"}
    ok: list[dict[str, Any]] = []
    touched: set[str] = set()
    for d in raw if isinstance(raw, list) else []:
        if not isinstance(d, dict) or len(ok) >= max_diffs:
            continue
        if d.get("op") == "merge":
            k, x = nodes.get(str(d.get("keep"))), nodes.get(str(d.get("drop")))
            same_person = bool(k and x and (k["type"] != "person" or (
                (k["norm"] in x["norm"] or x["norm"] in k["norm"]) and _names(k["label"]) == _names(x["label"]))))
            if k and x and same_person and k["id"] != x["id"] and k["type"] == x["type"] and k["type"] != "me" \
                    and not {d["keep"], d["drop"]} & touched:
                ok.append({"op": "merge", "keep": d["keep"], "drop": d["drop"]})
                touched |= {d["keep"], d["drop"]}
        elif d.get("op") == "expire":
            n = nodes.get(str(d.get("node")))
            if n and n["type"] == "plan" and d["node"] not in touched:
                ok.append({"op": "expire", "node": d["node"]})
                touched.add(d["node"])
    return ok


def apply_diffs(store: Store, home_id: str, diffs: list[dict[str, Any]]) -> int:
    n = 0
    for d in diffs:
        if d["op"] == "merge":
            n += store.kg_set_status(home_id, int(d["drop"][3:]), "merged", int(d["keep"][3:]))
        else:
            n += store.kg_set_status(home_id, int(d["node"][3:]), "expired")
    return n


# ------------------------------------------------------------------ constellation (person-facing)
CONSTELLATION_TYPES = {"me", "person", "place", "like", "helper", "plan", "activity"}


def constellation(store: Store, home_id: str) -> dict[str, Any]:
    rebuild(store, home_id)
    nodes = [n for n in store.kg_nodes(home_id) if n["status"] == "active" and n["type"] in CONSTELLATION_TYPES]
    ids = {n["id"] for n in nodes}
    edges = [e for e in store.kg_edges(home_id) if e["src"] in ids and e["dst"] in ids]
    return {"home_id": home_id, "nodes": [{"id": n["id"], "type": n["type"], "label": n["label"]} for n in nodes],
            "edges": [{"src": e["src"], "dst": e["dst"], "rel": e["rel"], "weight": e["weight"]} for e in edges]}


def stats(store: Store, home_id: str) -> dict[str, Any]:
    return {"types": dict(Counter(n["type"] for n in store.kg_nodes(home_id))),
            "edges": dict(Counter(e["rel"] for e in store.kg_edges(home_id)))}
