"""Helpers shared by the ams2kit scripts that run inside Blender (bpy + numpy only).

Coordinate convention (see docs/04-meshes-and-render.md, "Donor .blend round trip"):
    game    : X = car left, Y = up, Z = car rear (front of the car at -Z)
    Blender : X = car left, Y = car rear, Z = up (front of the car at -Y, i.e. it faces Blender's
              "Front" view, numpad 1). Units are metres in both.
    blender = S @ game with S = swap(Y, Z), S == S^-1. S is a reflection, so triangle winding is
    reversed in both directions: game (a, b, c) <-> Blender (a, c, b).
    Object matrices: M_blender = S @ M_game @ S (a proper rotation + translation).
"""
import hashlib
import json

import bpy
import numpy as np

S3 = np.array([[1.0, 0, 0], [0, 0, 1.0], [0, 1.0, 0]])
S4 = np.eye(4)
S4[:3, :3] = S3
SLOTS_TEXT = 'ams2kit_slots.json'
README_TEXT = 'AMS2KIT_README'


def game_to_blender_matrix(m16):
    m = np.array(m16, dtype=float).reshape(4, 4)
    return S4 @ m @ S4


def to_bpy_matrix(m):
    from mathutils import Matrix
    return Matrix([list(map(float, r)) for r in m])


def _q(arr, scale):
    return np.round(np.asarray(arr, dtype=np.float64) * scale).astype(np.int64).tobytes()


def mesh_fingerprint(obj):
    """Hash of everything in an object that changes the exported geometry. Stable across save/load."""
    h = hashlib.sha1()
    h.update(obj.type.encode())
    if obj.type != 'MESH' or obj.data is None:
        return h.hexdigest()
    me = obj.data
    nv, nl, npoly = len(me.vertices), len(me.loops), len(me.polygons)
    h.update(np.array([nv, nl, npoly], np.int64).tobytes())
    co = np.zeros(nv * 3, np.float32)
    me.vertices.foreach_get('co', co)
    h.update(_q(co, 1e6))
    lv = np.zeros(nl, np.int32)
    me.loops.foreach_get('vertex_index', lv)
    h.update(lv.tobytes())
    ls = np.zeros(npoly, np.int32)
    me.polygons.foreach_get('loop_start', ls)
    h.update(ls.tobytes())
    mi = np.zeros(npoly, np.int32)
    me.polygons.foreach_get('material_index', mi)
    h.update(mi.tobytes())
    for uv in me.uv_layers:
        a = np.zeros(nl * 2, np.float32)
        uv.data.foreach_get('uv', a)
        h.update(uv.name.encode())
        h.update(_q(a, 1e6))
    if nl:
        cn = np.zeros(nl * 3, np.float32)
        me.corner_normals.foreach_get('vector', cn)
        h.update(_q(cn, 1e4))
    for a in me.attributes:
        if a.name.startswith('.') or a.name in ('position', 'sharp_face', 'sharp_edge', 'custom_normal'):
            continue
        h.update(('%s:%s:%s' % (a.name, a.domain, a.data_type)).encode())
    h.update(_q(np.array(obj.matrix_world), 1e6))
    for s in obj.material_slots:
        mat = s.material
        h.update(('|%s|%s' % (mat.name if mat else '', mat.get('ams2_mtx', '') if mat else '')).encode())
    for md in obj.modifiers:
        h.update(('%s:%s:%s:%s' % (md.name, md.type, md.show_viewport, md.show_render)).encode())
    return h.hexdigest()


def read_slots(text_name=SLOTS_TEXT):
    t = bpy.data.texts.get(text_name)
    if t is None:
        return None
    return json.loads(t.as_string())


def write_text(name, content):
    t = bpy.data.texts.get(name) or bpy.data.texts.new(name)
    t.clear()
    t.write(content)
    return t
