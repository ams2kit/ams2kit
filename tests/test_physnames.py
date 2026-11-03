"""Car-named physics files (docs/12): the vdfm layout check and buildphys independent mode.

Run:  python -m unittest tests.test_physnames -v   (from ams2kit\\)
"""
import os
import random
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ams2kit import buildphys as B, cockpit, physics as P, project as project_mod  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import WORK as W  # noqa: E402

PERSIST = W / "phys" / "PHYSICSPERSISTENT_extracted" / "vehicles" / "physics"
COCKPITS = W / "research" / "cockpit" / "samples"
CAMARO = W / "kit_projects" / "BYD_Seal_Camaro"
VENENO = W / "kit_projects" / "BYD_Seal"


def donor_vdfm(proj, key):
    return (proj / "donor" / "files" / "vehicles" / "physics" / "vehicles" / f"{key}.vdfm").read_bytes()


def old_in_place(b, names):
    """The pre-fix buildphys.write_vdfm_in_place (table rewritten, length updated, pad byte NOT)."""
    b = bytearray(b)
    _, rel, relocs, _, _ = P._vdfm_layout(bytes(b))
    fields = {}
    for r in relocs:
        s0 = 0x1F0 + struct.unpack_from("<Q", b, 0x30 + r)[0]
        fields[0x30 + r] = b[s0:b.index(b"\0", s0)].decode("latin-1")
    fields.update(names)
    table, offs = bytearray(), {}
    for n in dict.fromkeys(fields.values()):
        offs[n] = len(table)
        table += n.encode() + b"\0"
    b[0x1F0:rel] = table.ljust(rel - 0x1F0, b"\0")
    struct.pack_into("<I", b, 0x18, max(len(table), struct.unpack_from("<I", b, 0x18)[0]))
    for f, n in fields.items():
        struct.pack_into("<Q", b, f, offs[n])
    return bytes(b)


class TestLayoutCheck(unittest.TestCase):
    def test_base_files_pass(self):
        if not PERSIST.exists():
            self.skipTest("no PHYSICSPERSISTENT extraction")
        files = list((PERSIST / "vehicles").glob("*.vdfm")) + list((PERSIST / "statistics").glob("*.mrdf"))
        self.assertGreater(len(files), 1500)
        for p in files:
            self.assertTrue(P.serial_layout_ok(p.read_bytes()), p.name)

    def test_cockpit_bins_pass(self):
        files = list(COCKPITS.glob("*.bin"))
        if not files:
            self.skipTest("no cockpit samples")
        for p in files:
            b = p.read_bytes()
            self.assertTrue(P.serial_layout_ok(b), p.name)
            # retargeting to a much longer name appends to the data block: pads must follow
            out = cockpit.retarget_cockpit_bin(b, p.stem.lower().replace("_cockpit", ""), "some_long_car_key_x",
                                               "Some_Long_Car_Key_X")
            self.assertTrue(P.serial_layout_ok(out), p.name)

    def test_known_in_game_results(self):
        """Every vdfm that crashed in game fails the check; every one that worked passes."""
        if not CAMARO.exists() or not VENENO.exists():
            self.skipTest("kit projects missing")
        cam, ven = donor_vdfm(CAMARO, "camaro_ss"), donor_vdfm(VENENO, "lamborghini_veneno")
        crashed = old_in_place(cam, {0x48: "byd_seal", 0x70: "byd_seal"})
        worked = [old_in_place(cam, {}), old_in_place(ven, {0x48: "byd_seal", 0x70: "byd_seal"}),
                  old_in_place(ven, {0x48: "byd_seal_engine", 0x70: "byd_seal_gearbox"})]
        self.assertFalse(P.serial_layout_ok(crashed))
        for b in worked:
            self.assertTrue(P.serial_layout_ok(b))
        # the fixed writer makes the crashed case valid
        fixed = B.write_vdfm_in_place(cam, {0x48: "byd_seal", 0x70: "byd_seal"})
        self.assertTrue(P.serial_layout_ok(fixed))
        d = P.read_vdfm(fixed)
        self.assertEqual((d["engine"], d["gearbox"], d["tyres"]), ("byd_seal", "byd_seal", "chevrolet_camaro_zl1"))

    def test_any_name_length(self):
        if not PERSIST.exists():
            self.skipTest("no PHYSICSPERSISTENT extraction")
        rnd = random.Random(7)
        files = sorted((PERSIST / "vehicles").glob("*.vdfm"))
        for p in rnd.sample(files, 40):
            b = p.read_bytes()
            for _ in range(5):
                names = {f: "x" * rnd.randint(1, 60) + str(i)
                         for i, f in enumerate((0x38, 0x48, 0x70, 0x78, 0x80))}
                out = B.write_vdfm_in_place(b, names)
                self.assertTrue(P.serial_layout_ok(out), p.name)
                f = B.vdfm_fields(out)
                for k, v in names.items():
                    self.assertEqual(f[k], v)
                self.assertEqual(f[0x88], B.vdfm_fields(b)[0x88])


