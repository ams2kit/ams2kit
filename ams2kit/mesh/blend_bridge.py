"""Donor car <-> Blender round trip.

    export_donor_blend(mesh_files, out_blend, *, wheel_centres=None, vhf_text=None, blender_exe=None)
        donor .meb files -> donor_<car>.blend (one object per .meb, organised in collections)
    build_from_blend(blend_path, donor_mesh_files, out_dir, *, blender_exe=None)
        edited .blend -> .meb files under the donor's file names (+ manifest.json)

Both run Blender headless with the scripts in ams2kit/blender/. The coordinate convention is documented
in ams2kit/blender/_common.py and docs/04-meshes-and-render.md ("Donor .blend round trip").
"""
import json
import os
import shutil
import struct
import subprocess
import tempfile

import numpy as np

from . import meb_write as W
from . import donor_layout as L
from . import vhf_nodes as V
from . import meshweld

R = W.R  # the meb_read module instance meb_write uses


def find_blender():
    """blender.exe from ams2kit's settings, %AMS2KIT_BLENDER%, Program Files or PATH (ams2kit.game.find_blender)."""
    try:
        from .. import game
        exe = game.find_blender()
    except ImportError:          # mesh package used on its own
        exe = os.environ.get('AMS2KIT_BLENDER') or shutil.which('blender')
    return str(exe) if exe else 'blender'


BLENDER_EXE = find_blender()     # resolved at import; the functions below re-resolve when blender_exe is None
_HERE = os.path.dirname(os.path.abspath(__file__))
AMS2KIT_ROOT = os.path.dirname(os.path.dirname(_HERE))          # folder that contains the ams2kit package
BLENDER_SCRIPTS = os.path.join(os.path.dirname(_HERE), 'blender')
CONVENTION = ('blender = (game.x, game.z, game.y): Blender X = car left, Y = car rear, Z = up '
              '(car front at -Y); a reflection, so triangle winding is reversed')
CORNER_ALIASES = {'FL': 'FL', 'LF': 'FL', 'FR': 'FR', 'RF': 'FR', 'RL': 'RL', 'LR': 'RL', 'RR': 'RR'}
WHITE = (255, 255, 255, 255)
FMT_COMPS = {0: 1, 1: 2, 2: 3, 3: 4}

README = """AMS2KIT donor .blend - how to use it
=====================================
Donor: {donor}
Every object is one mesh file (.meb) of the donor car, named after the file. Units are metres.
Orientation: car front towards -Y (Blender "Front" view, numpad 1), car left at +X, Z up.

What to do
----------
1. REPLACE_Body holds the exterior at full detail (LOD A). Model or import your car here.
   Either (a) delete the donor faces and join your parts INTO the donor object (select your parts, then the
   donor object last so it is active, Ctrl+J) so the object keeps its name and custom properties, or
   (b) delete the donor object and give your own object exactly the donor object's name.
   Several objects can feed one slot: give them the custom property  ams2_target = <slot name>.
2. Materials: every material slot is a donor material (named after its .mtx path). Assign these donor
   materials to your faces (paint, glass, plastic, lights, ...). Your own textures are not supported yet:
   faces with a non-donor material fall back to the slot's first donor material (the build warns).
   Optional custom properties on a material control the extra vertex data of NEW faces:
     ams2_uv0 = "user" (default: your UV map "UVMap") | "fit" (donor-like UVs fitted from position) |
                "u,v" (one fixed donor texel, e.g. for glass and light atlases)
     ams2_tc2 / ams2_tc4 ... = "fit" (default) | "a,b"  (secondary UV sets: livery/AO, fitted from the donor)
     ams2_col = "r,g,b,a" (vertex colour, default white)
3. Wheels: Wheels/Wheel_FL..RR hold rim, tyre, brake disc and caliper per corner, positioned at the
   physics wheel centres (empties WHEEL_FL..RR). Model each corner around its empty.
   Tyres are skinned (bones) and can only be kept or deleted.
4. Deleting an object (or leaving it empty) hides that part in game (its mesh is collapsed).
5. Hidden collections are generated automatically when you do not edit them:
   LODs (lower detail, decimated from LOD A), Damage (_dmg morphs = copy of the base mesh),
   CockpitView (_cpit copies of exterior parts seen from the cockpit). If you edit one of their
   objects, your version is used instead. Cockpit holds the cockpit-pak interior (driver's view).
6. Unchanged objects are written back byte-identical to the donor.
7. Limits: a mesh may not exceed 65535 vertices (after splitting by normals/UVs); bigger meshes are
   decimated automatically. Keep the car within the GROUND_guide footprint: parts far outside the donor's
   bounding spheres may be culled at screen edges (the build reports this).
8. Save as <project>/model/car.blend (literally "car.blend", not your car's name) and run the
   ams2kit build.
"""


# ------------------------------------------------------------------ helpers
def _run_blender(exe, script, job, blend=None, timeout=3600):
    jp = job['_path']
    with open(jp, 'w') as fh:
        json.dump({k: v for k, v in job.items() if k != '_path'}, fh)
    cmd = [exe or find_blender(), '--factory-startup', '--disable-autoexec', '-b'] + ([blend] if blend else []) + \
          ['--python-exit-code', '1', '--python', script, '--', jp]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors='replace')
    if p.returncode != 0 or not os.path.exists(job['result']):
        tail = '\n'.join((p.stdout + '\n' + p.stderr).splitlines()[-40:])
        raise RuntimeError('Blender failed (%s, exit %s):\n%s' % (os.path.basename(script), p.returncode, tail))
    with open(job['result']) as fh:
        return json.load(fh)


def _parse_all(mesh_files):
    out = {}
    for path, data in mesh_files.items():
        if not path.lower().endswith('.meb'):
            continue
        st = L.stem_of(path)
        out[st] = (path, R.parse(data, st + '.meb'), data)
    return out


