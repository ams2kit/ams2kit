"""Runs inside Blender (headless): dump the meshes of an edited donor .blend for the .meb builder.

    blender -b car.blend --factory-startup --disable-autoexec --python import_blend.py -- job.json

job.json (from ams2kit.mesh.blend_bridge.build_from_blend):
    {"slots": [{"stem", "kind", "sources", "ratio", "skinned"}], "dump_dir", "result", "force", "max_verts",
     "ams2kit_root"}
Writes one <stem>.npz per slot that needs geometry (see meshweld.py for the arrays) and result.json with
the action per slot: donor | collapse | mesh | dmg | dmg_mesh.
Never saves the .blend (temporary modifiers are removed again and the file is not written).
"""
import json
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

GEOM_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}


def resolve_mtx(mat):
    if mat is None:
        return '?<none>'
    v = mat.get('ams2_mtx')
    if v:
        return str(v)
    if mat.name.lower().endswith('.mtx'):
        return mat.name
    base = mat.name.rsplit('.', 1)[0] if mat.name[-4:-3] == '.' and mat.name[-3:].isdigit() else mat.name
    if base.lower().endswith('.mtx'):
        return base
    return '?' + mat.name


def object_arrays(obj, frame_inv, ratio):
    """Evaluated, triangulated corner arrays of one object in game space local to the slot frame."""
    dec = weld = None
    if ratio < 0.98:
        # merge split vertices first (imported models are often fully split; collapse needs connectivity)
        weld = obj.modifiers.new('_ams2_weld', 'WELD')
        weld.merge_threshold = 1e-5
        dec = obj.modifiers.new('_ams2_decimate', 'DECIMATE')
        dec.decimate_type = 'COLLAPSE'
        dec.ratio = max(ratio, 0.002)
        dec.use_collapse_triangulate = True
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    eo = obj.evaluated_get(dg)
    me = eo.to_mesh()
    try:
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        nl = len(me.loops)
        nv = len(me.vertices)
        lt = np.zeros(nt * 3, np.int32)
        me.loop_triangles.foreach_get('loops', lt)
        ltm = np.zeros(nt, np.int32)
        me.loop_triangles.foreach_get('material_index', ltm)
        lv = np.zeros(nl, np.int32)
        me.loops.foreach_get('vertex_index', lv)
        co = np.zeros(nv * 3, np.float32)
        me.vertices.foreach_get('co', co)
        co = co.reshape(-1, 3).astype(np.float64)
        cn = np.zeros(nl * 3, np.float32)
        if nl:
            me.corner_normals.foreach_get('vector', cn)
        cn = cn.reshape(-1, 3).astype(np.float64)
        an, ac, dn0 = me.attributes.get('ams2_nrm'), me.attributes.get('ams2_co'), me.attributes.get('ams2_donor')
        if (an is not None and ac is not None and dn0 is not None and an.domain == 'CORNER'
                and ac.domain == 'POINT' and dn0.domain == 'POINT' and nl):
            a = np.zeros(nl * 3, np.float32)
            an.data.foreach_get('vector', a)
            oc = np.zeros(nv * 3, np.float32)
            ac.data.foreach_get('vector', oc)
            fl = np.zeros(nv, np.int32)
            dn0.data.foreach_get('value', fl)
            still = (np.abs(oc.reshape(-1, 3) - co).max(1) < 1e-6) & (fl > 0)    # donor vertex not moved
            use = still[lv]
            cn[use] = a.reshape(-1, 3)[use]
        else:
            still = np.zeros(nv, bool)
        tans = {}
        for key in ('tan4', 'tan5'):
            ta = me.attributes.get('ams2_' + key)
            if ta is not None and ta.domain == 'POINT' and ta.data_type == 'FLOAT_VECTOR':
                a = np.zeros(nv * 3, np.float32)
                ta.data.foreach_get('vector', a)
                tans[key] = a.reshape(-1, 3).astype(np.float64)
        mw = np.array(eo.matrix_world, dtype=np.float64)
        A = frame_inv @ C.S4 @ mw          # Blender object space -> game slot-local space
        L = A[:3, :3]
        flip = np.linalg.det(L) < 0         # S makes this True for normal objects
        tri = lt.reshape(-1, 3)
        if flip:
            tri = tri[:, [0, 2, 1]]
        corner = tri.ravel()
        vidx = lv[corner]
        pos = co[vidx] @ L.T + A[:3, 3]
        nrm = cn[corner] @ np.linalg.inv(L)          # (L^-1)^T n, row-vector form
        ln = np.linalg.norm(nrm, axis=1)
        ln[ln < 1e-12] = 1.0
        nrm = nrm / ln[:, None]
        out = {'pos': pos.astype(np.float32), 'nrm': nrm.astype(np.float32), 'vidx': vidx.astype(np.int64),
               'mat': ltm, 'nv': nv}
        if len(tans) == 2:                    # donor tangents for unmoved donor vertices (others recomputed)
            for key, a in tans.items():
                t = a[vidx] @ L.T
                lt_ = np.linalg.norm(t, axis=1)
                lt_[lt_ < 1e-12] = 1.0
                out[key] = (t / lt_[:, None]).astype(np.float32)
            out['tanok'] = still[vidx].astype(np.int8)
        # UV maps (TEXCOORD0 = the active render map)
        uv_active = None
        for uv in me.uv_layers:
            if uv.active_render:
                uv_active = uv.name
        if uv_active is None and len(me.uv_layers):
            uv_active = me.uv_layers[0].name
        uvs = {}
        for uv in me.uv_layers:
            a = np.zeros(nl * 2, np.float32)
            uv.data.foreach_get('uv', a)
            uvs[uv.name] = a.reshape(-1, 2)[corner]
        out['uv0'] = uvs[uv_active] if uv_active else np.zeros((len(corner), 2), np.float32)
        for name, a in uvs.items():
            if name.startswith('TEXCOORD'):
                out['uv:' + name] = a
        for at in me.attributes:
            if at.name.startswith('TEXCOORD') and at.data_type == 'FLOAT' and at.domain in ('CORNER', 'POINT'):
                a = np.zeros(len(at.data), np.float32)
                at.data.foreach_get('value', a)
                out['attr:' + at.name] = a[corner] if at.domain == 'CORNER' else a[vidx]
        ca = me.color_attributes.get('COLOR0')
        if ca is not None and ca.domain in ('CORNER', 'POINT'):
            a = np.zeros(len(ca.data) * 4, np.float32)
            ca.data.foreach_get('color_srgb', a)
            a = np.clip(np.round(a.reshape(-1, 4) * 255.0), 0, 255).astype(np.uint8)
            out['col'] = a[corner] if ca.domain == 'CORNER' else a[vidx]
        dn = me.attributes.get('ams2_donor')
        if dn is not None and dn.domain == 'POINT' and dn.data_type == 'INT':
            a = np.zeros(nv, np.int32)
            dn.data.foreach_get('value', a)
            out['donor'] = (a[vidx] > 0).astype(np.int8)
        else:
            out['donor'] = np.zeros(len(corner), np.int8)
        la = me.attributes.get('ams2_light')                      # fit_model: candidate light ids (bitmask)
        if la is not None and la.domain == 'FACE' and la.data_type == 'INT' and nt:
            a = np.zeros(len(me.polygons), np.int32)
            la.data.foreach_get('value', a)
            lp = np.zeros(nt, np.int32)
            me.loop_triangles.foreach_get('polygon_index', lp)
            out['light'] = np.repeat(a[lp], 3)
        mats = []
        props = {}
        for s in eo.material_slots:
            m = resolve_mtx(s.material)
            mats.append(m)
            if s.material is not None:
                pr = {k[5:]: str(s.material[k]) for k in s.material.keys()
                      if k.startswith('ams2_') and k != 'ams2_mtx'}
                if pr:
                    props[m] = pr
        if not mats:
            mats = ['?<none>']
        out['mats'] = mats
        out['mat'] = np.minimum(ltm, len(mats) - 1)
        out['props'] = props
        return out
    finally:
        eo.to_mesh_clear()
        for md in (dec, weld):
            if md is not None:
                obj.modifiers.remove(md)


