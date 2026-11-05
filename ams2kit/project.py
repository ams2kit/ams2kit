"""A car project: a folder with car.toml plus generated files.

<project>/
  car.toml          everything the user sets (the UI edits this)
  donor/            unpacked donor (plain paks, physics, crd, driveline record)
  model/            donor_<car>.blend (exported) and car.blend (the user's)
  art/              logo + rendered car-select images
  build/            generated physics, meshes, paks, mod files
"""
import re, tomllib
from copy import deepcopy
from pathlib import Path

DEFAULTS = {
    "car": {
        "name": "", "display_name": "", "short_name": "", "manufacturer": "", "model": "",
        "year": 2025, "class": "Street", "country": "", "region": "EU", "description": "", "donor": "",
        "engine_placement": "",    # Front / Mid / Rear / Mid-Front / Mid-Rear; "" keeps the donor's
    },
    "powertrain": {
        "type": "ev",              # "ev" or "ice"
        "power_kw": 300.0,
        "torque_nm": 500.0,        # menu value (real car)
        "rev_limit": 8000,         # simulated motor/engine limit
        "base_speed_fraction": 0.45,  # ev: share of rev limit with constant torque
        "sim_power_kw": 0.0,       # ev: simulated motor power (covers driveline losses); 0 = power_kw
        "sim_torque_nm": 0.0,      # ev: simulated motor peak torque; 0 = from power and base_speed_fraction
        "ev_clutch": True,         # ev: centrifugal clutch copy of the driveline (no stall, no clutch pedal)
        "regen_kw": 60.0,          # ev: lift-off regen power (engine-braking column)
        "regen_nm": 300.0,         # ev: lift-off regen torque cap
        "chassis_drive": "keep",   # "keep" the donor chassis' driven wheels, or "match" the driveline (experimental)
        "top_speed_kmh": 200.0,    # ev: final drive is chosen so the rev limit gives this speed
        "torque_curve": [],        # ice: [[rpm, nm], ...]
        "gears": [],               # ice: forward ratios, e.g. [3.2, 2.1, 1.5, 1.2, 1.0, 0.85]
        "final_drive": 0.0,        # ice; ev computes it
        "driveline": "",           # game driveline group (AWD_/RWD_/FWD_...); "" keeps the donor's
        "drivetrain": "AWD",       # menu label; follows the driveline's prefix when one is chosen
        "engine_layout": 18,       # menu label index (docs/05); there is no EV label
        "displacement_l": 0.0,
    },
    "chassis": {
        "mass_kg": 0.0,            # 0 = keep donor
        "cg_height_m": 0.0,
        "wheelbase_m": 0.0,
        "track_front_m": 0.0,
        "track_rear_m": 0.0,
        "rear_weight": 0.5,        # menu only
        "wheel_radius_m": 0.0,     # EV gearing radius override; 0 = the tyre's (tyre_size, else donor vdfm diameter / 2)
        "tyre_size": "",           # e.g. "245/45R19": physics size (vdfm) + resized visual tyres; "" keeps the donor's
        "tyre_size_rear": "",      # rear axle if different ("" = tyre_size)
        "tyre_set": "",            # tyre model/grip: any base set from TyresHD.xml (`ams2kit tyres`); "" = donor's
        "resize_tyre_meshes": True,  # scale the donor's skinned tyre meshes to tyre_size
        "geometry_reference": "physics",  # wheelbase/tracks are "physics" wheel centres or the real car's
                                          # "visual" values (moves both by Specs - donor vhf hubs; buildphys)
    },
    "stats": {"zero_to_100_s": 0.0},
    "physics": {
        "independent": True,       # car-named chassis/suspension/engine/gearbox files (docs/12; proven in game)
        "rename_collision": True,  # also car-named collision (needs independent; loads and drives)
    },
    "art": {
        "logo": "",
        "liveries": {},            # livery id -> "#rrggbb" (plain paint; default palette otherwise)
        "livery_names": {},        # livery id -> colour name shown in game
        "render_azimuth": 34.0,
        "render_blend": "",        # menu images from another .blend (e.g. the source model with its own materials)
        "render_paint": [],        # its paint material names (livery colour); [] = names containing paint/livery
        "render_front": "-Y",      # the way the rendered model faces: -Y (ams2kit) or +Y (many glTF imports)
    },
    "sound": {
        "kit": "",                 # car whose engine sound (csdbin + FMOD banks) the car uses; "" = the donor's
        "replace_samples": True,   # pack the WAVs in sound/replace/ into a copy of the kit's banks (sound.py)
    },
    "overrides": {},             # any physics field: "chassis.<key>[#n]" = value or [values] (see Physics page)
    "materials": {},             # NAME -> {base, base_color, roughness, metallic, normal}: car's own textures (materials.py)
    "model": {"blend": "model/car.blend", "use_model": True,
              "own_meshes": True,         # meshes under the car's own names (donor car stays intact)
              "plain_liveries": True},    # liveries = plain paint colours (no donor designs)
}

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,40}$")


