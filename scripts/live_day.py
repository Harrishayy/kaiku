"""What do today's recordings do to Aino's reading? Posts a good day and a rough day and prints what the
practitioner API returns for each, next to the record as it opens.

    uv run python scripts/live_day.py                      # throwaway database, both days side by side (no network)
    uv run python scripts/live_day.py --url http://127.0.0.1:8000 --kind good
                                                           # post ONE day to a running local API (sim: true rows;
                                                           # `make demo-reset` removes them again)
Real devices do the same thing: link the iPhone or Mac to home `aino` and record a check-in, a game or a walk.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("KAIKU_NO_DOTENV", "1")  # the throwaway run never needs a key
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud"))

import httpx  # noqa: E402
from kaiku_cloud.jobs import single_person  # noqa: E402
from kaiku_cloud.settings import TZ  # noqa: E402

LABEL = {"robot": "Check-ins & robot", "glasses": "Walks & outings", "laptop": "Apps", "wearable": "Watch"}
WORDS = {"watch": "worth a check-in / still forming", "needs_call": "needs a call", "stable": "stable", "safety": "safety"}
SHOW = ("mood", "energy", "sleep", "outing_min", "firefly_reaction", "late_night", "watch_sleep", "resting_hr")

HOME = os.environ.get("KAIKU_HOME_ID") or "aino"  # the seeded person's record


def reading(client, home: str) -> dict:
    cons = client.get(f"/v1/patients/{home}/consensus").json()
    timeline = client.get(f"/v1/patients/{home}/timeline", params={"days": 30}).json()
    today = datetime.now(TZ).date().isoformat()
    values = {}
    for series in timeline["series"]:
        if series["metric"] not in SHOW:
            continue
        pts = [p for p in series["points"] if p.get("value") is not None]
        dip = [p["value"] for p in pts[-8:-3]] if len(pts) >= 8 else []
        last = pts[-1] if pts else None
        values[series["metric"]] = (series["label"], series["unit"], last["value"] if last and last["date"] == today else None,
                                    last.get("baseline_median") if last else None, min(dip) if dip else None,
                                    max(dip) if dip else None)
    week = client.get(f"/v1/patients/{home}/week").json()
    return {"state": cons["state"], "agreement": cons["agreement"], "ack": cons.get("acknowledged_by"),
            "sources": {s["source"]: s["verdict"] for s in cons["sources"]},
            "headline": (cons.get("explanation") or {}).get("headline", ""), "values": values,
            "look": [i["text"] for i in week["worth_a_look"]][:4], "well": [i["text"] for i in week["going_well"]][:4]}


def show(title: str, r: dict) -> None:
    print(f"\n=== {title} ===")
    print(f"  reading: {WORDS.get(r['state'], r['state'])} ({r['state']}, {r['agreement']})"
          + (f", acknowledged by {r['ack']}" if r["ack"] else ""))
    print("  " + " · ".join(f"{LABEL[k]}: {v.replace('_', ' ')}" for k, v in r["sources"].items()))
    for label, unit, today, usual, lo, hi in r["values"].values():
        if today is None:
            continue
        span = f"; the hard days last week: {lo:g}-{hi:g}" if lo is not None else ""
        print(f"    {label:38} today {today:g} {unit} (her usual {usual:g}{span})" if usual is not None
              else f"    {label:38} today {today:g} {unit}")
    for text in r["look"]:
        print(f"    worth a look: {text}")
    for text in r["well"][:2]:
        print(f"    going well:   {text}")


def local_run() -> int:
    from fastapi.testclient import TestClient
    from kaiku_cloud.api.main import create_app
    from kaiku_cloud.settings import Settings

    now = datetime.now(TZ)
    rows = single_person.build(now.date() - timedelta(days=1))
    results = {}
    for kind in ("good", "rough"):
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(Settings(db_path=f"{tmp}/day.sqlite", demo_mode=True, web_dir=None,
                                                    llm="template")))
            single_person.seed("http://127.0.0.1:1", rows, jobs=False, client=client)
            if kind == "good":
                show("As the record opens this morning (sixteen days, nothing yet today)", reading(client, HOME))
            posted = client.post("/v1/events", json={"events": single_person.today_events(now.date(), kind, now=now)}).json()
            assert not posted["rejected"], posted
            results[kind] = reading(client, HOME)
            show(f"After a {kind} day today", results[kind])
    ok = results["good"]["state"] != results["rough"]["state"] or results["good"]["sources"] != results["rough"]["sources"]
    print("\n" + ("The two days read differently: today's recordings move the comparison." if ok
                  else "WARNING: both days read the same; check config/criteria.toml against the record."))
    return 0 if ok else 1


def remote_run(url: str, kind: str) -> int:
    single_person._local(url)
    now = datetime.now(TZ)
    with httpx.Client(base_url=url, timeout=60) as client:
        if client.get("/v1/discovery").json().get("mode") != "demo":
            print("this API is not in credential-free local mode; not posting", file=sys.stderr)
            return 1
        show("Before", reading(client, HOME))
        posted = client.post("/v1/events", json={"events": single_person.today_events(now.date(), kind, now=now)}).json()
        print(f"\nposted a {kind} day: {posted['accepted']} new, {posted['duplicates']} already there")
        show(f"After a {kind} day today", reading(client, HOME))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="post to this running local API instead of a throwaway database")
    parser.add_argument("--kind", choices=("good", "rough"), help="which day to post (required with --url)")
    args = parser.parse_args()
    if args.url:
        if not args.kind:
            parser.error("--url needs --kind good|rough")
        return remote_run(args.url.rstrip("/"), args.kind)
    return local_run()


if __name__ == "__main__":
    raise SystemExit(main())
