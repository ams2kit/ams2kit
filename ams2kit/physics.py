"""Typed accessors for AMS2 car physics files, built on :mod:`ams2kit.shcb`.

Every accessor finds its data **by key** (never by offset or value search), so it works on any
donor: torque tables with 25..64+ rows stored as f32 / i32 / u8 codes, gearboxes with 1..60 ratio
options, suspension files with 10..11 bodies, etc. A field the donor lacks raises
:class:`MissingField`.

Classes (construct from bytes, or ``Cls.load(path)``; write back with ``to_bytes()`` / ``save(path)``)::

    Engine      torque_curve / set_torque_curve, rev_limit, displacement, idle_rpm
    Gearbox     gear_cogs / set_gear_cogs, gear_count, ratios, bevel, final_drive(s), make_single_speed
    Chassis     mass, inertia, cg_height, spring_ranges, axle_points, set_axle_z, shift_axle_points
    Suspension  bodies, points, wheel_centres, move_corner, set_geometry

Plain functions for the non-ShCB files::

    read_vdfm(data) -> dict ; write_vdfm(data, fields, new_id=None) -> bytes
    read_stats(data) -> dict ; write_stats(data, values) -> bytes

Game space: X = left, Y = up, Z = rear (the front axle has negative Z). Corners are
``"FL", "FR", "RL", "RR"``.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

from . import shcb
from .shcb import T_TUPLE, T_NULL, C_U8, C_I32, C_F32, Value, Group

CORNERS = ("FL", "FR", "RL", "RR")


class MissingField(KeyError):
    """The donor file has no such field."""

    def __str__(self):
        return self.args[0] if self.args else "missing field"


def _corner(x, z):
    return ("F" if z < 0 else "R") + ("L" if x > 0 else "R")


def _idx(lst, obj):
    """Index by identity (Values compare equal by content)."""
    for i, e in enumerate(lst):
        if e is obj:
            return i
    raise shcb.ShcbError("entry is not a top-level value")


def _num(v: Value, i=None):
    if v.type == T_NULL:
        return 0
    x = v.value[i] if i is not None else v.value
    return x


# ============================================================================ base

class PhysFile:
    KIND = "ShCB file"

    def __init__(self, data: bytes):
        self.file = shcb.parse(data)

    @classmethod
    def load(cls, path):
        return cls(Path(path).read_bytes())

    def to_bytes(self) -> bytes:
        return shcb.serialize(self.file)

    def save(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(self.to_bytes())

    def dump(self) -> str:
        return shcb.dump(self.file, getattr(self, "NAMES", None))

    def _all(self, key, what):
        vs = self.file.find_all(key)
        if not vs:
            raise MissingField(f"{self.KIND} has no {what} (key {key})")
        return vs

    def _one(self, key, what):
        return self._all(key, what)[0]

    def _scalar(self, key, what, index=None):
        v = self._one(key, what)
        if v.type == T_TUPLE:
            return v.value[index or 0]
        return _num(v)

    def _set_scalar(self, key, what, value, index=None):
        v = self._one(key, what)
        if v.type == T_TUPLE:
            vals = list(v.value)
            vals[index or 0] = value
            v.set_tuple(vals)
        else:
            v.set_scalar(value)


# ============================================================================ engine

class Engine(PhysFile):
    """``vehicles\\physics\\engines\\<engine>.edfbin``."""
    KIND = "engine"
    K_TORQUE = "8b0ab771"       # repeated tuple: rpm, drag (engine braking, Nm, <= 0), torque Nm
    K_REV_LIMIT = "dea72eb7"    # tuple (rev limit rpm, ?, ?)
    K_DISPLACEMENT = "92c7cd7c"  # f32 litres
    K_IDLE = "4d239754"         # tuple (idle rpm, idle rpm upper?) e.g. (850, 950); tentative
    NAMES = {K_TORQUE: "torque_row", K_REV_LIMIT: "rev_limit", K_DISPLACEMENT: "displacement_l",
             K_IDLE: "idle_rpm?"}

    def _rows(self):
        return self._all(self.K_TORQUE, "torque table")

    def torque_curve(self):
        """[(rpm, drag_nm, torque_nm), ...] in file order (any row count)."""
        return [tuple(float(x) for x in v.value) for v in self._rows()]

    def set_torque_curve(self, rows, resize=True):
        """Replace the table. ``rows``: [(rpm, drag, torque)] or [(rpm, torque)] (the drag column is
        then interpolated from the donor). Row count may differ from the donor's when ``resize``;
        otherwise the new curve is resampled to the donor's rpm count."""
        cur = self._rows()
        donor = self.torque_curve()
        rows = [tuple(r) for r in rows]
        if rows and len(rows[0]) == 2:
            rows = [(r, _interp(donor, r, 1), t) for r, t in rows]
        if not resize and len(rows) != len(cur):
            rows = resample_curve(rows, len(cur))
        container = self.file.entries
        first = _idx(container, cur[0])
        # all rows must be one contiguous top-level run for resizing
        if any(container[first + i] is not v for i, v in enumerate(cur)):
            if len(rows) != len(cur):
                raise shcb.ShcbError("torque rows are not contiguous; cannot resize")
        for v, r in zip(cur, rows):
            v.set_tuple(list(r))
        if len(rows) > len(cur):
            tag = cur[-1].tag & ~0x80 if cur[-1].tag is not None else 0x24
            extra = []
            for r in rows[len(cur):]:
                nv = Value(cur[-1].key, T_TUPLE, tag=tag)
                nv.set_tuple(list(r), [C_F32] * 3)
                extra.append(nv)
            pos = first + len(cur)
            container[pos:pos] = extra
        elif len(rows) < len(cur):
            del container[first + len(rows): first + len(cur)]

    @property
    def rev_limit(self) -> int:
        return int(self._scalar(self.K_REV_LIMIT, "rev limit"))

    @rev_limit.setter
    def rev_limit(self, rpm):
        self._set_scalar(self.K_REV_LIMIT, "rev limit", int(rpm))

    @property
    def displacement(self) -> float:
        return float(self._scalar(self.K_DISPLACEMENT, "displacement"))

    @displacement.setter
    def displacement(self, litres):
        v = self._one(self.K_DISPLACEMENT, "displacement")
        v.set_scalar(float(litres), shcb.T_F32)

    @property
    def idle_rpm(self) -> int:
        """First element of key 4d239754 (850 in the Veneno, 700 in the Camaro SS). Tentative."""
        return int(self._scalar(self.K_IDLE, "idle rpm"))

    @idle_rpm.setter
    def idle_rpm(self, rpm):
        self._set_scalar(self.K_IDLE, "idle rpm", int(rpm))

    def max_torque(self):
        return max(r[2] for r in self.torque_curve())

    K_BOOST_MULT = "515f5e83"   # turbo engines: rows (rpm, m1..m5) multiplying the torque table; [guess] the
                                # columns are boost levels, the last one full boost (VW Polo GTS: 1, 1.4, 1.8, 2.44, 2.6)

    def boost_multipliers(self):
        """[(rpm, (m1, ...)), ...] of a turbo engine's torque multiplier table; [] for other engines."""
        return [(float(v.value[0]), tuple(float(x) for x in v.value[1:])) for v in self.file.find_all(self.K_BOOST_MULT)]

    def full_boost_multiplier(self, rpm):
        """Torque multiplier at full boost (last column, linear in rpm; 1.0 without a table)."""
        rows = sorted((r, m[-1]) for r, m in self.boost_multipliers())
        if not rows:
            return 1.0
        return _interp([(r, m) for r, m in rows], rpm, 1)


