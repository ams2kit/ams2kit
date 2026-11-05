"""Pick texels of donor textures for new faces (flat colour per class), by reading the actual texture.

The fit tool gives new glass/light/rim/trim faces one constant TEXCOORD0 into the donor material's texture.
Choosing it as "the donor's most common UV" picked a red tail-light texel of the shared glass atlas for the
Jetta's windows (common_glass_various_diff.dds: grey glass / black / red glass / grey quadrants). This module
resolves material -> .bmt -> diffuse .dds (donor paks first, then the game's shared paks), decodes it with Pillow
and scores candidate texels (the cells the donor's own faces use, then the whole texture) per class:

  GLASS     translucent, neutral, darkish        LIGHT       neutral, bright
  LIGHT_RED saturated red (tail lights)          LIGHT_AMBER orange (indicators)
  RIM       neutral, mid/light grey (silver)     GLOSS       neutral, light (chrome-ish trim)
  PLASTIC / INTERIOR   neutral, dark (trim)

Result: {mtx path lower: {'texture': path, 'size': [w, h], CLASS: {'uv': [u, v] (D3D, v down), 'rgba': [...],
'source': 'donor-uv'|'texture'}}}. Everything is standard library + numpy + Pillow (runs outside Blender).
"""
import io
import json
import re
from pathlib import Path

import numpy as np

from . import meb_read as R

RULES = ('GLASS', 'LIGHT', 'LIGHT_RED', 'LIGHT_AMBER', 'RIM', 'PLASTIC', 'GLOSS', 'INTERIOR')
_SKIP_TEX = ('spec', 'norm', 'nrm', 'crack', 'rain', 'glow', 'fresnel', 'dirt', 'damage', 'env', 'ao.', '_ao', 'mask',
             'droplet', 'flake', 'livery')


def bmt_textures(bmt_bytes):
    """Texture paths named in a BLMY material (.bmt), in file order."""
    return [s.decode('latin-1') for s in re.findall(rb'[ -~]{4,}?\.dds', bmt_bytes, re.I)]


def diffuse_of(bmt_bytes):
    tex = bmt_textures(bmt_bytes)
    named = [t for t in tex if 'diff' in t.lower()]
    if named:
        return named[0]
    rest = [t for t in tex if not any(k in t.lower() for k in _SKIP_TEX)]
    return (rest or tex or [None])[0]


class TextureSource:
    """Find pak files by path: the given readers first, then an index of the game's top-level Pakfiles\\*.bff
    (cached in index_file; car paks under Pakfiles\\Vehicles are not scanned)."""

    def __init__(self, readers, game_dir=None, index_file=None):
        from .. import paks
        self._paks = paks
        self.readers = list(readers)
        self.game_dir = Path(game_dir) if game_dir else None
        self.index_file = Path(index_file) if index_file else None
        self._index = None

    def _game_index(self):
        if self._index is not None:
            return self._index
        self._index = {}
        if self.index_file and self.index_file.exists():
            self._index = json.loads(self.index_file.read_text(encoding='utf-8'))
        elif self.game_dir:
            for f in sorted((self.game_dir / 'Pakfiles').glob('*.bff')):
                try:
                    with self._paks.PakReader(f) as r:
                        for p in r.paths:
                            if p.lower().endswith(('.dds', '.bmt')):
                                self._index.setdefault(p.lower(), f.name)
                except Exception:
                    continue
            if self.index_file:
                self.index_file.parent.mkdir(parents=True, exist_ok=True)
                self.index_file.write_text(json.dumps(self._index), encoding='utf-8')
        return self._index

    def read(self, path):
        for r in self.readers:
            if path in r:
                return r.read(path)
        pk = self._game_index().get(path.lower())
        if pk and self.game_dir:
            with self._paks.PakReader(self.game_dir / 'Pakfiles' / pk) as r:
                return r.read(path)
        return None


def decode_dds(data):
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    return np.asarray(im.convert('RGBA'), np.float64) / 255.0


