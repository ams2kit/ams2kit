"""Donor -> .blend -> .meb round-trip tests (needs Blender 5.2 and the donor paks).

    python -m unittest tests.test_blend_bridge -v        (from the repository root)
    AMS2KIT_DONORS=Lamborghini_Veneno,Camaro_SS  limits the donors (default: Veneno + Camaro_SS)

Donor files come from <AMS2KIT_TEST_WORK>\\research\\blend\\donors\\<Pak> when extracted there, else they
are read (read-only) from the game's encrypted paks (see tests/_paths.py).
The model-fit test needs AMS2KIT_TEST_MODEL=<a car model .blend> and AMS2KIT_TEST_FIT=<its fit config .json>.
"""
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ams2kit.mesh import blend_bridge as BB  # noqa: E402
from ams2kit.mesh import donor_layout as L  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import WORK, VEHICLE_PAKS  # noqa: E402

R = BB.R
W = BB.W
CACHE = str(WORK / 'research' / 'blend' / 'donors')
GAME_PAKS = str(VEHICLE_PAKS)
WHEELS = {'Lamborghini_Veneno': {'FL': (0.865, 0.333, -1.351), 'FR': (-0.865, 0.333, -1.351),
                                 'RL': (0.859, 0.358, 1.351), 'RR': (-0.859, 0.358, 1.351)}}
DONORS = os.environ.get('AMS2KIT_DONORS', 'Lamborghini_Veneno,Camaro_SS').split(',')


def load_donor(pak):
    """-> ({pak path: bytes} for main + cockpit .meb files, [vhf texts])"""
    files, vhfs = {}, []
    for sub in (pak, pak + '_Cockpit'):
        root = os.path.join(CACHE, sub)
        if os.path.isdir(root):
            for dp, _, fns in os.walk(root):
                for fn in fns:
                    full = os.path.join(dp, fn)
                    data = open(full, 'rb').read()
                    if fn.lower().endswith('.meb'):
                        files[os.path.relpath(full, root)] = data
                    elif fn.lower().endswith('.vhf'):
                        vhfs.append(data.decode('utf-8', 'replace'))
        else:
            from ams2kit import pak_extract as P
            f, key, entries = P.open_pak(os.path.join(GAME_PAKS, sub + '.bff'))
            for e in entries:
                if e[0].lower().endswith('.meb'):
                    files[e[0]] = P.read_entry(f, key, e)
                elif e[0].lower().endswith('.vhf'):
                    vhfs.append(P.read_entry(f, key, e).decode('utf-8', 'replace'))
    return files, vhfs


# ------------------------------------------------------------------ comparison
def _arr(m, sem, idx=0):
    v = m.decoded(sem, idx)
    return None if v is None else np.array(v, np.float64).reshape(m.num_verts, -1)


