"""car.toml specs -> edited physics files (engine, gearbox, chassis, suspension, vdfm, mrdf).

Spec maths lives here; byte-level editing goes through `physics` (ShCB accessors, docs/09), which
works on every base car.

File names (docs/12). Default: the vdfm keeps the donor's chassis/suspension/engine/gearbox names and
the edited files replace the donor's inside our pak (this also changes the real donor car while our
pak is mounted). `independent` mode (car.toml [physics] independent = true, or AMS2KIT_INDEPENDENT=1)
points the vdfm at car-named files instead and leaves every donor-path file untouched. The old
"renaming crashes" verdict came from vdfms the game rejected (section pad byte, docs/12), not from the
names. The tyre set must be a base-game set (boot list TyresHD.xml): the donor's, or any other with [chassis]
tyre_set. The tyre SIZE is not in the set but in the vdfm wheel block ([chassis] tyre_size, tyres.py, docs/13).
"""
import math, os, struct

from . import donor as donor_mod
from . import physics as P

VDFM_STRTAB = 0x1F0
VDFM_CHASSIS, VDFM_ENGINE, VDFM_GEARBOX, VDFM_SUSPENSION = 0x38, 0x48, 0x70, 0x78
VDFM_COLLISION, VDFM_TYRES = 0x80, 0x88
VDFM_ALL = (0x38, 0x48, 0x50, 0x68, 0x70, 0x78, 0x80, 0x88)
DRIVETRAIN = {"RWD": 0, "AWD": 1, "4WD": 1, "FWD": 2}


class PhysicsError(Exception):
    pass


def write_vdfm_in_place(b, names):
    """New vdfm with `names` ({field offset: name}) and a fresh per-file id.

    Kept under its old name: it used to rewrite the table in place because repacking "crashed the game".
    The real cause (docs/12) was the string section's pad byte (0x1D): the game rejects a vdfm unless
    every section's size + pad adds up to the file length, so a table whose length changed modulo 16
    made the whole file invalid (no tyre set -> crash on track load).
    physics.write_vdfm now recomputes the pads, so names of any length are fine."""
    out = P.write_vdfm(b, names, new_id=True)
    if not P.serial_layout_ok(out):
        raise PhysicsError("vdfm failed the game's layout check")
    return out


def vdfm_fields(b):
    """{pointer offset: string} for the main vdfm fields (used by doctor)."""
    out = {}
    for f in VDFM_ALL:
        o = struct.unpack_from("<Q", b, f)[0]
        s = VDFM_STRTAB + o
        out[f] = b[s:b.index(b"\0", s)].decode("latin-1")
    return out


# ----------------------------------------------------------------------------- spec maths

def ice_curve(points, rev_limit):
    """The user's [[rpm, nm], ...], sorted, with a cut row just above the rev limit."""
    pts = sorted((float(r), float(t)) for r, t in points)
    if pts[0][0] > 0:
        pts.insert(0, (0.0, min(0.0, pts[0][1])))
    top = max(pts[-1][0], rev_limit)
    return pts + [(top + 250, -100.0)]


def ratio_to_cogs(ratio, lo=8, hi=255, tol=0.003):
    """(driver, driven) byte cogs for the ratio: the smallest pair within `tol` (relative), else the closest."""
    cands = [(d, round(ratio * d)) for d in range(lo, 64) if 1 <= round(ratio * d) <= hi]
    good = [c for c in cands if abs(c[1] / c[0] / ratio - 1) <= tol]
    return good[0] if good else min(cands, key=lambda p: abs(p[1] / p[0] - ratio))


DRIVE_WHEELS = {"AWD": b"FOUR", "4WD": b"FOUR", "RWD": b"REAR", "FWD": b"FRONT"}


