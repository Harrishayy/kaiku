"""Render the step-by-step assembly figures for hardware/assembly_guide/kaiku_assembly.tex.

Run:  /Applications/Blender.app/Contents/MacOS/Blender -b -P hardware/cad/assembly_guide.py
      (after kaiku_cad.py, which writes hardware/cad/out/render/*.stl + scene.json)
Out:  hardware/assembly_guide/figures/asm_*.jpg  (then: latexmk -pdf kaiku_assembly.tex in that folder)

In every step the parts being added are blue, parts already fitted are light grey, everything else is hidden.
The body is the MVP cardboard box (brown, see-through where we need to look inside).
"""

import json
from pathlib import Path

import bpy
from mathutils import Vector

HERE = Path(__file__).parent
SRC = HERE / "out" / "render"
FIG = HERE.parent / "assembly_guide" / "figures"
FIG.mkdir(parents=True, exist_ok=True)

# heights from kaiku_cad.py (report.json)
REPORT = json.loads((HERE / "out" / "report.json").read_text())["heights"]
TOP, HEAD_Z = REPORT["body_top"], REPORT["head_floor"]
CAM_Z, DISP_Z = REPORT["camera_centre"], REPORT["display_centre"]
NECK = (0, 10, 108)

NOT_IN_BUILD = {"REF_motor_purr", "REF_ky054_light", "REF_ky035_hall", "REF_magnet", "purr_sleeve", "purr_weight",
                "window_pane"}
BLUE, GREY, BOX = (0.16, 0.42, 0.86), (0.80, 0.80, 0.78), (0.62, 0.45, 0.28)

NECK_PARTS = ["pan_base", "turntable", "pan_motor_mount", "pinion", "REF_motor_pan", "REF_shaft_pan"]
DISPLAY = ["REF_display", "REF_display_screen", "REF_display_plugs"]
CAMERA = ["REF_camera", "REF_camera_clip", "REF_camera_ring_light"]
KNOB = ["REF_knob", "REF_knob_shaft", "ear_left", "knob_cap"]
MIC = ["REF_mic", "ear_right"]
KNOCK = ["REF_ky031_knock", "REF_antenna_rod", "antenna_ball"]
FACE = ["face_bezel", "cheek_left", "cheek_right"]
HEAD_ALL = ["head_shell", "head_back"] + DISPLAY + CAMERA + KNOB + MIC + KNOCK + FACE
BODY_ELEC = ["REF_atech_board", "REF_atech_usbc", "REF_unoq", "REF_speaker", "REF_modulino_buzzer", "REF_ky053_adc",
             "REF_led_grid_l", "REF_led_grid_r"]
LID = ["REF_ky039_pulse", "finger_cradle", "REF_button"]

# name, new parts, fitted parts, camera eye, camera target, lens, body mode ("none" | "ghost" | "solid" | "lid")
STEPS = [
    ("asm_1_testfit", ["turntable"], ["pan_base"], (160, -190, 170), (0, 12, 108), 55, "none"),
    ("asm_2_pinion", ["pinion"], ["REF_motor_pan", "REF_shaft_pan"], (110, -40, 125), (0, 32, 85), 55, "none"),
    ("asm_3_sleeve", ["pan_motor_mount"], ["REF_motor_pan", "REF_shaft_pan", "pinion"], (130, -60, 110),
     (0, 32, 80), 50, "none"),
    ("asm_4_neck", ["pan_motor_mount", "REF_motor_pan", "REF_shaft_pan", "pinion"], ["pan_base", "turntable"],
     (190, -150, 40), (0, 18, 92), 50, "none"),
    ("asm_5_neck_on_lid", NECK_PARTS, [], (260, -260, 260), (0, 5, 100), 50, "lid"),
    ("asm_6_display", DISPLAY, ["head_shell"], (230, 330, 330), (0, -10, DISP_Z - 25), 45, "none"),
    ("asm_7_camera", CAMERA, ["head_shell"] + DISPLAY, (210, 280, 260), (0, -10, CAM_Z), 50, "none"),
    ("asm_8_knob_ear", KNOB, ["head_shell"] + DISPLAY + CAMERA, (-300, 180, 240), (-40, 0, HEAD_Z + 64), 50, "none"),
    ("asm_9_mic_ear", MIC, ["head_shell", "ear_left", "knob_cap"] + DISPLAY + CAMERA, (300, 180, 240),
     (40, 0, HEAD_Z + 64), 50, "none"),
    ("asm_10_knock_antenna", KNOCK, ["head_shell"] + DISPLAY + CAMERA + ["REF_knob", "REF_mic"], (220, 360, 360),
     (0, 0, 215), 42, "none"),
    ("asm_11_back_lid", ["head_back"], [p for p in HEAD_ALL if p not in ("head_back",) and p not in FACE],
     (230, 330, 260), (0, 0, 195), 50, "none"),
    ("asm_12_face", FACE, [p for p in HEAD_ALL if p not in FACE], (-150, -330, 220), (0, -30, 200), 50, "none"),
    ("asm_13_head_on_neck", HEAD_ALL, NECK_PARTS, (330, -420, 280), (0, 0, 150), 45, "lid"),
    ("asm_14_body", BODY_ELEC, [], (-190, -230, 210), (0, 5, 40), 40, "ghost"),
    ("asm_15_lid_parts", LID, NECK_PARTS, (180, -330, 300), (0, -20, 100), 45, "lid"),
]


def lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def material(name, rgb, alpha=1.0, emit=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (lin(rgb[0]), lin(rgb[1]), lin(rgb[2]), 1)
    b.inputs["Roughness"].default_value = 0.55
    if alpha < 1:
        b.inputs["Alpha"].default_value = alpha
        m.blend_method = "BLEND"
        if hasattr(m, "shadow_method"):
            m.shadow_method = "NONE"
    if emit:
        key = "Emission Color" if "Emission Color" in b.inputs else "Emission"
        b.inputs[key].default_value = (lin(rgb[0]), lin(rgb[1]), lin(rgb[2]), 1)
        b.inputs["Emission Strength"].default_value = emit
    return m


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
objs, natural = {}, {}
for item in json.loads((SRC / "scene.json").read_text()):
    if item["name"] in NOT_IN_BUILD:
        continue
    path = str(SRC / f"{item['name']}.stl")
    if hasattr(bpy.ops.wm, "stl_import"):
        bpy.ops.wm.stl_import(filepath=path)
    else:
        bpy.ops.import_mesh.stl(filepath=path)
    ob = bpy.context.selected_objects[0]
    ob.name = item["name"]
    ob.data.materials.append(material("x", (1, 1, 1)))
    objs[item["name"]] = ob
    natural[item["name"]] = item["rgba"][:3]

M_NEW, M_FIT = material("new", BLUE), material("fitted", GREY)
M_BOX, M_GHOST = material("box", BOX), material("ghost", BOX, alpha=0.18)
M_NAT = {n: material(f"nat_{n}", c, emit=1.0 if n in ("REF_display_screen", "REF_camera_ring_light",
                                                          "REF_led_grid_l", "REF_led_grid_r") else 0.0)
         for n, c in natural.items()}

bpy.ops.mesh.primitive_plane_add(size=4000, location=(0, 0, 0))
desk = bpy.context.object
desk.data.materials.append(material("desk", (0.93, 0.92, 0.90)))
world = bpy.data.worlds.new("w")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (1, 1, 1, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
for loc, energy in (((-300, -400, 600), 2.0e6), ((400, -200, 300), 9e5), ((0, 500, 500), 8e5)):
    bpy.ops.object.light_add(type="POINT", location=loc)
    bpy.context.object.data.energy = energy
    bpy.context.object.data.shadow_soft_size = 150

cam_data = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
scene.render.engine = "CYCLES"
scene.cycles.samples = 32
scene.cycles.use_denoising = True
scene.render.resolution_x, scene.render.resolution_y = 1000, 800
scene.render.film_transparent = False
scene.render.image_settings.file_format = "JPEG"
scene.render.image_settings.quality = 88


def set_mat(ob, m):
    ob.data.materials[0] = m


def look(eye, target, lens):
    cam_data.lens = lens
    cam.location = Vector(eye)
    cam.rotation_euler = (Vector(target) - cam.location).to_track_quat("-Z", "Y").to_euler()


def body(mode):
    for n in ("body_tub", "top_plate"):
        if n in objs:
            objs[n].hide_render = mode == "none"
    if mode == "none":
        return
    set_mat(objs["body_tub"], M_GHOST if mode in ("ghost", "lid") else M_BOX)
    objs["top_plate"].hide_render = mode == "ghost"
    set_mat(objs["top_plate"], M_BOX)


def shot(name, new, fitted, eye, target, lens, body_mode):
    for n, ob in objs.items():
        ob.location = (0, 0, 0)
        if n in new:
            ob.hide_render = False
            set_mat(ob, M_NEW)
        elif n in fitted:
            ob.hide_render = False
            set_mat(ob, M_FIT)
        else:
            ob.hide_render = True
    body(body_mode)
    look(eye, target, lens)
    scene.render.filepath = str(FIG / f"{name}.jpg")
    bpy.ops.render.render(write_still=True)


def natural_all(body_mode):
    for n, ob in objs.items():
        ob.hide_render = False
        set_mat(ob, M_NAT[n])
    body(body_mode)


# exploded overview (natural colours, cardboard body)
natural_all("solid")
lift = {**{n: 150 for n in HEAD_ALL}, "turntable": 95, **{n: 60 for n in NECK_PARTS if n != "turntable"},
        **{n: 30 for n in ["top_plate"] + LID}}
for n, ob in objs.items():
    ob.location = (0, 70 if n == "head_back" else 0, lift.get(n, 0))
look((-430, -470, 330), (0, 0, 175), 55)
scene.render.filepath = str(FIG / "asm_0_exploded.jpg")
bpy.ops.render.render(write_still=True)

for st in STEPS:
    shot(*st)

# finished MVP: natural colours on the cardboard box
for ob in objs.values():
    ob.location = (0, 0, 0)
natural_all("solid")
look((-300, -520, 300), (0, 0, 135), 50)
scene.render.filepath = str(FIG / "asm_16_complete.jpg")
bpy.ops.render.render(write_still=True)
