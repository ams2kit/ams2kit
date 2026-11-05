"""Runs inside Blender (headless): put a user's car model into an exported donor .blend.

    blender -b donor_<car>.blend --factory-startup --disable-autoexec --python fit_model.py -- job.json

Donor-agnostic: donor objects are found through the slot properties/collections written by export_donor.py
(roles from ams2kit.mesh.donor_layout), donor materials per class by .mtx-name heuristics, texture hints from
the donor's own UVs. Model-specific input comes from job['config'] (see ams2kit.mesh.blend_bridge.FIT_DEFAULTS):

    exterior_root / exterior_objects / exterior_exclude   which model objects form the exterior
    wheel_objects {FL,FR,RL,RR: name}, tyre_materials, rim_materials
    material_classes {model material: PAINT|GLASS|PLASTIC|GLOSS|LIGHT|SKIP|CUSTOM:<NAME>}
    custom_materials {NAME: car-owned .mtx} (ams2kit.materials): CUSTOM faces keep the model's UVs
    scale (None = from the wheelbase), rim_fit ('tyre' | 'donor_rim'), donor_materials, uv_hints, hide flags

The model file is only APPENDED from (read-only). The result is saved to job['out_blend'].
"""
import fnmatch
import json
import math
import os
import sys

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector

CLASSES = ('PAINT', 'GLASS', 'PLASTIC', 'GLOSS', 'LIGHT', 'RIM')
STEM_CORNER = {'FL': 'lf', 'FR': 'rf', 'RL': 'lr', 'RR': 'rr'}
log = {'warnings': []}


def warn(msg):
    log['warnings'].append(msg)


# ------------------------------------------------------------------ donor discovery
def coll_objects(name):
    c = bpy.data.collections.get(name)
    return [o for o in c.all_objects if o.type == 'MESH'] if c else []


def tri_count_by_mat(o):
    cnt = {}
    for p in o.data.polygons:
        if p.material_index < len(o.material_slots):
            m = o.material_slots[p.material_index].material
            if m is not None:
                cnt[m] = cnt.get(m, 0) + len(p.vertices) - 2
    return cnt


def find_donor(cfg):
    d = {}
    body_cands = coll_objects('REPLACE_Body')
    if not body_cands:
        raise SystemExit('donor .blend has no REPLACE_Body collection (not an ams2kit donor export?)')
    named = [o for o in body_cands if '_body_' in o.name.lower() or o.name.lower().endswith('_body')]
    d['body'] = bpy.data.objects.get(cfg.get('donor_body') or '') or (named or sorted(
        body_cands, key=lambda o: -len(o.data.polygons)))[0]
    lights = [o for o in coll_objects('Lights') if o.get('ams2_role') == 'lights']
    d['lights'] = bpy.data.objects.get(cfg.get('donor_lights') or '') or (
        sorted(lights, key=lambda o: -len(o.data.polygons))[0] if lights else None)
    d['rims'], d['tyres'] = {}, {}
    for c in STEM_CORNER:
        for o in coll_objects('Wheel_' + c):
            if o.get('ams2_role') == 'rim':
                d['rims'][c] = o
            elif o.get('ams2_role') == 'tire':
                d['tyres'][c] = o
    return d


def donor_materials(d, cfg):
    """class -> donor material, by .mtx-name heuristics (overridable with cfg['donor_materials'])."""
    allm = [m for m in bpy.data.materials if m.get('ams2_mtx')]
    base = lambda m: m['ams2_mtx'].replace('/', '\\').split('\\')[-1].rsplit('.', 1)[0].lower()
    body_cnt = tri_count_by_mat(d['body'])
    ranked = sorted(body_cnt, key=lambda m: -body_cnt[m])         # body materials, most used first
    bad = ('skin', 'blur', 'lodc', 'flare', 'badge', 'decal', 'licplate', 'interior', 'cockpit')

    def pick(pred, pool):
        for m in pool:
            if pred(base(m)) and not any(b in base(m) for b in bad):
                return m
        return None
    out = {}
    out['PAINT'] = pick(lambda n: n.endswith('_paint') or n == 'paint', ranked + allm) or \
        pick(lambda n: 'paint' in n and not any(k in n for k in ('plastic', 'carbon')), ranked + allm) or ranked[0]
    out['GLASS'] = pick(lambda n: 'window' in n or 'glass' in n or 'windscreen' in n, ranked + allm)
    out['PLASTIC'] = (pick(lambda n: 'plastic' in n, ranked) or pick(lambda n: 'black' in n or 'trim' in n, ranked)
                      or pick(lambda n: 'misc' in n, ranked) or pick(lambda n: 'carbon' in n, ranked) or out['PAINT'])
    prefix = os.path.commonprefix([base(m) for m in ranked if not base(m).startswith('generic')]).rstrip('_')
    out['GLOSS'] = (pick(lambda n: n == prefix, ranked + allm) or pick(lambda n: 'chrome' in n or 'gloss' in n
                                                                        or 'metal' in n, ranked) or out['PLASTIC'])
    if d['lights'] is not None:
        lc = tri_count_by_mat(d['lights'])
        out['LIGHT'] = max(lc, key=lambda m: lc[m])
    else:
        out['LIGHT'] = pick(lambda n: 'light' in n, allm) or out['GLOSS']
    rim = d['rims'].get('FL') or next(iter(d['rims'].values()), None)
    if rim is not None:
        rc = tri_count_by_mat(rim)
        out['RIM'] = max(rc, key=lambda m: rc[m])
    for cls, v in (cfg.get('donor_materials') or {}).items():
        m = next((x for x in allm if x['ams2_mtx'].lower() == v.lower() or base(x) == v.lower()), None)
        if m is None:
            warn('donor material %r for %s not found' % (v, cls))
        else:
            out[cls.upper()] = m
    if out.get('GLASS') is None:
        out['GLASS'] = out['GLOSS']
        warn('donor has no glass material; using %s' % out['GLASS'].name)
    return out


