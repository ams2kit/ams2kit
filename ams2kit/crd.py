"""The new car's .crd (vehicle definition), mod folder files and driveline record."""
import re

MOD_XML = """<?xml version="1.0"?>
<Reflection>
    <class name="BRTTIRefCount" base="root class" />
    <class name="BPersistent" base="BRTTIRefCount">
        <prop name="Name" type="String" />
    </class>
    <class name="ModDetails" base="BPersistent">
        <prop name="DisplayName" type="String" />
    </class>
    <data class="ModDetails" id="0x44974535">
        <prop name="Name" data="{name}" />
        <prop name="DisplayName" data="{display}" />
    </data>
</Reflection>
"""

# Props that tie a car to DLC or to the donor's body; dropped from the clone.
DROP = {"DLC ID"} | {f"Exhaust {k} {i}" for k in ("Position", "Target Position") for i in range(1, 9)}
XLASTID = 558   # next free id after the base game's highest (see docs/02)


def _xml_attr(s):
    return str(s).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def build_crd(donor_crd_text, project, donor_info):
    c, p = project.cfg["car"], project.cfg["powertrain"]
    name, dkey = project.name, donor_info["name"]
    props = {
        "Name": name,
        "Vehicle Name": c["display_name"],
        "ShortVehicleName": c["short_name"] or c["display_name"],
        "XLASTID": str(XLASTID),
        "VehicleManufacturer": c["manufacturer"],
        "VehicleModel": c["model"] or c["display_name"],
        "Vehicle Render Model": f"{name}.vhf",
        "Vehicle Physics Model": name,
        "Vehicle Properties": name,
        "Vehicle Year": str(c["year"]),
        "Shadow Texture": f"{name}_ambsh.dds",
        "Vehicle Class": c["class"],
        "Vehicle Description": c["description"],
        "Region": c["region"],
        "Country": c["country"],
    }
    # "Cockpit properties" is read from the car's own folder; build makes a retargeted car-named copy
    # (cockpit.retarget_cockpit_bin, docs/10) and passes its name here
    props.update(donor_info.get("cockpit_props") or {})
    if c.get("engine_placement"):
        props["Engine Placement"] = c["engine_placement"]
    if p["type"] == "ev":
        props.update({"Number of Exhausts": "0", "Exhaust Smoke Amount Multiplier": "0.0"})
    head, data = donor_crd_text.split('<data class="VehicleDetails"', 1)
    out = []
    for line in data.splitlines():
        m = re.search(r'<prop name="([^"]+)" data="[^"]*"', line)
        if m and m.group(1) in DROP:
            continue
        if m and m.group(1) in props:
            line = line[:m.start()] + f'<prop name="{m.group(1)}" data="{_xml_attr(props[m.group(1)])}"' + line[m.end():]
        out.append(line)
    # The game silently rejects a crd whose header declares a prop missing from the data (docs/02).
    head = "".join(l for l in head.splitlines(keepends=True)
                   if not any(f'<prop name="{x}" type=' in l for x in DROP))
    return head + '<data class="VehicleDetails"' + "\r\n".join(out) + "\r\n"


def crd_consistency(text):
    """Props declared in VehicleDetails' class chain but missing from the data (must be empty)."""
    head, data = text.split('<data class="VehicleDetails"', 1)
    declared = set(re.findall(r'<prop name="([^"]+)" type=', head))
    present = set(re.findall(r'<prop name="([^"]+)" data=', data))
    # class headers also declare base-class props used by other records; only check VehicleDetails' own block
    m = re.search(r'<class name="VehicleDetails".*?</class>', head, re.S)
    own = set(re.findall(r'<prop name="([^"]+)" type=', m.group(0))) if m else declared
    return sorted(own - present)


def driveline(donor_record, project):
    group = project.cfg["powertrain"].get("driveline")
    if group:   # any driveline group the game defines; the donor's otherwise
        donor_record = re.sub(r"^(\s*contents\s+)\S+", lambda m: m.group(1) + group, donor_record, count=1, flags=re.M)
    rec = re.sub(r"^RECORD\s+\S+", f"RECORD {project.name.upper()}_DRIVELINE_01", donor_record, count=1, flags=re.M)
    return re.sub(r'(^\s*name\s+)"[^"]*"', rf'\1"{project.name.upper()}"', rec, count=1, flags=re.M)


def ev_driveline(donor_record, project, game_rg_text):
    """EV: a copy of the chosen (or donor's) driveline group with a centrifugal clutch (no stall,
    no clutch pedal), defined in the mod's driveline.rg (ev.ev_driveline_rg, docs/11)."""
    from . import ev
    group = project.cfg["powertrain"].get("driveline") or re.search(r"^\s*contents\s+(\S+)", donor_record, re.M).group(1)
    return ev.ev_driveline_rg(project.name, group, game_rg_text, suffix=f"{project.name.upper()}_EV")


def mod_files(project, donor_record, game_rg_text=None):
    name = project.name
    pt = project.cfg["powertrain"]
    rg = (ev_driveline(donor_record, project, game_rg_text)
          if pt["type"] == "ev" and pt.get("ev_clutch", True) and game_rg_text else driveline(donor_record, project))
    return {
        f"{name}.xml": MOD_XML.format(name=name, display=_xml_attr(project.cfg["car"]["display_name"])),
        "vehiclelist.lst": f"vehicles\\{project.key}\\{project.key}.crd\n",
        "driveline.rg": rg,
        "Readme.txt": f"{project.cfg['car']['display_name']} - built with ams2kit from the "
                      f"{project.cfg['car']['donor']} donor.\n",
    }
