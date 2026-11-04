"""Extract selected files from an encrypted AMS2 pak without decrypting the rest.

  python -m ams2kit.pak_extract <pak> <out_dir> <substring> [<substring> ...]
"""
import struct, sys, zlib
from pathlib import Path
from . import pak_decrypt_twin as d

KEYS_CS = str(Path(__file__).with_name("BPakFileEncryption.cs"))


def open_pak(path):
    f = open(path, "rb")
    hdr = f.read(0x130)
    h = d.parse_header(hdr)
    data_off, = struct.unpack_from("<Q", hdr, 12)
    f.seek(0)
    meta = f.read(data_off)
    keys = [d.deobfuscate(k.split(b"\x00")[0]) for k in d.load_keys(KEYS_CS)]
    toc_raw = meta[0x130:0x130 + h["toc_size"]]
    key = next(k for k in keys if (x := d.rc4(k, toc_raw[:64]))[14] == 0 and x[15] == 0)
    toc = d.rc4(key, toc_raw)
    ext_entries, ext_len = d.ext_region(meta, h)
    ext = d.Scribe().decrypt(meta[ext_entries:ext_entries + ext_len])
    entries = []
    for i in range(h["count"]):
        uid, pos, size, orig, mtime, ctype, pad, crc = struct.unpack_from("<QQIIQBBI", toc, i * d.TOC_ENTRY)
        no, = struct.unpack_from("<Q", ext, i * 16)
        rel = no - ext_entries
        entries.append((ext[rel + 1:rel + 1 + ext[rel]].decode("latin-1"), pos, size, orig, ctype))
    return f, key, entries


OODLE_DLL = None   # path of the game's oo2core_4_win64.dll; None = look in the AMS2 folder (ams2kit.game)
_oodle = None


def _oodle_dll():
    if OODLE_DLL:
        return OODLE_DLL
    from . import game
    g = game.find_game()
    if not g:
        raise FileNotFoundError("Automobilista 2 not found: Oodle-compressed files need the game's oo2core_4_win64.dll")
    return str(g / "oo2core_4_win64.dll")


def oodle_decompress(data, orig):
    global _oodle
    import ctypes
    if _oodle is None:
        if not hasattr(ctypes, "WinDLL"):
            raise RuntimeError("Oodle-compressed pak entries need Windows (the decoder is the game's oo2core_4_win64.dll)")
        _oodle = ctypes.WinDLL(_oodle_dll()).OodleLZ_Decompress
        _oodle.restype = ctypes.c_int64
        # src, srcLen, dst, dstLen, fuzzSafe, checkCRC, verbosity, decBufBase, decBufSize,
        # callback, callbackData, decoderMemory, decoderMemorySize, threadPhase
        _oodle.argtypes = [ctypes.c_char_p, ctypes.c_int64, ctypes.c_char_p, ctypes.c_int64] + \
            [ctypes.c_int] * 3 + [ctypes.c_void_p, ctypes.c_int64] + [ctypes.c_void_p] * 3 + \
            [ctypes.c_int64, ctypes.c_int]
    out = ctypes.create_string_buffer(orig)
    n = _oodle(data, len(data), out, orig, 0, 0, 0, None, 0, None, None, None, 0, 3)
    return out.raw[:n]


def read_entry(f, key, entry):
    path, pos, size, orig, ctype = entry
    f.seek(pos)
    data = d.rc4(key, f.read(size))
    if ctype == 1:
        data = zlib.decompress(data) if data[:2] == b"\x78\x9c" else zlib.decompress(data, -15)
    elif ctype in (3, 4):
        data = oodle_decompress(data, orig)
    elif ctype != 0:
        raise ValueError(f"compression type {ctype} not supported for {path}")
    return data


if __name__ == "__main__":
    pak, out = sys.argv[1], Path(sys.argv[2])
    subs = [s.lower() for s in sys.argv[3:]]
    f, key, entries = open_pak(pak)
    for e in entries:
        if any(s in e[0].lower() for s in subs):
            dst = out / Path(*e[0].split("\\"))
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(read_entry(f, key, e))
            print(e[0], dst.stat().st_size)
