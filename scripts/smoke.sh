#!/usr/bin/env bash
# End-to-end smoke test: throwaway cloud on a free port + temp DB, seed sim patients, check key endpoints.
# Usage: scripts/smoke.sh        (make smoke)     Exit 0 = the integrated system works end to end.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT=${SMOKE_PORT:-8765}
TMP=$(mktemp -d)
export KAIKU_DB_PATH="$TMP/smoke.sqlite" KAIKU_LLM=template KAIKU_CLOUD_URL="http://127.0.0.1:$PORT"
unset KAIKU_HOME_TOKEN KAIKU_ADMIN_TOKEN

uv run --quiet uvicorn kaiku_cloud.api.main:app --port "$PORT" --log-level warning >"$TMP/cloud.log" 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null || true; rm -rf "$TMP"' EXIT

for _ in $(seq 1 60); do curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && break; sleep 0.5; done
curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null || { echo "❌ cloud did not start"; cat "$TMP/cloud.log"; exit 1; }

uv run --quiet python -m sim.seed_demo --reset >"$TMP/seed.log" 2>&1 || { echo "❌ seed failed"; tail -20 "$TMP/seed.log"; exit 1; }

uv run --quiet python - "$PORT" <<'EOF'
import json, sys, urllib.request
base = f"http://127.0.0.1:{sys.argv[1]}"
def get(path):
    with urllib.request.urlopen(base + path, timeout=20) as r:
        return json.loads(r.read())
fails = []
def check(name, ok, detail=""):
    print(("✅ " if ok else "❌ ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok: fails.append(name)

patients = get("/v1/patients")
rows = patients if isinstance(patients, list) else patients.get("patients", patients.get("items", []))
check("patients listed", len(rows) >= 8, f"{len(rows)} rows")
by_id = {(p.get("home_id") or p.get("id") or p.get("patient_id")): p for p in rows}
aino = next((p for k, p in by_id.items() if k and "aino" in k), None)
check("Aino present", aino is not None)
if aino:
    state = json.dumps(aino)
    check("Aino needs a call", "needs_call" in state, state[:200])
    pid = aino.get("home_id") or aino.get("id") or aino.get("patient_id")
    cons = get(f"/v1/patients/{pid}/consensus")
    srcs = {s.get("source") for s in cons.get("sources", [])}
    check("consensus has robot/glasses/laptop", {"robot", "glasses", "laptop"} <= srcs, str(srcs))
    check("consensus has wearable source", "wearable" in srcs, str(srcs))
    me = get(f"/v1/me?home_id={pid}")
    check("/v1/me summary", bool(me.get("summary")))
    check("/v1/me mascot", isinstance(me.get("mascot"), dict) and bool(me["mascot"].get("mood")), str(me.get("mascot")))
    banned = ["diagnos", "relapse", "predict"]
    text = json.dumps(me).lower()
    check("/v1/me wording clean", not any(b in text for b in banned))
    tl = get(f"/v1/patients/{pid}/timeline")
    check("timeline has series", len(tl.get("series", [])) > 5)
    req = urllib.request.Request(base + "/v1/companion/session", method="POST",
                                 data=json.dumps({"home_id": pid, "surface": "robot", "intent": "ritual"}).encode(),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        sess = json.loads(r.read())
    check("companion session has system_instruction", "## Who Kaiku is" in sess.get("system_instruction", ""))
    check("companion session has tools", {"remember", "recall", "end_session"} <= {t["name"] for t in sess.get("tools", [])})
    card = sess.get("context_card", {})
    check("context card is rich (name, memories, thread)", card.get("first_name") == "Aino" and card.get("memories")
          and card.get("open_thread"), json.dumps(card)[:300])
    card_text = json.dumps(card).lower()
    check("context card has no state words", not any(w in card_text for w in
          ["needs_call", "needs a call", "stable", "consensus", "worse", "score", "diagnos", "relapse", "predict"]),
          card_text[:300])
    mems = get(f"/v1/me/memories?home_id={pid}")
    check("/v1/me/memories lists Aino's notebook", len(mems.get("memories", [])) >= 4)
if fails:
    print(f"\n{len(fails)} smoke check(s) failed"); sys.exit(1)
print("\nsmoke OK")
EOF
