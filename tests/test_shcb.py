"""Tests for ams2kit.shcb (format) and ams2kit.physics (accessors).

Run:  python -m unittest discover -s tests -v   (from the repository root)
(or pytest). The all-cars round trip uses the cache in research\\shcb\\physics_all; if the cache
is missing it is built from the encrypted base-game paks (slow, a few minutes).
"""
import math
import os
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ams2kit import shcb, physics as P  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import WORK as W, VEHICLE_PAKS  # noqa: E402

CACHE = W / "research" / "shcb" / "physics_all"
PAKS = VEHICLE_PAKS
DONOR = W / "donor" / "Lamborghini_Veneno_extracted" / "vehicles" / "physics"
BYD_OUT = W / "BYD_Seal" / "build" / "physics"
PERSIST = W / "phys" / "PHYSICSPERSISTENT_extracted" / "vehicles" / "physics"


def ensure_cache():
    """Extract vehicles\\physics\\* (non-xml) of every base car pak into CACHE/<pak>/<dir>/<file>."""
    if CACHE.exists() and any(CACHE.iterdir()):
        return
    from ams2kit import pak_extract as pe
    for pak in sorted(PAKS.glob("*.bff")):
        name = pak.stem
        if name.lower().endswith(("_cockpit", "_livery")):
            continue
        try:
            f, key, entries = pe.open_pak(str(pak))
        except Exception:
            continue                     # unencrypted mod paks etc.
        with f:
            for e in entries:
                p = e[0].lower()
                if p.startswith("vehicles\\physics\\") and not p.endswith(".xml"):
                    dst = CACHE / name / Path(*e[0].split("\\")[2:])
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(pe.read_entry(f, key, e))
        (CACHE / name).mkdir(parents=True, exist_ok=True)
        (CACHE / name / ".done").write_text("ok")


def cached(car, sub, pattern="*"):
    files = sorted((CACHE / car / sub).glob(pattern))
    if not files:
        raise unittest.SkipTest(f"no cached {car}/{sub}")
    return files[0]


class TestRoundTrip(unittest.TestCase):
    def test_all_base_cars_byte_identical(self):
        ensure_cache()
        files = [p for p in CACHE.glob("*/*/*") if p.is_file() and p.name != ".done"]
        if not files:
            self.skipTest("needs the game's physics files (set AMS2KIT_GAME)")
        self.assertGreater(len(files), 3000)
        bad, raw = [], []
        for p in files:
            b = p.read_bytes()
            f = shcb.parse(b)
            if shcb.serialize(f) != b:
                bad.append(p)
            if any(isinstance(e, shcb.Raw) for e in f.entries):
                raw.append(p.parent.parent.name)
        self.assertEqual(bad, [])
        # only the Mini Cooper S 1965 gearbox has an unknown construct (kept verbatim)
        self.assertTrue(set(raw) <= {"Mini_CooperS_1965", "Mini_CooperS_1965_B"}, raw)
        print(f"\n  round-tripped {len(files)} files")

    def test_donor_trailer_kept(self):
        # the donor folder's clutch has bytes after the ShCB total size (extraction padding)
        p = DONOR / "clutches" / "gt_gt3.cmfbin"
        if not p.exists():
            self.skipTest("no donor")
        b = p.read_bytes()
        f = shcb.parse(b)
        self.assertEqual(shcb.serialize(f), b)
        self.assertEqual(len(f.trailer), len(b) - struct.unpack_from("<I", b, 8)[0])

    def test_dump(self):
        p = DONOR / "engines" / "lamborghini_veneno_lp750-4.edfbin"
        if not p.exists():
            self.skipTest("no donor")
        text = shcb.dump(p.read_bytes())
        self.assertIn("8b0ab771", text)
        self.assertIn("tuple[3] (8500:i32", text)
        text = shcb.dump((DONOR / "suspension" / "lamborghini_veneno.sdfbin").read_bytes())
        self.assertIn("GROUP[3]", text)
        self.assertIn("OBJECT 7817b5d2", text)


