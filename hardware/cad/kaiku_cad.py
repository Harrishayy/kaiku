# /// script
# requires-python = ">=3.11"
# dependencies = ["build123d>=0.9"]
# ///
"""Kaiku desk robot: parametric CAD, the single source of truth for every printed part.

Run:  uv run --script hardware/cad/kaiku_cad.py
Out (hardware/cad/out/):
  kaiku_assembly.step       named, coloured assembly (open in Fusion / FreeCAD / Onshape)
  stl/<part>.stl            printed parts, already rotated into print orientation
  render/*.stl, scene.json  every body in assembly position, for render.py (Blender)
  report.json               sizes, volumes, print sets, fit-check result

Axes: X = right, Y = back (the robot faces -Y), Z = up, Z = 0 is the desk. Millimetres.
Bought-in parts are envelopes named REF_*; sizes come from hardware/dimensions.md.
Anything marked ASSUMED there has not been measured; re-measure before printing the part that holds it.

Written during Junction 2026 (see hardware/cad/README.md for provenance).
"""

from __future__ import annotations

import itertools
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from build123d import (
    Align,
    Axis,
    Box,
    Color,
    Compound,
    Cone,
    Cylinder,
    Polygon,
    Pos,
    RectangleRounded,
    Rot,
    Sphere,
    export_step,
    export_stl,
    extrude,
    fillet,
)

HERE = Path(__file__).parent
OUT = HERE / "out"
MIN = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class P:
    # ---------------- bought-in parts (hardware/dimensions.md) ----------------
    motor: tuple = (23.0, 23.0, 44.0)      # Atech DC Motor V2.3 body; 3 mm shaft on the centre of one end
    shaft_d: float = 3.0
    shaft_flat: float = 2.5                # D-flat: flat-to-round distance (N20 standard; VERIFY)
    shaft_len: float = 10.0
    plug_clear: float = 15.0               # cable plug room past the connector end of every module
    speaker: tuple = (48.0, 45.0, 23.0)    # Atech Speaker V2.2 (photo estimate)
    mic: tuple = (21.0, 41.0, 12.0)        # Atech Microphone V1.1 (photo estimate)
    cube: float = 22.0                     # 1-port Atech module footprint (LED grid, IMU, button)
    cube_h: float = 16.0                   # ASSUMED height
    display: tuple = (42.0, 21.0, 10.5)    # Color Display 160x80 front x height x depth (photo est. vs the mic)
    display_win: tuple = (28.0, 13.0)      # its screen: 28.8 x 13.7 dark area, centred on the module
    display_plug: float = 12.0             # cable plugs on its top long edge need this much room
    knob: tuple = (42.0, 42.0, 13.0)       # Knob module: square face x height (photo est.); knob out of the face
    knob_out: float = 23.0                 # bushing (~8 mm) + its own black knob (~9.5 x 14 mm) above the face
    knob_d: float = 9.5                    # that knob's diameter: the printed cap slides over it
    board: tuple = (127.0, 68.0, 6.0)      # Atech motherboard (photo estimate), thickness ASSUMED
    unoq: tuple = (53.34, 68.58, 13.5)     # Arduino UNO Q, datasheet; height incl. headers (photo est.)
    cam_d: float = 70.0                    # Arduino USB Camera TPX00246 body, datasheet
    cam_depth: float = 40.0
    clip: tuple = (64.0, 37.0, 22.0)       # its folded clip under the body (photo estimate)
    ky039: tuple = (25.0, 15.0, 8.0)       # pulse sensor board, nominal
    ky035: tuple = (18.5, 15.0, 6.0)       # hall sensor board, nominal
    magnet_d: float = 6.0                  # homing magnet (any 6x3 mm disc)
    magnet_t: float = 3.0

    # ---------------- body ----------------
    body_w: float = 104.0
    body_d: float = 136.0
    body_h: float = 100.0
    body_r: float = 16.0
    body_ri: float = 14.2                  # inside corner radius; must be >= body_r - wall or the corner opens
    wall: float = 1.8
    floor: float = 2.0
    top_t: float = 2.4
    window: tuple = (52.0, 30.0)           # chest window (2 LED grids behind it)
    window_z: float = 47.0

    # ---------------- neck / pan ----------------
    gear_m: float = 1.25
    ring_teeth: int = 40                   # on the turntable
    pinion_teeth: int = 12                 # on the pan motor: 3.33:1
    gear_face: float = 6.0
    flange_t: float = 3.0
    thrust_t: float = 0.6
    axle_od: float = 24.0
    axle_id: float = 19.0
    neck_r: float = 20.0
    disc_r: float = 29.0

    # ---------------- head ----------------
    head_w: float = 112.0
    head_h: float = 134.0
    head_d: float = 60.0
    head_r: float = 38.0                   # top corners: the arch
    head_r_bot: float = 10.0
    head_wall: float = 2.0
    cam_window_d: float = 65.0             # smaller than the 70 mm body: the camera's front rim rests on it
    ear_z: float = 64.0                    # ear centre above the head floor

    @property
    def pan_a(self) -> float:              # gear centre distance
        return self.gear_m * (self.ring_teeth + self.pinion_teeth) / 2


p = P()

