import argparse
import json

from . import DEMO_PATIENTS, demo_events

ap = argparse.ArgumentParser(description="Generate the simulated demo cohort")
ap.add_argument("--jsonl", help="write every envelope to this file")
args = ap.parse_args()

events = demo_events()
for p in DEMO_PATIENTS:
    ev = events[p.home_id]
    print(f"{p.home_id:12} expect={p.expected_state:10} onset={p.onset!s:4} events={len(ev):4} "
          f"sources={'+'.join(sorted(p.present))}  {p.scenario}")
if args.jsonl:
    with open(args.jsonl, "w") as f:
        for ev in events.values():
            for e in ev:
                f.write(json.dumps(e) + "\n")
    print("wrote", args.jsonl)
