"""Read and write unencrypted AMS2 .bff paks.

Layout (all little-endian):
  header 0x130 | TOC count*0x2A | ext header 0x308 | ext entries count*0x10 |
  names (1-byte length + path, no terminator) | zero pad to 16 |
  DHSA load-group block | zero pad to 16 | file data, each aligned to 16.

The game checks each TOC CRC against ~crc32(bytes as stored) and accepts
encryption type 0, so no encryption is needed. Hashing ported from
Nenkai/PCarsTools BHashCode (lookup8).
"""
import struct, zlib
from dataclasses import dataclass, field
from pathlib import Path

HEADER_SIZE = 0x130
TOC_ENTRY = 0x2A
EXT_HEADER = 0x308
PAK_ID = b" KAP"
PAK_VERSION = 0x10400004
EXT_ID = 0x45585420
SECTOR = 16
TYPE_NONE, TYPE_ZLIB = 0, 1
M64 = (1 << 64) - 1


def _mix64(a, b, c):
    a = (a - b - c) & M64; a ^= c >> 43
    b = (b - c - a) & M64; b ^= (a << 9) & M64
    c = (c - a - b) & M64; c ^= b >> 8
    a = (a - b - c) & M64; a ^= c >> 38
    b = (b - c - a) & M64; b ^= (a << 23) & M64
    c = (c - a - b) & M64; c ^= b >> 5
    a = (a - b - c) & M64; a ^= c >> 35
    b = (b - c - a) & M64; b ^= (a << 49) & M64
    c = (c - a - b) & M64; c ^= b >> 11
    a = (a - b - c) & M64; a ^= c >> 12
    b = (b - c - a) & M64; b ^= (a << 18) & M64
    c = (c - a - b) & M64; c ^= b >> 22
    return a, b, c


def path_uid(path):
    """64-bit uid of a pak path (lower-cased, backslashes)."""
    k = path.lower().replace("/", "\\").encode("latin-1")
    if not k:
        return 0x8DB63936938575BF
    a = b = 0
    c = 0x9E3779B97F4A7C13
    i, rem = 0, len(k)
    be = lambda s: int.from_bytes(s, "big")
    while rem >= 24:
        a = (a + be(k[i:i + 8])) & M64
        b = (b + be(k[i + 8:i + 16])) & M64
        c = (c + be(k[i + 16:i + 24])) & M64
        a, b, c = _mix64(a, b, c)
        i += 24; rem -= 24
    c = (c + len(k)) & M64
    for j in range(rem):  # byte j of the tail; c's low byte is reserved for the length
        v = k[i + j]
        if j < 8:
            a = (a + (v << (8 * j))) & M64
        elif j < 16:
            b = (b + (v << (8 * (j - 8)))) & M64
        else:
            c = (c + (v << (8 * (j - 15)))) & M64
    return _mix64(a, b, c)[2]


@dataclass
class Entry:
    path: str
    stored: bytes          # bytes as they sit in the pak (compressed if ctype is zlib)
    orig_size: int
    ctype: int = TYPE_ZLIB
    mtime: int = 0
    pad: int = 4

    @classmethod
    def from_file(cls, path, data, mtime=0, compress=True):
        if compress:
            return cls(path, zlib.compress(data, 6), len(data), TYPE_ZLIB, mtime)
        return cls(path, bytes(data), len(data), TYPE_NONE, mtime)

    def data(self):
        return zlib.decompress(self.stored) if self.ctype == TYPE_ZLIB else self.stored


@dataclass
class Pak:
    name: str
    entries: list
    groups: list = field(default_factory=list)  # (first index, count)
    config: str = "Reiza.xml"
    platform: str = "PC"


