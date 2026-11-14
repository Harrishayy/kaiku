"""Render demo/deck/index.html to kaiku-deck.pdf (16:9) and, with --png DIR, one PNG per slide.

uv run --with playwright python demo/deck/render.py [--png DIR]
Needs network once for the Google Fonts named in design/tokens.json. CHROME overrides the browser binary.
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
CHROME = os.environ.get(
    "CHROME",
    str(Path.home() / "Library/Caches/ms-playwright/chromium_headless_shell-1254"
        "/chrome-headless-shell-mac-arm64/chrome-headless-shell"),
)

png_dir = Path(sys.argv[sys.argv.index("--png") + 1]) if "--png" in sys.argv else None

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME)
    page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5)
    page.goto((HERE / "index.html").as_uri(), wait_until="networkidle")
    page.evaluate("document.fonts.ready")
    fonts = page.evaluate("[...document.fonts].filter(f => f.status === 'loaded').map(f => f.family)")
    print("fonts loaded:", sorted(set(fonts)))
    slides = page.locator(".slide")
    for i in range(slides.count()):
        s = slides.nth(i)
        over = s.evaluate(
            "el => [...el.querySelectorAll('*')].filter(c => { const r = c.getBoundingClientRect(),"
            " b = el.getBoundingClientRect(); return r.width && (r.bottom > b.bottom - 44 && !c.closest('.foot')"
            " && !c.closest('.fine') && !c.classList.contains('halo') || r.right > b.right + 1); })"
            ".map(c => c.tagName + '.' + c.className).slice(0, 4)"
        )
        if over:
            print(f"slide {i + 1}: content reaches the footer band or the right edge:", over)
        if png_dir:
            png_dir.mkdir(parents=True, exist_ok=True)
            s.screenshot(path=str(png_dir / f"slide-{i + 1:02d}.png"))
    page.pdf(path=str(HERE / "kaiku-deck.pdf"), width="1280px", height="720px", print_background=True,
             margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
    browser.close()
print("wrote", HERE / "kaiku-deck.pdf")