def compare_mesh(donor_bytes, built_bytes, name):
    """Geometry/stream comparison of a rebuilt mesh with its donor. Returns a dict of metrics."""
    d, b = R.parse(donor_bytes, name), R.parse(built_bytes, name)
    r = {'identical': donor_bytes == built_bytes, 'verts': (d.num_verts, b.num_verts),
         'layout_equal': [(s.fmt, s.semantic, s.index) for s in d.streams] ==
                         [(s.fmt, s.semantic, s.index) for s in b.streams],
         'materials_equal': [ib.material for ib in d.ibufs] == [ib.material for ib in b.ibufs],
         'name_equal': d.name == b.name}
    if r['identical']:
        return r
    dt, _ = BB._tris(d)
    bt, _ = BB._tris(b)
    r['tris'] = (len(dt), len(bt))
    if d.num_verts != b.num_verts:
        # degenerate donor triangles are dropped on export; vertices only they used disappear
        used = np.zeros(d.num_verts, bool)
        used[dt.ravel()] = True
        r['degenerate_only_verts'] = int(d.num_verts - used.sum())
        return r
    r['indices_equal'] = len(dt) == len(bt) and bool(np.all(dt == bt))
    used = np.zeros(d.num_verts, bool)
    used[dt.ravel()] = True
    if not d.ibufs:          # damage morph: every vertex counts
        used[:] = True
    r['pos_err'] = float(np.abs(_arr(d, 0) - _arr(b, 0))[used].max()) if used.any() else 0.0
    if d.stream(2) is not None:
        nd = _arr(d, 2)
        nz = used & (np.linalg.norm(nd, axis=1) > 0.5)       # donors contain a few zero normals
        r['nrm_min_dot'] = float(np.min(np.sum(nd * _arr(b, 2), 1)[nz])) if nz.any() else 1.0
    tc_err = 0.0
    for s in d.streams:
        if s.semantic == 3:
            tc_err = max(tc_err, float(np.abs(_arr(d, 3, s.index) - _arr(b, 3, s.index))[used].max()))
    r['tc_err'] = tc_err
    if d.stream(6) is not None:
        r['col_equal'] = bool(np.all(_arr(d, 6) == _arr(b, 6)))
    if d.stream(4) is not None:
        agree = np.sum(_arr(d, 4) * _arr(b, 4), 1)[used] > 0.9
        r['tangent_agree'] = float(agree.mean()) if used.any() else 1.0
    r['aabb_err'] = float(np.max(np.abs(np.array(d.aabb) - np.array(b.aabb))))
    r['sphere_err'] = float(np.max(np.abs(np.array(d.sphere) - np.array(b.sphere))))
    return r


def mesh_ok(r):
    if r['identical']:
        return True
    if not (r['layout_equal'] and r['materials_equal'] and r['name_equal']):
        return False
    if r['verts'][0] != r['verts'][1]:
        return r['verts'][0] - r.get('degenerate_only_verts', 0) == r['verts'][1] and r['tris'][0] == r['tris'][1]
    return (r.get('indices_equal', False) and r['pos_err'] < 1e-5 and r.get('nrm_min_dot', 1) > 0.999
            and r['tc_err'] < 1e-5 and r.get('col_equal', True) and r['aabb_err'] < 1e-5)


def compare_all(files, outputs):
    rep = {}
    for path, data in files.items():
        if not path.lower().endswith('.meb'):
            continue
        out = outputs.get(path)
        built = open(out, 'rb').read() if out else data
        rep[path] = compare_mesh(data, built, L.stem_of(path) + '.meb')
    return rep


def print_report(rep):
    ok = sum(mesh_ok(r) for r in rep.values())
    ident = sum(r['identical'] for r in rep.values())
    print('meshes %d: equivalent %d (byte-identical %d)' % (len(rep), ok, ident))
    ta = [r['tangent_agree'] for r in rep.values() if 'tangent_agree' in r]
    pe = [r['pos_err'] for r in rep.values() if 'pos_err' in r]
    if ta:
        print('tangent agreement: min %.3f mean %.3f; max position error %.2g' % (min(ta), sum(ta) / len(ta), max(pe)))
    for p, r in sorted(rep.items()):
        if not mesh_ok(r):
            print('  DIFF', os.path.basename(p), {k: v for k, v in r.items() if k != 'identical'})
    return ok


def run_blender_edit(blend_in, blend_out, code):
    """Apply a bpy snippet to a copy of a .blend (headless) and save it as blend_out."""
    fd, script = tempfile.mkstemp(suffix='.py')
    with os.fdopen(fd, 'w') as fh:
        fh.write('import bpy\n' + code + '\nbpy.ops.wm.save_as_mainfile(filepath=%r, copy=True)\n' % blend_out)
    p = subprocess.run([BB.BLENDER_EXE, '--factory-startup', '--disable-autoexec', '-b', blend_in,
                        '--python-exit-code', '1', '--python', script], capture_output=True, text=True)
    os.remove(script)
    if p.returncode:
        raise RuntimeError(p.stdout[-2000:] + p.stderr[-2000:])


