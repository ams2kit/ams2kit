"""Generic classification of a donor car's mesh files (no car-specific names).

Every AMS2 car mesh file name follows `<prefix>_<part>[_<corner>][_blur]_<lod>[_dmg].meb`, for example
`lambo_veneno_body_loda.meb`, `mit_lanr_wheel_lf_blur_loda.meb`, `camaro_ss_body_cpit_dmg.meb`.
`<lod>` is `loda`..`lodd` (main pak) or `cpit` (cockpit pak: what the driver sees from inside).

This module turns a list of pak paths into:
  * `classify(stem)`      -> MeshInfo (part, role, lod, variant, corner, collection)
  * `make_plan(infos, tri_counts, skinned)` -> how each slot is rebuilt when the user edits the .blend

Used both by Python (ams2kit) and by the scripts running inside Blender (pure standard library).
"""
import re

CORNERS = {'lf': 'FL', 'rf': 'FR', 'lr': 'RL', 'rr': 'RR'}
LOD_RE = re.compile(r'^lod([a-z])$')

# role keywords (matched against the underscore tokens of the part name, prefix included)
ROLE_KEYWORDS = [
    ('flare', ('lightglows', 'lightglow', 'glows', 'flare', 'flares')),
    ('lights', ('lights', 'light', 'headlights', 'taillights')),
    ('glass', ('windows', 'window', 'glass', 'windscreen')),
    ('rim', ('wheel', 'wheels', 'rim', 'rims')),
    ('tire', ('tire', 'tyre', 'tires', 'tyres')),
    ('disc', ('disc', 'disk', 'brake', 'rotor')),
    ('caliper', ('caliper', 'calipers')),
    ('shadow', ('shadow',)),
    ('wiper', ('wiper', 'wipers')),
    ('interior', ('interior', 'interior2', 'cockpit', 'inside', 'display', 'gauges', 'needle', 'paddle',
                  'gearshift', 'shiftgaiter', 'steeringwheel', 'intanim', 'extanim', 'seat', 'seats', 'dash',
                  'mirrors_int', 'driver')),
]

# Blender collections (name -> visible by default)
COLLECTIONS = [
    ('REPLACE_Body', True),      # exterior LOD A: what the user models
    ('Lights', True),
    ('Glass', True),
    ('Wheels', True),            # with one child collection per corner: Wheel_FL, Wheel_FR, Wheel_RL, Wheel_RR
    ('Interior', True),          # main-pak interior (seen from outside)
    ('Cockpit', False),          # cockpit pak: what the driver sees
    ('Other', True),             # shadow plane, wipers, anything unclassified
    ('Flares', False),           # light-glow quads (expanded by the shader: their geometry looks odd)
    ('LODs', False),             # lower LODs + blurred rims (auto-generated from LOD A)
    ('CockpitView', False),      # *_cpit copies of exterior parts (auto-generated from LOD A)
    ('Damage', False),           # *_dmg morph targets (auto-generated from their base mesh)
]
WHEEL_COLLECTIONS = ['Wheel_FL', 'Wheel_FR', 'Wheel_RL', 'Wheel_RR']


class MeshInfo:
    """Parsed mesh file name."""

    def __init__(self, stem, pak_path=''):
        self.stem = stem                    # file name without extension, as in the pak
        self.pak_path = pak_path
        s = stem.lower()
        toks = s.split('_')
        self.dmg = toks[-1] == 'dmg'
        if self.dmg:
            toks = toks[:-1]
        self.lod = None                     # 'a'..'d'
        self.cpit = False
        if toks and LOD_RE.match(toks[-1]):
            self.lod = LOD_RE.match(toks[-1]).group(1)
            toks = toks[:-1]
        elif toks and toks[-1] == 'cpit':
            self.cpit = True
            toks = toks[:-1]
        self.blur = bool(toks) and toks[-1] == 'blur'
        if self.blur:
            toks = toks[:-1]
        self.corner = next((CORNERS[t] for t in toks if t in CORNERS), None)
        self.part = '_'.join(toks)          # e.g. lambo_veneno_wheel_lf
        self.role = 'body'
        for role, kws in ROLE_KEYWORDS:
            if any(t in kws for t in toks):
                self.role = role
                break
        if self.corner and self.role == 'body':
            self.role = 'rim'

    @property
    def base_stem(self):
        """Stem of the mesh this one is a damage morph of."""
        return self.stem[:-4] if self.dmg else self.stem

    @property
    def lod_key(self):
        return 'cpit' if self.cpit else (self.lod or '')

    def collection(self, cockpit_only):
        """Blender collection for this mesh. cockpit_only: True if a cpit part has no main-pak counterpart."""
        if self.dmg:
            return 'Damage'
        if self.cpit:
            if self.role == 'glass' or cockpit_only:
                return 'Cockpit'
            return 'CockpitView'
        if self.blur or (self.lod and self.lod != 'a'):
            return 'LODs'
        if self.corner:
            return 'Wheel_' + self.corner
        return {'body': 'REPLACE_Body', 'lights': 'Lights', 'flare': 'Flares', 'glass': 'Glass',
                'interior': 'Interior', 'shadow': 'Other', 'wiper': 'Other'}.get(self.role, 'Other')

    def __repr__(self):
        return 'MeshInfo(%s part=%s role=%s lod=%s cpit=%s blur=%s dmg=%s corner=%s)' % (
            self.stem, self.part, self.role, self.lod, self.cpit, self.blur, self.dmg, self.corner)