def set_drive_wheels(data, layout):
    """The chassis file also names the driven wheels (REAR/FOUR/FRONT, in its encrypted string table,
    docs/11). Make it match the driveline: an AWD driveline on a REAR chassis drove like the RWD car.
    Same-length swaps (REAR<->FOUR) only; FRONT would need the table resized."""
    from . import ev, shcb
    want = DRIVE_WHEELS[layout]
    f = shcb.parse(data)
    sec = f.section(shcb.STRINGS_ID)
    if not sec:
        return data, None
    plain = ev.strtab_crypt(sec.data)
    toks = plain.split(b"\0")
    cur = next((t for t in toks if t in (b"REAR", b"FOUR", b"FRONT")), None)
    if cur is None or cur == want:
        return data, cur
    if len(cur) != len(want):
        raise PhysicsError(f"chassis drives {cur.decode()} wheels; changing to {want.decode()} needs a resized "
                           "string table (not supported yet): pick a donor with the same drive layout")
    sec.data = ev.strtab_crypt(plain.replace(b"\0" + cur + b"\0", b"\0" + want + b"\0", 1)
                               if (b"\0" + cur + b"\0") in plain else plain.replace(cur, want, 1))
    return shcb.serialize(f), cur


PHYSICS_KINDS = ("engine", "gearbox", "chassis", "suspension")


def parse_override_key(k):
    """'chassis.86ae662b' / 'chassis.86ae662b#1' -> ('chassis', '86ae662b', 1); index None = every occurrence."""
    kind, _, rest = k.partition(".")
    key, _, idx = rest.partition("#")
    return kind, key.lower(), (int(idx) if idx else None)


def apply_overrides(f, kind, project, log=print):
    """Apply car.toml [overrides] for one physics file (any field by key hash, applied last).

    Values: a number for scalar fields, a list for tuple fields (same length as the donor's).
    Keys name the file kind and the field key, e.g. "chassis.beba677b" = [0.30, 0, 0];
    "#n" selects the n-th occurrence of a repeated key."""
    from . import shcb as _shcb
    n = 0
    for k, val in (project.cfg.get("overrides") or {}).items():
        okind, key, idx = parse_override_key(k)
        if okind != kind:
            continue
        hits = f.find_all(_shcb.key_of(key))
        if not hits:
            raise PhysicsError(f"override {k}: field {key} not in the donor's {kind} file")
        for i, v in enumerate(hits):
            if idx is not None and i != idx:
                continue
            if isinstance(val, (list, tuple)):
                if not isinstance(v.value, (list, tuple)) or len(v.value) != len(val):
                    raise PhysicsError(f"override {k}: expected {len(v.value) if isinstance(v.value, (list, tuple)) else 1} values")
                v.set_tuple(list(val))
            else:
                if isinstance(v.value, (list, tuple)):
                    raise PhysicsError(f"override {k}: field holds {len(v.value)} values, give a list")
                v.set_scalar(val)
            n += 1
    if n:
        log(f"overrides: {n} {kind} field(s) set")
    return n


def driveline_layout(project):
    """AWD/RWD/FWD of the chosen driveline group, else of the donor's record."""
    import re
    group = project.cfg["powertrain"].get("driveline")
    if not group:
        m = re.search(r"^\s*contents\s+(\S+)", (project.donor_dir / "driveline.rg").read_text(encoding="latin-1"), re.M)
        group = m.group(1) if m else project.cfg["powertrain"]["drivetrain"]
    layout = group.split("_")[0].upper()
    return layout if layout in DRIVETRAIN else project.cfg["powertrain"]["drivetrain"].upper()


def retarget_collision(data, donor_base, new_base):
    """Collision xml (.xml/.joi.xml/.sys.xml) with the main object COLLISION_CONVEX_<donor> renamed.

    The game builds the object name as "COLLISION_CONVEX_" + vdfm field 0x80 and loads
    collision\\<field>.xml (+ .joi.xml) for it. Sub-shape names (COLLISION_CONVEX_<DONOR>_CHASSIS_LODA...)
    are left alone: they are names inside the donor's shape set, not keyed by the vdfm."""
    import re
    pat = re.compile(rb"COLLISION_CONVEX_" + re.escape(donor_base.encode()) + rb'(?=")', re.I)
    return pat.sub(b"COLLISION_CONVEX_" + new_base.upper().encode(), data)


