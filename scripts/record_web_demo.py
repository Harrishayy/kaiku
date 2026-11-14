"""Record the practitioner dashboard (one viewport, one person) as a video, driven like a person would.

    uv run --with playwright python scripts/record_web_demo.py --url http://127.0.0.1:8000/?id=aino
    uv run --with playwright python scripts/record_web_demo.py --url <base> [--person aino] [--out demo/recordings]
        [--name web-dashboard] [--size 1440x900] [--allow-model] [--browser <path to chrome-headless-shell>]

The take: default view → hover along the Trends chart → Kaiku's review (a cited record, then the agent trace) →
the knowledge graph maximised and one node selected → the Daily account with one day opened → a panel collapsed
to the bar and another moved. Writes <out>/<name>.mp4 (h264, via ffmpeg; the .webm is kept when ffmpeg is
missing), <name>-sheet.png (12 frames) and <name>-steps.txt (chapter time codes).

Read-only by default, so it is safe against someone else's running service: every request other than GET is
blocked, and `GET .../insight` is sent with `generate=false` (cached review or the rule-based summary: no model
call). `--allow-model` lifts both for a take that should show a freshly written review.

The dashboard is still changing, so every step looks for its control by role or accessible name with a few
fallbacks, waits patiently, and is skipped with a `SKIP` line when the control is not there; the take goes on.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import Locator, Page, Route, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

HEADLESS_SHELL = Path.home() / ("Library/Caches/ms-playwright/chromium_headless_shell-1254/"
                                "chrome-headless-shell-mac-arm64/chrome-headless-shell")

# A visible pointer: Playwright's video does not draw the mouse. Recording aid only, injected into the page.
POINTER_JS = """
(() => {
  const make = () => {
    if (document.getElementById('rec-pointer')) return;
    const d = document.createElement('div');
    d.id = 'rec-pointer';
    d.style.cssText = 'position:fixed;left:0;top:0;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;' +
      'background:rgba(40,30,25,.28);border:1.5px solid rgba(40,30,25,.75);z-index:2147483647;pointer-events:none;' +
      'transition:transform .08s ease;transform:translate(-100px,-100px)';
    document.documentElement.appendChild(d);
    let x = -100, y = -100, s = 1;
    const put = () => { d.style.transform = `translate(${x}px,${y}px) scale(${s})`; };
    addEventListener('mousemove', (e) => { x = e.clientX; y = e.clientY; put(); }, true);
    addEventListener('mousedown', () => { s = 0.7; put(); }, true);
    addEventListener('mouseup', () => { s = 1; put(); }, true);
  };
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', make); else make();
})();
"""


class Take:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.t0 = time.monotonic()
        self.steps: list[tuple[float, str]] = []
        self.skipped: list[str] = []
        self.at = (700.0, 450.0)
        self.model = False
        self.opened = time.monotonic()

    # -- pacing and pointer -------------------------------------------------------------------------------------
    def wait(self, s: float) -> None:
        self.page.wait_for_timeout(int(s * 1000))

    def chapter(self, name: str) -> None:
        self.steps.append((time.monotonic() - self.t0, name))
        print(f"STEP {name}")

    def skip(self, what: str, why: object = "") -> None:
        self.skipped.append(what)
        print(f"SKIP {what}: {str(why).splitlines()[0] if why else 'not found'}")

    def move(self, x: float, y: float, seconds: float = 0.6) -> None:
        """Glide the pointer there (eased), instead of teleporting."""
        x0, y0 = self.at
        n = max(8, int(seconds * 50))
        for i in range(1, n + 1):
            k = i / n
            e = k * k * (3 - 2 * k)
            self.page.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            self.page.wait_for_timeout(int(seconds * 1000 / n))
        self.at = (x, y)

    def first(self, *candidates: Locator, timeout: float = 6) -> Locator | None:
        """The first candidate that becomes visible."""
        deadline = time.monotonic() + timeout
        while True:
            for c in candidates:
                try:
                    if c.count() and c.first.is_visible():
                        return c.first
                except Exception:  # noqa: BLE001 - a detached node while the page re-renders
                    pass
            if time.monotonic() > deadline:
                return None
            self.page.wait_for_timeout(200)

    def point(self, target: Locator, dx: float = 0.5, dy: float = 0.5, seconds: float = 0.7) -> bool:
        try:
            target.scroll_into_view_if_needed(timeout=3000)
            box = target.bounding_box()
        except Exception:  # noqa: BLE001
            box = None
        if not box:
            return False
        self.move(box["x"] + box["width"] * dx, box["y"] + box["height"] * dy, seconds)
        return True

    def click(self, what: str, *candidates: Locator, after: float = 1.5, timeout: float = 6) -> bool:
        target = self.first(*candidates, timeout=timeout)
        if target is None or not self.point(target):
            self.skip(what)
            return False
        self.wait(0.35)
        try:
            self.page.mouse.down()
            self.wait(0.08)
            self.page.mouse.up()
        except Exception as e:  # noqa: BLE001
            self.skip(what, e)
            return False
        self.wait(after)
        return True

    def panel(self, key: str, title: str) -> Locator:
        """A panel by its data attribute, else by its heading text."""
        by_id = self.page.locator(f'[data-panel="{key}"]')
        if by_id.count():
            return by_id.first
        return self.page.locator("section").filter(has=self.page.get_by_role("heading", name=re.compile(title, re.I))).first

    def open_panel(self, key: str, title: str) -> Locator | None:
        """The open panel; opens it from the bar below when it is collapsed."""
        p = self.panel(key, title)
        if not (p.count() and p.is_visible()):
            self.click(f"open {title}", self.page.get_by_role("button", name=re.compile(rf"^Open {title}", re.I)),
                       self.page.get_by_role("button", name=re.compile(rf"\+\s*{title}", re.I)), after=1.8)
            p = self.panel(key, title)
        if p.count() and p.is_visible():
            return p
        self.skip(f"panel {title}")
        return None

    def wheel(self, over: Locator, dy: int, times: int = 1, pause: float = 1.2) -> None:
        if not self.point(over, 0.5, 0.6):
            return
        for _ in range(times):
            for _ in range(6):                      # a scroll gesture, not a jump
                self.page.mouse.wheel(0, dy / 6)
                self.page.wait_for_timeout(40)
            self.wait(pause)


def flow(t: Take, url: str) -> None:
    page = t.page
    page.goto(url, wait_until="domcontentloaded")
    try:
        page.wait_for_selector('[data-panel], main [role="status"], main [role="alert"]', timeout=30_000)
        page.wait_for_selector('#dash-panels[data-ready="true"], [data-panel]', timeout=15_000)
    except PlaywrightTimeout as e:
        t.skip("dashboard ready", e)
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PlaywrightTimeout:
        pass                                        # the page polls; idle may never come

    # let the page settle first: the routine, the graph and (when the model may be asked) the written review
    try:
        page.get_by_text(re.compile(r"Written by Gemma|Rule-based summary")).first.wait_for(timeout=15_000)
        if t.model:
            page.get_by_text(re.compile(r"Written by Gemma")).first.wait_for(timeout=20_000)
    except PlaywrightTimeout:
        pass
    t.wait(1.5)
    t.t0 = time.monotonic()                         # chapters count from here; the load before it is cut from the clip
    t.chapter("default-view")
    t.move(720, 420, 0.8)
    t.wait(4)

    # -- the chart: read a few days along the line ------------------------------------------------------------
    t.chapter("trends-hover")
    trends = t.panel("trends", "Trends")
    chart = t.first(trends.locator('svg[role="img"]'), page.get_by_role("img", name=re.compile(r"by day", re.I)),
                    trends.locator("svg"), timeout=8)
    if chart is not None and t.point(chart, 0.12, 0.45):
        for fx in (0.3, 0.48, 0.62, 0.78, 0.9, 0.7):
            t.point(chart, fx, 0.45, seconds=0.9)
            t.wait(1.1)
    else:
        t.skip("trends chart")

    # -- Kaiku's review: findings, a cited record, the agent trace ------------------------------------------------
    t.chapter("review")
    review = t.open_panel("review", "Kaiku.s review")
    if review is not None:
        t.point(review, 0.5, 0.3)
        t.wait(1.5)
        reading = t.first(review.get_by_text(re.compile(r"reading of the whole record", re.I)), review.locator(".d-overview"), timeout=3)
        if reading is not None and t.point(reading, 0.3, 0.5):
            t.chapter("gemma-reading")
            t.wait(4.5)                             # long enough to read the first sentence
        else:
            t.skip("Gemma's reading (the review on screen is not model-written)")
            t.wait(2)
        if t.click("cited record", review.locator("button.d-cite"), review.get_by_role("button", expanded=False).filter(
                has_text=re.compile(r"^\s*\[?\d+\]?")), after=3, timeout=4):
            t.wheel(review, 220, times=1, pause=1.8)
        else:
            t.wheel(review, 260, times=2, pause=1.6)
        t.chapter("agent-trace")
        if t.click("agent trace tab", review.get_by_role("tab", name=re.compile(r"trace", re.I)),
                   page.get_by_role("tab", name=re.compile(r"trace", re.I)), after=3):
            t.wheel(review, 260, times=2, pause=1.8)
            t.wheel(review, -600, times=1, pause=0.6)
            t.click("review tab", review.get_by_role("tab", name=re.compile(r"^review", re.I)), after=1.5)

    # -- knowledge graph: maximise, pick a node, read its evidence, restore --------------------------------------
    t.chapter("knowledge-graph")
    graph = t.open_panel("graph", "Knowledge graph")
    if graph is not None:
        t.wait(1.5)
        t.click("maximise graph", page.get_by_role("button", name=re.compile(r"^Maximise Knowledge graph", re.I)),
                graph.get_by_role("button", name=re.compile(r"maximi[sz]e", re.I)), after=3)
        graph = t.panel("graph", "Knowledge graph")
        nodes = graph.locator('svg [role="button"][aria-label]')
        t.chapter("graph-node")
        picked = False
        try:
            n = nodes.count()
        except Exception:  # noqa: BLE001
            n = 0
        # prefer a node that reads as an activity or routine, else one from the middle of the picture
        order = [i for i in range(n) if re.search(r"walk|outing|sleep|mood", nodes.nth(i).get_attribute("aria-label") or "", re.I)]
        order += [n // 2, n // 3, 0]
        for i in order[:4]:
            if n and t.click(f"graph node {i}", nodes.nth(i), after=3.5, timeout=2):
                picked = True
                break
        if not picked:
            t.skip("graph node")
        else:
            others = [i for i in order[1:4] if i != order[0]]
            if others and n > 1:
                t.click("second graph node", nodes.nth(others[0]), after=3, timeout=2)
        t.click("restore graph", page.get_by_role("button", name=re.compile(r"^Restore", re.I)), after=2)

    # -- the daily account: open one day -------------------------------------------------------------------------
    t.chapter("daily-account")
    evidence = t.open_panel("evidence", "Daily account")
    if evidence is not None:
        t.point(evidence, 0.5, 0.3)
        t.wait(1.5)
        strip = t.first(evidence.get_by_role("img", name=re.compile(r"reflection level by day", re.I)),
                        evidence.get_by_text(re.compile(r"^Reflections$")), timeout=3)
        if strip is not None and t.point(strip, 0.2, 0.5):
            t.chapter("reflections")
            t.point(strip, 0.85, 0.5, seconds=1.6)  # along the strip, day by day
            t.wait(1.2)
            t.click("reflections detail", evidence.locator("section.d-refl summary"),
                    evidence.get_by_text(re.compile(r"^Reflections$")), after=3, timeout=2)
        else:
            t.skip("reflections strip")
        days = evidence.locator("button.d-day-head")
        if not days.count():
            days = evidence.get_by_role("listitem").get_by_role("button")
        closed = evidence.locator('button.d-day-head[aria-expanded="false"]')
        if t.click("a day", closed.nth(1) if closed.count() > 1 else days.nth(1), days, after=3, timeout=4):
            t.wheel(evidence, 240, times=2, pause=1.8)

    # -- the layout is hers: collapse one panel to the bar, move another -------------------------------------------
    t.chapter("collapse-and-move")
    collapsed = None
    for title in ("Routine", "Knowledge graph", "Daily account"):
        if t.click(f"collapse {title}", page.get_by_role("button", name=re.compile(rf"^Collapse {title}", re.I)),
                   after=2.5, timeout=2):
            collapsed = title
            break
    if collapsed is None:
        t.skip("collapse a panel")
    moved = False
    for title in ("Kaiku.s review", "Consensus now", "Daily account"):
        grip = t.first(page.get_by_role("button", name=re.compile(rf"^Move {title}", re.I)), timeout=2)
        if grip is None or not t.point(grip):
            continue
        t.wait(0.6)
        try:
            grip.focus()
            page.keyboard.press("ArrowLeft")       # the grip moves a panel one place with the arrow keys
            t.wait(2.5)
            page.keyboard.press("ArrowRight")
            t.wait(2)
            moved = True
        except Exception as e:  # noqa: BLE001
            t.skip(f"move {title}", e)
        break
    if not moved:
        t.skip("move a panel")
    t.click("reset layout", page.get_by_role("button", name=re.compile(r"reset layout", re.I)), after=3, timeout=3)
    t.chapter("end")
    t.move(720, 430, 0.8)
    t.wait(2.5)


def read_only(route: Route) -> None:
    """No writes and no model calls: non-GET requests are dropped; the insight is asked for with generate=false."""
    req = route.request
    if req.method not in ("GET", "HEAD", "OPTIONS"):
        print(f"BLOCKED {req.method} {urlsplit(req.url).path}")
        route.abort()
        return
    parts = urlsplit(req.url)
    if parts.path.rstrip("/").endswith("/insight"):
        q = dict(parse_qsl(parts.query))
        if q.get("generate") != "false":
            q["generate"] = "false"
            route.continue_(url=urlunsplit(parts._replace(query=urlencode(q))))
            return
    route.continue_()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", "--base", dest="url", required=True, help="dashboard URL (with or without ?id=<person>)")
    ap.add_argument("--person", default="aino")
    ap.add_argument("--out", default="demo/recordings")
    ap.add_argument("--name", default="web-dashboard")
    ap.add_argument("--size", default="1440x900", help="viewport = video size (the layout opens five panels from 1280x800)")
    ap.add_argument("--allow-model", action="store_true", help="do not force generate=false or block writes")
    ap.add_argument("--browser", default=str(HEADLESS_SHELL), help="chrome-headless-shell to launch (falls back to Playwright's own)")
    a = ap.parse_args()

    parts = urlsplit(a.url)
    q = dict(parse_qsl(parts.query))
    q.setdefault("id", a.person)
    url = urlunsplit(parts._replace(path=parts.path or "/", query=urlencode(q)))
    w, h = (int(v) for v in a.size.lower().split("x"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / f".video-{a.name}"
    shutil.rmtree(tmp, ignore_errors=True)
    ffmpeg = shutil.which("ffmpeg") or ("/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else None)

    with sync_playwright() as p:
        launch = {"headless": True}
        if a.browser and Path(a.browser).exists():
            launch["executable_path"] = a.browser
        browser = p.chromium.launch(**launch)
        ctx = browser.new_context(viewport={"width": w, "height": h}, record_video_dir=str(tmp),
                                  record_video_size={"width": w, "height": h}, device_scale_factor=1,
                                  color_scheme="light", reduced_motion="no-preference")
        ctx.add_init_script(POINTER_JS)
        if not a.allow_model:
            ctx.route("**/v1/**", read_only)
        page = ctx.new_page()
        take = Take(page)
        take.model = a.allow_model
        try:
            flow(take, url)
        finally:
            ctx.close()
            browser.close()

    webm = next(tmp.glob("*.webm"))
    (out / f"{a.name}-steps.txt").write_text("".join(f"{int(s // 60)}:{s % 60:04.1f}  {n}\n" for s, n in take.steps))
    if ffmpeg:
        mp4 = out / f"{a.name}.mp4"
        lead = max(0.0, take.t0 - take.opened - 0.3)   # the page loading: not part of the take
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{lead:.2f}", "-i", str(webm), "-vf", "fps=30,format=yuv420p", "-c:v", "libx264",
                        "-crf", "23", "-preset", "slow", "-movflags", "+faststart", str(mp4)], check=True)
        dur = max(1.0, take.steps[-1][0] if take.steps else 12.0)
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(mp4), "-vf",
                        f"fps=12/{dur:.2f},scale=720:-2,tile=4x3:padding=6:color=white", "-frames:v", "1",
                        str(out / f"{a.name}-sheet.png")], check=True)
        print(f"{mp4}  {mp4.stat().st_size / 1e6:.1f} MB  {dur:.0f} s")
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        shutil.move(str(webm), out / f"{a.name}.webm")
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"{out / (a.name + '.webm')} (ffmpeg not found: no mp4, no contact sheet)")
    if take.skipped:
        print("SKIPPED " + "; ".join(take.skipped))


if __name__ == "__main__":
    main()
