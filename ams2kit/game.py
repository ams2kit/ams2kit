"""Locate the game and Blender; list installed cars (the donor catalog)."""
import json, os, re, shutil, winreg
from pathlib import Path

from .paks import PakReader

APP_ID = "1066890"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ams2kit"
CONFIG = DATA_DIR / "config.json"


def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _steam_root():
    for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
        try:
            with winreg.OpenKey(hive, key) as k:
                for name in ("SteamPath", "InstallPath"):
                    try:
                        return Path(winreg.QueryValueEx(k, name)[0])
                    except OSError:
                        pass
        except OSError:
            pass
    return Path(r"C:\Program Files (x86)\Steam")


def find_game():
    """The configured game folder, else the Steam library that holds app 1066890."""
    cfg = load_config()
    if cfg.get("game") and (Path(cfg["game"]) / "AMS2AVX.exe").exists():
        return Path(cfg["game"])
    root = _steam_root()
    libs = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        libs += [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(errors="ignore"))]
    for lib in libs:
        g = lib / "steamapps" / "common" / "Automobilista 2"
        if (g / "AMS2AVX.exe").exists():
            return g
    return None


def find_blender():
    """The configured blender.exe, else %AMS2KIT_BLENDER%, else the newest Program Files install, else PATH."""
    cfg = load_config()
    for exe in (cfg.get("blender"), os.environ.get("AMS2KIT_BLENDER")):
        if exe and Path(exe).exists():
            return Path(exe)
    base = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Blender Foundation"
    found = sorted(base.glob("Blender */blender.exe"), key=lambda p: [int(x) for x in re.findall(r"\d+", p.parent.name)])
    if found:
        return found[-1]
    on_path = shutil.which("blender")
    return Path(on_path) if on_path else None


def crd_props(text):
    """{prop: value} from a crd's data section."""
    data = text.split('<data class="VehicleDetails"', 1)[-1]
    return dict(re.findall(r'<prop name="([^"]+)" data="([^"]*)"', data))


_DERIVED = re.compile(r"_(lod[b-z]|dmg|blur)(_|\.|$)|_lod[b-z]_dmg")


def mesh_counts(vehicles, car):
    """How much a modder has to replace: exterior parts (main pak meshes minus lower LODs, damage
    and blur copies), all meshes, and cockpit-pak meshes."""
    parts = total = cockpit = 0
    for kind in ("pak", "cockpit"):
        if not car.get(kind):
            continue
        try:
            with PakReader(Path(vehicles) / car[kind]) as r:
                mebs = [p.lower().rsplit("\\", 1)[-1] for p in r.paths if p.lower().endswith(".meb")]
        except Exception:
            continue
        if kind == "pak":
            total = len(mebs)
            parts = sum(1 for m in mebs if not _DERIVED.search(m))
        else:
            cockpit = len(mebs)
    return {"parts": parts, "meshes": total, "cockpit_meshes": cockpit}


def list_cars(game, refresh=False):
    """Every base car with its own pak: [{name, display, manufacturer, cls, year, pak, ...}]."""
    cache = DATA_DIR / "cars.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    vehicles = Path(game) / "Pakfiles" / "Vehicles"
    paks = {p.stem.lower(): p.name for p in vehicles.glob("*.bff")}
    cars = []
    with PakReader(Path(game) / "Pakfiles" / "BOOTFLOW.bff") as boot:
        for f in boot.paths:
            low = f.lower()
            if not (low.startswith("vehicles\\") and low.endswith(".crd")):
                continue
            p = crd_props(boot.read(f).decode("utf-8", "replace"))
            name = p.get("Name", "")
            pak = paks.get(name.lower())
            if not pak or p.get("AI ONLY") == "true":
                continue
            cars.append({
                "name": name, "display": p.get("Vehicle Name", name), "manufacturer": p.get("VehicleManufacturer", ""),
                "cls": p.get("Vehicle Class", ""), "year": p.get("Vehicle Year", ""), "pak": pak,
                "physics": p.get("Vehicle Physics Model", name), "crd": f,
                "cockpit": paks.get(name.lower() + "_cockpit"), "livery": paks.get(name.lower() + "_livery"),
            })
    for c in cars:
        c.update(mesh_counts(vehicles, c))
    cars.sort(key=lambda c: (c["cls"], c["display"]))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(cars, indent=1), encoding="utf-8")
    return cars


def car_classes(cars):
    return sorted({c["cls"] for c in cars if c["cls"]})