def stem_of(pak_path):
    base = pak_path.replace('/', '\\').split('\\')[-1]
    return base[:-4] if base.lower().endswith('.meb') else base


def classify_all(pak_paths):
    """-> {stem: MeshInfo} plus the collection name of every mesh."""
    infos = {}
    for p in pak_paths:
        st = stem_of(p)
        infos[st] = MeshInfo(st, p)
    main_parts = {i.part for i in infos.values() if not i.cpit}
    for i in infos.values():
        i.cockpit_only = i.cpit and i.part not in main_parts
        i.coll = i.collection(i.cockpit_only)
    return infos


def make_plan(infos, tri_counts, skinned):
    """Decide, per slot, where its geometry comes from when the user edits the .blend.

    infos: {stem: MeshInfo}; tri_counts: {stem: donor triangle count}; skinned: {stem: bool}.
    Returns {stem: dict(kind, sources, ratio, skinned)} where kind is
      'base'  - built from its own Blender object (LOD A, cockpit-only parts, anything without a source)
      'lod'   - lower LOD / blurred rim / cockpit-view copy: from `sources` (LOD A objects), decimated by
                `ratio` when the sources were edited and this object was not
      'dmg'   - damage morph of sources[0] (copy of the rebuilt base; donor bytes if the base is unchanged)
    """
    by_part_lod = {}
    for st, i in infos.items():
        if not i.dmg:
            by_part_lod[(i.part, i.lod_key, i.blur)] = st
    plan = {}
    # exterior (non-wheel) parts that have a LOD A: candidates for the far-LOD union rule
    ext_roles = ('body', 'lights', 'glass')
    ext_parts = sorted({i.part for i in infos.values() if not i.dmg and not i.cpit and i.lod == 'a'
                        and i.role in ext_roles and not i.corner})
    body_parts = [p for p in ext_parts if infos[by_part_lod[(p, 'a', False)]].role == 'body']
    for st, i in infos.items():
        sk = bool(skinned.get(st))
        if i.dmg:
            plan[st] = {'kind': 'dmg', 'sources': [i.base_stem] if i.base_stem in infos else [], 'ratio': 1.0,
                        'skinned': sk}
            if not plan[st]['sources']:
                plan[st]['kind'] = 'base'
            continue
        src = None
        if i.cpit or i.blur or (i.lod and i.lod != 'a'):
            src = by_part_lod.get((i.part, 'a', False))
        if not src:
            plan[st] = {'kind': 'base', 'sources': [], 'ratio': 1.0, 'skinned': sk}
            continue
        sources = [src]
        # far-LOD union: a LOD level that only ONE body part has stands in for the whole car
        if i.lod and i.lod != 'a' and not i.cpit and not i.blur and i.part in body_parts and len(body_parts) > 1:
            having = [p for p in body_parts if (p, i.lod, False) in by_part_lod]
            if having == [i.part]:
                sources = [by_part_lod[(p, 'a', False)] for p in ext_parts if (p, i.lod, False) not in by_part_lod
                           or p == i.part]
                sources.sort(key=lambda s: s != src)
        donor_src = sum(tri_counts.get(s, 0) for s in sources) or 1
        ratio = min(1.0, tri_counts.get(st, 0) / donor_src)
        plan[st] = {'kind': 'lod', 'sources': sources, 'ratio': round(ratio, 4), 'skinned': sk}
    return plan
