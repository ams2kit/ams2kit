"""Reader for Automobilista 2 / Madness-engine .meb mesh binaries (version minor 4).

Usage:
    python -I meb_read.py file.meb [out.obj]        # parse, print summary, export OBJ
    python -I meb_read.py --scan DIR                 # parse every .meb under DIR (sanity check)

Layout (see FINDINGS.md):
    u32 version (BVersion bitfield; AMS2 = 0x01000000 -> minor 4)
    u8 hasBones, u8 dynamicEnvMapRequired, u16 pad
    char name[] (NUL-terminated, then pad to 4)
    i32 numVerts, i32 numStreams, i32 numIndexBuffers
    f32 boundSphere[4] (cx, cy, cz, r)
    f32 aabbMin[3], aabbMax[3]
    [if hasBones: i32 nBones, i32 namesSize, names, 48 bytes per bone] (tyres, wipers)
    numStreams x { i32 format, i32 semantic, i32 semanticIndex, data[numVerts * stride] }
    numIndexBuffers x {
        char material[] (NUL-terminated, pad to 4)   e.g. vehicles\\X\\Y.mtx
        u32 flags(0), u32 numTris, [hasBones: u32 n, u16 palette[n], pad4], u16 indices[numTris*3], pad4
        u16 minIndex, u16 maxIndex, f32 sphere[4], f32 aabb[6]
    }
"""
import math
import struct
import sys
import os

SEMANTICS = ['POSITION', 'BLENDWEIGHT', 'NORMAL', 'TEXCOORD', 'TANGENT',
             'BINORMAL', 'COLOR', 'DEPTH', 'BLENDINDICES']

# Engine vertex-format ids seen in AMS2 meshes -> (byte stride, struct fmt).
# NOT DXGI numbering, except 20 which PCarsTools treats as "encrypted float3 position".
FORMATS = {
    0: (4, '<f'),      # float1
    1: (8, '<2f'),     # float2 (texcoords)
    2: (12, '<3f'),    # float3 (normals, tangents, binormals, texcoords (u, v, 0))
    3: (16, '<4f'),    # float4 (GUESS by enum order; not seen in donors)
    4: (4, '<4B'),     # 4 x u8 colour
    5: (4, '<4B'),     # 4 x u8 uint (blend indices)
    20: (12, '<3f'),   # float3 position with X component XOR-encrypted
}
FMT_ENC_POS = 20


# ---------------------------------------------------------------- hashing / crypto
def _mix32(a, b, c):
    M = 0xFFFFFFFF
    a = (a - b - c) & M; a ^= c >> 13
    b = (b - c - a) & M; b ^= (a << 8) & M
    c = (c - a - b) & M; c ^= b >> 13
    a = (a - b - c) & M; a ^= c >> 12
    b = (b - c - a) & M; b ^= (a << 16) & M
    c = (c - a - b) & M; c ^= b >> 5
    a = (a - b - c) & M; a ^= c >> 3
    b = (b - c - a) & M; b ^= (a << 10) & M
    c = (c - a - b) & M; c ^= b >> 15
    return a, b, c


def hash32_nocase(s):
    """BHashCode.CreateHash32NoCase (Bob Jenkins lookup2 variant, upper-cased)."""
    if not s:
        return 0xBD49D10D
    k = [ord(ch) for ch in s.upper()]
    length = len(k)
    M = 0xFFFFFFFF
    a = b = 0x9E3779B9
    c = 0
    ln = length
    o = 0
    while ln >= 12:
        a = (a + (k[o + 3] + (k[o + 2] << 8) + (k[o + 1] << 16) + (k[o + 0] << 24))) & M
        b = (b + (k[o + 7] + (k[o + 6] << 8) + (k[o + 5] << 16) + (k[o + 4] << 24))) & M
        c = (c + (k[o + 11] + (k[o + 10] << 8) + (k[o + 9] << 16) + (k[o + 8] << 24))) & M
        a, b, c = _mix32(a, b, c)
        o += 12
        ln -= 12
    c = (c + length) & M
    tail = {11: ('c', 10, 24), 10: ('c', 9, 16), 9: ('c', 8, 8),
            8: ('b', 7, 24), 7: ('b', 6, 16), 6: ('b', 5, 8), 5: ('b', 4, 0),
            4: ('a', 3, 24), 3: ('a', 2, 16), 2: ('a', 1, 8), 1: ('a', 0, 0)}
    while ln > 0:
        reg, idx, sh = tail[ln]
        v = (k[o + idx] << sh) & M
        if reg == 'a':
            a = (a + v) & M
        elif reg == 'b':
            b = (b + v) & M
        else:
            c = (c + v) & M
        ln -= 1
    a, b, c = _mix32(a, b, c)
    return c


