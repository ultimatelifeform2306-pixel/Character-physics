"""Build Frieza [Drip] as a PS2-style low-poly character in Blender.

    python3 blender/make_textures.py            # once, paints the textures
    blender -b -P blender/build_frieza_drip.py  # or: python3 blender/build_frieza_drip.py (bpy module)

Outputs blender/frieza_drip.blend and blender/frieza_drip.glb.

Style rules, PS2-era: everything is built from 6-16 sided tubes and spheres,
textures are 64-256 px and sampled with nearest filtering, and the skin is
rigid per body segment (each part follows one or two bones) with a chain of
bones in the tail. Blender convention: Z up, the character faces -Y, so his
left side is +X (".L" bones).
"""
import math
import os

import bpy  # first: as a pip module, bpy has to load before bmesh
import bmesh
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
TEX = os.path.join(HERE, "textures")
TAU = math.tau

# --------------------------------------------------------------------------- scene

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
col = bpy.data.collections.new("FriezaDrip")
scene.collection.children.link(col)


def link(obj):
    col.objects.link(obj)
    return obj


# ----------------------------------------------------------------------- materials

def material(name, color, tex=None, rough=0.85, spec=0.2, metal=0.0):
    m = bpy.data.materials.new(name)
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    bsdf.inputs["Specular IOR Level"].default_value = spec
    if tex:
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(os.path.join(TEX, tex))
        node.interpolation = "Closest"  # no filtering: the PS2 look
        node.location = (-320, 260)
        nt.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
    m.diffuse_color = (*color, 1)
    return m