# brand-ish palette (apps/web/app/globals.css)
CREAM = Color(0.95, 0.92, 0.86)
TEAL = Color(0.18, 0.44, 0.39)
INK = Color(0.15, 0.16, 0.18)
AMBER = Color(0.93, 0.62, 0.20)
WHITE = Color(0.97, 0.97, 0.95)
GREY = Color(0.55, 0.57, 0.60)
DARK = Color(0.10, 0.10, 0.11)
PCB = Color(0.15, 0.40, 0.25)
GLOW = Color(0.55, 0.95, 0.90)

# ---------------------------------------------------------------- derived heights ---
TOP = p.body_h                                   # top surface of the body
GEAR_Z = TOP + p.flange_t + p.thrust_t           # underside of the turntable gear
AXLE_TOP = GEAR_Z + p.gear_face + 8.0            # bore guidance = gear + 8 mm of neck
FLARE_Z = AXLE_TOP
DISC_Z = FLARE_Z + (p.disc_r - p.neck_r)         # 45 degree flare: printable without support
HEAD_Z = DISC_Z + 2.0                            # head floor sits here
IN_W = p.body_w - 2 * p.wall                     # body inside
IN_D = p.body_d - 2 * p.wall
LEDGE_Z = TOP - p.top_t                          # top plate rests here
HW = p.head_w / 2 - p.head_wall                  # head inside half-width
HFRONT = -p.head_d / 2 + p.head_wall             # head inside front face (y)
CAM_Z = p.head_wall + p.clip[2] + p.cam_d / 2    # camera centre above the head floor
CABLE_SLOT = (30.0, 11.0, 23.0)                  # head floor + turntable disc: width, y0, y1


# ---------------------------------------------------------------------- helpers ---
def mk(shape, label: str, color: Color):
    shape.label = label
    shape.color = color
    return shape


def rbox(w, d, h, r, z0=0.0):
    """Box with vertical edges rounded, bottom at z0."""
    return Pos(0, 0, z0) * extrude(RectangleRounded(w, d, r), h)


def slab_y(w, h, r, t, r_bot=None):
    """Rounded plate in the XZ plane, centred on x and z, spanning y in [0, t].
    With r_bot, the top corners get radius r and the bottom corners r_bot (cathedral-radio arch)."""
    prof = RectangleRounded(w, h, r)
    if r_bot is not None:
        prof = prof + Pos(0, -h / 4) * RectangleRounded(w, h / 2, r_bot)
    return Pos(0, t, 0) * (Rot(90, 0, 0) * extrude(prof, t))


def cyl_x(r, length, x0=0.0):
    return Pos(x0, 0, 0) * (Rot(0, 90, 0) * Cylinder(r, length, align=MIN))


def cyl_y(r, length, y0=0.0):
    return Pos(0, y0, 0) * (Rot(-90, 0, 0) * Cylinder(r, length, align=MIN))


def d_hole(depth, clearance=0.15):
    """Hole for the 3 mm D-shaft, along +Z from z = 0, flat facing +X."""
    r = p.shaft_d / 2 + clearance
    flat = p.shaft_flat - p.shaft_d / 2 + clearance
    round_part = Cylinder(r, depth, align=MIN)
    keep = Pos(flat - 2 * r, 0, 0) * Box(4 * r, 4 * r, depth, align=MIN)
    return round_part & keep


def gear(teeth: int, m: float, face: float, backlash: float = 0.15, pa_deg: float = 20.0):
    """Involute spur gear, axis Z, from z = 0 to face. Teeth thinned by `backlash` (mm on the pitch circle)."""
    pa = math.radians(pa_deg)
    rp = m * teeth / 2
    rb = rp * math.cos(pa)
    ra = rp + m
    rf = rp - 1.25 * m
    inv_pa = math.tan(pa) - pa
    half = math.pi / (2 * teeth) - backlash / (2 * rp)
    t_tip = math.sqrt((ra / rb) ** 2 - 1)
    flank = []
    for i in range(10):
        t = t_tip * i / 9
        flank.append((rb * math.sqrt(1 + t * t), t - math.atan(t)))
    pts = []
    for k in range(teeth):
        base = 2 * math.pi * k / teeth
        lower = [(r, base - half - inv_pa + th) for r, th in flank]
        upper = [(r, base + half + inv_pa - th) for r, th in reversed(flank)]
        tooth = []
        if rf < rb:
            tooth.append((rf, lower[0][1]))
        tooth += lower + upper
        if rf < rb:
            tooth.append((rf, upper[-1][1]))
        pts += [(r * math.cos(a), r * math.sin(a)) for r, a in tooth]
    return extrude(Polygon(*pts, align=None), face)


def soft(part, radius, axis=Axis.Z):
    """Round the edges parallel to an axis; skip silently if the kernel refuses."""
    try:
        return fillet(part.edges().filter_by(axis), radius)
    except Exception:  # noqa: BLE001 - cosmetic only
        return part


