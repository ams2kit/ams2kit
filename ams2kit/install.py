"""Install / uninstall a built car. Every file written is recorded in a receipt so uninstall is exact.

Receipts: %LOCALAPPDATA%\\ams2kit\\installs\\<Name>.json. The original PakDirInfo.dat is backed up
once to %LOCALAPPDATA%\\ams2kit\\backup\\.
"""
import json, shutil, time
from pathlib import Path

from . import game, pakdirinfo

RECEIPTS = game.DATA_DIR / "installs"
BACKUP = game.DATA_DIR / "backup"


def pak_rel(pak_name):
    return "pakfiles\\vehicles\\" + pak_name.lower()


def _registry(gamedir):
    return Path(gamedir) / "Pakfiles" / "PakDirInfo.dat"


def register(gamedir, pak_files, add=True):
    pdi = _registry(gamedir)
    BACKUP.mkdir(parents=True, exist_ok=True)
    if not (BACKUP / "PakDirInfo.dat").exists():
        shutil.copy2(pdi, BACKUP / "PakDirInfo.dat")
    ver, entries = pakdirinfo.read(pdi)
    ours = {pakdirinfo.t.path_uid(pak_rel(p.name)) for p in pak_files}
    entries = [e for e in entries if e[0] not in ours]
    if add:
        entries += [pakdirinfo.entry_for(p, pak_rel(p.name)) for p in pak_files]
    pakdirinfo.write(pdi, ver, entries)


def install(project, gamedir, log=print):
    gamedir = Path(gamedir)
    if (gamedir / "Pakfiles" / "PakDirInfo.dat").exists() is False:
        raise FileNotFoundError("not an AMS2 folder: " + str(gamedir))
    uninstall(project.name, gamedir, log=lambda *a: None)
    built = project.build_dir
    pak_files = sorted((built / "paks").glob("*.bff"))
    if not pak_files:
        raise FileNotFoundError("build the car first")
    written = []
    for p in pak_files:
        dst = gamedir / "Pakfiles" / "Vehicles" / p.name
        shutil.copy2(p, dst)
        written.append(str(dst))
    inst = built / "install"
    for src in inst.rglob("*"):
        if src.is_file():
            dst = gamedir / src.relative_to(inst)
            if dst.exists() and str(dst) not in written and not _ours(project.name, dst):
                raise FileExistsError(f"refusing to overwrite a game file: {dst}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            written.append(str(dst))
    register(gamedir, [gamedir / "Pakfiles" / "Vehicles" / p.name for p in pak_files])
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    (RECEIPTS / f"{project.name}.json").write_text(json.dumps(
        {"name": project.name, "game": str(gamedir), "time": time.ctime(), "files": written,
         "paks": [p.name for p in pak_files]}, indent=1), encoding="utf-8")
    log(f"installed {project.name}: {len(written)} files, {len(pak_files)} paks registered")
    return written


def _ours(name, path):
    r = RECEIPTS / f"{name}.json"
    return r.exists() and str(path) in json.loads(r.read_text(encoding="utf-8"))["files"]


def installed():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RECEIPTS.glob("*.json"))] if RECEIPTS.exists() else []


def uninstall(name, gamedir, log=print):
    r = RECEIPTS / f"{name}.json"
    if not r.exists():
        log(f"{name} is not installed (no receipt)")
        return
    rec = json.loads(r.read_text(encoding="utf-8"))
    for f in rec["files"]:
        p = Path(f)
        if p.exists():
            p.unlink()
            d = p.parent
            while d != Path(gamedir) and d.exists() and not any(d.iterdir()):
                d.rmdir()
                d = d.parent
    register(gamedir, [Path(gamedir) / "Pakfiles" / "Vehicles" / n for n in rec["paks"]], add=False)
    r.unlink()
    log(f"uninstalled {name}: {len(rec['files'])} files removed, paks unregistered")
