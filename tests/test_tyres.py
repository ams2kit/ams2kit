"""Tyre size (docs/13): size parsing, the vdfm wheel block, visual tyre resize, buildphys/doctor integration.

Run:  python -m unittest tests.test_tyres -v   (from ams2kit\\)
"""
import copy
import os
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ams2kit import physics as P, project as project_mod, tyres  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import WORK as W  # noqa: E402

VEHICLES = W / "phys" / "PHYSICSPERSISTENT_extracted" / "vehicles" / "physics" / "vehicles"
LANCER = W / "kit_projects" / "BYD_Seal_Lancer"
LANCER_PAK = LANCER / "donor" / "paks" / "Mitsubishi_LancerR.bff"


class SizeTests(unittest.TestCase):
    def test_parse(self):
        s = tyres.parse_size("245/45R19")
        self.assertAlmostEqual(s["width"], 0.245)
        self.assertAlmostEqual(s["diameter"], 0.2205 + 0.4826, places=4)
        self.assertAlmostEqual(s["rim_radius"], 0.2413, places=4)
        self.assertEqual(tyres.parse_size("245/45 ZR19")["diameter"], s["diameter"])
        self.assertEqual(tyres.parse_size("355/25R21")["text"], "355/25R21")
        with self.assertRaises(ValueError):
            tyres.parse_size("19 inch")

    def test_project_sizes(self):
        pr = project_mod.Project(W / "nonexistent_project_dir")
        self.assertIsNone(tyres.project_sizes(pr))
        pr.cfg["chassis"]["tyre_size"] = "255/30R20"
        pr.cfg["chassis"]["tyre_size_rear"] = "355/25R21"
        s = tyres.project_sizes(pr)
        self.assertAlmostEqual(s["front"]["width"], 0.255)
        self.assertAlmostEqual(s["rear"]["width"], 0.355)


@unittest.skipUnless(VEHICLES.is_dir(), "no PHYSICSPERSISTENT extraction")
class VdfmWheelTests(unittest.TestCase):
    def test_known_cars(self):
        # Veneno 255/30R20 + 355/25R21: diameter/2 = tyre mesh radius 0.332 / 0.357
        w = tyres.read_vdfm_wheels((VEHICLES / "lamborghini_veneno.vdfm").read_bytes())
        self.assertAlmostEqual(w["FL"]["diameter"] / 2, 0.332, places=3)
        self.assertAlmostEqual(w["RR"]["diameter"] / 2, 0.357, places=3)
        self.assertAlmostEqual(w["RL"]["width"], 0.355, places=3)
        self.assertAlmostEqual(w["FL"]["pos"][1], 0.333, places=3)    # = the .vhf hub / suspension wheel y

    def test_write_roundtrip(self):
        b = (VEHICLES / "mitsubishi_lancerr.vdfm").read_bytes()
        sizes = {"front": tyres.parse_size("245/45R19"), "rear": tyres.parse_size("275/40R19")}
        moves = {"FL": (0.036, -0.135), "FR": (-0.036, -0.135), "RL": (0.0385, 0.135), "RR": (-0.0385, 0.135)}
        nb = tyres.write_vdfm_wheels(b, sizes, moves)
        self.assertEqual(len(nb), len(b))
        self.assertTrue(P.serial_layout_ok(nb))
        self.assertEqual(P.read_vdfm(nb), P.read_vdfm(b))          # names untouched
        w0, w1 = tyres.read_vdfm_wheels(b), tyres.read_vdfm_wheels(nb)
        self.assertAlmostEqual(w1["RL"]["width"], 0.275, places=5)
        self.assertAlmostEqual(w1["FR"]["diameter"], sizes["front"]["diameter"], places=4)
        self.assertAlmostEqual(w1["FL"]["pos"][0] - w0["FL"]["pos"][0], 0.036, places=5)
        self.assertAlmostEqual(w1["RR"]["pos"][2] - w0["RR"]["pos"][2], 0.135, places=5)
        self.assertEqual(w1["FL"]["pos"][1], w0["FL"]["pos"][1])
        # changed bytes stay inside the wheel block
        diff = [i for i in range(len(b)) if b[i] != nb[i]]
        self.assertTrue(all(0x98 <= i < 0xE8 for i in diff))