def _interp(rows, rpm, col):
    pts = sorted((r[0], r[col]) for r in rows)
    if rpm <= pts[0][0]:
        return pts[0][1]
    for (a, va), (b, vb) in zip(pts, pts[1:]):
        if rpm <= b:
            return va + (vb - va) * (rpm - a) / (b - a) if b != a else vb
    return pts[-1][1]


def resample_curve(rows, n):
    """Resample [(rpm, drag, torque)] to ``n`` rows evenly spaced over the same rpm range."""
    rows = sorted(rows)
    lo, hi = rows[0][0], rows[-1][0]
    out = []
    for i in range(n):
        r = lo + (hi - lo) * i / (n - 1) if n > 1 else lo
        out.append((float(round(r)), _interp(rows, r, 1), _interp(rows, r, 2)))
    return out


# ============================================================================ gearbox

class Gearbox(PhysFile):
    """``vehicles\\physics\\gearbox\\<gearbox>.gdfbin``.

    Layout: object ``88de240f`` lists the forward-gear cog pairs (driver, driven); object
    ``9765b7af`` holds the bevel pair (``3c5bef62``) and one or more final-drive pairs (same gear
    key as the forward gears). Cars with setup choices list many options (up to ~60); fixed
    gearboxes list exactly one pair per gear (the Veneno: 7).
    """
    KIND = "gearbox"
    K_GEAR = "9d58f964"
    K_BEVEL = "3c5bef62"
    O_GEARS = "88de240f"
    O_FINAL = "9765b7af"
    NAMES = {K_GEAR: "gear_cogs", K_BEVEL: "bevel_cogs", O_GEARS: "gears", O_FINAL: "final_drive"}

    def _block(self, okey, what):
        k = shcb.key_of(okey)
        for obj, ents in self.file.blocks():
            if obj is not None and obj.key == k:
                return obj, ents
        raise MissingField(f"gearbox has no {what} object ({okey})")

    def _gears(self):
        _, ents = self._block(self.O_GEARS, "forward gears")
        g = [e for e in ents if isinstance(e, Value) and e.key == shcb.key_of(self.K_GEAR)]
        if not g:
            raise MissingField("gearbox has no forward gears")
        return g

    def _finals(self):
        _, ents = self._block(self.O_FINAL, "final drive")
        g = [e for e in ents if isinstance(e, Value) and e.key == shcb.key_of(self.K_GEAR)]
        if not g:
            raise MissingField("gearbox has no final drive")
        return g

    def gear_cogs(self):
        """[(driver, driven), ...] forward gears (or ratio options)."""
        return [tuple(int(x) for x in v.value) for v in self._gears()]

    @property
    def gear_count(self) -> int:
        return len(self._gears())

    def ratios(self):
        return [b / a for a, b in self.gear_cogs()]

    def set_gear_cogs(self, cogs):
        """Replace the forward gear list; the count may change. The Veneno's driveline needs 7
        gears (a 1-gear box broke the physics): prefer :meth:`make_single_speed` for EVs."""
        cur = self._gears()
        cogs = [tuple(c) for c in cogs]
        if not cogs:
            raise ValueError("need at least one gear")
        ents = self.file.entries
        first = _idx(ents, cur[0])
        last = _idx(ents, cur[-1])
        tag = cur[0].tag
        new = []
        for i, c in enumerate(cogs):
            v = cur[i] if i < len(cur) else Value(cur[0].key, T_TUPLE, tag=tag & ~0x80)
            v.set_tuple(list(c), [C_U8 if 0 <= x <= 127 else C_I32 for x in c])
            new.append(v)
        ents[first:last + 1] = new

    def make_single_speed(self, ratio=None, cogs=None):
        """Turn the box into an effective single speed: every forward gear gets the same cogs,
        keeping the donor's gear count. Give ``cogs=(driver, driven)`` or a ``ratio`` (cogs are
        chosen with driver 20 when possible)."""
        if cogs is None:
            cogs = _cogs_for(ratio if ratio is not None else 1.0)
        self.set_gear_cogs([tuple(cogs)] * self.gear_count)

    @property
    def bevel(self):
        v = self._one(self.K_BEVEL, "bevel")
        return tuple(int(x) for x in v.value)

    @bevel.setter
    def bevel(self, cogs):
        v = self._one(self.K_BEVEL, "bevel")
        v.set_tuple(list(cogs), [C_U8 if 0 <= x <= 127 else C_I32 for x in cogs])

    def final_drives(self):
        return [tuple(int(x) for x in v.value) for v in self._finals()]

    @property
    def final_drive(self):
        """First final-drive pair (driver, driven)."""
        return self.final_drives()[0]

    @final_drive.setter
    def final_drive(self, cogs):
        v = self._finals()[0]
        v.set_tuple(list(cogs), [C_U8 if 0 <= x <= 127 else C_I32 for x in cogs])

    def set_final_drives(self, cogs_list):
        cur = self._finals()
        ents = self.file.entries
        first, last = _idx(ents, cur[0]), _idx(ents, cur[-1])
        new = []
        for i, c in enumerate(cogs_list):
            v = cur[i] if i < len(cur) else Value(cur[0].key, T_TUPLE, tag=cur[0].tag & ~0x80)
            v.set_tuple(list(c), [C_U8 if 0 <= x <= 127 else C_I32 for x in c])
            new.append(v)
        ents[first:last + 1] = new

    def overall_ratio(self, gear=-1):
        a, b = self.gear_cogs()[gear]
        ba, bb = self.bevel
        fa, fb = self.final_drive
        return (b / a) * (bb / ba) * (fb / fa)