# ------------------------------------------------------------------ tests
class TestLayout(unittest.TestCase):
    def test_classification(self):
        names = ['lambo_veneno_body_loda', 'lambo_veneno_body_lodb_dmg', 'lambo_veneno_wheel_lf_blur_loda',
                 'lambo_veneno_tire_rr_lodc', 'lambo_veneno_body_cpit', 'lambo_veneno_interior2_cpit',
                 'lambo_veneno_lightglows_f_loda', 'mit_lanr_steeringwheel_cpit', 'camaro_ss_windows_cpit',
                 'lambo_veneno_chassis_lodd']
        infos = L.classify_all(['vehicles\\x\\%s.meb' % n for n in names])
        c = {k: v.coll for k, v in infos.items()}
        self.assertEqual(c['lambo_veneno_body_loda'], 'REPLACE_Body')
        self.assertEqual(c['lambo_veneno_body_lodb_dmg'], 'Damage')
        self.assertEqual(c['lambo_veneno_wheel_lf_blur_loda'], 'LODs')
        self.assertEqual(infos['lambo_veneno_tire_rr_lodc'].corner, 'RR')
        self.assertEqual(c['lambo_veneno_body_cpit'], 'CockpitView')
        self.assertEqual(c['lambo_veneno_interior2_cpit'], 'Cockpit')
        self.assertEqual(c['lambo_veneno_lightglows_f_loda'], 'Flares')
        self.assertEqual(c['camaro_ss_windows_cpit'], 'Cockpit')

    def test_far_lod_union(self):
        names = ['v_body_loda', 'v_body_lodb', 'v_boot_loda', 'v_boot_lodb', 'v_chassis_loda', 'v_chassis_lodd',
                 'v_lights_loda']
        infos = L.classify_all(names)
        plan = L.make_plan(infos, {n: 100 for n in names}, {})
        self.assertEqual(plan['v_chassis_lodd']['sources'][0], 'v_chassis_loda')
        self.assertEqual(set(plan['v_chassis_lodd']['sources']),
                         {'v_body_loda', 'v_boot_loda', 'v_chassis_loda', 'v_lights_loda'})
        self.assertEqual(plan['v_body_lodb']['sources'], ['v_body_loda'])