def srgb(h):
    """'#rrggbb' -> linear RGB tuple."""
    def c(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return tuple(c(int(h[i:i + 2], 16)) for i in (1, 3, 5))


M = {
    "skin": material("Skin", srgb("#8a5cb8"), rough=0.6, spec=0.35),
    "head": material("HeadShell", srgb("#17121d"), rough=0.45, spec=0.5),
    "dome": material("Dome", srgb("#3e1a66"), rough=0.18, spec=0.9),
    "jacket": material("Jacket", srgb("#5c2c8a"), "jacket.png"),
    "rib": material("JacketRib", srgb("#52267c"), "rib.png"),
    "zip": material("Zipper", srgb("#b8b8c0"), rough=0.3, metal=0.9),
    "shirt": material("Shirt", srgb("#16161a"), "shirt.png"),
    "pants": material("Pants", srgb("#1e1e22"), "pants.png"),
    "pocket": material("PocketFlap", srgb("#141417"), "pants.png"),
    "belt": material("Belt", srgb("#0e0e10"), rough=0.5),
    "buckle": material("Buckle", srgb("#9a9aa2"), rough=0.3, metal=0.9),
    "sock": material("Sock", srgb("#101012")),
    "shoe": material("Shoe", srgb("#c41e1e"), "shoe.png", rough=0.45, spec=0.5),
    "sole": material("Sole", srgb("#181416"), "sole.png", rough=0.6),
    "tail": material("Tail", srgb("#1a1620"), rough=0.4, spec=0.5),
    "eye": material("EyeWhite", srgb("#f2eef0"), rough=0.3),
    "iris": material("Iris", srgb("#c0121a"), rough=0.2, spec=0.7),
    "line": material("InkLine", srgb("#06040a"), rough=0.9),
    "ear": material("EarHole", srgb("#2c2434"), rough=0.6),
}

# -------------------------------------------------------------------- mesh helpers

def make_obj(name, verts, faces, uvs, mat_list, face_mats=None):
    """verts/faces as lists; uvs: per-face list of (u, v) matching the face loop order."""
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    uv = me.uv_layers.new(name="UVMap")
    for poly, puv in zip(me.polygons, uvs):
        for k in range(poly.loop_total):
            uv.data[poly.loop_start + k].uv = puv[k]
    for m in mat_list:
        me.materials.append(m)
    if face_mats:
        for poly, mi in zip(me.polygons, face_mats):
            poly.material_index = mi
    me.update()
    return link(bpy.data.objects.new(name, me))


def catmull(points, per_seg):
    """Catmull-Rom through the control points, per_seg samples per span."""
    P = [Vector(p) for p in points]
    P = [P[0] * 2 - P[1]] + P + [P[-1] * 2 - P[-2]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for s in range(per_seg):
            t = s / per_seg
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    out.append(P[-2].copy())
    return out


def tube(name, pts, radii, mat, sides=8, arc=None, cap0=True, cap1=True, ref=(1, 0, 0),
         uv_v=(0.0, 1.0)):
    """Loft rings along a path. radii: float or (rx, ry) per ring (or one for all).

    Ring point at angle a = centre + cos(a)*rx*N + sin(a)*ry*B with N starting at
    `ref` and parallel-transported along the path, B = T x N. For a path going up
    +Z with ref +X that puts a=90deg at +Y (back) and a=270deg at -Y (front).
    arc=(a0, a1) leaves the ring open (used for the unzipped jacket)."""
    pts = [Vector(p) for p in pts]
    n = len(pts)
    if not isinstance(radii, (list, tuple)) or (len(radii) == 2 and not isinstance(radii[0], (list, tuple)) and n != 2):
        radii = [radii] * n
    radii = [(r, r) if not isinstance(r, (list, tuple)) else r for r in radii]

    T = []
    for i in range(n):
        t = pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]
        T.append(t.normalized())
    r = Vector(ref)
    N = [(r - T[0] * r.dot(T[0])).normalized()]
    for i in range(1, n):
        nv = N[-1].copy()
        axis = T[i - 1].cross(T[i])
        if axis.length > 1e-6:
            nv = Matrix.Rotation(T[i - 1].angle(T[i]), 3, axis.normalized()) @ nv
        N.append((nv - T[i] * nv.dot(T[i])).normalized())
    B = [T[i].cross(N[i]) for i in range(n)]

    closed = arc is None
    a0, a1 = (0.0, TAU) if closed else arc
    cols = sides if closed else sides + 1

    # v follows path length so textures do not stretch
    L = [0.0]
    for i in range(1, n):
        L.append(L[-1] + (pts[i] - pts[i - 1]).length)
    total = L[-1] or 1.0
    vv = [uv_v[0] + (uv_v[1] - uv_v[0]) * l / total for l in L]

    verts = []
    for i in range(n):
        rx, ry = radii[i]
        for j in range(cols):
            a = a0 + (a1 - a0) * j / sides
            verts.append(pts[i] + math.cos(a) * rx * N[i] + math.sin(a) * ry * B[i])

    faces, uvs = [], []
    for i in range(n - 1):
        for j in range(sides):
            j1 = (j + 1) % cols
            faces.append((i * cols + j, i * cols + j1, (i + 1) * cols + j1, (i + 1) * cols + j))
            u0, u1 = j / sides, (j + 1) / sides
            uvs.append(((u0, vv[i]), (u1, vv[i]), (u1, vv[i + 1]), (u0, vv[i + 1])))
    if closed:
        def cap_uv(j):
            a = TAU * j / sides
            return (0.5 + 0.04 * math.cos(a), max(0.02, min(0.98, vv[0])) + 0.0 * math.sin(a))
        if cap0:
            faces.append(tuple(reversed(range(cols))))
            uvs.append(tuple(cap_uv(j) for j in reversed(range(cols))))
        if cap1:
            base = (n - 1) * cols
            faces.append(tuple(base + j for j in range(cols)))
            uvs.append(tuple((cap_uv(j)[0], max(0.02, min(0.98, vv[-1]))) for j in range(cols)))
    return make_obj(name, verts, faces, uvs, [mat])


def prim(name, kind, loc, scale, mat, rot=(0, 0, 0), **kw):
    """UV sphere / cube / cylinder with box-projected-ish default UVs, transform applied."""
    if kind == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=kw.get("seg", 10), ring_count=kw.get("rings", 6))
    elif kind == "cube":
        bpy.ops.mesh.primitive_cube_add(size=2)
    elif kind == "cyl":
        bpy.ops.mesh.primitive_cylinder_add(vertices=kw.get("seg", 8), radius=1, depth=2)
    o = bpy.context.active_object
    for c in o.users_collection:
        c.objects.unlink(o)
    link(o)
    o.name = name
    o.location = loc
    o.scale = scale
    o.rotation_euler = rot
    o.data.materials.append(mat)
    bake(o)
    return o


def bake(o):
    """Apply the object's transform into its mesh."""
    o.data.transform(o.matrix_basis)
    o.matrix_basis = Matrix.Identity(4)


