"""Render menu images of the car (transparent background, one image per livery colour), lit like the game's
own car-select images: Cycles, a dark studio with a long overhead softbox and a front key light, low camera
with the car's front to the right of the frame.

blender -b <model.blend> --python render_menu.py -- <outdir> <width> <height> <azimuth_deg> name=r,g,b ...
        [--paint=Material A|Material B] [--front=-Y|+Y]
Renders everything that will go into the game except LOD/damage/cockpit/guide collections. The paint is the
--paint materials (exact names), else materials whose name contains "paint" or "livery". Materials with image
textures keep their look; untextured ones (donor stand-ins) get a look from their name.
Blender space: Z up; the car faces --front (default -Y, the ams2kit convention).
"""
import bpy, math, sys
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
opts = dict(a[2:].split("=", 1) for a in args if a.startswith("--"))
pos = [a for a in args if not a.startswith("--")]
out, W, H, AZ = pos[0], int(pos[1]), int(pos[2]), float(pos[3])
colors = [(a.split("=")[0], tuple(float(x) for x in a.split("=")[1].split(","))) for a in pos[4:]]
PAINT = {p for p in opts.get("paint", "").split("|") if p}
SKIP = ("lod", "damage", "dmg", "cockpit", "guide")
sc = bpy.context.scene


def skipped(ob):
    names = [c.name.lower() for c in ob.users_collection]
    return ob.type != "MESH" or any(s in n for n in names for s in SKIP) or ob.name.lower().endswith("_dmg")


visible = []
for ob in bpy.data.objects:
    hide = skipped(ob) or ob.hide_get() or ob.hide_viewport or ob.hide_render
    ob.hide_render = hide
    if not hide:
        visible.append(ob)
    if ob.type == "LIGHT":
        ob.hide_render = True
if not visible:
    raise SystemExit("nothing to render")

pts = [ob.matrix_world @ Vector(c) for ob in visible for c in ob.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
centre, size = (lo + hi) / 2, (hi - lo).length
fwd = Vector((0, 1, 0)) if opts.get("front", "-Y") == "+Y" else Vector((0, -1, 0))
left = Vector((-fwd.y, fwd.x, 0))

# ------------------------------------------------------------------ render settings
sc.render.engine = "CYCLES"
cy = sc.cycles
try:   # a GPU if there is one (a few seconds per image instead of minutes)
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for dev in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = dev
            prefs.get_devices()
        except Exception:
            continue
        if any(d.type == dev for d in prefs.devices):
            for d in prefs.devices:
                d.use = d.type == dev
            cy.device = "GPU"
            break
except Exception:
    pass
cy.samples = 96
cy.use_adaptive_sampling = True
cy.use_denoising = True
sc.render.film_transparent = True
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGBA"
for vt in ("Khronos PBR Neutral", "Standard"):   # hue-preserving (AgX turns red paint orange)
    try:
        sc.view_settings.view_transform = vt
        break
    except Exception:
        pass
sc.view_settings.exposure = 0.35

# ------------------------------------------------------------------ studio: dark surround, softboxes
world = bpy.data.worlds.new("menu_studio")
sc.world = world
world.use_nodes = True
nt = world.node_tree
nt.nodes.clear()
tc, sep = nt.nodes.new("ShaderNodeTexCoord"), nt.nodes.new("ShaderNodeSeparateXYZ")
ramp, bg, wout = nt.nodes.new("ShaderNodeValToRGB"), nt.nodes.new("ShaderNodeBackground"), nt.nodes.new("ShaderNodeOutputWorld")
nt.links.new(tc.outputs["Generated"], sep.inputs[0])
nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
els = ramp.color_ramp.elements
els[0].position, els[0].color = 0.45, (0.015, 0.015, 0.017, 1)
els[1].position, els[1].color = 0.75, (1.0, 1.0, 1.0, 1)
els.new(0.52).color = (0.10, 0.10, 0.11, 1)
nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
bg.inputs["Strength"].default_value = 0.07
nt.links.new(bg.outputs["Background"], wout.inputs["Surface"])


def softbox(name, offset, energy, sx, sy):
    ld = bpy.data.lights.new(name, "AREA")
    ld.shape, ld.size, ld.size_y, ld.energy = "RECTANGLE", sx, sy, energy
    ob = bpy.data.objects.new(name, ld)
    sc.collection.objects.link(ob)
    ob.location = centre + offset
    ob.rotation_euler = (centre - ob.location).to_track_quat("-Z", "Y").to_euler()


S = size / 5
softbox("top", -fwd * 1.6 * S + Vector((0, 0, 3.2 * S)), 2600 * S * S, 3.5 * S, 1.6 * S)   # long roof/bonnet band
softbox("key", (fwd * 2.4 - left * 2.6) * S + Vector((0, 0, 2.0 * S)), 320 * S * S, 2.2 * S, 2.2 * S)
softbox("rim", (-fwd * 3.0 + left * 1.5) * S + Vector((0, 0, 1.8 * S)), 700 * S * S, 2.0 * S, 1.2 * S)

cam = bpy.data.objects.new("menu_cam", bpy.data.cameras.new("menu_cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.lens = 70
az, el = math.radians(AZ), math.radians(4)
d = (fwd * math.cos(az) - left * math.sin(az)).normalized()      # front to the right of the frame
cam.location = centre + (d * math.cos(el) + Vector((0, 0, math.sin(el)))) * size * 2.3
cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()


# ------------------------------------------------------------------ materials
def _bsdf(m):
    m.use_nodes = True
    nodes = m.node_tree.nodes
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None) or nodes.new("ShaderNodeBsdfPrincipled")
    out_node = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None) or nodes.new("ShaderNodeOutputMaterial")
    if not bsdf.outputs["BSDF"].links:
        m.node_tree.links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])
    return bsdf


