"""Record the intelligence-flow explainer (docs/explainers/intelligence-flow.html): a video and two README GIFs.

    uv run --with playwright python scripts/record_flow.py
    uv run --with playwright python scripts/record_flow.py [--only video|fast] [--size 1920x1080] [--fps 30]
        [--theme light|dark] [--out demo/recordings/intelligence-flow.mp4] [--gif docs/media/intelligence-flow.gif]
        [--gif-max-mb 3] [--gif-all docs/media/intelligence-flow-all.gif] [--gif-all-max-mb 10] [--seconds N]
        [--waiting] [--browser <path to chrome-headless-shell>]

The page is a pure function of its timeline, so this does not film a browser in real time: it opens the page with
`?autoplay=1&record=1&clock=manual`, asks it for the length of the auto-play (`__flow.total()`), then for every
frame sets the time (`__flow.seek(ms)`) and takes a screenshot. Frames are piped straight into ffmpeg, so a take
has exact timing and no dropped frames whatever the machine is doing. Needs ffmpeg and gifsicle, and a network
connection for the two Google Fonts (the script says so when they did not load).

One run makes two takes:

1. The full take at the page's reading pace: <out> (h264), <out stem>-sheet.png (one frame per hop),
   <out stem>-steps.txt (time code of every scene and hop, for the video edit) and --gif, the first scene.
2. The fast take (`&pace=fast`: the page's own timeline with short dwells, every hop still travelled; past 70 s
   the page speeds itself up, by a fifth at most, so seven scenes take 70 s): <out stem>-fast.mp4,
   <out stem>-fast-steps.txt, --gif-all (every scene and hop, ending on the model table) and
   <out stem>-all-sheet.png, frames of that GIF at every hop.

Both GIFs go through a palette (ffmpeg) and gifsicle -O3 --lossy, stepped down until they are under their size
limit; the whole-flow GIF never goes under 800 px wide. `--waiting` also films the scenes that still wait for
their facts (a check of the wiring, not a take to publish; give it its own --out, --gif and --gif-all).
No model, cloud or key is involved: every number and payload is already in the page.

    uv run --with playwright python scripts/record_flow.py --audit [--sizes 1280x720,400x860] [--shots DIR]

`--audit` records nothing. It opens the page the way a reader gets it (not the full-bleed recording view) at
every size in AUDIT_RUNS, light and dark, and once with the web fonts blocked, visits every scene's opening and
closing card, every hop, every node card and the legend, and fails (exit 1) on: text that does not fit its box,
map text outside its node, chips over a node, a label or each other, panel content under the bottom bar, anything
cut by the stage or pushed off a phone screen. `--shots DIR` also saves a picture of every state it visits.
"""

from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs/explainers/intelligence-flow.html"
HEADLESS_SHELL = Path.home() / ("Library/Caches/ms-playwright/chromium_headless_shell-1254/"
                                "chrome-headless-shell-mac-arm64/chrome-headless-shell")
# Tried in order until a GIF fits: (width px, every n-th frame of the take, palette colours, gifsicle --lossy).
# Every n-th frame keeps the motion even; the type on the map stops being readable under 800 px.
GIF_LADDER = [(960, 3, 128, 30), (960, 3, 96, 60), (960, 3, 64, 100), (900, 3, 64, 140), (840, 3, 48, 170),
              (800, 3, 48, 200), (800, 5, 48, 200)]
BT709 = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]


def clock(ms: float) -> str:
    s = ms / 1000
    return f"{int(s // 60)}:{s % 60:04.1f}"


def run(cmd: list[str]) -> None:
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit(f"{cmd[0]} failed:\n{done.stderr[-1500:]}")


