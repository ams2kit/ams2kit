"""Project -> build/paks/<Name>*.bff + build/install/ (mod folder, crd, loose files)."""
import json, os, re, shutil

from . import buildphys, cockpit, crd, donor as donor_mod, paks
from .mesh import meb_read, meb_write


def _renamed_copies(pak, donor_key, car_key, donor_folder):
    """car-named copies of files in the donor's own folder that carry the donor's name (vhf, rcf, crd, anims...)."""
    folder_prefix = donor_folder
    extra = []
    for e in pak.entries:
        low = e.path.lower()
        folder, name = low.rsplit("\\", 1)
        if not (folder == folder_prefix or folder.startswith(folder_prefix + "\\")):
            continue
        # meshes, materials and textures are found by full path from the vhf: no copies needed
        # (except the shadow texture, which the crd names after the car)
        if name.endswith((".meb", ".bmt", ".mtx")) or (name.endswith(".dds") and not name.endswith("_ambsh.dds")):
            continue
        if donor_key in name or folder.endswith("\\anims"):
            new = f"vehicles\\{car_key}" + folder[len(folder_prefix):] + "\\" + name.replace(donor_key, car_key)
            extra.append(paks.Entry(new, e.stored, e.orig_size, e.ctype, e.mtime, e.pad))
    return extra


def _cockpit_bins(project, info, donor_crd, ckey, name, log=print):
    """Retargeted cockpit properties for the crd's (IMSA) "Cockpit properties" props (docs/10).

    Returns ({crd prop: (new file name, bytes)}, [(cockpit .vhf path the car needs, donor .vhf path)]).
    AMS2KIT_NO_COCKPIT_BIN=1 skips them (car drives, but no cockpit/bonnet/helmet cameras).
    """
    if os.environ.get("AMS2KIT_NO_COCKPIT_BIN"):
        return {}, []
    dkey = info["key"]
    dfolder = info.get("folder", f"vehicles\\{dkey}")
    globals_ = {g.lower(): g for g in info.get("global_files", [])}
    bins, vhfs = {}, []
    for prop, suffix in (("Cockpit properties", ""), ("IMSA Cockpit properties", "_IMSA")):
        m = re.search(r'<prop name="%s" data="([^"]+)"' % re.escape(prop), donor_crd)
        if not m:
            continue
        g = globals_.get(f"{dfolder}\\{m.group(1).lower()}")
        if g is None:
            log(f"warning: {prop} {m.group(1)} not among the donor's global files; kept as is")
            continue
        fname = f"{name}_Cockpit{suffix}.bin"
        src = donor_mod.file(project, g).read_bytes()
        data = cockpit.retarget_cockpit_bin(src, dkey, ckey, name, resource_path=f"vehicles\\{ckey}\\{fname.lower()}")
        old_vhf = cockpit.parse(src).get_string(cockpit.F_COCKPIT_VHF)
        new_vhf = cockpit.parse(data).get_string(cockpit.F_COCKPIT_VHF)
        if old_vhf:
            vhfs.append((f"vehicles\\{ckey}\\{new_vhf.lower()}", f"{dfolder}\\{old_vhf.lower()}"))
        bins[prop] = (fname, data)
        log(f"{prop}: {fname} -> cockpit model {new_vhf}")
    return bins, vhfs


_CORNER = {"LF": "FL", "RF": "FR", "LR": "RL", "RR": "RR", "FL": "FL", "FR": "FR", "RL": "RL"}
_WHEEL_PART = re.compile(r"(WHEEL|TIRE|TYRE|DISC|CALIPER|CALLIPER|RIM|HUB|BRAKE)[A-Z0-9_]*?_(LF|RF|LR|RR|FL|FR|RL)(_|$)", re.I)


def vhf_move_wheels(text, moves):
    """Shift the render file's wheel-hub matrices by each corner's physics move (dx, dz).

    The game draws wheels at these vhf matrices, not at the physics wheel centres, so a new
    wheelbase/track must move them too. A hub matrix is one whose nodes are wheel parts of a corner."""
    if not any(dx or dz for dx, dz in moves.values()):
        return text, 0
    corner_of = {}
    for m in re.finditer(r'<NODE type="\w+" Name="([^"]+)" MatrixNumber="(\d+)"', text):
        c = _WHEEL_PART.search(m.group(1))
        if c and m.group(2) != "0":
            corner_of.setdefault(m.group(2), _CORNER[c.group(2).upper()])
    n = 0

    def shift(m):
        nonlocal n
        c = corner_of.get(m.group(1))
        if not c:
            return m.group(0)
        x, y, z = (float(v) for v in m.group(2).split())
        dx, dz = moves[c]
        n += 1
        return f'<MATRIX id="{m.group(1)}" Offset="{x + dx:.6f} {y:.6f} {z + dz:.6f}"'
    return re.sub(r'<MATRIX id="(\d+)" Offset="([^"]+)"', shift, text), n


