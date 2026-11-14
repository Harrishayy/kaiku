"""Build the README GIFs in docs/media/ from the real recordings in demo/recordings/ (nothing is drawn or staged).

    uv run python scripts/record_gifs.py                 # all of them
    uv run python scripts/record_gifs.py ios-talk web-dashboard
    uv run python scripts/record_gifs.py --list

Each GIF is a few pieces of one clip, in order: (start, seconds of source, speed). A start is either a number
(seconds into the clip, picked by eye from `<clip>-sheet.png`) or "chapter+offset" from `<clip>-steps.txt`.
After re-recording a clip, check its pieces against the new sheet. Targets: 12 fps, phone GIFs 340 px wide (the
README shows them at 170 to 190 px, so text is twice as sharp as its size there), web 900 px, each under its
`limit` (5 MB unless it says less; the script lowers quality step by step until a GIF fits and says what it used).
The three conversation GIFs (`ios-today-path`, `ios-talk`, `ios-checkin-hard-day`) come from takes against a
private service with the real model key: typed lines, real Gemini Live replies, no sound, no microphone
(`apps/apple/scripts/record_app_demo.sh`, top of the file). Never cut one from a take on the scripted Live.
`mac-app` is cut from `mac-tour.mp4` when a real screen recording exists (`record_app_demo.sh mac`); otherwise
it steps through the in-app renders in `demo/recordings/mac-snapshots/` (`record_app_demo.sh mac-snap`).
Needs ffmpeg and gifsicle.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REC = ROOT / "demo" / "recordings"
OUT = ROOT / "docs" / "media"
LIMIT_MB = 5.0
PAPER = "0xF6EFE4"

# name → clip, width, pieces [(start, source seconds, speed)], seconds to hold the last frame
GIFS: dict[str, dict] = {
    # welcome → what Kaiku is and is not → the choices → permissions → Kaiku's hello → practice dial, "You did it" → Today
    "ios-first-run": {"clip": "iphone-1-first-run", "width": 340, "hold": 1.5, "pieces": [
        (1.5, 3.0, 2.0), (9.0, 6.0, 4.0), (28.0, 12.0, 4.0), (45.0, 12.0, 5.0), (61.0, 4.0, 2.0), (75.0, 12.0, 4.0),
        (95.5, 3.0, 1.5)]},
    # Today with Kaiku's invitation → the first stop as a small chat on an ordinary day (typed lines, real replies;
    # Kaiku wraps it up: "Good to see you") → Lantern: the flame, a touch, a star → the sky she lit
    "ios-today-path": {"clip": "iphone-2-today-path", "width": 340, "hold": 2.0, "limit": 3.0, "pieces": [
        (4.0, 3.6, 1.5), (16.5, 13.5, 2.2), (40.5, 9.0, 2.2), (54.5, 8.5, 1.7), (66.5, 2.4, 1.5), (225.5, 9.5, 1.6),
        (276.0, 6.5, 2.0), (282.5, 2.5, 1.0)]},
    # Seed shelf: the shelf pairs marks with pots → a pot per packet → the sprouts. From the take of 14 Nov 12:16,
    # kept as iphone-2-today-path-dials (the game has not changed since; that take's check-in was the old dials)
    "ios-seed-shelf": {"clip": "iphone-2-today-path-dials", "width": 340, "hold": 2.0, "pieces": [
        (227.5, 3.0, 1.5), (238.0, 12.0, 2.0), (316.0, 12.0, 2.0), (329.5, 5.0, 1.0)]},
    # Talk is a call: it opens, Kaiku says hello → her typed line, Kaiku's answer → she mutes Kaiku: the answer to
    # her next line still comes as captions → the phone locked: her line, then Kaiku's answer on the Lock
    # Screen's bar → "End" there → back in the app: "Call ended."
    "ios-talk": {"clip": "iphone-4-talk", "width": 340, "hold": 2.0, "limit": 3.0, "pieces": [
        (9.5, 6.5, 2.0), (17.0, 9.0, 2.0), (25.8, 2.2, 1.0), (33.0, 10.5, 2.2), (47.5, 12.5, 1.8), (76.5, 5.0, 1.5),
        (85.0, 2.5, 1.0)]},
    # A hard day: the check-in opens → she types that the day is hard, Kaiku's answer → her second line, the
    # answer → "What do you think?", the one offer → the phone locked: her thanks and Kaiku's answer on the bar
    "ios-checkin-hard-day": {"clip": "iphone-8-checkin-hard-day", "width": 340, "hold": 2.5, "limit": 3.0, "pieces": [
        (11.5, 5.0, 1.5), (16.0, 12.5, 2.2), (37.5, 11.0, 2.2), (57.5, 10.5, 2.2), (74.0, 21.5, 2.4)]},
    # History → Your days: the garden → "Today, so far" → What Kaiku saw today, each line with its switch
    "ios-today-so-far": {"clip": "iphone-3-today-so-far", "width": 340, "hold": 1.5, "pieces": [
        (9.5, 3.0, 1.5), (13.0, 17.0, 2.4), (31.5, 12.0, 2.4)]},
    # You → Glasses check with no glasses connected → the self-test running → its three results
    "ios-glasses-check": {"clip": "iphone-5-you-glasses-check", "width": 340, "hold": 2.0, "pieces": [
        (33.0, 5.0, 1.5), (38.0, 14.0, 3.5), (52.5, 18.0, 3.6), (72.0, 4.0, 1.5)]},
    # default view → chart read day by day → Gemma's reading → agent trace → graph with a node picked → daily account
    "web-dashboard": {"clip": "web-dashboard", "width": 900, "hold": 1.5, "pieces": [
        (0.0, 3.5, 1.0), ("trends-hover", 10.0, 2.0), ("gemma-reading-1", 8.0, 2.0), ("agent-trace", 8.0, 2.0),
        ("graph-node-5", 12.0, 2.4), ("reflections-2", 10.0, 2.5)]},
    # a real screen recording when there is one …
    "mac-app": {"clip": "mac-tour", "width": 720, "hold": 1.5, "pieces": [(4.0, 40.0, 4.0)],
                # … else the app's own renders of its panes, 1.8 s each
                # (Talk and You are left out: their text field and switches are drawn as placeholders there)
                "stills": ["mac-snapshots/mac-today.png", "mac-snapshots/mac-play.png", "mac-snapshots/mac-lantern.png",
                           "mac-snapshots/mac-seeds.png", "mac-snapshots/mac-days.png"], "still_seconds": 1.8,
                "crop_top": 44,                     # the renderer cuts the pane's first line in half: leave it out
                "canvas": (720, 492)},
}


def chapters(clip: str) -> dict[str, float]:
    out: dict[str, float] = {}
    steps = REC / f"{clip}-steps.txt"
    if steps.exists():
        for line in steps.read_text().splitlines():
            m = re.match(r"\s*(\d+):([\d.]+)\s+(\S+)", line)
            if m:
                out.setdefault(m.group(3), int(m.group(1)) * 60 + float(m.group(2)))
    return out


def start_of(clip: str, start: float | str) -> float:
    if isinstance(start, (int, float)):
        return float(start)
    m = re.match(r"([a-z0-9-]+?)([+-][\d.]+)?$", start)
    marks = chapters(clip)
    if not m or m.group(1) not in marks:
        sys.exit(f"{clip}: no chapter '{start}' in {clip}-steps.txt (have: {', '.join(marks) or 'none'})")
    return max(0.0, marks[m.group(1)] + float(m.group(2) or 0))


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def palette_tail(colors: int) -> str:
    return (f"split[a][b];[a]palettegen=max_colors={colors}:stats_mode=diff[p];"
            f"[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")


def from_clip(ffmpeg: str, spec: dict, raw: Path, fps: int, colors: int) -> None:
    src = REC / f"{spec['clip']}.mp4"
    pieces = spec["pieces"]
    parts = []
    for i, (start, seconds, speed) in enumerate(pieces):
        hold = f",tpad=stop_mode=clone:stop_duration={spec.get('hold', 1.5)}" if i == len(pieces) - 1 else ""
        parts.append(f"[0:v]trim=start={start_of(spec['clip'], start):.2f}:duration={seconds:.2f},"
                     f"setpts=(PTS-STARTPTS)/{speed},fps={fps},scale={spec['width']}:-2:flags=lanczos{hold}[v{i}]")
    joined = "".join(f"[v{i}]" for i in range(len(pieces)))
    graph = ";".join(parts) + f";{joined}concat=n={len(pieces)}:v=1[v];[v]{palette_tail(colors)}"
    run(ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-filter_complex", graph, "-loop", "0", str(raw))


def from_stills(ffmpeg: str, spec: dict, raw: Path, fps: int, colors: int) -> None:
    stills = [REC / s for s in spec["stills"] if (REC / s).exists()]
    if not stills:
        sys.exit("mac-app: no screen recording and no in-app renders (run record_app_demo.sh mac or mac-snap first)")
    w, h = spec["canvas"]
    secs, fade = spec["still_seconds"], 0.35
    args, parts = [], []
    for i, s in enumerate(stills):
        args += ["-loop", "1", "-t", f"{secs + fade}", "-i", str(s)]
        parts.append(f"[{i}:v]crop=iw:ih-{spec.get('crop_top', 0)}:0:{spec.get('crop_top', 0)},"
                     f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={PAPER},"
                     f"fps={fps},format=rgb24,setsar=1[s{i}]")
    last = "s0"
    for i in range(1, len(stills)):
        parts.append(f"[{last}][s{i}]xfade=transition=fade:duration={fade}:offset={i * secs:.2f}[x{i}]")
        last = f"x{i}"
    graph = ";".join(parts) + f";[{last}]{palette_tail(colors)}"
    run(ffmpeg, "-y", "-loglevel", "error", *args, "-filter_complex", graph, "-loop", "0", str(raw))


def build(name: str, ffmpeg: str, gifsicle: str) -> None:
    spec = GIFS[name]
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{name}.gif"
    real = (REC / f"{spec['clip']}.mp4").exists()
    if not real and "stills" not in spec:
        sys.exit(f"{name}: demo/recordings/{spec['clip']}.mp4 is missing (record it first)")
    if real and not spec["pieces"]:
        sys.exit(f"{name}: no pieces chosen yet")
    with tempfile.TemporaryDirectory(prefix="kaiku-gif-") as tmp:
        raw = Path(tmp) / "raw.gif"
        limit = spec.get("limit", LIMIT_MB)
        # quality ladder: stop at the first rung that fits
        for fps, colors, lossy in ((12, 128, 30), (12, 96, 60), (10, 80, 90), (10, 64, 140), (8, 48, 200)):
            (from_clip if real else from_stills)(ffmpeg, spec, raw, fps, colors)
            run(gifsicle, "-O3", f"--lossy={lossy}", str(raw), "-o", str(out))
            mb = out.stat().st_size / 1e6
            if mb <= limit:
                break
    kind = "clip" if real else "in-app renders (no screen recording found)"
    print(f"{out.relative_to(ROOT)}  {mb:.2f} MB  {fps} fps, {colors} colours, lossy {lossy}  from {kind}")
    if mb > limit:
        print(f"  still over {limit} MB: shorten its pieces")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="which GIFs (default: all)")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for n, s in GIFS.items():
            print(f"{n}: {s['clip']}.mp4 {s['pieces']}")
        return
    ffmpeg, gifsicle = shutil.which("ffmpeg"), shutil.which("gifsicle")
    if not ffmpeg or not gifsicle:
        sys.exit("needs ffmpeg and gifsicle (brew install ffmpeg gifsicle)")
    for n in a.names or list(GIFS):
        if n not in GIFS:
            sys.exit(f"unknown GIF '{n}' (have: {', '.join(GIFS)})")
        build(n, ffmpeg, gifsicle)


if __name__ == "__main__":
    main()