def record(args: argparse.Namespace, out: Path, fast: bool = False) -> list[dict]:
    width, height = (int(n) for n in args.size.lower().split("x"))
    url = (PAGE.as_uri() + "?autoplay=1&record=1&clock=manual" + (f"&theme={args.theme}" if args.theme else "")
           + ("&pace=fast" if fast else "") + ("&waiting=1" if args.waiting else ""))
    encode = ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(args.fps), "-c:v", "png",
              "-i", "-", "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", "-c:v", "libx264",
              "-preset", "slow", "-crf", "16", *BT709, "-movflags", "+faststart", str(out)]
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.browser) if args.browser else p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        problems: list[str] = []
        page.on("pageerror", lambda e: problems.append(str(e)))
        page.goto(url)
        page.wait_for_selector("html[data-flow-ready='1']", state="attached", timeout=20000)
        if not page.evaluate("document.fonts.check('500 20px Fredoka') && document.fonts.check('600 14px Nunito')"):
            print("WARNING: Fredoka / Nunito did not load (offline?), the take uses fallback fonts")
        total = page.evaluate("__flow.total()")
        marks = page.evaluate("__flow.marks()")
        if args.seconds:
            total = min(total, args.seconds * 1000)
        frames = math.ceil(total / 1000 * args.fps)
        print(f"{'fast take' if fast else 'full take'}: {width}x{height}, {frames} frames at {args.fps} fps, "
              f"{clock(total)} of auto-play")
        ff = subprocess.Popen(encode, stdin=subprocess.PIPE)
        assert ff.stdin is not None
        started = time.monotonic()
        for i in range(frames):
            page.evaluate("t => __flow.seek(t)", i * 1000 / args.fps)
            ff.stdin.write(page.screenshot(type="png"))
            if i and i % (args.fps * 20) == 0:
                print(f"  {clock(i * 1000 / args.fps)} ({time.monotonic() - started:.0f} s)")
        ff.stdin.close()
        if ff.wait() != 0:
            sys.exit("ffmpeg could not encode the frames")
        browser.close()
        if problems:
            print("PAGE ERRORS:", problems[:5])
    return marks


def steps_file(marks: list[dict], path: Path) -> list[float]:
    """Write the time code of every scene and hop; return the moment each hop has landed (for the sheet)."""
    lines, rests = [], []
    for scene in marks:
        lines.append(f"{clock(scene['t0'])}  {scene['id']}")
        for step in scene.get("steps", []):
            lines.append(f"{clock(step['t0'])}    {step['id']}")
            rests.append(step["rest"] + 600)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rests


def sheet(video: Path, times: list[float], path: Path, length_ms: float) -> None:
    times = [t for t in times if t < length_ms]
    if not times:
        return
    tmp = path.parent / f".{path.stem}-frames"
    tmp.mkdir(exist_ok=True)
    for i, t in enumerate(times):
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t / 1000:.3f}", "-i", str(video), "-frames:v", "1",
             "-vf", "scale=640:-1:flags=lanczos", str(tmp / f"{i:03d}.png")])
    cols = 5
    run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "1", "-i", str(tmp / "%03d.png"), "-frames:v", "1",
         "-vf", f"tile={cols}x{math.ceil(len(times) / cols)}:margin=8:padding=8:color=0xF5EDE1", str(path)])
    shutil.rmtree(tmp)


def gif(video: Path, t0: float, t1: float, path: Path, max_mb: float, take_fps: int) -> tuple[int, float]:
    """A GIF of the take from t0 to t1 (ms): palette, then gifsicle. Returns (width, frames a second) used."""
    raw = path.with_name("." + path.stem + "-raw.gif")
    width, fps = 0, 0.0
    for width, nth, colours, lossy in GIF_LADDER:
        fps = take_fps / nth
        # no dither: the page is flat colour and small type, and a dither pattern costs both size and sharpness
        chain = (f"fps={fps:g},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors={colours}:"
                 "stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle")
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t0 / 1000:.3f}", "-t", f"{(t1 - t0) / 1000:.3f}",
             "-i", str(video), "-filter_complex", chain, "-loop", "0", str(raw)])
        run(["gifsicle", "-O3", f"--lossy={lossy}", str(raw), "-o", str(path)])
        size = path.stat().st_size / 1e6
        print(f"  {path.name}: {width} px, {fps:g} fps, {colours} colours, lossy {lossy}: {size:.2f} MB")
        if size <= max_mb:
            break
    else:
        print(f"WARNING: {path.name} is still over {max_mb} MB at the smallest setting")
    raw.unlink(missing_ok=True)
    return width, fps


