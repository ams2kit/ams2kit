"""Unpack a donor car into <project>/donor/.

donor/
  paks/<Car>.bff, <Car>_Cockpit.bff, <Car>_Livery.bff   unencrypted copies (CRCs recomputed)
  files/...                                              crd, vdfm, mrdf, physics, vhf, rcf (pak paths)
  driveline.rg                                           the donor's driveline record
  donor.json                                             catalog entry + derived facts
"""
import json, re
from pathlib import Path

from . import game, paks

DRIVELINE = "vehicles\\physics\\driveline\\driveline.rg"


def _save(root, pak_path, data):
    dst = root.joinpath(*pak_path.split("\\"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    return dst


def driveline_record(text, physics_name):
    """The `RECORD ... l_driveline` block whose name is the donor's physics name (upper case):
    its header line plus the indented lines under it, nothing after."""
    lines = text.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        if not line.startswith("RECORD "):
            continue
        block = [line]
        for nxt in lines[i + 1:]:
            if not nxt.strip() or not nxt[0].isspace():
                break
            block.append(nxt.rstrip())
        if any(re.match(rf'\s*name\s+"{re.escape(physics_name.upper())}"\s*$', b) for b in block):
            return "\n".join(block) + "\n"
    raise KeyError(f"no driveline record named {physics_name.upper()}")


def driveline_groups(text):
    """Names of every driveline RECORDGROUP the game defines (what a car's record can point at)."""
    return re.findall(r"^RECORDGROUP\s+(\S+)", text, re.M)


def unpack(project, gamedir, log=print):
    car = next((c for c in game.list_cars(gamedir) if c["name"].lower() == project.cfg["car"]["donor"].lower()), None)
    if car is None:
        raise KeyError(f"donor {project.cfg['car']['donor']} not found in the game")
    d = project.donor_dir
    files = d / "files"
    vehicles = Path(gamedir) / "Pakfiles" / "Vehicles"
    for kind in ("pak", "cockpit", "livery"):
        if car.get(kind):
            log(f"decrypting {car[kind]}")
            paks.decrypt_to_plain(vehicles / car[kind], d / "paks" / car[kind])
    key = car["name"].lower()
    phys = car["physics"].lower()
    with paks.PakReader(Path(gamedir) / "Pakfiles" / "BOOTFLOW.bff") as boot:
        _save(files, car["crd"], boot.read(car["crd"]))
    with paks.PakReader(Path(gamedir) / "Pakfiles" / "PHYSICSPERSISTENT.bff") as pp:
        for f in (f"vehicles\\physics\\vehicles\\{phys}.vdfm", f"vehicles\\physics\\statistics\\{phys}.mrdf"):
            if f in pp:
                _save(files, f, pp.read(f))
        rg = pp.read(DRIVELINE).decode("latin-1")
        (d / "driveline.rg").write_text(driveline_record(rg, car["physics"]), encoding="latin-1")
        groups_file = game.DATA_DIR / "driveline_groups.json"
        game.DATA_DIR.mkdir(parents=True, exist_ok=True)
        groups_file.write_text(json.dumps(driveline_groups(rg), indent=0), encoding="utf-8")
    # per-car files kept in global paks under the donor's folder/name: camera and pit data
    # (.cdp/.cdv/.cgp/.vdp), configanim/pitcontroller/motec bins, the dashboard display. Without
    # car-named copies the new car is missing camera views.
    folder = car["crd"].rsplit("\\", 1)[0].lower()
    extra = []
    # other cars sharing the folder (vehicles\vw_virtus holds VW_Virtus and VW_Virtus_GTS): their own
    # <key>.cdp/... and <key>_cockpit.bin are not the donor's; shared files (configanim, motec, pit) are kept
    siblings = {c["name"].lower() for c in game.list_cars(gamedir)
                if c["crd"].rsplit("\\", 1)[0].lower() == folder and c["name"].lower() != key}

    def own(l):
        stem = l.rsplit("\\", 1)[-1].split(".")[0]
        return not any(stem == s or stem.startswith(s + "_cockpit") for s in siblings)
    for gp, pred in (("HRDFPERSISTENT.bff", lambda l: l.startswith(folder + "\\") and not l.endswith((".dds", ".meb")) and own(l)),
                     ("HUDDISPLAY.bff", lambda l: l.startswith(f"gui\\display_{key}"))):
        with paks.PakReader(Path(gamedir) / "Pakfiles" / gp) as r:
            for f in r.paths:
                if pred(f.lower()):
                    _save(files, f, r.read(f))
                    extra.append(f)
    with paks.PakReader(d / "paks" / car["pak"]) as main:
        for f in main.paths:
            low = f.lower()
            if low.startswith("vehicles\\physics\\") or low.endswith((".vhf", ".rcf", ".crd", ".csdbin")):
                _save(files, f, main.read(f))
    # folder: vehicles\<folder>; not always the car name (VW_Virtus_GTS)
    info = dict(car, key=key, physics_key=phys, folder=folder, global_files=extra)
    (d / "donor.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    log(f"donor {car['display']} unpacked to {d}")
    return info


def tyre_radius(project):
    """Rolling radius from the donor's rear tyre mesh (half its height). The suspension's wheel-centre
    height is not a usable radius on every car (some measure from another reference)."""
    import re
    from .mesh import meb_read
    i = info(project)
    with paks.PakReader(project.donor_dir / "paks" / i["pak"]) as r:
        tyres = [p for p in r.paths if re.search(r"(tire|tyre)_(lr|rr)_loda\.meb$", p.lower())]
        if not tyres:
            return None
        m = meb_read.parse(r.read(tyres[0]), tyres[0].rsplit("\\", 1)[-1])
    lo, hi = m.aabb[:3], m.aabb[3:]
    return round((hi[1] - lo[1]) / 2, 4)


def info(project):
    return json.loads((project.donor_dir / "donor.json").read_text(encoding="utf-8"))


def file(project, pak_path):
    return project.donor_dir.joinpath("files", *pak_path.split("\\"))