def solidify(o, thick, rim_mat=None):
    mod = o.modifiers.new("Solidify", "SOLIDIFY")
    mod.thickness = thick
    mod.offset = -1.0
    if rim_mat is not None:
        o.data.materials.append(rim_mat)
        mod.material_offset_rim = len(o.data.materials) - 1
    with bpy.context.temp_override(object=o, active_object=o):
        bpy.ops.object.modifier_apply(modifier=mod.name)


# ---------------------------------------------------------------------- skeleton

BONES = {}  # name -> (head, tail, parent)


def bone(name, head, tail, parent=None):
    BONES[name] = (Vector(head), Vector(tail), parent)


bone("root", (0, 0, 0), (0, 0, 0.2))
bone("hips", (0, 0, 0.86), (0, 0, 1.00), "root")
bone("spine", (0, 0, 1.00), (0, 0, 1.17), "hips")
bone("chest", (0, 0, 1.17), (0, 0, 1.35), "spine")
bone("neck", (0, 0, 1.35), (0, 0, 1.46), "chest")
bone("head", (0, 0, 1.46), (0, 0, 1.72), "neck")
for sfx, s in ((".L", 1), (".R", -1)):
    bone("shoulder" + sfx, (s * 0.04, 0, 1.31), (s * 0.19, 0, 1.30), "chest")
    bone("upper_arm" + sfx, (s * 0.235, 0, 1.28), (s * 0.29, 0.01, 1.03), "shoulder" + sfx)
    bone("forearm" + sfx, (s * 0.29, 0.01, 1.03), (s * 0.315, -0.01, 0.80), "upper_arm" + sfx)
    bone("hand" + sfx, (s * 0.315, -0.01, 0.80), (s * 0.33, -0.015, 0.65), "forearm" + sfx)
    bone("thigh" + sfx, (s * 0.09, 0, 0.86), (s * 0.11, -0.01, 0.50), "hips")
    bone("shin" + sfx, (s * 0.11, -0.01, 0.50), (s * 0.12, 0, 0.12), "thigh" + sfx)
    bone("foot" + sfx, (s * 0.12, 0, 0.10), (s * 0.12, -0.15, 0.04), "shin" + sfx)

# Tail: leaves the lower back, drops behind him and sweeps round his right foot.
TAIL_PATH = catmull([
    (0, 0.10, 0.86), (0, 0.24, 0.80), (0, 0.38, 0.62), (-0.05, 0.47, 0.40),
    (-0.19, 0.48, 0.20), (-0.37, 0.38, 0.09), (-0.50, 0.17, 0.07), (-0.53, -0.04, 0.11),
    (-0.46, -0.17, 0.19), (-0.37, -0.18, 0.27), (-0.33, -0.12, 0.31),
], 3)
TAIL_BONES = []
step = 4
for k, i in enumerate(range(0, len(TAIL_PATH) - 1, step)):
    j = min(i + step, len(TAIL_PATH) - 1)
    name = f"tail_{k + 1:02d}"
    bone(name, TAIL_PATH[i], TAIL_PATH[j], TAIL_BONES[-1] if TAIL_BONES else "hips")
    TAIL_BONES.append(name)