def read_pak(path):
    b = Path(path).read_bytes()
    assert b[:4] == PAK_ID, "not a pak"
    count, = struct.unpack_from("<I", b, 8)
    toc_size, _crc, ext_size, sec_pos, sec_size = struct.unpack_from("<5I", b, 0x118)
    assert b[0x12D] == 0, "pak is encrypted; run pak_decrypt_twin.py first"
    name = b[0x18:0x118].split(b"\0")[0].decode()
    ext = HEADER_SIZE + toc_size
    config = b[ext + 8:ext + 0x108].split(b"\0")[0].decode()
    platform = b[ext + 0x208:ext + 0x308].split(b"\0")[0].decode()
    entries = []
    for i in range(count):
        uid, pos, size, orig, mtime, ctype, pad, crc = struct.unpack_from("<QQIIQBBI", b, HEADER_SIZE + i * TOC_ENTRY)
        no, = struct.unpack_from("<Q", b, ext + EXT_HEADER + i * 16)
        p = b[no + 1:no + 1 + b[no]].decode("latin-1")
        assert path_uid(p) == uid, f"uid mismatch for {p}"
        entries.append(Entry(p, b[pos:pos + size], orig, ctype, mtime, pad))
    groups = None  # some paks (e.g. liveries) have no DHSA block
    if sec_size:
        sec = b[sec_pos:sec_pos + sec_size]
        assert sec[:4] == b"DHSA"
        ngroups, = struct.unpack_from("<I", sec, 8)
        groups = [struct.unpack_from("<II", sec, 16 + i * 16) for i in range(ngroups)]
    return Pak(name, entries, groups, config, platform)


def _align(n, a=SECTOR):
    return (n + a - 1) // a * a


def write_pak(pak, path):
    n = len(pak.entries)
    toc_size = n * TOC_ENTRY
    ext_start = HEADER_SIZE + toc_size
    names_start = ext_start + EXT_HEADER + n * 16
    names, name_offs = bytearray(), []
    for e in pak.entries:
        raw = e.path.replace("/", "\\").encode("latin-1")
        assert len(raw) < 256, e.path
        name_offs.append(names_start + len(names))
        names += bytes([len(raw)]) + raw
    ext_size = EXT_HEADER + n * 16 + len(names)
    if pak.groups is None:
        sec_pos = sec_size = 0
        data_off = _align(ext_start + ext_size)
    else:
        sec_pos = _align(ext_start + ext_size)
        sec_size = 16 + 16 * len(pak.groups)
        data_off = _align(sec_pos + sec_size)

    positions, cur = [], data_off
    for e in pak.entries:
        positions.append(cur)
        cur = _align(cur + len(e.stored))
    end = positions[-1] + len(pak.entries[-1].stored)

    out = bytearray(end)
    struct.pack_into("<4sIIQI", out, 0, PAK_ID, PAK_VERSION, n, data_off, SECTOR)
    out[0x18:0x18 + len(pak.name)] = pak.name.encode()
    struct.pack_into("<5IBB", out, 0x118, toc_size, 0, ext_size, sec_pos, sec_size, 0, 0)

    for i, (e, pos) in enumerate(zip(pak.entries, positions)):
        ext3 = e.path.rsplit(".", 1)[-1][:3].encode().ljust(4, b"\0")
        struct.pack_into("<QQIIQBBI4s", out, HEADER_SIZE + i * TOC_ENTRY, path_uid(e.path), pos,
                         len(e.stored), e.orig_size, e.mtime, e.ctype, e.pad,
                         ~zlib.crc32(e.stored) & 0xFFFFFFFF, ext3)
        out[pos:pos + len(e.stored)] = e.stored

    struct.pack_into("<II", out, ext_start, EXT_ID, ext_size - EXT_HEADER)
    out[ext_start + 8:ext_start + 8 + len(pak.config)] = pak.config.encode()
    out[ext_start + 0x208:ext_start + 0x208 + len(pak.platform)] = pak.platform.encode()
    for i, (e, no) in enumerate(zip(pak.entries, name_offs)):
        struct.pack_into("<QQ", out, ext_start + EXT_HEADER + i * 16, no, e.mtime)
    out[names_start:names_start + len(names)] = names

    if pak.groups is None:
        Path(path).write_bytes(bytes(out))
        return len(out)
    struct.pack_into("<4sIII", out, sec_pos, b"DHSA", 0x10000000, len(pak.groups), 0)
    for i, (first, cnt) in enumerate(pak.groups):
        last = first + cnt - 1
        span = positions[last] + len(pak.entries[last].stored) - positions[first]
        struct.pack_into("<IIQ", out, sec_pos + 16 + i * 16, first, cnt, span)

    Path(path).write_bytes(bytes(out))
    return len(out)
