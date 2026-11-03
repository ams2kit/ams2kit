"""Electric-drive helpers (docs/11-electric-drive.md). Offline maths and text/byte generation only.

AMS2 has no stand-alone electric powertrain that a car file can select: every shipping car (hybrids
included) drives through the ICE model (`.edfbin` torque table, idle, clutch, gearbox). Hybrids add
an electric motor through the "boost" system (`.bbfbin`, vdfm field 0xF8). So an EV is still built
as an ICE whose torque table is an electric-motor curve; this module makes that curve, the gearing,
a mod `driveline.rg` with a no-stall centrifugal clutch, and (experimental) a hybrid boost file.

    motor_rows(...)            (rpm, drag, torque) rows: flat torque, constant power, regen drag
    final_drive_for(...)       overall ratio for a top speed at the rev limit
    sim_peak_torque(...)       wheel-force-equivalent torque when the simulated motor revs lower
    ev_driveline_rg(...)       mod driveline.rg text: copy of a game group with a centrifugal clutch
    strtab_crypt(...)          ShCB string-table cipher (fixed keystream, see docs/09)
    boost_set(...)             patch a donor .bbfbin (tentative key names, BOOST_KEYS)
"""
from __future__ import annotations

import math
import re

from . import shcb

# ----------------------------------------------------------------------------- motor curve

def _w(rpm):
    return rpm * 2 * math.pi / 60


def motor_rows(power_kw, torque_nm, rev_limit, *, regen_kw=0.0, regen_nm=None, regen_fade_rpm=600.0,
               friction_nm=15.0, n_rows=25, over=(100, 250, 500, 1000, 1500)):
    """Engine-table rows (rpm, drag, torque) for an electric motor.

    torque  = min(torque_nm, P/w) up to the rev limit, 0 at the limit, negative above (soft cut).
    drag    = engine braking at closed throttle (<= 0): -(friction + min(regen_nm, regen_kw/w)),
              i.e. lift-off regen at constant power with a torque cap, faded linearly to 0 below
              `regen_fade_rpm` (a motor cannot regenerate at standstill). Row 0 is (0, -friction, -friction)
              because the donors start with a 0 rpm row (dropping it crashed the game, docs/08).
    torque_nm/power_kw are in the *simulated* motor's frame (use sim_peak_torque first when the
    simulated rev limit is lower than the real motor's).
    """
    if regen_nm is None:
        regen_nm = torque_nm
    p = power_kw * 1000.0
    base = p / torque_nm / (2 * math.pi / 60)          # corner rpm: torque * w = power
    if base >= rev_limit:
        raise ValueError(f"torque {torque_nm} Nm never reaches {power_kw} kW below {rev_limit} rpm")
    n_body = n_rows - 1 - len(over) - 1                  # 0 rpm row, overspeed rows, limit row
    n_flat = max(2, round(n_body * base / rev_limit))
    flat = [base * (i + 1) / n_flat for i in range(n_flat)]
    n_pow = n_body - n_flat
    pw = [base + (rev_limit - base) * (i + 1) / (n_pow + 1) for i in range(n_pow)]

    def drag(r):
        regen = min(regen_nm, regen_kw * 1000.0 / _w(r)) if regen_kw > 0 else 0.0
        if regen_fade_rpm > 0:
            regen *= min(1.0, r / regen_fade_rpm)
        return -(friction_nm + regen)

    rows = [(0.0, -friction_nm, -friction_nm)]
    rows += [(r, drag(r), min(torque_nm, p / _w(r))) for r in flat + pw]
    rows.append((float(rev_limit), drag(rev_limit), 0.0))
    peak = min(torque_nm, p / _w(rev_limit))
    rows += [(float(rev_limit + d), drag(rev_limit + d), -peak * min(1.0, d / 500.0) - 50.0) for d in over]
    return [(round(r, 1), round(d, 2), round(t, 2)) for r, d, t in rows]


def sim_peak_torque(real_torque_nm, real_max_rpm, sim_rev_limit):
    """Torque giving the same wheel force when the simulated motor's limiter is lower than the real one
    (the overall ratio shrinks by sim/real, so torque grows by real/sim)."""
    return real_torque_nm * real_max_rpm / sim_rev_limit


