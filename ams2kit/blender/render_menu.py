"""Render menu images of the car in a project .blend (transparent background, one image per livery colour).

blender -b car.blend --python render_menu.py -- <outdir> <width> <height> <azimuth_deg> name=r,g,b ...
Renders everything that will go into the game except LOD/damage/cockpit/guide collections. Faces whose
material name contains "paint" or "livery" (the donor's livery materials) take the livery colour.
Blender space: Z up, the car faces -Y (front) with its right side towards -X (ams2kit convention).
"""
import bpy, math, sys
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
out, W, H, AZ = args[0], int(args[1]), int(args[2]), float(args[3])
colors = [(a.split("=")[0], tuple(float(x) for x in a.split("=")[1].split(","))) for a in args[4:]]
SKIP = ("lod", "damage", "dmg", "cockpit", "guide", "interior")
sc = bpy.context.scene


def skipped(ob):
    names = [c.name.lower() for c in ob.users_collection]
    return ob.type != "MESH" or any(s in n for n in names for s in SKIP) or ob.name.lower().endswith("_dmg")


visible = []
for ob in bpy.data.objects:
    hide = skipped(ob) or ob.hide_get() or ob.hide_viewport
    ob.hide_render = hide
    if not hide:
        visible.append(ob)
if not visible:
    raise SystemExit("nothing to render")

# frame: bounding box of what is rendered
pts = [ob.matrix_world @ Vector(c) for ob in visible for c in ob.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
centre, size = (lo + hi) / 2, (hi - lo).length

sc.render.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items} else sc.render.engine
sc.render.film_transparent = True
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGBA"
try:
    sc.view_settings.view_transform = "AgX"
except Exception:
    pass
world = sc.world or bpy.data.worlds.new("menu")
sc.world = world
world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs["Color"].default_value = (0.55, 0.58, 0.62, 1)
bg.inputs["Strength"].default_value = 0.5
for ob in [o for o in bpy.data.objects if o.type == "LIGHT"]:
    ob.hide_render = True


def light(name, offset, energy, area):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy, ld.size = energy, area
    ob = bpy.data.objects.new(name, ld)
    sc.collection.objects.link(ob)
    ob.location = centre + Vector(offset) * size / 5
    ob.rotation_euler = (centre - ob.location).to_track_quat("-Z", "Y").to_euler()


light("key", (-4, -4, 6), 500, 5)
light("top", (0, 0, 7), 420, 8)
light("fill", (5, -2, 3), 180, 4)
light("rim", (2, 6, 3), 280, 4)

cam = bpy.data.objects.new("menu_cam", bpy.data.cameras.new("menu_cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.lens = 50
az, el = math.radians(AZ), math.radians(9)
d = Vector((-math.cos(az), -math.sin(az), 0))
cam.location = centre + Vector((d.x * math.cos(el), d.y * math.cos(el), math.sin(el))) * size * 2.2
cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()

def _bsdf(m):
    m.use_nodes = True
    nodes = m.node_tree.nodes
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None) or nodes.new("ShaderNodeBsdfPrincipled")
    out_node = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None) or nodes.new("ShaderNodeOutputMaterial")
    if not bsdf.outputs["BSDF"].links:
        m.node_tree.links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])
    for inp in ("Base Color", "Alpha", "Roughness", "Metallic"):
        for l in list(bsdf.inputs[inp].links):
            m.node_tree.links.remove(l)
    return bsdf


# Donor materials arrive untextured in the .blend; give non-paint ones a look by name so the menu
# images read like a car (dark glass, black tyres and trim, metallic rims, glossy lights).
LOOKS = [  # (name keywords, base colour (linear), roughness, metallic, alpha)
    (("window", "glass", "windscreen"), (0.012, 0.014, 0.017), 0.05, 0.0, 0.85),
    (("tire", "tyre", "tread", "rubber"), (0.018, 0.018, 0.018), 0.8, 0.0, 1.0),
    (("rim", "wheel", "chrome"), (0.55, 0.56, 0.58), 0.25, 1.0, 1.0),
    (("light", "lamp", "glow", "flare"), (0.75, 0.75, 0.78), 0.1, 0.3, 1.0),
    (("misc", "plastic", "black", "trim", "grill", "under", "chassis", "carbon", "interior", "cockpit", "disc", "caliper"),
     (0.02, 0.02, 0.022), 0.5, 0.0, 1.0),
]
for m in bpy.data.materials:
    low = m.name.lower()
    if any(k in low for k in ("paint", "livery")):
        continue
    for keys, col, rough, metal, alpha in LOOKS:
        if any(k in low for k in keys):
            b = _bsdf(m)
            b.inputs["Base Color"].default_value = (*col, 1)
            b.inputs["Roughness"].default_value = rough
            b.inputs["Metallic"].default_value = metal
            b.inputs["Alpha"].default_value = alpha
            if alpha < 1:
                try:
                    m.surface_render_method = "BLENDED"
                except Exception:
                    pass
            break

paints = []
for m in bpy.data.materials:
    if any(k in m.name.lower() for k in ("paint", "livery")):
        m.use_nodes = True
        nodes = m.node_tree.nodes
        bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None) or nodes.new("ShaderNodeBsdfPrincipled")
        out_node = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None) or nodes.new("ShaderNodeOutputMaterial")
        if not bsdf.outputs["BSDF"].links:
            m.node_tree.links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])
        for l in list(bsdf.inputs["Base Color"].links):
            m.node_tree.links.remove(l)
        bsdf.inputs["Roughness"].default_value = 0.3
        if "Coat Weight" in bsdf.inputs:
            bsdf.inputs["Coat Weight"].default_value = 1.0
        paints.append(bsdf)
print("paint materials:", len(paints))
for name, rgb in colors or [("car", (0.5, 0.5, 0.5))]:
    for b in paints:
        b.inputs["Base Color"].default_value = (*rgb, 1)
    sc.render.filepath = f"{out}/{name}.png"
    bpy.ops.render.render(write_still=True)
    print("WROTE", sc.render.filepath)