def gif_sheet(gif_path: Path, marks: list[dict], fps: float, path: Path) -> None:
    """One frame of the GIF for every opening card, hop, closing card and the model table: the check that all of
    it is in there. Frames are taken from the GIF itself, not from the take it was made from."""
    times: list[float] = []
    for scene in marks:
        if "steps" not in scene:
            times.append(scene["t1"] - 300)
            continue
        times.append(scene["intro"] - 200)
        times += [(st["rest"] + st["t1"]) / 2 for st in scene["steps"]]
        times.append(scene["outro"] + 100)
    frames = sorted({round(t / 1000 * fps) for t in times})
    pick = "+".join(f"eq(n,{n})" for n in frames)
    cols = 6
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(gif_path), "-frames:v", "1", "-vf",
         f"select='{pick}',scale=480:-1:flags=lanczos,tile={cols}x{math.ceil(len(frames) / cols)}:margin=6:padding=6:"
         "color=0xF5EDE1", str(path)])


# Every size the page is checked at: (viewport, theme, web fonts loaded). Wide layout down to 1100 px, the
# stacked layout below; fallback fonts are wider, so the tightest sizes run once without the Google Fonts.
AUDIT_SIZES = ["1920x1080", "1440x900", "1280x720", "1100x700", "820x900", "400x860", "360x740"]
AUDIT_RUNS = ([(size, "light", True, "") for size in AUDIT_SIZES]
              + [("1280x720", "dark", True, ""), ("400x860", "dark", True, "")]
              + [("1440x900", "light", False, ""), ("1280x720", "light", False, ""), ("1100x700", "light", False, ""),
                 ("400x860", "light", False, "")]
              # scenes that are wired but still wait for their facts (hidden from readers until then)
              + [("1920x1080", "light", True, "waiting=1"), ("1280x720", "light", True, "waiting=1"),
                 ("1100x700", "light", False, "waiting=1"), ("400x860", "light", True, "waiting=1")])