@unittest.skipUnless(LANCER_PAK.exists(), "Lancer donor project missing")
class TyreMeshTests(unittest.TestCase):
    def setUp(self):
        from ams2kit import paks
        from ams2kit.mesh import meb_read
        with paks.PakReader(LANCER_PAK) as r:
            p = next(p for p in r.paths if p.lower().endswith("tire_lf_loda.meb"))
            self.name = p.rsplit("\\", 1)[-1]
            self.data = r.read(p)
        self.m = meb_read.parse(self.data, self.name)

    def test_dims_from_bones(self):
        o, b, w = tyres.tyre_dims(self.m)
        self.assertAlmostEqual(o, 0.3233, places=3)       # CARCASS - ROAD
        self.assertAlmostEqual(b, 0.2285, places=3)       # CARCASS - RIM (18" bead)
        self.assertAlmostEqual(w, 0.2314, places=3)

    def test_resize(self):
        from ams2kit.mesh import meb_read, meb_write
        nm = tyres.resize_tyre_meb(self.m, 0.3573, 0.2413, 1.1)
        back = meb_read.parse(meb_write.serialize(nm, self.name), self.name)
        o, b, _ = tyres.tyre_dims(back)
        self.assertAlmostEqual(o, 0.3573, places=4)
        self.assertAlmostEqual(b, 0.2413, places=4)
        pos = np.array(back.decoded(0))
        r = np.hypot(pos[:, 1], pos[:, 2])
        self.assertAlmostEqual(r.max(), 0.3573 * 0.3242 / 0.3233, delta=0.002)
        p0 = np.array(self.m.decoded(0))
        np.testing.assert_allclose(pos[:, 0], p0[:, 0] * 1.1, atol=1e-5)
        # CARCASS (hub) unchanged, normals unit length, bounds recomputed
        self.assertEqual(tyres.tyre_bones(back)["CARCASS"], tyres.tyre_bones(self.m)["CARCASS"])
        n = np.array(back.decoded(2))
        np.testing.assert_allclose(np.linalg.norm(n, axis=1), 1.0, atol=1e-4)
        self.assertAlmostEqual(back.aabb[4], pos[:, 1].max(), places=5)
        self.assertEqual(meb_read.check(back)[0], [])

    def test_identity(self):
        o, b, _ = tyres.tyre_dims(self.m)
        nm = tyres.resize_tyre_meb(self.m, o, b, 1.0)
        np.testing.assert_allclose(np.array(nm.decoded(0)), np.array(self.m.decoded(0)), atol=2e-6)

    def test_plan_and_files(self):
        pr = project_mod.Project(LANCER)
        pr.cfg = copy.deepcopy(pr.cfg)
        pr.cfg["chassis"]["tyre_size"], pr.cfg["chassis"]["tyre_size_rear"] = "", ""
        vd = tyres.donor_vdfm(pr)
        files = {"vehicles\\x\\" + self.name: self.data}
        same, rep = tyres.resize_mesh_files(pr, files, vd)
        self.assertIsNone(rep)
        self.assertIs(same, files)
        pr.cfg["chassis"]["tyre_size"] = "245/45R19"
        new, rep = tyres.resize_mesh_files(pr, files, vd)
        e = rep["vehicles\\x\\" + self.name]
        # donor draws its tyre 5.8 mm over diameter/2 (0.3233 vs 0.635/2); the new tyre keeps that offset
        self.assertAlmostEqual(e["outer"][1], 0.7031 / 2 + (0.3233 - 0.635 / 2), places=3)
        self.assertEqual(e["width_scale"], 1.0)


if __name__ == "__main__":
    unittest.main()