# ======================================================================== BODY ===
def body_tub():
    outer = rbox(p.body_w, p.body_d, p.body_h, p.body_r)
    inner = rbox(IN_W, IN_D, p.body_h, p.body_ri, z0=p.floor)
    tub = outer - inner
    # stepped 45 degree ledge the top plate rests on
    for i, w in enumerate((0.8, 1.6, 2.4)):
        z0 = LEDGE_Z - 2.4 + 0.8 * i
        ring = rbox(IN_W, IN_D, 0.8, p.body_ri, z0) - rbox(IN_W - 2 * w, IN_D - 2 * w, 0.8,
                                                          max(p.body_ri - w, 0.5), z0)
        tub += ring
    front = -p.body_d / 2
    # chest window
    # chest grille: five louvre slots the LED glow shines through (radio-cabinet look)
    for i in range(5):
        z = p.window_z + (i - 2) * 6.0
        tub -= Pos(0, front - 1, z) * (Rot(-90, 0, 0) * extrude(RectangleRounded(p.window[0], 3.6, 1.7), 6))
    # speaker grille, right wall
    for iy, iz in itertools.product(range(7), range(5)):
        y = -4 + iy * 6.0
        z = 12 + iz * 6.5
        tub -= Pos(p.body_w / 2 - 4, y, z) * cyl_x(1.6, 8)
    # rear cable opening: UNO Q USB-C, Atech USB-C, camera USB
    tub -= Pos(-10, p.body_d / 2 - 3, 15) * (Rot(-90, 0, 0) * extrude(RectangleRounded(72, 20, 8), 6))
    # Atech USB-C power module sits at the rear-top corner of the board
    tub -= Pos(-32, p.body_d / 2 - 3, 59) * (Rot(-90, 0, 0) * extrude(RectangleRounded(18, 14, 5), 6))
    # UNO Q standoffs (UNO R3 hole pattern), board at x -27..26.3, y -7..61.6, rotated 90 deg
    for hx, hy in UNOQ_HOLES:
        tub += Pos(hx, hy, p.floor) * (Cylinder(2.6, 5, align=MIN) - Cylinder(1.3, 5, align=MIN))
    return tub


BOARD_X = -IN_W / 2 + 8.5                              # Atech board on the left wall; 8.5 mm clears the corner radius
UNOQ_X0, UNOQ_Y0 = -27.0, 61.6 - 68.58                  # board corner (x min, y min)
# UNO R3 mounting holes from the board corner, (along 68.6 edge, along 53.3 edge), mapped onto x/y
UNOQ_HOLES = [(UNOQ_X0 + b, UNOQ_Y0 + a) for a, b in ((14.0, 2.5), (15.3, 50.7), (66.1, 7.6), (66.1, 35.5))]


def top_plate():
    plate = rbox(IN_W - 0.4, IN_D - 0.4, p.top_t, p.body_ri - 0.2, LEDGE_Z)
    plate -= Pos(0, 11, LEDGE_Z - 1) * extrude(RectangleRounded(29, 76, 6), p.top_t + 2)  # pan hole
    plate -= Pos(BUTTON_XY[0], BUTTON_XY[1], LEDGE_Z - 1) * Box(23.4, 23.4, p.top_t + 2, align=MIN)
    plate -= Pos(0, FINGER_Y, LEDGE_Z - 1) * Cylinder(4.5, p.top_t + 2, align=MIN)
    plate -= Pos(32, 52, LEDGE_Z - 1) * Cylinder(8, p.top_t + 2, align=MIN)  # finger hole to lift it out
    plate -= Pos(*LIGHT_XY, LEDGE_Z - 1) * Cylinder(2.5, p.top_t + 2, align=MIN)  # KY-054 room-light window
    return plate


BUTTON_XY = (-32.0, 46.0)
LIGHT_XY = (34.0, 28.0)
FINGER_Y = -48.0


def finger_cradle():
    """Finger rest over the KY-039 pulse sensor; dark, so it shades ambient light."""
    w, d, h = 32.0, 24.0, 9.0
    blk = Pos(0, FINGER_Y, TOP) * rbox(w, d, h, 6)
    groove = Pos(0, FINGER_Y - d, TOP + h + 4.5) * cyl_y(8.5, 2 * d)
    blk -= groove
    blk -= Pos(0, FINGER_Y, TOP - 1) * Cylinder(4.5, h + 2, align=MIN)
    return blk


def window_pane():
    w, h = p.window[0] + 6, p.window[1] + 6
    return Pos(0, -p.body_d / 2 + p.wall, p.window_z - h / 2) * (
        Pos(0, 0, h / 2) * slab_y(w, h, 6, 0.8))


# ======================================================================== NECK ===
PINION_XY = (0.0, p.pan_a)


def pan_base():
    """Fixed neck base on top of the body: flange, axle tube, thrust ring. Prints flange-down."""
    flange = Pos(0, 12, TOP) * rbox(46, 86, p.flange_t, 8)
    axle = Pos(0, 0, TOP) * Cylinder(p.axle_od / 2, AXLE_TOP - TOP, align=MIN)
    thrust = Pos(0, 0, TOP + p.flange_t) * (Cylinder(22, p.thrust_t, align=MIN) - Cylinder(13, p.thrust_t, align=MIN))
    part = flange + axle + thrust
    part -= Pos(0, 0, TOP - 1) * Cylinder(p.axle_id / 2, AXLE_TOP - TOP + 2, align=MIN)
    part -= Pos(*PINION_XY, TOP - 1) * Cylinder(3.5, p.flange_t + 2, align=MIN)
    return part