def merge(parts):
    """Concatenate object dumps; unify material lists (by resolved .mtx path, first appearance order)."""
    mats, props = [], {}
    for p in parts:
        for m in p['mats']:
            if m not in mats:
                mats.append(m)
        props.update(p['props'])
    keys_uv = sorted({k for p in parts for k in p if k.startswith('uv:') or k.startswith('attr:')})
    has_col = any('col' in p for p in parts)
    has_light = any('light' in p for p in parts)
    out = {k: [] for k in ['pos', 'nrm', 'vidx', 'mat', 'donor', 'uv0', 'tan4', 'tan5', 'tanok'] + keys_uv +
           (['col'] if has_col else []) + (['light'] if has_light else [])}
    off = 0
    for p in parts:
        nc = len(p['vidx'])
        remap = np.array([mats.index(m) for m in p['mats']], np.int32)
        out['pos'].append(p['pos'])
        out['nrm'].append(p['nrm'])
        out['vidx'].append(p['vidx'] + off)
        out['mat'].append(remap[p['mat']] if len(p['mat']) else p['mat'])
        donor = p['donor'].copy()
        out['uv0'].append(p['uv0'])
        for k in ('tan4', 'tan5'):
            out[k].append(p[k] if k in p else np.zeros((nc, 3), np.float32))
        out['tanok'].append(p['tanok'] if 'tanok' in p else np.zeros(nc, np.int8))
        for k in keys_uv:
            if k in p:
                out[k].append(p[k])
            else:
                out[k].append(np.zeros((nc, 2) if k.startswith('uv:') else nc, np.float32))
                donor[:] = 0                                  # missing stored stream -> regenerate
        if has_col:
            if 'col' in p:
                out['col'].append(p['col'])
            else:
                out['col'].append(np.full((nc, 4), 255, np.uint8))
                donor[:] = 0
        if has_light:
            out['light'].append(p['light'] if 'light' in p else np.zeros(nc, np.int32))
        out['donor'].append(donor)
        off += p['nv']
    res = {k: np.concatenate(v) if v else np.zeros(0) for k, v in out.items()}
    return res, mats, props


