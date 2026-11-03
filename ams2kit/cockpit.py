"""Cockpit properties files (`vehicles\\<car>\\<car>_cockpit.bin`, crd prop "Cockpit properties").

Format (docs/10): a serialized C++ struct with a pointer-relocation table.

    0x00  51 02 01 NN 08 00 01 04   magic/version; NN = number of sections + 1 (5, 3 or 2)
    0x08  u64  lookup8 uid of the file's own resource path (pak_tool.path_uid, lower case)
    0x10  u32  data size
    0x14  u8 1, u8 unknown (0..15), u16 0
    0x18  (u32 size, u32 tag) x (NN-1)  section table; tag low byte = kind:
              0x10 pointer relocations: u64 data offsets of pointer fields (pointers are data-relative)
              0x32 enum-name string pool (e.g. "eGauge_Tach\\0...")
              0x33 enum fixups: (u64 field offset in data, u64 offset in the enum pool)
              0x50 type table: u32 count + count x (u32 type hash, u16 version, 2 chars)
    data at align16(end of section table), then each section at the next 16-byte boundary,
    file padded to 16.

The game loads the cockpit model from `<car folder>\\` + the string at data+0x10
(`Camaro_SS_Cockpit.vhf`). If that model is missing, the game crashes when the car loads.
"""
import re
import struct

from . import pak_tool

MAGIC = b"\x51\x02\x01"
KIND_RELOC, KIND_ENUMSTR, KIND_FIXUP, KIND_TYPES = 0x10, 0x32, 0x33, 0x50

# string pointer fields of the cockpit properties struct (data offsets)
F_GEARSHIFT_NODE = 0x00   # node in the cockpit .vhf, e.g. CAMARO_SS_GEARSHIFT_CPIT (may be null)
F_CONTAINER = 0x08        # "Container"
F_COCKPIT_VHF = 0x10      # cockpit render model, resolved in the car's own folder
F_DISPLAY = 0x18          # HUD/dashboard display name, e.g. display_camaro_ss (may be null)
STRING_FIELDS = {F_GEARSHIFT_NODE: "gearshift_node", F_CONTAINER: "container",
                 F_COCKPIT_VHF: "cockpit_vhf", F_DISPLAY: "display"}


def _a16(x):
    return (x + 15) & ~15


class CockpitBin:
    def __init__(self, data: bytes):
        if data[:3] != MAGIC:
            raise ValueError("not a cockpit properties file (magic)")
        self.head = bytearray(data[:0x18])
        self.uid, = struct.unpack_from("<Q", data, 8)
        size, = struct.unpack_from("<I", data, 0x10)
        nsec = data[3] - 1
        self.sections = []   # [tag, bytes]
        tbl = [struct.unpack_from("<II", data, 0x18 + 8 * i) for i in range(nsec)]
        self.table_end = 0x18 + 8 * nsec
        start = _a16(self.table_end)
        self.header_pad = data[self.table_end:start]
        self.data = bytearray(data[start:start + size])
        o = start + size
        for sz, tag in tbl:
            o = _a16(o)
            self.sections.append([tag, bytes(data[o:o + sz])])
            o += sz
        if _a16(o) != len(data):
            raise ValueError(f"layout mismatch: computed {_a16(o):#x}, file {len(data):#x}")

    # -- sections
    def section(self, kind):
        for tag, raw in self.sections:
            if tag & 0xFF == kind:
                return raw
        return b""

    @property
    def relocs(self):
        raw = self.section(KIND_RELOC)
        return [v for (v,) in struct.iter_unpack("<Q", raw)]

    @property
    def enum_fixups(self):
        raw, pool = self.section(KIND_FIXUP), self.section(KIND_ENUMSTR)
        out = []
        for field, soff in struct.iter_unpack("<QQ", raw):
            out.append((field, pool[soff:pool.index(b"\0", soff)].decode("ascii", "replace")))
        return out

    # -- pointers and strings
    def ptr(self, field):
        return struct.unpack_from("<Q", self.data, field)[0] if field in self.relocs else None

    def cstr(self, off):
        end = self.data.index(b"\0", off)
        return self.data[off:end].decode("latin-1")

    def get_string(self, field):
        p = self.ptr(field)
        return None if p is None else self.cstr(p)

    def strings(self):
        return {name: self.get_string(f) for f, name in STRING_FIELDS.items()}

    def set_string(self, field, s):
        """Point `field` at string `s`: overwrite in place when it fits and nothing else shares the
        old string, otherwise append it to the end of the data block (all offsets are data-relative,
        so appending moves nothing)."""
        p = self.ptr(field)
        if p is None:
            raise KeyError(f"field {field:#x} is not a pointer in this file")
        new = s.encode("latin-1") + b"\0"
        old_len = len(self.cstr(p)) + 1
        shared = [f for f in self.relocs if f != field and struct.unpack_from("<Q", self.data, f)[0] == p]
        if len(new) <= old_len and not shared:
            self.data[p:p + old_len] = new.ljust(old_len, b"\0")
        else:
            off = len(self.data)
            self.data += new
            struct.pack_into("<Q", self.data, field, off)

    def set_resource_path(self, path):
        self.uid = pak_tool.path_uid(path.lower())

    # -- write
    def to_bytes(self):
        head = bytearray(self.head)
        struct.pack_into("<Q", head, 8, self.uid)
        struct.pack_into("<I", head, 0x10, len(self.data))
        # byte 0x15 / tag byte 1 = the section's pad to 16: the game rejects the file unless
        # header + sum(size + pad) == file length (docs/12)
        head[0x15] = -len(self.data) % 16
        out = bytearray(head)
        for tag, raw in self.sections:
            tag = (tag & ~0xFF00) | ((-len(raw) % 16) << 8)
            out += struct.pack("<II", len(raw), tag)
        out += self.header_pad
        out = out.ljust(_a16(len(out)), b"\0")
        out += self.data
        for tag, raw in self.sections:
            out = out.ljust(_a16(len(out)), b"\0")
            out += raw
        return bytes(out.ljust(_a16(len(out)), b"\0"))


