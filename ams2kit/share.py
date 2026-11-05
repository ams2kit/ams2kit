"""Share a built car: build/share/<Name>.zip that a friend installs without ams2kit.

<Name>.zip
  README.txt           what the car is, how to install and remove it
  install.bat          runs install.ps1 (Windows PowerShell, built into Windows)
  uninstall.bat        runs install.ps1 -Uninstall
  install.ps1          copies game\\ into the game folder and registers the paks (share_install.ps1)
  registry.txt         the paks' PakDirInfo.dat entries, computed here so the installer needs no hashing
  game\\               the files Install writes, laid out like the game folder

Not inside build/install: Install copies everything there into the game.
"""
import time, zipfile
from pathlib import Path

from . import __version__, doctor, install, pakdirinfo

INSTALLER = Path(__file__).with_name("share_install.ps1")
BAT = "@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass -File \"%~dp0install.ps1\" {args}%*\r\npause\r\n"

README = """{display} for Automobilista 2
{rule}

{description}Class: {cls}. Built with ams2kit {version} on {date}, from the base-game {donor}.
Unofficial fan-made car: not affiliated with or endorsed by Reiza Studios. You need your own copy of
Automobilista 2 (Steam).

INSTALL
1. Close Automobilista 2.
2. Extract this zip into a folder (right-click > Extract All). Don't run it from inside the zip.
3. Double-click install.bat. It finds the game through Steam; if it can't, it asks for the game folder
   (the one with AMS2AVX.exe).
   If Windows SmartScreen warns about the file, choose "More info" > "Run anyway".
4. Start the game: the car is listed in the {cls} class.

After a game update, run install.bat again (updates can reset the game's list of car packages).

REMOVE
Double-click uninstall.bat. It deletes exactly the files the install wrote and takes the car out of the
game's package list.

WHAT IT CHANGES
- adds {paks} to Pakfiles\\Vehicles\\ and lists them in Pakfiles\\PakDirInfo.dat
  (backed up once to PakDirInfo.dat.ams2kit-backup);
- adds the mod folder UserData\\Mods\\{name}\\ and the car's own files ({files} files in all, see game\\);
- never overwrites a game file. If anything goes wrong, Steam > Automobilista 2 > Properties >
  Installed Files > "Verify integrity of game files" restores the game.

Don't use modified cars in online races. Back up Documents\\Automobilista 2\\ first, as with any mod.
{sound}"""


def _registry_lines(pak_files):
    out = []
    for p in pak_files:
        e = pakdirinfo.entry_for(p, install.pak_rel(p.name))
        out.append(" ".join(str(v) for v in e) + f"   {p.name}")
    return "\r\n".join(out) + "\r\n"


def share(project, gamedir=None, log=print):
    """Write build/share/<Name>.zip from the last build; refuses when Check finds a failure."""
    built = project.build_dir
    pak_files = sorted((built / "paks").glob("*.bff"))
    inst = built / "install"
    if not pak_files or not inst.exists():
        raise FileNotFoundError("build the car first")
    fails = [r["msg"] for r in doctor.check(project, gamedir) if r["level"] == doctor.FAIL]
    if fails:
        raise RuntimeError("Check reports problems; fix them before sharing:\n- " + "\n- ".join(fails))
    if project.toml.stat().st_mtime > max(p.stat().st_mtime for p in pak_files):
        log("warning: car.toml changed after the last build; the zip holds the last build")
    loose = sorted(p for p in inst.rglob("*") if p.is_file())
    c = project.cfg["car"]
    sound = ""
    if any(p.suffix.lower() == ".bank" for p in loose):
        sound = (f"\nThis car plays modified engine samples. Don't race it in the same session as the car whose sound it\n"
                 f"uses ({project.cfg['sound']['kit'] or c['donor']}): the game can load only one of the two.\n")
    readme = README.format(
        display=c["display_name"], rule="=" * (len(c["display_name"]) + 22), name=project.name,
        description=(c["description"].strip() + "\n\n") if c["description"].strip() else "",
        cls=c["class"], donor=c["donor"], version=__version__, date=time.strftime("%Y-%m-%d"),
        paks=", ".join(p.name for p in pak_files), files=len(pak_files) + len(loose), sound=sound)
    out = built / "share" / f"{project.name}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".zip.part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("README.txt", readme.replace("\n", "\r\n"))
        z.writestr("install.ps1", INSTALLER.read_text(encoding="utf-8").replace("__NAME__", project.name).replace("\n", "\r\n").replace("\r\r\n", "\r\n"))
        z.writestr("install.bat", BAT.format(args=""))
        z.writestr("uninstall.bat", BAT.format(args="-Uninstall "))
        z.writestr("registry.txt", _registry_lines(pak_files))
        for p in pak_files:
            z.write(p, f"game/Pakfiles/Vehicles/{p.name}")
        for p in loose:
            z.write(p, "game/" + p.relative_to(inst).as_posix())
    tmp.replace(out)
    log(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {len(pak_files)} paks, {len(loose)} other files)")
    return {"zip": str(out), "mb": round(out.stat().st_size / 1e6, 1)}