def _metrics(rgba):
    rgb = rgba[..., :3]
    mx, mn = rgb.max(-1), rgb.min(-1)
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722])
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    return lum, sat, rgba[..., 3]


def score(rule, lum, sat, alpha):
    """Lower is better."""
    if rule == 'GLASS':
        return 3 * sat + abs(lum - 0.2) + 2 * np.maximum(alpha - 0.6, 0)
    if rule == 'LIGHT':
        return 3 * sat + (1 - lum)
    if rule == 'RIM':
        return 3 * sat + abs(lum - 0.6)
    if rule == 'GLOSS':
        return 3 * sat + abs(lum - 0.7)
    return 3 * sat + lum                      # PLASTIC / INTERIOR: dark neutral trim


def score_rgb(rule, rgba):
    """Colour rules (lower is better); None for the neutral rules handled by score()."""
    r, g, b = rgba[..., 0], rgba[..., 1], rgba[..., 2]
    if rule == 'LIGHT_RED':
        return (1 - r) + 2 * g + 2 * b
    if rule == 'LIGHT_AMBER':
        return (1 - r) + abs(g - 0.5 * r) * 2 + 2 * b
    return None


def _score(rule, rgba):
    s = score_rgb(rule, rgba)
    if s is not None:
        return s
    return score(rule, *_metrics(rgba))


def _sample(img, u, v):
    h, w = img.shape[:2]
    x = int((u % 1.0) * w) % w
    y = int((v % 1.0) * h) % h
    x0, x1, y0, y1 = max(x - 1, 0), min(x + 2, w), max(y - 1, 0), min(y + 2, h)
    return img[y0:y1, x0:x1].reshape(-1, 4).mean(0)


def material_uvs(mesh_files):
    """{mtx lower: (N, 2) TEXCOORD0 of the donor vertices using it} over all donor meshes."""
    out = {}
    for path, data in mesh_files.items():
        try:
            m = R.parse(data, path.rsplit('\\', 1)[-1])
        except Exception:
            continue
        dec = m.decoded(3, 0) if m.num_verts else None
        if not dec:
            continue
        uv = np.array([t[:2] for t in dec], np.float64)
        for ib in m.ibufs:
            if ib.indices:
                out.setdefault(ib.material.lower(), []).append(uv[np.unique(np.asarray(ib.indices))])
    return {k: np.concatenate(v) for k, v in out.items()}


def pick(img, uvs, rule, min_share=0.002):
    """(uv, rgba, source) for one rule: best-scoring cell among those the donor's faces use (at least min_share of
    them), else the best texel of the whole texture."""
    h, w = img.shape[:2]
    cand = []
    if uvs is not None and len(uvs):
        g = max(4, min(64, w, h))
        q = np.floor((uvs % 1.0) * g).astype(np.int64)
        keys, inv, cnt = np.unique(q[:, 0] * g + q[:, 1], return_inverse=True, return_counts=True)
        for i, k in enumerate(keys):
            if cnt[i] < max(1, min_share * len(uvs)):
                continue
            u, v = uvs[inv.ravel() == i].mean(0) % 1.0
            cand.append(((float(u), float(v)), _sample(img, u, v), 'donor-uv'))
    ok = bool(cand) and _score(rule, np.array([c[1] for c in cand])).min() < 0.5
    if not ok:                                  # whole texture on a coarse grid
        g = 32
        cand = [(((x + 0.5) / g, (y + 0.5) / g), _sample(img, (x + 0.5) / g, (y + 0.5) / g), 'texture')
                for y in range(g) for x in range(g)]
    s = _score(rule, np.array([c[1] for c in cand]))
    i = int(np.argmin(s))
    uv, rgba, src = cand[i]
    if score_rgb(rule, np.asarray(rgba)) is not None and s[i] > 0.7:
        return None                               # no such colour in this texture: the caller uses the base rule
    return [round(uv[0], 6), round(uv[1], 6)], [round(float(x), 3) for x in rgba], src