def _base_xor():
    f = lambda x: math.floor(x)
    # computed in float32 in C#; these values are far from integer boundaries so float64 agrees
    v = (f(math.log10(1.49) * 1000.0)
         | (f(math.tan(0.418) * 500.0) << 8)
         | (f(math.cos(1.3561) * 1000.0) << 16)
         | ((f(math.sin(0.74) * 100.0) + f(math.sin(0.45) * 100.0)) << 24))
    return v & 0xFFFFFFFF


BASE_XOR = _base_xor()


def _rotl(x, n):
    n &= 31
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF if n else x


def pos_key(file_name, j):
    """XOR key applied to the raw u32 of vertex j's X coordinate (symmetric)."""
    c = (hash32_nocase(file_name) ^ BASE_XOR ^ j) & 0xFFFFFFFF
    return _rotl(c, j % 32)


def crypt_positions(raw, file_name):
    """En/decrypt (XOR, symmetric) a packed float3 position buffer. Returns bytes."""
    h = hash32_nocase(file_name) ^ BASE_XOR
    out = bytearray(raw)
    n = len(raw) // 12
    for j in range(n):
        x, = struct.unpack_from('<I', out, j * 12)
        struct.pack_into('<I', out, j * 12, x ^ _rotl((h ^ j) & 0xFFFFFFFF, j % 32))
    return bytes(out)


# ---------------------------------------------------------------- parsing
class Stream:
    def __init__(self, fmt, semantic, index, raw):
        self.fmt, self.semantic, self.index, self.raw = fmt, semantic, index, raw

    @property
    def name(self):
        return '%s%d' % (SEMANTICS[self.semantic] if self.semantic < len(SEMANTICS) else '?', self.index)


class IndexBuffer:
    def __init__(self, material, flags, indices, min_index, max_index, sphere, aabb):
        self.material, self.flags, self.indices = material, flags, indices
        self.mat_pad = self.idx_pad = b''
        self.min_index, self.max_index, self.sphere, self.aabb = min_index, max_index, sphere, aabb


class Meb:
    def __init__(self):
        self.version = 0x01000000
        self.has_bones = 0
        self.dyn_env = 0
        self.pad = 0
        self.name = ''
        self.name_pad = b''
        self.bone_names = []
        self.bone_str_raw = b''
        self.bone_xforms = []   # per bone 12 floats (3 x vec4), meaning unconfirmed
        self.num_verts = 0
        self.sphere = (0, 0, 0, 0)
        self.aabb = (0, 0, 0, 0, 0, 0)
        self.streams = []
        self.ibufs = []
        self.trailer = b''
        self.file_name = ''

    def stream(self, semantic, index=0):
        for s in self.streams:
            if s.semantic == semantic and s.index == index:
                return s
        return None

    def decoded(self, semantic, index=0):
        """Return list of tuples for the stream (positions decrypted)."""
        s = self.stream(semantic, index)
        if s is None:
            return None
        raw = s.raw
        if s.fmt == FMT_ENC_POS:
            raw = crypt_positions(raw, self.file_name)
        stride, f = FORMATS[s.fmt]
        return [struct.unpack_from(f, raw, i * stride) for i in range(self.num_verts)]


def _cstr(d, p):
    # NUL-terminated string padded to 4. Returns (str, pad_bytes_after_NUL, new_pos)
    e = d.index(bytes(1), p)
    q = (e + 1 + 3) & ~3
    return d[p:e].decode("latin-1"), d[e + 1:q], q


