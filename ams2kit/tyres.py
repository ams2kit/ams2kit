"""Tyre and wheel size (docs/13).

Where the size lives [file + proven]:
- The PHYSICS size is in the car's .vdfm, not in the tyre set:
    0x98 + 12*i  wheel position x, y, z (FL, FR, RL, RR) in the visual frame (= the .vhf hub matrices and the
                 tyre meshes' CARCASS bone; y = hub height above the design ground)
    0xC8 + 8*i   tyre width, tyre DIAMETER (m)
  The game uses radius = 0.5 * diameter.
  For 251 of 267 base cars diameter/2 equals the tyre mesh radius within 1 cm.
- The tyre set (vdfm 0x88, a boot-list name from TyresHD.xml) holds the tyre model's grip/heat/carcass
  parameters plus a width per axle (key bd034c23); it has no radius. A mod can point at any base set.
- Visual tyres are skinned meshes; their bone binds (CARCASS = hub, RIM = bead, ROAD = contact, SIDEWALL_L/R)
  are in car space and the render reads tyre dimensions from them, so a resize scales the
  vertices and the bone offsets together (resize_tyre_meb).
"""
import json, math, re, struct

import numpy as np

VDFM_WHEEL_POS = 0x98      # 4 x float3
VDFM_WHEEL_SIZE = 0xC8     # 4 x (width, diameter)
CORNERS = ("FL", "FR", "RL", "RR")
INCH = 0.0254

_SIZE_RE = re.compile(r"^\s*(\d{3})\s*/\s*(\d{2,3})\s*(?:Z?R|-|\s)\s*(\d{2}(?:\.\d)?)\s*$", re.I)


def parse_size(s):
    """'245/45R19' -> {'width': 0.245, 'diameter': 0.7031, 'rim_radius': 0.2413, 'text': ...}.

    Also accepts '245/45 R19', '245/45ZR19' and a metric dict/str 'w=0.245,d=0.70,rim=19'."""
    if isinstance(s, dict):
        w, d, rim = float(s["width"]), float(s["diameter"]), float(s.get("rim_in", 0)) or None
        return {"width": w, "diameter": d, "rim_radius": rim * INCH / 2 if rim else None, "text": str(s)}
    m = _SIZE_RE.match(str(s))
    if not m:
        raise ValueError(f"tyre size {s!r}: expected e.g. 245/45R19")
    w_mm, aspect, rim_in = int(m.group(1)), int(m.group(2)), float(m.group(3))
    w = w_mm / 1000.0
    d = 2 * w * aspect / 100.0 + rim_in * INCH
    return {"width": round(w, 4), "diameter": round(d, 4), "rim_radius": round(rim_in * INCH / 2, 4),
            "text": f"{w_mm}/{aspect}R{m.group(3)}"}


def project_sizes(project):
    """{'front': size, 'rear': size} from car.toml [chassis] tyre_size / tyre_size_rear, or None."""
    ch = project.cfg["chassis"]
    f = (ch.get("tyre_size") or "").strip()
    r = (ch.get("tyre_size_rear") or "").strip() or f
    if not f and not r:
        return None
    return {"front": parse_size(f or r), "rear": parse_size(r)}


# ----------------------------------------------------------------------------- vdfm wheel block

def read_vdfm_wheels(b):
    """{corner: {'pos': (x, y, z), 'width': w, 'diameter': d}}."""
    out = {}
    for i, c in enumerate(CORNERS):
        pos = struct.unpack_from("<3f", b, VDFM_WHEEL_POS + 12 * i)
        w, d = struct.unpack_from("<2f", b, VDFM_WHEEL_SIZE + 8 * i)
        out[c] = {"pos": tuple(round(v, 6) for v in pos), "width": round(w, 5), "diameter": round(d, 5)}
    return out