def common_uv(objs, mat):
    """Most common TEXCOORD0 (D3D convention, v down) of the donor faces using mat: a texel the donor
    itself uses a lot, so new faces sample a plausible, usually uniform part of the donor texture."""
    pts = []
    for o in objs:
        uvl = o.data.uv_layers.get('UVMap') if o is not None else None
        if uvl is None:
            continue
        idx = {i for i, s in enumerate(o.material_slots) if s.material == mat}
        nl = len(o.data.loops)
        uv = np.zeros(nl * 2, np.float32)
        uvl.data.foreach_get('uv', uv)
        uv = uv.reshape(-1, 2)
        for p in o.data.polygons:
            if p.material_index in idx:
                pts.append(uv[p.loop_start:p.loop_start + p.loop_total])
    if not pts:
        return None
    a = np.concatenate(pts)
    q = np.round(a * 256).astype(np.int64)
    keys, inv, cnt = np.unique(q, axis=0, return_inverse=True, return_counts=True)
    sel = inv.ravel() == np.argmax(cnt)
    u, v = a[sel].mean(0)
    return (float(u), float(1.0 - v)), float(cnt.max() / len(a))


# ------------------------------------------------------------------ helpers
def ctx_join(active, others):
    if not others:
        return
    with bpy.context.temp_override(active_object=active, object=active,
                                   selected_objects=[active] + others, selected_editable_objects=[active] + others):
        bpy.ops.object.join()


def world_verts(o, mats=None):
    mw = o.matrix_world
    if mats is None:
        return [mw @ v.co for v in o.data.vertices]
    idx = {i for i, s in enumerate(o.material_slots) if s.material and s.material.name in mats}
    vs = {v for p in o.data.polygons if p.material_index in idx for v in p.vertices}
    return [mw @ o.data.vertices[v].co for v in vs]


def bbox_centre(pts):
    return Vector([(min(p[k] for p in pts) + max(p[k] for p in pts)) / 2 for k in range(3)])


def guess_class(name):
    n = name.lower()
    for kws, cls in ((('glass', 'gls', 'window', 'windscreen', 'mirror'), 'GLASS'),
                     (('light', 'lamp', 'emis', 'led'), 'LIGHT'), (('chrome', 'chr', 'metal', 'gloss'), 'GLOSS'),
                     (('paint', 'body', 'carpaint'), 'PAINT')):
        if any(k in n for k in kws):
            return cls
    return 'PLASTIC'


def matches(name, patterns):
    return any(name == p or fnmatch.fnmatchcase(name, p) for p in patterns)


def subtree(root, parent_of, objs):
    """objs that are root or below it in the model hierarchy (parent_of: name -> parent name)."""
    out = []
    for o in objs:
        n, k = o.name, 0
        while n is not None and k < 100:
            if n == root:
                out.append(o)
                break
            n, k = parent_of.get(n), k + 1
    return out


def move_to(obj, coll):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)


# ------------------------------------------------------------------ interior
def _plane_frame(pts):
    """(centre, normal) of a roughly planar part (steering wheel): PCA normal, bbox centre in the plane."""
    a = np.array([tuple(p) for p in pts], np.float64)
    mean = a.mean(0)
    w, v = np.linalg.eigh(np.cov((a - mean).T))
    n, e1, e2 = v[:, 0], v[:, 2], v[:, 1]
    q = (a - mean) @ np.stack([e1, e2, n], 1)
    mid = (q.min(0) + q.max(0)) / 2
    c = mean + mid[0] * e1 + mid[1] * e2 + q[:, 2].mean() * n
    if n[1] < 0:                                  # face the driver (+Y = rear)
        n = -n
    return Vector(c), Vector(n)