def motor_sleeve(length=16.0, end_plate=True):
    """Motor holder: square tube, optionally with an end plate (shaft hole) to glue against a wall.
    Local frame: shaft along +Z. With a plate: plate at z in [0, 2], motor face on it at z = 0.
    Tube from z = -length to the top."""
    o = p.motor[0] + 0.6 + 2 * 1.6
    top = 2.0 if end_plate else 0.0
    tube = Pos(0, 0, -length) * (Box(o, o, length + top, align=MIN) - Box(o - 3.2, o - 3.2, length + top, align=MIN))
    if not end_plate:
        return tube
    plate = Box(o, o, 2, align=MIN)
    return tube + plate - Pos(0, 0, -1) * Cylinder(3.5, 4, align=MIN)


def pan_motor_mount():
    """Pan motor sleeve, glued under the pan base through the top-plate hole."""
    s = motor_sleeve(30.0, end_plate=False)
    return Pos(*PINION_XY, TOP) * s                       # end plate up, against the flange underside


def turntable():
    """Ring gear + neck + disc the head glues onto. Prints gear-down, no supports."""
    g = gear(p.ring_teeth, p.gear_m, p.gear_face)
    neck = Pos(0, 0, p.gear_face) * Cylinder(p.neck_r, AXLE_TOP - GEAR_Z - p.gear_face, align=MIN)
    flare = Pos(0, 0, FLARE_Z - GEAR_Z) * Cone(p.neck_r, p.disc_r, DISC_Z - FLARE_Z, align=MIN)
    disc = Pos(0, 0, DISC_Z - GEAR_Z) * Cylinder(p.disc_r, 2.0, align=MIN)
    t = g + neck + flare + disc
    t -= Cylinder(p.axle_od / 2 + 0.3, AXLE_TOP - GEAR_Z, align=MIN)               # bore on the axle
    t -= Pos(0, 0, AXLE_TOP - GEAR_Z) * Cylinder(17.5, 40, align=MIN)              # cable space
    w, y0, y1 = CABLE_SLOT
    t -= Pos(0, (y0 + y1) / 2, DISC_Z - GEAR_Z - 12) * Box(w, y1 - y0, 20, align=MIN)
    t -= Pos(0, -18, -0.01) * Cylinder(p.magnet_d / 2 + 0.15, p.magnet_t + 0.2, align=MIN)  # homing magnet
    for ang in (30, 150):
        a = math.radians(ang)
        t -= Pos(24 * math.cos(a), 24 * math.sin(a), DISC_Z - GEAR_Z - 3) * Cylinder(1.4, 6, align=MIN)
    return Pos(0, 0, GEAR_Z) * t


def pinion():
    g = gear(p.pinion_teeth, p.gear_m, p.gear_face) - Pos(0, 0, -1) * d_hole(p.gear_face + 2)
    return Pos(*PINION_XY, GEAR_Z) * (Rot(0, 0, 180 / p.pinion_teeth) * g)   # tooth into gap


# ======================================================================== HEAD ===
def head_shell():
    """Front + sides + top + floor in one piece, open at the back. Prints face-down."""
    h0 = HEAD_Z
    outer = Pos(0, -p.head_d / 2, h0 + p.head_h / 2) * slab_y(p.head_w, p.head_h, p.head_r, p.head_d,
                                                                 p.head_r_bot)
    try:
        outer = fillet(outer.edges().group_by(Axis.Y)[0], 3.0)
    except Exception:  # noqa: BLE001
        pass
    inner = Pos(0, HFRONT, h0 + p.head_h / 2) * slab_y(p.head_w - 2 * p.head_wall, p.head_h - 2 * p.head_wall,
                                                       p.head_r - p.head_wall, p.head_d, p.head_r_bot - p.head_wall)
    s = outer - inner
    front = -p.head_d / 2
    # camera window: the ring light shows through, the body's rim stops on the lip
    s -= Pos(0, front - 1, h0 + CAM_Z) * cyl_y(p.cam_window_d / 2, 5)
    # display window + locating frame for the module
    dz = h0 + DISP_Z
    s -= Pos(0, front - 1, dz) * (Rot(-90, 0, 0) * extrude(RectangleRounded(*p.display_win, 2), 5))
    dw, dh = p.display[0] + 0.6, p.display[1] + 0.6
    frame = Pos(0, HFRONT, dz) * (slab_y(dw + 3.2, dh + 3.2, 2, 5) - slab_y(dw, dh, 1, 5))
    frame -= Pos(0, HFRONT - 1, dz + dh / 2) * Box(dw + 10, 10, 10, align=(Align.CENTER, Align.MIN, Align.MIN))  # top edge open: cable plugs
    s += frame
    # left ear: knob shaft hole; right ear: microphone holes
    s -= Pos(-p.head_w / 2 - 1, 0, h0 + p.ear_z) * cyl_x(6, 5)
    for dy, dz2 in [(0, 0)] + [(6 * math.cos(a), 6 * math.sin(a)) for a in [i * math.pi / 3 for i in range(6)]]:
        s -= Pos(p.head_w / 2 - 4, dy, h0 + p.ear_z + dz2) * cyl_x(1.0, 8)
    # floor: cable slot + two screw holes matching the turntable disc
    w, y0, y1 = CABLE_SLOT
    s -= Pos(0, (y0 + y1) / 2, h0 - 1) * Box(w, y1 - y0, p.head_wall + 2, align=MIN)
    for ang in (30, 150):
        a = math.radians(ang)
        s -= Pos(24 * math.cos(a), 24 * math.sin(a), h0 - 1) * Cylinder(1.6, p.head_wall + 2, align=MIN)
    # antenna socket in the top
    s -= Pos(34, 8, h0 + p.head_h - p.head_wall - 1) * Cylinder(1.7, p.head_wall + 2, align=MIN)
    return s