def _cogs_for(ratio):
    best = None
    for drv in range(8, 61):
        dvn = round(drv * ratio)
        if 1 <= dvn <= 255:
            err = abs(dvn / drv - ratio)
            if best is None or err < best[0] - 1e-12 or (abs(err - best[0]) < 1e-12 and drv == 20):
                best = (err, (drv, dvn))
    return best[1]


# ============================================================================ chassis

class Chassis(PhysFile):
    """``vehicles\\physics\\chassis\\<base>.cdfbin``."""
    KIND = "chassis"
    K_MASS = "670b57ab"         # i32 or f32 kg
    K_INERTIA = "bbb39f0b"      # tuple3 (pitch?, yaw?, roll?) kg m^2
    K_CG_HEIGHT = "1824eaa8"    # f32 m
    K_SPRING = "a5123d0d"       # 4x tuple (start N/m, step N/m, count) in FL, FR, RL, RR objects
    K_AXLE = {"FL": "e9ded999", "FR": "ba614262", "RL": "ac8de939", "RR": "c7c23d06"}
    NAMES = {K_MASS: "mass", K_INERTIA: "inertia", K_CG_HEIGHT: "cg_height", K_SPRING: "spring_range",
             **{v: f"axle_point_{k}" for k, v in K_AXLE.items()}}

    @property
    def mass(self):
        return self._scalar(self.K_MASS, "mass")

    @mass.setter
    def mass(self, kg):
        v = self._one(self.K_MASS, "mass")
        v.set_scalar(kg if v.type != shcb.T_I32 else int(round(kg)))

    @property
    def inertia(self):
        return tuple(float(x) for x in self._one(self.K_INERTIA, "inertia").value)

    @inertia.setter
    def inertia(self, xyz):
        self._one(self.K_INERTIA, "inertia").set_tuple([float(x) for x in xyz])

    @property
    def cg_height(self):
        return float(self._scalar(self.K_CG_HEIGHT, "CG height"))

    @cg_height.setter
    def cg_height(self, m):
        self._one(self.K_CG_HEIGHT, "CG height").set_scalar(float(m), shcb.T_F32)

    def spring_ranges(self):
        """[(start, step, count)] per corner, FL, FR, RL, RR (file order)."""
        return [tuple(v.value) for v in self._all(self.K_SPRING, "spring ranges")]

    def set_spring_ranges(self, ranges):
        vs = self._all(self.K_SPRING, "spring ranges")
        if len(ranges) != len(vs):
            raise ValueError(f"need {len(vs)} spring ranges")
        for v, r in zip(vs, ranges):
            vals = list(v.value)
            vals[:len(r)] = list(r)
            v.set_tuple(vals)

    def scale_springs(self, factor):
        """Scale start and step of every spring range (ints stay ints, rounded)."""
        new = []
        for r in self.spring_ranges():
            start, step = r[0], r[1]
            if isinstance(start, int):
                new.append((round(start * factor), round(step * factor)))
            else:
                new.append((start * factor, step * factor))
        self.set_spring_ranges(new)

    def axle_points(self):
        """{corner: (x, y, z)}: four symmetric chassis reference points (keys e9ded999 FL,
        ba614262 FR, ac8de939 RL, c7c23d06 RR). In the Veneno (and ~70 other cars) their z equals
        the wheel-centre z (+-1.351 = half wheelbase), but in most cars they sit 0-0.6 m off the
        axle lines and ~0.2-0.3 m inboard of the wheels, so they are *not* reliably axle
        positions (probably floor / ride-height contact points). Move them with the axles."""
        return {c: tuple(float(x) for x in self._one(k, f"axle point {c}").value)
                for c, k in self.K_AXLE.items()}

    corner_points = axle_points

    @property
    def axle_points_half_span(self):
        """Half of the z distance between the front and rear points (== half wheelbase only for
        cars like the Veneno; use Suspension.wheelbase for the real value)."""
        p = self.axle_points()
        return (p["RL"][2] - p["FL"][2]) / 2

    def set_axle_z(self, front_z, rear_z):
        """Set the z of the front pair and of the rear pair (what the BYD build did: +-1.46)."""
        for c, k in self.K_AXLE.items():
            v = self._one(k, f"axle point {c}")
            vals = list(v.value)
            vals[2] = front_z if c[0] == "F" else rear_z
            v.set_tuple(vals)

    def shift_axle_points(self, dz_front, dz_rear, dx_front=0.0, dx_rear=0.0):
        """Move the points with the axles: z by dz_front / dz_rear, x outward by dx_* (sign-aware).
        Pass the same deltas as Suspension.set_geometry returns per corner."""
        for c, k in self.K_AXLE.items():
            v = self._one(k, f"axle point {c}")
            x, y, z = (float(t) for t in v.value)
            dx = dx_front if c[0] == "F" else dx_rear
            v.set_tuple([x + (dx if c[1] == "L" else -dx), y, z + (dz_front if c[0] == "F" else dz_rear)])


