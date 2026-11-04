"""Locate the game and Blender; list installed cars (the donor catalog)."""
import json, os, re, shutil, sys
from pathlib import Path

from .paks import PakReader

APP_ID = "1066890"
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"


def _data_dir():
    """Per-user settings and caches: %LOCALAPPDATA%\\ams2kit on Windows, ~/Library/Application Support/ams2kit
    on macOS, $XDG_DATA_HOME/ams2kit (~/.local/share) elsewhere."""
    if WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or Path.home()
    elif MACOS:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "ams2kit"


DATA_DIR = _data_dir()
CONFIG = DATA_DIR / "config.json"


def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _steam_roots():
    """Candidate Steam folders, most likely first. Windows reads the registry; Linux covers the native,
    Debian-style and Flatpak installs (the game runs there through Proton)."""
    if WINDOWS:
        import winreg
        roots = []
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for name in ("SteamPath", "InstallPath"):
                        try:
                            roots.append(Path(winreg.QueryValueEx(k, name)[0]))
                        except OSError:
                            pass
            except OSError:
                pass
        return roots + [Path(r"C:\Program Files (x86)\Steam")]
    home = Path.home()
    if MACOS:
        return [home / "Library" / "Application Support" / "Steam"]
    return [home / ".steam" / "steam", home / ".local" / "share" / "Steam", home / ".steam" / "debian-installation",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"]


def find_game():
    """The configured game folder, else the Steam library that holds app 1066890."""
    cfg = load_config()
    if cfg.get("game") and (Path(cfg["game"]) / "AMS2AVX.exe").exists():
        return Path(cfg["game"])
    libs = []
    for root in _steam_roots():
        libs.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():   # VDF escapes backslashes in Windows paths
            libs += [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(errors="ignore"))]
    for lib in libs:
        g = lib / "steamapps" / "common" / "Automobilista 2"
        if (g / "AMS2AVX.exe").exists():
            return g
    return None


def _installed_blenders():
    """Blender installs in the platform's usual place, oldest first."""
    if WINDOWS:
        base = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Blender Foundation"
        found = list(base.glob("Blender */blender.exe"))
        version = lambda p: p.parent.name
    elif MACOS:
        found = [p for a in (Path("/Applications"), Path.home() / "Applications")
                 for p in a.glob("Blender*.app/Contents/MacOS/Blender")]
        version = lambda p: p.parents[2].name
    else:
        return []   # Linux installs are on PATH (distro package, snap) or set by hand
    return sorted(found, key=lambda p: [int(x) for x in re.findall(r"\d+", version(p))])


def find_blender():
    """The configured Blender, else %AMS2KIT_BLENDER%, else the newest standard install, else PATH."""
    cfg = load_config()
    for exe in (cfg.get("blender"), os.environ.get("AMS2KIT_BLENDER")):
        if exe and Path(exe).exists():
            return Path(exe)
    found = _installed_blenders()
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