def reflected_inertia(i_real, real_max_rpm, sim_rev_limit):
    """Rotor inertia for the simulated (slower) crankshaft: kinetic energy is kept, so it scales with
    (real/sim)^2. E.g. 0.04 kg m^2 at 16000 rpm simulated at 8000 rpm -> 0.16 (the Veneno crank is 0.10)."""
    return i_real * (real_max_rpm / sim_rev_limit) ** 2


def final_drive_for(top_kmh, rev_limit, radius_m, gear_ratio=1.0):
    """Overall final ratio so the rev limit in `gear_ratio` gives `top_kmh` (rolling radius `radius_m`)."""
    return _w(rev_limit) * radius_m / (top_kmh / 3.6) / gear_ratio


def wheel_force(rows, rpm, overall_ratio, radius_m, efficiency=1.0):
    """Tractive force (N) from the table at `rpm` (linear interpolation)."""
    pts = [(r, t) for r, _, t in rows]
    for (r0, t0), (r1, t1) in zip(pts, pts[1:]):
        if r0 <= rpm <= r1:
            t = t0 + (t1 - t0) * (rpm - r0) / ((r1 - r0) or 1)
            return t * overall_ratio * efficiency / radius_m
    return 0.0


# ----------------------------------------------------------------------------- driveline.rg

_KW = ("RECORD", "RECORDGROUP", "LAYOUT", "ATTRIBUTE", "INFO", "DEFAULTGROUP")


def rg_blocks(text):
    """{name: (kind, layout, [body lines])} for every RECORD / RECORDGROUP in a driveline.rg."""
    out, cur = {}, None
    for line in text.splitlines():
        s = line.strip()
        head = s.split()
        if head and head[0] in _KW:
            cur = None
            if head[0] in ("RECORD", "RECORDGROUP") and len(head) >= 2:
                cur = []
                out[head[1]] = (head[0], head[2] if head[0] == "RECORD" and len(head) > 2 else None, cur)
            continue
        if cur is not None and s and not s.startswith("#"):
            cur.append(s)
    return out


def _record_text(name, layout, lines):
    return "\n".join([f"RECORD {name} {layout}"] + ["\t" + l for l in lines]) + "\n"