DISP_Z = p.head_wall + p.clip[2] + p.cam_d + 2 + p.display[1] / 2 + 2   # display centre above head floor


def head_back():
    """Back lid with a lip; two ribs hold the camera against the front lip. Prints plate-down."""
    h0 = HEAD_Z
    yb = p.head_d / 2
    plate = Pos(0, yb, h0 + p.head_h / 2) * slab_y(p.head_w, p.head_h, p.head_r, 2.0, p.head_r_bot)
    iw, ih, ir = p.head_w - 2 * p.head_wall - 0.4, p.head_h - 2 * p.head_wall - 0.4, p.head_r - p.head_wall - 0.2
    rb = p.head_r_bot - p.head_wall - 0.2
    lip = Pos(0, yb - 4, h0 + p.head_h / 2) * (slab_y(iw, ih, ir, 4, rb) - slab_y(iw - 2.4, ih - 2.4, ir - 1.2, 4,
                                                                                 rb - 1.2))
    lid = plate + lip
    cam_back = HFRONT + p.cam_depth
    for sx in (-1, 1):
        rib = Pos(sx * 24, cam_back + 0.3, h0 + CAM_Z - 5) * Box(3, yb - cam_back - 0.3, 10, align=(
            Align.CENTER, Align.MIN, Align.MIN))
        lid += rib
    # radio grille
    for i in range(6):
        z = h0 + p.head_h - 26 - i * 6
        lid -= Pos(0, yb - 1, z) * Box(64, 4, 3, align=(Align.CENTER, Align.MIN, Align.CENTER))
    # cable notch at the bottom so the lid closes over the cable bundle
    lid -= Pos(0, yb - 5, h0 - 1) * Box(30, 10, 10, align=(Align.CENTER, Align.MIN, Align.MIN))
    return lid


def face_bezel():
    """Optional dark face plate glued on the front: two-tone look without a multi-colour printer."""
    w = p.head_w - 16
    z0, z1 = CAM_Z - p.cam_window_d / 2 - 6, p.head_h - 6
    zc, h = HEAD_Z + (z0 + z1) / 2, z1 - z0
    b = Pos(0, -p.head_d / 2 - 1.2, zc) * slab_y(w, h, p.head_r - 8, 1.2, 6)
    b -= Pos(0, -p.head_d / 2 - 3, HEAD_Z + CAM_Z) * cyl_y(p.cam_window_d / 2 + 0.5, 5)
    b -= Pos(0, -p.head_d / 2 - 3, HEAD_Z + DISP_Z) * (
        Rot(-90, 0, 0) * extrude(RectangleRounded(p.display_win[0] + 1, p.display_win[1] + 1, 2.5), 5))
    return b


def cheek(side: int):
    """Amber blush dot glued on the face bezel beside the camera ring."""
    return Pos(side * 41, -p.head_d / 2 - 2.4, HEAD_Z + CAM_Z - 16) * (Rot(90, 0, 0) * Cylinder(5.5, 1.2, align=MIN))


def ear(side: int):
    """Ear ring glued on the side of the head. Left (-1): knob passes through. Right (+1): mic grille."""
    x = side * p.head_w / 2
    e = Pos(x, 0, HEAD_Z + p.ear_z) * (Rot(0, 90, 0) * Cylinder(17, 4, align=(Align.CENTER, Align.CENTER,
                                                                                 Align.MIN if side > 0 else Align.MAX)))
    if side < 0:
        e -= Pos(x - 10, 0, HEAD_Z + p.ear_z) * cyl_x(7, 20)
    else:
        for dy, dz in [(0, 0)] + [(6 * math.cos(a), 6 * math.sin(a)) for a in [i * math.pi / 3 for i in range(6)]] + [
                (11 * math.cos(a), 11 * math.sin(a)) for a in [i * math.pi / 4 for i in range(8)]]:
            e -= Pos(x - 1, dy, HEAD_Z + p.ear_z + dz) * cyl_x(1.0, 7)
    return e


def knob_cap():
    """Big tuning-dial cap that slides over the Knob module's own small black knob (press fit + a drop of glue)."""
    x0 = -p.head_w / 2 - 4 - 3.5                       # open end 3.5 mm off the ear ring
    length = 16.0
    cap = Cylinder(11, length, align=MIN)
    for i in range(24):
        a = 2 * math.pi * i / 24
        cap -= Pos(11.3 * math.cos(a), 11.3 * math.sin(a), 2) * Cylinder(1.0, length, align=MIN)
    cap -= Pos(0, 0, -1) * Cylinder(p.knob_d / 2 + 0.15, length - 2 + 1, align=MIN)
    return Pos(x0, 0, HEAD_Z + p.ear_z) * (Rot(0, -90, 0) * cap)


