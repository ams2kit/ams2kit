"""What the UI and CLI can do. Each job function takes a `log` callable and returns a JSON-able result."""
import json, os, subprocess
from pathlib import Path

from . import art, build, doctor, donor, game, install, project as project_mod, testing


def _game():
    g = game.find_game()
    if not g:
        raise FileNotFoundError("Automobilista 2 not found: set the game folder in Setup")
    return g


def state(projects_root, projects):
    g = game.find_game()
    b = game.find_blender()
    return {
        "game": str(g) if g else None, "blender": str(b) if b else None,
        "steam_appid": testing.steam_appid(g) if g else False,
        "projects_root": str(projects_root), "projects": projects,
        "installed": install.installed(), "data_dir": str(game.DATA_DIR),
    }


def save_settings(body):
    cfg = game.load_config()
    for k in ("game", "blender", "projects"):
        if body.get(k):
            cfg[k] = body[k]
    game.save_config(cfg)
    if "steam_appid" in body and game.find_game():
        testing.steam_appid(game.find_game(), bool(body["steam_appid"]))
    return {"ok": True}


def donors(refresh=False):
    cars = game.list_cars(_game(), refresh=refresh)
    groups_file = game.DATA_DIR / "driveline_groups.json"
    if refresh or not groups_file.exists():
        from . import paks
        with paks.PakReader(Path(_game()) / "Pakfiles" / "PHYSICSPERSISTENT.bff") as r:
            groups_file.write_text(json.dumps(donor.driveline_groups(r.read(donor.DRIVELINE).decode("latin-1"))), encoding="utf-8")
    groups = json.loads(groups_file.read_text(encoding="utf-8"))
    return {"cars": cars, "classes": game.car_classes(cars), "drivelines": groups}


def _files(d, pattern):
    return sorted(str(p) for p in Path(d).glob(pattern)) if Path(d).exists() else []


def project_info(path):
    pr = project_mod.Project(path)
    blend = pr.root / pr.cfg["model"]["blend"]
    tests = pr.build_dir / "tests"
    info = {
        "path": str(pr.root), "cfg": pr.cfg, "errors": pr.validate(),
        "donor_unpacked": (pr.donor_dir / "donor.json").exists(),
        "donor": donor.info(pr) if (pr.donor_dir / "donor.json").exists() else None,
        "donor_blend": _files(pr.model_dir, "donor_*.blend"),
        "car_blend": str(blend) if blend.exists() else None,
        "meshes_built": (pr.build_dir / "meshes" / "pak_manifest.json").exists(),
        "built": (pr.build_dir / "build.json").exists(),
        "build": json.loads((pr.build_dir / "build.json").read_text()) if (pr.build_dir / "build.json").exists() else None,
        "previews": _files(pr.art_dir, "preview_*.png"),
        "art_sources": _files(pr.art_dir, "*.png"),
        "liveries": art.colours(pr) if (pr.donor_dir / "donor.json").exists() else {},
        "test_results": [json.loads(Path(f).read_text()) for f in _files(tests, "*.json")][-5:],
        "shots": _files(tests, "*.png")[-6:],
        "installed": any(r["name"] == pr.name for r in install.installed()),
    }
    return info


def save_project(path, cfg):
    pr = project_mod.Project(path)
    pr.cfg = project_mod._merge(project_mod.DEFAULTS, cfg)
    pr.save()
    return {"ok": True, "errors": pr.validate()}


def physics_fields(path):
    """Physics page: every donor physics field with the built value and the project's override."""
    from . import buildphys
    pr = project_mod.Project(path)
    if not (pr.donor_dir / "donor.json").exists():
        return {"rows": [], "error": "Donor not unpacked yet."}
    return {"rows": buildphys.physics_table(pr), "built": (pr.build_dir / "install").exists()}


def open_path(path, with_app=None):
    p = Path(path)
    if with_app == "blender":
        subprocess.Popen([str(game.find_blender()), str(p)])
    else:
        os.startfile(p if p.is_dir() else p.parent)
    return {"ok": True}


def _bridge():
    from .mesh import blend_bridge
    return blend_bridge


def _mesh_files(pr):
    """{pak path: bytes} of every donor .meb (main + cockpit paks)."""
    info = donor.info(pr)
    out = {}
    from . import paks
    for kind in ("pak", "cockpit"):
        if info.get(kind):
            with paks.PakReader(pr.donor_dir / "paks" / info[kind]) as r:
                out.update({p: r.read(p) for p in r.paths if p.lower().endswith(".meb")})
    # [chassis] tyre_size: the .blend (and the fit tool's rim radius, rim_fit "tyre") see the resized tyres
    from . import tyres
    out, _ = tyres.resize_mesh_files(pr, out, tyres.donor_vdfm(pr))
    return out