class TestFormatEdits(unittest.TestCase):
    def setUp(self):
        p = DONOR / "engines" / "lamborghini_veneno_lp750-4.edfbin"
        if not p.exists():
            self.skipTest("no donor")
        self.eng_bytes = p.read_bytes()

    def _check_header(self, b):
        self.assertEqual(b[:4], b"ShCB")
        total, count = struct.unpack_from("<IH", b, 8)
        self.assertEqual(total, len(b))
        end = 0x10 + 12 * count
        for k in range(count):
            sid, size, off = struct.unpack_from("<III", b, 0x10 + 12 * k)
            self.assertGreaterEqual(off, end)
            self.assertLessEqual(off + size, total)

    def test_resize_torque_table(self):
        e = P.Engine(self.eng_bytes)
        rows = [(float(r), -50.0 - r / 100, 500.0 + (r % 1000) / 10) for r in range(0, 12001, 250)]
        e.set_torque_curve(rows)
        b = e.to_bytes()
        self._check_header(b)
        e2 = P.Engine(b)
        got = e2.torque_curve()
        self.assertEqual(len(got), len(rows))
        for (a, bb, c), (x, y, z) in zip(rows, got):
            self.assertAlmostEqual(a, x, 3)
            self.assertAlmostEqual(bb, y, 3)
            self.assertAlmostEqual(c, z, 3)
        self.assertEqual(e2.rev_limit, 8500)          # entries after the table intact
        self.assertAlmostEqual(e2.displacement, 6.498, 3)
        # shrink
        e2.set_torque_curve(rows[:10])
        e3 = P.Engine(e2.to_bytes())
        self.assertEqual(len(e3.torque_curve()), 10)
        # resample to donor count
        e4 = P.Engine(self.eng_bytes)
        e4.set_torque_curve(rows, resize=False)
        self.assertEqual(len(P.Engine(e4.to_bytes()).torque_curve()), 26)

    def test_zero_and_codes(self):
        e = P.Engine(self.eng_bytes)
        e.set_torque_curve([(0, -10.0, 0.0), (1000, -20.0, 300.5)] + e.torque_curve()[2:])
        r = P.Engine(e.to_bytes()).torque_curve()
        self.assertEqual(r[0], (0.0, -10.0, 0.0))
        self.assertAlmostEqual(r[1][2], 300.5, 4)

    def test_gearbox_resize(self):
        g = P.Gearbox((DONOR / "gearbox" / "lamborghini_aventador_lp700-4.gdfbin").read_bytes())
        g.set_gear_cogs([(12, 40), (18, 38), (300, 301)])
        b = g.to_bytes()
        self._check_header(b)
        g2 = P.Gearbox(b)
        self.assertEqual(g2.gear_cogs(), [(12, 40), (18, 38), (300, 301)])
        self.assertEqual(g2.bevel, (38, 47))
        self.assertEqual(g2.final_drive, (15, 43))

    def test_new_value_and_groups_roundtrip(self):
        f = shcb.parse(self.eng_bytes)
        f.entries.append(shcb.new_value("deadbeef", [1.5, 0, 70000]))
        f.entries.append(shcb.new_value("cafef00d", 2.25))
        f2 = shcb.parse(shcb.serialize(f))
        self.assertEqual(f2.find("deadbeef").value, [1.5, 0, 70000])
        self.assertEqual(f2.find("deadbeef").codes, [shcb.C_F32, shcb.C_U8, shcb.C_I32])
        self.assertEqual(f2.find("cafef00d").value, 2.25)
        s = shcb.parse((DONOR / "suspension" / "lamborghini_veneno.sdfbin").read_bytes())
        g = next(e for e in s.entries if isinstance(e, shcb.Group))
        g.members[2].set_tuple([0.1, 0.2, 0.3])
        s2 = shcb.parse(shcb.serialize(s))
        g2 = next(e for e in s2.entries if isinstance(e, shcb.Group))
        self.assertAlmostEqual(g2.members[2].value[2], 0.3, 6)


DONORS = ["Lamborghini_Veneno", "Camaro_SS", "BMW_M4_GT3", "Formula_Classic_G1M1", "ARC_Camaro", "Kart_01"]