def write_vdfm_wheels(b, sizes=None, moves=None):
    """vdfm bytes with new tyre sizes ({'front'|'rear': size}) and/or wheel positions moved by
    moves {corner: (dx, dz)} (the same moves as the suspension and the .vhf hubs). Same length."""
    b = bytearray(b)
    for i, c in enumerate(CORNERS):
        if sizes:
            s = sizes["front" if c[0] == "F" else "rear"]
            struct.pack_into("<2f", b, VDFM_WHEEL_SIZE + 8 * i, s["width"], s["diameter"])
        if moves and c in moves:
            x, y, z = struct.unpack_from("<3f", b, VDFM_WHEEL_POS + 12 * i)
            dx, dz = moves[c]
            struct.pack_into("<3f", b, VDFM_WHEEL_POS + 12 * i, x + dx, y, z + dz)
    return bytes(b)


def rolling_radius(project, vdfm=None, axle="rear"):
    """Physics radius (diameter / 2) of the driven axle: the Specs tyre size, else the donor vdfm's."""
    sz = project_sizes(project)
    if sz:
        return sz[axle]["diameter"] / 2
    if vdfm is not None:
        w = read_vdfm_wheels(vdfm)
        d = w["RL" if axle == "rear" else "FL"]["diameter"]
        if 0.2 < d < 1.6:
            return d / 2
    return None


# ----------------------------------------------------------------------------- tyre sets

def boot_tyre_sets(gamedir):
    """Set names of the boot list vehicles\\physics\\tyres\\TyresHD.xml (label stems), in list order."""
    from . import paks
    from pathlib import Path
    with paks.PakReader(Path(gamedir) / "Pakfiles" / "PHYSICSBOOTFLOW.bff") as r:
        xml = r.read("vehicles\\physics\\tyres\\tyreshd.xml").decode("utf-8", "replace")
    return [m.group(1) for m in re.finditer(r'<Item label="([^"]+?)\.hdtbin"', xml, re.I)]


def catalog(gamedir, refresh=False):
    """{set name: {'widths': [front, rear] (tyre-set width per axle), 'compounds': [...], 'cars': [...],
    'sizes': [[front w, front d, rear w, rear d], ...] (vdfm sizes of the cars using it)}} for every base set.
    Cached in %LOCALAPPDATA%\\ams2kit\\tyre_sets.json."""
    from . import game, paks, shcb, ev, physics as P
    from pathlib import Path
    cache = game.DATA_DIR / "tyre_sets.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    sets = boot_tyre_sets(gamedir)
    out = {}
    with paks.PakReader(Path(gamedir) / "Pakfiles" / "PHYSICSPERSISTENT.bff") as r:
        paths = {p.lower(): p for p in r.paths}
        for s in sets:
            p = paths.get(f"vehicles\\physics\\tyres\\{s.lower()}.hdtbin")
            e = {"widths": [], "compounds": [], "cars": [], "sizes": []}
            if p:
                f = shcb.parse(r.read(p))
                e["widths"] = [round(float(v.value), 4) for v in f.find_all("bd034c23")]
                try:
                    e["compounds"] = [t for t in ev.strings_of(f) if t and t != "Lat"]
                except ValueError:
                    pass
            out[s] = e
        low = {s.lower(): s for s in out}
        for p in paths.values():
            if not p.endswith(".vdfm"):
                continue
            b = r.read(p)
            try:
                t = P.read_vdfm(b).get("tyres", "")
            except Exception:
                continue
            s = low.get(t.lower())
            if s:
                w = read_vdfm_wheels(b)
                out[s]["cars"].append(p.rsplit("\\", 1)[-1][:-5])
                sz = [w["FL"]["width"], w["FL"]["diameter"], w["RL"]["width"], w["RL"]["diameter"]]
                if sz not in out[s]["sizes"]:
                    out[s]["sizes"].append(sz)
    game.DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def rank_sets(cat, sizes, road=None):
    """[(score, set, entry)] best first: tyre-set widths vs the wanted widths (cm), plus the size of the cars
    that use the set (diameter, cm). road=True prefers sets with a 'Street'/'Road' compound."""
    rows = []
    for s, e in cat.items():
        if not e["widths"]:
            continue
        wf, wr = e["widths"][0], e["widths"][-1]
        score = abs(wf - sizes["front"]["width"]) * 100 + abs(wr - sizes["rear"]["width"]) * 100
        if e["sizes"]:
            d = min(abs(z[1] - sizes["front"]["diameter"]) + abs(z[3] - sizes["rear"]["diameter"]) for z in e["sizes"])
            score += d * 50
        if road is not None:
            is_road = any(c.lower() in ("street", "road", "roadsport") for c in e["compounds"])
            score += 0 if is_road == road else 5
        rows.append((round(score, 2), s, e))
    rows.sort(key=lambda t: t[0])
    return rows


