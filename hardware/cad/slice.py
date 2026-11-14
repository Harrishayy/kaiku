# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Slice every print plate for the Bambu Lab P1S and P2S with Bambu Studio's own command-line slicer.

Run:  uv run --script hardware/cad/slice.py            (after kaiku_cad.py; needs Bambu Studio in /Applications)
      uv run --script hardware/cad/slice.py P2S        (one printer)
Out:  hardware/cad/out/print/<printer>/<plate>.3mf     sliced plates: open in Bambu Studio and press Print
      hardware/cad/out/print/<printer>/estimate.json   every candidate tried, and the one kept
      hardware/cad/out/print/summary.json              kept plates, both printers, MVP / full / body totals

How "optimal" is decided, per plate and printer:
- One filament per plate (any colour), so nothing needs an AMS purge (no flush waste, no prime tower).
- Every part is modelled to print without supports in the orientation kaiku_cad.py exports; supports are off.
- No brim, 2 walls; infill 10 % on shells, 15 % on parts that carry load (gears, neck).
- Each plate is sliced with every allowed layer-height preset and the fastest is kept. Plates with gear
  teeth are limited to 0.20 mm so the involute flanks stay accurate.
Times are Bambu Studio's prediction, which includes the printer's start sequence.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
STL = HERE / "out" / "stl"
OUT = HERE / "out" / "print"
APP = Path("/Applications/BambuStudio.app/Contents")
PROFILES = APP / "Resources" / "profiles" / "BBL"
CLI = APP / "MacOS" / "BambuStudio"

PRINTERS = {
    "P1S": {"machine": "Bambu Lab P1S 0.4 nozzle", "filament": "Bambu PLA Basic @BBL X1C",
            "fine": ["0.20mm Standard @BBL X1C"],
            "draft": ["0.20mm Standard @BBL X1C", "0.24mm Draft @BBL X1C", "0.28mm Extra Draft @BBL X1C"]},
    "P2S": {"machine": "Bambu Lab P2S 0.4 nozzle", "filament": "Bambu PLA Basic @BBL P2S",
            "fine": ["0.20mm Standard @BBL P2S"],
            "draft": ["0.20mm Standard @BBL P2S", "0.24mm Standard @BBL P2S",
                      "0.24mm Standard @BBL P2S|layer_height=0.28"]},   # no 0.28 preset ships for the P2S
}

# plate: (set, filament, quality, infill %, parts)
PLATES = {
    "1_head":         ("mvp", "any", "draft", 10, ["head_shell", "head_back"]),
    "2_neck":         ("mvp", "any", "fine", 15, ["turntable", "pan_base", "pan_motor_mount", "purr_sleeve",
                                                    "finger_cradle"]),
    "3_small_parts":  ("mvp", "any", "fine", 15, ["pinion", "purr_weight", "ear_left", "ear_right", "knob_cap",
                                                    "antenna_ball", "cheek_left", "cheek_right"]),
    "4_face_bezel":   ("full", "any", "draft", 10, ["face_bezel"]),
    "5_body":         ("body", "any", "draft", 10, ["body_tub", "top_plate", "window_pane"]),
}

BASE_OVERRIDES = {
    "enable_support": "0",
    "brim_type": "no_brim",
    "wall_loops": "2",
    "enable_prime_tower": "0",
}


# ------------------------------------------------------------------ profiles ---
def index() -> dict[str, Path]:
    idx = {}
    for f in PROFILES.rglob("*.json"):
        try:
            name = json.loads(f.read_text()).get("name")
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if name:
            idx.setdefault(name, f)
    return idx


def flatten(name: str, idx: dict[str, Path]) -> dict:
    data = json.loads(idx[name].read_text())
    parent = data.pop("inherits", None)
    merged = flatten(parent, idx) if parent else {}
    merged.update(data)
    return merged


def split(process: str) -> tuple[str, dict]:
    """'preset|key=value|...' -> (preset, overrides)."""
    name, *extra = process.split("|")
    return name, dict(kv.split("=", 1) for kv in extra)


def write_presets(printer: str, process: str, infill: int, idx, pdir: Path) -> list[Path]:
    """The command-line slicer does not follow "inherits", so resolve each system preset and save it as a
    user preset that names our machine as compatible."""
    spec = PRINTERS[printer]
    mname = f"kaiku {printer} machine"
    files = []
    pname, extra = split(process)
    for kind, parent in (("machine", spec["machine"]), ("process", pname), ("filament", spec["filament"])):
        cfg = flatten(parent, idx)
        if kind == "process":
            cfg.update(BASE_OVERRIDES)
            cfg.update(extra)
            cfg["sparse_infill_density"] = f"{infill}%"
        cfg.update({"type": kind, "from": "User", "name": f"kaiku {printer} {kind}", "inherits": parent})
        cfg.pop("setting_id", None)
        if kind == "machine":
            cfg["printer_settings_id"] = mname
        else:
            cfg["compatible_printers"] = [mname, spec["machine"]]
            cfg["compatible_printers_condition"] = ""
            if kind == "process":
                cfg["print_settings_id"] = cfg["name"]
            else:
                cfg["filament_settings_id"] = [cfg["name"]]
        path = pdir / f"{kind}.json"
        path.write_text(json.dumps(cfg, indent=1))
        files.append(path)
    return files