def ev_driveline_rg(physics_name, base_group, game_rg_text, *, suffix="EV", clutch_torque=3000.0,
                    clutch_rpm=(900.0, 1500.0), crank_mass=None, minhz=6000, electric_motor_on=None):
    """Mod driveline.rg text for an EV built on `base_group` (a game RECORDGROUP name).

    The group is copied as `<base_group>_<suffix>` with its foot clutch (l_clutch) replaced by a
    centrifugal clutch between the same shafts (engages between clutch_rpm[0] and [1]: no stall, no
    clutch pedal, launch like an automatic). `crank_mass` (sim:mass of the "crankshaft", i.e. rotor
    inertia) adds copies of the crankshaft and of every record that references it.
    `electric_motor_on=<shaft record>` adds an `electricmotor` component with `pto <shaft>`: the game has
    this component but no shipping car uses it and its torque source is unknown; in-game experiment
    only (docs/11).
    Records defined here are new names, so the game's own records stay untouched.
    """
    blocks = rg_blocks(game_rg_text)
    kind, _, members = blocks[base_group]
    if kind != "RECORDGROUP":
        raise KeyError(f"{base_group} is not a RECORDGROUP")
    tag = suffix.upper()
    new_members, extra = [], []
    rename = {}

    if crank_mass is not None:
        cranks = [m for m in members if blocks.get(m, ("",))[0] == "RECORD" and blocks[m][1] == "shaft"
                  and any(l.split()[:2] == ["name", '"crankshaft"'] for l in blocks[m][2])]
        for c in cranks:
            rename[c] = f"{c}_{tag}"
            lines = [l for l in blocks[c][2] if not l.startswith("sim:mass")] + [f"sim:mass {crank_mass}"]
            extra.append(_record_text(rename[c], "shaft", lines))

    def sub_refs(lines):
        out = []
        for l in lines:
            parts = l.split()
            if len(parts) >= 2 and parts[1] in rename:
                l = l.replace(parts[1], rename[parts[1]], 1)
            out.append(l)
        return out

    replaced_clutch = False
    for m in members:
        if m in rename:
            new_members.append(rename[m])
            continue
        b = blocks.get(m)
        if b and b[0] == "RECORD" and b[1] == "l_clutch" and not replaced_clutch and not m.startswith(("clutch_RX", "AWD_")):
            pairs = [l for l in b[2] if l.startswith(("pair:left", "pair:right"))]
            name = f"clutch_{tag}_centrifugal"
            lines = sub_refs(pairs) + ["mat:stiffness 1.0e6", f"clutch:torque {clutch_torque:g}", "mat:damping 0.0",
                                       "clutch:visc_drag 1.0e3", "clutch:slip_factor 1.0",
                                       f'clutch:rpm "{clutch_rpm[0]:g} {clutch_rpm[1]:g}"']
            extra.append(_record_text(name, "l_centrifugal_clutch", lines))
            new_members.append(name)
            replaced_clutch = True
            continue
        if b and b[0] == "RECORD" and rename and any(len(l.split()) >= 2 and l.split()[1] in rename for l in b[2]):
            rename[m] = f"{m}_{tag}"
            extra.append(_record_text(rename[m], b[1], sub_refs(b[2])))
            new_members.append(rename[m])
            continue
        new_members.append(m)
    if not replaced_clutch:
        raise ValueError(f"{base_group} has no l_clutch record to replace")
    if electric_motor_on:
        name = f"electricmotor_{tag}"
        extra.append(_record_text(name, "electricmotor", [f"pto {rename.get(electric_motor_on, electric_motor_on)}"]))
        new_members.append(name)

    group = f"{base_group}_{tag}"
    rec = re.sub(r"[^A-Z0-9_]", "_", physics_name.upper())
    text = [f"RECORD {rec}_{tag}_01 l_driveline", f'\tname "{physics_name.upper()}"', f"\tcontents {group}",
            f"\tdl:minhz\t{minhz}", "", *extra, f"RECORDGROUP {group}", *["\t" + m for m in new_members], ""]
    return "\n".join(text)


# ----------------------------------------------------------------------------- ShCB string tables

# The ShCB string section (id 0x55864952) is XORed with one fixed keystream for every file (RC4 with a
# constant key, applied from offset 0 of the section). Recovered by known plaintext ("REAR"/"FOUR"
# in .bbfbin/.cdfbin, suspension body names in .sdfbin); the first 107 bytes are cross-checked.
STRTAB_KEYSTREAM = bytes.fromhex(
    "84193b2fef4f62832bc30d6d287b0deb8dfa45792b6795e4ff1a29cb2075ddcc100185503081bb5e88c1e662b6"
    "08222288c2ae996c8286f17db9fb027d0c21fbfb338b28db9f310ca03e5a76e727ddb54808dc311ee86f13b07e"
    "2499e6f16f3b378e4938a93e8048dbd636")


def strtab_crypt(data: bytes) -> bytes:
    """Encrypt or decrypt (XOR) a whole string section."""
    if len(data) > len(STRTAB_KEYSTREAM):
        raise ValueError(f"only {len(STRTAB_KEYSTREAM)} keystream bytes are known")
    return bytes(a ^ b for a, b in zip(data, STRTAB_KEYSTREAM))


def strings_of(f: shcb.ShcbFile):
    """Decrypted NUL-separated strings of a parsed file's string section ([] if none)."""
    s = f.section(shcb.STRINGS_ID)
    if not s:
        return []
    return strtab_crypt(s.data).rstrip(b"\0").decode("latin-1").split("\0")


# ----------------------------------------------------------------------------- boost (.bbfbin)

