"""Runs inside Blender (headless): render a quick Workbench preview of a donor/car .blend (never saves it).

    blender -b file.blend --factory-startup --disable-autoexec --python render_preview.py -- out.png [view]
view: 'front34' (default, front-left three-quarter), 'rear34', 'side', 'top', or 'cockpit:x,y,z[,yaw]' (driver's view
from the eye point x,y,z in GAME space, e.g. the cockpit .bin +0x88 value; shows the Cockpit/CockpitView collections
instead of the exterior/interior LOD A meshes; yaw in degrees, + = left).
"""
import math
import sys

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index('--') + 1:]
out = args[0]
view = args[1] if len(args) > 1 else 'front34'
scene = bpy.context.scene
vl = bpy.context.view_layer
pts = []
for o in vl.objects:
    if o.type == 'MESH' and o.visible_get() and not o.hide_render and not o.name.startswith('GROUND'):
        pts += [o.matrix_world @ Vector(c) for c in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
centre = (lo + hi) / 2
size = max((hi - lo).length, 1.0)
dirs = {'front34': Vector((1.0, -1.25, 0.55)), 'rear34': Vector((-1.0, 1.25, 0.55)),
        'side': Vector((1.0, 0.0, 0.08)), 'top': Vector((0.0, 0.0001, 1.0))}
d = dirs.get(view, dirs['front34']).normalized()
cam_data = bpy.data.cameras.new('preview_cam')
cam_data.lens = 50
cam = bpy.data.objects.new('preview_cam', cam_data)
scene.collection.objects.link(cam)
cam.location = centre + d * size * 1.25
cam.rotation_euler = (centre - cam.location).to_track_quat('-Z', 'Y').to_euler()
if view.startswith('cockpit'):
    vals = [float(v) for v in (view.split(':', 1)[1].split(',') if ':' in view else '0.35,1.15,0.1'.split(','))]
    gx, gy, gz = vals[:3]
    yaw = math.radians(vals[3] if len(vals) > 3 else 0.0)

    def walk(lc):
        yield lc
        for ch in lc.children:
            yield from walk(ch)
    for lc in walk(vl.layer_collection):
        n = lc.collection.name
        if n in ('Cockpit', 'CockpitView'):
            lc.exclude, lc.hide_viewport = False, False
            lc.collection.hide_render = False
        elif n in ('REPLACE_Body', 'Interior', 'Glass', 'Guides', 'Flares', 'LODs', 'Damage'):
            lc.collection.hide_render = True
    cam.location = Vector((gx, gz, gy))                       # game (x, y up, z rear) -> Blender (x, y rear, z up)
    fwd = Vector((math.sin(yaw), -math.cos(yaw), -0.12))
    cam.rotation_euler = fwd.to_track_quat('-Z', 'Y').to_euler()
    cam_data.lens = 16
    cam_data.clip_start = 0.02
scene.camera = cam
scene.render.engine = 'BLENDER_WORKBENCH'
sh = scene.display.shading
sh.light = 'STUDIO'
sh.color_type = 'MATERIAL'
sh.show_object_outline = True
sh.show_cavity = True
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.film_transparent = False
scene.render.image_settings.file_format = 'PNG'
scene.render.filepath = out
bpy.ops.render.render(write_still=True)
print('preview written', out)