def fit_interior(icfg, meshes, parent_of):
    """Replace the donor's interior/cockpit meshes with the model's interior.

    icfg keys:
      root | objects          model interior (hierarchy root, or names/patterns)
      steering_root | steering_objects   model steering wheel (goes to the steering slots)
      exclude                 names/patterns left out (airbags, inner glass, ...)
      material_classes        {model material: class}; class SKIP drops those faces; unknown -> PLASTIC
      donor_materials         {class: donor .mtx base name}; used where the target slot has that material,
                              otherwise the slot's most used material (single-material slots take everything)
      targets                 {donor object: 'interior'|'steering'|{kind, objects, exclude, materials_from}}
                              (a dict sends only those model objects, e.g. to spread a detailed interior over two
                              cockpit meshes; materials_from = donor object whose materials to use);
                              default: role 'interior' objects in the Interior and CockpitView collections
                              ('steeringwheel' in the name = steering)
      decimate                {donor object: ratio}: Weld+Decimate modifiers on that target (exterior-view LOD)
      align_steering          default true: model wheel centre/axis onto the donor wheel's (the game rotates the
                              steering node about the donor's axis)
      hide                    donor objects/patterns to delete (cockpit parts the model replaces)
    New faces get a flat colour: each donor material's most common texel in that slot (ams2_uv0)."""
    ilog = log.setdefault('interior', {})
    alive = []
    for o in meshes:                              # exterior parts were joined into the donor body (removed)
        try:
            o.name
        except ReferenceError:
            continue
        alive.append(o)
    meshes = alive
    model_names = {o.name for o in meshes}

    def pick(root_key, list_key):
        if icfg.get(list_key):
            return [o for o in meshes if matches(o.name, icfg[list_key])]
        if icfg.get(root_key):
            if icfg[root_key] not in parent_of:
                raise SystemExit('interior %s %r not found in the model' % (root_key, icfg[root_key]))
            return subtree(icfg[root_key], parent_of, meshes)
        return []
    excl = list(icfg.get('exclude') or [])
    sw = [o for o in pick('steering_root', 'steering_objects') if not matches(o.name, excl)]
    sw_names = {o.name for o in sw}
    inter = [o for o in pick('root', 'objects') if o.name not in sw_names and not matches(o.name, excl)]
    if not inter:
        raise SystemExit('interior: no model objects selected')
    classes = {k: v.upper() for k, v in (icfg.get('material_classes') or {}).items()}
    targets = icfg.get('targets')
    if not targets:
        targets = {}
        for cn in ('Interior', 'CockpitView'):
            for o in coll_objects(cn):
                if o.get('ams2_role') == 'interior':
                    targets[o.name] = 'steering' if 'steeringwheel' in o.name.lower() else 'interior'
    allm = [m for m in bpy.data.materials if m.get('ams2_mtx')]

    def base(m):
        return m['ams2_mtx'].replace('/', '\\').split('\\')[-1].rsplit('.', 1)[0].lower()
    want = {c.upper(): v.replace('/', '\\').split('\\')[-1].rsplit('.', 1)[0].lower()
            for c, v in (icfg.get('donor_materials') or {}).items()}
    sw_frame = _plane_frame([p for o in sw for p in world_verts(o)]) if sw else None
    guessed = set()
    # donor materials of every slot involved, ranked by use, taken before any slot is cleared/refilled
    mats_of = {}
    for tname, kind in targets.items():
        for n in (tname, kind.get('materials_from') if isinstance(kind, dict) else None):
            o = bpy.data.objects.get(n or '')
            if o is not None and o.type == 'MESH' and n not in mats_of:
                cnt = tri_count_by_mat(o)
                mats_of[n] = sorted(cnt, key=lambda m: -cnt[m]) or \
                    [m for m in (s.material for s in o.material_slots) if m is not None]
    for tname, kind in targets.items():
        tgt = bpy.data.objects.get(tname)
        if tgt is None or tgt.type != 'MESH':
            log['warnings'].append('interior target %s not in the donor .blend' % tname)
            continue
        sub = {}
        if isinstance(kind, dict):             # {kind, objects: [patterns], exclude: [patterns]}: part of the interior
            sub, kind = kind, kind.get('kind', 'interior')
        src = sw if kind == 'steering' else inter
        if sub.get('objects'):
            src = [o for o in src if matches(o.name, sub['objects'])]
        if sub.get('exclude'):
            src = [o for o in src if not matches(o.name, sub['exclude'])]
        if not src:
            continue
        msrc = bpy.data.objects.get(sub.get('materials_from') or '') or tgt   # donor materials of another slot
        slot_mats = list(mats_of.get(msrc.name, []))
        if not slot_mats:
            log['warnings'].append('interior target %s has no donor material' % tname)
            continue
        donor_frame = _plane_frame(world_verts(tgt)) if kind == 'steering' and len(tgt.data.vertices) > 3 else None
        for m in slot_mats:                       # flat colour for new faces: the donor's most common texel
            if not m.get('ams2_uv0'):
                e = TEXELS.get(m['ams2_mtx'].lower(), {}).get('INTERIOR')
                if e:                             # texture-checked: neutral dark texel of that texture
                    m['ams2_uv0'] = '%.6f,%.6f' % tuple(e['uv'])
                    log.setdefault('texels', {}).setdefault(m['ams2_mtx'].split('\\')[-1], {})['INTERIOR'] = e
                    continue
                r = common_uv([msrc], m)
                if r is not None:
                    m['ams2_uv0'] = '%.6f,%.6f' % r[0]
        by_base = {base(m): m for m in slot_mats}
        copies, used = [], {}
        for o in src:
            c = o.copy()
            c.data = o.data.copy()
            bpy.context.scene.collection.objects.link(c)
            keep_faces = set()
            for i, sl in enumerate(c.material_slots):
                nm = sl.material.name if sl.material else ''
                cls = classes.get(nm)
                if cls is None:
                    cls = 'PLASTIC'
                    guessed.add(nm)
                if cls == 'SKIP':
                    continue
                keep_faces.add(i)
                dm_ = by_base.get(want.get(cls, '')) or slot_mats[0]
                used[cls] = dm_['ams2_mtx'].split('\\')[-1]
                sl.material = dm_
            bm = bmesh.new()
            bm.from_mesh(c.data)
            bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index not in keep_faces], context='FACES')
            bm.to_mesh(c.data)
            bm.free()
            if c.data.polygons:
                copies.append(c)
            else:
                bpy.data.objects.remove(c, do_unlink=True)
        if not copies:
            continue
        if kind == 'steering' and sw_frame and donor_frame and icfg.get('align_steering', True):
            (cm, nm_), (cd, nd) = sw_frame, donor_frame
            q = nm_.rotation_difference(nd)
            M = Matrix.Translation(cd) @ q.to_matrix().to_4x4() @ Matrix.Translation(-cm)
            for c in copies:
                c.matrix_world = M @ c.matrix_world
            ilog.setdefault('steering_align', {})[tname] = {
                'model_centre': [round(x, 4) for x in cm], 'donor_centre': [round(x, 4) for x in cd],
                'move_m': round((cd - cm).length, 4), 'tilt_deg': round(math.degrees(nm_.angle(nd)), 2)}
        bm = bmesh.new()
        bm.from_mesh(tgt.data)
        bmesh.ops.delete(bm, geom=list(bm.verts), context='VERTS')
        bm.to_mesh(tgt.data)
        bm.free()
        ctx_join(tgt, copies)
        ratio = (icfg.get('decimate') or {}).get(tname)
        if ratio:
            w = tgt.modifiers.new('ams2_weld', 'WELD')
            w.merge_threshold = 1e-5
            d = tgt.modifiers.new('ams2_decimate', 'DECIMATE')
            d.ratio = float(ratio)
            d.use_collapse_triangulate = True
        ilog[tname] = {'kind': kind, 'model_objects': len(copies), 'decimate': ratio,
                       'tris': sum(len(p.vertices) - 2 for p in tgt.data.polygons), 'classes': used}
    if guessed:
        log['warnings'].append('interior materials without a class (PLASTIC): %s' % sorted(guessed))
    hidden = []
    for o in list(bpy.data.objects):
        if o.type == 'MESH' and o.name not in model_names and matches(o.name, icfg.get('hide') or []):
            hidden.append(o.name)
            bpy.data.objects.remove(o, do_unlink=True)
    ilog['hidden'] = sorted(hidden)


