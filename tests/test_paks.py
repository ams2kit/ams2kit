"""Tests for decrypting base-game paks (ams2kit.pak_decrypt_twin / pak_extract).

Run:  python -m unittest discover -s tests -v   (from the repository root)
Reads encrypted paks from the game install (read-only); outputs go to a temp dir.
VW_Virtus_GTS_Livery.bff has an encrypted ext region whose length is not a multiple of
16 and vehiclespersistent.bff has plain zero blocks after the encrypted part.
"""
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ams2kit import pak_decrypt_twin as d, pak_extract as pe, pak_tool as pt  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import VEHICLE_PAKS  # noqa: E402

PAKS = VEHICLE_PAKS
SAMPLE = ["VW_Virtus_GTS_Livery.bff", "VW_Virtus_Livery.bff", "BMW_2002_Turbo_SC_Livery.bff",
          "Lamborghini_Veneno_Livery.bff", "vehiclespersistent.bff"]


def decompress(data, orig, ctype):
    if ctype == 1:
        return zlib.decompress(data) if data[:2] == b"\x78\x9c" else zlib.decompress(data, -15)
    if ctype in (3, 4):
        return pe.oodle_decompress(data, orig)
    return data


@unittest.skipUnless(PAKS.is_dir(), "AMS2 install not found")
class TestDecryptTwin(unittest.TestCase):
    def test_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in SAMPLE:
                with self.subTest(pak=name):
                    src, dst = PAKS / name, Path(tmp) / name
                    h, _, entries = d.twin(src, dst, pe.KEYS_CS)
                    b = dst.read_bytes()
                    self.assertEqual(b[d.ENC_OFFSET], 0)
                    pak = pt.read_pak(dst)  # also checks every path against its TOC uid
                    self.assertEqual([e.path for e in pak.entries], [e[0] for e in entries])
                    for i, (path, pos, size, orig, ctype) in enumerate(entries):
                        data = b[pos:pos + size]
                        crc, = struct.unpack_from("<I", b, d.HEADER_SIZE + i * d.TOC_ENTRY + d.TOC_CRC)
                        self.assertEqual(crc, ~zlib.crc32(data) & 0xFFFFFFFF, path)
                        self.assertEqual(len(decompress(data, orig, ctype)), orig, path)
                    # decrypted ext padding is all zeros
                    start, length = d.ext_region(PAKS.joinpath(name).read_bytes()[:0x100000], h)
                    need = (h["ext_size"] - d.EXT_HEADER + 15) & ~15
                    self.assertFalse(any(b[start + need:start + length]))
                    dst.unlink()

    def test_open_pak_matches_twin_paths(self):
        f, key, entries = pe.open_pak(PAKS / "VW_Virtus_GTS_Livery.bff")
        with f:
            self.assertTrue(entries and all(e[0].startswith("vehicles\\") for e in entries))
            e = entries[0]
            self.assertEqual(len(pe.read_entry(f, key, e)), e[3])


if __name__ == "__main__":
    unittest.main()