def donor_visual_geometry(project):
    """(wheelbase, track front, track rear) of the donor's VISUAL wheels (its .vhf rim hubs), or None."""
    from .mesh import blend_bridge
    info = donor_mod.info(project)
    folder = info.get("folder", "vehicles\\" + info["key"])
    try:
        text = donor_mod.file(project, folder + "\\" + info["key"] + ".vhf").read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None
    w = blend_bridge.visual_wheel_centres(text)
    if len(w) != 4:
        return None
    return ((w["RL"][2] + w["RR"][2]) / 2 - (w["FL"][2] + w["FR"][2]) / 2, w["FL"][0] - w["FR"][0], w["RL"][0] - w["RR"][0])


def geometry_targets(project, sus):
    """(wheelbase, track front, track rear) to pass to Suspension.set_geometry, or None to keep the donor's.

    [chassis] geometry_reference = "physics" (default, as the BYD builds): the Specs values are the physics
    wheel-centre distances. "visual": they are the real car's (visual) values; the physics geometry moves by
    the same amount as the visible wheels (donor vhf hubs -> Specs), so a donor whose physics geometry differs
    from its body (VW Virtus GTS: Mini Cooper suspension, physics wheelbase 2.466 vs 2.651 visual) keeps
    that offset and the wheels end up where the Specs say."""
    ch = project.cfg["chassis"]
    if not any(ch[k] for k in ("wheelbase_m", "track_front_m", "track_rear_m")):
        return None
    wb, (tf, tr) = sus.wheelbase, sus.tracks
    vis = donor_visual_geometry(project) if ch.get("geometry_reference", "physics") == "visual" else None
    if vis:
        return (wb + (ch["wheelbase_m"] - vis[0] if ch["wheelbase_m"] else 0.0),
                tf + (ch["track_front_m"] - vis[1] if ch["track_front_m"] else 0.0),
                tr + (ch["track_rear_m"] - vis[2] if ch["track_rear_m"] else 0.0))
    return (ch["wheelbase_m"] or wb, ch["track_front_m"] or tf, ch["track_rear_m"] or tr)


def independent_options(project):
    """(independent, rename_collision) from car.toml [physics], overridden by AMS2KIT_INDEPENDENT /
    AMS2KIT_RENAME_COLLISION (1 = on, 0 = off). Collision renaming needs independent mode."""
    cfg = project.cfg.get("physics", {})
    ind = bool(cfg.get("independent", True))
    col = bool(cfg.get("rename_collision", True))
    if os.environ.get("AMS2KIT_INDEPENDENT") is not None:
        ind = os.environ["AMS2KIT_INDEPENDENT"] not in ("", "0")
    if os.environ.get("AMS2KIT_RENAME_COLLISION") is not None:
        col = os.environ["AMS2KIT_RENAME_COLLISION"] not in ("", "0")
    return ind, ind and col


# ----------------------------------------------------------------------------- top level