def seg_dist(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return (p - (a + ab * t)).length


def skin(o, candidates, power=6, keep=2):
    """Rigid-ish PS2 skinning: each vertex follows its nearest one or two bones."""
    groups = {b: o.vertex_groups.new(name=b) for b in candidates}
    for v in o.data.vertices:
        d = sorted((seg_dist(v.co, BONES[b][0], BONES[b][1]), b) for b in candidates)[:keep]
        w = [(1.0 / max(dist, 1e-4) ** power, b) for dist, b in d]
        tot = sum(x for x, _ in w)
        for x, b in w:
            if x / tot > 0.02:
                groups[b].add([v.index], x / tot, "REPLACE")


PARTS = []


def part(o, bones, **kw):
    skin(o, bones, **kw)
    PARTS.append(o)
    return o


# ------------------------------------------------------------------------- body

FRONT_GAP = math.radians(24)  # half-width of the unzipped jacket opening
front = 1.5 * math.pi          # a = 270deg faces -Y

# Shirt torso (black tee, print on the chest at u = 0.75).
part(tube("Shirt", [(0, 0, 0.86), (0, 0, 1.00), (0, 0, 1.15), (0, 0, 1.28), (0, 0.0, 1.355)],
          [(0.168, 0.118), (0.178, 0.124), (0.19, 0.13), (0.18, 0.12), (0.07, 0.06)],
          M["shirt"], sides=12, uv_v=(0.0, 1.0)), ["hips", "spine", "chest"])

# Jacket body: open at the front, given thickness with a zipper-silver rim.
jb = tube("Jacket", [(0, 0, 0.885), (0, 0, 1.00), (0, 0, 1.12), (0, 0, 1.22), (0, 0, 1.285), (0, 0, 1.325), (0, 0, 1.355), (0, 0, 1.375)],
          [(0.212, 0.158), (0.215, 0.16), (0.226, 0.165), (0.236, 0.162), (0.226, 0.148), (0.19, 0.125), (0.13, 0.1), (0.09, 0.08)],
          M["jacket"], sides=16, arc=(front + FRONT_GAP, front - FRONT_GAP + TAU))
solidify(jb, 0.014, M["zip"])
part(jb, ["hips", "spine", "chest"])

hem = tube("JacketHem", [(0, 0, 0.835), (0, 0, 0.89)], [(0.19, 0.142), (0.203, 0.15)], M["rib"],
           sides=16, arc=(front + FRONT_GAP * 1.05, front - FRONT_GAP * 1.05 + TAU))
solidify(hem, 0.016, M["zip"])
part(hem, ["hips"])

collar = tube("Collar", [(0, 0.005, 1.345), (0, 0.01, 1.40), (0, 0.012, 1.445)],
              [(0.098, 0.088), (0.104, 0.094), (0.116, 0.104)], M["jacket"], sides=12,
              arc=(front + math.radians(38), front - math.radians(38) + TAU))
solidify(collar, 0.012, M["zip"])
part(collar, ["chest", "neck"])

part(tube("Neck", [(0, 0.0, 1.32), (0, 0.004, 1.40), (0, 0.006, 1.49)], [0.052, 0.05, 0.05],
          M["skin"], sides=8), ["chest", "neck", "head"])

for sfx, s in ((".L", 1), (".R", -1)):
    # Puffy bomber sleeve, shoulder to wrist.
    part(tube("Sleeve" + sfx,
              [(s * 0.15, 0, 1.285), (s * 0.205, 0, 1.30), (s * 0.252, 0, 1.262), (s * 0.275, 0.005, 1.15),
               (s * 0.29, 0.01, 1.03), (s * 0.302, 0.003, 0.92), (s * 0.312, -0.008, 0.83)],
              [0.05, 0.08, 0.088, 0.084, 0.08, 0.075, 0.064], M["jacket"], sides=10),
         ["shoulder" + sfx, "upper_arm" + sfx, "forearm" + sfx])
    part(tube("Cuff" + sfx, [(s * 0.311, -0.008, 0.845), (s * 0.317, -0.01, 0.785)], [0.06, 0.05],
              M["rib"], sides=10), ["forearm" + sfx])

    # Hand: flat palm facing the thigh, three fingers and a thumb.
    hx, hy = s * 0.322, -0.012
    part(tube("Palm" + sfx, [(hx, hy, 0.79), (hx + s * 0.004, hy - 0.002, 0.745), (hx + s * 0.006, hy - 0.004, 0.70)],
              [(0.026, 0.042), (0.028, 0.05), (0.024, 0.046)], M["skin"], sides=8), ["hand" + sfx])
    for k, dy in enumerate((-0.026, 0.0, 0.026)):
        fx, fy = hx + s * 0.006, hy - 0.004 + dy
        length = 0.06 if k == 1 else 0.052
        part(tube(f"Finger{k}" + sfx,
                  [(fx, fy, 0.712), (fx, fy, 0.712 - length * 0.55), (fx - s * 0.01, fy, 0.712 - length * 0.9),
                   (fx - s * 0.024, fy, 0.712 - length)],
                  [0.0145, 0.014, 0.013, 0.011], M["skin"], sides=6), ["hand" + sfx])
    part(tube("Thumb" + sfx,
              [(hx - s * 0.004, hy - 0.03, 0.765), (hx - s * 0.01, hy - 0.05, 0.735), (hx - s * 0.02, hy - 0.055, 0.71)],
              [0.015, 0.014, 0.012], M["skin"], sides=6), ["hand" + sfx])

# Pelvis / seat of the pants, belt and buckle.
part(tube("Pelvis", [(0, 0, 0.93), (0, 0, 0.86), (0, 0.005, 0.78), (0, 0.01, 0.73)],
          [(0.172, 0.122), (0.18, 0.13), (0.155, 0.115), (0.07, 0.06)], M["pants"], sides=12), ["hips"])
part(tube("Belt", [(0, 0, 0.875), (0, 0, 0.91)], [(0.184, 0.134), (0.18, 0.13)], M["belt"], sides=12,
          cap0=False, cap1=False), ["hips"])
part(prim("Buckle", "cube", (0, -0.134, 0.892), (0.03, 0.006, 0.019), M["buckle"]), ["hips"])
part(prim("BuckleHole", "cube", (0, -0.139, 0.892), (0.018, 0.003, 0.009), M["belt"]), ["hips"])

for sfx, s in ((".L", 1), (".R", -1)):
    x = s * 0.1
    # Baggy cargo leg gathered into an elastic cuff at the ankle.
    part(tube("Leg" + sfx,
              [(s * 0.085, 0, 0.86), (s * 0.103, -0.004, 0.68), (s * 0.11, -0.01, 0.50), (s * 0.116, -0.004, 0.33),
               (s * 0.12, 0, 0.22), (s * 0.12, 0, 0.175), (s * 0.12, 0, 0.14)],
              [0.108, 0.118, 0.11, 0.106, 0.1, 0.064, 0.056], M["pants"], sides=10, ref=(s, 0, 0)),
         ["hips", "thigh" + sfx, "shin" + sfx])
    # Side cargo pocket with a darker flap.
    part(prim("Pocket" + sfx, "cube", (s * 0.214, -0.012, 0.60), (0.024, 0.078, 0.078), M["pants"],
              rot=(0, s * math.radians(-4), 0)), ["thigh" + sfx])
    part(prim("PocketFlap" + sfx, "cube", (s * 0.224, -0.012, 0.678), (0.026, 0.083, 0.018), M["pocket"],
              rot=(0, s * math.radians(-4), 0)), ["thigh" + sfx])
    part(tube("Sock" + sfx, [(s * 0.12, 0.005, 0.07), (s * 0.12, 0.0, 0.16)], 0.046, M["sock"], sides=8),
         ["shin" + sfx, "foot" + sfx])

    # Sneaker: red upper lofted heel->toe, chunky sole underneath.
    sx = s * 0.125
    part(tube("Shoe" + sfx,
              [(sx, 0.085, 0.075), (sx, 0.06, 0.098), (sx, 0.0, 0.1), (sx, -0.065, 0.08), (sx, -0.13, 0.062),
               (sx, -0.185, 0.046)],
              [(0.05, 0.045), (0.064, 0.06), (0.068, 0.064), (0.068, 0.052), (0.062, 0.04), (0.04, 0.025)],
              M["shoe"], sides=10, ref=(s, 0, 0)), ["foot" + sfx])
    part(tube("Sole" + sfx,
              [(sx, 0.1, 0.034), (sx, 0.045, 0.031), (sx, -0.065, 0.027), (sx, -0.165, 0.025), (sx, -0.2, 0.03)],
              [(0.058, 0.034), (0.072, 0.033), (0.074, 0.028), (0.068, 0.025), (0.042, 0.02)],
              M["sole"], sides=10, ref=(s, 0, 0)), ["foot" + sfx])

# Tail: tapered 8-sided tube along the spline, skinned down the bone chain.
nT = len(TAIL_PATH)
tail_r = [0.068 * (1 - i / (nT - 1)) ** 0.8 + 0.006 for i in range(nT)]
tail_r[0] = 0.05
part(tube("Tail", TAIL_PATH, tail_r, M["tail"], sides=8, ref=(1, 0, 0)), ["hips"] + TAIL_BONES, power=4)

# ------------------------------------------------------------------------- head

HC = Vector((0, 0.004, 1.565))
head = prim("Head", "sphere", HC, (0.112, 0.122, 0.132), M["head"], seg=16, rings=10)
head.data.materials.append(M["skin"])
for p in head.data.polygons:  # paint the face area purple, the rest stays black
    c = p.center
    if p.normal.y < -0.42 and 1.455 < c.z < 1.602:
        p.material_index = 1
# Pull the chin a little forward and down for Frieza's pointed jaw.
for v in head.data.vertices:
    if v.co.z < HC.z - 0.07 and v.co.y < 0:
        v.co.y -= 0.012
        v.co.z -= 0.008
part(head, ["head"])

part(prim("Dome", "sphere", (0, 0.016, 1.632), (0.102, 0.114, 0.082), M["dome"], seg=16, rings=8), ["head"])

for sfx, s in ((".L", 1), (".R", -1)):
    part(prim("Ear" + sfx, "cyl", (s * 0.11, 0.012, 1.562), (0.021, 0.021, 0.006), M["ear"],
              rot=(0, math.radians(90), 0), seg=8), ["head"])
    tilt = (0, s * math.radians(-14), 0)
    part(prim("Eye" + sfx, "sphere", (s * 0.039, -0.108, 1.566), (0.026, 0.011, 0.0135), M["eye"], rot=tilt,
              seg=8, rings=4), ["head"])
    part(prim("Iris" + sfx, "sphere", (s * 0.035, -0.117, 1.565), (0.0085, 0.004, 0.0095), M["iris"],
              seg=6, rings=4), ["head"])
    part(prim("Pupil" + sfx, "sphere", (s * 0.035, -0.1205, 1.565), (0.003, 0.0015, 0.0055), M["line"],
              seg=6, rings=3), ["head"])
    # Heavy angry brow line, sloping down toward the nose.
    part(prim("Brow" + sfx, "cube", (s * 0.041, -0.112, 1.585), (0.032, 0.007, 0.0045), M["line"],
              rot=(0, s * math.radians(-17), 0)), ["head"])

part(prim("Mouth", "cube", (0.006, -0.108, 1.498), (0.02, 0.004, 0.0022), M["line"],
          rot=(0, math.radians(6), 0)), ["head"])

# ------------------------------------------------------------------- join + rig

bpy.ops.object.select_all(action="DESELECT")
for o in PARTS:
    o.select_set(True)
bpy.context.view_layer.objects.active = PARTS[0]
bpy.ops.object.join()
body = bpy.context.active_object
body.name = "Frieza_Drip"
body.data.name = "Frieza_Drip_Mesh"

bm = bmesh.new()
bm.from_mesh(body.data)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
bm.to_mesh(body.data)
bm.free()
bpy.ops.object.shade_smooth_by_angle(angle=math.radians(55))

arm_data = bpy.data.armatures.new("Frieza_Rig")
arm = link(bpy.data.objects.new("Frieza_Rig", arm_data))
arm_data.display_type = "STICK"
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
for name, (h, t, parent) in BONES.items():
    eb = arm_data.edit_bones.new(name)
    eb.head, eb.tail = h, t
    if parent:
        eb.parent = arm_data.edit_bones[parent]
        eb.use_connect = (eb.parent.tail - h).length < 1e-5
bpy.ops.object.mode_set(mode="OBJECT")

body.parent = arm
mod = body.modifiers.new("Armature", "ARMATURE")
mod.object = arm

# -------------------------------------------------------------- idle animation

scene.render.fps = 30
scene.frame_start, scene.frame_end = 1, 61
arm.animation_data_create()
action = bpy.data.actions.new("Idle")
arm.animation_data.action = action
for pb in arm.pose.bones:
    pb.rotation_mode = "XYZ"


def key(bone_name, frame, rot):
    pb = arm.pose.bones[bone_name]
    pb.rotation_euler = rot
    pb.keyframe_insert("rotation_euler", frame=frame)


for f in range(1, 62, 5):
    ph = (f - 1) / 60 * TAU
    key("chest", f, (0.03 * math.sin(ph), 0, 0))           # breathing
    key("head", f, (-0.02 * math.sin(ph), 0, 0))
    for sfx, s in ((".L", 1), (".R", -1)):
        key("upper_arm" + sfx, f, (0, 0.04 * math.sin(ph), 0))
    for k, b in enumerate(TAIL_BONES):                       # lazy tail swish, wave travels to the tip
        amp = 0.05 + 0.03 * k
        key(b, f, (0.04 * math.sin(ph - k * 0.7), 0, amp * math.sin(ph - k * 0.7)))
for pb in arm.pose.bones:
    pb.rotation_euler = (0, 0, 0)
scene.frame_set(1)

# ---------------------------------------------------------------------- output

tris = sum(len(p.vertices) - 2 for p in body.data.polygons)
print(f"Frieza_Drip: {len(body.data.vertices)} verts, {tris} tris, {len(BONES)} bones")

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "frieza_drip.blend"), compress=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=os.path.join(HERE, "frieza_drip.glb"), export_format="GLB",
                          export_animations=True, export_yup=True, export_apply=False)
print("saved frieza_drip.blend and frieza_drip.glb")