def antenna_ball():
    b = Sphere(7) - Pos(0, 0, -8) * Cylinder(1.6, 8, align=MIN) - Pos(0, 0, -9) * Box(20, 20, 3, align=MIN)
    return Pos(34, 8, HEAD_Z + p.head_h + 45) * b


# ======================================================================== PURR ===
PURR_Y, PURR_Z = -52.0, p.floor + 1.6 + p.motor[0] / 2 + 0.3
PURR_X0 = -26.0                                     # shaft end of the purr motor


def purr_sleeve():
    s = motor_sleeve(16.0)
    return Pos(PURR_X0, PURR_Y, PURR_Z) * (Rot(0, -90, 0) * s)


def purr_weight():
    w = (Cylinder(8, 6, align=MIN) & Pos(-8, 0, 0) * Box(16, 16, 6, align=(Align.MIN, Align.MIN, Align.MIN)))
    w += Cylinder(4.2, 6, align=MIN)
    w -= Pos(0, 0, -1) * d_hole(8)
    return Pos(PURR_X0 - p.shaft_len + 1, PURR_Y, PURR_Z) * (Rot(0, -90, 0) * (Pos(0, 0, -6) * w))


# =================================================================== REFERENCES ===
def ref_parts():
    refs = []

    def add(shape, name, color=GREY):
        refs.append(mk(shape, f"REF_{name}", color))

    mx, my, ml = p.motor
    # pan motor: vertical, shaft up, end face under the pan base
    add(Pos(*PINION_XY, TOP - ml) * Box(mx, my, ml, align=MIN), "motor_pan", DARK)
    add(Pos(*PINION_XY, TOP) * Cylinder(p.shaft_d / 2, p.shaft_len, align=MIN), "shaft_pan")
    # purr motor along X on the floor
    add(Pos(PURR_X0, PURR_Y, PURR_Z) * Box(ml, my, mx, align=(Align.MIN, Align.CENTER, Align.CENTER)), "motor_purr",
        DARK)
    # electronics in the body
    bw, bh, bt = p.board
    add(Pos(BOARD_X, 0, p.floor) * Box(bt, bw, bh, align=(Align.MIN, Align.CENTER, Align.MIN)), "atech_board", INK)
    add(Pos(BOARD_X + bt, 51, p.floor + bh - 22) * Box(16, 22, 22, align=(Align.MIN, Align.CENTER, Align.MIN)),
        "atech_usbc", INK)
    ux, uy, uh = p.unoq
    add(Pos(UNOQ_X0, UNOQ_Y0, p.floor + 5) * Box(ux, uy, uh, align=(Align.MIN, Align.MIN, Align.MIN)), "unoq", PCB)
    sw, sd, st = p.speaker
    add(Pos(IN_W / 2 - st, -10, p.floor) * Box(st, sw, sd, align=(Align.MIN, Align.MIN, Align.MIN)), "speaker", DARK)
    # Modulino Buzzer (41 x 25.36, datasheet) on the right wall above the speaker, Qwiic to the UNO Q
    add(Pos(IN_W / 2 - 8, -5, 55) * Box(8, 41, 25.36, align=(Align.MIN, Align.MIN, Align.MIN)), "modulino_buzzer",
        PCB)
    for sx in (-1, 1):
        add(Pos(sx * (p.cube / 2 + 1), -p.body_d / 2 + p.wall + 0.8, p.window_z) * Box(
            p.cube, p.cube_h, p.cube, align=(Align.CENTER, Align.MIN, Align.CENTER)), f"led_grid_{'l' if sx < 0 else 'r'}",
            GLOW)
    add(Pos(*BUTTON_XY, TOP - p.cube_h) * Box(p.cube, p.cube, p.cube_h, align=MIN), "button", AMBER)
    # KY-053 (ADS1115) for the KY-039, taped on the floor in front of the UNO Q (nominal 28 x 17 x 5)
    add(Pos(6, -26, p.floor) * Box(28, 17, 5, align=MIN), "ky053_adc", PCB)
    kx, ky, kh = p.ky039
    add(Pos(0, FINGER_Y, LEDGE_Z - kh) * Box(kx, ky, kh, align=MIN), "ky039_pulse", PCB)
    add(Pos(*LIGHT_XY, LEDGE_Z - 6) * Box(20, 15, 6, align=MIN), "ky054_light", PCB)
    hx, hy, hh = p.ky035
    add(Pos(0, -18, TOP - hh) * Box(hx, hy, hh, align=MIN), "ky035_hall", PCB)
    add(Pos(0, -18, GEAR_Z) * Cylinder(p.magnet_d / 2, p.magnet_t, align=MIN), "magnet", GREY)
    # head
    h0 = HEAD_Z
    cx, cy, ch = p.clip
    add(Pos(0, HFRONT, h0 + p.head_wall) * Box(cx, cy, ch, align=(Align.CENTER, Align.MIN, Align.MIN)),
        "camera_clip", DARK)
    add(Pos(0, 0, h0 + CAM_Z) * cyl_y(p.cam_d / 2, p.cam_depth, HFRONT), "camera", DARK)
    add(Pos(0, HFRONT - 0.5, h0 + CAM_Z) * cyl_y(30, 0.5), "camera_ring_light", WHITE)
    dw, dh, dt = p.display
    add(Pos(0, HFRONT, h0 + DISP_Z) * Box(dw, dt, dh, align=(Align.CENTER, Align.MIN, Align.CENTER)),
        "display", DARK)
    add(Pos(0, HFRONT - 0.3, h0 + DISP_Z) * Box(26, 0.3, 12, align=(Align.CENTER, Align.MIN, Align.CENTER)),
        "display_screen", GLOW)
    add(Pos(0, HFRONT + 1, h0 + DISP_Z + dh / 2) * Box(34, dt - 2, p.display_plug, align=(
        Align.CENTER, Align.MIN, Align.MIN)), "display_plugs", GREY)
    kw, kd, kt = p.knob
    add(Pos(-HW, 0, h0 + p.ear_z) * Box(kt, kd, kw, align=(Align.MIN, Align.CENTER, Align.CENTER)), "knob", DARK)
    add(Pos(-HW - p.knob_out, 0, h0 + p.ear_z) * cyl_x(p.knob_d / 2, p.knob_out), "knob_shaft", GREY)
    mw, ml2, mt = p.mic
    add(Pos(HW - mt, 0, h0 + p.ear_z) * Box(mt, mw, ml2, align=(Align.MIN, Align.CENTER, Align.CENTER)), "mic", DARK)
    # KY-031 knock sensor (the drum) glued under the head top, wired to the UNO Q through the neck
    add(Pos(0, 4, h0 + p.head_h - p.head_wall - 10) * Box(25, 15, 10, align=(Align.CENTER, Align.MIN, Align.MIN)),
        "ky031_knock", PCB)
    add(Pos(34, 8, h0 + p.head_h - p.head_wall) * Cylinder(1.5, 52, align=MIN), "antenna_rod", GREY)
    return refs


