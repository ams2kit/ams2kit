"""Checks that catch the game's silent failures before launching (docs/08)."""
import struct, zlib
from pathlib import Path

from . import buildphys, crd, donor as donor_mod, game, install, pak_tool, pakdirinfo

OK, WARN, FAIL = "ok", "warn", "fail"


def _pak_crcs(path):
    """Number of TOC entries whose stored CRC doesn't match ~crc32(stored bytes)."""
    b = Path(path).read_bytes()
    count = struct.unpack_from("<I", b, 8)[0]
    bad = 0
    for i in range(count):
        _, pos, size, _, _, _, _, crc = struct.unpack_from("<QQIIQBBI", b, 0x130 + i * 0x2A)
        if crc != (~zlib.crc32(b[pos:pos + size]) & 0xFFFFFFFF):
            bad += 1
    return count, bad, b[0x12D]


def _check_tyres(project, gamedir, vb, tyre_set, donor_set, add):
    """Tyre set must be a base-game set (boot list); sizes in the vdfm wheel block (docs/13)."""
    from . import tyres
    try:
        sets = {s.lower() for s in tyres.boot_tyre_sets(gamedir)}
    except Exception as e:   # no game install to compare with
        sets = None
        add(WARN, f"could not read the base tyre-set list ({e}); tyres field is {tyre_set!r}")
    if sets is not None:
        if tyre_set.lower() not in sets:
            add(FAIL, f"vdfm tyres field {tyre_set!r} is not a base-game tyre set (TyresHD.xml): the game would get a "
                      "null tyre set and crash on track (docs/12). Use the donor's or one from `ams2kit tyres`.")
        else:
            add(OK, f"tyre set {tyre_set!r} is a base-game set" + ("" if tyre_set == donor_set else f" (donor: {donor_set!r})"))
    w = tyres.read_vdfm_wheels(vb)
    bad = [c for c, e in w.items() if not (0.08 < e["width"] < 0.6 and 0.25 < e["diameter"] < 1.6)]
    if bad:
        add(FAIL, f"vdfm tyre sizes out of range at {bad}: {w}")
    sizes = tyres.project_sizes(project)
    if sizes:
        for c, e in w.items():
            s = sizes["front" if c[0] == "F" else "rear"]
            if abs(e["diameter"] - s["diameter"]) > 1e-3 or abs(e["width"] - s["width"]) > 1e-3:
                add(FAIL, f"vdfm tyre {c} is {e['width']:.3f}/{e['diameter']:.4f} m, Specs say {s['text']}: rebuild")
                break
        else:
            add(OK, "vdfm tyre sizes: " + ", ".join(f"{a} {s['text']} (radius {s['diameter'] / 2:.4f} m)" for a, s in sizes.items()))
        try:
            ent = tyres.catalog(gamedir).get(next((k for k in tyres.catalog(gamedir) if k.lower() == tyre_set.lower()), ""), {})
            ws = ent.get("widths") or []
            if ws and (abs(ws[0] - sizes["front"]["width"]) > 0.03 or abs(ws[-1] - sizes["rear"]["width"]) > 0.03):
                add(WARN, f"tyre set {tyre_set!r} is tuned for widths {ws} m, Specs {sizes['front']['width']}/"
                          f"{sizes['rear']['width']} m: consider a closer set ([chassis] tyre_set, `ams2kit tyres`)")
        except Exception:
            pass
    else:
        add(OK, f"tyre sizes kept from the donor: front {w['FL']['width']:.3f}/{w['FL']['diameter']:.3f} m, "
                f"rear {w['RL']['width']:.3f}/{w['RL']['diameter']:.3f} m (width/diameter)")


def _check_sound(project, gamedir, add):
    """The built csdbin must name banks that exist in the game or in our install tree (docs/16)."""
    from . import sound
    csd_file = project.build_dir / "install" / "Vehicles" / project.key / f"{project.key}.csdbin"
    if not csd_file.exists():
        return
    try:
        banks = sound.csd_banks(csd_file.read_bytes())
    except ValueError as e:
        add(FAIL, f"csdbin unreadable: {e}")
        return
    inst = project.build_dir / "install"
    # only the engine banks: base cars also name shared banks that aren't in the game (Audio/Surface/WindBuffeting)
    missing = [b for b in banks if b.startswith(sound.ENGINE_BANKS + (sound.MOD_BANKS,))
               and not (sound.bank_file(gamedir, b).exists() or sound.bank_file(inst, b).exists())]
    if missing:
        add(FAIL, f"csdbin names FMOD banks that don't exist (no engine sound): {missing}")
    else:
        add(OK, f"sound: {sound.kit_name(project)}'s ({len(banks)} banks found)")
    ours = [b for b in banks if b.startswith(sound.MOD_BANKS)]
    if ours:
        info = sound.kit_info(project) or {"banks": {}}
        same = sorted({c for b in ours for c in sound.cars_using(gamedir, info["banks"].get(b.rsplit("/", 1)[-1], {}).get("path", ""))})
        add(WARN, f"replaced samples: the rebuilt banks keep the FMOD ids of the originals, so don't race this car in the "
                  f"same session as {', '.join(same) or sound.kit_name(project)} (the game loads only one of the two; "
                  "docs/16)")