# --------------------------------------------------------------------- slice ---
def slice_once(files: list[Path], parts: list[str], work: Path, out3mf: Path) -> dict:
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    cmd = [str(CLI), "--slice", "0", "--arrange", "1", "--orient", "0", "--ensure-on-bed",
           "--load-settings", f"{files[0]};{files[1]}", "--load-filaments", str(files[2]),
           "--outputdir", str(work), "--export-3mf", out3mf.name,
           *[str(STL / f"{p}.stl") for p in parts]]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    res: dict = {"returncode": proc.returncode}
    produced = work / out3mf.name
    if produced.exists():
        with zipfile.ZipFile(produced) as z:
            info = [n for n in z.namelist() if n.endswith("slice_info.config")]
            txt = z.read(info[0]).decode() if info else ""
        preds = [int(v) for v in re.findall(r'key="prediction" value="(\d+)"', txt)]
        grams = [float(v) for v in re.findall(r'used_g="([\d.]+)"', txt)]
        plates = len(re.findall(r"<plate>", txt))
        outside = 'key="outside" value="true"' in txt
        if preds:
            res.update(hours=round(sum(preds) / 3600, 3), grams=round(sum(grams), 1), plates=plates,
                       outside_bed=outside)
            produced.replace(out3mf)
    if "hours" not in res:
        res["log"] = (proc.stdout[-1200:] + proc.stderr[-1200:]).strip()
    shutil.rmtree(work, ignore_errors=True)
    return res


def run_printer(printer: str, idx) -> dict:
    pdir = OUT / printer
    pdir.mkdir(parents=True, exist_ok=True)
    results = {}
    for plate, (pset, colour, quality, infill, parts) in PLATES.items():
        tried = []
        for process in PRINTERS[printer][quality]:
            if split(process)[0] not in idx:
                tried.append({"process": process, "skipped": "preset not shipped with this Bambu Studio"})
                continue
            tag = re.sub(r"[^0-9a-z]+", "_", process.lower())
            cand = pdir / f"_{plate}__{tag}.3mf"
            ppre = pdir / f"_presets_{plate}_{tag}"
            ppre.mkdir(exist_ok=True)
            files = write_presets(printer, process, infill, idx, ppre)
            r = slice_once(files, parts, pdir / f"_work_{plate}_{tag}", cand)
            shutil.rmtree(ppre, ignore_errors=True)
            r["process"] = process
            tried.append(r)
            print(f"[{printer}] {plate:16s} {process:30s} "
                  + (f"{r['hours']:.2f} h {r['grams']:.0f} g plates={r['plates']}" if "hours" in r else "FAILED"),
                  flush=True)
        ok = [t for t in tried if "hours" in t and t["plates"] == 1 and not t["outside_bed"]]
        best = min(ok, key=lambda t: (t["hours"], t["grams"])) if ok else None
        for t in tried:
            if "hours" not in t:
                continue
            tag = re.sub(r"[^0-9a-z]+", "_", t["process"].lower())
            cand = pdir / f"_{plate}__{tag}.3mf"
            if best is t:
                cand.replace(pdir / f"{plate}.3mf")
            else:
                cand.unlink(missing_ok=True)
        results[plate] = {"set": pset, "filament": colour, "infill_pct": infill, "parts": parts,
                          "kept": best, "tried": tried}
    (pdir / "estimate.json").write_text(json.dumps(results, indent=1))
    return results


def totals(results: dict) -> dict:
    out = {}
    for label, sets in (("mvp", {"mvp"}), ("full_without_body", {"mvp", "full"}), ("full_with_body",
                                                                                   {"mvp", "full", "body"})):
        kept = [r["kept"] for r in results.values() if r["set"] in sets and r["kept"]]
        out[label] = {"hours": round(sum(k["hours"] for k in kept), 2),
                      "grams": round(sum(k["grams"] for k in kept), 1), "plates": len(kept)}
    return out


def main():
    if not CLI.exists():
        sys.exit("Bambu Studio not found in /Applications")
    wanted = [a for a in sys.argv[1:] if a in PRINTERS] or list(PRINTERS)
    idx = index()
    with ThreadPoolExecutor(max_workers=len(wanted)) as ex:
        res = dict(zip(wanted, ex.map(lambda pr: run_printer(pr, idx), wanted), strict=True))
    summary_path = OUT / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    for pr, r in res.items():
        summary[pr] = {"plates": {k: {"set": v["set"], "filament": v["filament"],
                                      "process": v["kept"]["process"] if v["kept"] else None,
                                      "hours": v["kept"]["hours"] if v["kept"] else None,
                                      "grams": v["kept"]["grams"] if v["kept"] else None,
                                      "parts": v["parts"]} for k, v in r.items()},
                       "totals": totals(r)}
    summary_path.write_text(json.dumps(summary, indent=1))
    for pr in res:
        print(pr, json.dumps(summary[pr]["totals"]))


if __name__ == "__main__":
    main()
