# Assembly

> **Illustrated step-by-step version:** [`assembly_guide/kaiku_assembly.pdf`](assembly_guide/kaiku_assembly.pdf).

How to put Kaiku together, either on the **cardboard body (MVP)** or the **printed body**. The parts come from
`hardware/cad/` (see its README for the print plan). Positions below are in mm. Every number comes from
`hardware/cad/kaiku_cad.py`, so if a parameter changes, regenerate the files rather than editing this page.

## What you need besides the printed parts

- Hot-glue gun, plus superglue for the PLA-to-PLA joints.
- One 6 × 3 mm disc magnet (pan homing).
- One 3 mm bamboo skewer or stiff wire, about 50 mm long (the antenna).
- Double-sided foam tape.
- Optional: two M3 × 8 screws (head to turntable).
- MVP: one corrugated cardboard sheet, about 3–4 mm thick, at least 500 × 300 mm. Also a craft knife, a steel
  ruler and some tracing paper (behind the chest window).

## Atech ports: there are only 12

The board has 12 module ports (1–7, 9–11, 13–14); two-port modules need a neighbouring pair on the same side.
The layout from `docs/kaiku_robot_electronics_specs.md` uses all 12:

| Module | Ports | Where |
|---|---|---|
| Speaker | 1–2 | body, right-wall grille |
| Color Display (eyes) | 3–4 | head, tuning window |
| Knob (dial ear) | 5–6 | head, left ear |
| Button ("I'm not OK" / push to talk) | 7 | lid, square opening |
| Microphone | 9–10 | head, right ear |
| LED Grid left / right (breathing glow) | 11 / 14 | body, behind the chest louvres (port 11 stayed dark on the bench: `hardware/wiring.md`) |
| DC Motor (pan) | 13 | under the pan base |

So there is **one motor** (pan) and no Atech IMU: taps come from the KY-031 on the UNO Q. The purr mount in the CAD
stays as an option: it needs a free port (drop one LED grid, or the Speaker). Power comes through the Atech USB-C
module (port 8). The UNO Q and the camera run off a powered USB-C PD hub that sits behind the robot.

The UNO Q side (D39: no KY-035 hall, no KY-054 light): KY-031 knock (D2), KY-053 ADC for the
KY-039 pulse (SDA/SCL), and the Modulino Buzzer on Qwiic. Pin ground truth: `hardware/wiring.md`.

## 1. Neck (printed plate 2 + plate 3), about 15 min

1. Press the **pinion** onto the pan motor's shaft, flat side to flat side, until it is flush with the shaft end.
2. Slide the **pan motor** into **pan_motor_mount**, shaft end first, so its end face is flush with the open top
   of the sleeve. The connector end hangs down.
3. Glue the sleeve's top edge to the underside of **pan_base**, centred under the small hole (the pinion pokes
   through it). The motor's end face then touches the flange.
4. Glue the **magnet** into the pocket under the **turntable** gear.
5. *Only if you have a KY-035 and a 6×3 mm magnet (not in this build, D39):* glue the magnet in the gear pocket and
   tape the **KY-035 hall sensor** under the pan base flange, 18 mm in front of the axle centre. That
   is the spot the magnet passes over at "home" (head facing front).
6. Drop the turntable over the axle. Its gear should mesh with the pinion, and it should turn freely; a drop of
   grease helps. Spin the motor by hand to check the mesh.

## 2. Head (printed plate 1 + 3 + 4), about 25 min

1. Glue the **face bezel** onto the front, then the two **cheeks** below and beside the ring. These are optional.
2. Put the **Color Display** into the frame behind the small window, screen forward, **connector edge up** (the
   frame is open at the top for the plugs). Tape it in place. Check that the screen lines up with the window
   *before* gluing.
3. **Camera:** fold its clip flat under the body and stand it on the head floor, ring forward, so the front rim
   rests on the round lip. Run its USB cable down through the floor slot.
4. Put the square **Knob** module flat against the left inner wall, with its knob through the ear hole. Glue the
   **left ear** ring on the outside, then press the **knob cap** over the module's own black knob (add a drop of
   glue if it's loose). Optional: drill the ear hole out to Ø26 to show the module's light ring.
