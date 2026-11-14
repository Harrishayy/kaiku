"""Assemble the draft cut of the demo video from the clips in demo/recordings (no voiceover, no invented footage).

    uv run --with pillow python demo/draft_cut.py            # → demo/recordings/kaiku-draft-cut.mp4 (+ -sheet.png)

The order follows docs/demo-narrative.md. Each entry of CUT is either a card (a plain 2-second card naming a shot
that still has to be filmed with real hardware or people) or a piece of an existing clip: (clip, chapter, offset
into the chapter, seconds of source, speed). Chapters come from <clip>-steps.txt, so a re-recorded clip keeps
working; chapter "@" means the offset is an absolute time in the clip (used for the first-run clip, whose chapter
codes run several seconds late: check those pieces by eye after re-recording it). Long stretches are sped up; nothing is reordered inside a piece. Phone clips sit centred on the paper
background; every piece carries a small caption saying what it is (simulator, simulated record).
The printed table (also written to demo/recordings/kaiku-draft-cut-timeline.txt) gives each piece's place in
the cut: copy it into demo/draft-cut-narration.md when the cut changes.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
REC = ROOT / "recordings"
W, H, FPS = 1920, 1080, 30
PAPER, INK, MUTED, CLAY = (246, 239, 228), (59, 47, 42), (122, 106, 96), (158, 75, 50)
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"
FONT = "/System/Library/Fonts/Helvetica.ttc"
PHONE = "iPhone simulator · simulated record · no model calls in this take"
DASH = "Practitioner dashboard · simulated record"

# kind, then: card → (title, what to film) | clip → (file stem, chapter, offset s, source s, speed, caption)
CUT: list[tuple] = [
    ("card", "Shot 1: cold open", "To film: kitchen table, appointment card with twenty dates crossed out, phone face down"),
    ("clip", "iphone-1-first-run", "@", 0.2, 3.0, 1.0, PHONE),      # welcome
    ("clip", "iphone-1-first-run", "@", 12.0, 6.0, 2.0, PHONE),     # nearby services → continue without connecting
    ("clip", "iphone-1-first-run", "@", 24.0, 12.0, 2.0, PHONE),    # the choices, one switch each
    ("clip", "iphone-1-first-run", "@", 41.0, 12.0, 3.0, PHONE),    # permissions asked from their own rows
    ("clip", "iphone-1-first-run", "@", 60.0, 26.0, 4.0, PHONE),    # hello, practice dial, "You did it", Today
    ("card", "Shot 3: Kaiku's voice", "To record on a real iPhone with sound: she says good morning, Kaiku answers aloud (Gemini Live)"),
    ("clip", "iphone-4-talk", "typing", 0.0, 14.0, 2.0, PHONE + " · typed fallback, no voice"),
    ("clip", "iphone-2-today-path", "lantern", 20.0, 16.0, 1.6, PHONE),
    ("clip", "iphone-2-today-path", "rotating-game", -8.0, 4.0, 1.0, PHONE),
    ("clip", "iphone-2-today-path", "rotating-game", 14.0, 8.0, 2.0, PHONE),
    ("clip", "iphone-2-today-path", "all-done", 2.0, 4.0, 1.0, PHONE),
    ("card", "Shot 5: walk with the glasses", "To film outdoors with the real Ray-Ban Meta (docs/glasses-test.md): voice in her ear, phone in her pocket"),
    ("clip", "iphone-3-today-so-far", "today-so-far", 0.0, 7.5, 1.5, PHONE),
    ("card", "Shot 6: the robot ritual", "To film: the robot on her desk. Eyes open, three turns of the ear dial, one breath, a drum"),
    ("card", "Shot 7: Mac menu bar", "To record with QuickTime: category minutes, breaks and the pause switch"),
    ("clip", "web-dashboard", "default-view", 0.0, 4.0, 1.0, DASH),
    ("clip", "web-dashboard", "trends-hover", 0.0, 12.0, 1.6, DASH),
    ("clip", "web-dashboard", "gemma-reading", -2.0, 12.0, 1.5, DASH + " · review written by Gemma (cached)"),
    ("clip", "web-dashboard", "agent-trace", 0.0, 10.0, 2.0, DASH),
    ("clip", "web-dashboard", "graph-node", -6.0, 14.0, 2.3, DASH),
    ("clip", "web-dashboard", "reflections", -2.0, 12.0, 2.0, DASH),
    ("clip", "web-dashboard", "collapse-and-move", 0.0, 10.0, 2.5, DASH),
    ("card", "Shot 10: the follow-up", "To record on the dashboard: one click records a care action; the following days sit beside it"),
    ("card", "Kaiku", "End card to film: robot, phone and glasses on the table. Research prototype, not a medical device"),
]
CARD_SECONDS = 2.0


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size)


def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=f) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + [line]


def card_png(path: Path, title: str, body: str) -> None:
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    big, small, tag = font(FONT_BOLD, 76), font(FONT, 38), font(FONT_BOLD, 26)
    d.text((W / 2, H / 2 - 150), "PLACEHOLDER: NOT YET FILMED", font=tag, fill=CLAY, anchor="mm")
    d.text((W / 2, H / 2 - 60), title, font=big, fill=INK, anchor="mm")
    for i, line in enumerate(wrap(d, body, small, 1400)):
        d.text((W / 2, H / 2 + 40 + i * 52), line, font=small, fill=MUTED, anchor="mm")
    im.save(path)


def caption_png(path: Path, text: str) -> None:
    f = font(FONT, 24)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    w = int(probe.textlength(text, font=f)) + 36
    im = Image.new("RGBA", (w, 44), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, 43), radius=12, fill=(59, 47, 42, 200))
    d.text((18, 22), text, font=f, fill=(255, 250, 243, 255), anchor="lm")
    im.save(path)


def chapters(stem: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in (REC / f"{stem}-steps.txt").read_text().splitlines():
        m = re.match(r"\s*(\d+):([\d.]+)\s+(\S+)", line)
        if m:
            out.setdefault(m.group(3), int(m.group(1)) * 60 + float(m.group(2)))
    return out


def run(ffmpeg: str, *args: str) -> None:
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", *args], check=True)


def main() -> None:
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    tmp = Path(tempfile.mkdtemp(prefix="kaiku-cut-"))
    enc = ["-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-an"]
    parts: list[Path] = []
    rows: list[str] = []
    t = 0.0
    for i, item in enumerate(CUT):
        seg = tmp / f"{i:02d}.mp4"
        if item[0] == "card":
            _, title, body = item
            png = tmp / f"{i:02d}.png"
            card_png(png, title, body)
            run(ffmpeg, "-loop", "1", "-t", f"{CARD_SECONDS}", "-i", str(png), *enc, str(seg))
            length, what = CARD_SECONDS, f"PLACEHOLDER  {title}: {body}"
        else:
            _, stem, chapter, offset, source, speed, caption = item
            if chapter == "@":                      # an absolute time in the clip, picked by eye
                start = offset
            else:
                marks = chapters(stem)
                if chapter not in marks:
                    sys.exit(f"{stem}: no chapter '{chapter}' in {stem}-steps.txt (have: {', '.join(marks)})")
                start = max(0.0, marks[chapter] + offset)
            cap = tmp / f"{i:02d}-cap.png"
            caption_png(cap, caption)
            fit = f"scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2"
            graph = (f"[0:v]trim=start={start:.2f}:duration={source:.2f},setpts=(PTS-STARTPTS)/{speed},{fit},"
                     f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0xF6EFE4,fps={FPS}[v];[v][1:v]overlay=28:H-h-24[o]")
            run(ffmpeg, "-i", str(REC / f"{stem}.mp4"), "-i", str(cap), "-filter_complex", graph, "-map", "[o]", *enc, str(seg))
            length = source / speed
            what = f"{stem} · {chapter}{offset:+.0f}s · {source:.0f}s of source at {speed:g}x"
        rows.append(f"{int(t // 60)}:{t % 60:04.1f}–{int((t + length) // 60)}:{(t + length) % 60:04.1f}  {what}")
        t += length
        parts.append(seg)
    listing = tmp / "list.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in parts))
    out = REC / "kaiku-draft-cut.mp4"
    run(ffmpeg, "-f", "concat", "-safe", "0", "-i", str(listing), *enc, "-movflags", "+faststart", str(out))
    run(ffmpeg, "-i", str(out), "-vf", f"fps=24/{t:.2f},scale=480:-2,tile=6x4:padding=6:color=white", "-frames:v", "1",
        str(REC / "kaiku-draft-cut-sheet.png"))
    (REC / "kaiku-draft-cut-timeline.txt").write_text("\n".join(rows) + f"\n\ntotal {int(t // 60)}:{t % 60:04.1f}\n")
    print("\n".join(rows))
    print(f"\n{out}  {out.stat().st_size / 1e6:.1f} MB  {int(t // 60)}:{t % 60:04.1f}")
    if t > 118:
        sys.exit("longer than 1:58: shorten a piece")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