# ====================================================================== BUILD ===
# name: (builder, colour, print set, copies, print rotation (x, y, z) degrees)
PARTS = {
    "head_shell":      (head_shell,      CREAM, "mvp",  1, (90, 0, 0)),
    "head_back":       (head_back,       CREAM, "mvp",  1, (-90, 0, 0)),
    "pan_base":        (pan_base,        TEAL,  "mvp",  1, (0, 0, 0)),
    "pan_motor_mount": (pan_motor_mount, TEAL,  "mvp",  1, (180, 0, 0)),
    "turntable":       (turntable,       TEAL,  "mvp",  1, (0, 0, 0)),
    "pinion":          (pinion,          AMBER, "mvp",  1, (0, 0, 0)),
    "purr_sleeve":     (purr_sleeve,     GREY,  "mvp",  1, (0, 90, 0)),
    "purr_weight":     (purr_weight,     AMBER, "mvp",  1, (0, 90, 0)),
    "ear_left":        (lambda: ear(-1), AMBER, "mvp",  1, (0, -90, 0)),
    "ear_right":       (lambda: ear(1),  AMBER, "mvp",  1, (0, 90, 0)),
    "knob_cap":        (knob_cap,        AMBER, "mvp",  1, (0, 90, 0)),
    "finger_cradle":   (finger_cradle,   INK,   "mvp",  1, (0, 0, 0)),
    "antenna_ball":    (antenna_ball,    AMBER, "mvp",  1, (0, 0, 0)),
    "face_bezel":      (face_bezel,      INK,   "full", 1, (90, 0, 0)),
    "cheek_left":      (lambda: cheek(-1), AMBER, "full", 1, (90, 0, 0)),
    "cheek_right":     (lambda: cheek(1),  AMBER, "full", 1, (90, 0, 0)),
    "window_pane":     (window_pane,     WHITE, "full", 1, (90, 0, 0)),
    "top_plate":       (top_plate,       CREAM, "body", 1, (0, 0, 0)),
    "body_tub":        (body_tub,        CREAM, "body", 1, (0, 0, 0)),
}

# pairs that touch or nest by design (glued faces, shafts in holes): not reported as clashes
EXPECTED = {
    frozenset(x) for x in [
        ("REF_shaft_pan", "pinion"),
        ("REF_camera_ring_light", "REF_camera"), ("REF_display_screen", "REF_display"),
        ("REF_antenna_rod", "antenna_ball"), ("REF_antenna_rod", "head_shell"),
        ("REF_shaft_pan", "pan_base"), ("REF_knob_shaft", "head_shell"), ("REF_knob_shaft", "ear_left"),
        ("REF_knob_shaft", "knob_cap"),
    ]
}


