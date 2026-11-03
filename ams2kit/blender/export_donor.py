"""Runs inside Blender (headless): build donor_<car>.blend from decoded donor meshes.

    blender -b --factory-startup --python export_donor.py -- job.json

job.json is written by ams2kit.mesh.blend_bridge.export_donor_blend (mesh arrays in .npz files, game space).
"""
import json
import math
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

COLOURS = [  # (keyword in material path, RGBA viewport/base colour)
    ('window', (0.35, 0.55, 0.75, 0.35)), ('glass', (0.35, 0.55, 0.75, 0.35)),
    ('tire', (0.05, 0.05, 0.05, 1)), ('tread', (0.05, 0.05, 0.05, 1)), ('tyre', (0.05, 0.05, 0.05, 1)),
    ('rim', (0.55, 0.55, 0.58, 1)), ('disc', (0.35, 0.33, 0.32, 1)), ('caliper', (0.75, 0.15, 0.1, 1)),
    ('flare', (1.0, 0.95, 0.6, 1)), ('light', (0.95, 0.85, 0.4, 1)),
    ('interior', (0.25, 0.2, 0.17, 1)), ('carbon', (0.12, 0.12, 0.13, 1)), ('plastic', (0.12, 0.12, 0.12, 1)),
    ('badge', (0.8, 0.8, 0.8, 1)), ('licplate', (0.9, 0.9, 0.9, 1)), ('shadow', (0.0, 0.0, 0.0, 0.5)),
    ('paint', (0.75, 0.12, 0.08, 1)),
]


def colour_for(mtx):
    low = mtx.lower()
    for kw, c in COLOURS:
        if kw in low:
            return c
    return (0.6, 0.6, 0.62, 1)


def get_material(mtx, cache):
    if mtx in cache:
        return cache[mtx]
    m = bpy.data.materials.new(mtx)
    m['ams2_mtx'] = mtx
    col = colour_for(mtx)
    m.diffuse_color = col
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get('Principled BSDF')
    if bsdf is not None:
        bsdf.inputs['Base Color'].default_value = col
        if col[3] < 1:
            bsdf.inputs['Alpha'].default_value = col[3]
    if col[3] < 1:
        try:
            m.surface_render_method = 'BLENDED'
        except Exception:
            pass
    cache[mtx] = m
    return m


def build_mesh(rec, mats):
    d = np.load(rec['npz'])
    pos = d['pos'].astype(np.float64)
    n = len(pos)
    tris = d['tris'].astype(np.int64).reshape(-1, 3)
    faces = tris[:, [0, 2, 1]]                       # game winding -> Blender winding (S is a reflection)
    me = bpy.data.meshes.new(rec['stem'])
    me.vertices.add(n)
    me.vertices.foreach_set('co', pos[:, [0, 2, 1]].astype(np.float32).ravel())
    nt = len(faces)
    me.loops.add(nt * 3)
    me.loops.foreach_set('vertex_index', faces.ravel().astype(np.int32))
    me.polygons.add(nt)
    me.polygons.foreach_set('loop_start', (np.arange(nt, dtype=np.int32) * 3))
    me.update(calc_edges=True)
    for mtx in rec['materials']:
        me.materials.append(get_material(mtx, mats))
    if nt:
        me.polygons.foreach_set('material_index', d['groups'].astype(np.int32))
    corner = faces.ravel()
    for key in sorted(k for k in d.files if k.startswith('tc')):
        k = int(key[2:])
        a = d[key].astype(np.float32)
        c = a.shape[1]
        if c >= 2:
            name = 'UVMap' if k == 0 else 'TEXCOORD%d' % k
            uv = me.uv_layers.new(name=name)
            vals = np.stack([a[:, 0], 1.0 - a[:, 1]], axis=1)   # D3D v-down -> Blender v-up
            if nt:
                uv.data.foreach_set('uv', vals[corner].ravel())
            if c == 3:
                at = me.attributes.new('TEXCOORD%d_W' % k, 'FLOAT', 'CORNER')
                if nt:
                    at.data.foreach_set('value', a[corner, 2])
        else:
            at = me.attributes.new('TEXCOORD%d' % k, 'FLOAT', 'CORNER')
            if nt:
                at.data.foreach_set('value', a[corner, 0])
    if me.uv_layers.get('UVMap') is not None:
        me.uv_layers['UVMap'].active = True
        me.uv_layers['UVMap'].active_render = True
    if 'col' in d.files:
        ca = me.color_attributes.new('COLOR0', 'BYTE_COLOR', 'CORNER')
        if nt:
            ca.data.foreach_set('color_srgb', (d['col'][corner].astype(np.float32) / 255.0).ravel())
    fl = me.attributes.new('ams2_donor', 'INT', 'POINT')
    fl.data.foreach_set('value', np.ones(n, np.int32))
    # exact donor normals + original positions: used for vertices the user did not move (Blender's int16
    # custom normals cannot reproduce every donor normal, e.g. normals facing away from their faces)
    oc = me.attributes.new('ams2_co', 'FLOAT_VECTOR', 'POINT')
    oc.data.foreach_set('vector', pos[:, [0, 2, 1]].astype(np.float32).ravel())
    for key, an in (('tan4', 'ams2_tan4'), ('tan5', 'ams2_tan5')):      # donor tangent frame (semantic 4/5)
        if key in d.files:
            ta = me.attributes.new(an, 'FLOAT_VECTOR', 'POINT')
            ta.data.foreach_set('vector', d[key][:, [0, 2, 1]].astype(np.float32).ravel())
    if nt and 'nrm' in d.files:
        on = me.attributes.new('ams2_nrm', 'FLOAT_VECTOR', 'CORNER')
        on.data.foreach_set('vector', d['nrm'][:, [0, 2, 1]].astype(np.float32)[corner].ravel())
    if nt:
        me.shade_smooth()
        if 'nrm' in d.files:
            nb = d['nrm'][:, [0, 2, 1]].astype(np.float64)
            ln = np.linalg.norm(nb, axis=1)
            nb[ln < 1e-8] = (0, 0, 1)
            me.normals_split_custom_set_from_vertices([tuple(v) for v in nb])
    return me