# ----------------------------------------------------------------------------- visual tyre meshes

def tyre_bones(m):
    """{role: (x, y, z)} of a skinned tyre mesh's bones (CARCASS, RIM, ROAD, SIDEWALL_LEFT, SIDEWALL_RIGHT)."""
    out = {}
    for n, x in zip(m.bone_names, m.bone_xforms):
        for role in ("CARCASS", "RIM", "ROAD", "SIDEWALL_LEFT", "SIDEWALL_RIGHT"):
            if n.upper().endswith(role):
                out[role] = tuple(x[9:12])
    return out


def tyre_dims(m):
    """(outer radius, bead radius, width) of a donor tyre mesh from its bones (vertex AABB as fallback)."""
    b = tyre_bones(m)
    pos = np.array(m.decoded(0), dtype=np.float64)
    width = float(pos[:, 0].max() - pos[:, 0].min())
    r = np.hypot(pos[:, 1], pos[:, 2])
    if "CARCASS" in b and "ROAD" in b and "RIM" in b:
        return b["CARCASS"][1] - b["ROAD"][1], b["CARCASS"][1] - b["RIM"][1], width
    return float(r.max()), float(r.min()), width


def _radial_map(r, r_in0, r_out0, r_in1, r_out1):
    k = (r_out1 - r_in1) / (r_out0 - r_in0)
    return r_in1 + (r - r_in0) * k, k


def resize_tyre_meb(m, outer, bead, width_scale):
    """Resized copy (new Meb object, same file name/key) of a skinned tyre mesh.

    Vertices (wheel-local, axle = x): x *= width_scale; radius r -> linear map of [bead0, outer0] onto
    [bead, outer] (the sidewall profile keeps its shape). Normals/tangents follow the map's Jacobian.
    Bone binds: offsets from CARCASS are mapped the same way (CARCASS itself stays at the hub)."""
    import copy
    from .mesh import meb_read as R, meb_write as W
    o0, b0, _ = tyre_dims(m)
    m = copy.deepcopy(m)
    pos = np.array(m.decoded(0), dtype=np.float64)
    y, z = pos[:, 1], pos[:, 2]
    r = np.hypot(y, z)
    r_new, k = _radial_map(r, b0, o0, bead, outer)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(r > 1e-9, r_new / r, 1.0)
    new = np.column_stack([pos[:, 0] * width_scale, y * t, z * t])
    # Jacobian in (axial, radial, tangential) coordinates: diag(width_scale, k, t)
    er = np.column_stack([np.zeros_like(r), np.where(r > 1e-9, y / np.maximum(r, 1e-9), 1.0),
                          np.where(r > 1e-9, z / np.maximum(r, 1e-9), 0.0)])
    et = np.column_stack([np.zeros_like(r), -er[:, 2], er[:, 1]])
    ex = np.array([1.0, 0.0, 0.0])

    def transform(v, inverse_transpose):
        a, rr, tt = v @ ex, np.einsum("ij,ij->i", v, er), np.einsum("ij,ij->i", v, et)
        if inverse_transpose:
            a, rr, tt = a / width_scale, rr / k, tt / t
        else:
            a, rr, tt = a * width_scale, rr * k, tt * t
        out = a[:, None] * ex + rr[:, None] * er + tt[:, None] * et
        n = np.linalg.norm(out, axis=1)
        return out / np.where(n > 1e-12, n, 1.0)[:, None]

    def put(stream, arr):
        stream.raw = arr.astype("<f4").tobytes()

    for s in m.streams:
        if s.semantic == 0 and s.index == 0:
            raw = new.astype("<f4").tobytes()
            s.raw = R.crypt_positions(raw, m.file_name) if s.fmt == R.FMT_ENC_POS else raw
        elif s.semantic in (2, 4, 5) and s.fmt == 2:
            v = np.frombuffer(s.raw, dtype="<f4").reshape(-1, 3).astype(np.float64)
            put(s, transform(v, s.semantic == 2))
    # bone binds (car space, CARCASS = hub)
    bones = tyre_bones(m)
    if "CARCASS" in bones:
        cx, cy, cz = bones["CARCASS"]
        xf = []
        for x in m.bone_xforms:
            x = list(x)
            dx, dy, dz = x[9] - cx, x[10] - cy, x[11] - cz
            rr = math.hypot(dy, dz)
            if rr > 1e-6:
                rn, _ = _radial_map(rr, b0, o0, bead, outer)
                dy, dz = dy * rn / rr, dz * rn / rr
            x[9], x[10], x[11] = cx + dx * width_scale, cy + dy, cz + dz
            xf.append(tuple(x))
        m.bone_xforms = xf
    # derived bounds
    rc = W.recompute(m)
    m.aabb, m.sphere = rc["aabb"], rc["sphere"]
    for ib, d in zip(m.ibufs, rc["ibufs"]):
        ib.aabb, ib.sphere = d["aabb"], d["sphere"]
    return m