class TestRoundTrip(unittest.TestCase):
    """export -> unchanged .blend -> build: plain build must change nothing; forced rebuild must be equivalent."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='ams2bt_')

    def _roundtrip(self, pak):
        files, vhfs = load_donor(pak)
        self.assertTrue(files, 'no donor files for %s' % pak)
        blend = os.path.join(self.tmp, 'donor_%s.blend' % pak.lower())
        res = BB.export_donor_blend(files, blend, wheel_centres=WHEELS.get(pak), vhf_text=vhfs)
        self.assertEqual(res['objects'], len(files))
        out = BB.build_from_blend(blend, files, os.path.join(self.tmp, 'plain_' + pak))
        self.assertEqual(out, {}, 'unchanged .blend must reproduce the donor files')
        out = BB.build_from_blend(blend, files, os.path.join(self.tmp, 'force_' + pak), force_rebuild=True,
                                  include_unchanged=True)
        rep = compare_all(files, out)
        print('\n[%s]' % pak)
        ok = print_report(rep)
        self.assertEqual(ok, len(rep))
        ta = [r['tangent_agree'] for r in rep.values() if 'tangent_agree' in r]
        if ta:
            self.assertGreater(sum(ta) / len(ta), 0.9)
        return blend, files

    def test_donors(self):
        if not os.path.isdir(GAME_PAKS):
            self.skipTest("needs the game (set AMS2KIT_GAME)")
        for pak in DONORS:
            with self.subTest(pak=pak):
                blend, files = self._roundtrip(pak)
                if pak == DONORS[0]:
                    self._edit_scenario(blend, files)

    def _edit_scenario(self, blend, files):
        """Delete one LOD A part, move the body: LODs/damage/cockpit copies must follow."""
        infos = L.classify_all(list(files))
        body = next(s for s, i in infos.items() if i.coll == 'REPLACE_Body' and '_body_' in s.lower())
        victim = next(s for s, i in infos.items() if i.coll == 'REPLACE_Body' and s != body)
        edited = os.path.join(self.tmp, 'edited.blend')
        run_blender_edit(blend, edited, 'bpy.data.objects.remove(bpy.data.objects[%r])\n'
                                        'ob = bpy.data.objects[%r]\n'
                                        'for v in ob.data.vertices: v.co.z += 0.01\n' % (victim, body))
        out_dir = os.path.join(self.tmp, 'edited_out')
        out = BB.build_from_blend(edited, files, out_dir)
        import json
        man = json.load(open(os.path.join(out_dir, 'manifest.json')))['files']
        by_stem = {L.stem_of(p): e for p, e in man.items()}
        self.assertEqual(by_stem[body]['action'], 'mesh')
        self.assertEqual(by_stem[victim]['action'], 'collapse')
        part = infos[victim].part
        for st, i in infos.items():
            if i.part == part and st != victim:
                if any(s != victim for s in L.make_plan(infos, {}, {})[st]['sources']):
                    continue      # far-LOD union also contains other parts
                self.assertEqual(by_stem[st]['action'], 'collapse', st)
        bpart = infos[body].part
        derived = [st for st, i in infos.items() if i.part == bpart and st != body]
        self.assertTrue(derived)
        changed = {L.stem_of(p) for p in out}
        for st in derived:
            self.assertEqual(by_stem[st]['action'], 'dmg' if infos[st].dmg else 'mesh', st)
            self.assertIn(st, changed)
        for p, e in man.items():
            self.assertEqual(e['reader_check'], 'OK', p)


PARTNER = os.environ.get('AMS2KIT_TEST_MODEL', '')      # a car model .blend (not part of the repository)
BYD_FIT = os.environ.get('AMS2KIT_TEST_FIT') or str(WORK / 'research' / 'blend' / 'byd_camaro' / 'byd_seal_fit.json')


@unittest.skipUnless(os.path.exists(PARTNER) and os.path.exists(BYD_FIT), 'set AMS2KIT_TEST_MODEL (and AMS2KIT_TEST_FIT) to run')
class TestFitModel(unittest.TestCase):
    """fit_model_into_donor on the Camaro: automatic donor parts/materials, build passes the reader checks."""

    def test_camaro(self):
        import json
        tmp = tempfile.mkdtemp(prefix='ams2fit_')
        files, vhfs = load_donor('Camaro_SS')
        donor = os.path.join(tmp, 'donor.blend')
        BB.export_donor_blend(files, donor, vhf_text=vhfs)
        log = BB.fit_model_into_donor(donor, PARTNER, os.path.join(tmp, 'car.blend'), config=BYD_FIT)
        self.assertEqual(log['donor_materials']['PAINT'].split(chr(92))[-1], 'CAMARO_SS_PAINT.mtx')
        self.assertEqual(log['donor_materials']['RIM'].split(chr(92))[-1], 'CAMARO_SS_RIM.mtx')
        self.assertIn('camaro_ss_fbumper_loda', log['hidden'])
        self.assertLess(max(abs(x) for e in log['wheel_fit_error_m'].values() for x in e), 0.05)
        out = os.path.join(tmp, 'out')
        BB.build_from_blend(os.path.join(tmp, 'car.blend'), files, out)
        man = json.load(open(os.path.join(out, 'manifest.json')))['files']
        self.assertTrue(all(e['reader_check'] == 'OK' for e in man.values()))
        body = next(e for p, e in man.items() if p.lower().endswith('camaro_ss_body_loda.meb'))
        self.assertEqual(body['action'], 'mesh')
        self.assertGreater(body['tris'], 50000)


if __name__ == '__main__':
    unittest.main()
