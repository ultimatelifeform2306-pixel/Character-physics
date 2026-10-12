"""Build a 3D sky scene in Blender: a physical sky at golden hour, a sun,
a sea of volumetric clouds below the camera and a few tall cumulus towers.

Run inside Blender (Scripting tab -> Open -> Run Script), or headless:
    blender --background --python make_sky.py -- [--render sky.png] [--save sky.blend]
"""
import math
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
opt = lambda name: argv[argv.index(name) + 1] if name in argv else None

SUN_ELEVATION = math.radians(6)     # low sun for warm light
SUN_ROTATION = math.radians(200)    # sun azimuth, roughly in front of the camera

# start from an empty scene
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
try:
    bpy.ops.preferences.addon_enable(module="cycles")
except Exception:
    pass
scene.render.engine = "CYCLES"
scene.cycles.samples = 96
scene.cycles.use_denoising = True
scene.cycles.volume_bounces = 2
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = "AgX - Punchy"
scene.view_settings.exposure = -0.4
scene.render.resolution_x, scene.render.resolution_y = 1280, 720

# --- sky ---
world = bpy.data.worlds.new("Sky")
scene.world = world
nt = world.node_tree
nt.nodes.clear()
sky = nt.nodes.new("ShaderNodeTexSky")
sky.sky_type = "MULTIPLE_SCATTERING"
sky.sun_elevation = SUN_ELEVATION
sky.sun_rotation = SUN_ROTATION
sky.altitude = 2500
sky.air_density = 1.0
sky.aerosol_density = 1.6          # a little haze
sky.sun_size = math.radians(1.2)
bg = nt.nodes.new("ShaderNodeBackground")
bg.inputs["Strength"].default_value = 0.35
out = nt.nodes.new("ShaderNodeOutputWorld")
nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
nt.links.new(bg.outputs["Background"], out.inputs["Surface"])

# --- sun lamp matching the sky's sun ---
sun_data = bpy.data.lights.new("Sun", "SUN")
sun_data.energy = 4.0
sun_data.color = (1.0, 0.78, 0.55)
sun_data.angle = math.radians(1.2)
sun = bpy.data.objects.new("Sun", sun_data)
scene.collection.objects.link(sun)
# the sky's sun points from the +Y axis rotated by sun_rotation; aim the lamp the same way
sun.rotation_euler = (math.pi / 2 - SUN_ELEVATION, 0, SUN_ROTATION - math.pi / 2)


def cloud_material(name, density, scale, detail_cut):
    """Volume material: world-space noise, thinned out towards the edges of its box."""
    mat = bpy.data.materials.new(name)
    t = mat.node_tree
    t.nodes.clear()
    n = t.nodes
    coord = n.new("ShaderNodeTexCoord")
    geo = n.new("ShaderNodeNewGeometry")      # world position, so noise size is in metres
    noise = n.new("ShaderNodeTexNoise")
    noise.noise_dimensions = "3D"
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 8
    noise.inputs["Roughness"].default_value = 0.6
    # falloff: 1 at the centre of the generated box, 0 at its edges
    sub = n.new("ShaderNodeVectorMath"); sub.operation = "SUBTRACT"
    sub.inputs[1].default_value = (0.5, 0.5, 0.5)
    mul = n.new("ShaderNodeVectorMath"); mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = (2, 2, 2.6)
    length = n.new("ShaderNodeVectorMath"); length.operation = "LENGTH"
    fall = n.new("ShaderNodeMapRange")
    fall.inputs["From Min"].default_value = 1.0
    fall.inputs["From Max"].default_value = 0.2
    shape = n.new("ShaderNodeMath"); shape.operation = "MULTIPLY_ADD"   # noise + 0.5 * falloff
    shape.inputs[1].default_value = 0.5
    ramp = n.new("ShaderNodeMapRange")
    ramp.inputs["From Min"].default_value = detail_cut
    ramp.inputs["From Max"].default_value = detail_cut + 0.15
    ramp.inputs["To Max"].default_value = density
    vol = n.new("ShaderNodeVolumePrincipled")
    vol.inputs["Color"].default_value = (1, 1, 1, 1)
    vol.inputs["Anisotropy"].default_value = 0.4
    out = n.new("ShaderNodeOutputMaterial")
    L = t.links.new
    L(geo.outputs["Position"], noise.inputs["Vector"])
    L(coord.outputs["Generated"], sub.inputs[0])
    L(sub.outputs[0], mul.inputs[0])
    L(mul.outputs[0], length.inputs[0])
    L(length.outputs["Value"], fall.inputs["Value"])
    L(fall.outputs["Result"], shape.inputs[0])
    L(noise.outputs["Fac"], shape.inputs[2])
    L(shape.outputs[0], ramp.inputs["Value"])
    L(ramp.outputs["Result"], vol.inputs["Density"])
    L(vol.outputs["Volume"], out.inputs["Volume"])
    return mat


def cloud(name, loc, size, mat):
    bpy.ops.mesh.primitive_cube_add(location=loc)
    ob = bpy.context.object
    ob.name = name
    ob.scale = (size[0] / 2, size[1] / 2, size[2] / 2)
    ob.data.materials.append(mat)
    return ob


# a wide, flat cloud sea below the camera, and cumulus towers rising out of it
sea = cloud_material("CloudSea", density=3, scale=0.03, detail_cut=0.72)
cloud("Cloud Sea", (0, 500, -10), (2600, 2600, 22), sea)
tower = cloud_material("Cumulus", density=5, scale=0.045, detail_cut=0.8)
for i, (x, y, w, h) in enumerate([(-55, 150, 60, 50), (40, 210, 80, 70), (95, 110, 45, 36), (-120, 260, 90, 60)]):
    cloud(f"Cumulus {i + 1}", (x, y, h / 2 - 16), (w, w * 0.8, h), tower)

# --- camera just above the cloud tops, looking towards the low sun ---
cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = 24
cam_data.clip_end = 3000
cam = bpy.data.objects.new("Camera", cam_data)
scene.collection.objects.link(cam)
cam.location = (0, -40, 9)
cam.rotation_euler = (math.radians(87), 0, 0)
scene.camera = cam

if opt("--save"):
    bpy.ops.wm.save_as_mainfile(filepath=opt("--save"))
if opt("--render"):
    scene.render.filepath = opt("--render")
    bpy.ops.render.render(write_still=True)