def _norm_wheels(wc):
    if not wc:
        return {}
    out = {}
    for k, v in wc.items():
        c = CORNER_ALIASES.get(k.upper().replace('WHEEL_', '').replace('_', ''))
        if c is None:
            raise ValueError('unknown wheel corner %r' % k)
        out[c] = [float(x) for x in v]
    return out


def _decode(m):
    """-> dict of numpy arrays for a parsed Meb (positions decrypted, game space, mesh-local)."""
    d = {'pos': np.array(m.decoded(0), np.float64).reshape(-1, 3)}
    if m.stream(2) is not None:
        d['nrm'] = np.array(m.decoded(2), np.float64).reshape(-1, 3)
    for s in m.streams:
        if s.semantic == 3:
            d['tc%d' % s.index] = np.array(m.decoded(3, s.index), np.float64).reshape(m.num_verts, -1)
        elif s.semantic == 6 and s.index == 0:
            d['col'] = np.frombuffer(s.raw, np.uint8).reshape(-1, 4)
        elif s.semantic in (4, 5) and s.index == 0 and s.fmt == 2:
            d['tan%d' % s.semantic] = np.array(m.decoded(s.semantic), np.float64).reshape(-1, 3)
    return d


def _tris(m):
    if not m.ibufs:
        return np.zeros((0, 3), np.int64), np.zeros(0, np.int64)
    tl, gl = [], []
    for g, ib in enumerate(m.ibufs):
        t = np.array(ib.indices, np.int64).reshape(-1, 3)
        tl.append(t)
        gl.append(np.full(len(t), g, np.int64))
    t, g = np.concatenate(tl), np.concatenate(gl)
    ok = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])   # drop degenerate triangles
    return t[ok], g[ok]


def _apply(m16, p):
    M = np.array(m16, np.float64).reshape(4, 4)
    return p @ M[:3, :3].T + M[:3, 3]


def _translation(c, rot16=None):
    M = np.eye(4) if rot16 is None else np.array(rot16, np.float64).reshape(4, 4).copy()
    M[:3, 3] = c
    return [float(x) for x in M.ravel()]


