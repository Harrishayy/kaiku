# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build hardware/cad/out/overview.html: every render, the assemblies, parts, print plates and the cardboard sheet.

Run:  uv run --script hardware/cad/overview.py      (after kaiku_cad.py, render.py, slice.py, cardboard.py)
The page lives in out/, which is gitignored: regenerate it locally, open it in a browser.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "out"

VIEWS = [
    ("front", "Front three-quarter, full printed build"),
    ("rear", "Rear three-quarter: radio grille on the head, cable openings, speaker holes"),
    ("side", "Right side: microphone ear, speaker grille"),
    ("mvp_cardboard", "MVP: printed head and neck on the cardboard body"),
    ("exploded", "Exploded: head, turntable, pan base + motor, lid, body"),
    ("internals", "Inside the body and head (shells hidden)"),
    ("head_internals", "Inside the head from the back (lid off)"),
    ("neck", "Neck: pan base, ring gear, pinion, homing magnet"),
]


def table(headers, rows) -> str:
    th = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


def main():
    rep = json.loads((OUT / "report.json").read_text())
    summ_path = OUT / "print" / "summary.json"
    summ = json.loads(summ_path.read_text()) if summ_path.exists() else {}
    cut_path = OUT / "cardboard" / "cutlist.json"
    cut = json.loads(cut_path.read_text()) if cut_path.exists() else None

    parts = table(["Part", "Set", "Size (mm, assembly axes)", "Solid volume (cm³)"],
                  [[n, v["set"], " × ".join(f"{s:g}" for s in v["size_mm"]), v["volume_cm3"]]
                   for n, v in rep["parts"].items()])
    clashes = rep.get("clashes")
    fit = ("<p class=ok>Fit check: no clashes between any printed part and any bought-in part envelope.</p>"
           if clashes == [] else f"<pre>{html.escape(json.dumps(clashes, indent=1))}</pre>")

    prints = ""
    for printer, data in summ.items():
        rows = []
        for plate, v in data["plates"].items():
            link = f'<a href="print/{printer}/{plate}.3mf">{plate}.3mf</a>'
            hours = f"{int(v['hours'])} h {round((v['hours'] % 1) * 60):02d} min" if v["hours"] else "–"
            rows.append([link, v["set"], v["filament"], html.escape(v["process"] or "–"), hours,
                         f"{v['grams']:.0f} g" if v["grams"] else "–", ", ".join(v["parts"])])
        t = data["totals"]
        tot = " · ".join(f"<b>{k.replace('_', ' ')}</b>: {v['hours']:.2f} h, {v['grams']:.0f} g, {v['plates']} plates"
                         for k, v in t.items())
        prints += f"<h3>{printer}</h3>" + table(["Plate", "Set", "Filament", "Preset", "Time", "Filament used",
                                                 "Parts"], rows) + f"<p>{tot}</p>"

    imgs = "".join(
        f'<figure><a href="img/{v}.png"><img src="img/{v}.png" alt="{html.escape(c)}"></a><figcaption>{html.escape(c)}'
        f"</figcaption></figure>" for v, c in VIEWS if (OUT / "img" / f"{v}.png").exists())

    card = ""
    if cut:
        rows = []
        for name, pnl in cut["panels"].items():
            holes = "<br>".join(
                (f"{h['w']:g}×{h['h']:g} rect" if h["kind"] == "rect" else f"Ø{h['d']:g}")
                + f" centred at u={h['u']:.1f}, v={h['v']:.1f}" + (f" — {html.escape(h['note'])}" if h.get("note") else "")
                for h in pnl["holes"][:6]) + (f"<br>… {len(pnl['holes']) - 6} more" if len(pnl["holes"]) > 6 else "")
            rows.append([name, f"{pnl['w']:g} × {pnl['h']:g}", holes or "–"])
        card = (f"<p>Board thickness {cut['board_thickness_mm']:g} mm. u/v are mm from the panel's bottom-left corner, "
                "seen from outside.</p>" + table(["Panel", "Size (mm)", "Cut-outs"], rows)
                + '<p><a href="cardboard/sheet.svg">sheet.svg</a> (all panels, 1:1) · A4 pages: '
                + " ".join(f'<a href="cardboard/{n}_A4.svg">{n}</a>' for n in cut["panels"])
                + '</p><img class=sheet src="cardboard/sheet.svg" alt="cardboard sheet">')

    h = rep["heights"]
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Kaiku robot CAD</title>
<style>
:root{{--bg:#f7f3ec;--ink:#1f2328;--muted:#5f646c;--line:#e2dacd;--accent:#2f6f64}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:24px 16px 64px}}
h1{{margin:0 0 4px}} h2{{margin-top:40px;border-bottom:1px solid var(--line);padding-bottom:6px}}
.muted{{color:var(--muted)}} .ok{{color:var(--accent);font-weight:600}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}}
figure{{margin:0;background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden}}
figure img{{width:100%;display:block}} figcaption{{padding:8px 12px;font-size:13px;color:var(--muted)}}
table{{border-collapse:collapse;width:100%;background:#fff;font-size:13px;display:block;overflow-x:auto}}
th,td{{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}}
th{{background:#f1ebe1}} img.sheet{{width:100%;background:#fff;border:1px solid var(--line);margin-top:8px}}
a{{color:var(--accent)}}
</style></head><body><main>
<h1>Kaiku — desk robot CAD</h1>
<p class=muted>Generated by hardware/cad/overview.py from the CAD report, renders, slicer results and cardboard
template. Local only (hardware/cad/out is gitignored). Assembly STEP: <a href="kaiku_assembly.step">kaiku_assembly.step</a>
· print STLs: <code>stl/</code>.</p>
<p>Body top {h['body_top']:g} mm · head floor {h['head_floor']:.1f} mm · head top {h['head_top']:.1f} mm ·
camera centre {h['camera_centre']:.1f} mm · display centre {h['display_centre']:.1f} mm above the desk.</p>
<h2>Renders and assemblies</h2><div class=grid>{imgs}</div>
<h2>Print plates</h2>{prints or '<p>Run slice.py.</p>'}
<h2>Parts</h2>{fit}{parts}
<h2>Cardboard body</h2>{card or '<p>Run cardboard.py.</p>'}
</main></body></html>"""
    (OUT / "overview.html").write_text(page)
    print(OUT / "overview.html")


if __name__ == "__main__":
    main()