def job(action, body):
    """Return fn(log) for a background job."""
    path = body.get("path")

    if action == "new_project":
        def fn(log):
            root = Path(body.get("root") or "") / body["name"]
            if (root / "car.toml").exists():
                raise FileExistsError(f"a project already exists at {root}")
            pr = project_mod.new_project(root, body["name"], body["donor"], display_name=body.get("display_name", ""),
                                         manufacturer=body.get("manufacturer", ""), **{"class": body.get("cls") or "Street"})
            donor.unpack(pr, _game(), log)
            return {"path": str(pr.root)}
        return fn

    pr = project_mod.Project(path)

    def need_donor():
        if not (pr.donor_dir / "donor.json").exists():
            raise RuntimeError("donor not unpacked")

    if action == "unpack":
        return lambda log: donor.unpack(pr, _game(), log)
    if action == "export_blend":
        def fn(log):
            need_donor()
            from . import buildphys
            info = donor.info(pr)
            out = pr.model_dir / f"donor_{info['key']}.blend"
            log("exporting donor meshes to Blender (this takes a minute)...")
            res = _bridge().export_donor_blend(_mesh_files(pr), out, **_bridge_extras(pr))
            log(f"wrote {out}")
            return {"blend": str(out), "detail": res}
        return fn
    if action == "build_meshes":
        def fn(log):
            need_donor()
            blend = pr.root / pr.cfg["model"]["blend"]
            if not blend.exists():
                raise FileNotFoundError(f"save your model as {blend} first")
            log("building game meshes from", blend)
            manifest = _bridge().build_from_blend(blend, _mesh_files(pr), pr.build_dir / "meshes")
            (pr.build_dir / "meshes" / "pak_manifest.json").write_text(json.dumps(
                {p: str(Path(f).relative_to(pr.build_dir / "meshes")).replace("\\", "/") for p, f in manifest.items()}, indent=1))
            log(f"{len(manifest)} meshes")
            return {"meshes": len(manifest)}
        return fn
    if action == "render":
        return lambda log: {"dir": str(art.render(pr, log=log))}
    if action == "art":
        return lambda log: art.build(pr, _game(), log)
    if action == "build":
        return lambda log: build.build(pr, log)
    if action == "doctor":
        return lambda log: doctor.check(pr, _game())
    if action == "install":
        return lambda log: install.install(pr, _game(), log)
    if action == "uninstall":
        return lambda log: install.uninstall(pr.name, _game(), log)
    if action == "test":
        def fn(log):
            res = testing.track_run(_game(), pr.build_dir / "tests", f"run_{int(__import__('time').time())}",
                                    seconds=float(body.get("seconds", 120)), log=log,
                                    expect_car=pr.cfg["car"]["display_name"])
            (pr.build_dir / "tests" / f"{res['name']}.json").write_text(json.dumps(res, indent=1))
            return res
        return fn
    if action == "menu":
        def fn(log):
            res = testing.menu_check(_game(), pr.build_dir / "tests", f"menu_{int(__import__('time').time())}", log=log)
            return res
        return fn
    raise ValueError(f"unknown action {action}")


def _bridge_extras(pr):
    """Donor export extras: the vhf texts (main + cockpit) and the wheel centres of the NEW car's
    geometry (Specs wheelbase/track), so the .blend's WHEEL_* markers show where the wheels will be."""
    from . import buildphys, paks, physics as P
    info = donor.info(pr)
    texts = []
    for kind in ("pak", "cockpit"):
        if info.get(kind):
            with paks.PakReader(pr.donor_dir / "paks" / info[kind]) as r:
                texts += [r.read(f).decode("utf-8", "replace") for f in r.paths if f.lower().endswith(".vhf")]
    vdfm = donor.file(pr, f"vehicles\\physics\\vehicles\\{info['physics_key']}.vdfm").read_bytes()
    susp_name = buildphys.vdfm_fields(vdfm)[buildphys.VDFM_SUSPENSION]
    susp = P.Suspension(donor.file(pr, f"vehicles\\physics\\suspension\\{susp_name}.sdfbin").read_bytes())
    before = susp.wheel_centres()
    target = buildphys.geometry_targets(pr, susp)
    if target:
        susp.set_geometry(*target)
    # markers in the visual (vhf) frame: the donor's hubs moved by the geometry change, which is exactly
    # where build.vhf_move_wheels puts the wheels (some donors' physics frame is offset, e.g. Camaro SS)
    wheels = _bridge().visual_wheel_centres(texts, before, susp.wheel_centres())
    return {"vhf_text": texts, "wheel_centres": wheels, "donor_name": info["display"]}