def main():
    job = json.load(open(sys.argv[sys.argv.index('--') + 1]))
    sys.path.insert(0, job['ams2kit_root'])
    from ams2kit.mesh import meshweld
    info = C.read_slots()
    if info is None:
        raise SystemExit('not an ams2kit donor .blend (text block %s missing)' % C.SLOTS_TEXT)
    stored = info['slots']
    os.makedirs(job['dump_dir'], exist_ok=True)
    force = bool(job.get('force'))
    max_verts = int(job.get('max_verts', 65535))
    slot_names = {s['stem'].lower() for s in job['slots']}
    lower = {}
    for o in bpy.data.objects:
        lower.setdefault(o.name.lower(), o)

    def primary(stem):
        o = bpy.data.objects.get(stem) or lower.get(stem.lower())
        if o is not None and o.type in GEOM_TYPES:
            return o
        cands = sorted((x for x in bpy.data.objects if x.get('ams2_slot') == stem and x.type in GEOM_TYPES
                        and x.name.lower() not in slot_names), key=lambda x: x.name)
        return cands[0] if cands else None

    targets = {}
    for o in bpy.data.objects:
        t = o.get('ams2_target')
        if t and o.type in GEOM_TYPES:
            targets.setdefault(str(t).lower(), []).append(o)

    status, objs_of = {}, {}
    for s in job['slots']:
        st = s['stem']
        p = primary(st)
        extra = [o for o in targets.get(st.lower(), []) if o is not p]
        objs = ([p] if p is not None else []) + extra
        objs_of[st] = objs
        if not objs or all(o.type == 'MESH' and len(o.data.polygons) == 0 and not o.modifiers for o in objs):
            status[st] = 'deleted'
        elif (st in stored and p is not None and not extra and p.name == st
              and C.mesh_fingerprint(p) == stored[st]['fp']):
            status[st] = 'unchanged'
        elif st not in stored and p is None and not extra:
            status[st] = 'deleted'
        else:
            status[st] = 'edited'

    def frame_inv(st):
        fr = stored.get(st, {}).get('frame')
        if fr is None:
            return np.eye(4)
        return np.linalg.inv(np.array(fr, dtype=np.float64).reshape(4, 4))

    result = {'slots': {}, 'warnings': []}

    def dump(st, objs, ratio, frame_of):
        r = ratio
        notes = []
        for _ in range(6):
            parts = [object_arrays(o, frame_inv(frame_of), r) for o in objs]
            d, mats, props = merge(parts)
            n = meshweld.welded_count(d)
            if n <= max_verts:
                break
            notes.append('%d vertices > %d: decimated (ratio %.3f)' % (n, max_verts, r * 0.97 * max_verts / n))
            r = r * 0.97 * max_verts / n
        else:
            notes.append('could not get below %d vertices' % max_verts)
        path = os.path.join(job['dump_dir'], st + '.npz')
        np.savez(path, **d)
        with open(path[:-4] + '.json', 'w') as fh:
            json.dump({'mats': mats, 'props': props}, fh)
        return path, r, notes

    # sources first, so a derived LOD can take the source's own (vertex-limit) decimation into account
    eff = {}
    first_pass = [x for x in job['slots'] if x['kind'] != 'lod' or status[x['stem']] != 'unchanged']
    second = [x for x in job['slots'] if x not in first_pass]
    for s in first_pass + second:
        st, kind, srcs = s['stem'], s['kind'], s['sources']
        own = status[st]
        rec = {'status': own, 'objects': [o.name for o in objs_of[st]], 'notes': []}
        action = None
        if kind == 'dmg':
            if force and own != 'deleted' and not s['skinned']:
                action = 'dmg_mesh'
            else:
                action = 'dmg'
        elif s['skinned']:
            src_dead = srcs and all(status.get(x) == 'deleted' for x in srcs)
            if own == 'deleted' or (own == 'unchanged' and src_dead):
                action = 'collapse'
            else:
                action = 'donor'
                if own == 'edited':
                    rec['notes'].append('skinned mesh (bones): rebuilding is not supported, donor mesh kept')
                    result['warnings'].append('%s: skinned mesh edited; donor mesh kept' % st)
        elif own == 'deleted':
            action = 'collapse'
        elif own == 'edited':
            action = 'mesh'
            rec['dump'], rec['ratio'], n = dump(st, objs_of[st], 1.0, st)
            rec['notes'] += n
        elif kind == 'lod' and any(status.get(x) != 'unchanged' for x in srcs):
            live = [x for x in srcs if status.get(x) != 'deleted']
            if not live:
                action = 'collapse'
                rec['notes'].append('source deleted')
            else:
                action = 'mesh'
                rec['derived_from'] = live
                objs = [o for x in live for o in objs_of[x]]
                r0 = float(s['ratio']) * min(eff.get(x, 1.0) for x in live)
                rec['dump'], rec['ratio'], n = dump(st, objs, r0, st)
                rec['notes'] += n
        else:
            action = 'donor'
        if action == 'donor' and force and not s['skinned'] and objs_of[st]:
            action = 'mesh'
            rec['dump'], rec['ratio'], n = dump(st, objs_of[st], 1.0, st)
        if action == 'dmg_mesh':
            rec['dump'], rec['ratio'], n = dump(st, objs_of[st], 1.0, st)
        rec['action'] = action
        if action == 'mesh':
            eff[st] = rec.get('ratio', 1.0)
        result['slots'][st] = rec

    used = {o.name for v in objs_of.values() for o in v}
    guide_prefixes = ('WHEEL_', 'GROUND_guide', 'INFO_', 'FRONT_marker')
    result['unassigned'] = sorted(o.name for o in bpy.data.objects if o.type in GEOM_TYPES and o.name not in used
                                  and not o.name.startswith(guide_prefixes) and not o.hide_render
                                  and o.users_collection)
    if result['unassigned']:
        result['warnings'].append('objects not used by any slot (rename them to a donor object name, join them into '
                                  'one, or set custom property ams2_target): ' + ', '.join(result['unassigned'][:30]))
    with open(job['result'], 'w') as fh:
        json.dump(result, fh, indent=1)


main()
