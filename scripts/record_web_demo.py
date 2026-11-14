"""Record short videos of the web app against a seeded cloud (dev harness, no keys).

    uv run --with playwright==1.58.0 python scripts/record_web_demo.py --base http://127.0.0.1:18011 --out demo/recordings
Needs a cloud serving the static export (`make web-build`) and `make seed`; `scripts/record_web_demo.sh` does both.
One WebM per flow (Playwright record_video_dir), converted to MP4 with ffmpeg when it is installed.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


def person_me(page: Page, base: str) -> None:
    page.goto(f"{base}/me/?home_id=demo-aino")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2500)
    for _ in range(6):
        page.mouse.wheel(0, 450)
        page.wait_for_timeout(900)
    page.wait_for_timeout(1000)


def clinician(page: Page, base: str) -> None:
    page.goto(f"{base}/clinician/")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)
    page.mouse.wheel(0, 400)
    page.wait_for_timeout(1500)


def patient(page: Page, base: str) -> None:
    page.goto(f"{base}/clinician/patient/?id=demo-aino")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2500)
    for _ in range(8):
        page.mouse.wheel(0, 500)
        page.wait_for_timeout(900)


def firefly(page: Page, base: str) -> None:
    page.goto(f"{base}/play/firefly/?home_id=demo-aino")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)
    page.locator("button.k-b-pri").first.click()  # start (never the "I'm not OK" button)
    # tap fireflies, let moths fly by, like a person would (the game runs ~60 s; keep the clip short)
    for _ in range(60):
        fly = page.locator("button.k-fly:not(.moth)")
        if fly.count():
            page.wait_for_timeout(350)
            if fly.count():
                fly.first.dispatch_event("pointerdown")
        page.wait_for_timeout(400)
    page.wait_for_timeout(1500)


FLOWS = {"web-me": (person_me, "phone"), "web-clinician": (clinician, "desktop"),
         "web-patient": (patient, "desktop"), "web-firefly": (firefly, "phone")}
VIEWPORTS = {"phone": {"width": 390, "height": 844}, "desktop": {"width": 1280, "height": 800}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", default="demo/recordings")
    ap.add_argument("--only", default="", help="comma list of flows")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg") or ("/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else None)
    only = {s for s in a.only.split(",") if s}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for name, (flow, kind) in FLOWS.items():
            if only and name not in only:
                continue
            vp = VIEWPORTS[kind]
            tmp = out / f".video-{name}"
            ctx = browser.new_context(viewport=vp, record_video_dir=str(tmp), record_video_size=vp,
                                      device_scale_factor=1, color_scheme="light")
            page = ctx.new_page()
            flow(page, a.base.rstrip("/"))
            ctx.close()
            webm = next(tmp.glob("*.webm"))
            if ffmpeg:
                mp4 = out / f"{name}.mp4"
                subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-pix_fmt",
                                "yuv420p", "-crf", "28", "-preset", "veryfast", "-movflags", "+faststart", str(mp4)],
                               check=True)
                print(f"{mp4}  {mp4.stat().st_size / 1e6:.1f} MB")
            else:
                shutil.move(str(webm), out / f"{name}.webm")
            shutil.rmtree(tmp, ignore_errors=True)
        browser.close()


if __name__ == "__main__":
    main()