def main():
    job = json.load(open(sys.argv[sys.argv.index('--') + 1]))
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    colls = {}
    for name, visible in job['collections']:
        c = bpy.data.collections.new(name)
        scene.collection.children.link(c)
        colls[name] = (c, visible)
    for name in job['wheel_collections']:
        c = bpy.data.collections.new(name)
        colls['Wheels'][0].children.link(c)
        colls[name] = (c, True)
    guides = bpy.data.collections.new('Guides')
    scene.collection.children.link(guides)

    mats = {}
    slots = {}
    objs = []
    for rec in job['meshes']:
        me = build_mesh(rec, mats)
        ob = bpy.data.objects.new(rec['stem'], me)
        ob.matrix_world = C.to_bpy_matrix(C.game_to_blender_matrix(rec['frame']))
        ob['ams2_slot'] = rec['stem']
        ob['ams2_pak_path'] = rec['pak_path']
        ob['ams2_role'] = rec['role']
        ob['ams2_note'] = rec['note']
        ob['ams2_frame_game'] = json.dumps(rec['frame'])
        if rec['skinned']:
            ob['ams2_skinned'] = 1
        colls[rec['coll']][0].objects.link(ob)
        objs.append((ob, rec))
        if rec['coll'] in ('LODs', 'Damage', 'CockpitView'):
            ob.display_type = 'WIRE' if rec['coll'] == 'Damage' else 'SOLID'

    # guides: wheel empties, ground plane, info text
    tyre_r = job.get('tyre_radius', {})
    for corner, c in job['wheels'].items():
        e = bpy.data.objects.new('WHEEL_' + corner, None)
        e.empty_display_type = 'CIRCLE'
        e.empty_display_size = float(tyre_r.get(corner, 0.33))
        e.location = (c[0], c[2], c[1])
        e.rotation_euler = (0.0, math.pi / 2, 0.0)       # circle in the Blender YZ plane = wheel plane
        e['ams2_wheel_centre_game'] = list(c)
        e.show_name = True
        guides.objects.link(e)
    g = job['ground']
    bpy.ops.mesh.primitive_plane_add(size=1.0)
    pl = bpy.context.active_object
    for cl in list(pl.users_collection):
        cl.objects.unlink(pl)
    guides.objects.link(pl)
    pl.name = 'GROUND_guide'
    pl.location = (g['cx'], g['cy'], g['z'])
    pl.scale = (g['sx'], g['sy'], 1.0)
    pl.display_type = 'WIRE'
    pl.hide_select = True
    pl.hide_render = True
    txt = bpy.data.curves.new('INFO_text', 'FONT')
    txt.body = job['info']
    txt.size = 0.09
    t = bpy.data.objects.new('INFO_read_AMS2KIT_README', txt)
    t.location = (g['cx'] + g['sx'] / 2 + 0.3, g['cy'] - g['sy'] / 2, g['z'])
    t.hide_render = True
    guides.objects.link(t)
    fr = bpy.data.curves.new('FRONT_text', 'FONT')
    fr.body = 'FRONT (-Y)'
    fr.size = 0.25
    fr.align_x = 'CENTER'
    f = bpy.data.objects.new('FRONT_marker', fr)
    f.location = (g['cx'], g['cy'] - g['sy'] / 2 - 0.4, g['z'])
    f.hide_render = True
    guides.objects.link(f)

    # visibility
    def walk(lc):
        yield lc
        for ch in lc.children:
            yield from walk(ch)
    for lc in walk(bpy.context.view_layer.layer_collection):
        if lc.name in colls and not colls[lc.name][1]:
            lc.hide_viewport = True
            lc.collection.hide_render = True

    bpy.context.view_layer.update()
    for ob, rec in objs:
        slots[rec['stem']] = {'pak_path': rec['pak_path'], 'frame': rec['frame'], 'coll': rec['coll'],
                              'fp': C.mesh_fingerprint(ob), 'skinned': rec['skinned']}
    C.write_text(C.SLOTS_TEXT, json.dumps({'format': 1, 'donor': job['donor'], 'convention': job['convention'],
                                           'wheels_game': job['wheels'], 'slots': slots}, indent=1))
    C.write_text(C.README_TEXT, job['readme'])
    scene['ams2_donor'] = job['donor']
    scene['ams2_convention'] = job['convention']
    # viewports: colour by material, show the README in a text editor when the file is opened in the UI
    for scr in bpy.data.screens:
        for area in scr.areas:
            for sp in area.spaces:
                if sp.type == 'VIEW_3D':
                    sp.shading.color_type = 'MATERIAL'
                    sp.clip_end = 1000.0
                elif sp.type == 'TEXT_EDITOR':
                    sp.text = bpy.data.texts[C.README_TEXT]
    out = job['out_blend']
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.context.preferences.filepaths.save_version = 0      # no .blend1 backup next to the export
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
    with open(job['result'], 'w') as fh:
        json.dump({'objects': len(objs), 'materials': len(mats), 'blend': out}, fh)


main()
