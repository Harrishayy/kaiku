"""Audit, export and replay what the hub stored for a ritual (hub/kaiku_hub/store.py, `[hub] store_path`).

    python tools/session.py list
    python tools/session.py show last                       # counts per stream, emitted obs, summary, notes
    python tools/session.py export last -o logs/s.json      # everything: session, raw samples, emitted obs
    python tools/session.py rederive last                   # recompute drum + pulse from the stored raw numbers
                                                            # and compare with the obs that was uplinked
    python tools/session.py replay-file last -o logs/s.jsonl   # tools/record.py format, then:
    python tools/replay.py logs/s.jsonl                        # re-publish the raw stream to a broker

A session is named by its id, its episode id (what the cloud knows), a unique prefix of either, or `last`.
The store holds numbers only (no image, no audio) and stays on this machine: an export is personal data, keep it
in gitignored logs/. A replay file is always marked `sim: true`: replayed data is not a fresh measurement.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kaiku_contracts import make, to_json, topic_for  # noqa: E402
from kaiku_contracts.config import get, load_dotenv  # noqa: E402
from kaiku_hub.perception.hrv import PpgBuffer  # noqa: E402
from kaiku_hub.perception.taps import TapAnalyzer  # noqa: E402
from kaiku_hub.settings import resolve_path  # noqa: E402
from kaiku_hub.store import list_sessions, open_readonly, read_session, resolve_session  # noqa: E402

DRUM_KEYS = ("tempo_bpm", "regularity", "taps", "duration_s", "tempo_start_bpm", "tempo_end_bpm", "taps_per_s",
             "pauses", "rejected_taps")


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _window(obs: list[dict], step: str) -> tuple[datetime, datetime] | None:
    """[started, ended] of a ritual step, from the stored obs.ritual rows."""
    start = next((o for o in obs if o["type"] == "obs.ritual" and o["payload"]["step"] == step
                  and o["payload"]["status"] == "started"), None)
    end = next((o for o in obs if o["type"] == "obs.ritual" and o["payload"]["step"] == step
                and o["payload"]["status"] != "started"), None)
    return (_ts(start["ts"]), _ts(end["ts"])) if start and end else None


def rederive(session: dict, samples: list[dict], obs: list[dict]) -> dict[str, Any]:
    """Recompute the drum and pulse observations from the stored raw numbers (same code as the hub) and compare
    with what was emitted. `match` is True/False, or None when there was nothing to compare."""
    out: dict[str, Any] = {"session": session["id"]}
    # ---- drum: taps between "drum started" and the emitted obs.drum_session
    emitted = next((o for o in obs if o["type"] == "obs.drum_session"), None)
    w = _window(obs, "drum")
    taps = TapAnalyzer(float(get("perception", "tap_refractory_ms", 80)), float(get("perception", "tap_force_max_g", 4.0)))
    if w:
        end = _ts(emitted["ts"]) if emitted else w[1]
        for r in samples:
            if r["type"] == "raw.head.tap" and w[0] <= _ts(r["ts"]) <= end:
                taps.add(int(r["payload"]["t_ms"]), r["payload"].get("force"))
    dur = (taps.times[-1] - taps.times[0]) / 1000 if taps.count > 1 else 0.0
    again = {k: v for k, v in taps.summary(dur).items() if v is not None} if taps.count >= 4 else None
    diff = ({k: (emitted["payload"].get(k), again.get(k)) for k in DRUM_KEYS
             if emitted["payload"].get(k) != again.get(k)} if emitted and again else {})
    out["drum"] = {"stored_taps": taps.count + taps.rejected, "emitted": emitted and emitted["payload"],
                   "rederived": again, "diff": diff,
                   "match": None if not (emitted or again) else bool(emitted and again and not diff)}
    # ---- pulse: every stored ppg batch of the breathe step
    emitted = next((o for o in obs if o["type"] == "obs.hrv_session"), None)
    buf = PpgBuffer()
    for r in samples:
        if r["type"] == "raw.sensors.ppg":
            p = r["payload"]
            buf.add(p["fs_hz"], p["samples"], t0_ms=p.get("t0_ms"), quality=r["quality"])
    band = get("perception", "ppg_band_hz", [0.7, 3.5])
    again, quality, _pre, _post = buf.session(
        float(emitted["payload"]["breath_bpm"]) if emitted else float(get("ritual", "breathe_bpm", 6)),
        float(emitted["payload"]["duration_s"]) if emitted else buf.seconds, (float(band[0]), float(band[1])),
        float(get("perception", "ppg_min_clean_ratio", 0.7)), window_s=float(get("ritual", "hrv_window_s", 30)),
        quality_min=float(get("perception", "quality_min", 0.5)))
    diff = ({k: (emitted["payload"].get(k), again.get(k)) for k in ("hr_bpm", "method", "beats")
             if emitted["payload"].get(k) != again.get(k)} if emitted and again else {})
    note = ((session.get("summary") or {}).get("notes") or {}).get("pulse_not_measured")
    out["pulse"] = {"stored_seconds": round(buf.seconds, 1), "method": buf.method, "emitted": emitted and emitted["payload"],
                    "rederived": again, "rederived_quality": round(quality, 3),
                    "not_measured": None if again else buf.reason, "stored_note": note, "diff": diff,
                    "match": None if not buf.samples and not emitted else (again is None) == (emitted is None) and not diff}
    return out


def replay_rows(session: dict, samples: list[dict], home_id: str) -> list[dict]:
    """tools/record.py lines for the raw stream ({t, topic, msg}); `sim` forced true (a replay is not a measurement)."""
    if not samples:
        return []
    t0 = _ts(samples[0]["ts"])
    rows = []
    for r in samples:
        env = make(r["type"], r["payload"], source=r["source"], home_id=home_id, quality=r["quality"], sim=True,
                   ts=_ts(r["ts"]))
        rows.append({"t": round(max(0.0, (_ts(r["ts"]) - t0).total_seconds()), 4), "topic": topic_for(env),
                     "msg": json.loads(to_json(env))})
    return sorted(rows, key=lambda r: r["t"])


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", type=Path, help="default: [hub] store_path")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for name in ("show", "export", "rederive", "replay-file"):
        sp = sub.add_parser(name)
        sp.add_argument("session")
        if name in ("export", "replay-file"):
            sp.add_argument("-o", "--out", type=Path, required=True)
    a = ap.parse_args(argv)
    path = a.store or resolve_path(str(get("hub", "store_path", "logs/hub_sessions.sqlite")))
    if not path.is_file():
        print(f"no session store at {path} (run a ritual with the hub first, or pass --store)", file=sys.stderr)
        return 1
    db = open_readonly(path)
    try:
        if a.cmd == "list":
            for s in list_sessions(db):
                eng = ((s["summary"] or {}).get("engagement") or {}).get("level")
                print(f"{s['id']}  {s['started']}  {s['outcome'] or 'open':<11} {s['reason']:<9} "
                      f"raw={s['samples']:<6} obs={s['obs']:<3} sim={str(s['sim']).lower():<5} "
                      f"engagement={'-' if eng is None else eng}")
            return 0
        try:
            session, samples, obs = read_session(db, resolve_session(db, a.session))
        except LookupError as e:
            print(str(e), file=sys.stderr)
            return 1
        if a.cmd == "show":
            print(json.dumps({**session, "raw_counts": dict(Counter(r["type"] for r in samples)),
                              "obs": [{"id": o["id"], "type": o["type"], "ts": o["ts"], "quality": o["quality"]}
                                      for o in obs]}, indent=2))
        elif a.cmd == "export":
            a.out.parent.mkdir(parents=True, exist_ok=True)
            a.out.write_text(json.dumps({"session": session, "samples": samples, "obs": obs}, indent=1))
            print(f"exported {len(samples)} raw messages + {len(obs)} obs -> {a.out}")
        elif a.cmd == "rederive":
            res = rederive(session, samples, obs)
            print(json.dumps(res, indent=2))
            return 0 if res["drum"]["match"] is not False and res["pulse"]["match"] is not False else 2
        elif a.cmd == "replay-file":
            rows = replay_rows(session, samples, session.get("home_id") or str(get("home", "id", "demo-aino")))
            a.out.parent.mkdir(parents=True, exist_ok=True)
            a.out.write_text("".join(json.dumps(r) + "\n" for r in rows))
            print(f"wrote {len(rows)} messages -> {a.out}  (replay: python tools/replay.py {a.out})")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