def is_tyre_mesh(path):
    return bool(re.search(r"(tire|tyre)_(lf|rf|lr|rr|fl|fr|rl)(_[a-z0-9]+)*\.meb$", path.lower()))


def corner_of(path):
    m = re.search(r"(tire|tyre)_(lf|rf|lr|rr|fl|fr|rl)", path.lower())
    return {"lf": "FL", "rf": "FR", "lr": "RL", "rr": "RR", "fl": "FL", "fr": "FR", "rl": "RL"}[m.group(2)] if m else None


def resize_plan(project, vdfm):
    """{corner: {'outer', 'bead', 'width_scale', ...}} for the donor's tyre meshes, or None (no tyre size set).

    outer = new physics radius + the donor's mesh-minus-physics offset (donors draw the tyre a few mm larger than
    diameter/2; the same offset is kept), bead = new rim radius + the donor's bead-minus-nominal offset is not
    known, so the nominal rim radius is used; width scale = new width / donor vdfm width."""
    sizes = project_sizes(project)
    if not sizes or not project.cfg["chassis"].get("resize_tyre_meshes", True):
        return None
    dw = read_vdfm_wheels(vdfm)
    plan = {}
    for c in CORNERS:
        s = sizes["front" if c[0] == "F" else "rear"]
        plan[c] = {"size": s, "donor_diameter": dw[c]["diameter"], "donor_width": dw[c]["width"],
                   "width_scale": s["width"] / dw[c]["width"] if dw[c]["width"] > 0.05 else 1.0}
    return plan


def resize_mesh_files(project, mesh_files, vdfm, log=None):
    """{pak path: bytes} with every tyre mesh (all LODs, damage copies) resized to the Specs tyre size.
    Returns (new dict, report). Unchanged when no tyre size is set."""
    from .mesh import meb_read as R, meb_write as W
    plan = resize_plan(project, vdfm)
    if not plan:
        return mesh_files, None
    out = dict(mesh_files)
    report = {}
    for p, data in mesh_files.items():
        if not is_tyre_mesh(p):
            continue
        c = corner_of(p)
        fname = p.replace("\\", "/").rsplit("/", 1)[-1]
        m = R.parse(data, fname)
        if not m.has_bones and not m.ibufs:
            continue
        o0, b0, w0 = tyre_dims(m)
        e = plan[c]
        outer = e["size"]["diameter"] / 2 + (o0 - e["donor_diameter"] / 2)
        bead = e["size"]["rim_radius"] or b0 * outer / o0
        nm = resize_tyre_meb(m, outer, bead, e["width_scale"])
        out[p] = W.serialize(nm, fname)
        report[p] = {"corner": c, "outer": [round(o0, 4), round(outer, 4)], "bead": [round(b0, 4), round(bead, 4)],
                     "width_scale": round(e["width_scale"], 4)}
    if log and report:
        any_p = next(iter(report.values()))
        log(f"tyre meshes: {len(report)} resized (e.g. outer radius {any_p['outer'][0]} -> {any_p['outer'][1]} m, "
            f"bead {any_p['bead'][0]} -> {any_p['bead'][1]} m, width x{any_p['width_scale']})")
    return out, report


