"""Render the Kaiku robot from out/render/*.stl (written by kaiku_cad.py).

Run:  /Applications/Blender.app/Contents/MacOS/Blender -b -P hardware/cad/render.py
Out:  hardware/cad/out/img/{front,rear,side,internals,head_internals}.png
"""

import json
import math
from pathlib import Path

import bpy
from mathutils import Vector

HERE = Path(__file__).parent
SRC = HERE / "out" / "render"
IMG = HERE / "out" / "img"
IMG.mkdir(parents=True, exist_ok=True)


def lin(c):
    """CAD colours are sRGB; Blender shader inputs are linear."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

objs = {}
for item in json.loads((SRC / "scene.json").read_text()):
    path = str(SRC / f"{item['name']}.stl")
    if hasattr(bpy.ops.wm, "stl_import"):
        bpy.ops.wm.stl_import(filepath=path)
    else:
        bpy.ops.import_mesh.stl(filepath=path)
    ob = bpy.context.selected_objects[0]
    ob.name = item["name"]
    r, g, b, _ = item["rgba"]
    mat = bpy.data.materials.new(item["name"])
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (lin(r), lin(g), lin(b), 1)
    bsdf.inputs["Roughness"].default_value = 0.5
    if item["name"] in ("REF_display_screen", "REF_led_grid_l", "REF_led_grid_r", "REF_camera_ring_light"):
        key = "Emission Color" if "Emission Color" in bsdf.inputs else "Emission"
        bsdf.inputs[key].default_value = (lin(r), lin(g), lin(b), 1)
        bsdf.inputs["Emission Strength"].default_value = 1.2
    ob.data.materials.append(mat)
    objs[item["name"]] = (ob, item["group"])

# desk
bpy.ops.mesh.primitive_plane_add(size=4000, location=(0, 0, 0))
desk = bpy.context.object
dm = bpy.data.materials.new("desk")
dm.use_nodes = True
dm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.55, 0.42, 0.28, 1)
desk.data.materials.append(dm)

world = bpy.data.worlds.new("w")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.82, 0.85, 0.88, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.9

for loc, energy in (((-300, -400, 600), 2.5e6), ((400, -200, 300), 1.0e6), ((0, 500, 500), 8e5)):
    bpy.ops.object.light_add(type="POINT", location=loc)
    bpy.context.object.data.energy = energy
    bpy.context.object.data.shadow_soft_size = 120

cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 70
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
scene.render.engine = "CYCLES"
scene.cycles.samples = 48
scene.cycles.use_denoising = True
scene.render.resolution_x = 1100
scene.render.resolution_y = 1300
scene.unit_settings.scale_length = 0.001


def look(eye, target):
    cam.location = Vector(eye)
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def show(hide_names=(), hide_groups=()):
    for name, (ob, group) in objs.items():
        hidden = name in hide_names or group in hide_groups
        ob.hide_render = hidden


def shot(name, eye, target=(0, 0, 130), hide_names=(), hide_groups=()):
    show(hide_names, hide_groups)
    look(eye, target)
    scene.render.filepath = str(IMG / f"{name}.png")
    bpy.ops.render.render(write_still=True)


HEAD = ("head_shell", "head_back", "face_bezel", "cheek_left", "cheek_right", "ear_left", "ear_right", "knob_cap",
        "antenna_ball", "REF_camera", "REF_camera_clip", "REF_camera_ring_light", "REF_display", "REF_display_screen",
        "REF_knob", "REF_mic", "REF_imu", "REF_antenna_rod")
TURNING = ("turntable", "REF_magnet")
NECK = ("pan_base", "pan_motor_mount", "pinion", "REF_motor_pan", "REF_shaft_pan", "REF_ky035_hall")
LID = ("top_plate", "finger_cradle", "REF_button", "REF_ky039_pulse")


def exploded(on: bool):
    lift = {**{n: 150 for n in HEAD}, **{n: 95 for n in TURNING}, **{n: 60 for n in NECK}, **{n: 30 for n in LID}}
    for name, (ob, _) in objs.items():
        dz = lift.get(name, 0) if on else 0
        dy = 70 if (on and name == "head_back") else 0
        ob.location = (0, dy, dz)


r = 620
shot("front", (r * math.sin(math.radians(-30)), -r * math.cos(math.radians(30)), 300), hide_groups=("ref_hidden",))
shot("rear", (r * math.sin(math.radians(150)), -r * math.cos(math.radians(150)), 320))
shot("side", (r, 0, 160))
shot("internals", (-430, -420, 360), target=(0, 0, 110),
     hide_names=("body_tub", "top_plate", "head_shell", "head_back", "face_bezel", "window_pane", "ear_left",
                 "ear_right", "knob_cap", "finger_cradle"))
shot("head_internals", (300, 380, 330), target=(0, 0, 190),
     hide_names=("head_back", "body_tub", "top_plate"))
shot("neck", (170, -230, 190), target=(0, 10, 105), hide_names=("head_shell", "head_back", "face_bezel", "cheek_left",
                                                               "cheek_right", "ear_left", "ear_right", "knob_cap"))
exploded(True)
shot("exploded", (-700, -560, 420), target=(0, 0, 190))
exploded(False)

# MVP: printed head and neck on the cardboard body (a plain box of the same outer size)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 50))
box = bpy.context.object
box.scale = (104, 136, 100)
cm = bpy.data.materials.new("cardboard")
cm.use_nodes = True
cm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.45, 0.30, 0.17, 1)
cm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
box.data.materials.append(cm)
objs["cardboard_box"] = (box, "cardboard")
show(("body_tub", "top_plate", "window_pane", "face_bezel", "cheek_left", "cheek_right"))
look((r * math.sin(math.radians(-30)), -r * math.cos(math.radians(30)), 300), (0, 0, 130))
scene.render.filepath = str(IMG / "mvp_cardboard.png")
bpy.ops.render.render(write_still=True)
box.hide_render = True