# ============================================================================ suspension

class Suspension(PhysFile):
    """``vehicles\\physics\\suspension\\<base>.sdfbin``.

    Three object types (keys):
      body  ``7817b5d2``: name ``3a1e187c`` (string-table offset, used as the body id),
            mass ``670b57ab``, inertia ``bbb39f0b``, position ``4209feea``, ``aab5db49`` (?)
      hinge ``8adfea7e``: wheel body ``9f9074d0``, carrier body ``8a1e5909``, position = body
            ``4209feea``, axis ``a213897d`` -- one per wheel (the spin axle)
      link  ``2f5a4bdb``: optional name, body A ``9f9074d0`` (0 = chassis), body B ``8a1e5909``,
            point on A ``4209feea``, point on B ``5a44c7e0`` (wishbones, track rods, ...)
    Wheel centres = positions of the hinge wheel bodies.
    """
    KIND = "suspension"
    O_BODY, O_HINGE, O_LINK = "7817b5d2", "8adfea7e", "2f5a4bdb"
    K_NAME, K_MASS, K_INERTIA, K_POS, K_POS2 = "3a1e187c", "670b57ab", "bbb39f0b", "4209feea", "5a44c7e0"
    K_BODY_A, K_BODY_B, K_AXIS, K_AUX = "9f9074d0", "8a1e5909", "a213897d", "aab5db49"
    NAMES = {O_BODY: "body", O_HINGE: "hinge", O_LINK: "link", K_NAME: "name_id", K_MASS: "mass",
             K_INERTIA: "inertia", K_POS: "pos/point_a", K_POS2: "point_b", K_BODY_A: "body_a",
             K_BODY_B: "body_b", K_AXIS: "axis", K_AUX: "aux_vec?"}

    def _objects(self, okey):
        k = shcb.key_of(okey)
        out = []
        for obj, ents in self.file.blocks():
            if obj is None or obj.key != k:
                continue
            fields = {}
            for e in ents:
                if isinstance(e, Group):
                    for m in e.members:
                        fields.setdefault(shcb.key_hex(m.key), m)
                elif isinstance(e, Value):
                    fields.setdefault(shcb.key_hex(e.key), e)
            out.append(fields)
        return out

    @staticmethod
    def _vec(v):
        if v is None or v.type != T_TUPLE or len(v.value) != 3:
            return None
        return tuple(float(x) for x in v.value)

    def bodies(self):
        """[{'id', 'mass', 'inertia', 'pos', 'value'}] in file order (``value`` = position Value)."""
        out = []
        for i, f in enumerate(self._objects(self.O_BODY)):
            nid = f.get(self.K_NAME)
            out.append({
                "id": int(nid.value) if nid is not None else i,
                "mass": float(f[self.K_MASS].value[0]) if self.K_MASS in f and f[self.K_MASS].type == T_TUPLE
                else (float(f[self.K_MASS].value or 0) if self.K_MASS in f else None),
                "inertia": self._vec(f.get(self.K_INERTIA)),
                "pos": self._vec(f.get(self.K_POS)),
                "value": f.get(self.K_POS),
            })
        return out

    def hinges(self):
        out = []
        for f in self._objects(self.O_HINGE):
            out.append({"wheel": int(f[self.K_BODY_A].value), "carrier": int(f[self.K_BODY_B].value),
                        "axis": self._vec(f.get(self.K_AXIS))})
        return out

    def links(self):
        out = []
        for f in self._objects(self.O_LINK):
            out.append({"a": int(f[self.K_BODY_A].value) if self.K_BODY_A in f else None,
                        "b": int(f[self.K_BODY_B].value) if self.K_BODY_B in f else None,
                        "pa": f.get(self.K_POS), "pb": f.get(self.K_POS2),
                        "name": int(f[self.K_NAME].value) if self.K_NAME in f else None})
        return out

    def _body_corners(self):
        """{body id: corner} for wheels and their carriers (uprights / axles get None when shared)."""
        bodies = {b["id"]: b for b in self.bodies()}
        hinges = self.hinges()
        if not hinges:
            raise MissingField("suspension has no wheel hinges")
        corner = {}
        for h in hinges:
            b = bodies.get(h["wheel"])
            if b is None or b["pos"] is None:
                continue
            c = _corner(b["pos"][0], b["pos"][2])
            corner[h["wheel"]] = c
            prev = corner.get(h["carrier"], c)
            corner[h["carrier"]] = c if prev == c else (prev[0] if prev[0] == c[0] else None)
        return corner

    def wheel_centres(self):
        """{corner: (x, y, z)} from the hinge wheel bodies."""
        bodies = {b["id"]: b for b in self.bodies()}
        out = {}
        for h in self.hinges():
            b = bodies.get(h["wheel"])
            if b is None or b["pos"] is None:
                continue
            c = _corner(b["pos"][0], b["pos"][2])
            if c in out:
                raise shcb.ShcbError(f"two wheels map to corner {c}")
            out[c] = b["pos"]
        if len(out) != 4:
            raise MissingField(f"found {len(out)} wheel centres, expected 4")
        return out

    def points(self):
        """[(Value, role, corner)] for every 3-float point: body positions ('body') and link
        end points ('link_a' / 'link_b'). ``corner`` is FL/FR/RL/RR, 'F'/'R' for a body shared
        by an axle, or None for the chassis."""
        corners = self._body_corners()
        out = []
        for b in self.bodies():
            if b["pos"] is not None:
                out.append((b["value"], "body", corners.get(b["id"])))
        for ln in self.links():
            c = corners.get(ln["b"]) or corners.get(ln["a"])
            for role, v in (("link_a", ln["pa"]), ("link_b", ln["pb"])):
                if self._vec(v) is None:
                    continue
                cc = c
                if cc is None or len(cc) == 1:   # shared axle / unknown: fall back to point signs
                    x, _, z = self._vec(v)
                    cc = _corner(x, z) if cc is None else cc + ("L" if x > 0 else "R")
                out.append((v, role, cc))
        return out

    def move_corner(self, corner, dx=0.0, dz=0.0, dy=0.0):
        """Move every point of one corner (wheel, upright, both ends of its links) by (dx, dy, dz).
        Points of a body shared by both sides of an axle move by dz only (and dy)."""
        corner = corner.upper()
        n = 0
        for v, role, c in self.points():
            if c is None:
                continue
            if c == corner or (len(c) == 1 and c == corner[0]):
                x, y, z = (float(t) for t in v.value)
                ddx = dx if c == corner else 0.0
                v.set_tuple([x + ddx, y + dy, z + dz])
                n += 1
        return n

    def set_geometry(self, wheelbase, track_front, track_rear, keep_centre=True):
        """Move each corner as a unit so the wheel centres span ``wheelbase`` and the given tracks
        (wheel-centre to wheel-centre). The wheelbase midpoint is kept."""
        w = self.wheel_centres()
        zf = (w["FL"][2] + w["FR"][2]) / 2
        zr = (w["RL"][2] + w["RR"][2]) / 2
        mid = (zf + zr) / 2 if keep_centre else 0.0
        new_zf, new_zr = mid - wheelbase / 2, mid + wheelbase / 2
        moves = {}
        for c in CORNERS:
            x, _, z = w[c]
            half = (track_front if c[0] == "F" else track_rear) / 2
            tx = half if c[1] == "L" else -half
            tz = new_zf if c[0] == "F" else new_zr
            moves[c] = (tx - x, tz - z)
        for c, (dx, dz) in moves.items():
            self.move_corner(c, dx, dz)
        return moves

    @property
    def wheelbase(self):
        w = self.wheel_centres()
        return (w["RL"][2] + w["RR"][2]) / 2 - (w["FL"][2] + w["FR"][2]) / 2

    @property
    def tracks(self):
        w = self.wheel_centres()
        return (w["FL"][0] - w["FR"][0], w["RL"][0] - w["RR"][0])