# Runs in the page at one resting state; returns what is wrong there. All geometry is read from the live layout.
AUDIT_JS = r"""
() => {
  const out = new Set();
  const q = (s, r) => [...(r || document).querySelectorAll(s)];
  const R = (e) => e.getBoundingClientRect();
  const shown = (e) => {
    for (let n = e; n && n.nodeType === 1; n = n.parentElement) {
      const c = getComputedStyle(n);
      if (c.display === 'none' || c.visibility === 'hidden' || +c.opacity < 0.05) return false;
    }
    const r = R(e);
    return r.width > 0.5 && r.height > 0.5;
  };
  const say = (e) => '"' + (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 42) + '"';
  const cls = (e) => e.id ? '#' + e.id : '.' + (e.getAttribute('class') || e.tagName.toLowerCase()).trim().split(/\s+/).join('.');
  const hit = (a, b, m) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > m &&
                           Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > m;
  const add = (kind, msg) => out.add(kind + ' | ' + msg);
  const layout = document.getElementById('page').getAttribute('data-layout');
  const stage = R(document.getElementById('stage'));
  let slack = null, legend = null;

  // 1. text that is wider or taller than the box that holds it
  const BOXES = '.box,.pay,.note,.took .num,.took .tx,.bubble,.kicker,.route,.p-step h3,.src,.hc,.hc-main,' +
    '.hc-status,.hc-her,.hc-kaiku,.hc-row,.hc-chips,.hd-top,.hd-find,.hd-fact,.hd-foot,.intro h2,.intro p,.cta,' +
    '.tab,.ctl,.badge,.lg-c,.lg-foot,.legendview h2,.hopbtn,.p-node p,.p-node h3,.s-step,.s-cap,.files div';
  for (const e of q(BOXES)) {
    if (!shown(e) || !e.clientWidth) continue;
    const dx = e.scrollWidth - e.clientWidth, dy = e.scrollHeight - e.clientHeight;
    if (dx > 1 || dy > 1) add('text does not fit its box', cls(e) + ' ' + say(e) + ' by ' + Math.max(dx, 0) + ' x ' + Math.max(dy, 0) + ' px');
  }
  // 2. content that leaves its card or box (a centred overflow does not show up as scroll size)
  const inside = (kids, box, pad, what) => {
    for (const k of kids) {
      if (!shown(k)) continue;
      const r = R(k);
      const over = Math.max(box.left + pad - r.left, r.right - (box.right - pad), box.top + pad - r.top, r.bottom - (box.bottom - pad));
      if (over > 1) add(what, cls(k) + ' ' + say(k) + ' by ' + Math.round(over) + ' px');
    }
  };
  for (const c of q('.hc')) {
    if (!shown(c)) continue;
    const b = R(c);
    inside(q('.hc-face,.hc-status,.hc-her,.hc-kaiku,.hc-ctl,.hc-row,.hc-chips,.hd-top,.hd-kicker,.hd-find,.hd-fact,.hd-foot', c), b, b.width * 0.025, 'app card content outside its card');
  }
  for (const c of q('.box')) if (shown(c)) inside(q('*', c).filter((k) => !k.closest('svg')), R(c), 2, 'content outside its box');

  if (layout === 'wide') {
    const top = R(q('.top')[0]), bar = R(q('.bar')[0]);
    // 3. the panel: nothing wider than it, nothing below it (so nothing reaches the bottom bar)
    const panel = document.getElementById('panel');
    if (shown(panel)) {
      const pr = R(panel), kids = [...panel.children].filter(shown);
      for (const k of kids) if (R(k).right > pr.right + 1) add('panel', cls(k) + ' is wider than the panel by ' + Math.round(R(k).right - pr.right) + ' px');
      if (kids.length) {
        const last = kids.reduce((a, k) => R(k).bottom > R(a).bottom ? k : a, kids[0]);
        slack = Math.round(pr.bottom - R(last).bottom);
        if (slack < 0) add('panel runs past its space', cls(last) + ' ends ' + (-slack) + ' px below the panel (' + Math.round(R(last).bottom - bar.top) + ' px past the top of the bottom bar)');
      }
    }
    // 4. the two bars
    const brand = q('.brand')[0], tabs = q('.tabs')[0];
    if (R(brand).right > R(tabs).left - 4) add('top bar', 'the title line runs into the tabs by ' + Math.round(R(brand).right - R(tabs).left + 4) + ' px');
    if (R(tabs).right > stage.right - 4 || R(tabs).left < stage.left + 4) add('top bar', 'the tabs run out of the stage');
    const ctl = [...q('.bar')[0].children].filter(shown);
    for (let i = 0; i < ctl.length; i++) {
      const r = R(ctl[i]);
      if (r.right > stage.right - 4 || r.left < stage.left + 4) add('bottom bar', cls(ctl[i]) + ' runs out of the stage');
      for (let j = i + 1; j < ctl.length; j++) if (hit(r, R(ctl[j]), 1)) add('bottom bar', cls(ctl[i]) + ' overlaps ' + cls(ctl[j]));
    }
    const scrub = document.getElementById('scrub');
    if (shown(scrub) && R(scrub).width < 90) add('bottom bar', 'the timeline is squeezed to ' + Math.round(R(scrub).width) + ' px');
    // 5. the map, when the camera is at rest on it
    const world = document.getElementById('world');
    const still = (() => { const t = getComputedStyle(world).transform; if (t === 'none') return true; const m = t.match(/matrix\(([^,]+),/); return !!m && Math.abs(parseFloat(m[1]) - 1) < 0.01; })();
    if (shown(world) && still) {
      for (const g of q('.node')) {
        const nb = g.querySelector('rect.nb').getBBox();
        for (const t of q('text', g)) {
          if (t.closest('.tag')) continue;
          const b = t.getBBox();
          const over = Math.max(nb.x + 6 - b.x, b.x + b.width - (nb.x + nb.width - 6), nb.y + 2 - b.y, b.y + b.height - (nb.y + nb.height - 2));
          if (over > 0.5) add('map text outside its node', g.dataset.node + ' ' + say(t) + ' by ' + over.toFixed(1) + ' units');
        }
        const tag = g.querySelector('.tag rect'), title = g.querySelector('.nt');
        if (tag && title && title.getBBox().x + title.getBBox().width > tag.getBBox().x - 3) add('map text', g.dataset.node + ': the title runs into its tag');
        const pill = g.querySelector('.pill-state'), pt = g.querySelector('.pill-text');
        if (pill && pt) { const a = pill.getBBox(), b = pt.getBBox(); if (b.x < a.x + 4 || b.x + b.width > a.x + a.width - 4) add('map text', g.dataset.node + ': the state pill is too small for its words'); }
      }
      for (const g of q('.chip')) {
        const r = g.querySelector('rect').getBBox(), t = g.querySelector('text').getBBox();
        if (t.x + t.width > r.x + r.width - 3) add('chip text outside its chip', say(g));
      }
      const labels = q('.zt,.zs,.mem-label,.lane-label').filter((e) => shown(e) && e.tagName.toLowerCase() !== 'tspan').map((e) => ({e, r: R(e)}));
      const nodes = q('.node').map((g) => ({id: g.dataset.node, r: R(g.querySelector('rect.nb'))}));
      for (let i = 0; i < labels.length; i++) {
        for (let j = i + 1; j < labels.length; j++) if (hit(labels[i].r, labels[j].r, 1)) add('map labels overlap', say(labels[i].e) + ' / ' + say(labels[j].e));
        for (const n of nodes) if (hit(labels[i].r, n.r, 1)) add('map label over a node', say(labels[i].e) + ' / ' + n.id);
      }
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) if (hit(nodes[i].r, nodes[j].r, 1)) add('nodes overlap', nodes[i].id + ' / ' + nodes[j].id);
      const chips = q('.chip').filter((c) => shown(c) && +getComputedStyle(c).opacity > 0.5).map((e) => ({e, r: R(e)}));
      for (let i = 0; i < chips.length; i++) {
        const c = chips[i];
        if (c.e.classList.contains('held')) {   // held back inside the device: has to sit inside that node
          if (!nodes.some((n) => c.r.left >= n.r.left + 2 && c.r.right <= n.r.right - 2 && c.r.top >= n.r.top + 2 && c.r.bottom <= n.r.bottom - 2)) add('held chip not inside its node', say(c.e));
          const texts = q('.node text').filter(shown).map((t) => R(t));
          if (texts.some((t) => hit(c.r, t, 0.5))) add('held chip over the node\'s words', say(c.e));
        } else for (const n of nodes) if (hit(c.r, n.r, 1.5)) add('chip over a node', say(c.e) + ' / ' + n.id);
        for (const l of labels) if (hit(c.r, l.r, 1)) add('chip over a label', say(c.e) + ' / ' + say(l.e));
        for (let j = i + 1; j < chips.length; j++) if (hit(c.r, chips[j].r, 1)) add('chips overlap', say(c.e) + ' / ' + say(chips[j].e));
        if (c.r.left < stage.left + 2 || c.r.right > stage.right - 2 || c.r.top < top.bottom - 2 || c.r.bottom > bar.top + 2) add('chip cut by the stage or a bar', say(c.e));
        if (shown(panel) && hit(c.r, R(panel), 1)) add('chip over the panel', say(c.e));
      }
      // a path that is drawn in this scene must not run through a label
      const m = world.querySelector('svg').getScreenCTM();
      for (const path of q('.edge.in,.edge.lane,.edge-live')) {
        const len = path.getTotalLength();
        for (let d = 0; d <= len; d += 2) {
          const pt = path.getPointAtLength(d), x = m.a * pt.x + m.e, y = m.d * pt.y + m.f;
          const l = labels.find((k) => x > k.r.left + 1 && x < k.r.right - 1 && y > k.r.top + 2 && y < k.r.bottom - 2 && !(k.e.classList.contains('mem-label') && k.e.hasAttribute('transform')));
          if (l) { add('a path runs through a label', say(l.e)); break; }
        }
      }
      for (const p of q('.pore').filter((e) => +getComputedStyle(e).opacity > 0.5)) {
        for (const l of labels) if (l.e.classList.contains('mem-label') && hit(R(p), l.r, 0.5)) add('crossing point on a gate name', say(l.e));
      }
      for (const e of q('.node rect.nb,.zone,.mem-band')) {
        const r = R(e);
        if (r.left < stage.left - 1 || r.right > stage.right + 1 || r.top < top.bottom - 3 || r.bottom > bar.top + 3) add('map cut by the stage or under a bar', cls(e));
      }
      const right = Math.max(...q('.zone').map((z) => R(z).right));
      if (shown(panel) && right > R(panel).left - 2) add('map runs under the panel', Math.round(right - R(panel).left + 2) + ' px');
    }
    // 6. the app card and its caption
    const intro = document.getElementById('intro');
    if (shown(intro)) {
      const kids = [...intro.children].filter(shown);
      const b = Math.max(...kids.map((k) => R(k).bottom)), t = Math.min(...kids.map((k) => R(k).top));
      if (b > bar.top - 2) add('caption reaches the bottom bar', Math.round(b - bar.top + 2) + ' px');
      const hc = q('#hero .hc').filter(shown)[0];
      if (hc) {
        const h = R(hc);
        if (h.bottom > t - 6) add('app card touches its caption', Math.round(h.bottom - t + 6) + ' px');
        if (h.top < top.bottom || h.left < stage.left + 4 || h.right > stage.right - 4) add('app card cut by the stage or the top bar', '');
      }
    }
    // 7. the legend
    const lv = document.getElementById('legendview');
    if (shown(lv)) {
      const kids = [...lv.children].filter(shown);
      const b = Math.max(...kids.map((k) => R(k).bottom));
      const room = Math.min(R(lv).bottom, bar.top - 2);
      if (b > room + 1) add('legend runs past its space', Math.round(b - room) + ' px');
      legend = Math.round(room - b);
    }
    // 8. anything else the stage would cut
    for (const e of q('#stage > :not(.world):not(.hero) *, #hero .hc')) {
      if (!shown(e) || (e.closest('svg') && e.tagName.toLowerCase() !== 'svg')) continue;
      const r = R(e);
      if (r.left < stage.left - 1 || r.right > stage.right + 1 || r.top < stage.top - 1 || r.bottom > stage.bottom + 1) add('cut by the stage', cls(e) + ' ' + say(e));
    }
  } else {
    // stacked layout: nothing wider than the screen, the sticky bar's buttons side by side
    const iw = document.documentElement.clientWidth;
    if (document.documentElement.scrollWidth > iw + 1) add('page scrolls sideways', document.documentElement.scrollWidth + ' px wide on a ' + iw + ' px screen');
    for (const e of q('.wrap *, .below *')) {
      if (!shown(e) || (e.closest('svg') && e.tagName.toLowerCase() !== 'svg')) continue;
      const r = R(e);
      if (r.right <= iw + 1 && r.left >= -1) continue;
      let p = e.parentElement, clipped = false;
      while (p) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') { clipped = true; break; } p = p.parentElement; }
      if (!clipped) add('wider than the screen', cls(e) + ' ' + say(e));
    }
    const ctl = [...q('.bar')[0].children].filter(shown);
    for (let i = 0; i < ctl.length; i++) for (let j = i + 1; j < ctl.length; j++) if (hit(R(ctl[i]), R(ctl[j]), 1)) add('bottom bar', cls(ctl[i]) + ' overlaps ' + cls(ctl[j]));
  }
  return {issues: [...out], slack, legend, layout, fits: window.__flow.fits()};
}
"""


