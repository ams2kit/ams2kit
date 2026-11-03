"""One interface over encrypted (base game) and plain (ours) .bff paks."""
import struct
from pathlib import Path

from . import pak_decrypt_twin as dec
from . import pak_extract as enc
from . import pak_tool

HEADER_SIZE = 0x130


def is_encrypted(path):
    with open(path, "rb") as f:
        hdr = f.read(HEADER_SIZE)
    return hdr[dec.ENC_OFFSET] != 0


class PakReader:
    """Read-only view of a pak: `.paths` (in TOC order) and `.read(path)`."""

    def __init__(self, path):
        self.path = Path(path)
        self.encrypted = is_encrypted(path)
        if self.encrypted:
            self._f, self._key, ents = enc.open_pak(str(path))
            self._ents = {e[0].lower(): e for e in ents}
            self.paths = [e[0] for e in ents]
        else:
            self._pak = pak_tool.read_pak(path)
            self._ents = {e.path.lower(): e for e in self._pak.entries}
            self.paths = [e.path for e in self._pak.entries]

    def __contains__(self, path):
        return path.lower() in self._ents

    def read(self, path):
        e = self._ents[path.lower()]
        return enc.read_entry(self._f, self._key, e) if self.encrypted else e.data()

    def close(self):
        if self.encrypted:
            self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def decrypt_to_plain(src, dst):
    """Unencrypted copy of a base-game pak with recomputed CRCs (loadable by the game)."""
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    if not is_encrypted(src):
        Path(dst).write_bytes(Path(src).read_bytes())
        return
    dec.twin(str(src), str(dst), enc.KEYS_CS)


def find(paks, predicate):
    """Yield (pak_path, file_path) for files whose lower-case path satisfies predicate."""
    for p in paks:
        try:
            with PakReader(p) as r:
                for f in r.paths:
                    if predicate(f.lower()):
                        yield p, f
        except (OSError, ValueError, StopIteration, AssertionError, struct.error):
            continue


read_plain = pak_tool.read_pak
write_plain = pak_tool.write_pak
Entry = pak_tool.Entry
