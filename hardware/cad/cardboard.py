# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Cardboard body template, generated from the same numbers as the printed body.

Run:  uv run --script hardware/cad/cardboard.py [--t 4]      (after kaiku_cad.py; --t = board thickness, mm)
Out:  hardware/cad/out/cardboard/sheet.svg        all six panels, 1:1, with every hole
      hardware/cad/out/cardboard/<panel>_A4.svg   one panel per A4 page at 1:1 (print at 100 %, check the 50 mm bar)
      hardware/cad/out/cardboard/cutlist.json     panel sizes and hole centres, mm from each panel's bottom-left

Panels are drawn as seen from OUTSIDE the robot. u runs left to right, v runs bottom to top.
Construction: bottom panel; front and back stand on it; the sides sit between them; the lid is a loose
104 x 136 panel resting on the walls (removable for access), located by four strips glued under it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "out" / "cardboard"


def panels(f: dict, t: float) -> dict:
    W, D, H = f["outer"]
    wall_h = H - 2 * t                       # bottom and lid thickness above/below the walls
    side_l = D - 2 * t
    P = {
        "front": {"w": W, "h": wall_h, "holes": []},
        "back": {"w": W, "h": wall_h, "holes": []},
        "left": {"w": side_l, "h": wall_h, "holes": []},
        "right": {"w": side_l, "h": wall_h, "holes": []},
        "lid": {"w": W, "h": D, "holes": []},
        "bottom": {"w": W, "h": D, "holes": []},
    }
    # front, seen from the front: u = x + W/2, v = z - t
    g = f["front_grille"]
    P["front"]["holes"].append({"kind": "rect", "u": g["x"] + W / 2, "v": g["z"] - t, "w": g["w"], "h": g["h"],
                                "note": "chest window: cover with tracing paper from inside, LED grids behind"})
    # right side, seen from the right: u = y - (-D/2 + t)
    for y, z in f["speaker_holes"]:
        P["right"]["holes"].append({"kind": "circle", "u": y + D / 2 - t, "v": z - t, "d": 3.2})
    P["right"]["holes"][0]["note"] = "speaker grille: poke 35 holes with a skewer"
    # back, seen from behind: u = W/2 - x
    for key, note in (("rear_cable_slot", "USB cables: UNO Q, camera"), ("rear_usbc", "Atech USB-C power")):
        r = f[key]
        P["back"]["holes"].append({"kind": "rect", "u": W / 2 - r["x"], "v": r["z"] - t, "w": r["w"], "h": r["h"],
                                   "note": note})
    # lid, seen from above, front edge at the bottom: u = x + W/2, v = y + D/2
    r = f["lid_pan_hole"]
    P["lid"]["holes"].append({"kind": "rect", "u": r["x"] + W / 2, "v": r["y"] + D / 2, "w": r["w"], "h": r["d"],
                              "note": "pan motor sleeve drops through; the printed pan base glues on top"})
    r = f["lid_button"]
    P["lid"]["holes"].append({"kind": "rect", "u": r["x"] + W / 2, "v": r["y"] + D / 2, "w": r["w"], "h": r["d"],
                              "note": "button module (or its cable) comes out here"})
    for key, note in (("lid_finger_hole", "pulse sensor window, finger cradle glues over it"),
                      ("lid_lift_hole", "finger hole to lift the lid"),
                      ("lid_light_hole", "KY-054 room-light sensor looks up through this")):
        r = f[key]
        P["lid"]["holes"].append({"kind": "circle", "u": r["x"] + W / 2, "v": r["y"] + D / 2, "d": r["d"],
                                  "note": note})
    r = f["pan_base_flange"]
    P["lid"]["outline_marks"] = [{"u": r["x"] + W / 2, "v": r["y"] + D / 2, "w": r["w"], "h": r["d"],
                                  "note": "pan base flange outline (glue area)"}]
    return P