class TestAccessorsOnDonors(unittest.TestCase):
    def test_smoke(self):
        ensure_cache()
        for car in DONORS:
            with self.subTest(car=car):
                eng = P.Engine.load(cached(car, "engines", "*.edfbin"))
                rows = eng.torque_curve()
                self.assertGreaterEqual(len(rows), 10)
                self.assertTrue(all(rows[i][0] <= rows[i + 1][0] for i in range(len(rows) - 1)))
                self.assertGreater(eng.rev_limit, 3000)
                self.assertGreater(eng.max_torque(), 5)
                try:
                    d = eng.displacement
                    self.assertGreaterEqual(d, 0)
                except P.MissingField:
                    pass
                gb = P.Gearbox.load(cached(car, "gearbox", "*.gdfbin"))
                self.assertGreaterEqual(gb.gear_count, 1)
                gb.bevel, gb.final_drive
                ch = P.Chassis.load(cached(car, "chassis", "*.cdfbin"))
                self.assertGreater(ch.mass, 50)
                self.assertEqual(len(ch.inertia), 3)
                self.assertEqual(len(ch.spring_ranges()), 4)
                ap = ch.axle_points()
                self.assertAlmostEqual(ap["FL"][0], -ap["FR"][0], 4)
                self.assertLess(ap["FL"][2], ap["RL"][2])
                su = P.Suspension.load(cached(car, "suspension", "*.sdfbin"))
                w = su.wheel_centres()
                self.assertEqual(set(w), set(P.CORNERS))
                self.assertGreater(su.wheelbase, 0.8)
                tf, tr = su.tracks
                self.assertGreater(tf, 0.7)
                self.assertGreater(tr, 0.7)

    def test_set_geometry_all_donors(self):
        ensure_cache()
        for car in DONORS:
            with self.subTest(car=car):
                su = P.Suspension.load(cached(car, "suspension", "*.sdfbin"))
                wb, (tf, tr) = su.wheelbase, su.tracks
                su.set_geometry(wb + 0.1, tf + 0.04, tr - 0.02)
                su2 = P.Suspension(su.to_bytes())
                self.assertAlmostEqual(su2.wheelbase, wb + 0.1, 5)
                self.assertAlmostEqual(su2.tracks[0], tf + 0.04, 5)
                self.assertAlmostEqual(su2.tracks[1], tr - 0.02, 5)

    def test_missing_field_is_clear(self):
        ensure_cache()
        eng = P.Engine.load(cached("CART_Lola_B2K00_Ford", "engines", "*.edfbin"))
        with self.assertRaises(P.MissingField) as cm:
            eng.displacement
        self.assertIn("displacement", str(cm.exception))
        with self.assertRaises(P.MissingField):
            P.Chassis((DONOR / "gearbox" / "lamborghini_aventador_lp700-4.gdfbin").read_bytes()).mass

    def test_camaro_int_coded_torque(self):
        ensure_cache()
        eng = P.Engine.load(cached("Camaro_SS", "engines", "*.edfbin"))
        rows = eng.torque_curve()
        self.assertEqual(len(rows), 65)
        self.assertEqual(rows[64][0], 8000.0)
        self.assertEqual(rows[64][2], 285.0)            # stored as i32
        self.assertEqual(eng.rev_limit, 6550)


class TestBydReproduction(unittest.TestCase):
    """Reproduce scripts/build_byd_physics.py with the accessors and compare with its outputs."""

    def setUp(self):
        if not DONOR.exists() or not BYD_OUT.exists():
            self.skipTest("no donor / BYD build")

    def test_engine(self):
        power_w, peak, redline = 390_000, 1050.0, 8000
        base_rpm = power_w / (peak * 2 * math.pi / 60)
        power_rpms = [4000, 4500, 5000, 5500, 6000, 6500, 7000, 7500, 7800, 7900]
        rows = ([(445, -20.0)] + [(r, peak) for r in (450, 1000, 1500, 2000, 2500, 3000, round(base_rpm))]
                + [(r, power_w / (r * 2 * math.pi / 60)) for r in power_rpms]
                + [(redline, 0.0), (8100, -100.0), (8250, -150.0), (8500, -200.0), (9000, -300.0),
                   (9500, -350.0), (10500, -400.0)])
        e = P.Engine.load(DONOR / "engines" / "lamborghini_veneno_lp750-4.edfbin")
        cur = e.torque_curve()
        # the build script rewrote the 25 f32-coded rows (all but the first, rpm-0 row), keeping drag
        new = [cur[0]] + [(rpm, cur[i + 1][1], nm) for i, (rpm, nm) in enumerate(rows)]
        e.set_torque_curve(new)
        e.rev_limit = redline
        e.displacement = 0.0
        self.assertEqual(e.to_bytes(), (BYD_OUT / "engines" / "lamborghini_veneno_lp750-4.edfbin").read_bytes())

    def test_gearbox(self):
        g = P.Gearbox.load(DONOR / "gearbox" / "lamborghini_aventador_lp700-4.gdfbin")
        self.assertEqual(g.gear_count, 7)
        g.make_single_speed(cogs=(20, 20))
        g.bevel = (1, 1)
        g.final_drive = (11, 63)
        out = (BYD_OUT / "gearbox" / "lamborghini_aventador_lp700-4.gdfbin").read_bytes()
        ref = P.Gearbox(out)
        self.assertEqual(g.gear_cogs(), ref.gear_cogs())
        self.assertEqual(g.bevel, ref.bevel)
        self.assertEqual(g.final_drives(), ref.final_drives())
        self.assertEqual(g.to_bytes(), out)               # happens to be byte-identical too

    def test_chassis(self):
        c = P.Chassis.load(DONOR / "chassis" / "lamborghini_veneno.cdfbin")
        self.assertEqual(c.mass, 1570)
        ratio = 2185 / 1570
        c.mass = 2185
        c.inertia = [v * ratio * 0.9 for v in c.inertia]
        c.cg_height = 0.40
        c.scale_springs(ratio)
        self.assertAlmostEqual(c.axle_points_half_span, 1.351, 5)
        c.set_axle_z(-2.92 / 2, 2.92 / 2)
        self.assertEqual(c.to_bytes(), (BYD_OUT / "chassis" / "lamborghini_veneno.cdfbin").read_bytes())

    def test_suspension(self):
        s = P.Suspension.load(DONOR / "suspension" / "lamborghini_veneno.sdfbin")
        w = s.wheel_centres()
        self.assertAlmostEqual(w["FL"][0], 0.865, 5)
        self.assertAlmostEqual(w["RR"][0], -0.859048, 5)
        self.assertAlmostEqual(w["FL"][2], -1.351, 5)
        pts = [p for p in s.points() if p[2] is not None]
        self.assertEqual(len(pts), 48)                    # 8 wheel/upright bodies + 40 link points
        half_track = {"F": (0.865, 1.620 / 2), "R": (0.859, 1.625 / 2)}
        dwb = 2.92 / 2 - 1.351
        for c in P.CORNERS:
            donor_t, target_t = half_track[c[0]]
            dx = (target_t - donor_t) * (1 if c[1] == "L" else -1)
            dz = dwb * (1 if c[0] == "R" else -1)
            self.assertEqual(s.move_corner(c, dx, dz), 12)
        self.assertEqual(s.to_bytes(), (BYD_OUT / "suspension" / "lamborghini_veneno.sdfbin").read_bytes())
        # and the high-level helper lands on the same geometry
        s2 = P.Suspension.load(DONOR / "suspension" / "lamborghini_veneno.sdfbin")
        s2.set_geometry(2.92, 1.620, 2 * 0.859048 + (1.625 - 2 * 0.859))
        self.assertAlmostEqual(s2.wheelbase, 2.92, 5)


