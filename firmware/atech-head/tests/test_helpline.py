"""The helpline lines the head shows on `cmd.head {show: "help"}`: the same as the ground truth, and laid out to fit.

1. `kaiku_link/helpline.h` must say exactly what `config/kaiku.toml [safety]` says (the hub prints those three lines
   in its crisis path): a different number on the robot's own screen would be a safety fault.
2. No other firmware source carries a copy of the name or the number.
3. `kaiku_link/help_screen.h`, the layout both firmwares and the bench compile, is built for this computer and must
   keep every row inside the upright 80 x 160 screen and the wide 160 x 80 one, complete, in order, the numbers large.

Nothing here says how readable the real display is: that is the bench's question (bench/speaker_pcm).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]  # firmware/atech-head
ROOT = HEAD.parents[1]
LINK = HEAD / "kaiku_link"


def _defines() -> dict[str, str]:
    text = (LINK / "helpline.h").read_text()
    out = dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', text, re.M))
    out.update(re.findall(r"^#define\s+(HELP_SHOW_MS)\s+(\d+)", text, re.M))
    return out


def test_firmware_lines_equal_the_config():
    safety = tomllib.loads((ROOT / "config" / "kaiku.toml").read_text())["safety"]
    d = _defines()
    assert d["HELPLINE_NAME"] == safety["helpline_name"]
    assert d["HELPLINE_NUMBER"] == safety["helpline_number"]
    assert d["EMERGENCY_NUMBER"] == safety["emergency_number"]
    assert int(d["HELP_SHOW_MS"]) == 10 * 60 * 1000  # cmd.head `show`: "until none, a new ritual, or 10 minutes"


def test_no_second_copy_of_the_lines_in_the_firmware():
    d = _defines()
    skip = {"build", ".venv", ".pio", "tests", "recordings"}
    copies = [str(p.relative_to(HEAD)) for p in HEAD.rglob("*")
              if p.is_file() and p.suffix in {".h", ".cpp", ".yaml", ".toml", ".py", ".sh", ".ino"}
              and not skip & set(p.relative_to(HEAD).parts) and p.name != "helpline.h"
              and any(v in p.read_text(errors="replace") for v in (d["HELPLINE_NAME"], d["HELPLINE_NUMBER"]))]
    assert not copies, f"the helpline lines belong in kaiku_link/helpline.h only, also found in {copies}"


DRIVER = r"""
#include <cstdio>
#include <cstdlib>
#include "help_screen.h"
int main(int, char** argv) {
  help_screen::draw(atoi(argv[1]), atoi(argv[2]), [](const char* t, int x, int y, int s, uint16_t c) {
    printf("%d\t%d\t%d\t%u\t%s\n", x, y, s, (unsigned)c, t);
  });
  return 0;
}
"""


@pytest.fixture(scope="module")
def layout(tmp_path_factory):
    cxx = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    if not cxx:
        pytest.skip("no C++ compiler on this computer: the help screen layout is not checked here")
    tmp = tmp_path_factory.mktemp("help_screen")
    (tmp / "driver.cpp").write_text(DRIVER)
    subprocess.run([cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(LINK), str(tmp / "driver.cpp"),
                    "-o", str(tmp / "driver")], check=True)

    def rows(w: int, h: int) -> list[dict]:
        out = subprocess.run([str(tmp / "driver"), str(w), str(h)], check=True, capture_output=True, text=True).stdout
        return [dict(x=int(x), y=int(y), size=int(s), color=int(c), text=t)
                for x, y, s, c, t in (line.split("\t") for line in out.splitlines())]

    return rows


# screen (w, h) -> the smallest font size each line may come out at (helpline number, emergency number)
SCREENS = {(80, 160): (3, 4), (160, 80): (2, 3)}  # upright: the standalone and the bench; wide: the MQTT firmware


@pytest.mark.parametrize("screen", SCREENS)
def test_help_screen_fits_and_is_complete(layout, screen):
    w, h = screen
    rows, d = layout(w, h), _defines()
    assert rows, "nothing was drawn"
    for r in rows:  # every row inside the screen: 6 x 8 pixels a character at size 1, the last spacing column free
        right, bottom = r["x"] + len(r["text"]) * 6 * r["size"] - r["size"], r["y"] + 8 * r["size"]
        assert 0 <= r["x"] and right <= w and 0 <= r["y"] and bottom <= h, f"{r} leaves the {w} x {h} screen"
    for a, b in zip(rows, rows[1:], strict=False):  # top to bottom, never overlapping
        assert b["y"] >= a["y"] + 8 * a["size"], f"{a['text']!r} and {b['text']!r} overlap"
    by_color: dict[int, list[dict]] = {}
    for r in rows:
        by_color.setdefault(r["color"], []).append(r)
    lines = [" ".join(r["text"] for r in group) for group in by_color.values()]  # dicts keep the drawing order
    assert lines == [d["HELPLINE_NAME"], d["HELPLINE_NUMBER"], d["EMERGENCY_NUMBER"]]
    name, number, emergency = by_color.values()
    min_number, min_emergency = SCREENS[screen]
    assert min(r["size"] for r in number) >= min_number, "the helpline number came out smaller than it was"
    assert min(r["size"] for r in emergency) >= min_emergency, "the emergency number came out smaller than it was"
    assert all(r["size"] >= 1 for r in name)