def _quat_rotate(q, v):
    x, y, z, w = q
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + y * tz - z * ty, v[1] + w * ty + z * tx - x * tz, v[2] + w * tz + x * ty - y * tx)


def vhf_fit_spheres(text, spheres):
    """Grow the render file's culling spheres so they cover the car's meshes.

    spheres: {resource path (lower case): (cx, cy, cz, r)} in mesh space. An OBJECT node naming one of them gets
    that sphere; every group node (LOD/DAMAGE/HIERARCHY) grows to enclose its children (children in another
    matrix frame are moved by that MATRIX's offset/orientation, xyzw). Spheres only grow, never shrink.
    The game culls a node whose sphere is off screen, so a body bigger than the donor's could pop out."""
    import math
    lines = text.split("\n")
    mats = {}
    for m in re.finditer(r'<MATRIX id="(\d+)" Offset="([^"]+)" Orientation="([^"]+)"[^>]*?(?:parent="(\d+)")?\s*/>', text):
        mats[m.group(1)] = ([float(v) for v in m.group(2).split()], [float(v) for v in m.group(3).split()], m.group(4))
    root = {"children": [], "sphere": None, "line": None}
    stack = [root]
    sph_re = re.compile(r'<SPHERE Centre="([^"]+)" Radius="([^"]+)"')
    for i, line in enumerate(lines):
        st = line.strip()
        m = re.match(r'<NODE type="(\w+)"[^>]*?MatrixNumber="(\d+)"', st)
        if m and not st.endswith("/>"):
            node = {"type": m.group(1), "matrix": m.group(2), "children": [], "sphere": None, "line": None, "res": None}
            stack[-1]["children"].append(node)
            stack.append(node)
            continue
        if st.startswith("</NODE>") and len(stack) > 1:
            stack.pop()
            continue
        cur = stack[-1]
        r = re.match(r'<RESOURCE Filename="([^"]+)"', st)
        if r:
            cur["res"] = r.group(1).lower()
        sm = sph_re.search(st)
        if sm and cur["line"] is None and cur is not root:
            c = [float(v) for v in sm.group(1).split()]
            cur["sphere"], cur["line"] = [c[0], c[1], c[2], float(sm.group(2))], i

    def union(a, b):
        d = math.dist(a[:3], b[:3])
        if d + b[3] <= a[3]:
            return a
        if d + a[3] <= b[3]:
            return list(b)
        r = (d + a[3] + b[3]) / 2
        t = (r - a[3]) / d
        return [a[k] + (b[k] - a[k]) * t for k in range(3)] + [r]
    changed = 0

    def walk(node):
        """True when the node's sphere (or a descendant's) grew; groups are only refitted then."""
        nonlocal changed
        dirty = [ch for ch in node["children"] if walk(ch)]
        if node["line"] is None:
            return bool(dirty)
        cur = node["sphere"]
        new = list(cur)
        if node["type"] == "OBJECT" and node["res"] in spheres:
            new = union(new, list(spheres[node["res"]]))
        for ch in dirty:
            if ch["sphere"] is None:
                continue
            cs = ch["sphere"]
            if ch["matrix"] != node["matrix"]:
                mt = mats.get(ch["matrix"])
                if mt is None or (mt[2] or "0") != node["matrix"]:
                    continue
                c = _quat_rotate(mt[1], cs[:3])
                cs = [c[0] + mt[0][0], c[1] + mt[0][1], c[2] + mt[0][2], cs[3]]
            new = union(new, cs)
        if any(abs(a - b) > 1e-6 for a, b in zip(new, cur)):
            node["sphere"] = new
            lines[node["line"]] = sph_re.sub('<SPHERE Centre="%.6f %.6f %.6f 1.000000" Radius="%.6f"' % tuple(new),
                                             lines[node["line"]], count=1)
            changed += 1
            return True
        return bool(dirty)
    walk(root)
    return "\n".join(lines), changed


