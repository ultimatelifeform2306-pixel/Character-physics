"""Render Frieza [Drip] views and lay them out as a PS2 character-select screen.

    python3 blender/render_sheet.py     (after build_frieza_drip.py)

Renders front / side / back / three-quarter views with Cycles on the CPU at a low
resolution, blows them up with nearest-neighbour scaling, draws a wireframe of
the real mesh, and writes renders/*.png plus renders/select_screen.png.
"""
import math
import os

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "renders")
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.open_mainfile(filepath=os.path.join(HERE, "frieza_drip.blend"))
scene = bpy.context.scene
scene.frame_set(1)
body = bpy.data.objects["Frieza_Drip"]

r = scene.render
r.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 48
scene.cycles.use_denoising = True
r.film_transparent = True
r.image_settings.file_format = "PNG"
r.image_settings.color_mode = "RGBA"
scene.view_settings.view_transform = "Standard"

world = bpy.data.worlds.new("World")
scene.world = world
world.color = (0.05, 0.03, 0.09)
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.09, 0.06, 0.16, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0


def light(name, kind, loc, energy, color=(1, 1, 1), size=1.0):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    if kind == "AREA":
        ld.size = size
    o = bpy.data.objects.new(name, ld)
    scene.collection.objects.link(o)
    o.location = loc
    look(o, Vector((0, 0, 0.9)))
    return o


def look(o, target):
    o.rotation_euler = (target - o.location).to_track_quat("-Z", "Y").to_euler()


cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 70
cam = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam

TARGET = Vector((0, 0, 0.88))
VIEWS = {  # camera position relative to the character, render size
    "front": ((0, -1, 0.06), (240, 360)),
    "side": ((1, 0, 0.06), (240, 360)),
    "back": ((0, 1, 0.06), (240, 360)),
    "three_quarter": ((-0.7, -0.75, 0.12), (240, 360)),
}
DIST = 5.2


def place_camera(direction):
    d = Vector(direction).normalized()
    cam.location = TARGET + d * DIST
    look(cam, TARGET)
    for o in lights:  # lights follow the camera so every view gets the same studio setup
        o.location = rig_pos(o["rel"], d)
        look(o, TARGET)


def rig_pos(rel, d):
    # rel is (right, up, toward-camera) in the camera's frame
    fwd = -d
    right = fwd.cross(Vector((0, 0, 1))).normalized()
    return TARGET + right * rel[0] + Vector((0, 0, 1)) * rel[1] + d * rel[2]


lights = [
    light("Key", "AREA", (0, 0, 0), 260, (1.0, 0.95, 0.9), size=1.5),
    light("Fill", "AREA", (0, 0, 0), 90, (0.75, 0.7, 1.0), size=2.0),
    light("Rim", "AREA", (0, 0, 0), 220, (0.8, 0.55, 1.0), size=1.0),
]
lights[0]["rel"] = (-1.6, 1.8, 2.6)
lights[1]["rel"] = (2.2, 0.3, 2.0)
lights[2]["rel"] = (0.6, 1.6, -2.4)


def render_view(name, direction, size, scale=2):
    place_camera(direction)
    r.resolution_x, r.resolution_y = size
    r.resolution_percentage = 100
    raw = os.path.join(OUT, f"_raw_{name}.png")
    r.filepath = raw
    bpy.ops.render.render(write_still=True)
    img = Image.open(raw).convert("RGBA")
    # PS2-ish: 5-bit-per-channel colour, then nearest-neighbour upscale
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            c = px[x, y]
            px[x, y] = (c[0] & 0xF8, c[1] & 0xF8, c[2] & 0xF8, 255 if c[3] > 110 else 0)
    img.resize((img.width * scale, img.height * scale), Image.NEAREST).save(os.path.join(OUT, f"{name}.png"))
    os.remove(raw)
    return img  # native low-res frame; the sheet scales it up by whole pixels


def wireframe(direction, size, scale=3):
    place_camera(direction)
    r.resolution_x, r.resolution_y = size
    dg = bpy.context.evaluated_depsgraph_get()
    ev = body.evaluated_get(dg)
    me = ev.to_mesh()
    w, h = size[0] * scale, size[1] * scale
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pts = []
    for v in me.vertices:
        c = world_to_camera_view(scene, cam, ev.matrix_world @ v.co)
        pts.append((c.x * w, (1 - c.y) * h))
    for e in me.edges:
        a, b = e.vertices
        d.line((pts[a], pts[b]), fill=(235, 235, 245, 200), width=1)
    ev.to_mesh_clear()
    return img