def svg_panel(name: str, pnl: dict, ox: float, oy: float) -> list[str]:
    """SVG elements for one panel with its bottom-left at (ox, oy + h) in SVG coordinates (y down)."""
    w, h = pnl["w"], pnl["h"]
    top = oy
    el = [f'<rect x="{ox}" y="{top}" width="{w}" height="{h}" fill="none" stroke="#000" stroke-width="0.4"/>',
          f'<text x="{ox + 2}" y="{top - 2}" font-size="4" font-family="sans-serif">{name.upper()}  '
          f'{w:g} x {h:g} mm  (outside face)</text>']
    for m in pnl.get("outline_marks", []):
        x0, y0 = ox + m["u"] - m["w"] / 2, top + h - m["v"] - m["h"] / 2
        el.append(f'<rect x="{x0}" y="{y0}" width="{m["w"]}" height="{m["h"]}" rx="6" fill="none" stroke="#2f6f64" '
                  f'stroke-width="0.3" stroke-dasharray="2,1.5"/>')
    for hole in pnl["holes"]:
        cx, cy = ox + hole["u"], top + h - hole["v"]
        if hole["kind"] == "rect":
            el.append(f'<rect x="{cx - hole["w"] / 2}" y="{cy - hole["h"] / 2}" width="{hole["w"]}" height="{hole["h"]}" '
                      f'fill="none" stroke="#c0392b" stroke-width="0.4"/>')
            el.append(f'<text x="{cx}" y="{cy + 1.2}" font-size="2.6" text-anchor="middle" font-family="sans-serif" '
                      f'fill="#c0392b">{hole["w"]:g}x{hole["h"]:g} @ {hole["u"]:g},{hole["v"]:g}</text>')
        else:
            el.append(f'<circle cx="{cx}" cy="{cy}" r="{hole["d"] / 2}" fill="none" stroke="#c0392b" stroke-width="0.3"/>')
        el.append(f'<path d="M{cx - 1.5},{cy} h3 M{cx},{cy - 1.5} v3" stroke="#c0392b" stroke-width="0.15"/>')
    return el


def page(elements: list[str], w: float, h: float) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">'
            f'<rect width="{w}" height="{h}" fill="#fff"/>' + "".join(elements) + "</svg>")


def scale_bar(x: float, y: float) -> str:
    return (f'<path d="M{x},{y} h50 M{x},{y - 2} v4 M{x + 50},{y - 2} v4" stroke="#000" stroke-width="0.4"/>'
            f'<text x="{x}" y="{y + 5}" font-size="3" font-family="sans-serif">50 mm: measure before cutting</text>')


def main():
    t = 4.0
    if "--t" in sys.argv:
        t = float(sys.argv[sys.argv.index("--t") + 1])
    rep = json.loads((HERE / "out" / "report.json").read_text())
    P = panels(rep["body_features"], t)
    OUT.mkdir(parents=True, exist_ok=True)
    # combined sheet
    els, x, y, row_h = [], 10.0, 12.0, 0.0
    for name in ("front", "back", "left", "right"):
        els += svg_panel(name, P[name], x, y)
        x += P[name]["w"] + 12
        row_h = max(row_h, P[name]["h"])
    width = x
    x, y = 10.0, y + row_h + 16
    for name in ("lid", "bottom"):
        els += svg_panel(name, P[name], x, y)
        x += P[name]["w"] + 12
    els.append(scale_bar(x + 10, y + 20))
    els.append(f'<text x="{x + 10}" y="{y + 34}" font-size="3.4" font-family="sans-serif">Board thickness t = {t:g} mm. '
               'Black = panel edge, red = cut-out, green dashed = glue area.</text>')
    height = y + max(P["lid"]["h"], P["bottom"]["h"]) + 12
    (OUT / "sheet.svg").write_text(page(els, max(width, x + 160), height))
    # one panel per A4 page
    for name, pnl in P.items():
        ox = (210 - pnl["w"]) / 2
        els = svg_panel(name, pnl, ox, 30) + [scale_bar(20, 30 + pnl["h"] + 25)]
        (OUT / f"{name}_A4.svg").write_text(page(els, 210, 297))
    (OUT / "cutlist.json").write_text(json.dumps({"board_thickness_mm": t, "panels": P}, indent=1))
    for name, pnl in P.items():
        print(f"{name:7s} {pnl['w']:6.1f} x {pnl['h']:6.1f} mm, {len(pnl['holes'])} cut-outs")


if __name__ == "__main__":
    main()