def _unlink(m, b, inputs):
    for inp in inputs:
        for l in list(b.inputs[inp].links):
            m.node_tree.links.remove(l)


def textured(m):
    return m.use_nodes and any(n.type == "TEX_IMAGE" and n.image for n in m.node_tree.nodes)


def is_paint(m):
    return m.name in PAINT if PAINT else any(k in m.name.lower() for k in ("paint", "livery"))


# untextured materials (donor stand-ins in a fitted .blend): a look from the name
LOOKS = [  # (name keywords, base colour (linear), roughness, metallic, alpha)
    (("tire", "tyre", "tread", "rubber"), (0.018, 0.018, 0.018), 0.8, 0.0, 1.0),
    (("rim", "wheel", "chrome"), (0.55, 0.56, 0.58), 0.25, 1.0, 1.0),
    (("light", "lamp", "glow", "flare"), (0.75, 0.75, 0.78), 0.1, 0.3, 1.0),
    (("misc", "plastic", "black", "trim", "grill", "under", "chassis", "carbon", "interior", "cockpit", "disc", "caliper"),
     (0.02, 0.02, 0.022), 0.5, 0.0, 1.0),
]
for m in bpy.data.materials:
    low = m.name.lower()
    if is_paint(m):
        continue
    is_window = any(k in low for k in ("window", "windscreen"))   # "Windows Ext Tinted Light" is still a window
    if is_window or ("glass" in low and not any(k in low for k in ("red", "lamp", "light", "hdr"))):
        # window glass reads dark and reflective in the game's images (the interior must not glow through)
        b = _bsdf(m)
        _unlink(m, b, ("Base Color", "Alpha", "Roughness", "Metallic"))
        b.inputs["Base Color"].default_value = (0.01, 0.011, 0.013, 1)
        b.inputs["Alpha"].default_value, b.inputs["Roughness"].default_value = 0.7, 0.02
        try:
            m.surface_render_method = "BLENDED"
        except Exception:
            pass
        continue
    if textured(m):
        continue
    for keys, col, rough, metal, alpha in LOOKS:
        if any(k in low for k in keys):
            b = _bsdf(m)
            _unlink(m, b, ("Base Color", "Alpha", "Roughness", "Metallic"))
            b.inputs["Base Color"].default_value = (*col, 1)
            b.inputs["Roughness"].default_value, b.inputs["Metallic"].default_value = rough, metal
            b.inputs["Alpha"].default_value = alpha
            break

paints = []
for m in bpy.data.materials:
    if is_paint(m):
        b = _bsdf(m)
        _unlink(m, b, ("Base Color",))
        b.inputs["Roughness"].default_value = 0.18
        if "Coat Weight" in b.inputs:
            b.inputs["Coat Weight"].default_value = 1.0
            b.inputs["Coat Roughness"].default_value = 0.03
        paints.append(b)
print("paint materials:", len(paints))
for name, rgb in colors or [("car", (0.5, 0.5, 0.5))]:
    for b in paints:
        b.inputs["Base Color"].default_value = (*rgb, 1)
    sc.render.filepath = f"{out}/{name}.png"
    bpy.ops.render.render(write_still=True)
    print("WROTE", sc.render.filepath)
