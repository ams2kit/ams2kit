"""Writer for AMS2 .meb mesh binaries (minor version 4). Companion to meb_read.py.

    python -I meb_write.py --roundtrip DIR       re-encode every donor .meb under DIR, compare bytes
    python -I meb_write.py --bounds DIR          recompute all derived fields (bounds/spheres/min-max)
                                                 from geometry and compare with the stored values
    python -I meb_write.py --obj in.obj out.meb MATERIAL_PATH
                                                 build a new static mesh from an OBJ (see build_from_obj)

The writer can either serialize a parsed Meb verbatim (round-trip) or build one from plain
arrays with build_static_mesh(), which computes every derived field the same way the
original exporter did (verified by --bounds on all donor meshes).
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import meb_read as R  # noqa: E402


def _cstr(s, pad=None):
    b = s.encode('latin-1') + b'\0'
    n = (-len(b)) % 4
    return b + (pad if pad is not None and len(pad) == n else b'\0' * n)


def serialize(m, file_name=None):
    """Serialize a Meb. Streams' raw bytes are written as stored (position stream stays
    encrypted with the key of m.file_name). If file_name differs from m.file_name the
    position stream is re-keyed for the new file name."""
    out = bytearray()
    out += struct.pack('<IBBH', m.version, m.has_bones, m.dyn_env, m.pad)
    out += _cstr(m.name, m.name_pad)
    out += struct.pack('<3i', m.num_verts, len(m.streams), len(m.ibufs))
    out += struct.pack('<4f', *m.sphere)
    out += struct.pack('<6f', *m.aabb)
    if m.has_bones:
        names = b''.join(n.encode('latin-1') + b'\0' for n in m.bone_names)
        raw = m.bone_str_raw if m.bone_str_raw[:len(names)] == names else names + b'\0' * ((-len(names)) % 4)
        out += struct.pack('<2i', len(m.bone_names), len(raw))  # size field = padded length
        out += raw
        for x in m.bone_xforms:
            out += struct.pack('<12f', *x)
    for s in m.streams:
        raw = s.raw
        if s.fmt == R.FMT_ENC_POS and file_name and file_name.lower() != m.file_name.lower():
            raw = R.crypt_positions(R.crypt_positions(raw, m.file_name), file_name)
        out += struct.pack('<3i', s.fmt, s.semantic, s.index) + raw
    for ib in m.ibufs:
        out += _cstr(ib.material, ib.mat_pad)
        out += struct.pack('<2I', ib.flags, len(ib.indices) // 3)
        if m.has_bones:
            out += struct.pack('<I', len(ib.palette)) + struct.pack('<%dH' % len(ib.palette), *ib.palette)
            n = (-2 * len(ib.palette)) % 4
            out += ib.pal_pad if len(ib.pal_pad) == n else b'\0' * n
        out += struct.pack('<%dH' % len(ib.indices), *ib.indices)
        n = (-2 * len(ib.indices)) % 4
        out += ib.idx_pad if len(ib.idx_pad) == n else b'\0' * n
        out += struct.pack('<2H', ib.min_index, ib.max_index)
        out += struct.pack('<4f', *ib.sphere)
        out += struct.pack('<6f', *ib.aabb)
    out += m.trailer
    return bytes(out)


# ---------------------------------------------------------------- derived fields
def _f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def aabb_of(points):
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    return tuple(lo + hi)


def mesh_sphere(points, bb):
    """Header sphere: centre = AABB centre, radius = max distance of a vertex from it."""
    c = [_f32((bb[i] + bb[i + 3]) * 0.5) for i in range(3)]
    r = max(math.sqrt(sum((p[i] - c[i]) ** 2 for i in range(3))) for p in points)
    return (c[0], c[1], c[2], _f32(r))


def ibuf_sphere(bb):
    """Index-buffer 'sphere': centre = sub-mesh AABB centre, w = largest AABB extent."""
    c = [_f32((bb[i] + bb[i + 3]) * 0.5) for i in range(3)]
    w = max(bb[i + 3] - bb[i] for i in range(3))
    return (c[0], c[1], c[2], _f32(w))


def recompute(m):
    """Return dict of recomputed derived fields for a parsed Meb (positions decrypted)."""
    pos = m.decoded(0)
    bb = aabb_of(pos)
    res = {'aabb': bb, 'sphere': mesh_sphere(pos, bb), 'ibufs': []}
    for ib in m.ibufs:
        sub = [pos[i] for i in set(ib.indices)]
        b2 = aabb_of(sub)
        res['ibufs'].append({'aabb': b2, 'sphere': ibuf_sphere(b2),
                             'min': min(ib.indices), 'max': max(ib.indices)})
    return res


# ---------------------------------------------------------------- building new meshes
def build_static_mesh(file_name, name, positions, normals, tangents, binormals, uvs, submeshes,
                      colors=None, dyn_env=1):
    """Build a non-skinned Meb.

    positions/normals/tangents/binormals: lists of 3-tuples in GAME space
        (X = car left, Y = up, Z = rear; front of car is -Z) -- see FINDINGS.md.
    uvs: list of 2-tuples, D3D convention (v = 0 at top of texture).
    submeshes: list of (material_path, [i0, i1, i2, ...]) e.g. 'vehicles\\BYD_Seal\\BYD_SEAL_PAINT.mtx'.
        Triangle order must satisfy (b-a)x(c-a) . normal > 0.
    colors: list of (r, g, b, a) bytes; default white (used as baked AO in donors).
    Stream set mirrors the simplest donor layout (wheel): POSITION(enc) COLOR NORMAL TANGENT
    BINORMAL TEXCOORD0(float2).
    """
    # Donor meshes store each submesh's vertices as one contiguous, disjoint range
    # (min_index..max_index). Reorder (and duplicate shared vertices) to match.
    order, new_subs = [], []
    for mat, idx in submeshes:
        local = {}
        out_idx = []
        for i in idx:
            if i not in local:
                local[i] = len(order)
                order.append(i)
            out_idx.append(local[i])
        new_subs.append((mat, out_idx))
    submeshes = new_subs
    pick = lambda arr: [arr[i] for i in order] if arr is not None else None
    positions, normals, tangents, binormals, uvs, colors = map(pick, (positions, normals, tangents, binormals, uvs, colors))
    nv = len(positions)
    if nv > 65535:
        raise ValueError('u16 indices: split meshes above 65535 vertices')
    m = R.Meb()
    m.file_name = os.path.basename(file_name)
    m.version = 0x01000000
    m.has_bones, m.dyn_env, m.pad = 0, dyn_env, 0
    m.name = name.upper()
    m.num_verts = nv
    pos = [tuple(_f32(c) for c in p) for p in positions]
    bb = aabb_of(pos)
    m.aabb = bb
    m.sphere = mesh_sphere(pos, bb)
    if colors is None:
        colors = [(255, 255, 255, 255)] * nv

    def pack(fmtid, items):
        stride, f = R.FORMATS[fmtid]
        return b''.join(struct.pack(f, *it) for it in items)

    praw = R.crypt_positions(pack(2, pos), m.file_name)
    m.streams = [R.Stream(R.FMT_ENC_POS, 0, 0, praw),
                 R.Stream(4, 6, 0, pack(4, colors)),
                 R.Stream(2, 2, 0, pack(2, normals)),
                 R.Stream(2, 4, 0, pack(2, tangents)),
                 R.Stream(2, 5, 0, pack(2, binormals)),
                 R.Stream(1, 3, 0, pack(1, uvs))]
    for mat, idx in submeshes:
        sub = [pos[i] for i in set(idx)]
        b2 = aabb_of(sub)
        m.ibufs.append(R.IndexBuffer(mat, 0, tuple(idx), min(idx), max(idx), ibuf_sphere(b2), b2))
    return m


def _norm(v):
    l = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / l for c in v)


def compute_tangents(pos, nrm, uv, tris):
    """Per-vertex tangent/binormal from UV gradients (Lengyel), orthogonalized to the normal."""
    tan = [[0.0, 0.0, 0.0] for _ in pos]
    bit = [[0.0, 0.0, 0.0] for _ in pos]
    for t in range(0, len(tris), 3):
        i0, i1, i2 = tris[t:t + 3]
        p0, p1, p2 = pos[i0], pos[i1], pos[i2]
        w0, w1, w2 = uv[i0], uv[i1], uv[i2]
        e1 = [p1[k] - p0[k] for k in range(3)]
        e2 = [p2[k] - p0[k] for k in range(3)]
        s1, t1 = w1[0] - w0[0], w1[1] - w0[1]
        s2, t2 = w2[0] - w0[0], w2[1] - w0[1]
        d = s1 * t2 - s2 * t1
        if abs(d) < 1e-12:
            continue
        r = 1.0 / d
        sd = [(t2 * e1[k] - t1 * e2[k]) * r for k in range(3)]
        td = [(s1 * e2[k] - s2 * e1[k]) * r for k in range(3)]
        for i in (i0, i1, i2):
            for k in range(3):
                tan[i][k] += sd[k]
                bit[i][k] += td[k]
    T, B = [], []
    for i, n in enumerate(nrm):
        t = tan[i]
        dn = sum(t[k] * n[k] for k in range(3))
        t = _norm([t[k] - n[k] * dn for k in range(3)])
        if t == (0.0, 0.0, 0.0) or not any(t):
            t = _norm((1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0))
        b = _norm(bit[i]) if any(bit[i]) else _norm((n[1] * t[2] - n[2] * t[1], n[2] * t[0] - n[0] * t[2], n[0] * t[1] - n[1] * t[0]))
        T.append(t)
        B.append(b)
    return T, B


def read_obj(path):
    """Minimal OBJ reader (triangulated v/vt/vn faces, 'usemtl' groups).
    Returns unique-vertex arrays (pos, nrm, uv) in OBJ space and {material: [indices]}."""
    V, VT, VN = [], [], []
    verts, remap, groups = [], {}, {}
    cur = 'DEFAULT'
    with open(path) as f:
        for line in f:
            sp = line.split()
            if not sp:
                continue
            if sp[0] == 'v':
                V.append(tuple(map(float, sp[1:4])))
            elif sp[0] == 'vt':
                VT.append(tuple(map(float, sp[1:3])))
            elif sp[0] == 'vn':
                VN.append(tuple(map(float, sp[1:4])))
            elif sp[0] == 'usemtl':
                cur = sp[1]
            elif sp[0] == 'f':
                corners = sp[1:]
                ids = []
                for c in corners:
                    if c not in remap:
                        parts = (c.split('/') + ['', ''])[:3]
                        vi = int(parts[0]) - 1
                        ti = int(parts[1]) - 1 if parts[1] else None
                        ni = int(parts[2]) - 1 if parts[2] else None
                        remap[c] = len(verts)
                        verts.append((V[vi], VT[ti] if ti is not None else (0.0, 0.0),
                                      VN[ni] if ni is not None else (0.0, 1.0, 0.0)))
                    ids.append(remap[c])
                g = groups.setdefault(cur, [])
                for k in range(1, len(ids) - 1):  # fan triangulation
                    g += [ids[0], ids[k], ids[k + 1]]
    pos = [v[0] for v in verts]
    uv = [v[1] for v in verts]
    nrm = [_norm(v[2]) for v in verts]
    return pos, nrm, uv, groups


def build_from_obj(obj_path, out_path, material_prefix, blender_axes=True):
    """OBJ -> .meb. With blender_axes=True the OBJ is assumed to come from Blender's OBJ exporter
    with its defaults (forward -Z, up Y => obj = (bx, bz, -by)) for a car modelled in Blender with
    its front towards -Y, up +Z (so car-left is +X). Game space is X = car left, Y = up,
    Z = car rear, so game = (obj x, obj y, -obj z). That is a reflection, so the triangle order is
    reversed to keep (b-a)x(c-a) . normal > 0 as in all donor meshes.
    Each usemtl group becomes one index buffer with material material_prefix + NAME.mtx."""
    pos, nrm, uv, groups = read_obj(obj_path)
    if blender_axes:
        pos = [(p[0], p[1], -p[2]) for p in pos]
        nrm = [(n[0], n[1], -n[2]) for n in nrm]
        for g in groups.values():
            for t in range(0, len(g), 3):
                g[t + 1], g[t + 2] = g[t + 2], g[t + 1]
    uv = [(u, 1.0 - v) for u, v in uv]  # OBJ v-up -> D3D v-down
    all_tris = [i for g in groups.values() for i in g]
    tan, bit = compute_tangents(pos, nrm, uv, all_tris)
    clean = lambda nm: nm.upper()[:-4] if nm.upper().endswith('.MTX') else nm.upper()
    subs = [(material_prefix + clean(name) + '.mtx', g) for name, g in groups.items()]
    fn = os.path.basename(out_path)
    # Donor check: stream semantic 4 ("TANGENT") = +dP/dv, semantic 5 ("BINORMAL") = +dP/du
    m = build_static_mesh(fn, os.path.splitext(fn)[0], pos, nrm, bit, tan, uv, subs)
    data = serialize(m)
    with open(out_path, 'wb') as f:
        f.write(data)
    return m, data


# ---------------------------------------------------------------- CLI
def _walk(d):
    for root, _, files in os.walk(d):
        for fn in sorted(files):
            if fn.lower().endswith('.meb'):
                yield os.path.join(root, fn)


def _close(a, b, tol):
    return all(abs(x - y) <= tol * max(1.0, abs(y)) for x, y in zip(a, b))


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == '--roundtrip':
        ok = bad = 0
        for p in _walk(sys.argv[2]):
            data = open(p, 'rb').read()
            if serialize(R.parse(data, p)) == data:
                ok += 1
            else:
                bad += 1
                print('MISMATCH', p)
        print('byte-identical: %d, mismatched: %d' % (ok, bad))
    elif cmd == '--bounds':
        ok = bad = 0
        for p in _walk(sys.argv[2]):
            m = R.load(p)
            fn = m.file_name.lower()
            if fn.endswith('_dmg.meb') or 'lightglows' in fn:
                continue  # dmg keeps base bounds; flares are expanded in the shader
            rc = recompute(m)
            errs = []
            if not _close(rc['aabb'], m.aabb, 1e-6):
                errs.append('aabb')
            if not _close(rc['sphere'], m.sphere, 1e-5):
                errs.append('sphere %s vs %s' % (rc['sphere'], m.sphere))
            for i, (a, ib) in enumerate(zip(rc['ibufs'], m.ibufs)):
                if not _close(a['aabb'], ib.aabb, 1e-6):
                    errs.append('ib%d aabb' % i)
                if not _close(a['sphere'], ib.sphere, 1e-5):
                    errs.append('ib%d sphere %s vs %s' % (i, a['sphere'], ib.sphere))
                if (a['min'], a['max']) != (ib.min_index, ib.max_index):
                    errs.append('ib%d minmax' % i)
            if errs:
                bad += 1
                print('DIFF', os.path.basename(p), '; '.join(errs)[:300])
            else:
                ok += 1
        print('derived fields reproduced: %d, differ: %d' % (ok, bad))
    elif cmd == '--obj':
        m, data = build_from_obj(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else 'vehicles\\BYD_Seal\\')
        print('wrote %s (%d bytes, %d verts, %d submeshes)' % (sys.argv[3], len(data), m.num_verts, len(m.ibufs)))
