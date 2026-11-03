"""Corner -> vertex welding shared by the Blender dump script and the .meb builder (numpy only).

A "dump" is a dict of per-corner arrays (3 corners per triangle, game winding, game space, mesh-local):
    pos (C,3) f32, nrm (C,3) f32, vidx (C,) i64 (source vertex id; corners of one Blender vertex share it),
    mat (T,) i32 (index into the dump's material list), donor (C,) i8, optional col (C,4) u8,
    uv0 (C,2) (TEXCOORD0, Blender v-up), 'uv:<name>' (C,2), 'attr:<name>' (C,)
Welding merges corners with the same material, vertex id (donor vertex index, or the quantised position
for new geometry), normal and attribute values. The result is
ordered by (material, vertex id), so a mesh that came from a donor .meb gets its original vertex order
back, and every material's vertices form one contiguous range (required by the .meb format).
"""
import numpy as np

NRM_Q = 1e4
UV_Q = 1e6


def _qcols(a, scale):
    a = np.asarray(a, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    return np.round(np.nan_to_num(a) * scale).astype(np.int64)


POS_Q = 1e5


def vertex_ids(d):
    """Vertex identity used for welding: the source vertex index for donor vertices (keeps the donor's
    vertex order), a position id for everything else (imported models are often fully split)."""
    vidx = np.asarray(d['vidx'], np.int64)
    donor = np.asarray(d['donor']) > 0
    if donor.all():
        return vidx
    q = np.round(np.asarray(d['pos'], np.float64)[~donor] * POS_Q).astype(np.int64)
    _, pid = np.unique(q, axis=0, return_inverse=True)
    out = vidx.copy()
    out[~donor] = (int(vidx.max()) + 1) + pid.ravel()
    return out


def snap_normals(matc, vidx, nrm, min_dot=0.9999):
    """Corners of one vertex whose normals agree within min_dot get the exact same normal (Blender stores
    custom normals as int16 per corner, so a smooth vertex comes back with tiny per-corner differences)."""
    nrm = np.asarray(nrm, np.float64).copy()
    key = matc * (int(vidx.max()) + 1 if len(vidx) else 1) + vidx
    order = np.argsort(key, kind='stable')
    ks = key[order]
    start = np.ones(len(ks), bool)
    start[1:] = ks[1:] != ks[:-1]
    ref = order[np.maximum.accumulate(np.where(start, np.arange(len(ks)), 0))]
    snap = np.empty(len(ks), bool)
    snap[order] = np.sum(nrm[order] * nrm[ref], axis=1) > min_dot
    refc = np.empty(len(ks), np.int64)
    refc[order] = ref
    nrm[snap] = nrm[refc[snap]]
    return nrm


def weld(d):
    """-> (first, inverse): first[v] = a corner index representing welded vertex v,
    inverse[c] = welded vertex of corner c. Vertices sorted by (material, vidx, attributes)."""
    n = len(d['vidx'])
    if n == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    matc = np.repeat(np.asarray(d['mat'], np.int64), 3)
    vidx = vertex_ids(d)
    cols = [matc[:, None], vidx[:, None], _qcols(snap_normals(matc, vidx, d['nrm']), NRM_Q), _qcols(d['uv0'], UV_Q)]
    for k in sorted(d.keys()):
        if k.startswith('uv:') or k.startswith('attr:'):
            cols.append(_qcols(d[k], UV_Q))
    if 'col' in d:
        cols.append(np.asarray(d['col'], np.int64))
    cols.append(np.asarray(d['donor'], np.int64)[:, None])
    key = np.ascontiguousarray(np.hstack(cols))
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return first, inv.ravel()


def welded_count(d):
    return len(weld(d)[0])