def check(project, gamedir=None):
    gamedir = Path(gamedir or game.find_game())
    res = []
    add = lambda level, msg: res.append({"level": level, "msg": msg})
    errs = project.validate()
    for e in errs:
        add(FAIL, e)
    if not (project.donor_dir / "donor.json").exists():
        add(FAIL, "Donor not unpacked yet.")
        return res
    paks = sorted((project.build_dir / "paks").glob("*.bff"))
    if not paks:
        add(WARN, "Not built yet.")
    for p in paks:
        n, bad, enc = _pak_crcs(p)
        add(FAIL if bad or enc else OK, f"{p.name}: {n} files, {bad} bad CRCs, encryption flag {enc}")
    crd_file = project.build_dir / "install" / "Vehicles" / project.key / f"{project.key}.crd"
    if crd_file.exists():
        missing = crd.crd_consistency(crd_file.read_text(encoding="utf-8"))
        add(FAIL if missing else OK, "crd header/data consistent" if not missing else
            f"crd declares props missing from its data (car would be silently dropped): {missing}")
    # physics names
    phys_dir = project.build_dir / "install" / "Vehicles" / "physics" / "vehicles"
    vdfm = phys_dir / f"{project.key}.vdfm"
    if vdfm.exists():
        vb = vdfm.read_bytes()
        ok = buildphys.P.serial_layout_ok(vb)
        add(OK if ok else FAIL, "vdfm passes the game's layout check" if ok else
            "vdfm section sizes/pads don't add up: the game rejects it and crashes on track (null tyre set, docs/12)")
        f = buildphys.vdfm_fields(vb)
        pk = donor_mod.info(project)["physics_key"]
        donor_f = buildphys.vdfm_fields(donor_mod.file(project, f"vehicles\\physics\\vehicles\\{pk}.vdfm").read_bytes())
        _check_tyres(project, gamedir, vb, f[0x88], donor_f[0x88], add)
        renamed = {hex(k): f[k] for k in (0x38, 0x48, 0x70, 0x78, 0x80) if f[k] != donor_f[k]}
        add(OK, f"vdfm car-named fields: {renamed}" if renamed else "vdfm keeps the donor's part names "
            "(our edited files override the donor car's while the pak is mounted)")
    # driveline vs donor chassis drive layout
    try:
        from . import ev, shcb
        pk2 = donor_mod.info(project)["physics_key"]
        base = buildphys.vdfm_fields(donor_mod.file(project, f"vehicles\\physics\\vehicles\\{pk2}.vdfm").read_bytes())[0x38]
        toks = ev.strings_of(shcb.parse(donor_mod.file(project, f"vehicles\\physics\\chassis\\{base}.cdfbin").read_bytes()))
        chassis_drive = next((t for t in toks if t in ("REAR", "FOUR", "FRONT")), None)
        want = buildphys.DRIVE_WHEELS[buildphys.driveline_layout(project)].decode()
        if chassis_drive and chassis_drive != want:
            add(WARN, f"driveline is {buildphys.driveline_layout(project)} but the donor chassis drives {chassis_drive} wheels: "
                      "the car will effectively keep the donor's layout. Pick a donor with the layout you want.")
    except Exception:
        pass
    _check_sound(project, gamedir, add)
    # images / logo
    art = project.art_dir / "manifest.json"
    add(OK if art.exists() else WARN, "menu art present" if art.exists() else "No car-select images or logo yet (menu shows the donor's / a white box).")
    # installation state
    pdi = gamedir / "Pakfiles" / "PakDirInfo.dat"
    if pdi.exists() and paks:
        _, entries = pakdirinfo.read(pdi)
        uids = {e[0] for e in entries}
        missing = [p.name for p in paks if pak_tool.path_uid(install.pak_rel(p.name)) not in uids]
        inst = (gamedir / "Pakfiles" / "Vehicles" / paks[0].name).exists()
        if inst:
            add(FAIL if missing else OK, "paks registered in PakDirInfo.dat" if not missing else
                f"installed but not registered (game ignores them): {missing}. Re-run Install (a game update may have reset the registry).")
            stale = [p.name for p in paks if (gamedir / "Pakfiles" / "Vehicles" / p.name).stat().st_size != p.stat().st_size]
            if stale:
                add(WARN, f"installed paks differ from the latest build: {stale}. Install again.")
        else:
            add(WARN, "Not installed.")
    return res