def donor_vdfm(project):
    from . import donor as donor_mod
    info = donor_mod.info(project)
    return donor_mod.file(project, "vehicles\\physics\\vehicles\\" + info["physics_key"] + ".vdfm").read_bytes()


def write_resized_tyres(project, out_dir, log=print):
    """Resize every donor tyre mesh (main + cockpit paks) to the Specs tyre size and write them under
    out_dir/<pak path>. Returns {pak path: file} ({} when no tyre size is set)."""
    from pathlib import Path
    from . import donor as donor_mod, paks
    if not resize_plan(project, donor_vdfm(project)):
        return {}
    info = donor_mod.info(project)
    files = {}
    for kind in ("pak", "cockpit"):
        if info.get(kind):
            with paks.PakReader(project.donor_dir / "paks" / info[kind]) as r:
                files.update({p: r.read(p) for p in r.paths if is_tyre_mesh(p)})
    new, report = resize_mesh_files(project, files, donor_vdfm(project), log)
    out = {}
    for p in report or {}:
        f = Path(out_dir).joinpath(*p.split("\\"))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(new[p])
        out[p] = f
    return out


def report(project, gamedir, road=True, top=12):
    """Text: donor tyre sizes, the Specs size and the base tyre sets ranked against it."""
    from . import donor as donor_mod
    vd = donor_vdfm(project)
    w = read_vdfm_wheels(vd)
    from . import buildphys
    cur = buildphys.vdfm_fields(vd)[buildphys.VDFM_TYRES]
    lines = [f"donor {donor_mod.info(project)['name']}: tyre set {cur!r}",
             f"  front {w['FL']['width']:.3f} m wide, diameter {w['FL']['diameter']:.4f} m (radius {w['FL']['diameter'] / 2:.4f})",
             f"  rear  {w['RL']['width']:.3f} m wide, diameter {w['RL']['diameter']:.4f} m (radius {w['RL']['diameter'] / 2:.4f})"]
    sizes = project_sizes(project)
    if not sizes:
        lines.append("no [chassis] tyre_size set: the build keeps the donor's sizes")
        sizes = {"front": {"width": w["FL"]["width"], "diameter": w["FL"]["diameter"], "text": "donor"},
                 "rear": {"width": w["RL"]["width"], "diameter": w["RL"]["diameter"], "text": "donor"}}
    else:
        for a, s in sizes.items():
            lines.append(f"Specs {a}: {s['text']} = {s['width']:.3f} m wide, diameter {s['diameter']:.4f} m "
                         f"(radius {s['diameter'] / 2:.4f}), rim radius {s['rim_radius']}")
    cat = catalog(gamedir)
    lines.append(f"base tyre sets closest to it ({'road' if road else 'race'} compounds preferred; "
                 "set widths per axle, compounds, sizes of cars using it as width/diameter):")
    for score, s, e in rank_sets(cat, sizes, road)[:top]:
        szs = "; ".join(f"{z[0]:.3f}/{z[1]:.3f} {z[2]:.3f}/{z[3]:.3f}" for z in e["sizes"][:2])
        lines.append(f"  {score:6.2f}  {s:32s} widths {e['widths']}  {','.join(e['compounds'])[:30]:30s} "
                     f"{szs}  ({', '.join(e['cars'][:3])})")
    lines.append("set it with [chassis] tyre_set = \"<name>\" (the size itself comes from tyre_size, not the set)")
    return "\n".join(lines)