# ------------------------------------------------------------------ main
TEXELS = {}          # job['texels']: {mtx lower: {rule: {'uv': [u, v] (D3D), 'rgba': [...]}}} (ams2kit.mesh.texels)
UV_WRITTEN = set()   # donor materials whose new faces carry written texel UVs (ams2_uv0 = 'user')


def class_uv(mat, rule):
    """Texel (D3D u, v) for new faces of class `rule` with donor material `mat`: the texture-checked pick
    (texels.py), else the material's constant hint, else the donor's most common UV for it."""
    e = TEXELS.get(mat['ams2_mtx'].lower(), {})
    p = e.get(rule) or e.get(rule.split('_')[0]) or e.get('PLASTIC')
    if p:
        log.setdefault('texels', {}).setdefault(mat['ams2_mtx'].split('\\')[-1], {})[rule] = {
            'uv': p['uv'], 'rgba': p['rgba'], 'texture': e.get('texture'), 'source': p.get('source')}
        return tuple(p['uv'])
    h = str(mat.get('ams2_uv0') or '')
    if ',' in h:
        return tuple(float(x) for x in h.split(',')[:2])
    r = common_uv([o for o in bpy.data.objects if o.type == 'MESH' and mat.name in
                   [s.material.name for s in o.material_slots if s.material]][:3], mat)
    warn('no texture-checked texel for %s / %s; using the most common donor UV' % (mat['ams2_mtx'], rule))
    return r[0] if r else (0.5, 0.5)


CUSTOM = {}          # NAME -> Blender material for the car's own materials (CUSTOM:<NAME> classes)


def custom_material(cfg, name, like):
    """Blender material for car material NAME (its .mtx from cfg['custom_materials']); a copy of the donor
    material `like` so it carries the same custom properties."""
    if name in CUSTOM:
        return CUSTOM[name]
    mtx = (cfg.get('custom_materials') or {}).get(name) or (cfg.get('custom_materials') or {}).get(name.lower())
    if not mtx:
        raise SystemExit('material class CUSTOM:%s: no such entry in custom_materials (car.toml [materials])' % name)
    m = like.copy()
    m.name = mtx
    m['ams2_mtx'] = mtx
    for k in [k for k in m.keys() if k.startswith('ams2_uv')]:
        del m[k]                                  # no texel hints: the faces keep their own UVs
    CUSTOM[name] = m
    log.setdefault('custom_materials', {})[name] = mtx
    return m