# ------------------------------------------------------------------ export
def export_donor_blend(mesh_files, out_blend, *, wheel_centres=None, vhf_text=None, blender_exe=None,
                       donor_name=None, work_dir=None):
    """Write donor_<car>.blend from the donor's mesh files.

    mesh_files: {pak path: bytes} - every .meb of the main and cockpit paks (other files are ignored).
    wheel_centres: physics wheel centres in game space, {'FL'|'lf'|'WHEEL_FL': (x, y, z), ...}.
        Wheel-corner meshes (rim/tyre/disc/caliper) are placed there; without them the .vhf wheel nodes are used.
    vhf_text: the car's .vhf text (str/bytes), or a list of them (main + cockpit). Supplies node matrices
        (mesh positions are local to their vhf node). Without it every non-wheel mesh sits at the origin.
    Returns a summary dict (objects, collections per mesh, warnings).
    """
    parsed = _parse_all(mesh_files)
    if not parsed:
        raise ValueError('no .meb files given')
    infos = L.classify_all([v[0] for v in parsed.values()])
    texts = vhf_text if isinstance(vhf_text, (list, tuple)) else ([vhf_text] if vhf_text else [])
    nodes = {}
    for t in texts:
        nodes.update(V.node_matrices(t))
    wheels = _norm_wheels(wheel_centres)
    warnings = []
    if not wheels:   # fall back to the vhf hub nodes of the LOD A rims
        for st, i in infos.items():
            if i.role == 'rim' and i.corner and i.lod == 'a' and not i.blur:
                n = nodes.get((st + '.meb').upper())
                if n is not None:
                    wheels[i.corner] = [n[3], n[7], n[11]]
    tri_counts = {st: sum(len(ib.indices) // 3 for ib in v[1].ibufs) for st, v in parsed.items()}
    skinned = {st: bool(v[1].has_bones) for st, v in parsed.items()}
    plan = L.make_plan(infos, tri_counts, skinned)
    donor = donor_name or os.path.splitext(os.path.basename(out_blend))[0].replace('donor_', '')
    work = work_dir or tempfile.mkdtemp(prefix='ams2bl_')
    os.makedirs(work, exist_ok=True)
    meshes = []
    tyre_r = {}
    world_lo, world_hi = np.full(3, 1e9), np.full(3, -1e9)
    corder = [c[0] for c in L.COLLECTIONS]
    cidx = lambda c: corder.index('Wheels') + 0.5 if c.startswith('Wheel_') else corder.index(c)
    for st in sorted(parsed, key=lambda s: (cidx(infos[s].coll), s)):
        path, m, _ = parsed[st]
        i = infos[st]
        key = (st + '.meb').upper()
        frame = nodes.get(key)
        if i.corner and i.corner in wheels:
            frame = _translation(wheels[i.corner], frame)
        if frame is None:
            if texts and not i.corner:
                warnings.append('%s: no vhf node, placed at the origin' % st)
            elif i.corner:
                warnings.append('%s: no wheel centre / vhf node, placed at the origin' % st)
            frame = [float(x) for x in np.eye(4).ravel()]
        d = _decode(m)
        base = m
        if i.dmg and i.base_stem in parsed:
            base = parsed[i.base_stem][1]
        tris, groups = _tris(base)
        if len(tris) and tris.max() >= m.num_verts:
            tris, groups = np.zeros((0, 3), np.int64), np.zeros(0, np.int64)
            warnings.append('%s: base mesh topology does not match, exported as points' % st)
        npz = os.path.join(work, st + '.npz')
        arrs = {'pos': d['pos'], 'tris': tris, 'groups': groups}
        for k, v in d.items():
            if k != 'pos':
                arrs[k] = v
        np.savez(npz, **arrs)
        if i.role == 'tire' and i.corner and i.lod == 'a' and m.num_verts:
            tyre_r[i.corner] = float(np.max(np.hypot(d['pos'][:, 1], d['pos'][:, 2])))
        if i.coll in ('REPLACE_Body', 'Lights', 'Glass') or i.coll.startswith('Wheel_'):
            if m.num_verts:
                wp = _apply(frame, d['pos'])
                world_lo = np.minimum(world_lo, wp.min(0))
                world_hi = np.maximum(world_hi, wp.max(0))
        p = plan[st]
        if p['kind'] == 'dmg':
            note = 'Auto-generated: damage morph = copy of %s (unless the base is unchanged).' % p['sources'][0]
        elif p['kind'] == 'lod':
            note = 'Auto-generated from %s (decimate to %.0f%%) when that is edited; edit this object to override.' % (
                ' + '.join(p['sources']), 100 * p['ratio'])
        elif i.coll == 'REPLACE_Body':
            note = 'REPLACE: model your car here (full detail). LODs/damage/cockpit copies follow automatically.'
        elif i.coll == 'Cockpit':
            note = 'Cockpit-pak mesh (driver view). Kept unless you edit or delete it.'
        else:
            note = 'Kept unless you edit or delete it.'
        if skinned[st]:
            note += ' Skinned (bones): can only be kept or deleted.'
        meshes.append({'stem': st, 'pak_path': path, 'npz': npz, 'coll': i.coll, 'role': i.role, 'frame': frame,
                       'materials': [ib.material for ib in base.ibufs], 'skinned': skinned[st], 'note': note})
    if not np.all(np.isfinite(world_lo)) or world_lo[0] > world_hi[0]:
        world_lo, world_hi = np.array([-1.0, 0, -2.3]), np.array([1.0, 1.3, 2.3])
    # ground plane in Blender coordinates (x, y=game z, z=game y)
    gz = min((c[1] - tyre_r.get(k, 0.33) for k, c in wheels.items()), default=float(world_lo[1]))
    ground = {'cx': float((world_lo[0] + world_hi[0]) / 2), 'cy': float((world_lo[2] + world_hi[2]) / 2),
              'sx': float(world_hi[0] - world_lo[0] + 0.4), 'sy': float(world_hi[2] - world_lo[2] + 0.4), 'z': float(gz)}
    info = ['Donor: %s' % donor]
    if all(k in wheels for k in ('FL', 'FR', 'RL', 'RR')):
        wb = (wheels['RL'][2] + wheels['RR'][2] - wheels['FL'][2] - wheels['FR'][2]) / 2
        info.append('Wheelbase %.3f m, track F %.3f / R %.3f m' % (wb, abs(wheels['FL'][0] - wheels['FR'][0]),
                                                                    abs(wheels['RL'][0] - wheels['RR'][0])))
    info.append('Donor exterior %.2f x %.2f x %.2f m (W x H x L)' % tuple(world_hi - world_lo))
    info += ['Model your car in REPLACE_Body (+ Lights, Glass, Wheels).', 'Keep object names; assign donor materials.',
             'Read the text block AMS2KIT_README (Scripting tab).']
    job = {'_path': os.path.join(work, 'export_job.json'), 'result': os.path.join(work, 'export_result.json'),
           'out_blend': os.path.abspath(out_blend), 'donor': donor, 'convention': CONVENTION,
           'collections': [list(c) for c in L.COLLECTIONS], 'wheel_collections': L.WHEEL_COLLECTIONS,
           'meshes': meshes, 'wheels': wheels, 'tyre_radius': tyre_r, 'ground': ground, 'info': '\n'.join(info),
           'readme': README.format(donor=donor)}
    if os.path.exists(job['result']):
        os.remove(job['result'])
    res = _run_blender(blender_exe, os.path.join(BLENDER_SCRIPTS, 'export_donor.py'), job)
    if not work_dir:
        shutil.rmtree(work, ignore_errors=True)
    res['warnings'] = warnings
    res['collections'] = {m['stem']: m['coll'] for m in meshes}
    res['wheels'] = wheels
    return res


# ------------------------------------------------------------------ build helpers
def collapsed(donor):
    """Hide a donor mesh: every vertex moved to the sphere centre (all triangles zero-area).
    Streams, bones, index buffers and bounds stay the donor's."""
    c = tuple(W._f32(x) for x in donor.sphere[:3])
    raw = struct.pack('<3f', *c) * donor.num_verts
    for s in donor.streams:
        if s.semantic == 0 and s.index == 0:
            s.raw = R.crypt_positions(raw, donor.file_name) if s.fmt == R.FMT_ENC_POS else raw
    return donor


def as_dmg(base, dmg_name, header_from=None):
    """Damage morph = base vertex data, 0 index buffers, base bounds, keyed to the _dmg file name."""
    d = R.Meb()
    d.__dict__.update({k: v for k, v in base.__dict__.items() if k not in ('streams', 'ibufs', 'file_name')})
    d.file_name = dmg_name
    d.ibufs = []
    d.streams = []
    if header_from is not None:
        d.sphere, d.aabb = header_from.sphere, header_from.aabb
    for s in base.streams:
        raw = s.raw
        if s.fmt == R.FMT_ENC_POS:
            raw = R.crypt_positions(R.crypt_positions(raw, base.file_name), dmg_name)
        d.streams.append(R.Stream(s.fmt, s.semantic, s.index, raw))
    return d


def tangents_np(pos, nrm, uv, tris):
    """Vectorised numpy port of meb_write.compute_tangents (same maths: Lengyel, orthogonalised).
    Returns (T, B) = (dP/du, dP/dv) per vertex."""
    pos = np.asarray(pos, np.float64)
    nrm = np.asarray(nrm, np.float64)
    uv = np.asarray(uv, np.float64)
    t = np.asarray(tris, np.int64).reshape(-1, 3)
    n = len(pos)
    tan = np.zeros((n, 3))
    bit = np.zeros((n, 3))
    if len(t):
        p0, p1, p2 = pos[t[:, 0]], pos[t[:, 1]], pos[t[:, 2]]
        w0, w1, w2 = uv[t[:, 0]], uv[t[:, 1]], uv[t[:, 2]]
        e1, e2 = p1 - p0, p2 - p0
        s1, t1 = w1[:, 0] - w0[:, 0], w1[:, 1] - w0[:, 1]
        s2, t2 = w2[:, 0] - w0[:, 0], w2[:, 1] - w0[:, 1]
        d = s1 * t2 - s2 * t1
        ok = np.abs(d) >= 1e-12
        r = np.zeros_like(d)
        r[ok] = 1.0 / d[ok]
        sd = (t2[:, None] * e1 - t1[:, None] * e2) * r[:, None]
        td = (s1[:, None] * e2 - s2[:, None] * e1) * r[:, None]
        sd[~ok] = 0
        td[~ok] = 0
        for k in range(3):
            np.add.at(tan, t[:, k], sd)
            np.add.at(bit, t[:, k], td)
    dn = np.sum(tan * nrm, axis=1)
    T = tan - nrm * dn[:, None]
    lt = np.linalg.norm(T, axis=1)
    bad = lt < 1e-300
    T[~bad] /= lt[~bad, None]
    if bad.any():
        fb = np.where((np.abs(nrm[bad, 0]) < 0.9)[:, None], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
        T[bad] = fb
    lb = np.linalg.norm(bit, axis=1)
    B = np.zeros_like(bit)
    okb = lb > 0
    B[okb] = bit[okb] / lb[okb, None]
    if (~okb).any():
        c = np.cross(nrm[~okb], T[~okb])
        lc = np.linalg.norm(c, axis=1)
        lc[lc == 0] = 1.0
        B[~okb] = c / lc[:, None]
    return T, B


class _Template:
    """Donor mesh used as template: stream layout + statistics to fill streams for new geometry."""

    def __init__(self, m):
        self.m = m
        self.pos = np.array(m.decoded(0), np.float64).reshape(-1, 3) if m.num_verts else np.zeros((0, 3))
        self.tc = {}
        for s in m.streams:
            if s.semantic == 3:
                self.tc[s.index] = np.array(m.decoded(3, s.index), np.float64).reshape(m.num_verts, -1)
        col = m.stream(6)
        self.col = np.frombuffer(col.raw, np.uint8).reshape(-1, 4) if col is not None else None
        self.mat_verts = {}
        for ib in m.ibufs:
            self.mat_verts.setdefault(ib.material.lower(), set()).update(ib.indices)
        self._fits = {}
        # light control: on lamp faces one TEXCOORD stream holds (light id, value) instead of a UV, e.g. the
        # Virtus tail lamps (7/8), reverse (9/10), third brake light (12). The game lights faces by that id.
        self.light_ids = {}          # k -> (N,) bool: donor vertices carrying a light id in TEXCOORDk
        self.lights = {}             # k -> {id: (centroid xyz, value)}
        for k, v in self.tc.items():
            if v.shape[1] < 2:
                continue
            is_id = (np.abs(v[:, 0] - np.round(v[:, 0])) < 1e-4) & (v[:, 0] >= 1) & (v[:, 0] <= 30) & (v[:, 1] < 0)
            if is_id.any():
                self.light_ids[k] = is_id
                ids = np.round(v[is_id, 0]).astype(int)
                self.lights[k] = {int(i): (self.pos[is_id][ids == i].mean(0), float(np.median(v[is_id, 1][ids == i])))
                                  for i in np.unique(ids)}

    def light_value(self, k, mask, p):
        """(id, value) for a new lamp vertex at p: among the candidate ids in mask, the donor lamp nearest p
        (so a left/right id pair resolves by side). None when this donor mesh has none of those ids."""
        cand = [(np.sum((c - p) ** 2), i, val) for i, (c, val) in self.lights.get(k, {}).items() if mask >> i & 1]
        return min(cand)[1:] if cand else None

    def nearest_plain(self, mtx, k, p):
        """TEXCOORDk of the nearest donor vertex of mtx that is not a lamp (no light id), for new faces of a
        light-controlled material that are not lamps: a straight-line fit of ids would give fractional ids."""
        sel = self.sel(mtx)
        sel = sel[~self.light_ids[k][sel]]
        if not len(sel):
            return None
        P, out = self.pos[sel], np.zeros((len(p), self.tc[k].shape[1]))
        for a in range(0, len(p), 512):
            d2 = ((p[a:a + 512, None, :] - P[None, :, :]) ** 2).sum(-1)
            out[a:a + 512] = self.tc[k][sel[d2.argmin(1)]]
        return out

    def sel(self, mtx):
        s = self.mat_verts.get(mtx.lower())
        if s:
            return np.array(sorted(s), np.int64)
        return np.arange(self.m.num_verts)

    def fit(self, mtx, k, comps):
        """Predictor pos -> TEXCOORDk for new vertices with material mtx: per component either the donor's
        constant value or a least-squares linear fit on position (clamped to the donor's range)."""
        key = (mtx.lower(), k, comps)
        if key in self._fits:
            return self._fits[key]
        vals = self.tc.get(k)
        sel = self.sel(mtx)
        if vals is None or len(sel) == 0:
            f = lambda p: np.zeros((len(p), comps))
        else:
            Vv = np.zeros((len(sel), comps))
            c = min(comps, vals.shape[1])
            Vv[:, :c] = vals[sel, :c]
            P = self.pos[sel]
            lo, hi = Vv.min(0), Vv.max(0)
            const = np.median(Vv, axis=0)
            X = np.hstack([P, np.ones((len(P), 1))])
            coef = np.linalg.lstsq(X, Vv, rcond=None)[0] if len(P) >= 4 else None
            flat = (hi - lo) < 1e-3

            def f(p, coef=coef, const=const, lo=lo, hi=hi, flat=flat):
                out = np.tile(const, (len(p), 1))
                if coef is not None and not flat.all():
                    pr = np.clip(np.hstack([p, np.ones((len(p), 1))]) @ coef, lo, hi)
                    out[:, ~flat] = pr[:, ~flat]
                return out
        self._fits[key] = f
        return f

    def alpha(self, mtx):
        if self.col is None or not self.m.num_verts:
            return 255
        return int(np.median(self.col[self.sel(mtx), 3]))


def _np_aabb(p):
    return tuple(float(x) for x in np.concatenate([p.min(0), p.max(0)]))


def _np_mesh_sphere(p, bb):
    c = [W._f32((bb[i] + bb[i + 3]) * 0.5) for i in range(3)]
    r = float(np.sqrt(((p - np.array(c)) ** 2).sum(1)).max())
    return (c[0], c[1], c[2], W._f32(r))


def build_meb_from_dump(tmpl, d, meta, out_name, warnings):
    """Build a static (non-skinned) Meb from a Blender dump using a donor template's stream layout.
    Returns None when the dump has no triangles."""
    m0 = tmpl.m
    first, inv = meshweld.weld(d)
    nv = len(first)
    if nv == 0:
        return None
    if nv > 65535:
        raise ValueError('%s: %d vertices > 65535 after welding' % (out_name, nv))
    mats = list(meta['mats'])
    props = meta.get('props', {})
    fallback = m0.ibufs[0].material if m0.ibufs else None
    for gi, mt in enumerate(mats):
        if mt.startswith('?'):
            fb = fallback or 'vehicles\\unknown\\UNKNOWN.mtx'
            warnings.append('%s: material %s is not a donor material -> %s' % (out_name, mt[1:], fb))
            mats[gi] = fb
    tmpl_mats = {ib.material.lower() for ib in m0.ibufs}
    for mt in set(mats) - set(x for x in mats if x.lower() in tmpl_mats):
        if tmpl_mats and np.any(np.asarray(d['mat']) == mats.index(mt)):
            # another slot's material: the slot keeps its own vertex streams, which may lack what that
            # material's shader reads (Jetta: paint in the underface slot, no TEXCOORD2/4 -> rendered black)
            warnings.append('%s: material %s is not used by this donor slot (stream layout may not suit it)'
                            % (out_name, mt.rsplit(chr(92), 1)[-1]))
    tri_mat = np.asarray(d['mat'], np.int64)
    tri_idx = inv.reshape(-1, 3)
    vmat = np.repeat(tri_mat, 3)[first]
    pos = np.asarray(d['pos'], np.float64)[first].astype(np.float32).astype(np.float64)
    nrm = np.asarray(d['nrm'], np.float64)[first]
    nl = np.linalg.norm(nrm, axis=1)
    nl[nl < 1e-12] = 1.0
    nrm = nrm / nl[:, None]
    donor = np.asarray(d['donor'])[first] > 0
    uv0 = np.asarray(d['uv0'], np.float64)[first]
    uv0 = np.stack([uv0[:, 0], 1.0 - uv0[:, 1]], 1)               # Blender v-up -> D3D v-down

    def stored_tc(k, comps):
        """(values, available) for TEXCOORDk from the stored Blender layers."""
        out = np.zeros((nv, comps))
        ok = True
        if comps >= 2:
            if k == 0:
                out[:, :2] = uv0
            elif 'uv:TEXCOORD%d' % k in d:
                a = np.asarray(d['uv:TEXCOORD%d' % k], np.float64)[first]
                out[:, 0], out[:, 1] = a[:, 0], 1.0 - a[:, 1]
            else:
                ok = False
            if comps >= 3:
                if 'attr:TEXCOORD%d_W' % k in d:
                    out[:, 2] = np.asarray(d['attr:TEXCOORD%d_W' % k], np.float64)[first]
                else:
                    ok = False
        else:
            if 'attr:TEXCOORD%d' % k in d:
                out[:, 0] = np.asarray(d['attr:TEXCOORD%d' % k], np.float64)[first]
            else:
                ok = False
        return out, ok

    lamp = np.asarray(d['light'], np.int64)[first] if 'light' in d else np.zeros(nv, np.int64)
    missing_lights = set()
    tcs = {}
    for s in m0.streams:
        if s.semantic != 3:
            continue
        k, comps = s.index, FMT_COMPS[s.fmt]
        vals, ok = stored_tc(k, comps)
        fill = ~donor if ok else np.ones(nv, bool)
        if fill.any():
            for g in np.unique(vmat[fill]):
                sel = fill & (vmat == g)
                mtx = mats[g]
                pr = props.get(mtx, {})
                pred = tmpl.fit(mtx, k, comps)(pos[sel])
                mode = pr.get('tc%d' % k, pr.get('uv0', 'user') if k == 0 else 'fit').strip().lower()
                if mode == 'user' and k == 0:
                    pred[:, :2] = uv0[sel]                       # the user's own UVs
                elif mode not in ('fit', 'user'):
                    cv = _floats(mode, out_name, mtx, warnings)
                    if cv:
                        pred[:, :min(len(cv), comps)] = cv[:comps]
                if k in tmpl.light_ids and mode == 'fit':
                    lit = lamp[sel] > 0
                    if tmpl.light_ids[k][tmpl.sel(mtx)].any() and (~lit).any():
                        near = tmpl.nearest_plain(mtx, k, pos[sel][~lit])
                        if near is not None:
                            pred[~lit, :near.shape[1]] = near[:, :comps]
                    for j in np.flatnonzero(lit):
                        lv = tmpl.light_value(k, int(lamp[sel][j]), pos[sel][j])
                        if lv is None:
                            missing_lights.add(int(lamp[sel][j]))
                        else:
                            pred[j, :2] = lv
                vals[sel] = pred
        tcs[k] = vals
    if missing_lights:
        warnings.append('%s: light ids %s are not in this donor slot (lamp faces left unlit)' % (
            out_name, sorted({i for m_ in missing_lights for i in range(31) if m_ >> i & 1})))
    if 0 in tcs:
        uv_t = tcs[0][:, :2]
    else:
        uv_t = uv0
    col = np.tile(np.array(WHITE, np.uint8), (nv, 1))
    if m0.stream(6) is not None:
        for g in np.unique(vmat):
            col[vmat == g, 3] = tmpl.alpha(mats[g])
        for g in np.unique(vmat):
            cv = props.get(mats[g], {}).get('col')
            cv = _floats(cv, out_name, mats[g], warnings) if cv else None
            if cv:
                col[vmat == g] = np.clip(np.round((cv + [255.0] * 4)[:4]), 0, 255).astype(np.uint8)
        if 'col' in d:
            c = np.asarray(d['col'], np.uint8)[first]
            col[donor] = c[donor]
    T, B = tangents_np(pos, nrm, uv_t, tri_idx.ravel())
    if 'tanok' in d and len(d['tanok']):
        keep = (np.asarray(d['tanok'])[first] > 0) & donor        # unmoved donor vertices: donor tangent frame
        B[keep] = np.asarray(d['tan4'], np.float64)[first][keep]   # semantic 4
        T[keep] = np.asarray(d['tan5'], np.float64)[first][keep]   # semantic 5
    m = R.Meb()
    m.file_name = out_name
    m.version, m.has_bones, m.dyn_env, m.pad = m0.version, 0, m0.dyn_env, m0.pad
    m.name = m0.name
    m.num_verts = nv
    bb = _np_aabb(pos)
    m.aabb = bb
    m.sphere = _np_mesh_sphere(pos, bb)
    for s in m0.streams:
        sem = s.semantic
        if sem == 0:
            raw = pos.astype('<f4').tobytes()
            if s.fmt == R.FMT_ENC_POS:
                raw = R.crypt_positions(raw, out_name)
        elif sem == 2:
            raw = nrm.astype('<f4').tobytes()
        elif sem == 4:
            raw = B.astype('<f4').tobytes()      # donor convention: "TANGENT" = +dP/dv
        elif sem == 5:
            raw = T.astype('<f4').tobytes()      # "BINORMAL" = +dP/du
        elif sem == 6:
            raw = col.astype(np.uint8).tobytes()
        elif sem == 3:
            raw = tcs[s.index].astype('<f4').tobytes()
        else:
            raise ValueError('%s: template stream semantic %d (skinning) cannot be built' % (out_name, sem))
        if s.fmt in FMT_COMPS and sem in (2, 4, 5) and FMT_COMPS[s.fmt] != 3:
            raise ValueError('%s: unexpected format %d for semantic %d' % (out_name, s.fmt, sem))
        m.streams.append(R.Stream(s.fmt, sem, s.index, raw))
    flare = 'lightglows' in out_name.lower()      # quads expanded by the shader: keep the donor's bounds
    if flare and _contains(m0.aabb, bb):
        m.aabb, m.sphere = m0.aabb, m0.sphere
    tib = {ib.material.lower(): ib for ib in m0.ibufs}
    for g in range(len(mats)):
        sel = tri_mat == g
        if not sel.any():
            continue
        ix = tri_idx[sel].ravel()
        sub = pos[np.unique(ix)]
        b2 = _np_aabb(sub)
        sph = W.ibuf_sphere(b2)
        t = tib.get(mats[g].lower())
        if flare and t is not None and _contains(t.aabb, b2):
            b2, sph = t.aabb, t.sphere
        m.ibufs.append(R.IndexBuffer(mats[g], 0, tuple(int(x) for x in ix), int(ix.min()), int(ix.max()), sph, b2))
    return m


def _floats(text, out_name, mtx, warnings):
    try:
        return [float(x) for x in text.replace(';', ',').split(',') if x.strip()]
    except ValueError:
        warnings.append('%s: material %s: cannot parse custom value %r' % (out_name, mtx, text))
        return None


def _map_lod_materials(meta, tmpl, lod_key):
    """Derived LOD: use the template's LOD-specific variant of a material when it has one
    (e.g. ..._RIM.mtx -> ..._RIM_LODC.mtx in a *_lodc mesh)."""
    tm = [ib.material for ib in tmpl.m.ibufs]
    tl = {m.lower() for m in tm}
    out = []
    for m in meta['mats']:
        if m.lower() in tl or m.startswith('?') or not lod_key:
            out.append(m)
            continue
        base = m[:-4] if m.lower().endswith('.mtx') else m
        cand = [t for t in tm if t.lower().startswith(base.lower() + '_') and lod_key.lower() in t.lower()]
        out.append(cand[0] if cand else m)
    meta = dict(meta)
    meta['mats'] = out
    return meta


def _contains(outer, inner, tol=1e-6):
    return all(outer[i] <= inner[i] + tol for i in range(3)) and all(outer[i] >= inner[i] - tol for i in range(3, 6))


def _load_json(path):
    with open(path) as fh:
        return json.load(fh)


def _load_npz(path):
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


def _sphere_excess(new, old):
    """How far (m) the new mesh's bounding sphere pokes outside the donor's (== the .vhf culling sphere)."""
    dc = np.linalg.norm(np.array(new[:3]) - np.array(old[:3]))
    return float(dc + new[3] - old[3])


# ------------------------------------------------------------------ build
def build_from_blend(blend_path, donor_mesh_files, out_dir, *, blender_exe=None, force_rebuild=False,
                     include_unchanged=False, work_dir=None, keep_dump=False):
    """Build .meb files from an edited donor .blend.

    donor_mesh_files: {pak path: bytes}, the same donor files the .blend was exported from (templates).
    out_dir: files are written to out_dir/<pak path>, plus out_dir/manifest.json (details per file).
    force_rebuild: rebuild every non-skinned mesh from the Blender data even if unchanged (for testing).
    include_unchanged: also list unchanged donor files in the returned dict (they are written either way).
    Returns {pak path: output file} for every file that differs from the donor (all files if include_unchanged).
    """
    parsed = _parse_all(donor_mesh_files)
    infos = L.classify_all([v[0] for v in parsed.values()])
    tri_counts = {st: sum(len(ib.indices) // 3 for ib in v[1].ibufs) for st, v in parsed.items()}
    skinned = {st: bool(v[1].has_bones) for st, v in parsed.items()}
    plan = L.make_plan(infos, tri_counts, skinned)
    work = work_dir or tempfile.mkdtemp(prefix='ams2bb_')
    os.makedirs(work, exist_ok=True)
    job = {'_path': os.path.join(work, 'build_job.json'), 'result': os.path.join(work, 'build_result.json'),
           'dump_dir': os.path.join(work, 'dump'), 'force': bool(force_rebuild), 'max_verts': 65535,
           'ams2kit_root': AMS2KIT_ROOT,
           'slots': [dict(stem=st, **plan[st]) for st in sorted(parsed)]}
    if os.path.exists(job['result']):
        os.remove(job['result'])
    res = _run_blender(blender_exe, os.path.join(BLENDER_SCRIPTS, 'import_blend.py'), job,
                       blend=os.path.abspath(blend_path))
    warnings = list(res.get('warnings', []))
    manifest = {'blend': os.path.abspath(blend_path), 'files': {}, 'warnings': warnings,
                'unassigned_objects': res.get('unassigned', [])}
    built = {}
    outputs = {}
    order = sorted(parsed, key=lambda s: (plan[s]['kind'] == 'dmg', s))
    for st in order:
        path, donor_m, donor_bytes = parsed[st]
        rec = res['slots'].get(st, {'action': 'donor', 'status': 'missing'})
        action = rec['action']
        fname = path.replace('/', '\\').split('\\')[-1]
        notes = list(rec.get('notes', []))
        meb = None
        data = None
        try:
            if action == 'donor':
                data = donor_bytes
            elif action == 'collapse':
                meb = collapsed(R.parse(donor_bytes, fname))
            elif action == 'mesh':
                d = _load_npz(rec['dump'])
                meta = _load_json(rec['dump'][:-4] + '.json')
                tmpl = _Template(donor_m)
                if rec.get('derived_from'):
                    meta = _map_lod_materials(meta, tmpl, 'lod' + infos[st].lod if infos[st].lod else '')
                meb = build_meb_from_dump(tmpl, d, meta, fname, notes)
                if meb is None:
                    meb = collapsed(R.parse(donor_bytes, fname))
                    notes.append('no triangles -> collapsed')
                    action = 'collapse'
                else:
                    built[st] = meb
            elif action in ('dmg', 'dmg_mesh'):
                base = plan[st]['sources'][0] if plan[st]['sources'] else None
                base_act = outputs.get(base, {}).get('action')
                if action == 'dmg_mesh':
                    d = _load_npz(rec['dump'])
                    meta = _load_json(rec['dump'][:-4] + '.json')
                    mm = build_meb_from_dump(_Template(parsed[base][1] if base else donor_m), d, meta, fname, notes)
                    hdr = built.get(base) or (parsed[base][1] if base else donor_m)
                    if mm is not None and mm.num_verts == donor_m.num_verts:
                        meb = as_dmg(mm, fname, header_from=hdr)
                        built[st] = meb
                    else:
                        notes.append('damage object topology changed; using donor damage mesh')
                        data = donor_bytes
                elif base in built:
                    meb = as_dmg(built[base], fname)
                    notes.append('copy of rebuilt %s (no deformation)' % base)
                elif base_act == 'collapse':
                    meb = collapsed(R.parse(donor_bytes, fname))
                    action = 'collapse'
                else:
                    data = donor_bytes
                    action = 'donor'
        except Exception as e:  # keep going: report, keep the donor file
            notes.append('ERROR: %s; donor mesh kept' % e)
            warnings.append('%s: %s' % (st, e))
            data, meb, action = donor_bytes, None, 'donor'
        if data is None:
            data = W.serialize(meb)
        dst = os.path.join(out_dir, *path.replace('/', '\\').split('\\'))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, 'wb') as fh:
            fh.write(data)
        chk = R.parse(data, fname)
        probs, _ = R.check(chk)
        if action == 'collapse':
            probs = [p for p in probs if 'aabb' not in p]
        excess = _sphere_excess(chk.sphere, donor_m.sphere) if action not in ('donor', 'collapse') else 0.0
        if excess > 0.02:
            notes.append('bounding sphere exceeds the donor/.vhf culling sphere by %.3f m' % excess)
            if not infos[st].dmg:
                warnings.append('%s: exceeds the .vhf culling sphere by %.3f m (may pop out at screen edges)'
                                % (st, excess))
        entry = {'file': dst, 'action': action, 'status': rec.get('status'), 'verts': chk.num_verts,
                 'tris': sum(len(ib.indices) for ib in chk.ibufs) // 3, 'materials': [ib.material for ib in chk.ibufs],
                 'aabb': [round(x, 5) for x in chk.aabb], 'sphere': [round(x, 5) for x in chk.sphere],
                 'donor_sphere': [round(x, 5) for x in donor_m.sphere], 'sphere_excess_m': round(excess, 4),
                 'cockpit_pak': infos[st].cpit, 'derived_from': rec.get('derived_from'),
                 'reader_check': probs or 'OK', 'notes': notes}
        outputs[st] = entry
        manifest['files'][path] = entry
    with open(os.path.join(out_dir, 'manifest.json'), 'w') as fh:
        json.dump(manifest, fh, indent=1)
    if not work_dir and not keep_dump:
        shutil.rmtree(work, ignore_errors=True)
    return {parsed[st][0]: e['file'] for st, e in outputs.items()
            if include_unchanged or e['action'] != 'donor'}


def render_preview(blend_path, out_png, *, view='front34', blender_exe=None, timeout=600):
    """Render a Workbench preview PNG of a .blend (visible collections only). view: front34|rear34|side|top|cockpit:x,y,z[,yaw] (game-space eye)."""
    out_png = os.path.abspath(out_png)
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    cmd = [blender_exe or find_blender(), '--factory-startup', '--disable-autoexec', '-b', os.path.abspath(blend_path),
           '--python-exit-code', '1', '--python', os.path.join(BLENDER_SCRIPTS, 'render_preview.py'), '--',
           out_png, view]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors='replace')
    if p.returncode != 0 or not os.path.exists(out_png):
        raise RuntimeError('preview render failed:\n' + '\n'.join((p.stdout + p.stderr).splitlines()[-30:]))
    return out_png


# ------------------------------------------------------------------ fit a user model into a donor .blend
FIT_DEFAULTS = {
    'exterior_root': None,        # model object whose hierarchy is the exterior (or list 'exterior_objects')
    'exterior_objects': None,
    'exterior_exclude': [],       # e.g. interior objects under the root
    'wheel_objects': None,        # {'FL': name, 'FR': ..., 'RL': ..., 'RR': ...} (front of the model at -Y)
    'tyre_materials': [],         # model materials of the tyres (wheel centres = their bbox centre)
    'rim_materials': [],          # model materials that make up the rim (the rest of each wheel is dropped)
    'rim_custom_material': None,  # NAME of a car material (custom_materials) for the rims: they keep their UVs
    'material_classes': {},       # model material -> PAINT|GLASS|PLASTIC|GLOSS|LIGHT|SKIP|CUSTOM:<NAME> (unknown: guessed)
    'custom_materials': {},       # {NAME: car-owned .mtx path} (materials.mtx_paths): CUSTOM:<NAME> faces keep their UVs
    'scale': None,                # None: from the wheelbase (model wheels onto the WHEEL_* empties)
    'rim_fit': 'tyre',            # 'tyre': rim radius = donor tyre inner radius + flange overlap; 'donor_rim'
    'rim_flange_overlap': 0.005,
    'donor_materials': {},        # class -> donor .mtx (base name or path) to override the automatic choice
    'uv_hints': {},               # class -> {material custom prop: value|'auto'} (default: glass/light/rim auto)
    'hide_cockpit_body': True, 'hide_cockpit_glass': True, 'hide_cockpit_extanim': True,
    'extra_hide': [], 'keep': [], 'skip_prefixes': ['WGT-'],
    'rotate_z_deg': 0.0,          # turn the model about Z first; 0 + auto_orient: 180 when it faces +Y (glTF)
    'auto_orient': True,
    'part_slots': {},             # {model object pattern: donor body object}: spread a big body over several slots
    'split_sides': [],            # model object patterns split into <name>@L / <name>@R (left = +X) for part_slots
    'light_ids': {},              # model material -> donor light id(s) its faces switch with (brake, reverse...);
                                  # a list (e.g. [7, 8]) resolves left/right by the nearest donor lamp (docs/04)
    'cockpit_body': {},           # {donor *_cpit object: {objects: [patterns], min_z: m}}: body seen from the seat
    'interior': None,             # optional: model interior -> donor interior/cockpit slots (fit_model.fit_interior)
}


def fit_model_into_donor(donor_blend, model_blend, out_blend, *, config=None, scale=None, wheel_objects=None,
                         material_classes=None, rim_fit=None, blender_exe=None, work_dir=None, timeout=1800,
                         texels=None, custom_materials=None):
    """Put a car model (any .blend, front at -Y, Z up, metres) into an exported donor .blend and save out_blend.

    config: dict or path of a JSON file with the model-specific inputs (keys: FIT_DEFAULTS); keyword arguments
    override it. The model .blend is only appended from (never written). Returns the fit log
    (scale, wheel fit error, donor objects/materials picked, texture hints, rim scales, hidden donor parts)."""
    cfg = dict(FIT_DEFAULTS)
    if isinstance(config, str):
        with open(config) as fh:
            config = json.load(fh)
    cfg.update(config or {})
    for k, v in (('scale', scale), ('wheel_objects', wheel_objects), ('material_classes', material_classes),
                 ('rim_fit', rim_fit), ('custom_materials', custom_materials)):
        if v is not None:
            cfg[k] = v
    work = work_dir or tempfile.mkdtemp(prefix='ams2fit_')
    os.makedirs(work, exist_ok=True)
    job = {'_path': os.path.join(work, 'fit_job.json'), 'result': os.path.join(work, 'fit_result.json'),
           'model_blend': os.path.abspath(model_blend), 'out_blend': os.path.abspath(out_blend), 'config': cfg,
           # texture-checked texels per donor material (mesh.texels.donor_texels); without them new faces use the
           # donor's most common UV, which can be any colour of a shared atlas (red glass on the Jetta)
           'texels': (json.load(open(texels)) if isinstance(texels, str) else texels) or {}}
    if os.path.exists(job['result']):
        os.remove(job['result'])
    if os.path.abspath(out_blend).lower() == os.path.abspath(model_blend).lower():
        raise ValueError('out_blend must not be the model file')
    res = _run_blender(blender_exe, os.path.join(BLENDER_SCRIPTS, 'fit_model.py'), job,
                       blend=os.path.abspath(donor_blend), timeout=timeout)
    if not work_dir:
        shutil.rmtree(work, ignore_errors=True)
    return res


def visual_wheel_centres(vhf_text, donor_physics_centres=None, new_physics_centres=None):
    """Wheel centres in the VISUAL (mesh/.vhf) frame: the donor's vhf hub nodes of the LOD A rims, moved by
    how much the new geometry differs from the donor's physics (new - donor, per corner).

    Some donors' physics frame is offset from their visual frame (Camaro SS: physics wheel centres at
    y = 0.2185, vhf hubs at y = 0.35, and ~0.1 m apart along Z), so the physics points must not be used
    directly as WHEEL_* markers. For the Veneno both frames coincide."""
    texts = vhf_text if isinstance(vhf_text, (list, tuple)) else [vhf_text]
    nodes = {}
    for t in texts:
        nodes.update(V.node_matrices(t))
    out = {}
    for fn, m in nodes.items():
        i = L.MeshInfo(fn[:-4].lower())
        if i.role == 'rim' and i.corner and i.lod == 'a' and not i.blur and not i.dmg:
            out[i.corner] = [m[3], m[7], m[11]]
    if donor_physics_centres and new_physics_centres:
        dp, npc = _norm_wheels(donor_physics_centres), _norm_wheels(new_physics_centres)
        for c in out:
            if c in dp and c in npc:
                out[c] = [out[c][k] + npc[c][k] - dp[c][k] for k in range(3)]
    return out
