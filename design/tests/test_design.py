"""design/ checks: generated files fresh, mascot parts named, spec consistent, palette readable."""

from __future__ import annotations

import importlib.util
import json
import xml.etree.ElementTree as ET
from pathlib import Path

DESIGN = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("kaiku_design_gen", DESIGN / "gen.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

TOKENS = json.loads((DESIGN / "tokens.json").read_text())
SPEC = json.loads((DESIGN / "mascot.spec.json").read_text())
REQUIRED_PARTS = {"body", "shadow", "eye-l", "eye-r", "lid-l", "lid-r", "ear", "glow", "mouth-happy",
                  "mouth-yawn", "scarf", "z"}
REQUIRED_STATES = {"idle", "listening", "thinking", "happy", "cheering", "breathing", "sleepy", "walking",
                   "cozy", "peek"}


def _parts(nodes):
    for p in nodes:
        yield p
        yield from _parts(p.get("children", []))


PARTS = {p["id"]: p for p in _parts(SPEC["parts"])}


def test_generated_files_are_fresh():
    assert gen.stale() == [], "run `make design` and commit design/generated + design/mascot.svg"


def test_gen_writes_to_any_dir(tmp_path):
    assert gen.main(["--out", str(tmp_path)]) == 0
    for rel in gen.OUTPUTS:
        assert (tmp_path / rel).read_text() == (DESIGN / rel).read_text()
    assert gen.main(["--out", str(tmp_path), "--check"]) == 0


def test_svg_has_every_named_part():
    root = ET.parse(DESIGN / "mascot.svg").getroot()
    ids = {el.get("id") for el in root.iter() if el.get("id")}
    assert REQUIRED_PARTS <= ids
    assert set(PARTS) <= ids
    assert root.get("viewBox") == "0 0 200 200"


def test_states_cover_the_plan_and_reference_real_parts():
    assert REQUIRED_STATES <= set(SPEC["states"])
    for name, st in SPEC["states"].items():
        assert st["blink"] in SPEC["blink"]["modes"], name
        tracks = list(st["tracks"]) + [t for ev in st.get("events", {}).values() for t in ev["tracks"]]
        for part in [*st["pose"], *(t["part"] for t in tracks)]:
            assert part in PARTS, f"{name}: unknown part {part}"
        for t in tracks:
            assert t["prop"] in SPEC["props"], f"{name}: unknown prop {t['prop']}"
            assert t["easing"] in TOKENS["motion"]["easing"], f"{name}: unknown easing {t['easing']}"
            ts = [k[0] for k in t["keys"]]
            assert ts[0] == 0 and ts[-1] == 1 and ts == sorted(ts), f"{name}: keys must run 0..1"
        props = [(t["part"], t["prop"]) for t in st["tracks"]]
        assert len(props) == len(set(props)), f"{name}: one track per part+prop"


def test_colour_refs_exist_in_both_themes():
    light, dark = TOKENS["color"]["light"], TOKENS["color"]["dark"]
    assert set(light) == set(dark)
    for p in PARTS.values():
        for s in p.get("shapes", []):
            for key in ("fill", "stroke"):
                ref = s.get(key)
                if ref and ref not in ("none", "glow"):
                    assert ref in light, f"{p['id']}: unknown colour token {ref}"


def _lum(hexcol: str) -> float:
    c = [int(hexcol.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_text_colours_are_readable_in_both_themes():
    for theme in ("light", "dark"):
        c = TOKENS["color"][theme]
        for fg in ("ink", "ink-2", "muted", "clay", "sage", "sky", "honey", "crisis"):
            for bg in ("bg", "surface"):
                assert _contrast(c[fg], c[bg]) >= 4.5, f"{theme}: {fg} on {bg} is {_contrast(c[fg], c[bg]):.2f}"
        assert _contrast(c["clay-ink"], c["clay"]) >= 4.5, f"{theme}: button text on clay"


def test_motion_budget():
    d = TOKENS["motion"]["duration"]
    assert all(v >= 300 for k, v in d.items() if k not in ("blink",)), "character motion is never faster than 300 ms"
    gb = TOKENS["motion"]["guide-breath"]
    assert 60000 / gb["breaths-per-minute"] == SPEC["states"]["breathing"]["duration"]
