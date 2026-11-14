#!/usr/bin/env bash
# App icons for iPhone + Mac from the app's own mascot renderer (design/mascot.spec.json via MascotView).
# Renders with an opt-in KaikuKit test, then writes iOS/Assets.xcassets/AppIcon.appiconset (1024 light + dark)
# and Mac/Assets.xcassets/AppIcon.appiconset (16…1024, padded rounded square on the macOS icon grid).
# Re-run after the mascot or the colour tokens change: apps/apple/scripts/make_app_icon.sh
set -euo pipefail
cd "$(dirname "$0")/.."
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
(cd KaikuKit && KAIKU_ICON_OUT="$TMP" swift test --filter AppIconRenderTests >/dev/null)
uv run --with pillow python -I - "$TMP" "$PWD" <<'PY'
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw
src, root = Path(sys.argv[1]), Path(sys.argv[2])
light, dark = Image.open(src / "icon-light-1024.png").convert("RGB"), Image.open(src / "icon-dark-1024.png").convert("RGB")
ios = root / "iOS/Assets.xcassets/AppIcon.appiconset"; ios.mkdir(parents=True, exist_ok=True)
light.save(ios / "AppIcon-1024.png"); dark.save(ios / "AppIcon-1024-dark.png")
(ios / "Contents.json").write_text(json.dumps({"images": [
    {"filename": "AppIcon-1024.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"},
    {"appearances": [{"appearance": "luminosity", "value": "dark"}], "filename": "AppIcon-1024-dark.png",
     "idiom": "universal", "platform": "ios", "size": "1024x1024"}], "info": {"author": "xcode", "version": 1}}, indent=2))
# macOS grid: 824 px rounded square (radius 185) centred on a transparent 1024 canvas
body = light.resize((824, 824), Image.LANCZOS)
mask = Image.new("L", (824, 824), 0); ImageDraw.Draw(mask).rounded_rectangle((0, 0, 823, 823), radius=185, fill=255)
mac1024 = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0)); mac1024.paste(body, (100, 100), mask)
mac = root / "Mac/Assets.xcassets/AppIcon.appiconset"; mac.mkdir(parents=True, exist_ok=True)
images = []
for pt in (16, 32, 128, 256, 512):
    for scale in (1, 2):
        px = pt * scale; name = f"AppIcon-{pt}@{scale}x.png"
        mac1024.resize((px, px), Image.LANCZOS).save(mac / name)
        images.append({"filename": name, "idiom": "mac", "scale": f"{scale}x", "size": f"{pt}x{pt}"})
(mac / "Contents.json").write_text(json.dumps({"images": images, "info": {"author": "xcode", "version": 1}}, indent=2))
for d in (root / "iOS/Assets.xcassets", root / "Mac/Assets.xcassets"):
    (d / "Contents.json").write_text(json.dumps({"info": {"author": "xcode", "version": 1}}, indent=2))
print("icons written")
PY