class TestVdfmStats(unittest.TestCase):
    def setUp(self):
        if not PERSIST.exists():
            self.skipTest("no PHYSICSPERSISTENT extraction")

    def test_vdfm_all(self):
        files = sorted((PERSIST / "vehicles").glob("*.vdfm"))
        self.assertGreater(len(files), 700)
        for p in files:
            b = p.read_bytes()
            d = P.read_vdfm(b)
            self.assertIn("engine", d)
            self.assertIn("gearbox", d)
            self.assertEqual(P.write_vdfm(b, {}), b, p.name)    # rebuild is byte-identical

    def test_vdfm_edit(self):
        b = (PERSIST / "vehicles" / "lamborghini_veneno.vdfm").read_bytes()
        d = P.read_vdfm(b)
        self.assertEqual(d["engine"], "lamborghini_veneno_lp750-4")
        self.assertEqual(d["clutch"], "GT_GT3")
        self.assertEqual(d["failures"], "Supercar")
        self.assertEqual(d["gearbox"], "lamborghini_aventador_lp700-4")
        self.assertEqual(d["chassis"], "lamborghini_veneno")
        out = P.write_vdfm(b, {"engine": "byd_ev_motor_with_a_longer_name", "gearbox": "byd_ev_1speed"},
                           new_id=True)
        d2 = P.read_vdfm(out)
        self.assertEqual(d2["engine"], "byd_ev_motor_with_a_longer_name")
        self.assertEqual(d2["gearbox"], "byd_ev_1speed")
        self.assertEqual(d2["suspension"], "lamborghini_veneno")
        self.assertNotEqual(d2["id"], d["id"])
        self.assertEqual(len(out) % 16, 0)
        with self.assertRaises(P.MissingField):
            P.write_vdfm((PERSIST / "vehicles" / "kart_01.vdfm").read_bytes(), {"clutch": "x"})

    def test_stats(self):
        b = (PERSIST / "statistics" / "lamborghini_veneno.mrdf").read_bytes()
        s = P.read_stats(b)
        self.assertEqual(s["mass_kg"], 1570.0)
        self.assertEqual(s["gear_count"], 7)
        self.assertAlmostEqual(s["displacement_l"], 6.498, 3)
        out = P.write_stats(b, {"mass_kg": 2185, "gear_count": 1, "torque_nm": 670})
        s2 = P.read_stats(out)
        self.assertEqual((s2["mass_kg"], s2["gear_count"], s2["torque_nm"]), (2185.0, 1, 670.0))
        self.assertEqual(len(out), len(b))


if __name__ == "__main__":
    unittest.main(verbosity=2)