5. *Optional:* glue the **Microphone** module against the right inner wall behind the hole pattern, then glue the
   **right ear** grille on the outside.
6. Glue the **KY-031 knock sensor** flat under the head top, behind the display, on foam tape. The top is where
   you tap.
7. Push the skewer into the antenna socket on top and glue on the **antenna ball**.
8. Plug every head cable in now (display ×2, knob ×2, mic ×2, three KY-031 jumper wires), and route them all
   down through the floor
   slot. Fit the **back lid**: its two ribs push the camera forward against the lip.
9. Feed the cable bundle through the turntable disc and down the hollow axle. Glue the head floor onto the
   turntable disc, with the floor slot over the disc slot, facing front. Use the two M3 screws if you have them.

## 3a. Cardboard body (MVP), about 45 min

Get the template: `uv run --script hardware/cad/cardboard.py --t <your board thickness>`, then print
`hardware/cad/out/cardboard/<panel>_A4.svg` at **100 %**. Check the 50 mm bar before you cut. Or measure the
panels directly from this table (4 mm board; the generator recomputes for other thicknesses):

| Panel | Size (mm) | Cut-outs: size, centre measured from the panel's bottom-left corner seen from outside |
|---|---|---|
| Bottom | 104 × 136 | none |
| Front | 104 × 92 | chest window 52 × 30 at (52, 43); cover with tracing paper from inside |
| Back | 104 × 92 | cable slot 72 × 20 at (62, 11); Atech USB-C 18 × 14 at (84, 55) |
| Left | 128 × 92 | none (the Atech board is taped inside) |
| Right | 128 × 92 | speaker grille: 7 × 5 holes Ø3, 6 mm apart, the first at (60, 8) |
| Lid | 104 × 136 | pan hole 29 × 76 at (52, 79); button 23.4 square at (20, 114); pulse Ø9 at (52, 20); lift hole Ø16 at (84, 120); light sensor Ø5 at (86, 96) |

1. Hot-glue the **front** and **back** standing on the **bottom**, then the two **sides** between them.
2. **Inside, before the lid goes on:**
   - Tape the **Atech board** to the left wall, 8 mm off it on a foam-tape stack, with its USB-C module at the
     rear top. Line the USB-C up with the back hole.
   - Tape the **UNO Q** to the floor at the rear, with its USB-C facing the cable slot.
   - Tape the **speaker** to the right wall, behind the grille.
   - Tape the two **LED grids**, lit face forward, behind the chest window.
   - *Optional, only if it has a port:* glue the **purr_sleeve** to the floor at the front-left, shaft pointing
     left, slide a second motor in and press the **purr weight** onto its shaft.
   - Glue the **Modulino Buzzer** to the right wall above the speaker and run its Qwiic cable to the UNO Q.
3. Lid:
   - Glue **four cardboard strips** (10 mm wide) under the lid, 4 mm in from each edge, so it drops in and
     stays put.
   - Glue the neck's **pan base** on top, with the motor sleeve through the pan hole.
   - Glue the **finger cradle** over the Ø9 hole, then tape the **KY-039** under that hole, LED facing up.
   - Drop the **button** module into its square hole.
   - Tape the **KY-053** ADC to the floor next
     to the UNO Q.
4. Pass all the cables to the board and the UNO Q, put the lid on, and plug the power and USB cables in through
   the back.

## 3b. Printed body (plate 5), about 30 min

Same layout as 3a. The tub already has the UNO Q standoffs (M3 self-tapping, or hot glue), the grilles and the
cable openings. The **window pane** glues inside behind the chest louvres. The **top plate** rests on the inner
ledge and lifts out using its finger hole.

## Before you power on

- Turn the head by hand through its whole range (about ±100°). The cable bundle in the axle must not pull.
  Leave a loop inside the body.
- Home the head: **face it forward before powering on**; that position is 0° (no hall sensor, D39). The firmware works out the pan
  angle from timed moves between homings (there is no IMU; `docs/kaiku_robot_electronics_specs.md`).
- Update `hardware/wiring.md` with the actual port numbers as you plug things in.
