"""Cockpit properties (.bin) parser/retarget tests (reads HRDFPERSISTENT.bff read-only).

    python -m unittest tests.test_cockpit -v        (from the repository root)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ams2kit import cockpit, pak_tool, paks  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import GAME  # noqa: E402

PAK = str(GAME / "Pakfiles" / "HRDFPERSISTENT.bff")


@unittest.skipUnless(os.path.exists(PAK), "game not installed")
class CockpitBinTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = paks.PakReader(PAK)
        cls.files = {p: r.read(p) for p in r.paths if "cockpit" in p.lower() and p.lower().endswith(".bin")}

    def test_roundtrip_and_uid(self):
        self.assertGreater(len(self.files), 300)
        for p, d in self.files.items():
            cb = cockpit.parse(d)
            self.assertEqual(cb.to_bytes(), d, p)
            self.assertEqual(cb.uid, pak_tool.path_uid(p.lower()), p)

    def test_retarget_camaro(self):
        d = self.files[r"vehicles\camaro_ss\camaro_ss_cockpit.bin"]
        n = cockpit.retarget_cockpit_bin(d, "camaro_ss", "byd_seal", "BYD_Seal")
        s = cockpit.parse(n).strings()
        self.assertEqual(s["cockpit_vhf"], "BYD_Seal_Cockpit.vhf")
        self.assertEqual(s["gearshift_node"], "CAMARO_SS_GEARSHIFT_CPIT")
        self.assertEqual(s["display"], "display_camaro_ss")
        self.assertEqual(cockpit.parse(n).uid, pak_tool.path_uid(r"vehicles\byd_seal\byd_seal_cockpit.bin"))
        self.assertEqual(len(n), len(d))   # shorter name: rewritten in place

    def test_retarget_longer_name(self):
        d = self.files[r"vehicles\lamborghini_veneno\lamborghini_veneno_cockpit.bin"]
        n = cockpit.retarget_cockpit_bin(d, "lamborghini_veneno", "a_much_longer_car_name_x", "A_Much_Longer_Car_Name_X")
        cb = cockpit.parse(n)
        self.assertEqual(cb.get_string(cockpit.F_COCKPIT_VHF), "A_Much_Longer_Car_Name_X_Cockpit.vhf")
        self.assertEqual(cb.get_string(cockpit.F_DISPLAY), "display_lamborghini_veneno")
        self.assertEqual(cb.enum_fixups, cockpit.parse(d).enum_fixups)
        self.assertEqual(cb.to_bytes(), n)


if __name__ == "__main__":
    unittest.main()
