# hardware — AGENTS.md

> Read the root `AGENTS.md` first. Owner A.

- `cad/` — parametric CAD (`kaiku_cad.py`), renders, Bambu slicing (P1S/P2S), cardboard template; outputs in
  gitignored `cad/out/` (open `cad/out/overview.html`). Design, print plan and rebuild commands: `cad/README.md`.
  **Provenance is mandatory** in `cad/README.md` (renders were made before the event; ask
  organisers, disclose, redraw if not allowed — decision D8).
- `wiring.md` — ground truth for every pin, voltage and cable (D31 hardware, D32 software,
  `docs/plans/07-robot-electronics.md`). Update it the moment you wire something; each row names the bench test that
  proves it (`make bench-list`). UNO Q headers/Qwiic are 3.3 V, JCTL/bottom connectors 1.8 V; power the UNO Q
  through the PD hub (camera).
- **The robot as built** (D39, D54, D55, D66; `firmware/atech-head/standalone/project.yaml`): Atech board with
  Speaker 1–2, Knob 5–6 (ear dial with ring light; its press is the only button), a neopixel light on 7, Microphone
  9–10, Orientation Sensor 13 (the only tap source), pan motor 14 (open loop, no homing); UNO Q with the USB camera
  and the Modulino Buzzer. Not fitted: display, lid button, LED grids, every KY sensor. The printed shell and the
  assembly figures still have a place for each; the docs here say "not fitted" where that is so.
- `bom.md` — parts list.
- Electronics source spec (boards, ports, power, behaviour): `docs/kaiku_robot_electronics_specs.md`; how it maps onto
  the repo: plan 07.
- `assembly_guide/kaiku_assembly.pdf` — step-by-step illustrated build of the MVP, built from the hand-written
  `kaiku_assembly.tex` (figures from `cad/assembly_guide.py`; rebuild: Blender `-b -P hardware/cad/assembly_guide.py`
  for the figures, then `latexmk -pdf` in `assembly_guide/`). The text and the PDF were brought up to the robot as
  built on 2026-11-15 (PDF rebuilt, 8 pages). **The figures were not rendered again** and still draw the design
  before D54/D55 (display, KY-031, LED grids, KY-039, button); each such step says the part is not fitted.
- `assembly.md` — build steps (neck, head, cardboard or printed body) and the Atech ports as built.
- `dimensions.md` — ground truth for every part's physical size (datasheet, photo estimate or caliper value) for CAD.
- `datasheets/` — vendor PDFs, **gitignored** (third-party copyright). Re-download from the URLs in its `SOURCES.md`.
- Build notes (form, mapping of parts to functions, motion without servos, printing): `docs/plans/01-foundation.md` §8.
- Firmware that runs on this hardware lives in `firmware/*` (each with its own AGENTS.md).
