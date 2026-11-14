#!/bin/sh
# Copy the ground-truth design + safety files into KaikuKit (plain copies, no symlinks, so Xcode and SwiftPM
# resolve them without the repo layout). design/ and config/ stay the ground truth: edit THERE, then run this.
# KaikuKitTests/SyncFreshnessTests fails when a copy is stale.
set -eu
HERE="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
KIT="$HERE/KaikuKit/Sources/KaikuKit"
cp "$ROOT/design/generated/Tokens.swift" "$KIT/Design/Tokens.swift"
cp "$ROOT/design/copy.json"              "$KIT/Resources/copy.json"
cp "$ROOT/design/mascot.spec.json"       "$KIT/Resources/mascot.spec.json"
cp "$ROOT/config/safety_phrases.toml"    "$KIT/Resources/safety_phrases.toml"
echo "synced design + safety files into KaikuKit"
