"""Sound kits and FMOD bank sample replacement (sound.py, docs/16).

    python -m unittest tests.test_sound -v        (from the repository root)
"""
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import GAME  # noqa: E402
from ams2kit import game, physics, sound  # noqa: E402

AUDIO = GAME / "Audio"
VENENO = AUDIO / "AMS2" / "Vehicles" / "Sort" / "L" / "Lamborghini_Veneno_AMS2.bank"


def tone(seconds, hz, ch=2, rate=48000):
    t = np.arange(int(seconds * rate))
    x = (8000 * np.sin(2 * np.pi * hz * t / rate)).astype(np.int16)
    return np.stack([x] * ch, 1)


def mini_bank(fsb):
    """The smallest bank rebuild_bank needs: FMT, PROJ (one waveform, SNDH, STDT) and one SND chunk."""
    def chunk(cid, body):
        return cid + struct.pack("<I", len(body)) + body + b"\0" * (len(body) & 1)

    def lst(kind, body):
        return chunk(b"LIST", kind + body)
    wav = chunk(b"WAV ", os.urandom(16) + struct.pack("<HHHII", 0x0C, 0, 0, 0, 1))
    head = chunk(b"FMT ", struct.pack("<II", 0x50, 0x46))
    proj_wo_sndh = lst(b"WAVS", chunk(b"LCNT", struct.pack("<I", 1)) + wav)
    sndh_size, stdt = 12, chunk(b"STDT", b"")
    proj_len = 4 + len(proj_wo_sndh) + 8 + sndh_size + len(stdt)
    start = 12 + len(head) + 8 + proj_len + 8
    pad = -start % 32
    sndh = chunk(b"SNDH", struct.pack("<HHII", 3, 8, start + pad, len(fsb)))
    body = head + lst(b"PROJ", proj_wo_sndh + sndh + stdt) + chunk(b"SND ", bytes(pad) + fsb)
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"FEV " + body


class FsbAndWavTest(unittest.TestCase):
    def test_pcm_fsb_roundtrip(self):
        samples = [{"name": "idle", "pcm": tone(0.5, 110), "rate": 48000, "loop": [10, 23999]},
                   {"name": "odd_rate", "pcm": tone(0.3, 220, ch=1, rate=37000), "rate": 37000, "loop": None}]
        f = sound.build_fsb_pcm16(samples)
        parsed = sound.parse_fsb(f, 0)
        self.assertEqual(parsed["mode"], sound.MODE_PCM16)
        self.assertEqual(parsed["size"], len(f))
        for s, want in zip(parsed["samples"], samples):
            self.assertEqual((s["name"], s["rate"], s["channels"], s["frames"], s["loop"]),
                             (want["name"], want["rate"], want["pcm"].shape[1], len(want["pcm"]), want["loop"]))
            self.assertEqual(s["offset"] % 32, 0)
            got = sound.decode_pcm16(f[s["data_at"]:s["data_at"] + s["size"]], s["channels"], s["frames"])
            self.assertTrue(np.array_equal(got, want["pcm"]))

    def test_wav_roundtrip_keeps_loop(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "a.wav"
            sound.write_wav(p, tone(0.2, 440), 44100, [100, 8000])
            w = sound.read_wav(p)
            self.assertEqual((w["rate"], w["loop"], w["pcm"].shape), (44100, [100, 8000], (9600, 2)))

    def test_rebuild_points_waveform_at_new_block(self):
        old = sound.build_fsb_pcm16([{"name": "old", "pcm": tone(0.1, 100), "rate": 48000}])
        bank = sound.Bank(mini_bank(old))
        self.assertEqual([(w[1], w[2]) for w in bank.waves], [(0, 0)])
        new = sound.Bank(sound.rebuild_bank(bank, {(0, 0): {"name": "new", "pcm": tone(0.2, 300, ch=1), "rate": 48000}}))
        self.assertEqual(len(new.fsbs), 2)
        self.assertEqual([(w[1], w[2]) for w in new.waves], [(1, 0)])
        self.assertEqual(new.data[new.fsbs[0]["offset"]:new.fsbs[0]["offset"] + len(old)], old)
        self.assertTrue(all(f["offset"] % 32 == 0 for f in new.fsbs))
        self.assertTrue(np.array_equal(sound.decode(new, 1, 0), tone(0.2, 300, ch=1)))


@unittest.skipUnless(VENENO.exists(), "game not installed")
class GameSoundTest(unittest.TestCase):
    def test_every_csdbin_roundtrips_and_rewrites(self):
        cars = game.list_cars(GAME)
        self.assertGreater(len(cars), 200)
        for c in cars:
            d = sound.car_csd(GAME, c)
            self.assertEqual(sound.write_csd(d, {}), d, c["name"])
            banks = sound.csd_banks(d)
            self.assertTrue(sound.own_banks(banks), c["name"])
            new = sound.write_csd(d, {banks[0]: "Audio/AMS2KIT/Test/" + banks[0].rsplit("/", 1)[-1]})
            self.assertTrue(physics.serial_layout_ok(new), c["name"])
            self.assertEqual(sound.csd_banks(new)[0], "Audio/AMS2KIT/Test/" + banks[0].rsplit("/", 1)[-1])

    def test_fadpcm_matches_frame_history(self):
        """Each frame stores the encoder's last two input samples; a correct decoder ends the previous
        frame of that channel within a few LSB of them (a wrong coefficient table is off by thousands)."""
        bank = sound.Bank(VENENO.read_bytes())
        errs = []
        for fsb, j, s in bank.samples():
            if bank.fsbs[fsb]["mode"] != sound.MODE_FADPCM:
                continue
            raw = bank.data[s["data_at"]:s["data_at"] + s["size"]]
            ch, n = s["channels"], len(raw) // sound.FADPCM_FRAME
            hist = np.frombuffer(raw[:n * sound.FADPCM_FRAME], np.uint8).reshape(n, -1)[:, 8:10].copy().view("<i2")[:, 0]
            pcm = sound.decode_fadpcm(raw, ch, 10 ** 9).astype(int)
            errs += [abs(pcm[(f // ch) * 256 - 1, f % ch] - hist[f]) for f in range(ch, n)]
        self.assertGreater(len(errs), 1000)
        self.assertLess(np.median(errs), 64)

    def test_rebuild_real_bank(self):
        bank = sound.Bank(VENENO.read_bytes())
        vorbis = next((i, j) for i, j, _ in bank.samples() if bank.fsbs[i]["mode"] == sound.MODE_VORBIS)
        new = sound.Bank(sound.rebuild_bank(bank, {vorbis: {"name": "x", "pcm": tone(1, 150), "rate": 48000}}))
        self.assertEqual(len(new.fsbs), len(bank.fsbs) + 1)
        for a, b in zip(bank.fsbs, new.fsbs):
            self.assertEqual(bank.data[a["offset"]:a["offset"] + a["size"]], new.data[b["offset"]:b["offset"] + b["size"]])
        moved = [w for w in new.waves if w[1] == len(bank.fsbs)]
        self.assertEqual(len(moved), 1)
        self.assertEqual(len(new.waves), len(bank.waves))


if __name__ == "__main__":
    unittest.main()