def build(project, log=print, independent=None, rename_collision=None):
    """Return ({pak path: bytes}, names) for the new car's physics files.

    independent: car-named chassis/suspension/engine/gearbox (+ collision with rename_collision);
    None = from car.toml / environment (independent_options)."""
    ind, col = independent_options(project)
    independent = ind if independent is None else independent
    rename_collision = bool(col if rename_collision is None else rename_collision) and bool(independent)
    info = donor_mod.info(project)
    pk = info["physics_key"]
    dfile = lambda p: donor_mod.file(project, p).read_bytes()
    vdfm = dfile(f"vehicles\\physics\\vehicles\\{pk}.vdfm")
    fields = vdfm_fields(vdfm)
    pt, ch = project.cfg["powertrain"], project.cfg["chassis"]
    out = {}

    chassis_name, susp_name = fields[VDFM_CHASSIS], fields[VDFM_SUSPENSION]
    eng = P.Engine(dfile(f"vehicles\\physics\\engines\\{fields[VDFM_ENGINE]}.edfbin"))
    gbx = P.Gearbox(dfile(f"vehicles\\physics\\gearbox\\{fields[VDFM_GEARBOX]}.gdfbin"))
    chs = P.Chassis(dfile(f"vehicles\\physics\\chassis\\{chassis_name}.cdfbin"))
    sus = P.Suspension(dfile(f"vehicles\\physics\\suspension\\{susp_name}.sdfbin"))

    # geometry first: the EV gearing uses the rolling radius
    moves = {c: (0.0, 0.0) for c in P.CORNERS}
    target = geometry_targets(project, sus)
    if target:
        moves = sus.set_geometry(*target)
        # reference points follow the axles front to back only (as in the build proven in game)
        chs.shift_axle_points(moves["FL"][1], moves["RL"][1])
        log(f"geometry: wheelbase {sus.wheelbase:.3f} m, tracks {sus.tracks[0]:.3f}/{sus.tracks[1]:.3f} m")
    # rolling radius = the physics tyre's diameter / 2 (vdfm 0xC8 block, docs/13): Specs tyre_size, else the donor's
    from . import tyres as tyres_mod
    tyre_sizes = tyres_mod.project_sizes(project)
    axle = "front" if driveline_layout(project) == "FWD" else "rear"
    radius = (ch["wheel_radius_m"] or tyres_mod.rolling_radius(project, vdfm, axle)
              or donor_mod.tyre_radius(project) or 0.33)

    # engine + gearing
    if pt["type"] == "ev":
        # electric motor curve with lift-off regen in the engine-braking column (ev.py, docs/11)
        from . import ev
        # sim_power_kw / sim_torque_nm tune the simulated motor (driveline losses, measured performance)
        # while power_kw / torque_nm stay the real car's menu figures; 0 = derive as before
        sim_kw = pt.get("sim_power_kw") or pt["power_kw"]
        peak = pt.get("sim_torque_nm") or sim_kw * 1000 / (pt["rev_limit"] * pt["base_speed_fraction"] * 2 * math.pi / 60)
        rows = ev.motor_rows(sim_kw, peak, pt["rev_limit"], regen_kw=pt.get("regen_kw", 60.0),
                             regen_nm=pt.get("regen_nm", 300.0))
        # the limiter cut (d39464af, scaled with the rev limit) starts just under the limit: gear the car
        # so the top speed is reached at the cut, not at the limit (else it tops out a few km/h short)
        from . import shcb as _shcb
        cut = eng.file.find(_shcb.key_of("d39464af"))
        top_rpm = pt["rev_limit"]
        if cut is not None and eng.rev_limit and not os.environ.get("AMS2KIT_FINAL_AT_LIMIT"):
            top_rpm = pt["rev_limit"] * list(cut.value)[0] / eng.rev_limit
        final = top_rpm * 2 * math.pi / 60 * radius / (pt["top_speed_kmh"] / 3.6)
        gbx.make_single_speed(cogs=(20, 20))   # identical 1:1 gears: the driveline keeps its slot count
        gbx.bevel = (1, 1)                     # all reduction in the final drive
        gears = 1
        # a turbo donor multiplies the torque table by a boost map (515f5e83: rpm + 5 boost-level
        # multipliers, up to ~2.6x on the Lancer R); an electric motor has no boost, so every multiplier = 1
        from . import shcb as _shcb
        flat = 0
        for v in eng.file.find_all(_shcb.key_of("515f5e83")):
            vals = list(v.value)
            v.set_tuple([vals[0]] + [1.0] * (len(vals) - 1))
            flat += 1
        if flat:
            log(f"EV: turbo boost map neutralised ({flat} rows)")
        log(f"EV: {peak:.0f} Nm simulated peak torque, final drive {final:.3f} (rolling radius {radius:.3f} m)")
    else:
        rows = ice_curve(pt["torque_curve"], pt["rev_limit"])
        if pt.get("torque_at_full_boost", True) and eng.boost_multipliers():
            # turbo donors multiply the table by a boost map; the Specs curve is the real (boosted) torque,
            # so the table gets curve / full-boost multiplier (docs/03; [guess] last column = full boost)
            rows = [(r, t / eng.full_boost_multiplier(r)) for r, t in rows]
            log(f"turbo donor: torque table = curve / full-boost multiplier "
                f"({eng.full_boost_multiplier(2000):.2f} at 2000 rpm, {eng.full_boost_multiplier(6000):.2f} at 6000 rpm)")
        final = pt["final_drive"]
        if len(pt["gears"]) != gbx.gear_count:
            log(f"warning: donor gearbox lists {gbx.gear_count} gear options, spec has {len(pt['gears'])}")
        gbx.set_gear_cogs([ratio_to_cogs(r) for r in pt["gears"]])
        gears = len(pt["gears"])
    if pt["type"] == "ice":
        final /= gbx.bevel[1] / gbx.bevel[0]   # the donor's bevel stays; the final drive makes up the rest
    gbx.final_drive = ratio_to_cogs(final)
    eng.set_torque_curve(rows, resize=True)
    donor_limit = eng.rev_limit
    eng.rev_limit = int(pt["rev_limit"])
    # Other rpm settings sit relative to the donor's rev limit (7902b6bd: an rpm window, e.g. Camaro
    # 3000/4500; d39464af: a cut point + width just under the limit, Camaro 5800/165). Left at the donor's
    # values they capped the BYD's power above ~4500 rpm, so they scale with the new limit.
    if donor_limit and pt.get("scale_rpm_settings", True):
        from . import shcb as _shcb
        f = ratio = int(pt["rev_limit"]) / donor_limit
        for key, n_scaled in (("7902b6bd", 2), ("d39464af", 1)):
            for v in eng.file.find_all(_shcb.key_of(key)):
                vals = list(v.value)
                vals[:n_scaled] = [int(round(x * ratio)) for x in vals[:n_scaled]]
                v.set_tuple(vals)
        log(f"rpm settings scaled x{f:.3f} with the rev limit ({donor_limit} -> {int(pt['rev_limit'])})")
    try:
        eng.displacement = float(pt["displacement_l"])
    except P.MissingField:
        pass
    # file names: the donor's (our files override the donor's at its paths) or the car's own
    key = project.key
    renames = {}
    if independent:
        renames = {VDFM_ENGINE: key, VDFM_GEARBOX: key, VDFM_CHASSIS: key, VDFM_SUSPENSION: key}
        if rename_collision:
            renames[VDFM_COLLISION] = key
    elif os.environ.get("AMS2KIT_RENAME_ENGINE"):       # engine/gearbox only (the earlier experiment)
        renames = {VDFM_ENGINE: key, VDFM_GEARBOX: key}
    tyre_set = (ch.get("tyre_set") or "").strip()
    if tyre_set and tyre_set.lower() != fields[VDFM_TYRES].lower():
        # any base set works (the name is looked up in the boot pool); a name outside TyresHD.xml = null set = crash
        from . import game as game_mod
        sets = {s.lower(): s for s in tyres_mod.boot_tyre_sets(game_mod.find_game())}
        if tyre_set.lower() not in sets:
            raise PhysicsError(f"tyre_set {tyre_set!r} is not a base-game tyre set (TyresHD.xml); "
                               "see `python -m ams2kit tyres <project>`")
        renames[VDFM_TYRES] = sets[tyre_set.lower()]
    new_vdfm = write_vdfm_in_place(vdfm, renames)
    # wheel block (docs/13): tyre width/diameter = the physics tyre size; positions follow the wheel moves like the
    # .vhf hubs (they are the same visual-frame points). AMS2KIT_KEEP_VDFM_WHEELS=1 keeps the donor's positions.
    keep_pos = os.environ.get("AMS2KIT_KEEP_VDFM_WHEELS") not in (None, "", "0")
    new_vdfm = tyres_mod.write_vdfm_wheels(new_vdfm, tyre_sizes, None if keep_pos else moves)
    if not P.serial_layout_ok(new_vdfm):
        raise PhysicsError("vdfm failed the game's layout check after the wheel block edit")
    if tyre_sizes:
        log("tyres: " + ", ".join(f"{a} {s['text']} (width {s['width']:.3f} m, diameter {s['diameter']:.4f} m)"
                                  for a, s in tyre_sizes.items()) +
            f"; donor {tyres_mod.read_vdfm_wheels(vdfm)['RL']['diameter']:.4f} m")
    engine_new = renames.get(VDFM_ENGINE, fields[VDFM_ENGINE])
    gearbox_new = renames.get(VDFM_GEARBOX, fields[VDFM_GEARBOX])
    chassis_new = renames.get(VDFM_CHASSIS, chassis_name)
    susp_new = renames.get(VDFM_SUSPENSION, susp_name)
    if renames:
        log("vdfm names: " + ", ".join(f"{k:#x}={v}" for k, v in sorted(renames.items())) +
            f" (tyres {renames.get(VDFM_TYRES, fields[VDFM_TYRES])})")
    apply_overrides(eng.file, "engine", project, log)
    apply_overrides(gbx.file, "gearbox", project, log)
    out[f"vehicles\\physics\\engines\\{engine_new}.edfbin"] = eng.to_bytes()
    out[f"vehicles\\physics\\gearbox\\{gearbox_new}.gdfbin"] = gbx.to_bytes()

    donor_mass = float(chs.mass)
    if ch["mass_kg"]:
        ratio = ch["mass_kg"] / donor_mass
        chs.mass = int(ch["mass_kg"])
        chs.inertia = tuple(v * ratio for v in chs.inertia)
        chs.scale_springs(ratio)
    if ch["cg_height_m"]:
        chs.cg_height = float(ch["cg_height_m"])
    # The chassis also names the driven wheels. Switching a REAR donor chassis to FOUR lost the front
    # axle's torque (Camaro SS: 0.4 g instead of 0.65 g; its front suspension has no drive hardware),
    # so the donor's stays unless powertrain.chassis_drive = "match".
    apply_overrides(chs.file, "chassis", project, log)
    apply_overrides(sus.file, "suspension", project, log)
    if pt.get("chassis_drive", "keep") != "match" or os.environ.get("AMS2KIT_KEEP_CHASSIS_DRIVE"):
        chassis_bytes, was = chs.to_bytes(), None
    else:
        chassis_bytes, was = set_drive_wheels(chs.to_bytes(), driveline_layout(project))
    if was and was != DRIVE_WHEELS[driveline_layout(project)]:
        log(f"chassis drive wheels: {was.decode()} -> {DRIVE_WHEELS[driveline_layout(project)].decode()}")
    out[f"vehicles\\physics\\chassis\\{chassis_new}.cdfbin"] = chassis_bytes
    out[f"vehicles\\physics\\suspension\\{susp_new}.sdfbin"] = sus.to_bytes()
    if rename_collision:
        dcol = fields[VDFM_COLLISION]
        for ext in (".xml", ".joi.xml", ".sys.xml"):
            try:
                src = dfile(f"vehicles\\physics\\collision\\{dcol.lower()}{ext}")
            except FileNotFoundError:
                if ext == ".sys.xml":
                    continue
                raise
            out[f"vehicles\\physics\\collision\\{key}{ext}"] = retarget_collision(src, dcol, key)

    # vdfm + menu stats
    out[f"vehicles\\physics\\vehicles\\{project.key}.vdfm"] = new_vdfm
    values = {"top_speed_ms": pt["top_speed_kmh"] / 3.6, "mass_kg": float(ch["mass_kg"] or donor_mass),
              "gear_count": gears, "torque_nm": float(pt["torque_nm"]), "power_hp": pt["power_kw"] * 1.35962,
              "drivetrain": DRIVETRAIN.get(driveline_layout(project), 1), "engine_layout": int(pt["engine_layout"]),
              "rear_weight_fraction": float(ch["rear_weight"]), "displacement_l": float(pt["displacement_l"]),
              "wheelbase_m": float(ch["wheelbase_m"] or sus.wheelbase)}   # menu: the Specs value
    if pt["type"] == "ev":
        values.update(gear_at_100=1, gear_at_160=1, boost=0, aspiration=0)
    elif pt["gears"] and final:
        # menu "gear at 100/160 km/h": the first gear that reaches the speed below the rev limit
        def gear_for(kmh):
            for i, r in enumerate(pt["gears"]):
                if pt["rev_limit"] * 2 * math.pi / 60 * radius / (r * pt["final_drive"]) * 3.6 >= kmh:
                    return i + 1
            return len(pt["gears"])
        values.update(gear_at_100=gear_for(100), gear_at_160=gear_for(160))
    if project.cfg["stats"]["zero_to_100_s"]:
        values["zero_to_100_s"] = float(project.cfg["stats"]["zero_to_100_s"])
    out[f"vehicles\\physics\\statistics\\{project.key}.mrdf"] = P.write_stats(dfile(f"vehicles\\physics\\statistics\\{pk}.mrdf"), values)
    names = {"engine": engine_new, "gearbox": gearbox_new, "base": chassis_new, "suspension": susp_new,
             "donor_base": chassis_name, "donor_suspension": susp_name, "independent": bool(independent),
             "collision": renames.get(VDFM_COLLISION, fields[VDFM_COLLISION]), "tyres": renames.get(VDFM_TYRES, fields[VDFM_TYRES]),
             "donor_tyres": fields[VDFM_TYRES], "rolling_radius": round(radius, 4),
             "tyre_sizes": {a: z["text"] for a, z in tyre_sizes.items()} if tyre_sizes else None,
             "donor_mass": donor_mass, "wheelbase": round(sus.wheelbase, 3),
             "wheel_moves": {c: [round(dx, 5), round(dz, 5)] for c, (dx, dz) in moves.items()}}
    return out, names