shots = {name: render_view(name, d, s) for name, (d, s) in VIEWS.items()}
wire = wireframe(VIEWS["front"][0], VIEWS["front"][1])
wire.save(os.path.join(OUT, "wireframe.png"))
wire = wire.resize((wire.width // 3, wire.height // 3), Image.LANCZOS)

# ------------------------------------------------------------- select screen

W, H = 768, 1376
BG, PANEL, EDGE = (24, 18, 38), (44, 32, 72), (150, 120, 205)
sheet = Image.new("RGB", (W, H), BG)
dr = ImageDraw.Draw(sheet)
F = "/usr/share/fonts/truetype/dejavu/"
title_font = ImageFont.truetype(F + "DejaVuSansMono-BoldOblique.ttf", 54)
tag_font = ImageFont.truetype(F + "DejaVuSansMono-BoldOblique.ttf", 46)
stat_font = ImageFont.truetype(F + "DejaVuSans-Bold.ttf", 30)
small_stat = ImageFont.truetype(F + "DejaVuSans-Bold.ttf", 24)
btn_font = ImageFont.truetype(F + "DejaVuSans-Bold.ttf", 25)


def panel(box, grad=True):
    x0, y0, x1, y1 = box
    if grad:
        for y in range(y0, y1):
            t = (y - y0) / max(1, y1 - y0)
            c = tuple(int(PANEL[i] * (0.65 + 0.6 * t)) for i in range(3))
            dr.line((x0, y, x1, y), fill=c)
    else:
        dr.rectangle(box, fill=(18, 14, 28))
    dr.rectangle(box, outline=EDGE, width=3)


def paste_fit(img, box, pad=8):
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0 - 2 * pad, y1 - y0 - 2 * pad
    bb = img.getbbox() or (0, 0, img.width, img.height)
    crop = img.crop(bb)
    k = min(bw / crop.width, bh / crop.height)
    k = int(k) if k >= 2 else k  # whole-number scale keeps the pixels square once it is 2x or more
    crop = crop.resize((max(1, int(crop.width * k)), max(1, int(crop.height * k))), Image.NEAREST)
    sheet.paste(crop, (x0 + (x1 - x0 - crop.width) // 2, y0 + (y1 - y0 - crop.height) // 2), crop)


def chrome_text(xy, text, font):
    x, y = xy
    dr.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0))
    dr.text((x, y), text, font=font, fill=(222, 214, 230), stroke_width=2, stroke_fill=(40, 30, 60))


def bars(box, values, font, label_w):
    x0, y0, x1, y1 = box
    row = (y1 - y0 - 16) / len(values)
    for i, (label, v) in enumerate(values):
        y = int(y0 + 8 + i * row)
        dr.text((x0 + 10, y), label, font=font, fill=(235, 235, 240))
        bx0, bx1 = x0 + label_w, x1 - 12
        by0, by1 = y + 6, int(y + row - 6)
        dr.rectangle((bx0, by0, bx1, by1), fill=(12, 10, 18), outline=(70, 60, 90))
        fill_to = int(bx0 + (bx1 - bx0) * v)
        for x in range(bx0 + 2, fill_to):
            t = (x - bx0) / (bx1 - bx0)
            c = (int(235 - 150 * max(0, t - 0.35)), int(90 + 160 * min(1, t * 1.6)), 30)
            dr.line((x, by0 + 2, x, by1 - 2), fill=c)


chrome_text((24, 22), "FRIEZA [DRIP]", title_font)
dr.polygon([(510, 40), (752, 40), (740, 120), (494, 120)], fill=PANEL, outline=EDGE)
chrome_text((520, 48), "FRIEZA", tag_font)
dr.line((24, 112, 480, 112), fill=EDGE, width=3)

main_box = (16, 140, 486, 1092)
panel(main_box)
paste_fit(shots["front"], main_box, pad=24)

stat_box = (500, 140, 752, 300)
panel(stat_box, grad=False)
bars(stat_box, [("HP", .7), ("KI", .55), ("ATK", .62), ("DEF", .45), ("SPD", .72)], small_stat, 72)

for box, img in (((500, 312, 752, 612), shots["side"]), ((500, 626, 752, 950), shots["back"])):
    panel(box)
    paste_fit(img, box, pad=14)
wbox = (500, 962, 752, 1290)
panel(wbox, grad=False)
paste_fit(wire, wbox, pad=14)

lower = (16, 1104, 486, 1292)
panel(lower, grad=False)
bars(lower, [("HP", .47), ("KI", .33), ("ATK", .62), ("DEF", .53), ("SPD", .48)], stat_font, 92)


def button(x, y, sym, col, label):
    dr.ellipse((x, y, x + 40, y + 40), fill=(40, 40, 52), outline=(150, 150, 170), width=2)
    cx, cy = x + 20, y + 20
    if sym == "x":
        dr.line((cx - 9, cy - 9, cx + 9, cy + 9), fill=col, width=4)
        dr.line((cx - 9, cy + 9, cx + 9, cy - 9), fill=col, width=4)
    elif sym == "sq":
        dr.rectangle((cx - 9, cy - 9, cx + 9, cy + 9), outline=col, width=3)
    else:
        dr.polygon([(cx, cy - 11), (cx + 11, cy + 8), (cx - 11, cy + 8)], outline=col, width=3)
    dr.text((x + 50, y + 2), label, font=btn_font, fill=(230, 230, 236))


button(36, 1312, "x", (110, 150, 240), "BACK")
button(220, 1312, "sq", (230, 120, 200), "ROTATE")
button(420, 1312, "tri", (90, 210, 170), "SELECT COSTUME")

sheet.save(os.path.join(OUT, "select_screen.png"))
print("wrote", OUT)
