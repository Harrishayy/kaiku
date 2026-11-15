# Assembly

> **Illustrated step-by-step version:** [`assembly_guide/kaiku_assembly.pdf`](assembly_guide/kaiku_assembly.pdf).

How to put Kaiku together, either on the **cardboard body (MVP)** or the **printed body**. The parts come from
`hardware/cad/` (see its README for the print plan). Positions below are in mm. Every number comes from
`hardware/cad/kaiku_cad.py`, so if a parameter changes, regenerate the files rather than editing this page.

## What you need besides the printed parts

- Hot-glue gun, plus superglue for the PLA-to-PLA joints.
- Not needed for this build: a 6 × 3 mm disc magnet (pan homing with a KY-035; neither is fitted, D39).
- One 3 mm bamboo skewer or stiff wire, about 50 mm long (the antenna).
- Double-sided foam tape.
- Optional: two M3 × 8 screws (head to turntable).
- MVP: one corrugated cardboard sheet, about 3–4 mm thick, at least 500 × 300 mm. Also a craft knife, a steel
  ruler and some tracing paper (behind the chest window).

## Atech ports: the robot as built

The board has 12 module ports (1–7, 9–11, 13–14); two-port modules need a neighbouring pair on the same side.
What is plugged in is what the running firmware declares
(`firmware/atech-head/standalone/project.yaml`; pin ground truth: `hardware/wiring.md`):

| Module | Ports | Where (the CAD's place for it) |
|---|---|---|
| Speaker | 1–2 | body, right-wall grille |
| Knob (dial ear, with its ring light; its press is the robot's only button) | 5–6 | head, left ear |
| Neopixel light | 7 | — |
| Microphone | 9–10 | head, right ear |
| Orientation sensor (taps) | 13 | head, fixed rigidly to the shell |
| DC Motor (pan) | 14 | under the pan base |

Ports 3–4 and 11 are free. Port 11 cannot take the motor: its line (GPIO44, the serial receiver) never drove it.

**Not fitted, although the shell and the earlier layout have a place for them:** the Color Display (eyes, ports
3–4; removed 2026-11-14), the lid Button (port 7 in the earlier layout), the two chest LED grids (D54), the KY-031
knock switch (D55), the KY-039 pulse sensor and its KY-053 converter (D54), the KY-035 hall sensor and the KY-054
light sensor (D39). The earlier layout, with all 12 ports used, is in `docs/kaiku_robot_electronics_specs.md`; it
is not what was built.

So there is **one motor** (pan), with no homing: the head has no position sensor. Taps come from the Atech
orientation sensor in the head (D55). The purr mount in the CAD stays as an option. Power comes through the
Atech USB-C module (port 8) from its own charger (D54). The UNO Q and the camera run off a powered USB-C PD hub
that sits behind the robot; the UNO Q carries the camera and the Modulino Buzzer on Qwiic, and nothing else.

## 1. Neck (printed plate 2 + plate 3), about 15 min

1. Press the **pinion** onto the pan motor's shaft, flat side to flat side, until it is flush with the shaft end.
2. Slide the **pan motor** into **pan_motor_mount**, shaft end first, so its end face is flush with the open top
   of the sleeve. The connector end hangs down.
3. Glue the sleeve's top edge to the underside of **pan_base**, centred under the small hole (the pinion pokes
   through it). The motor's end face then touches the flange.
4. *Only if you have a KY-035 and a 6×3 mm magnet (not in this build, D39):* glue the magnet into the pocket under
   the **turntable** gear and tape the **KY-035 hall sensor** under the pan base flange, 18 mm in front of the axle
   centre. That is the spot the magnet passes over at "home" (head facing front). Without them the pocket stays
   empty.
5. Drop the turntable over the axle. Its gear should mesh with the pinion, and it should turn freely; a drop of
   grease helps. Spin the motor by hand to check the mesh.

## 2. Head (printed plate 1 + 3 + 4), about 25 min

1. Glue the **face bezel** onto the front, then the two **cheeks** below and beside the ring. These are optional.
2. (No Color Display in this build: it was removed on 2026-11-14. The shell keeps its frame and small window;
   leave them empty. With a display: screen forward, **connector edge up**, taped in the frame.)
3. **Camera:** fold its clip flat under the body and stand it on the head floor, ring forward, so the front rim
   rests on the round lip. Run its USB cable down through the floor slot.
4. Put the square **Knob** module flat against the left inner wall, with its knob through the ear hole. Glue the
   **left ear** ring on the outside, then press the **knob cap** over the module's own black knob (add a drop of
   glue if it's loose). Optional: drill the ear hole out to Ø26 to show the module's light ring.
5. *Optional:* glue the **Microphone** module against the right inner wall behind the hole pattern, then glue the
   **right ear** grille on the outside.
6. Fix the Atech **Orientation Sensor** module rigidly inside the head (foam tape or glue against the shell): it
   feels the taps on the head. (No KY-031 knock sensor in this build, D55.)
7. Push the skewer into the antenna socket on top and glue on the **antenna ball**.
8. Plug every head cable in now (knob ×2, mic ×2, orientation sensor ×1; no display and no KY-031 wires in this
   build), and route them all down through the floor
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
   - (No LED grids in this build, D54.)
   - *Optional, only if it has a port:* glue the **purr_sleeve** to the floor at the front-left, shaft pointing
     left, slide a second motor in and press the **purr weight** onto its shaft.
   - Glue the **Modulino Buzzer** to the right wall above the speaker and run its Qwiic cable to the UNO Q.
3. Lid:
   - Glue **four cardboard strips** (10 mm wide) under the lid, 4 mm in from each edge, so it drops in and
     stays put.
   - Glue the neck's **pan base** on top, with the motor sleeve through the pan hole.
   - Glue the **finger cradle** over the Ø9 hole (cosmetic now: no KY-039 in this build, D54).
   - (No Button module in this build: the square hole stays empty. The ear's press is the only button.)
4. Pass all the cables to the board and the UNO Q, put the lid on, and plug the power and USB cables in through
   the back.

## 3b. Printed body (plate 5), about 30 min

Same layout as 3a. The tub already has the UNO Q standoffs (M3 self-tapping, or hot glue), the grilles and the
cable openings. The **window pane** glues inside behind the chest louvres. The **top plate** rests on the inner
ledge and lifts out using its finger hole.

## Before you power on

- Turn the head by hand through its whole range (about ±100°; nothing in the firmware limits it). The cable bundle in the axle must not pull.
  Leave a loop inside the body.
- **Face the head forward before powering on.** There is no homing and no position sensor (no hall sensor, D39):
  the running firmware turns the head in short timed nudges at full speed and does not know its angle (D66). The
  orientation sensor in the head is used for taps only.
- Update `hardware/wiring.md` with the actual port numbers as you plug things in.