PHYSICS_EXT = {"engine": ("engines", "edfbin", VDFM_ENGINE), "gearbox": ("gearbox", "gdfbin", VDFM_GEARBOX),
               "chassis": ("chassis", "cdfbin", VDFM_CHASSIS), "suspension": ("suspension", "sdfbin", VDFM_SUSPENSION)}


def physics_table(project):
    """Every keyed field of the donor's engine/gearbox/chassis/suspension files for the Physics page:
    [{kind, key, idx, count, object, type, donor, built, override, name, unit, help}] (built = last build)."""
    from . import shcb as _shcb
    try:
        from . import fields as _fields
    except ImportError:
        _fields = None
    pk = donor_mod.info(project)["physics_key"]
    dfields = vdfm_fields(donor_mod.file(project, f"vehicles\\physics\\vehicles\\{pk}.vdfm").read_bytes())
    phys = project.build_dir / "install" / "Vehicles" / "physics"
    bvdfm = phys / "vehicles" / f"{project.key}.vdfm"
    bfields = vdfm_fields(bvdfm.read_bytes()) if bvdfm.exists() else {}
    ov = project.cfg.get("overrides") or {}
    plain = lambda v: list(v.value) if v.type == _shcb.T_TUPLE else v.value
    rows = []
    for kind, (folder, ext, slot) in PHYSICS_EXT.items():
        donor_f = _shcb.parse(donor_mod.file(project, "\\".join(("vehicles", "physics", folder, f"{dfields[slot]}.{ext}"))).read_bytes())
        bf = phys / folder / f"{bfields.get(slot, '')}.{ext}"
        built = {}
        if bfields and bf.exists():
            seen = {}
            for _, _, v in _shcb.parse(bf.read_bytes()).iter_values():
                i = seen[v.key] = seen.get(v.key, -1) + 1
                built[(v.key, i)] = plain(v)
        seen, obj = {}, None
        counts = {}
        for _, _, v in donor_f.iter_values():
            counts[v.key] = counts.get(v.key, 0) + 1
        for e in donor_f.entries:
            if isinstance(e, _shcb.Object):
                obj = _shcb.key_hex(e.key)
                continue
            vals = [e] if isinstance(e, _shcb.Value) else e.members if isinstance(e, _shcb.Group) else []
            for v in vals:
                i = seen[v.key] = seen.get(v.key, -1) + 1
                kh = _shcb.key_hex(v.key)
                o = ov.get(f"{kind}.{kh}#{i}", ov.get(f"{kind}.{kh}"))
                d = _fields.describe(kind, kh) if _fields and hasattr(_fields, "describe") else None
                d = d or {}
                rows.append({"kind": kind, "key": kh, "idx": i, "count": counts[v.key], "object": obj,
                             "type": _shcb.TYPE_NAMES.get(v.type, str(v.type)), "donor": plain(v),
                             "built": built.get((v.key, i)), "override": o,
                             "name": d.get("name") or "", "unit": d.get("unit") or "",
                             "help": d.get("desc") or "", "confidence": d.get("confidence") or ""})
    return rows