# Key (file byte order) -> (name, confidence). Names are the boost system's property names, matched
# by file order and values; "loader" = proven, "?" = guess. docs/11.
BOOST_KEYS = {
    "da4efba7": ("model type (3 KERS shots, 4 F1 ERS, 5 classic, 6 push-to-pass/IndyCar, 7 hybrid deploy)", "loader"),
    "4423f779": ("Full Charge, J (F1 4.0 MJ, LMDh 4.86 MJ, Revuelto 5 MJ)", "high"),
    "3a74a835": ("Max Boost, kW of electric power (F1 120, LMDh 50, Valkyrie 120, Revuelto 138)", "high"),
    "8eacad13": ("Max Boost Time, s (= Full Charge / Max Boost on F1, LMDh, F-Reiza)", "high"),
    "e31a9a4e": ("Max Torque, Nm of the motor (F1 200, Valkyrie 280, Revuelto 508)", "medium"),
    "d52a5024": ("KERS Wheel Drive: string offset; REAR/FOUR/FRONT", "loader"),
    "cbfaf20d": ("AWD Torque Split (Revuelto 0.62 with FOUR, 1 elsewhere)", "medium"),
    "4576357a": ("Throttle Range (min, max)", "medium"),
    "458ffefd": ("efficiency (0.9 / 0.95)", "medium"),
    "d88ea3c8": ("Max Regen Power, W? (F1 114000, LMDh/Revuelto 150000)", "low"),
    "32ca0d59": ("Max Regen Torque? (F1 120, LMDh 172, Revuelto 150)", "low"),
    "13123e7d": ("Max Lap Energy, J (F1 4 MJ)", "medium"),
    "2cc03bae": ("Charging Threshold RPM (F1 4000, others 1000)", "low"),
    "0db07194": ("Use Deployment Modes (bool)", "loader"),
    "8ffb007b": ("RPMDeployment rows: rpm, ?, factor per map x4", "medium"),
    "b77598d6": ("GearDeployment Qual (per gear)", "loader"),
    "d6613dbc": ("GearDeployment Attack (per gear)", "loader"),
    "64b089f5": ("GearDeployment Balanced (per gear)", "loader"),
    "747d8677": ("GearDeployment Build (per gear)", "loader"),
    "d568ad73": ("Smart Balanced Mode (4 ints)", "loader"),
    "5efadc8b": ("Smart Build Mode (4 ints)", "loader"),
    "31e7a2c2": ("Qual Map (percent)", "loader"),
    "ec86bac1": ("Attack Map (percent)", "loader"),
    "1f1fd9e4": ("Total Power Limit rows (throttle 0..1.025 step 0.025 -> kW; needs 42 rows)", "loader"),
}

_FIELD = {"full_charge_j": "4423f779", "max_boost_kw": "3a74a835", "max_boost_time_s": "8eacad13",
          "max_torque_nm": "e31a9a4e", "awd_split": "cbfaf20d", "efficiency": "458ffefd",
          "max_lap_energy_j": "13123e7d", "regen_power_w": "d88ea3c8", "regen_torque": "32ca0d59"}
WHEEL_DRIVE = ("REAR", "FOUR", "FRONT")


def boost_set(data: bytes, *, wheel_drive=None, **fields) -> bytes:
    """Patch a donor hybrid .bbfbin (e.g. lamborghini_revuelto.bbfbin, type 7). Experimental: the key
    names are tentative (BOOST_KEYS). `wheel_drive` rewrites the one-string table (REAR/FOUR/FRONT)."""
    f = shcb.parse(data)
    for k, v in fields.items():
        key = _FIELD[k]
        vals = f.find_all(key)
        if not vals:
            raise KeyError(f"{k} ({key}) not in this file")
        for val in vals:
            val.set_scalar(v)
    if wheel_drive is not None:
        if wheel_drive not in WHEEL_DRIVE:
            raise ValueError(f"wheel_drive must be one of {WHEEL_DRIVE}")
        if [v.value for v in f.find_all("d52a5024")] != [0]:
            raise ValueError("expected the wheel-drive string at table offset 0")
        f.section(shcb.STRINGS_ID).data = strtab_crypt(wheel_drive.encode() + b"\0")
    return shcb.serialize(f)
