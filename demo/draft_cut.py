"""Assemble the draft cut of the demo video from the clips in demo/recordings (no invented footage).

SUPERSEDED (15 Nov): this builds the earlier 1:55 cut; the video now follows the 1:58 script in docs/demo-narrative.md.

    uv run --with pillow python demo/draft_cut.py     # → demo/recordings/kaiku-draft-cut.mp4, -sheet.png, -timeline.txt

The order follows the shot table in docs/demo-narrative.md. CUT is the whole edit, top to bottom. An entry is

- a piece of a recorded clip: `clip` (file stem), `at` (seconds into the clip, picked by eye from its
  `-sheet.png`, or "chapter+offset" from its `-steps.txt`), `take` (seconds of source), `speed`, a `title` (what
  the judge is looking at, in a few words), and optionally `voice`: [(file in recordings/voice/, seconds into the
  piece)]: Kaiku's own lines, saved by `scripts/record_voice.py`. A piece with a voice runs at 1x. A missing voice
  file leaves the piece silent.
- a still: `still` (an image, path from the repo root), `seconds`, `title`, `note`.
- or a shot that needs people or hardware: `film` names the file to drop into demo/recordings/ (it then plays for
  `seconds`, with its own sound). Until it exists, its `standin` pieces play in its place when it has any (a
  typed simulator take, the simulated glasses, the app's own renders: each says so in clay capitals above its
  title); otherwise a plain card naming the shot stands in for `card_seconds`.

Phone pieces sit beside their title; dashboard pieces and stills sit above it. Every piece says where its picture
comes from. After re-recording a clip, check the `at` values against its new sheet.
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
VOICE = REC / "voice"
W, H, FPS = 1920, 1080, 30
PAPER, INK, MUTED, CLAY = (246, 239, 228), (59, 47, 42), (122, 106, 96), (158, 75, 50)
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"
FONT = "/System/Library/Fonts/Helvetica.ttc"
PHONE = "iPhone app on the simulator. Simulated record, no model calls in this take."
# the conversations: a private service with the real model key; her lines typed, the microphone never opened
TYPED = ("iPhone app on the simulator. Her lines are typed (microphone off); every answer is the real Gemini Live "
         "reply of this take. No sound was recorded.")
DASH = "Practitioner dashboard, public deployment. Simulated record."
CARD_SECONDS = 2.0
LIMIT = 118.0


def cut() -> list[dict]:
    return [
        {"film": "shot-01-cold-open.mp4", "seconds": 10, "card": "Shot 1: cold open",
         "body": "To film: kitchen table, appointment card with twenty dates crossed out, phone face down"},
        *FIRST_RUN,
        {"film": "shot-03-voice.mp4", "seconds": 16, "card": "Shot 3: the check-in on a hard day, in her real voice",
         "body": "To record on the iPhone with sound: she says the day is hard, Kaiku stays and offers one thing once, "
                 "she locks the phone and the call goes on as a bar on the Lock Screen",
         "standin": CHECK_IN},
        *LANTERN,
        {"film": "shot-05-glasses.mp4", "seconds": 16, "card": "Shot 5: walk with the glasses",
         "body": "To film outdoors with the real Ray-Ban Meta (docs/glasses-test.md): the style set to Playful, Kaiku "
                 "in her ear, a spotting count, the glasses coming off",
         "standin": WALK},
        {"film": "shot-06-robot.mp4", "seconds": 15, "card": "Shot 6: the robot ritual",
         "body": "To film: the robot on her desk. Eyes open, three turns of the ear dial, one breath, a drum"},
        {"film": "shot-07-mac.mp4", "seconds": 8, "card": "Shot 7: quick talk on the Mac",
         "body": "To record on the Mac: two taps of Control, she says she is not feeling too well, captions of both",
         "standin": QUICK_TALK},
        *DASHBOARD,
        {"film": "shot-10-care-action.mp4", "seconds": 6, "card": "Shot 10: the follow-up",
         "body": "To record on the dashboard: one click records a care action; the following days sit beside it"},
        {"film": "shot-11-end.mp4", "seconds": 4, "card": "Kaiku",
         "body": "End card to film: robot, phone and glasses on the table. Research prototype, not a medical device"},
    ]


# --- the pieces (edit these) ----------------------------------------------------------------------------------------
VOICED = " Sound: the line the app played, from the service's voice cache."
FIRST_RUN: list[dict] = [
    {"clip": "iphone-1-first-run", "at": 9.0, "take": 6.0, "speed": 3.0, "note": PHONE,
     "title": "First run: what Kaiku is, and what it is not"},
    {"clip": "iphone-1-first-run", "at": 27.5, "take": 12.5, "speed": 2.5, "note": PHONE,
     "title": "Every signal is a choice, with its own switch"},
    {"clip": "iphone-1-first-run", "at": 60.2, "take": 9.6, "speed": 1.0, "note": PHONE + VOICED,
     "title": "Kaiku has one voice", "voice": [("welcome.hello.wav", 0.6)]},
]
# Stand-in for shot 3 until it is filmed with her voice: one typed take of the check-in on a hard day, ending on
# the Lock Screen (iphone-8-checkin-hard-day: real Gemini Live replies, no sound, microphone off).
STANDIN_TYPED = "STAND-IN: TYPED ON THE SIMULATOR, NOT HER VOICE YET"
CHECK_IN: list[dict] = [
    {"clip": "iphone-8-checkin-hard-day", "at": 16.0, "take": 13.0, "speed": 2.0, "note": TYPED, "tag": STANDIN_TYPED,
     "title": "The check-in is a small chat. On a hard day Kaiku stays"},
    {"clip": "iphone-8-checkin-hard-day", "at": 57.5, "take": 10.5, "speed": 2.0, "note": TYPED, "tag": STANDIN_TYPED,
     "title": "It offers one thing, once"},
    {"clip": "iphone-8-checkin-hard-day", "at": 74.0, "take": 21.0, "speed": 2.4, "note": TYPED, "tag": STANDIN_TYPED,
     "title": "She locks the phone. The call goes on as a bar on the Lock Screen"},
]
GAME = "iPhone app on the simulator. Simulated record. The game itself calls no model."
LANTERN: list[dict] = [
    {"clip": "iphone-2-today-path", "at": 225.5, "take": 9.5, "speed": 1.6, "note": GAME,
     "title": "Lantern: a reaction-time reading inside a game"},
    {"clip": "iphone-2-today-path", "at": 276.5, "take": 8.0, "speed": 2.0, "note": GAME,
     "title": "No score. The sky she lit"},
]
# Stand-in for shot 5: the walk on the simulator with simulated glasses. There is no microphone there, so there is
# no conversation in it (the walk screen says so): only the style choice and the spotting count, which are the app's.
STANDIN_GLASSES = "STAND-IN: SIMULATED GLASSES"
SIMULATED = ("iPhone app on the simulator with simulated glasses and no microphone: no conversation in this take, "
             "and no model calls. Not filmed on the real glasses yet.")
WALK: list[dict] = [
    {"clip": "iphone-7-glasses-walk-simulated", "at": 6.5, "take": 16.0, "speed": 3.2, "note": SIMULATED,
     "tag": STANDIN_GLASSES, "title": "A walk starts with how Kaiku walks with her: Calm, Playful or Chatty"},
    {"clip": "iphone-7-glasses-walk-simulated", "at": 37.5, "take": 11.0, "speed": 2.2, "note": SIMULATED,
     "tag": STANDIN_GLASSES, "title": "A spotting game, counted on the phone"},
    {"clip": "iphone-7-glasses-walk-simulated", "at": 53.0, "take": 8.0, "speed": 2.0, "note": SIMULATED,
     "tag": STANDIN_GLASSES, "title": "The same count in the Dynamic Island, phone in her pocket"},
]
# Stand-in for shot 7: the Mac app's own renders of quick talk (drawn from seeded states, not a screen capture).
RENDERED = ("Drawn by the Mac app itself from a seeded state: not a screen capture, and the words in it are layout "
            "text, not a model's reply.")
QUICK_TALK: list[dict] = [
    {"still": "docs/media/mac-quick-talk-bar.png", "seconds": 2.0, "note": RENDERED, "tag": "STAND-IN: RENDERED BY THE MAC APP, NOT A SCREEN CAPTURE",
     "title": "Quick talk: a small bar at the screen edge, two buttons under the pointer"},
    {"still": "docs/media/mac-quick-talk-popup.png", "seconds": 3.5, "note": RENDERED, "tag": "STAND-IN: RENDERED BY THE MAC APP, NOT A SCREEN CAPTURE",
     "title": "Two taps of Control: the same call, with captions of both"},
    {"still": "docs/media/mac-quick-talk-island.png", "seconds": 2.0, "note": RENDERED, "tag": "STAND-IN: RENDERED BY THE MAC APP, NOT A SCREEN CAPTURE",
     "title": "Put away, the call goes on in the notch"},
]
DASHBOARD: list[dict] = [
    {"clip": "web-dashboard", "at": "default-view", "take": 4.0, "speed": 1.0, "note": DASH,
     "title": "One page: where Aino stands against her own usual"},
    {"clip": "web-dashboard", "at": "trends-hover", "take": 12.0, "speed": 1.7, "note": DASH,
     "title": "Each signal, day by day, beside her usual range"},
    {"clip": "web-dashboard", "at": "gemma-reading-1", "take": 12.0, "speed": 1.7, "note": DASH + " Review cached.",
     "title": "Gemma reads the whole record; code checks every number"},
    {"clip": "web-dashboard", "at": "agent-trace", "take": 8.0, "speed": 2.0, "note": DASH,
     "title": "The agent trace: each step, and what was rejected"},
    {"clip": "web-dashboard", "at": "graph-node-6", "take": 14.0, "speed": 2.5, "note": DASH,
     "title": "What Kaiku has learned, with the records behind it"},
    {"clip": "web-dashboard", "at": "reflections-2", "take": 10.0, "speed": 2.2, "note": DASH,
     "title": "The daily account, newest day first"},
]


def entries() -> list[dict]:
    """CUT with every shot that is not filmed yet replaced by its stand-in pieces, when it has any."""
    out: list[dict] = []
    for item in cut():
        if "film" in item and not (REC / item["film"]).exists() and item.get("standin"):
            out += [{**piece, "for": item["film"]} for piece in item["standin"]]
        else:
            out.append(item)
    return out


# --- drawing --------------------------------------------------------------------------------------------------------
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


# where the picture goes: (x, y, box width, box height); the title is drawn on the paper around it
PHONE_BOX = (250, 30, 520, 1020)
WEB_BOX = (192, 14, 1536, 960)
STILL_BOX = (360, 130, 1200, 720)


def backdrop_png(path: Path, kind: str, title: str, note: str, tag: str | None = None) -> None:
    """The frame around a piece: paper, the title (what the judge is seeing) and where the picture comes from.
    `tag`: the small capitals above the title (a stand-in says so there)."""
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    if kind == "phone":
        x, width = 900, 880
        big, small, small_tag = font(FONT_BOLD, 64), font(FONT, 28), font(FONT_BOLD, 24)
        lines = wrap(d, title, big, width)
        y = H / 2 - (len(lines) * 78) / 2 - 40
        d.text((x, y - 50), tag or "IPHONE", font=small_tag, fill=CLAY, anchor="lm")
        for i, line in enumerate(lines):
            d.text((x, y + 20 + i * 78), line, font=big, fill=INK, anchor="lm")
        for i, line in enumerate(wrap(d, note, small, width)):
            d.text((x, y + 30 + len(lines) * 78 + 18 + i * 38), line, font=small, fill=MUTED, anchor="lm")
    elif kind == "still":
        big, small, small_tag = font(FONT_BOLD, 44), font(FONT, 26), font(FONT_BOLD, 24)
        if tag:
            d.text((W / 2, 70), tag, font=small_tag, fill=CLAY, anchor="mm")
        d.text((W / 2, 930), title, font=big, fill=INK, anchor="mm")
        for i, line in enumerate(wrap(d, note, small, 1500)):
            d.text((W / 2, 990 + i * 34), line, font=small, fill=MUTED, anchor="mm")
    else:
        big, small = font(FONT_BOLD, 40), font(FONT, 24)
        d.text((WEB_BOX[0], 1012), title, font=big, fill=INK, anchor="lm")
        d.text((WEB_BOX[0], 1056), note, font=small, fill=MUTED, anchor="lm")
    im.save(path)


# --- timing ---------------------------------------------------------------------------------------------------------
def chapters(stem: str) -> dict[str, float]:
    out: dict[str, float] = {}
    steps = REC / f"{stem}-steps.txt"
    if steps.exists():
        for line in steps.read_text().splitlines():
            m = re.match(r"\s*(\d+):([\d.]+)\s+(\S+)", line)
            if m:
                out.setdefault(m.group(3), int(m.group(1)) * 60 + float(m.group(2)))
    return out


def start_of(stem: str, at: float | str) -> float:
    if isinstance(at, (int, float)):
        return float(at)
    m = re.match(r"([a-z0-9-]+?)([+-][\d.]+)?$", at)
    marks = chapters(stem)
    if not m or m.group(1) not in marks:
        sys.exit(f"{stem}: no chapter '{at}' in {stem}-steps.txt (have: {', '.join(marks) or 'none'})")
    return max(0.0, marks[m.group(1)] + float(m.group(2) or 0))


def stamp(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def has_audio(ffprobe: str, path: Path) -> bool:
    out = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True).stdout
    return bool(out.strip())


def run(ffmpeg: str, *args: str) -> None:
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", *args], check=True)


def main() -> None:
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    ffprobe = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
    tmp = Path(tempfile.mkdtemp(prefix="kaiku-cut-"))
    enc = ["-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-an"]
    parts: list[Path] = []
    rows: list[str] = []
    sounds: list[tuple[Path, float, float | None]] = []      # file, starts at (s) in the cut, seconds to keep
    silent: list[str] = []
    t = 0.0
    for i, item in enumerate(entries()):
        seg = tmp / f"{i:02d}.mp4"
        standin = f"STAND-IN for {item['for']}: " if item.get("for") else ""
        if "still" in item:
            x, y, bw, bh = STILL_BOX
            back = tmp / f"{i:02d}-back.png"
            backdrop_png(back, "still", item["title"], item["note"], item.get("tag"))
            length = float(item["seconds"])
            graph = (f"[0:v]scale={bw}:{bh}:force_original_aspect_ratio=decrease:force_divisible_by=2[v];"
                     f"[1:v][v]overlay={x}+({bw}-w)/2:{y}+({bh}-h)/2[o]")
            run(ffmpeg, "-loop", "1", "-t", f"{length}", "-i", str(ROOT.parent / item["still"]), "-loop", "1", "-t", f"{length}",
                "-i", str(back), "-filter_complex", graph, "-map", "[o]", "-t", f"{length}", *enc, str(seg))
            what = f"{standin}still {item['still']}, {length:g} s: {item['title']}"
        elif "film" in item:
            film = REC / item["film"]
            if film.exists():
                length = float(item["seconds"])
                run(ffmpeg, "-i", str(film), "-t", f"{length}", "-vf",
                    f"scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                    f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,fps={FPS}", *enc, str(seg))
                if has_audio(ffprobe, film):
                    sounds.append((film, t, length))
                what = f"FILMED       {item['film']} ({length:.0f} s, its own sound)"
            else:
                png = tmp / f"{i:02d}.png"
                card_png(png, item["card"], item["body"])
                length = CARD_SECONDS
                run(ffmpeg, "-loop", "1", "-t", f"{length}", "-i", str(png), *enc, str(seg))
                what = f"PLACEHOLDER  {item['card']}: {item['body']}  (drop {item['film']} into demo/recordings/)"
        else:
            stem, take, speed = item["clip"], float(item["take"]), float(item["speed"])
            start = start_of(stem, item["at"])
            phone = stem.startswith("iphone")
            x, y, bw, bh = PHONE_BOX if phone else WEB_BOX
            back = tmp / f"{i:02d}-back.png"
            backdrop_png(back, "phone" if phone else "web", item["title"], item["note"], item.get("tag"))
            graph = (f"[0:v]trim=start={start:.2f}:duration={take:.2f},setpts=(PTS-STARTPTS)/{speed},"
                     f"scale={bw}:{bh}:force_original_aspect_ratio=decrease:force_divisible_by=2,fps={FPS}[v];"
                     f"[1:v][v]overlay={x}+({bw}-w)/2:{y}+({bh}-h)/2:shortest=1[o]")
            run(ffmpeg, "-i", str(REC / f"{stem}.mp4"), "-loop", "1", "-i", str(back), "-filter_complex", graph,
                "-map", "[o]", *enc, str(seg))
            length = take / speed
            said = []
            for name, at in item.get("voice", []):
                wav = VOICE / name
                if wav.exists():
                    sounds.append((wav, t + at, None))
                    said.append(name)
                else:
                    silent.append(name)
            what = (f"{standin}{stem} from {stamp(start)}, {take:.0f} s at {speed:g}x: {item['title']}"
                    + (f"  [voice: {', '.join(said)}]" if said else ""))
        rows.append(f"{stamp(t)}–{stamp(t + length)}  {what}")
        t += length
        parts.append(seg)

    listing = tmp / "list.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in parts))
    picture = tmp / "picture.mp4"
    run(ffmpeg, "-f", "concat", "-safe", "0", "-i", str(listing), *enc, str(picture))
    # the sound: silence for the whole length, Kaiku's lines and any filmed shot's own audio at their moments
    inputs, graph, mix = ["-f", "lavfi", "-t", f"{t:.2f}", "-i", "anullsrc=r=48000:cl=stereo"], [], ["[0:a]"]
    for k, (path, at, keep) in enumerate(sounds, start=1):
        inputs += ["-i", str(path)]
        cutoff = f"atrim=duration={keep:.2f}," if keep else ""
        graph.append(f"[{k}:a]{cutoff}aresample=48000,aformat=channel_layouts=stereo,adelay={int(at * 1000)}:all=1[s{k}]")
        mix.append(f"[s{k}]")
    graph.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=first[a]")
    out = REC / "kaiku-draft-cut.mp4"
    run(ffmpeg, *inputs, "-i", str(picture), "-filter_complex", ";".join(graph), "-map", f"{len(sounds) + 1}:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", f"{t:.2f}", "-movflags", "+faststart", str(out))
    run(ffmpeg, "-i", str(out), "-vf", f"fps=24/{t:.2f},scale=480:-2,tile=6x4:padding=6:color=white", "-frames:v", "1",
        str(REC / "kaiku-draft-cut-sheet.png"))
    note = f"\ntotal {stamp(t)}\n" + (f"silent (voice file missing, run scripts/record_voice.py): {', '.join(silent)}\n" if silent else "")
    (REC / "kaiku-draft-cut-timeline.txt").write_text("\n".join(rows) + "\n" + note)
    print("\n".join(rows))
    print(f"{note}\n{out}  {out.stat().st_size / 1e6:.1f} MB")
    shutil.rmtree(tmp, ignore_errors=True)
    if t > LIMIT:
        sys.exit(f"{stamp(t)} is longer than 1:58: shorten a piece")


if __name__ == "__main__":
    main()
