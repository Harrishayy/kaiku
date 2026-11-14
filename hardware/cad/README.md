# CAD

Kaiku's body, built around the hardware we actually have. Everything is generated from one parametric script.
Dimensions come from `hardware/dimensions.md`. Assembly and the cardboard build are in `hardware/assembly.md`.

## Provenance (D8)

| File | Drawn by | When | Notes |
|---|---|---|---|
| `kaiku_cad.py` (every printed part) | Claude Code, with Edwin | 2026-11-14, during the event | New geometry around the measured hardware. Nothing reused from the pre-event renders. |
| `render.py`, `slice.py`, `cardboard.py`, `overview.py` | Claude Code, with Edwin | 2026-11-14, during the event | Tooling: renders, Bambu Studio slicing, cardboard template, local overview page. |

The pre-event concept renders mentioned in `handoff.md` §8 were not used.

## The design: a little "cathedral radio" (kaiku = echo)

- **Head (112 × 60 × 134 mm, arched top).** The Arduino USB Camera's ring light is the big round "speaker
  grille" in the middle of the face. The camera stands on its own folded clip on the head floor, and its front
  rim rests on a 65 mm lip. The Color Display sits above it in a "tuning window" and shows the eyes.
  - **Left ear:** the Knob (tuning dial).
  - **Right ear:** a microphone grille. The Microphone module sits behind it; this is optional.
  - **Inside:** the KY-031 knock sensor is glued under the top for taps (the drum). A wire antenna with a ball on top goes in the
    top socket.
- **Neck.** The pan base, glued on the body top, carries a fixed hollow axle. All the head cables go through it.
  - The turntable has a 40-tooth ring gear (module 1.25). It turns on the axle and the head glues onto its disc.
  - The pan motor hangs under the pan base in a sleeve and drives a 12-tooth pinion: 3.33 : 1 reduction.
  - A 6 × 3 mm magnet in the gear and a KY-035 hall sensor under the flange give the home position.
- **Body (104 × 136 × 100 mm).** It holds:
  - the Atech board, standing on the left wall;
  - the UNO Q on four standoffs (UNO hole pattern), with its USB-C at the rear;
  - the Speaker against the right-wall grille;
  - two LED grids behind the chest louvres (breathing glow);
  - the Modulino Buzzer on the right wall;
  - an optional purr motor mount on the floor (needs a free Atech port).
- **On the lid:** the pan base, a square opening for the Button module (or its cable), and the KY-039 pulse
  sensor under a finger cradle. A finger hole lets you lift the lid out.
- **One motor** (pan). All 12 Atech ports are used, so the purr mount is optional (D23). There is no tilt, because a
  200 g head that sits in front of the motor would make it slip back under load.
- **No ultrasonic sensor** (vision only).

Fit check: `kaiku_cad.py` intersects every printed part with every bought-in envelope. It currently reports
**no clashes**. Envelopes marked ASSUMED in `dimensions.md` (button, LED height) are guesses:
measure them before printing the part that holds them.

## Print plan (Bambu Studio's own estimates, 2026-11-14)

Any colour works. Each plate is one filament, so nothing needs an AMS colour change: no purge waste, no prime tower.
Every part prints without supports or a brim. `slice.py` tries every allowed layer height for each plate and keeps
the fastest. Plates with gear teeth are held at 0.20 mm.

| Plate | Set | P1S | P2S |
|---|---|---|---|
| 1 head: shell + back lid | MVP | 1 h 47 min, 119 g (0.28) | 1 h 45 min, 119 g (0.28) |
| 2 neck: turntable, pan base, motor sleeves, finger cradle | MVP | 1 h 10 min, 40 g (0.20) | 1 h 09 min, 40 g (0.20) |
| 3 small parts: pinion, purr weight, ears, knob cap, antenna ball, cheeks | MVP | 26 min, 10 g (0.20) | 25 min, 10 g (0.20) |
| 4 face bezel | full | 12 min, 9 g (0.24) | 11 min, 9 g (0.24) |
| 5 body tub + lid + window pane | body | 2 h 21 min, 149 g (0.28) | 2 h 17 min, 149 g (0.28) |
| **MVP (cardboard body)** | | **3 h 23 min, 170 g** | **3 h 19 min, 170 g** |
| **Full printed robot** | | **5 h 55 min, 327 g** | **5 h 47 min, 327 g** |

Budget was MVP < 4 h 30 min and full < 8 h (9 h with the body). The renders use suggested colours
(cream, teal, amber, black), but nothing depends on them; the face bezel and cheeks are optional.

Print order: plate 2 (neck: the pan mechanism can be tested on the bench), plate 1 (head), plate 3, then 4 and 5
if there is time.

## Rebuild

```bash
uv run --script hardware/cad/kaiku_cad.py          # STEP, print STLs, fit check, report.json  (~15 s)
/Applications/Blender.app/Contents/MacOS/Blender -b -P hardware/cad/render.py     # renders (~3 min)
uv run --script hardware/cad/slice.py              # Bambu Studio slicing, P1S + P2S  (~5 min)
uv run --script hardware/cad/cardboard.py          # cardboard template (--t 3 for 3 mm board)
uv run --script hardware/cad/overview.py           # out/overview.html: renders, plates, parts, cardboard
```

Everything goes to `hardware/cad/out/`, which is **gitignored**. To print, use the STLs in `out/stl/`: they are
already in print orientation, so load them in any slicer. Run the commands above to get:

- `out/overview.html`: every view and table on one page;
- `out/print/P1S/*.3mf` and `out/print/P2S/*.3mf`: open one in Bambu Studio and press Print;
- `out/stl/`: the parts, already rotated into print orientation;
- `out/kaiku_assembly.step`: the named assembly, for Fusion, Onshape or FreeCAD.

Change sizes in the `P` dataclass at the top of `kaiku_cad.py`, then rerun. Don't edit the STLs.

## Known gaps

- Sizes marked ASSUMED (button, LED height) are guesses. The knob is a photo estimate; its cap's 9.8 mm bore has to
  fit over the module's own black knob. The display is a photo estimate (42 × 21 × 10, screen
  centred); the frame around it is open at the top for the cable plugs.
- The motor shaft is assumed to be the standard 3 mm D-shaft. The pinion and purr weight have D-holes; if the
  shaft is round, glue them.
- The head lid, pan base and turntable-to-head joints are glued (two M3 holes are there for screws if you have
  them). Nothing holds the turntable down: gravity and the gear keep it in place, so lift the robot by the body.
- The body's 72 mm rear cable slot and the 52 mm chest louvres are long bridges. They print fine on the P1S and
  P2S, but expect a little sag.