def set_face_uvs(obj, slot_uv):
    """Write one UV per material slot ({slot index: (u, v) D3D}) to obj's faces (TEXCOORD0 = active render map)."""
    if not slot_uv:
        return
    me = obj.data
    uvl = next((u for u in me.uv_layers if u.active_render), None) or \
        (me.uv_layers[0] if len(me.uv_layers) else me.uv_layers.new(name='UVMap'))
    n = len(me.polygons)
    mi = np.zeros(n, np.int32)
    ls = np.zeros(n, np.int32)
    lt = np.zeros(n, np.int32)
    me.polygons.foreach_get('material_index', mi)
    me.polygons.foreach_get('loop_start', ls)
    me.polygons.foreach_get('loop_total', lt)
    uv = np.zeros(len(me.loops) * 2, np.float32)
    uvl.data.foreach_get('uv', uv)
    uv = uv.reshape(-1, 2)
    loop_mat = np.repeat(mi, lt)
    for idx, (u, v) in slot_uv.items():
        uv[loop_mat == idx] = (u, 1.0 - v)            # Blender v-up
        UV_WRITTEN.add(obj.material_slots[idx].material.name)
    uvl.data.foreach_set('uv', uv.ravel())


def light_mask(ids):
    """light_ids value (an id or a list of ids) -> bitmask of the candidate donor light ids."""
    ids = [ids] if isinstance(ids, int) else ids
    return sum(1 << int(i) for i in ids if 0 < int(i) < 31)


def set_face_lights(obj, slot_light):
    """ams2_light (face int): bitmask of the donor light ids the faces of these slots may take. The mesh
    writer picks the id whose donor lamp is nearest (left/right) and writes it into the light-control stream."""
    if not slot_light:
        return
    me = obj.data
    mat = np.zeros(len(me.polygons), np.int32)
    me.polygons.foreach_get('material_index', mat)
    a = me.attributes.get('ams2_light') or me.attributes.new('ams2_light', 'INT', 'FACE')
    val = np.zeros(len(me.polygons), np.int32)
    for idx, mask in slot_light.items():
        val[mat == idx] = mask
    a.data.foreach_set('value', val)