def parse(data: bytes) -> CockpitBin:
    return CockpitBin(data)


def _swap_key(s, donor_key, car_name):
    return re.sub(re.escape(donor_key), lambda m: car_name, s, flags=re.I)


def retarget_cockpit_bin(data: bytes, donor_key: str, car_key: str, car_name: str = None,
                         resource_path: str = None, vhf_name: str = None, display_name: str = None) -> bytes:
    """Make a donor's cockpit properties usable by a cloned car.

    - cockpit model name (data+0x10): donor key -> car name, e.g. Camaro_SS_Cockpit.vhf ->
      BYD_Seal_Cockpit.vhf. The game loads it from the CAR's folder (vehicles\\<car_key>\\), so the
      car's cockpit pak must contain vehicles\\<car_key>\\<car_key>_cockpit.vhf (+ .vhf.bml), which
      build._renamed_copies already produces. Pass vhf_name to choose it explicitly.
    - header uid: path_uid of the new resource path (default vehicles\\<car_key>\\<car_key>_cockpit.bin).
    - gearshift node / gauges: unchanged (they name nodes inside the cockpit .vhf, which is the donor's).
    - display name: unchanged by default (the donor's global gui\\display_<donor> exists); pass
      display_name to change it.
    """
    car_name = car_name or car_key
    cb = parse(data)
    old = cb.get_string(F_COCKPIT_VHF)
    if old is not None:
        cb.set_string(F_COCKPIT_VHF, vhf_name or _swap_key(old, donor_key, car_name))
    if display_name is not None and cb.ptr(F_DISPLAY) is not None:
        cb.set_string(F_DISPLAY, display_name)
    cb.set_resource_path(resource_path or f"vehicles\\{car_key.lower()}\\{car_key.lower()}_cockpit.bin")
    return cb.to_bytes()


def describe(data: bytes) -> dict:
    cb = parse(data)
    return {
        "version": cb.head[3], "uid": f"{cb.uid:#018x}", "data_size": len(cb.data),
        "sections": [(f"{tag:#x}", len(raw)) for tag, raw in cb.sections],
        "strings": cb.strings(), "relocs": [hex(r) for r in cb.relocs],
        "enum_fixups": [(hex(f), n) for f, n in cb.enum_fixups],
        "camera_xyz": struct.unpack_from("<3f", cb.data, 0x88) if len(cb.data) >= 0x94 else None,
    }