def parse(data, file_name):
    m = Meb()
    m.file_name = os.path.basename(file_name)
    m.version, m.has_bones, m.dyn_env, m.pad = struct.unpack_from('<IBBH', data, 0)
    minor = (m.version >> 22) & 63
    if minor != 4:
        raise ValueError('unsupported meb minor version %d' % minor)
    m.name, m.name_pad, p = _cstr(data, 8)
    m.num_verts, ns, nib = struct.unpack_from('<3i', data, p); p += 12
    m.sphere = struct.unpack_from('<4f', data, p); p += 16
    m.aabb = struct.unpack_from('<6f', data, p); p += 24
    if m.has_bones:
        nb, strsize = struct.unpack_from('<2i', data, p); p += 8
        blob = data[p:p + strsize]
        m.bone_names = [x.decode('latin-1') for x in blob.split(bytes(1))[:nb]]
        q = (p + strsize + 3) & ~3
        m.bone_str_raw = data[p:q]  # names + NULs + pad, kept verbatim
        p = q
        m.bone_xforms = [struct.unpack_from('<12f', data, p + 48 * i) for i in range(nb)]
        p += 48 * nb
    for _ in range(ns):
        fmt, sem, idx = struct.unpack_from('<3i', data, p); p += 12
        if fmt not in FORMATS:
            raise ValueError('unknown vertex format %d (semantic %d) at 0x%x' % (fmt, sem, p - 12))
        n = FORMATS[fmt][0] * m.num_verts
        m.streams.append(Stream(fmt, sem, idx, data[p:p + n])); p += n
    for _ in range(nib):
        mat, mpad, p = _cstr(data, p)
        flags, ntri = struct.unpack_from('<2I', data, p); p += 8
        if flags != 0:
            raise ValueError('index buffer flags %d not understood' % flags)
        pal, ppad = (), b""
        if m.has_bones:  # per-index-buffer bone palette (skinned meshes)
            npal, = struct.unpack_from("<I", data, p); p += 4
            pal = struct.unpack_from("<%dH" % npal, data, p); p += 2 * npal
            q = (p + 3) & ~3
            ppad = data[p:q]; p = q
        idx = struct.unpack_from('<%dH' % (ntri * 3), data, p); p += ntri * 6
        q = (p + 3) & ~3  # u16 index data padded to 4 bytes
        ipad = data[p:q]; p = q
        mn, mx = struct.unpack_from('<2H', data, p); p += 4
        sph = struct.unpack_from('<4f', data, p); p += 16
        bb = struct.unpack_from('<6f', data, p); p += 24
        ib = IndexBuffer(mat, flags, idx, mn, mx, sph, bb)
        ib.mat_pad, ib.idx_pad = mpad, ipad
        ib.palette, ib.pal_pad = pal, ppad
        m.ibufs.append(ib)
    m.trailer = data[p:]
    return m


def load(path):
    with open(path, 'rb') as f:
        return parse(f.read(), path)


# ---------------------------------------------------------------- OBJ export
def to_obj(m, path):
    pos = m.decoded(0)
    nrm = m.decoded(2)
    uv = m.decoded(3, 0)
    with open(path, 'w') as f:
        f.write('# exported from %s by meb_read.py\no %s\n' % (m.file_name, m.name))
        for v in pos:
            f.write('v %.6f %.6f %.6f\n' % v[:3])
        if uv:
            for t in uv:
                f.write('vt %.6f %.6f\n' % (t[0], 1.0 - t[1]))  # D3D v-down -> OBJ v-up
        if nrm:
            for n in nrm:
                f.write('vn %.6f %.6f %.6f\n' % n[:3])
        for ib in m.ibufs:
            f.write('g %s\nusemtl %s\n' % (os.path.basename(ib.material), os.path.basename(ib.material)))
            ix = ib.indices
            for t in range(0, len(ix), 3):
                a, b, c = ix[t] + 1, ix[t + 1] + 1, ix[t + 2] + 1
                # stored order satisfies (b-a)x(c-a) . normal > 0 (checked on all donors)
                if uv and nrm:
                    f.write('f %d/%d/%d %d/%d/%d %d/%d/%d\n' % (a, a, a, b, b, b, c, c, c))
                else:
                    f.write('f %d %d %d\n' % (a, b, c))