def main():
    global TEXELS
    job = json.load(open(sys.argv[sys.argv.index('--') + 1]))
    cfg = job['config']
    TEXELS = job.get('texels') or {}
    donor = find_donor(cfg)
    log['donor_objects'] = {'body': donor['body'].name, 'lights': donor['lights'].name if donor['lights'] else None,
                            'rims': {c: o.name for c, o in donor['rims'].items()},
                            'tyres': {c: o.name for c, o in donor['tyres'].items()}}
    dm = donor_materials(donor, cfg)
    log['donor_materials'] = {c: m['ams2_mtx'] for c, m in dm.items() if m is not None}
    # texture-space hints for new faces
    hints = {'PAINT': {'ams2_uv0': 'fit'}, 'GLASS': {'ams2_uv0': 'auto'}, 'LIGHT': {'ams2_uv0': 'auto'},
             'RIM': {'ams2_uv0': 'auto'}}
    for cls, h in (cfg.get('uv_hints') or {}).items():
        hints[cls.upper()] = h
    src_objs = {'GLASS': [donor['body']], 'LIGHT': [donor['lights'] or donor['body']],
                'RIM': list(donor['rims'].values())[:1], 'PAINT': [donor['body']]}
    log['material_props'] = {}
    for cls, h in hints.items():
        m = dm.get(cls)
        if m is None or not h:
            continue
        for k, v in h.items():
            if v == 'auto':
                r = common_uv(src_objs.get(cls, [donor['body']]), m)
                if r is None:
                    continue
                v = '%.6f,%.6f' % r[0]
                log.setdefault('auto_uv_share', {})[cls] = round(r[1], 3)
            m[k] = v
        log['material_props'][m['ams2_mtx']] = {k: m.get(k) for k in h}

    # 1. append the model (read-only)
    with bpy.data.libraries.load(job['model_blend'], link=False) as (src, dst):
        skip = tuple(cfg.get('skip_prefixes') or ('WGT-',))
        dst.objects = [n for n in src.objects if not n.startswith(skip)]
    imp = bpy.data.collections.new('MODEL_import')
    bpy.context.scene.collection.children.link(imp)
    for o in dst.objects:
        imp.objects.link(o)
    bpy.context.view_layer.update()
    parent_of = {o.name: (o.parent.name if o.parent else None) for o in dst.objects}
    meshes = [o for o in dst.objects if o.type == 'MESH']
    for o in meshes:
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
    for o in dst.objects:
        if o.type != 'MESH':
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.update()
    by_name = {o.name: o for o in meshes}

    # 2. scale + place: model wheel centres onto the WHEEL_* empties
    wheel_obj = {c: by_name.get(n) for c, n in (cfg.get('wheel_objects') or {}).items()}
    missing = [c for c, o in wheel_obj.items() if o is None]
    if missing or len(wheel_obj) < 4:
        raise SystemExit('wheel objects not found in the model: %s' % (missing or 'need FL, FR, RL, RR'))
    tyre_mats = set(cfg.get('tyre_materials') or [])
    mc = {}
    for c, o in wheel_obj.items():
        pts = world_verts(o, tyre_mats) if tyre_mats else []
        mc[c] = bbox_centre(pts or world_verts(o))
    tgt = {c: bpy.data.objects['WHEEL_' + c].location.copy() for c in mc}
    wb_t = (tgt['RL'].y + tgt['RR'].y - tgt['FL'].y - tgt['FR'].y) / 2
    wb_m = (mc['RL'].y + mc['RR'].y - mc['FL'].y - mc['FR'].y) / 2
    rot = float(cfg.get('rotate_z_deg') or 0.0)
    if not rot and wb_m * wb_t <= 0 and cfg.get('auto_orient', True):
        rot = 180.0                               # model faces +Y (glTF imports often do): turn it round
    if rot:
        R = Matrix.Rotation(math.radians(rot), 4, 'Z')
        for o in meshes:
            o.matrix_world = R @ o.matrix_world
        bpy.context.view_layer.update()
        mc = {c: R @ v for c, v in mc.items()}
        wb_m = (mc['RL'].y + mc['RR'].y - mc['FL'].y - mc['FR'].y) / 2
        log['model_rotated_z_deg'] = rot
    if wb_m * wb_t <= 0:
        raise SystemExit('model wheel order/orientation does not match the donor (front must be at -Y)')
    s = float(cfg['scale']) if cfg.get('scale') else wb_t / wb_m
    t = sum(tgt.values(), Vector()) / 4 - s * (sum(mc.values(), Vector()) / 4)
    X = Matrix.Translation(t) @ Matrix.Scale(s, 4)
    for o in meshes:
        o.matrix_world = X @ o.matrix_world
    bpy.context.view_layer.update()
    log['scale'] = s
    log['scale_source'] = 'config' if cfg.get('scale') else 'wheelbase'
    log['wheel_fit_error_m'] = {c: [round(x, 4) for x in (X @ mc[c]) - tgt[c]] for c in mc}
    tr_m = [(X @ mc['FL']).x - (X @ mc['FR']).x, (X @ mc['RL']).x - (X @ mc['RR']).x]
    tr_t = [tgt['FL'].x - tgt['FR'].x, tgt['RL'].x - tgt['RR'].x]
    log['track_model_vs_target_m'] = [[round(a, 4), round(b, 4)] for a, b in zip(tr_m, tr_t)]

    # 3. exterior: classify materials, body joined INTO the donor body object, lights replace the donor lights
    if cfg.get('exterior_objects'):
        ext = [by_name[n] for n in cfg['exterior_objects'] if n in by_name]
    else:
        rname = cfg.get('exterior_root') or ''
        if rname not in parent_of:                 # any object (mesh or empty) of the model hierarchy
            raise SystemExit('exterior_root %r not found in the model' % cfg.get('exterior_root'))
        root = by_name.get(rname)

        def under(o):
            p, n = parent_of.get(o.name), 0
            while p is not None and n < 100:
                if p == rname:
                    return True
                p, n = parent_of.get(p), n + 1
            return False
        ext = [o for o in meshes if o == root or under(o)]
    excl = list(cfg.get('exterior_exclude') or [])          # names or fnmatch patterns
    wheel_names = {o.name for o in wheel_obj.values()}
    ext = [o for o in ext if o.name not in wheel_names and not matches(o.name, excl)]
    classes = dict(cfg.get('material_classes') or {})
    light_ids = {k: light_mask(v) for k, v in (cfg.get('light_ids') or {}).items() if not k.startswith('_')}
    body_parts, light_parts = [], []
    guessed = {}
    for o in ext:
        cls_set = set()
        slot_uv, skip_idx, slot_light = {}, set(), {}
        for i, sl in enumerate(o.material_slots):
            if sl.material is None or sl.material.get('ams2_mtx'):
                continue
            nm = sl.material.name
            if nm in light_ids:
                slot_light[i] = light_ids[nm]
            cls = classes.get(nm)
            if cls is None:
                cls = guessed.setdefault(nm, guess_class(nm))
            cls = cls.upper()
            if cls.startswith('CUSTOM:'):
                # the car's own material (materials.py): faces keep the model's UVs into its own texture.
                # CUSTOM:<NAME>[:<CLASS>]: CLASS (default PLASTIC) picks where the part goes, e.g. LIGHT keeps
                # it in the donor's lights mesh (the slot the game lights up when braking)
                parts = cls.split(':')
                slot_cls = parts[2] if len(parts) > 2 and parts[2] in dm else 'PLASTIC'
                sl.material = custom_material(cfg, parts[1], dm[slot_cls])
                cls_set.add(slot_cls)
                continue
            base_cls = cls if cls in dm or cls == 'SKIP' else cls.split('_')[0]   # LIGHT_RED -> LIGHT material
            cls_set.add(base_cls)
            if cls == 'SKIP':
                skip_idx.add(i)
                continue
            sl.material = dm[base_cls]
            if base_cls != 'PAINT' and TEXELS:
                slot_uv[i] = class_uv(dm[base_cls], cls)
        if cls_set == {'SKIP'}:
            continue
        if o.data.users > 1:
            o.data = o.data.copy()
        if skip_idx:                               # SKIP faces of mixed objects are dropped too
            bm = bmesh.new()
            bm.from_mesh(o.data)
            bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index in skip_idx], context='FACES')
            bm.to_mesh(o.data)
            bm.free()
        set_face_uvs(o, slot_uv)
        set_face_lights(o, slot_light)
        (light_parts if cls_set == {'LIGHT'} and donor['lights'] is not None else body_parts).append(o)
    if guessed:
        warn('model materials without a class, guessed from the name: %s' % guessed)
    body = donor['body']
    # cockpit_body {cpit object: {objects: [patterns] (default all body parts), min_z: m}}: the body as seen from
    # the driver's seat. By default the build derives *_cpit from the body LOD A (decimated by the donor's ratio)
    # and parts sent to other slots (part_slots) have no cockpit copy; this puts full-detail parts there instead.
    for cname, cc in (cfg.get('cockpit_body') or {}).items():
        cobj = bpy.data.objects.get(cname)
        if cobj is None:
            warn('cockpit_body target %s not in the donor .blend' % cname)
            continue
        pats = cc.get('objects') or ['*']
        zmin = cc.get('min_z')
        copies = []
        for o in body_parts:
            if not matches(o.name, pats):
                continue
            c = o.copy()
            c.data = o.data.copy()
            bpy.context.scene.collection.objects.link(c)
            if zmin is not None:
                bm = bmesh.new()
                bm.from_mesh(c.data)
                mw = c.matrix_world
                bmesh.ops.delete(bm, geom=[f for f in bm.faces if max((mw @ v.co).z for v in f.verts) < zmin],
                                 context='FACES')
                bm.to_mesh(c.data)
                bm.free()
            if c.data.polygons:
                copies.append(c)
            else:
                bpy.data.objects.remove(c, do_unlink=True)
        bm = bmesh.new()
        bm.from_mesh(cobj.data)
        bmesh.ops.delete(bm, geom=list(bm.verts), context='VERTS')
        bm.to_mesh(cobj.data)
        bm.free()
        ctx_join(cobj, copies)
        log.setdefault('cockpit_body', {})[cname] = {
            'model_objects': len(copies), 'tris': sum(len(p.vertices) - 2 for p in cobj.data.polygons), 'min_z': zmin}
    # split_sides [model object patterns]: one object spanning both sides (e.g. both rear calipers) becomes
    # <name>@L and <name>@R by face centre (left = +X in the donor .blend), so part_slots can target each side
    for o in [o for o in body_parts if matches(o.name, cfg.get('split_sides') or [])]:
        halves = []
        for side, keep_left in (('@L', True), ('@R', False)):
            h = o.copy()
            h.data = o.data.copy()
            bpy.context.scene.collection.objects.link(h)
            bm = bmesh.new()
            bm.from_mesh(h.data)
            mw = h.matrix_world
            bmesh.ops.delete(bm, geom=[f for f in bm.faces if ((mw @ f.calc_center_median()).x > 0) != keep_left],
                             context='FACES')
            bm.to_mesh(h.data)
            bm.free()
            h.name = o.name + side
            if h.data.polygons:
                halves.append(h)
            else:
                bpy.data.objects.remove(h, do_unlink=True)
        body_parts.remove(o)
        bpy.data.objects.remove(o, do_unlink=True)
        body_parts.extend(halves)
        log.setdefault('split_sides', {})[halves[0].name[:-2] if halves else '?'] = [h.name for h in halves]
    # part_slots {model object pattern: donor object}: those parts go into another donor body slot instead of
    # the main body (each .meb holds at most 65535 vertices; a detailed body is decimated otherwise)
    groups = {body.name: []}
    for o in body_parts:
        dst = next((t for pat, t in (cfg.get('part_slots') or {}).items() if matches(o.name, [pat])), body.name)
        if dst not in bpy.data.objects:
            warn('part_slots target %s not in the donor .blend; %s goes into the body' % (dst, o.name))
            dst = body.name
        groups.setdefault(dst, []).append(o)
    used_slots = set()
    for dst, parts in groups.items():
        slot_obj = bpy.data.objects[dst]
        if dst != body.name:                       # the slot's own donor materials (its streams suit them)
            own = {m.name for m in tri_count_by_mat(slot_obj)}
            used = {s.material.name for o in parts for s in o.material_slots if s.material is not None}
            if used - own:
                warn('part_slots %s: its donor mesh does not use %s; the vertex streams of that slot may not suit '
                     'those shaders (paint rendered black from a slot without the paint material)'
                     % (dst, sorted(used - own)))
        bm = bmesh.new()
        bm.from_mesh(slot_obj.data)
        bmesh.ops.delete(bm, geom=list(bm.verts), context='VERTS')   # remove the donor faces, keep object + slots
        bm.to_mesh(slot_obj.data)
        bm.free()
        ctx_join(slot_obj, parts)
        used_slots.add(dst)
        entry = {'object': dst, 'tris': sum(len(p.vertices) - 2 for p in slot_obj.data.polygons), 'model_objects': len(parts)}
        if dst == body.name:
            log['body'] = entry
        else:
            log.setdefault('part_slots', {})[dst] = entry
    if light_parts:
        old = donor['lights']
        name, coll = old.name, old.users_collection[0]
        bpy.data.objects.remove(old, do_unlink=True)
        ctx_join(light_parts[0], light_parts[1:])
        lights = light_parts[0]
        lights.name = name
        move_to(lights, coll)
        log['lights'] = {'object': name, 'tris': sum(len(p.vertices) - 2 for p in lights.data.polygons),
                         'model_objects': len(light_parts)}

    # 4. rims: rim faces of each model wheel, radius fitted to the donor tyre (or rim), hub on the empty
    rim_mats = set(cfg.get('rim_materials') or [])
    rim_fit = cfg.get('rim_fit', 'tyre')
    log['rims'] = {}
    for c, w in wheel_obj.items():
        don = donor['rims'].get(c)
        if don is None or not rim_mats:
            continue
        if w.data.users > 1:
            w.data = w.data.copy()        # glTF imports share one mesh between the four wheels
        keep = {i for i, sl in enumerate(w.material_slots) if sl.material and sl.material.name in rim_mats}
        bm = bmesh.new()
        bm.from_mesh(w.data)
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index not in keep], context='FACES')
        bm.to_mesh(w.data)
        bm.free()
        if cfg.get('rim_custom_material'):
            # the car's own rim material (a clone of the donor rim's): faces keep the model's UVs
            cm = custom_material(cfg, cfg['rim_custom_material'], dm['RIM'])
            for sl in w.material_slots:
                sl.material = cm
        else:
            for sl in w.material_slots:
                sl.material = dm['RIM']
            if TEXELS:
                set_face_uvs(w, {i: class_uv(dm['RIM'], 'RIM') for i in range(len(w.material_slots))})
        pts = world_verts(w)
        hub = bbox_centre(pts)
        r_model = max(((p.y - hub.y) ** 2 + (p.z - hub.z) ** 2) ** 0.5 for p in pts)
        dp = world_verts(don)
        dl = don.matrix_world.translation
        r_rim = max(((p.y - dl.y) ** 2 + (p.z - dl.z) ** 2) ** 0.5 for p in dp)
        ty = donor['tyres'].get(c)
        r_tyre_in = None
        if ty is not None:
            tl = ty.matrix_world.translation
            r_tyre_in = min(((p.y - tl.y) ** 2 + (p.z - tl.z) ** 2) ** 0.5 for p in world_verts(ty))
        if rim_fit == 'tyre' and r_tyre_in is not None:
            target = r_tyre_in + float(cfg.get('rim_flange_overlap', 0.005))   # donors: rim edge ~5 mm under the bead
        else:
            target = r_rim
        sw = target / r_model
        left = c.endswith('L')
        outer_don = max(p.x for p in dp) if left else min(p.x for p in dp)
        outer_mod = max(p.x for p in pts) if left else min(p.x for p in pts)
        e = tgt[c]
        M = Matrix.Translation((outer_don - sw * (outer_mod - hub.x) - hub.x, e.y - hub.y, e.z - hub.z)) @ \
            Matrix.Translation(hub) @ Matrix.Scale(sw, 4) @ Matrix.Translation(-hub)
        w.matrix_world = M @ w.matrix_world
        name, coll = don.name, don.users_collection[0]
        bpy.data.objects.remove(don, do_unlink=True)
        w.name = name
        move_to(w, coll)
        log['rims'][c] = {'object': name, 'scale': round(sw, 4), 'model_rim_r': round(r_model, 4),
                          'donor_rim_r': round(r_rim, 4),
                          'donor_tyre_inner_r': round(r_tyre_in, 4) if r_tyre_in else None,
                          'target_r': round(target, 4), 'fit': rim_fit}

    # 4b. interior / cockpit (optional cfg['interior'])
    if cfg.get('interior'):
        fit_interior(cfg['interior'], meshes, parent_of)

    # 5. drop the rest of the model; hide donor-only exterior parts (by role/collection)
    for o in list(imp.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.collections.remove(imp)
    keep = set(cfg.get('keep') or [])
    hide = [o for o in coll_objects('REPLACE_Body') if o != body and o.name not in used_slots]
    hide += coll_objects('Glass') + coll_objects('Flares')
    hide += [o for o in coll_objects('Lights') if o.name != (log.get('lights') or {}).get('object')
             and (donor['lights'] is None or light_parts)]
    hide += [o for o in coll_objects('Other') if o.get('ams2_role') == 'wiper']
    for o in coll_objects('Cockpit'):
        role, n = o.get('ams2_role'), o.name.lower()
        if (role in ('body', 'wiper') and cfg.get('hide_cockpit_body', True)) or \
           (role == 'glass' and cfg.get('hide_cockpit_glass', True)) or \
           ('extanim' in n and cfg.get('hide_cockpit_extanim', True)):
            hide.append(o)
    hide += [bpy.data.objects[n] for n in cfg.get('extra_hide') or [] if n in bpy.data.objects]
    hidden = []
    for o in hide:
        if o.name in keep or o.name not in bpy.data.objects:
            continue
        hidden.append(o.name)
        bpy.data.objects.remove(o, do_unlink=True)
    log['hidden'] = sorted(hidden)
    for n in sorted(UV_WRITTEN):                   # new faces carry their texel in their own UVs
        m = bpy.data.materials.get(n)
        if m is not None and m.get('ams2_mtx'):
            m['ams2_uv0'] = 'user'
            log['material_props'].setdefault(m['ams2_mtx'], {})['ams2_uv0'] = 'user (texel UVs written per face)'
    bpy.context.preferences.filepaths.save_version = 0
    os.makedirs(os.path.dirname(job['out_blend']), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=job['out_blend'], compress=True)
    with open(job['result'], 'w') as fh:
        json.dump(log, fh, indent=1)


main()