# ============================================================================ vdfm

VDFM_STRINGS = 0x1F0      # string table start (constant in all 791 base files)
VDFM_DATA = 0x30          # pointer fields are relative to this
VDFM_FIELDS = {           # pointer-field offsets -> meaning (from matching against pak contents)
    0x30: "unknown_30",   # CarDetails+0x00: the game overwrites it with the vehicle's physics name
    0x38: "chassis",      # chassis\<name>.cdfbin (docs/12: renamable)
    0x48: "engine",       # engines\<name>.edfbin
    0x50: "clutch",
    0x58: "turbo",        # .tbfbin
    0x68: "failures",
    0x70: "gearbox",      # gearbox\<name>.gdfbin
    0x78: "suspension",   # suspension\<name>.sdfbin
    0x80: "base_80",      # collision\<name>.xml/.joi.xml + object COLLISION_CONVEX_<name>
    0x88: "tyres",        # tyre-set NAME from the boot list Tyres\TyresHD.xml: must stay a base-game set
    0xF8: "boost",        # .bbfbin (push-to-pass / hybrid)
}
_VDFM_BY_NAME = {v: k for k, v in VDFM_FIELDS.items()}


def _a16(x):
    return (x + 15) // 16 * 16


# ---- serialized-struct container (vdfm, mrdf, cockpit .bin; docs/12) ----
# header: 'Q' 02 01 <count> <header pad> ..., section table at 0x10: count x (u32 size, u8 kind, u8 pad, u16 0).
# The game walks the sections as offset += size + pad and REJECTS the whole file unless
# header pad + 0x10 + 8*count + sum(size + pad) == file length. A rejected vdfm leaves the car without
# engine/gearbox/tyre names, and the game crashes on track load.

