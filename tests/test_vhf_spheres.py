"""build.vhf_fit_spheres: culling spheres grow to cover rebuilt meshes (Jetta GLI build, 2026-11-03)."""
import re
import unittest

from ams2kit import build

VHF = """<?xml version="1.0" encoding="utf-8"?>
<CAR Name="X">
    <NODE type="HIERARCHY" Name="Root" MatrixNumber="0" matrices="2" subobjects="2">
        <SPHERE Centre="0.000000 0.500000 0.000000 1.000000" Radius="3.000000" />
        <MATRIX id="0" Offset="0.000000 0.000000 0.000000" Orientation="0.000000 0.000000 0.000000 1.000000" Scale="1.000000" />
        <MATRIX id="1" Offset="0.000000 0.000000 0.000000" Orientation="0.000000 0.000000 0.000000 1.000000" Scale="1.000000" parent="0" />
        <NODE type="LOD" Name="BODY_LOD0" MatrixNumber="1" subobjects="1">
            <SPHERE Centre="0.000000 0.500000 0.000000 1.000000" Radius="2.000000" />
            <NODE type="OBJECT" Name="BODY_LODA" MatrixNumber="1" instances="1" userflags="0">
                <RESOURCE Filename="vehicles\\x\\body_loda.meb" />
                <SPHERE Centre="0.000000 0.500000 0.000000 1.000000" Radius="2.000000" />
            </NODE>
        </NODE>
        <MATRIX id="2" Offset="0.700000 0.300000 1.400000" Orientation="0.000000 0.000000 0.000000 1.000000" Scale="1.000000" parent="0" />
        <NODE type="LOD" Name="WHEEL_LR_LOD0" MatrixNumber="2" subobjects="1">
            <SPHERE Centre="0.000000 0.000000 0.000000 1.000000" Radius="0.330000" />
            <NODE type="OBJECT" Name="WHEEL_LR_LODA" MatrixNumber="2" instances="1" userflags="0">
                <RESOURCE Filename="vehicles\\x\\wheel_lr_loda.meb" />
                <SPHERE Centre="0.000000 0.000000 0.000000 1.000000" Radius="0.330000" />
            </NODE>
        </NODE>
    </NODE>
</CAR>
"""


def spheres(text):
    return [(float(r), [float(v) for v in c.split()[:3]])
            for c, r in re.findall(r'<SPHERE Centre="([^"]+)" Radius="([^"]+)"', text)]


class VhfSpheres(unittest.TestCase):
    def test_noop(self):
        out, n = build.vhf_fit_spheres(VHF, {})
        self.assertEqual((out, n), (VHF, 0))

    def test_small_mesh_keeps_sphere(self):
        out, n = build.vhf_fit_spheres(VHF, {"vehicles\\x\\body_loda.meb": (0, 0.5, 0, 1.0)})
        self.assertEqual(n, 0)

    def test_grows_object_parents_and_root(self):
        out, n = build.vhf_fit_spheres(VHF, {"vehicles\\x\\body_loda.meb": (0, 0.5, 0.5, 2.6)})
        s = spheres(out)
        self.assertEqual(n, 3)                       # object, LOD group, root
        root, lod, obj = s[0], s[1], s[2]
        self.assertGreaterEqual(obj[0], 2.6 - 1e-6)
        self.assertGreaterEqual(lod[0], 2.6 - 1e-6)
        self.assertGreaterEqual(root[0], 3.0)
        self.assertEqual(s[3:], spheres(VHF)[3:])    # the wheel is untouched

    def test_child_in_offset_frame(self):
        out, n = build.vhf_fit_spheres(VHF, {"vehicles\\x\\wheel_lr_loda.meb": (0, 0, 0, 0.5)})
        root = spheres(out)[0]
        # wheel at (0.7, 0.3, 1.4) r 0.5 must be inside the root sphere
        d = sum((a - b) ** 2 for a, b in zip(root[1], (0.7, 0.3, 1.4))) ** 0.5
        self.assertLessEqual(d + 0.5, root[0] + 1e-5)


if __name__ == "__main__":
    unittest.main()
