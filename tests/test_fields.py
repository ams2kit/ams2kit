import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ams2kit import fields as F  # noqa: E402
from ams2kit import shcb  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import WORK  # noqa: E402

CACHE = str(WORK / "research" / "shcb" / "physics_all")


class TestHash(unittest.TestCase):
    def test_known_keys(self):
        # keys documented in docs/03 and 09, verified against the hash
        for name, key in [("RPMTorque", "8b0ab771"), ("Mass", "670b57ab"), ("Inertia", "bbb39f0b"),
                          ("CGHeight", "1824eaa8"), ("SpringRange", "a5123d0d"), ("BrakeTorque", "4ba4817a"),
                          ("Ratio", "9d58f964"), ("bevel", "3c5bef62"), ("EngineSize", "92c7cd7c"),
                          ("WheelDrive", "9435f2cb"), ("[FRONTLEFT]", "7d16e29f"), ("Width", "bd034c23")]:
            self.assertEqual(F.key_for_name(name), key, name)
            self.assertEqual(F.key_for_name(name.lower()), key)  # case-insensitive (upper-cased first)

    def test_lookup2_long_input(self):
        # > 12 bytes exercises the block loop
        self.assertEqual(F.key_for_name("OilWaterHeatTransfer"), F.key_for_name("OILWATERHEATTRANSFER"))
        self.assertEqual(F.key_for_name("Undertray11"), "9d8f09c3")


class TestDictionary(unittest.TestCase):
    def test_shape(self):
        self.assertEqual(set(F.FIELDS), set(F.KINDS))
        for kind, d in F.FIELDS.items():
            for k, e in d.items():
                self.assertEqual(len(k), 8, (kind, k))
                self.assertTrue({"name", "unit", "desc", "confidence", "editable", "name_source"} <= set(e))
                self.assertIn(e["confidence"], ("proven", "strong", "guess", "unknown"))
                self.assertIn(e["name_source"], ("hash", "analogy", "descriptive"))
                if e["name_source"] == "hash":
                    self.assertEqual(F.key_for_name(e["name"]), k)

    def test_calibration_fields(self):
        c = F.FIELDS["chassis"]
        self.assertEqual(c["4ba4817a"]["name"], "BrakeTorque")
        self.assertEqual(c["a3bf1e60"]["confidence"], "proven")
        for k in ("3363edfd", "2cfb70da", "23ec212a", "67dcb6b3", "83d385b9", "a6321357", "fdba6473",
                  "d0003859", "b3d2e5a0", "639d2bd2", "249e0313", "b2be8e7e", "bc1266e0", "bc907f88"):
            self.assertIn(k, c)
            self.assertTrue(c[k]["editable"], k)
        self.assertIn("b31155cd", F.FIELDS["tyres"])

    def test_describe_unknown(self):
        d = F.describe("chassis", "f8c2b0fd")
        self.assertIsNone(d["name"])
        self.assertEqual(d["confidence"], "unknown")
        self.assertIn("base files", d["desc"])
        d = F.describe("engine", 0x71B70A8B)   # int key = little-endian of the file bytes
        self.assertEqual(d["name"], "RPMTorque")
        self.assertEqual(F.describe("engine", "deadbeef")["desc"], "Not present in any base-game file.")
        with self.assertRaises(ValueError):
            F.describe("nope", "00000000")

    def test_kind_of_path(self):
        self.assertEqual(F.kind_of_path(r"x\engines\a.EDFBIN"), "engine")
        self.assertEqual(F.kind_of_path("a.hdtbin"), "tyres")
        self.assertIsNone(F.kind_of_path("a.vdfm"))

    def test_setup_value(self):
        self.assertAlmostEqual(F.setup_value([0, 0.01, 100], 35), 0.35)
        self.assertAlmostEqual(F.setup_value([0.5, 0.01, 50], 40), 0.9)


def _read(p):
    with open(p, "rb") as fh:
        return fh.read()


def _sample(ext):
    return sorted(glob.glob(os.path.join(CACHE, "*", "*", "*" + ext)))


@unittest.skipUnless(os.path.isdir(CACHE), "base-car physics cache missing")
class TestListFields(unittest.TestCase):
    def test_lancer_chassis(self):
        p = os.path.join(CACHE, "Mitsubishi_LancerR", "chassis", "mitsubishi_lancerr.cdfbin")
        b = _read(p)
        rows = F.list_fields("chassis", b)
        f = shcb.parse(b)
        self.assertEqual(len(rows), sum(1 for _ in f.iter_values()))
        bt = [r for r in rows if r["name"] == "BrakeTorque"]
        self.assertEqual([r["path"] for r in bt][0], "[FRONTLEFT]")
        self.assertEqual(len(bt), 4)
        self.assertEqual(bt[0]["value"], 3800)
        tm = [r for r in rows if r["key"] == "a3bf1e60"][0]
        self.assertEqual(tm["path"], "[ENGINE]")
        self.assertAlmostEqual(tm["value"], 0.85, places=5)
        mass = [r for r in rows if r["name"] == "Mass"][0]
        self.assertEqual((mass["path"], mass["value"]), ("[GENERAL]", 1490))

    def test_every_kind_parses(self):
        kinds = {".cdfbin": "chassis", ".edfbin": "engine", ".gdfbin": "gearbox", ".sdfbin": "suspension",
                 ".cmfbin": "clutch", ".fmfbin": "failures", ".tbfbin": "turbo", ".bbfbin": "boost"}
        for ext, kind in kinds.items():
            for p in _sample(ext)[:15]:
                rows = F.list_fields(kind, _read(p))
                self.assertTrue(rows, p)
                for r in rows:
                    self.assertIn(r["confidence"], ("proven", "strong", "guess", "unknown"))

    def test_engine_rows_and_repeats(self):
        p = os.path.join(CACHE, "Lamborghini_Veneno", "engines", "lamborghini_veneno_lp750-4.edfbin")
        rows = F.list_fields("engine", _read(p))
        tq = [r for r in rows if r["name"] == "RPMTorque"]
        self.assertEqual(len(tq), 26)
        self.assertEqual([r["occurrence"] for r in tq[:3]], [0, 1, 2])

    def test_suspension_paths(self):
        p = os.path.join(CACHE, "Lamborghini_Veneno", "suspension", "lamborghini_veneno.sdfbin")
        rows = F.list_fields("suspension", _read(p))
        paths = {r["path"] for r in rows}
        self.assertTrue(any(x.startswith("[BODY]#") for x in paths))
        self.assertTrue(any(x.startswith("[BAR]#") for x in paths))


if __name__ == "__main__":
    unittest.main()