def serial_sections(b):
    """[(table offset, size, kind, pad)] of a serialized-struct file."""
    return [(0x10 + 8 * i,) + struct.unpack_from("<IBB", b, 0x10 + 8 * i) for i in range(b[3])]


def serial_layout_ok(b) -> bool:
    """True when the game's header check accepts the file."""
    b = bytes(b)
    if len(b) < 16 or b[0] != 0x51 or b[2] != 1 or not b[3]:
        return False
    total = b[4] + 0x10 + 8 * b[3] + sum(sz + pad for _, sz, _, pad in serial_sections(b))
    return total == len(b)


def serial_fix_pads(b):
    """Set every section's pad byte to align its size to 16 (the layout all base files use)."""
    b = bytearray(b)
    for off, sz, _, _ in serial_sections(b):
        b[off + 5] = -sz % 16
    return b


def _vdfm_layout(b):
    if b[:4] != bytes.fromhex("51020104"):
        raise ValueError("not a .vdfm file")
    h = struct.unpack_from("<8I", b, 0x10)
    ss, rel_size, blk_size = h[2], h[4], h[6]
    rel = _a16(VDFM_STRINGS + ss)
    relocs = [struct.unpack_from("<Q", b, rel + 8 * i)[0] for i in range(rel_size // 8)]
    blk = _a16(rel + rel_size)
    return h, rel, relocs, blk, b[blk:blk + blk_size]


def read_vdfm(data: bytes) -> dict:
    """{field name: string} for every pointer field present, plus 'id' (bytes 8..16 hex)."""
    b = bytes(data)
    h, rel, relocs, blk, _ = _vdfm_layout(b)
    out = {"id": b[8:16].hex()}
    for r in relocs:
        off = struct.unpack_from("<Q", b, VDFM_DATA + r)[0]
        s0 = VDFM_STRINGS + off
        out[VDFM_FIELDS.get(VDFM_DATA + r, f"field_{VDFM_DATA + r:x}")] = b[s0:b.index(b"\0", s0)].decode("latin-1")
    return out


def write_vdfm(data: bytes, fields: dict, new_id: bytes | str | bool | None = None) -> bytes:
    """Rewrite the string table with ``fields`` ({name or offset: string}); other fields keep
    their strings. ``new_id``: True = random 8 bytes, bytes/hex = that id, None = keep.

    The section pad bytes are recomputed (docs/12). Before that fix, any table whose length changed
    modulo 16 made the game reject the file and crash on track load."""
    b = bytearray(data)
    h, rel, relocs, blk, block = _vdfm_layout(bytes(b))
    cur = read_vdfm(bytes(b))
    vals = {}
    for r in relocs:
        name = VDFM_FIELDS.get(VDFM_DATA + r, f"field_{VDFM_DATA + r:x}")
        vals[r] = cur[name]
    for k, s in fields.items():
        off = k if isinstance(k, int) else _VDFM_BY_NAME.get(k)
        if off is None and isinstance(k, str) and k.startswith("field_"):
            off = int(k[6:], 16)
        if off is None or off - VDFM_DATA not in vals:
            raise MissingField(f"vdfm has no pointer field {k!r}")
        vals[off - VDFM_DATA] = s
    table, offs = bytearray(), {}
    for r in relocs:                       # strings in field order, shared when equal
        s = vals[r]
        if s not in offs:
            offs[s] = len(table)
            table += s.encode("latin-1") + b"\0"
        struct.pack_into("<Q", b, VDFM_DATA + r, offs[s])
    out = bytearray(b[:VDFM_STRINGS]) + table
    out += bytes(_a16(len(out)) - len(out))
    out += b"".join(struct.pack("<Q", r) for r in relocs)
    out += bytes(_a16(len(out)) - len(out))
    out += block
    out += bytes(_a16(len(out)) - len(out))
    struct.pack_into("<I", out, 0x18, len(table))
    out = serial_fix_pads(out)
    if not serial_layout_ok(out):
        raise ValueError("vdfm layout check failed after rewrite")
    if new_id is True:
        out[8:16] = os.urandom(8)
    elif isinstance(new_id, str):
        out[8:16] = bytes.fromhex(new_id)
    elif isinstance(new_id, (bytes, bytearray)):
        out[8:16] = new_id
    return bytes(out)


# ============================================================================ mrdf stats

STATS_FIELDS = {          # offset: (name, struct format) -- menu only, see docs/03
    0x20: ("top_speed_ms", "<f"),
    0x24: ("zero_to_100_s", "<f"),
    0x28: ("gear_at_100", "<i"),
    0x30: ("gear_at_160", "<i"),
    0x3C: ("mass_kg", "<f"),
    0x40: ("gear_count", "<i"),
    0x44: ("torque_nm", "<f"),
    0x48: ("power_hp", "<f"),
    0x4C: ("drivetrain", "<i"),       # 1 = AWD
    0x50: ("boost", "<i"),
    0x54: ("aspiration", "<i"),
    0x64: ("engine_layout", "<i"),    # doc 05
    0x84: ("wheelbase_m", "<f"),
    0x88: ("rear_weight_fraction", "<f"),
    0xA0: ("displacement_l", "<f"),
}
STATS_SIZE = 224


def read_stats(data: bytes) -> dict:
    b = bytes(data)
    if len(b) != STATS_SIZE or b[:4] != bytes.fromhex("51020102"):
        raise ValueError(f"not a stats .mrdf (size {len(b)})")
    return {name: struct.unpack_from(fmt, b, off)[0] for off, (name, fmt) in STATS_FIELDS.items()}


def write_stats(data: bytes, values: dict) -> bytes:
    b = bytearray(data)
    read_stats(bytes(b))
    by_name = {name: (off, fmt) for off, (name, fmt) in STATS_FIELDS.items()}
    for k, v in values.items():
        if k not in by_name:
            raise MissingField(f"unknown stats field {k!r}")
        off, fmt = by_name[k]
        struct.pack_into(fmt, b, off, int(round(v)) if fmt == "<i" else float(v))
    return bytes(b)


# ============================================================================ helpers

def open_physics(path):
    """Pick the accessor class from the file extension."""
    ext = Path(path).suffix.lower()
    cls = {".edfbin": Engine, ".gdfbin": Gearbox, ".cdfbin": Chassis, ".sdfbin": Suspension}.get(ext, PhysFile)
    return cls.load(path)
