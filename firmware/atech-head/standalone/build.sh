#!/usr/bin/env bash
# Build the standalone head firmware: the Atech toolchain fetches the module drivers (project.yaml), then the
# website agent's program in src/ replaces the generated main. Include shims map its "modules/<group>/x.h" paths
# onto the toolchain's flat driver libraries. Usage: ./build.sh [upload PORT]
set -euo pipefail
cd "$(dirname "$0")"
source ../.venv/bin/activate
atech build . > /dev/null                      # generates build/ with build/lib/atech_* drivers + platformio.ini
if [ -z "${VERBOSE:-}" ]; then
  # Mute the Atech drivers' debug prints (e.g. "[NeoPixel] Brightness set" many times a second): on a charger with
  # no USB host reading, they stalled the loop and knob presses were missed (bench 2026-11-14). Only the generated
  # copies in build/lib are touched; src/main.cpp keeps its JSON lines. VERBOSE=1 ./build.sh keeps the prints.
  for f in build/lib/atech_*/*.cpp; do
    grep -q 'Serial\.' "$f" || continue
    python3 - "$f" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1]); s = p.read_text()
last = max(m.end() for m in re.finditer(r'^#include[^\n]*\n', s, re.M))
mute = ("// kaiku build.sh: driver debug prints muted (VERBOSE=1 keeps them)\n"
        "namespace { struct KaikuMuteSerial {\n"
        "  template <class... A> size_t print(A&&...) { return 0; }\n"
        "  template <class... A> size_t println(A&&...) { return 0; }\n"
        "  size_t printf(const char*, ...) { return 0; }\n"
        "} kaikuMuteSerial; }\n#define Serial kaikuMuteSerial\n")
p.write_text(s[:last] + mute + s[last:])
PY
  done
fi
rm -f build/src/*.cpp build/src/*.h
cp src/*.cpp src/*.h build/src/
for m in shared/atech_helpers display/st7735_tft input/rotary_encoder audio/speaker audio/microphone \
         motor/dc_motor sensor/icm40608 led/neopixel; do
  mkdir -p "build/src/modules/$(dirname "$m")"
  printf '#pragma once\n#include <%s.h>\n' "$(basename "$m")" > "build/src/modules/$m.h"
done
if [ "${1:-}" = upload ]; then
  # 115200 + --no-stub: the only upload that verifies on this Mac (bench 2026-11-14)
  sed -i '' 's/^upload_speed = .*/upload_speed = 115200/' build/platformio.ini
  python3 -c 'import pathlib; p = pathlib.Path("build/platformio.ini"); s = p.read_text()
if "--no-stub" not in s: p.write_text(s.replace("upload_flags =\n", "upload_flags =\n    --no-stub\n", 1))'
  pio run -d build -t upload --upload-port "${2:?usage: ./build.sh upload /dev/cu.usbmodemXXXX}"
else
  pio run -d build
fi