def summary(m):
    pos = m.decoded(0)
    lo = [min(p[i] for p in pos) for i in range(3)]
    hi = [max(p[i] for p in pos) for i in range(3)]
    s = ['%s  name=%s verts=%d streams=[%s]' % (m.file_name, m.name, m.num_verts,
         ', '.join('%s:f%d' % (st.name, st.fmt) for st in m.streams))]
    s.append('  header aabb min=%s max=%s' % (tuple(round(x, 4) for x in m.aabb[:3]), tuple(round(x, 4) for x in m.aabb[3:])))
    s.append('  decoded  min=%s max=%s  size=%s' % (tuple(round(x, 4) for x in lo), tuple(round(x, 4) for x in hi),
                                                     tuple(round(hi[i] - lo[i], 4) for i in range(3))))
    for ib in m.ibufs:
        s.append('  ibuf mat=%s tris=%d idx[%d..%d]' % (ib.material, len(ib.indices) // 3, ib.min_index, ib.max_index))
    if m.trailer:
        s.append('  TRAILER %d bytes' % len(m.trailer))
    return '\n'.join(s), lo, hi


def _aabb_ok(m, lo, hi, tol=1e-4):
    return all(abs(lo[i] - m.aabb[i]) < tol and abs(hi[i] - m.aabb[3 + i]) < tol for i in range(3))


def check(m):
    """Consistency checks. Returns list of problems (empty = OK) plus info dict."""
    probs, info = [], {}
    if m.trailer:
        probs.append('trailer %d bytes' % len(m.trailer))
    pos = m.decoded(0)
    lo = [min(p[i] for p in pos) for i in range(3)]
    hi = [max(p[i] for p in pos) for i in range(3)]
    is_dmg = m.file_name.lower().endswith('_dmg.meb')
    is_flare = 'lightglows' in m.file_name.lower()
    if not _aabb_ok(m, lo, hi) and not (is_dmg or is_flare):
        probs.append('aabb mismatch')
    if is_dmg and m.ibufs:
        probs.append('dmg mesh has index buffers')
    if not is_dmg and not m.ibufs:
        probs.append('no index buffers')
    nrm = m.decoded(2)
    agree = total = 0
    for ib in m.ibufs:
        ix = ib.indices
        if ix and (min(ix) != ib.min_index or max(ix) != ib.max_index):
            probs.append('ibuf min/max mismatch %s' % ib.material)
        if ix and max(ix) >= m.num_verts:
            probs.append('index out of range')
        if ix:
            sub = [pos[i] for i in set(ix)]
            blo = [min(p[k] for p in sub) for k in range(3)]
            bhi = [max(p[k] for p in sub) for k in range(3)]
            if not all(abs(blo[k] - ib.aabb[k]) < 1e-4 and abs(bhi[k] - ib.aabb[3 + k]) < 1e-4 for k in range(3)):
                if not is_flare:
                    probs.append('ibuf aabb mismatch %s' % ib.material)
        if nrm:
            for t in range(0, len(ix), 3):
                a, b, c = pos[ix[t]], pos[ix[t + 1]], pos[ix[t + 2]]
                u = [b[k] - a[k] for k in range(3)]
                v = [c[k] - a[k] for k in range(3)]
                fn = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
                n = nrm[ix[t]]
                d = fn[0] * n[0] + fn[1] * n[1] + fn[2] * n[2]
                if d != 0:
                    total += 1
                    agree += d > 0
    info['ccw_fraction'] = agree / total if total else None
    return probs, info


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == '--scan':
        ok = bad = 0
        ccw = []
        for root, _, files in os.walk(sys.argv[2]):
            for fn in sorted(files):
                if not fn.lower().endswith('.meb'):
                    continue
                try:
                    m = load(os.path.join(root, fn))
                    probs, info = check(m)
                    if info['ccw_fraction'] is not None:
                        ccw.append(info['ccw_fraction'])
                    if probs:
                        raise ValueError('; '.join(probs))
                    ok += 1
                except Exception as e:  # noqa
                    bad += 1
                    print('FAIL', fn, e)
        print('parsed+checked OK: %d, failed: %d' % (ok, bad))
        if ccw:
            print('fraction of tris whose (b-a)x(c-a) agrees with vertex normal: min %.3f mean %.3f'
                  % (min(ccw), sum(ccw) / len(ccw)))
    else:
        # meb_read.py file.meb [out.obj] [--base base.meb]   (--base supplies index buffers for _dmg morphs)
        args = sys.argv[1:]
        base = None
        if '--base' in args:
            i = args.index('--base')
            base = load(args[i + 1])
            del args[i:i + 2]
        m = load(args[0])
        txt, lo, hi = summary(m)
        print(txt)
        print('  decrypted positions match header AABB:', _aabb_ok(m, lo, hi))
        probs, info = check(m)
        print('  checks:', probs or 'OK', info)
        if len(args) > 1:
            if base is not None and not m.ibufs:
                m.ibufs = base.ibufs
            to_obj(m, args[1])
            print('wrote', args[1])
