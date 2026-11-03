"""Offline tests for ams2kit.ev (docs/11). Game data tests skip when the extracted files are missing."""
import glob
import math
import os
import sys

import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ams2kit import ev, shcb  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import WORK  # noqa: E402

RG = str(WORK / "phys" / "PHYSICSPERSISTENT_extracted" / "vehicles" / "physics" / "driveline" / "driveline.rg")
PHYS = str(WORK / "research" / "shcb" / "physics_all")


class EvTests(unittest.TestCase):
    def test_motor_rows_shape(self):
        rows = ev.motor_rows(390, 1050, 8000, regen_kw=60, regen_nm=300)
        assert len(rows) == 25 and rows[0][0] == 0.0
        rpms = [r for r, _, _ in rows]
        assert rpms == sorted(rpms)
        for r, d, t in rows[1:]:
            assert d <= 0
            if 0 < r < 8000:
                assert t <= 1050 + 1e-6 and t * r * 2 * math.pi / 60 <= 390e3 * 1.001
        assert dict((r, t) for r, _, t in rows)[8000.0] == 0.0
        assert all(t < 0 for r, _, t in rows if r > 8000)
        # constant power above the corner speed (3547 rpm)
        r, _, t = rows[12]
        assert abs(t * r * 2 * math.pi / 60 - 390e3) < 500


    def test_regen_fades_at_low_rpm(self):
        rows = ev.motor_rows(390, 1050, 8000, regen_kw=60, regen_nm=300, regen_fade_rpm=1000, friction_nm=0)
        low = [d for r, d, _ in rows if 0 < r < 1000]
        assert low and all(-300 < d < 0 for d in low)


    def test_gearing(self):
        fd = ev.final_drive_for(187, 8000, 0.3545)
        assert abs(fd - 5.717) < 0.01
        assert abs(ev.reflected_inertia(0.04, 16000, 8000) - 0.16) < 1e-9
        assert abs(ev.sim_peak_torque(500, 16000, 8000) - 1000) < 1e-9


    def test_strtab_cipher_roundtrip(self):
        for s in (b"REAR\0", b"FOUR\0", b"FRONT\0"):
            assert ev.strtab_crypt(ev.strtab_crypt(s)) == s
        assert ev.strtab_crypt(b"REAR\0").hex() == "d65c7a7def"      # bytes found in every RWD hybrid .bbfbin


    @unittest.skipUnless(os.path.exists(RG), "extracted driveline.rg missing")
    def test_ev_driveline_rg(self):
        g = open(RG, encoding="latin-1").read()
        t = ev.ev_driveline_rg("BYD_Seal", "AWD_VENENO_SEQUENTIAL_SVA_FLEX_v3", g, suffix="BYD_EV")
        b = ev.rg_blocks(t)
        grp = b["AWD_VENENO_SEQUENTIAL_SVA_FLEX_v3_BYD_EV"][2]
        assert "clutch_BYD_EV_centrifugal" in grp and "clutch_GT3_650Nm" not in grp
        assert b["clutch_BYD_EV_centrifugal"][1] == "l_centrifugal_clutch"
        assert 'name "BYD_SEAL"' in t
        # every member is either a game record or defined here
        game = ev.rg_blocks(g)
        assert all(m in game or m in b for m in grp)
        t2 = ev.ev_driveline_rg("BYD_Seal", "AWD_VENENO_SEQUENTIAL_SVA_FLEX_v3", g, suffix="X", crank_mass=0.16)
        b2 = ev.rg_blocks(t2)
        assert "sim:mass 0.16" in b2["crankshaft_GT3_X"][2]
        assert "pair:left crankshaft_GT3_X" in b2["clutch_X_centrifugal"][2]
        assert "pair:right crankshaft_GT3_X" in b2["torqueshaft_strain_VENENO_X"][2]


    @unittest.skipUnless(glob.glob(PHYS + r"\Lamborghini_Revuelto\turbo\*.bbfbin"), "no Revuelto cache")
    def test_boost_set_front(self):
        d = open(glob.glob(PHYS + r"\Lamborghini_Revuelto\turbo\*.bbfbin")[0], "rb").read()
        assert ev.strings_of(shcb.parse(d)) == ["FOUR"]
        out = ev.boost_set(d, wheel_drive="FRONT", max_boost_kw=160)
        f = shcb.parse(out)
        assert ev.strings_of(f) == ["FRONT"]
        assert f.find("3a74a835").value == 160
        assert shcb.serialize(f) == out


if __name__ == "__main__":
    unittest.main()
