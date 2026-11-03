"""Read node transforms from a car's `.vhf` (text XML, "Phx Staging Tools").

Mesh vertex positions in a .meb are local to the MATRIX of the OBJECT node that references the file
(FINDINGS.md section 3): wheels/discs/calipers are centred on the hub, the steering wheel and paddles are
rotated, body panels mostly use identity matrices.

`node_matrices(vhf_text)` -> {mesh file name upper-cased: 4x4 row-major matrix (game space, list of 16 floats)}
`node_spheres(vhf_text)`  -> {mesh file name upper-cased: (cx, cy, cz, r)} (the culling sphere, mesh-local)
"""
import math
import xml.etree.ElementTree as ET


def _quat_mat(x, y, z, w, s=1.0):
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return [[s * (1 - 2 * (y * y + z * z)), s * (2 * (x * y - z * w)), s * (2 * (x * z + y * w))],
            [s * (2 * (x * y + z * w)), s * (1 - 2 * (x * x + z * z)), s * (2 * (y * z - x * w))],
            [s * (2 * (x * z - y * w)), s * (2 * (y * z + x * w)), s * (1 - 2 * (x * x + y * y))]]


def _mat4(rot, off):
    return [rot[0][0], rot[0][1], rot[0][2], off[0],
            rot[1][0], rot[1][1], rot[1][2], off[1],
            rot[2][0], rot[2][1], rot[2][2], off[2],
            0.0, 0.0, 0.0, 1.0]


def matmul4(a, b):
    return [sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4)]


IDENTITY = _mat4([[1, 0, 0], [0, 1, 0], [0, 0, 1]], (0, 0, 0))


def _parse(vhf_text):
    if isinstance(vhf_text, bytes):
        vhf_text = vhf_text.decode('utf-8', 'replace')
    i = vhf_text.find('<')
    return ET.fromstring(vhf_text[i:].encode('utf-8'))


def node_matrices(vhf_text):
    root = _parse(vhf_text)
    local, parent = {}, {}
    for m in root.iter('MATRIX'):
        mid = int(m.get('id'))
        off = [float(v) for v in m.get('Offset', '0 0 0').split()]
        q = [float(v) for v in m.get('Orientation', '0 0 0 1').split()]
        s = float(m.get('Scale', '1'))
        local[mid] = _mat4(_quat_mat(q[0], q[1], q[2], q[3], s), off)
        if m.get('parent') is not None:
            parent[mid] = int(m.get('parent'))
    world = {}

    def get(mid, depth=0):
        if mid in world:
            return world[mid]
        w = local.get(mid, IDENTITY)
        if mid in parent and parent[mid] != mid and depth < 64:
            w = matmul4(get(parent[mid], depth + 1), w)
        world[mid] = w
        return w
    out = {}
    for node in root.iter('NODE'):
        if node.get('type') != 'OBJECT':
            continue
        res = node.find('RESOURCE')
        if res is None:
            continue
        fn = res.get('Filename', '').replace('/', '\\').split('\\')[-1].upper()
        out[fn] = get(int(node.get('MatrixNumber', '0')))
    return out


def node_spheres(vhf_text):
    root = _parse(vhf_text)
    out = {}
    for node in root.iter('NODE'):
        if node.get('type') != 'OBJECT':
            continue
        res, sph = node.find('RESOURCE'), node.find('SPHERE')
        if res is None or sph is None:
            continue
        fn = res.get('Filename', '').replace('/', '\\').split('\\')[-1].upper()
        c = [float(v) for v in sph.get('Centre').split()][:3]
        out[fn] = (c[0], c[1], c[2], float(sph.get('Radius')))
    return out