def _merge(base, over):
    out = deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f'"{k}" = {_toml_value(x)}' for k, x in v.items()) + " }"
    raise TypeError(type(v))


def dumps(cfg):
    lines = []
    for section, values in cfg.items():
        lines.append(f"[{section}]")
        bare = re.compile(r"^[A-Za-z0-9_-]+$")   # anything else (e.g. "chassis.beba677b#1") is quoted
        lines += [f"{k if bare.match(str(k)) else _toml_value(str(k))} = {_toml_value(v)}" for k, v in values.items()]
        lines.append("")
    return "\n".join(lines)


class Project:
    def __init__(self, root):
        self.root = Path(root)
        self.cfg = _merge(DEFAULTS, tomllib.loads(self.toml.read_text(encoding="utf-8"))) if self.toml.exists() else deepcopy(DEFAULTS)

    toml = property(lambda s: s.root / "car.toml")
    donor_dir = property(lambda s: s.root / "donor")
    model_dir = property(lambda s: s.root / "model")
    art_dir = property(lambda s: s.root / "art")
    build_dir = property(lambda s: s.root / "build")
    name = property(lambda s: s.cfg["car"]["name"])
    key = property(lambda s: s.cfg["car"]["name"].lower())   # file-name form, e.g. byd_seal

    def save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.toml.write_text(dumps(self.cfg), encoding="utf-8")

    def update(self, changes):
        self.cfg = _merge(self.cfg, changes)

    def validate(self):
        """List of human-readable problems with car.toml (empty = fine)."""
        c, p = self.cfg["car"], self.cfg["powertrain"]
        errs = []
        if not NAME_RE.match(c["name"]):
            errs.append("Internal name must be 3-41 letters, digits or _ and start with a letter.")
        if not c["donor"]:
            errs.append("Pick a donor car.")
        if not c["display_name"]:
            errs.append("Enter a display name.")
        if p["type"] not in ("ev", "ice"):
            errs.append("Powertrain type must be 'ev' or 'ice'.")
        if p["type"] == "ice" and len(p["torque_curve"]) < 3:
            errs.append("An ICE car needs a torque curve with at least 3 points.")
        if p["type"] == "ice" and not p["gears"]:
            errs.append("An ICE car needs gear ratios.")
        if p["power_kw"] <= 0 or p["rev_limit"] <= 1000:
            errs.append("Power and rev limit must be positive.")
        return errs


def new_project(root, name, donor, **car):
    pr = Project(root)
    pr.update({"car": {"name": name, "donor": donor, "display_name": car.pop("display_name", name.replace("_", " ")),
                       **car}})
    pr.cfg["car"].setdefault("short_name", pr.cfg["car"]["display_name"])
    if not pr.cfg["car"]["short_name"]:
        pr.cfg["car"]["short_name"] = pr.cfg["car"]["display_name"]
    if not pr.cfg["car"]["model"]:
        pr.cfg["car"]["model"] = pr.cfg["car"]["display_name"]
    pr.cfg["chassis"]["geometry_reference"] = "visual"   # new projects: Specs = the real car's dimensions
    for d in (pr.donor_dir, pr.model_dir, pr.art_dir, pr.build_dir):
        d.mkdir(parents=True, exist_ok=True)
    pr.save()
    return pr