GLOW_RULES = {'LIGHT_GLOW': 'LIGHT', 'LIGHT_GLOW_RED': 'LIGHT_RED', 'LIGHT_GLOW_AMBER': 'LIGHT_AMBER'}


def emissive_of(bmt_bytes):
    return next((t for t in bmt_textures(bmt_bytes) if any(k in t.lower() for k in ('glow', 'emis'))), None)


def pick_glow(img, glow, uvs, rule):
    """Like pick() for lamp faces (LIGHT_GLOW*): the colour of the base rule on a texel that also glows in the
    material's emissive map, so the face lights up when the game switches its light id on. The plain LIGHT*
    rules stay for reflectors and trim, which must not glow."""
    base = GLOW_RULES[rule]
    g = 64
    cand = []
    if uvs is not None and len(uvs):
        q = np.unique(np.floor((uvs % 1.0) * g).astype(np.int64), axis=0)
        cand = [((x + 0.5) / g, (y + 0.5) / g) for x, y in q]
    cand += [((x + 0.5) / g, (y + 0.5) / g) for y in range(g) for x in range(g)]
    rgba = np.array([_sample(img, u, v) for u, v in cand])
    lum = np.array([_sample(glow, u, v)[:3].max() for u, v in cand])
    s = _score(base, rgba) + 2 * (1 - lum)
    i = int(np.argmin(s))
    if lum[i] < 0.5 or (score_rgb(base, rgba[i]) is not None and score_rgb(base, rgba[i]) > 0.9):
        return None
    return ([round(cand[i][0], 6), round(cand[i][1], 6)], [round(float(x), 3) for x in rgba[i]],
            'texture+glow %.2f' % lum[i])


def donor_texels(mesh_files, source, materials=None, rules=RULES, log=None):
    """{mtx lower: {...}} (module doc) for the donor materials used by mesh_files (or `materials`)."""
    uvs = material_uvs(mesh_files)
    out = {}
    for mtx in sorted(materials or uvs):
        mtx_l = mtx.lower()
        bmt = source.read(mtx_l[:-4] + '.bmt' if mtx_l.endswith('.mtx') else mtx_l)
        if bmt is None:
            continue
        tex = diffuse_of(bmt)
        data = source.read(tex) if tex else None
        if data is None:
            if log:
                log('texels: %s: texture %s not found' % (mtx, tex))
            continue
        try:
            img = decode_dds(data)
        except Exception as e:
            if log:
                log('texels: %s: cannot decode %s (%s)' % (mtx, tex, e))
            continue
        e = {'texture': tex, 'size': [img.shape[1], img.shape[0]]}
        for rule in rules:
            r = pick(img, uvs.get(mtx_l), rule)
            if r is not None:
                e[rule] = {'uv': r[0], 'rgba': r[1], 'source': r[2]}
        gtex = emissive_of(bmt)
        gdata = source.read(gtex) if gtex else None
        if gdata is not None:
            try:
                glow = decode_dds(gdata)
            except Exception:
                glow = None
            if glow is not None:
                e['emissive'] = gtex
                for rule in GLOW_RULES:
                    r = pick_glow(img, glow, uvs.get(mtx_l), rule)
                    if r is not None:
                        e[rule] = {'uv': r[0], 'rgba': r[1], 'source': r[2]}
        out[mtx_l] = e
    return out


def project_texels(project, log=None):
    """donor_texels for an ams2kit project: donor paks first, then the game's top-level paks (index cached in
    the ams2kit data dir; the first run scans them, a few minutes)."""
    from .. import actions, donor, game, paks
    info = donor.info(project)
    readers = [paks.PakReader(project.donor_dir / 'paks' / info[k]) for k in ('pak', 'cockpit', 'livery') if info.get(k)]
    try:
        src = TextureSource(readers, game.find_game(), game.DATA_DIR / 'texture_index.json')
        return donor_texels(actions._mesh_files(project), src, log=log)
    finally:
        for r in readers:
            r.close()
