"""Generic parser / serializer for AMS2 "ShCB" keyed binaries.

The physics part files (``.edfbin`` engine, ``.gdfbin`` gearbox, ``.cdfbin`` chassis,
``.sdfbin`` suspension, ``.cmfbin`` clutch, ``.fmfbin`` failures, ``.tbfbin`` / ``.bbfbin``
turbo/boost) all use this container. The format is documented in
``docs/09-shcb-format.md``; in short::

    header   "ShCB" | u32 version 0x53dd0fe6 | u32 total size | u16 section count | u16 flags
             | count x (u32 section id, u32 size, u32 offset)
    sections 0x1010baba = body (keyed value stream), 0x55864952 = string table (RC4 encrypted,
             kept as raw bytes)
    trailer  some files carry bytes after ``total size``; kept verbatim.

Body = flat stream of entries. Each entry starts with a tag byte ``t``:

* ``t & 0x20`` (kinds 1/3/5/7): keyed entry ``t, key(4 bytes)`` then a value whose layout is
  given by ``type = t & 0x1f``. ``type 0`` with ``t & 0x40`` set (``0x60`` / ``0xe0``) is an
  *object begin* (no value).
* ``t & 0x60 == 0x40``: *group* of ``n = t & 0x1f`` members. ``ceil(n/2)`` bytes of 4-bit member
  types (low nibble first), then ``n`` x ``key(4) + value`` (no per-member tag).
* anything else: kept as an opaque :class:`Raw` run (only 1 base-game file needs it).

Value types: 0 = u8, 1 = i32, 2 = f32, 3 = f64, 4 = tuple, 6 = u8 (bool-like), 8 = null
(value omitted; the exporter writes zero/default values this way). A tuple starts with a
descriptor: low nibble = element count ``n``, then ``n`` 2-bit element codes starting at bit 4
(0 = u8, 1 = i32, 2 = f32, 3 = f64), ``ceil((4 + 2n) / 8)`` bytes in total.

Bit 7 of a tag (``0x80``) is a per-key flag whose meaning is unknown; it is preserved.

Public API::

    f = parse(data) -> ShcbFile          # f.entries: list of Value/Object/Group/Raw
    serialize(f) -> bytes                # byte-identical for unmodified input
    dump(data_or_file) -> str
    f.find(key) / f.find_all(key) / f.values(key)
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = b"ShCB"
BODY_ID = 0x1010BABA
STRINGS_ID = 0x55864952

T_U8, T_I32, T_F32, T_F64, T_TUPLE, T_BOOL, T_NULL = 0, 1, 2, 3, 4, 6, 8
C_U8, C_I32, C_F32, C_F64 = 0, 1, 2, 3
_CODE_FMT = {C_U8: "<B", C_I32: "<i", C_F32: "<f", C_F64: "<d"}
_CODE_SIZE = {C_U8: 1, C_I32: 4, C_F32: 4, C_F64: 8}
_SCALAR_FMT = {T_U8: "<B", T_BOOL: "<B", T_I32: "<i", T_F32: "<f", T_F64: "<d"}
TYPE_NAMES = {T_U8: "u8", T_I32: "i32", T_F32: "f32", T_F64: "f64", T_TUPLE: "tuple",
              T_BOOL: "bool", T_NULL: "null"}
CODE_NAMES = {C_U8: "u8", C_I32: "i32", C_F32: "f32", C_F64: "f64"}


class ShcbError(ValueError):
    pass


def key_of(k) -> int:
    """Accept a key as int, 4 bytes, or hex string as it appears in the file ("670b57ab")."""
    if isinstance(k, int):
        return k
    if isinstance(k, str):
        k = bytes.fromhex(k.replace(" ", ""))
    if len(k) != 4:
        raise ShcbError(f"key must be 4 bytes, got {k!r}")
    return int.from_bytes(k, "little")


def key_hex(k: int) -> str:
    return k.to_bytes(4, "little").hex()


# --------------------------------------------------------------------------- entries

@dataclass
class Value:
    """A keyed value. ``type`` is one of the T_* constants.

    Scalars: ``value`` is int/float/None. Tuples: ``value`` is a list and ``codes`` the
    per-element codes (C_*). ``tag`` is None for group members.
    """
    key: int
    type: int
    value: object = None
    codes: list | None = None
    tag: int | None = None
    _raw: bytes | None = field(default=None, repr=False, compare=False)   # original value bytes
    _orig: tuple | None = field(default=None, repr=False, compare=False)  # snapshot for _raw

    @property
    def flag(self) -> bool:
        return bool(self.tag is not None and self.tag & 0x80)

    def __len__(self):
        return len(self.value) if self.type == T_TUPLE else 1

    # tuple helpers ------------------------------------------------------
    def set_tuple(self, values, codes=None):
        """Replace a tuple's elements. Codes default to: keep the old code where the new value
        still fits, else f32 for floats, i32 for ints. Zero floats keep a u8 code if they had one."""
        values = list(values)
        if codes is None:
            old = self.codes or []
            codes = []
            for i, v in enumerate(values):
                oc = old[i] if i < len(old) else None
                codes.append(_fit_code(v, oc))
        if len(codes) != len(values) or len(values) > 15:
            raise ShcbError("tuple must have <= 15 elements and one code per element")
        self.type, self.value, self.codes = T_TUPLE, values, list(codes)

    def set_scalar(self, v, type=None):
        if type is None:
            type = self.type if self.type != T_TUPLE else None
            if type == T_NULL:
                type = None
            if type is not None and not _fits_type(v, type):
                type = None
            if type is None:
                type = T_F32 if isinstance(v, float) else T_I32
        self.type, self.value, self.codes = type, (None if type == T_NULL else v), None


def _fit_code(v, old):
    if old is not None:
        if old == C_U8 and isinstance(v, (int, float)) and float(v).is_integer() and 0 <= v <= 255 \
                and (isinstance(v, int) or v == 0):
            return C_U8
        if old == C_I32 and isinstance(v, int):
            return C_I32
        if old in (C_F32, C_F64) and isinstance(v, (int, float)):
            return old
    if isinstance(v, float):
        return C_F32
    return C_I32 if not (0 <= v <= 255) else C_U8


def _fits_type(v, t):
    if t in (T_U8, T_BOOL):
        return isinstance(v, int) and 0 <= v <= 255
    if t == T_I32:
        return isinstance(v, int) and -2**31 <= v < 2**31
    if t in (T_F32, T_F64):
        return isinstance(v, (int, float))
    return False


@dataclass
class Object:
    """Object begin marker (tag 0x60 / 0xe0): ``key`` names the object/class."""
    key: int
    tag: int = 0x60

    @property
    def flag(self) -> bool:
        return bool(self.tag & 0x80)


@dataclass
class Group:
    """Compact group (tag 0x40 | n): members are Values without tags."""
    members: list
    tag: int = 0x40
    _types_raw: bytes | None = field(default=None, repr=False, compare=False)


@dataclass
class Raw:
    """Bytes the parser does not understand, kept verbatim."""
    data: bytes


@dataclass
class Section:
    id: int
    data: bytes = b""          # raw bytes (non-body sections)
    offset: int = 0
    size: int = 0


@dataclass
class ShcbFile:
    version: int
    flags: int
    sections: list                 # Section objects in table order; the body one has data b""
    entries: list                  # body entries
    trailer: bytes = b""
    _pad: dict = field(default_factory=dict, repr=False)   # gaps between sections (offset -> bytes)

    # ------------------------------------------------------------ queries
    def iter_values(self):
        """Yield (container, index, Value) for every keyed value incl. group members."""
        for i, e in enumerate(self.entries):
            if isinstance(e, Value):
                yield self.entries, i, e
            elif isinstance(e, Group):
                for j, m in enumerate(e.members):
                    yield e.members, j, m

    def find_all(self, key) -> list:
        k = key_of(key)
        return [v for _, _, v in self.iter_values() if v.key == k]

    def find(self, key, default=KeyError):
        r = self.find_all(key)
        if not r:
            if default is KeyError:
                raise KeyError(f"key {key_hex(key_of(key))} not present")
            return default
        return r[0]

    def has(self, key) -> bool:
        return bool(self.find_all(key))

    def objects(self):
        """[(index, Object)] for every object-begin marker."""
        return [(i, e) for i, e in enumerate(self.entries) if isinstance(e, Object)]

    def blocks(self):
        """Split the body at object markers: [(Object|None, [entries...]), ...]."""
        out, cur, cur_obj = [], [], None
        for e in self.entries:
            if isinstance(e, Object):
                out.append((cur_obj, cur))
                cur, cur_obj = [], e
            else:
                cur.append(e)
        out.append((cur_obj, cur))
        return out

    def index_of(self, value) -> int:
        """Index in ``entries`` of a top-level Value (identity)."""
        for i, e in enumerate(self.entries):
            if e is value:
                return i
        raise ValueError("value is not a top-level entry")

    def section(self, sid):
        for s in self.sections:
            if s.id == sid:
                return s
        return None


# --------------------------------------------------------------------------- parsing

def _desc_len(n):
    return (4 + 2 * n + 7) // 8


def _read_desc(b, i):
    n = b[i] & 15
    nb = _desc_len(n)
    if i + nb > len(b):
        raise ShcbError("truncated tuple descriptor")
    bits = int.from_bytes(b[i:i + nb], "little") >> 4
    return nb, [(bits >> (2 * k)) & 3 for k in range(n)]


def _make_desc(codes):
    n = len(codes)
    v = n
    for k, c in enumerate(codes):
        v |= c << (4 + 2 * k)
    return v.to_bytes(_desc_len(n), "little")


def _read_value(b, i, t, key, tag):
    """Read a value of type ``t`` at ``i``; returns (Value, next index)."""
    start = i
    if t == T_NULL:
        return Value(key, t, None, tag=tag, _raw=b""), i
    if t in _SCALAR_FMT:
        fmt = _SCALAR_FMT[t]
        n = struct.calcsize(fmt)
        if i + n > len(b):
            raise ShcbError("truncated scalar")
        v = struct.unpack_from(fmt, b, i)[0]
        val = Value(key, t, v, tag=tag)
        i += n
    elif t == T_TUPLE:
        nb, codes = _read_desc(b, i)
        j = i + nb
        vals = []
        for c in codes:
            if j + _CODE_SIZE[c] > len(b):
                raise ShcbError("truncated tuple")
            vals.append(struct.unpack_from(_CODE_FMT[c], b, j)[0])
            j += _CODE_SIZE[c]
        val = Value(key, t, vals, codes=codes, tag=tag)
        i = j
    else:
        raise ShcbError(f"unknown value type {t}")
    val._raw = bytes(b[start:i])
    val._orig = _snapshot(val)
    return val, i


def _snapshot(v):
    return (v.type, tuple(v.value) if isinstance(v.value, list) else v.value,
            tuple(v.codes) if v.codes else None)


def _parse_entry(b, i, end):
    t = b[i]
    if t & 0x20:
        if i + 5 > end:
            raise ShcbError("truncated key")
        key = int.from_bytes(b[i + 1:i + 5], "little")
        ty = t & 0x1F
        if ty == 0 and t & 0x40:
            return Object(key, t), i + 5
        v, j = _read_value(b, i + 5, ty, key, t)
        return v, j
    if t & 0x60 == 0x40:
        n = t & 0x1F
        nt = (n + 1) // 2
        types_raw = bytes(b[i + 1:i + 1 + nt])
        types = [(types_raw[k // 2] >> (4 * (k % 2))) & 15 for k in range(n)]
        j = i + 1 + nt
        members = []
        for ty in types:
            if j + 4 > end:
                raise ShcbError("truncated group key")
            key = int.from_bytes(b[j:j + 4], "little")
            v, j = _read_value(b, j + 4, ty, key, None)
            members.append(v)
        return Group(members, t, types_raw), j
    raise ShcbError(f"unknown tag 0x{t:02x}")


def _parse_stream(b, start, end, out):
    """Parse entries in b[start:end] into ``out``; returns True when it lands exactly on end."""
    i = start
    while i < end:
        try:
            e, j = _parse_entry(b, i, end)
        except (ShcbError, struct.error, KeyError):
            return i
        if j > end:
            return i
        out.append(e)
        i = j
    return i


def parse_body(b, start, end):
    entries = []
    i = _parse_stream(b, start, end, entries)
    while i < end:
        # Unknown construct: find the nearest later offset from which the rest parses cleanly
        # and keep the gap as a Raw run (byte-exact either way).
        # Prefer a resync point that is an object marker (the only base-game case, the
        # Mini Cooper 1965 gearbox, resyncs at one); otherwise take the earliest.
        first = None
        for k in range(i + 1, end + 1):
            rest = []
            if k == end or _parse_stream(b, k, end, rest) == end:
                if first is None:
                    first = (k, rest)
                if k == end or b[k] in (0x60, 0xE0):
                    first = (k, rest)
                    break
        k, rest = first
        entries.append(Raw(bytes(b[i:k])))
        entries.extend(rest)
        i = end
    return entries


def parse(data: bytes) -> ShcbFile:
    b = bytes(data)
    if b[:4] != MAGIC:
        raise ShcbError("not a ShCB file (magic)")
    version, total, count, flags = struct.unpack_from("<IIHH", b, 4)
    if total > len(b):
        raise ShcbError(f"total size 0x{total:x} > file size 0x{len(b):x}")
    secs = []
    for k in range(count):
        sid, size, off = struct.unpack_from("<III", b, 0x10 + 12 * k)
        secs.append(Section(sid, b"", off, size))
    f = ShcbFile(version, flags, secs, [], b[total:])
    hdr_end = 0x10 + 12 * count
    pos = hdr_end
    for s in sorted(secs, key=lambda s: s.offset):
        if s.offset < pos or s.offset + s.size > total:
            raise ShcbError("overlapping or out-of-range sections")
        if s.offset > pos:
            f._pad[s.id] = b[pos:s.offset]
        pos = s.offset + s.size
        if s.id == BODY_ID:
            f.entries = parse_body(b, s.offset, s.offset + s.size)
        else:
            s.data = b[s.offset:s.offset + s.size]
    if pos != total:
        f._pad[None] = b[pos:total]
    return f


# --------------------------------------------------------------------------- serializing

def _pack_value(v: Value) -> bytes:
    if v._raw is not None and v._orig == _snapshot(v):
        return v._raw
    t = v.type
    if t == T_NULL:
        return b""
    if t in _SCALAR_FMT:
        return struct.pack(_SCALAR_FMT[t], v.value)
    if t == T_TUPLE:
        if len(v.value) != len(v.codes):
            raise ShcbError("tuple values/codes length mismatch")
        out = bytearray(_make_desc(v.codes))
        for c, x in zip(v.codes, v.value):
            if c in (C_U8, C_I32):
                x = int(round(x))
            out += struct.pack(_CODE_FMT[c], x)
        return bytes(out)
    raise ShcbError(f"cannot serialize type {t}")


def serialize_entry(e) -> bytes:
    if isinstance(e, Value):
        tag = e.tag if e.tag is not None else 0x20
        tag = (tag & 0xE0) | e.type
        return bytes([tag]) + e.key.to_bytes(4, "little") + _pack_value(e)
    if isinstance(e, Object):
        return bytes([e.tag]) + e.key.to_bytes(4, "little")
    if isinstance(e, Group):
        n = len(e.members)
        if n > 31:
            raise ShcbError("group has more than 31 members")
        types = bytearray((n + 1) // 2)
        for k, m in enumerate(e.members):
            types[k // 2] |= (m.type & 15) << (4 * (k % 2))
        if e._types_raw is not None and len(e._types_raw) == len(types) and \
                all(((e._types_raw[k // 2] >> (4 * (k % 2))) & 15) == (m.type & 15)
                    for k, m in enumerate(e.members)):
            types = e._types_raw     # keep any non-zero padding nibble
        out = bytearray([(e.tag & 0xE0) | n]) + types
        for m in e.members:
            out += m.key.to_bytes(4, "little") + _pack_value(m)
        return bytes(out)
    if isinstance(e, Raw):
        return e.data
    raise ShcbError(f"unknown entry {e!r}")


def serialize(f: ShcbFile) -> bytes:
    body = b"".join(serialize_entry(e) for e in f.entries)
    count = len(f.sections)
    hdr_len = 0x10 + 12 * count
    # lay sections out in their original offset order
    order = sorted(f.sections, key=lambda s: s.offset)
    pos = hdr_len
    blobs = []
    for s in order:
        pad = f._pad.get(s.id, b"")
        pos += len(pad)
        data = body if s.id == BODY_ID else s.data
        s.offset, s.size = pos, len(data)
        blobs.append(pad + data)
        pos += len(data)
    blobs.append(f._pad.get(None, b""))
    total = pos + len(f._pad.get(None, b""))
    out = bytearray(MAGIC + struct.pack("<IIHH", f.version, total, count, f.flags))
    for s in f.sections:
        out += struct.pack("<III", s.id, s.size, s.offset)
    out += b"".join(blobs)
    return bytes(out) + f.trailer


# --------------------------------------------------------------------------- dump

def _fmt(x, c=None):
    if isinstance(x, float):
        return f"{x:.7g}"
    return str(x)


def describe_value(v: Value) -> str:
    if v.type == T_TUPLE:
        inner = ", ".join(f"{_fmt(x)}:{CODE_NAMES[c]}" for x, c in zip(v.value, v.codes))
        return f"tuple[{len(v.value)}] ({inner})"
    if v.type == T_NULL:
        return "null"
    return f"{TYPE_NAMES.get(v.type, v.type)} {_fmt(v.value)}"


def dump(data_or_file, names: dict | None = None) -> str:
    """Readable listing. ``names`` maps key (int or hex) -> label."""
    f = parse(data_or_file) if isinstance(data_or_file, (bytes, bytearray)) else data_or_file
    nm = {key_of(k): v for k, v in (names or {}).items()}
    lines = [f"ShCB version 0x{f.version:08x} flags 0x{f.flags:04x} sections "
             + ", ".join(f"0x{s.id:08x}@0x{s.offset:x}+0x{s.size:x}" for s in f.sections)
             + (f" trailer {len(f.trailer)} bytes" if f.trailer else "")]

    def lab(k):
        return key_hex(k) + (f" {nm[k]}" if k in nm else "")
    depth = 0
    for i, e in enumerate(f.entries):
        if isinstance(e, Object):
            depth = 1
            lines.append(f"[{i:4d}] {e.tag:02x} OBJECT {lab(e.key)}")
        elif isinstance(e, Value):
            lines.append(f"[{i:4d}] {'  ' * depth}{e.tag:02x} {lab(e.key)} = {describe_value(e)}")
        elif isinstance(e, Group):
            lines.append(f"[{i:4d}] {'  ' * depth}{e.tag:02x} GROUP[{len(e.members)}]")
            for m in e.members:
                lines.append(f"       {'  ' * depth}   {lab(m.key)} = {describe_value(m)}")
        else:
            lines.append(f"[{i:4d}] {'  ' * depth}RAW {len(e.data)} bytes: {e.data.hex(' ')}")
    for s in f.sections:
        if s.id != BODY_ID:
            lines.append(f"section 0x{s.id:08x}: {len(s.data)} bytes (encrypted string table)")
    return "\n".join(lines)


# --------------------------------------------------------------------------- builders

def new_value(key, value, type=None, flag=False):
    """Build a top-level Value. Tuples: pass a list (codes auto-picked) or (list, codes)."""
    k = key_of(key)
    tag = 0xA0 if flag else 0x20
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], list):
        v = Value(k, T_TUPLE, tag=tag)
        v.set_tuple(value[0], value[1])
        return v
    if isinstance(value, list):
        v = Value(k, T_TUPLE, tag=tag)
        v.set_tuple(value)
        return v
    v = Value(k, T_NULL, tag=tag)
    v.set_scalar(value, type)
    return v


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        print(f"== {p}")
        print(dump(open(p, "rb").read()))
