"""Read/update Pakfiles\\PakDirInfo.dat, the game's registry of known paks.

Layout: "RIDP", u32 0x10000000, u32 count, u32 0, then count entries of
  u64 uid of the pak path (e.g. pakfiles\\vehicles\\x.bff)
  u32 metadata bytes (end of DHSA block, or data offset when there is none)
  u32 largest load-group stored span   (largest file when ungrouped)
  u32 largest load-group original size (largest file when ungrouped)
  u32 flags (0x31 on every entry)
"""
import struct
from pathlib import Path
from . import pak_tool as t

MAGIC = b"RIDP"
FLAGS = 0x31


def read(path):
    b = Path(path).read_bytes()
    magic, ver, n, _ = struct.unpack_from("<4sIII", b, 0)
    assert magic == MAGIC
    return ver, [struct.unpack_from("<QIIII", b, 16 + i * 24) for i in range(n)]


def write(path, ver, entries):
    out = bytearray(struct.pack("<4sIII", MAGIC, ver, len(entries), 0))
    for e in entries:
        out += struct.pack("<QIIII", *e)
    Path(path).write_bytes(bytes(out))


def entry_for(pak_file, rel_path):
    """Compute the registry entry for a pak file; rel_path like pakfiles\\vehicles\\x.bff."""
    b = Path(pak_file).read_bytes()
    data_off, = struct.unpack_from("<Q", b, 12)
    sec_pos, sec_size = struct.unpack_from("<II", b, 0x124)
    pak = t.read_pak(pak_file)
    grouped = set()
    spans, origs = [], []
    if pak.groups:
        for first, cnt in pak.groups:
            idx = range(first, first + cnt)
            grouped.update(idx)
            positions = _positions(b, first, cnt)
            last = first + cnt - 1
            spans.append(positions[-1] + len(pak.entries[last].stored) - positions[0])
            origs.append(sum(pak.entries[i].orig_size for i in idx))
    for i, e in enumerate(pak.entries):
        if i not in grouped:
            spans.append(len(e.stored))
            origs.append(e.orig_size)
    meta = sec_pos + sec_size if sec_size else data_off
    return (t.path_uid(rel_path), meta, max(spans), max(origs), FLAGS)


def _positions(b, first, cnt):
    return [struct.unpack_from("<Q", b, t.HEADER_SIZE + i * t.TOC_ENTRY + 8)[0] for i in range(first, first + cnt)]