def audit(args: argparse.Namespace) -> int:
    """Visit every resting state of the page at every size in AUDIT_RUNS and report what does not fit."""
    runs = AUDIT_RUNS
    if args.sizes:
        wanted = args.sizes.split(",")
        runs = [r for r in AUDIT_RUNS if r[0] in wanted] or [(w, "light", True, "") for w in wanted]
    bad = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.browser) if args.browser else p.chromium.launch()
        for size, theme, fonts, extra in runs:
            width, height = (int(n) for n in size.lower().split("x"))
            ctx = browser.new_context(viewport={"width": width, "height": height})
            if not fonts:
                ctx.route("**/*", lambda r: r.abort() if "fonts.g" in r.request.url else r.continue_())
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            page.goto(PAGE.as_uri() + f"?clock=manual&theme={theme}" + (f"&{extra}" if extra else ""))
            page.wait_for_selector("html[data-flow-ready='1']", state="attached", timeout=20000)
            page.wait_for_timeout(250)
            name = f"{size} {theme}{'' if fonts else ' no web fonts'}{' ' + extra if extra else ''}"
            if fonts and not page.evaluate("document.fonts.check('500 20px Fredoka')"):
                print(f"WARNING {name}: the web fonts did not load, this run is a fallback-font run")
            marks = page.evaluate("__flow.marks()")
            layout = page.evaluate("__flow.layout()")
            states: list[tuple[str, str]] = []
            for scene in marks:
                if "steps" not in scene:
                    states.append((scene["id"], f"__flow.seek({scene['t1'] - 500})"))
                    continue
                states.append((f"{scene['id']}/opening", f"__flow.seek({scene['intro']})"))
                if layout == "wide":
                    states += [(f"{scene['id']}/{i + 1}-{st['id']}", f"__flow.seek({st['rest'] + 500})")
                               for i, st in enumerate(scene["steps"])]
                    states.append((f"{scene['id']}/closing", f"__flow.seek({scene['outro']})"))
            if layout == "wide":
                states += [(f"node/{n}", f"__flow.seek({marks[0]['steps'][0]['rest'] + 500}); __flow.node('{n}')")
                           for n in page.evaluate("__flow.nodes()")]
            found: list[str] = []
            stepped: list[str] = []
            tightest: tuple[int, str] | None = None
            legend = ""
            for label, go in states:
                page.evaluate(go)
                page.wait_for_timeout(40)
                res = page.evaluate(AUDIT_JS)
                found += [f"{label}: {i}" for i in res["issues"]]
                if res["slack"] is not None and (tightest is None or res["slack"] < tightest[0]):
                    tightest = (res["slack"], label)
                if res["legend"] is not None:
                    legend = f", {res['legend']} px under the legend"
                # the page's fit guards (smaller type, tighter boxes) are for fallback fonts: with its own fonts
                # every text has to fit as designed, so a guard that steps in there is a problem
                fits = res["fits"]
                moved = [k for k, v in fits.items() if v not in (1, False)]
                if moved:
                    note = f"{label}: fit guard " + ", ".join(f"{k}={fits[k]}" for k in moved)
                    (found if fonts else stepped).append(note)
                if args.shots:
                    shot = Path(args.shots) / f"{name.replace(' ', '-')}--{label.replace('/', '-')}.png"
                    shot.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(shot), full_page=layout != "wide")
            room = f", least room under the panel {tightest[0]} px ({tightest[1]})" if tightest else ""
            print(f"{name:34} {layout:5} {len(states):3} states  {len(found):3} problems{room}{legend}")
            for line in found + [f"page error: {e}" for e in errors]:
                print("    " + line)
            if stepped:
                print(f"    (fallback fonts: the fit guards stepped in on {len(stepped)} states, e.g. {stepped[0]})")
            bad += len(found) + len(errors)
            ctx.close()
        browser.close()
    print("audit clean" if not bad else f"audit: {bad} problems")
    return 1 if bad else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--theme", choices=["light", "dark"], default="light")
    ap.add_argument("--only", choices=["video", "fast"], help="make only the full take or only the fast one")
    ap.add_argument("--out", type=Path, default=ROOT / "demo/recordings/intelligence-flow.mp4")
    ap.add_argument("--gif", type=Path, default=ROOT / "docs/media/intelligence-flow.gif")
    ap.add_argument("--gif-max-mb", type=float, default=3.0)
    ap.add_argument("--gif-all", type=Path, default=ROOT / "docs/media/intelligence-flow-all.gif")
    ap.add_argument("--gif-all-max-mb", type=float, default=10.0)
    ap.add_argument("--seconds", type=float, default=0, help="record only the first N seconds (quick check)")
    ap.add_argument("--waiting", action="store_true", help="also film the scenes that still wait for their facts")
    ap.add_argument("--browser", default=str(HEADLESS_SHELL) if HEADLESS_SHELL.exists() else "")
    ap.add_argument("--audit", action="store_true", help="check every state at every size instead of recording")
    ap.add_argument("--sizes", default="", help="audit only these sizes, e.g. 1280x720,400x860")
    ap.add_argument("--shots", default="", help="audit: also save a picture of every state into this folder")
    args = ap.parse_args()
    if args.audit:
        sys.exit(audit(args))
    if not shutil.which("ffmpeg") or not shutil.which("gifsicle"):
        sys.exit("needs ffmpeg and gifsicle (brew install ffmpeg gifsicle)")
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    made: list[str] = []

    if args.only != "fast":
        marks = record(args, out)
        length = args.seconds * 1000 if args.seconds else marks[-1]["t1"]
        steps = out.with_name(out.stem + "-steps.txt")
        rests = steps_file(marks, steps)
        sheet(out, rests, out.with_name(out.stem + "-sheet.png"), length)
        made += [f"video  {out}", f"steps  {steps}", f"sheet  {out.with_name(out.stem + '-sheet.png')}"]
        first = marks[0]
        if first["t1"] <= length:
            args.gif.parent.mkdir(parents=True, exist_ok=True)
            gif(out, first["t0"], first["t1"], args.gif.resolve(), args.gif_max_mb, args.fps)
            made.append(f"gif    {args.gif.resolve()}  (the first scene)")
        else:
            print("the first scene is not complete in this take: no GIF written")

    if args.only != "video":
        fast = out.with_name(out.stem + "-fast.mp4")
        marks = record(args, fast, fast=True)
        length = args.seconds * 1000 if args.seconds else marks[-1]["t1"]
        steps = out.with_name(out.stem + "-fast-steps.txt")
        steps_file(marks, steps)
        made += [f"video  {fast}", f"steps  {steps}"]
        if not args.seconds:
            whole = args.gif_all.resolve()
            whole.parent.mkdir(parents=True, exist_ok=True)
            width, fps = gif(fast, 0, length, whole, args.gif_all_max_mb, args.fps)
            hops = sum(len(m.get("steps", [])) for m in marks)
            board = out.with_name(out.stem + "-all-sheet.png")
            gif_sheet(whole, marks, fps, board)
            made += [f"gif    {whole}  ({whole.stat().st_size / 1e6:.2f} MB, {length / 1000:.1f} s, {fps:g} fps, "
                     f"{width} px, {len(marks) - 1} scenes, {hops} hops, then the model table)", f"sheet  {board}"]
        else:
            print("a short take: no whole-flow GIF written")
    print("\n".join(made))


if __name__ == "__main__":
    main()