class TestCollision(unittest.TestCase):
    def test_retarget(self):
        col = CAMARO / "donor" / "files" / "vehicles" / "physics" / "collision"
        if not col.exists():
            self.skipTest("no Camaro donor")
        xml = B.retarget_collision((col / "camaro_ss.xml").read_bytes(), "Camaro_SS", "byd_seal")
        sysx = B.retarget_collision((col / "camaro_ss.sys.xml").read_bytes(), "Camaro_SS", "byd_seal")
        joi = (col / "camaro_ss.joi.xml").read_bytes()
        self.assertIn(b'data="COLLISION_CONVEX_BYD_SEAL"', xml)
        self.assertNotIn(b'"COLLISION_CONVEX_CAMARO_SS"', xml)
        self.assertIn(b"COLLISION_CONVEX_CAMARO_SS_CHASSIS_LODA", xml)   # sub-shapes untouched
        self.assertEqual(sysx.count(b"COLLISION_CONVEX_BYD_SEAL"), 2)
        self.assertEqual(B.retarget_collision(joi, "Camaro_SS", "byd_seal"), joi)


class TestIndependentBuild(unittest.TestCase):
    def setUp(self):
        if not (CAMARO / "car.toml").exists() or not (CAMARO / "donor" / "donor.json").exists():
            self.skipTest("no Camaro kit project")
        self.pr = project_mod.Project(CAMARO)

    def _vdfm(self, out):
        return out[f"vehicles\\physics\\vehicles\\{self.pr.key}.vdfm"]

    def test_default_keeps_donor_names(self):
        out, names = B.build(self.pr, log=lambda *a: None, independent=False)
        f = B.vdfm_fields(self._vdfm(out))
        self.assertTrue(P.serial_layout_ok(self._vdfm(out)))
        self.assertEqual((f[0x38], f[0x48], f[0x70], f[0x78]), ("Camaro_SS",) * 4)
        self.assertIn("vehicles\\physics\\chassis\\Camaro_SS.cdfbin", out)
        self.assertFalse(names["independent"])

    def test_independent(self):
        key = self.pr.key
        out, names = B.build(self.pr, log=lambda *a: None, independent=True, rename_collision=False)
        v = self._vdfm(out)
        self.assertTrue(P.serial_layout_ok(v))
        f = B.vdfm_fields(v)
        self.assertEqual((f[0x38], f[0x48], f[0x70], f[0x78]), (key,) * 4)
        self.assertEqual(f[0x80], "Camaro_SS")                 # collision kept (verbatim donor files)
        self.assertEqual(f[0x88], "chevrolet_camaro_zl1")      # tyres: boot-list tyre set
        for sub, ext in (("chassis", "cdfbin"), ("suspension", "sdfbin"), ("engines", "edfbin"), ("gearbox", "gdfbin")):
            self.assertIn(f"vehicles\\physics\\{sub}\\{key}.{ext}", out)
        # nothing at a donor path: the real Camaro SS is unaffected by our pak
        self.assertFalse([p for p in out if "camaro_ss" in p.lower()])
        self.assertEqual((names["base"], names["donor_base"]), (key, "Camaro_SS"))
        # edited content: same files as the default build, only the names moved
        dflt, _ = B.build(self.pr, log=lambda *a: None, independent=False)
        self.assertEqual(out[f"vehicles\\physics\\chassis\\{key}.cdfbin"], dflt["vehicles\\physics\\chassis\\Camaro_SS.cdfbin"])
        self.assertEqual(out[f"vehicles\\physics\\engines\\{key}.edfbin"], dflt["vehicles\\physics\\engines\\Camaro_SS.edfbin"])

    def test_independent_collision(self):
        key = self.pr.key
        out, names = B.build(self.pr, log=lambda *a: None, independent=True, rename_collision=True)
        f = B.vdfm_fields(self._vdfm(out))
        self.assertEqual(f[0x80], key)
        for ext in (".xml", ".joi.xml", ".sys.xml"):
            self.assertIn(f"vehicles\\physics\\collision\\{key}{ext}", out)
        self.assertIn(b"COLLISION_CONVEX_" + key.upper().encode(), out[f"vehicles\\physics\\collision\\{key}.xml"])
        self.assertEqual(names["collision"], key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
