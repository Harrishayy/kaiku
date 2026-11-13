# hardware — AGENTS.md

> Read the root `AGENTS.md` first. Owner A.

- `cad/` — STL/STEP. **Provenance is mandatory** in `cad/README.md` (renders were made before the event; ask
  organisers, disclose, redraw if not allowed — decision D8).
- `wiring.md` — ground truth for every pin, voltage and level shifter. Update it the moment you wire something.
  KY-050 echo is 5 V → KY-051 level shifter/divider before any 3.3 V pin.
- `bom.md` — parts list.
- `dimensions.md` — ground truth for every part's physical size (datasheet, photo estimate or caliper value) for CAD.
- `datasheets/` — vendor PDFs, **gitignored** (third-party copyright). Re-download from the URLs in its `SOURCES.md`.
- Build notes (form, mapping of parts to functions, motion without servos, printing): `handoff.md` §8.
- Firmware that runs on this hardware lives in `firmware/*` (each with its own AGENTS.md).