def _replace(pak, path, data):
    for e in pak.entries:
        if e.path.lower() == path.lower():
            new = paks.Entry.from_file(e.path, data, e.mtime)
            e.stored, e.orig_size, e.ctype = new.stored, new.orig_size, new.ctype
            return True
    return False


def mesh_manifest(project):
    """{pak path: file} from the Blender build (build/meshes/manifest.json), if any."""
    m = project.build_dir / "meshes" / "pak_manifest.json"   # {pak path: file}; manifest.json is the Blender build report
    if not (project.cfg["model"]["use_model"] and m.exists()):
        return {}
    files = json.loads(m.read_text(encoding="utf-8"))
    files = files.get("files", files)
    return {p: (m.parent / (v["file"] if isinstance(v, dict) else v)) for p, v in files.items()}


def art_manifest(project):
    m = project.art_dir / "manifest.json"
    if not m.exists():
        return {}
    return {p: m.parent / v["file"] for p, v in json.loads(m.read_text(encoding="utf-8")).items()}


def build(project, log=print):
    errs = project.validate()
    if errs:
        raise ValueError("; ".join(errs))
    info = donor_mod.info(project)
    dkey, ckey, name = info["key"], project.key, project.name
    out = project.build_dir
    paks_dir, inst = out / "paks", out / "install"
    shutil.rmtree(inst, ignore_errors=True)
    paks_dir.mkdir(parents=True, exist_ok=True)

    phys, names = buildphys.build(project, log)
    donor_crd = donor_mod.file(project, info["crd"]).read_text(encoding="utf-8")
    cockpit_bins, cockpit_vhfs = _cockpit_bins(project, info, donor_crd, ckey, name, log)
    crd_text = crd.build_crd(donor_crd, project, dict(info, cockpit_props={p: v[0] for p, v in cockpit_bins.items()}))
    meshes = mesh_manifest(project)
    # [chassis] tyre_size: the donor's skinned tyre meshes resized to the physics tyre (tyres.py, docs/13); they
    # go in like rebuilt meshes (car-owned names, vhf paths and culling spheres updated)
    from . import tyres as tyres_mod
    shutil.rmtree(out / "tyres", ignore_errors=True)
    for p, f in tyres_mod.write_resized_tyres(project, out / "tyres", log).items():
        meshes.setdefault(p, f)
    art = art_manifest(project)
    # [sound]: another car's sound setup and/or the kit's banks with replaced samples (sound.py, docs/16)
    from . import sound
    csd, sound_banks = (None, {})
    if project.cfg["sound"]["kit"] or sound.replacements(project):
        from . import game as game_mod
        csd, sound_banks = sound.build_files(project, game_mod.find_game(), log)
    report = {"physics": names, "meshes": len(meshes), "art": len(art), "paks": {},
              "sound": {"kit": sound.kit_name(project), "banks": sorted(sound_banks)}}

    # car-owned mesh paths: donor path -> vehicles\<car>\<car>_<file>. With them the donor car keeps its
    # own look while our paks are mounted (writing at donor paths gave the real donor our body)
    own_meshes = project.cfg["model"].get("own_meshes", True) and bool(meshes)
    mesh_paths = {p.lower(): f"vehicles\\{ckey}\\{ckey}_{p.rsplit(chr(92), 1)[-1].lower()}" for p in meshes}
    groups = [("pak", name), ("cockpit", f"{name}_Cockpit"), ("livery", f"{name}_Livery")]
    mesh_spheres = None
    for kind, new_name in groups:
        if not info.get(kind):
            continue
        pak = paks.read_plain(project.donor_dir / "paks" / info[kind])
        extra = _renamed_copies(pak, dkey, ckey, info.get("folder", f"vehicles\\{dkey}"))
        if own_meshes:
            # the car's meshes under its own names (re-keyed: the position key follows the file name);
            # the donor's mesh paths stay untouched so the donor car keeps its look
            present = {e.path.lower() for e in pak.entries}
            replaced = 0
            for p, f in meshes.items():
                if p.lower() in present:
                    new = mesh_paths[p.lower()]
                    m = meb_read.parse(f.read_bytes(), p.rsplit("\\", 1)[-1])
                    extra.append(paks.Entry.from_file(new, meb_write.serialize(m, new.rsplit("\\", 1)[-1]), pak.entries[0].mtime))
                    replaced += 1
        else:
            replaced = sum(_replace(pak, p, f.read_bytes()) for p, f in meshes.items())
        if kind == "pak":
            # default: donor-named chassis/suspension/engine/gearbox edited in place; independent mode
            # (docs/12): all car-named, so nothing at a donor path changes; vdfm/stats/crd added
            files = dict(phys)
            for p in list(files):
                if _replace(pak, p, files[p]):
                    del files[p]
            files[f"vehicles\\{ckey}\\{ckey}.crd"] = crd_text.encode("utf-8")
            # per-car files from global paks (camera/pit data, dashboard display), renamed for the car
            dfolder = info.get("folder", f"vehicles\\{dkey}")
            for g in info.get("global_files", []):
                low = g.lower()
                if low.startswith(dfolder + "\\"):
                    new = f"vehicles\\{ckey}" + low[len(dfolder):]
                    head, _, fname = new.rpartition("\\")
                    new = head + "\\" + fname.replace(dkey, ckey)
                    if re.search(r"_cockpit(_\w+)?\.bin$", new):
                        continue   # cockpit properties: retargeted copies only (_cockpit_bins, docs/10)
                else:
                    new = low.replace(dkey, ckey)
                files.setdefault(new, donor_mod.file(project, g).read_bytes())
            # cockpit properties, retargeted at the car's cockpit model (the game reads both from the
            # car's own folder; a plain donor copy crashes the game, docs/10)
            for fname, data in cockpit_bins.values():
                files[f"vehicles\\{ckey}\\{fname.lower()}"] = data
            # car-named copies of the base physics: some lookups use the car's physics model name
            # (the hand-built BYD that worked had them; without them selecting the car hit a fatal error)
            base = names.get("donor_base", names["base"]).lower()
            for e in list(pak.entries):
                low = e.path.lower()
                for sub in ("chassis", "suspension", "collision"):
                    prefix = f"vehicles\\physics\\{sub}\\{base}."
                    if low.startswith(prefix):
                        new = f"vehicles\\physics\\{sub}\\{ckey}." + low[len(prefix):]
                        files.setdefault(new, phys.get(low) or e.data())
            files.update({p: f.read_bytes() for p, f in art.items()})
            # [materials]: the car's own textures on clones of donor materials (materials.py)
            from . import materials
            files.update(materials.pak_files(project, log))
            if csd:
                files[f"vehicles\\{ckey}\\{ckey}.csdbin"] = csd   # replaces the renamed donor copy
            extra += [paks.Entry.from_file(p, d, pak.entries[0].mtime) for p, d in files.items()]
        if kind == "cockpit":
            # the cockpit model the retargeted .bin names must exist in the car's folder; renamed
            # copies cover <donor>_cockpit.vhf, other names (variants sharing a model) are copied here
            have = {e.path.lower() for e in pak.entries} | {e.path.lower() for e in extra}
            src = {e.path.lower(): e for e in pak.entries}
            for want, donor_path in cockpit_vhfs:
                for suffix in ("", ".bml"):
                    if want + suffix not in have and donor_path + suffix in src:
                        e = src[donor_path + suffix]
                        extra.append(paks.Entry(want + suffix, e.stored, e.orig_size, e.ctype, e.mtime, e.pad))
                if want not in have and donor_path not in src:
                    log(f"warning: cockpit model {donor_path} not in {info[kind]}; cockpit cameras may crash")
        # later entries win (generated files over renamed donor copies); keep one entry per path
        extra = list({e.path.lower(): e for e in extra}.values())
        if own_meshes:
            # the car's render models are edited as text; its binary copies (.vhf.bml, no writer yet)
            # would still name the donor's meshes, so they are left out
            extra = [e for e in extra if not (e.path.lower().endswith(".vhf.bml") and e.path.lower().startswith(f"vehicles\\{ckey}\\"))]
        # plain-paint liveries: the car's livery lists swap the paint texture for one colour per livery
        if project.cfg["model"].get("plain_liveries", True):
            from . import art as art_mod, liveries
            pal = art_mod.livery_palette(project)
            for e in extra:
                low = e.path.lower()
                if low.startswith(f"vehicles\\{ckey}\\") and low.endswith(".rcf"):
                    text = liveries.plain_rcf(e.data().decode("utf-8-sig", "replace"), ckey,
                                              project.cfg["car"]["display_name"], pal)
                    new = paks.Entry.from_file(e.path, text.encode("utf-8"), e.mtime)
                    e.stored, e.orig_size, e.ctype = new.stored, new.orig_size, new.ctype
            if kind == "pak":
                extra += [paks.Entry.from_file(liveries.texture_path(ckey, lid), liveries.solid_dds(hexc), pak.entries[0].mtime)
                          for lid, (_, hexc) in pal.items()]
                log(f"plain liveries: {len(pal)} colours")
        # the car's own render files: wheel hubs follow the new wheelbase/track
        for e in extra:
            if e.path.lower().endswith(".vhf"):
                text, n = vhf_move_wheels(e.data().decode("utf-8", "replace"), names["wheel_moves"])
                if own_meshes:
                    text, k = re.subn(r'(<RESOURCE Filename=")([^"]+)(")',
                                      lambda m: m.group(1) + mesh_paths.get(m.group(2).lower(), m.group(2)) + m.group(3), text)
                    n += sum(1 for m in re.finditer(r'<RESOURCE Filename="([^"]+)"', text) if m.group(1).lower().startswith(f"vehicles\\{ckey}\\"))
                    # culling spheres must cover the new meshes (a bigger body popped out at screen edges)
                    if mesh_spheres is None:
                        mesh_spheres = {mesh_paths[p.lower()]: tuple(meb_read.parse(f.read_bytes(), p.rsplit("\\", 1)[-1]).sphere)
                                        for p, f in meshes.items()}
                    text, k = vhf_fit_spheres(text, mesh_spheres)
                    if k:
                        log(f"{e.path}: grew {k} culling spheres")
                    n += k
                if n:
                    new = paks.Entry.from_file(e.path, text.encode("utf-8"), e.mtime)
                    e.stored, e.orig_size, e.ctype = new.stored, new.orig_size, new.ctype
                    log(f"{e.path}: updated {n} entries (wheel hubs, mesh paths, culling spheres)")
        pak.entries += extra
        pak.name = new_name
        if kind == "pak":
            main_entries = pak.entries
        dst = paks_dir / f"{new_name}.bff"
        size = paks.write_plain(pak, dst)
        back = paks.read_plain(dst)
        assert [e.path for e in back.entries] == [e.path for e in pak.entries]
        report["paks"][dst.name] = {"files": len(pak.entries), "added": len(extra), "meshes": replaced, "mb": round(size / 1e6, 1)}
        log(f"{dst.name}: {len(pak.entries)} files ({len(extra)} added, {replaced} meshes replaced), {size / 1e6:.1f} MB")

    # install tree: mod folder, crd, and loose files the game only reads from disk
    mod = inst / "UserData" / "Mods" / name
    mod.mkdir(parents=True)
    game_rg = None
    if project.cfg["powertrain"]["type"] == "ev" and project.cfg["powertrain"].get("ev_clutch", True):
        from . import game as game_mod
        with paks.PakReader(game_mod.find_game() / "Pakfiles" / "PHYSICSPERSISTENT.bff") as r:
            game_rg = r.read(donor_mod.DRIVELINE).decode("latin-1")
    for rel, data in sound_banks.items():   # rebuilt banks: loose under Audio\AMS2KIT\<car>\
        dst = inst.joinpath(*rel.split("/"))
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
    for fname, text in crd.mod_files(project, (project.donor_dir / "driveline.rg").read_text(encoding="latin-1"), game_rg).items():
        (mod / fname).write_text(text, encoding="utf-8")
    car_dir = inst / "Vehicles" / ckey
    car_dir.mkdir(parents=True)
    (car_dir / f"{ckey}.crd").write_bytes(crd_text.encode("utf-8"))
    # every car-named file of the main pak goes loose too (as the working hand-built install did):
    # the game reads at least the crd and, it seems, the livery list (.rcf) from Vehicles\<car>\ on disk
    loose = {e.path: e.data() for e in main_entries if ckey in e.path.lower()}
    for p, f in art.items():
        loose[p] = f.read_bytes()
    for p, d in loose.items():
        parts = p.split("\\")
        dst = inst.joinpath("Vehicles" if parts[0].lower() == "vehicles" else parts[0].upper() if parts[0].lower() == "gui" else parts[0], *parts[1:])
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(d)
    (out / "build.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report