def body_features() -> dict:
    """Every cut-out in the body walls and lid, in assembly coordinates, for the cardboard template."""
    return {
        "outer": [p.body_w, p.body_d, p.body_h],
        "front_grille": {"x": 0, "z": p.window_z, "w": p.window[0], "h": p.window[1]},
        "speaker_holes": [[-4 + iy * 6.0, 12 + iz * 6.5] for iy in range(7) for iz in range(5)],  # right wall (y, z)
        "rear_cable_slot": {"x": -10, "z": 15, "w": 72, "h": 20},
        "rear_usbc": {"x": -32, "z": 59, "w": 18, "h": 14},
        "lid_pan_hole": {"x": 0, "y": 11, "w": 29, "d": 76},
        "lid_button": {"x": BUTTON_XY[0], "y": BUTTON_XY[1], "w": 23.4, "d": 23.4},
        "lid_finger_hole": {"x": 0, "y": FINGER_Y, "d": 9},
        "lid_lift_hole": {"x": 32, "y": 52, "d": 16},
        "lid_light_hole": {"x": LIGHT_XY[0], "y": LIGHT_XY[1], "d": 5},
        "pan_base_flange": {"x": 0, "y": 12, "w": 46, "d": 86},
        "purr_sleeve": {"x0": PURR_X0 - 2, "x1": PURR_X0 + 16, "y": PURR_Y},
        "atech_board_x": BOARD_X,
        "unoq_corner": [UNOQ_X0, UNOQ_Y0],
        "led_grids_z": p.window_z,
    }


def rotated(shape, rot):
    rx, ry, rz = rot
    s = shape
    if rx:
        s = Rot(rx, 0, 0) * s
    if ry:
        s = Rot(0, ry, 0) * s
    if rz:
        s = Rot(0, 0, rz) * s
    bb = s.bounding_box()
    return Pos(-(bb.min.X + bb.max.X) / 2, -(bb.min.Y + bb.max.Y) / 2, -bb.min.Z) * s


def fit_check(bodies):
    clashes = []
    for a, b in itertools.combinations(bodies, 2):
        if frozenset((a.label, b.label)) in EXPECTED:
            continue
        ba, bb = a.bounding_box(), b.bounding_box()
        if (ba.min.X >= bb.max.X or bb.min.X >= ba.max.X or ba.min.Y >= bb.max.Y or bb.min.Y >= ba.max.Y
                or ba.min.Z >= bb.max.Z or bb.min.Z >= ba.max.Z):
            continue
        try:
            v = (a & b).volume
        except Exception:  # noqa: BLE001
            v = float("nan")
        if not v < 1.0:                       # mm^3; also catches nan
            clashes.append({"a": a.label, "b": b.label, "mm3": round(v, 1)})
    return clashes


def main():
    quick = "--no-fit" in sys.argv
    for d in ("stl", "render"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    printed, report = [], {"params": asdict(p), "parts": {}, "heights": {
        "body_top": TOP, "head_floor": HEAD_Z, "head_top": HEAD_Z + p.head_h,
        "camera_centre": HEAD_Z + CAM_Z, "display_centre": HEAD_Z + DISP_Z}, "body_features": body_features()}
    for name, (fn, color, pset, copies, rot) in PARTS.items():
        shape = mk(fn(), name, color)
        printed.append(shape)
        bb = shape.bounding_box()
        export_stl(rotated(shape, rot), str(OUT / "stl" / f"{name}.stl"), tolerance=0.02, angular_tolerance=0.1)
        report["parts"][name] = {"set": pset, "copies": copies, "volume_cm3": round(shape.volume / 1000, 1),
                                 "size_mm": [round(bb.size.X, 1), round(bb.size.Y, 1), round(bb.size.Z, 1)]}
        print(f"{name:18s} {pset:5s} {shape.volume / 1000:6.1f} cm3  {bb.size.X:5.1f} x {bb.size.Y:5.1f} x {bb.size.Z:5.1f}")
    refs = ref_parts()
    scene = []
    for s in printed + refs:
        export_stl(s, str(OUT / "render" / f"{s.label}.stl"), tolerance=0.05, angular_tolerance=0.2)
        c = s.color.to_tuple() if hasattr(s.color, "to_tuple") else tuple(s.color)
        group = "ref" if s.label.startswith("REF_") else report["parts"][s.label]["set"]
        scene.append({"name": s.label, "group": group, "rgba": [round(v, 3) for v in c]})
    (OUT / "render" / "scene.json").write_text(json.dumps(scene, indent=1))
    groups = {
        "head": [s for s in printed if s.label in ("head_shell", "head_back", "face_bezel", "cheek_left", "cheek_right", "ear_left", "ear_right",
                                                   "knob_cap", "antenna_ball")],
        "neck": [s for s in printed if s.label in ("pan_base", "pan_motor_mount", "turntable", "pinion")],
        "body": [s for s in printed if s.label in ("body_tub", "top_plate", "window_pane", "finger_cradle", "purr_sleeve",
                                                   "purr_weight")],
        "reference_bought_in_parts": refs,
    }
    export_step(Compound(label="kaiku", children=[Compound(label=k, children=v) for k, v in groups.items()]),
                str(OUT / "kaiku_assembly.step"))
    if not quick:
        clashes = fit_check(printed + refs)
        report["clashes"] = clashes
        print("fit check:", "no clashes" if not clashes else json.dumps(clashes, indent=1))
    (OUT / "report.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
