"""Custom materials: the car's own textures on a clone of a donor material (car.toml [materials.<NAME>]).

    [materials.ATLAS]
    base = "VW_VIRTUS_MISC"            # donor material to clone (shader + settings); its .bmt name
    base_color = "C:/.../MaterialAtlas_C.png"
    roughness = "C:/.../MaterialAtlas_ORM@channels=G.png"   # optional
    metallic = "C:/.../MaterialAtlas_ORM@channels=B.png"    # optional
    normal = ""                                              # optional tangent-space normal map
    emissive = ""         # optional glow map for light materials (lit where the game switches the lamp on);
                          # without one a light clone gets a black glow map: it never glows by itself
    flip_v = false        # images must be the way Blender shows them; true turns upside-down files

    [materials.LENS]                   # a solid colour instead of images, e.g. a smoked lens
    base = "VW_VIRTUS_WINDOWS2"        # a glass material: its alpha makes it translucent
    color = "#3a0606b0"                # RRGGBB[AA]; roughness_value / metallic_value optional

A fit config maps model materials to it with the class "CUSTOM:ATLAS": those faces keep their own UVs.

The clone is the donor's compiled .bmt with its name and texture paths swapped for strings of the same
length (the file's string table keeps every offset), saved at a car-owned path with the car's DDS files.
"""
import re
import zlib
from pathlib import Path

from . import donor as donor_mod, paks, textures

SLOTS = {"diffuseTexture": "diff", "specularTexture": "spec", "normalTexture": "norm",
         "blurredDiffuseTexture": "diff", "blurredSpecularTexture": "spec",   # wheels.fx: rim blur when spinning
         "emissiveTexture": "glow"}   # lights: the donor's glow map would light our UVs at random -> black/own


class MaterialError(ValueError):
    pass


def defined(project):
    return dict(project.cfg.get("materials") or {})


def _base_bmt(project, base):
    """(pak path, bytes) of the donor material `base` (name, e.g. VW_VIRTUS_MISC)."""
    info = donor_mod.info(project)
    want = base.lower().rsplit("\\", 1)[-1].replace(".mtx", "").replace(".bmt", "") + ".bmt"
    for kind in ("pak", "cockpit", "livery"):
        if not info.get(kind):
            continue
        r = paks.PakReader(project.donor_dir / "paks" / info[kind])
        for p in r.paths:
            if p.lower().rsplit("\\", 1)[-1] == want:
                return p, r.read(p)
    raise MaterialError(f"donor material {base!r} not found in the donor paks")


def _fit(prefix, stem, suffix, length):
    """prefix + stem (cut or padded with '0') + suffix, exactly `length` characters."""
    room = length - len(prefix) - len(suffix)
    if room < 1:
        raise MaterialError(f"no room for a {length}-character name with prefix {prefix!r}")
    return prefix + (stem[:room] if len(stem) >= room else stem + "0" * (room - len(stem))) + suffix


def _tag(project, name):
    """Short stable tag for a material of this car (keeps names unique when cut to length)."""
    return "%04X" % (zlib.crc32(f"{project.key}/{name}".encode()) & 0xFFFF)


def plan(project, name, spec=None):
    """{mtx, bmt, internal, textures {diff/spec/norm: pak path}, base_path, replace {old: new}} for one material."""
    spec = spec or defined(project)[name]
    base_path, data = _base_bmt(project, spec["base"])
    strs = [s.decode("latin-1") for s in re.findall(rb"[ -~]{3,}", data)]
    base_name = base_path.rsplit("\\", 1)[-1][:-4]
    old_name = next((s for s in strs if s.lower() == base_name.lower()), None)
    if old_name is None:
        raise MaterialError(f"{base_path}: material name {base_name!r} not found in the file")
    tag = _tag(project, name)
    internal = _fit("", f"{project.key}_{name}".upper().replace(" ", "_"), "_" + tag, len(old_name))
    replace = {old_name: internal}
    texs = {}                                         # new pak path -> diff|spec|norm
    for i, s in enumerate(strs):                      # texture path strings precede their slot name
        if s.lower().endswith(".dds") and i + 1 < len(strs) and strs[i + 1] in SLOTS:
            k = SLOTS[strs[i + 1]]
            hint = "b" if strs[i + 1].startswith("blurred") else ""
            new = _fit(f"vehicles\\textures\\{project.key}\\", f"{name.lower()}{tag.lower()}{hint}", f"_{k}.dds", len(s))
            replace[s] = new
            texs[new] = k
    if "diff" not in texs.values():              # glass.fx has no specular/normal slot: diffuse is enough
        raise MaterialError(f"{base_path}: no diffuse texture slot to replace")
    return {"mtx": f"vehicles\\{project.name}\\{internal}.mtx", "bmt": f"vehicles\\{project.key}\\{internal.lower()}.bmt",
            "internal": internal, "textures": texs, "base_path": base_path, "replace": replace, "base_bytes": data}


def clone_bmt(data, replace):
    for old, new in replace.items():
        o, n = old.encode("latin-1"), new.encode("latin-1")
        if len(o) != len(n):
            raise MaterialError(f"replacement length differs: {old!r} -> {new!r}")
        if data.count(o + b"\0") != 1:
            raise MaterialError(f"{old!r} occurs {data.count(o + b'\\0')} times in the material file")
        data = data.replace(o + b"\0", n + b"\0")
    return data


def _src(project, p):
    if not p:
        return None
    path = Path(p)
    if not path.is_absolute():
        path = project.root / path
    if not path.exists():
        raise MaterialError(f"texture file not found: {path}")
    return path


def mtx_paths(project):
    """{NAME: car-owned .mtx path} for the fit config's CUSTOM:<NAME> classes."""
    return {n: plan(project, n, s)["mtx"] for n, s in defined(project).items()}


def pak_files(project, log=print):
    """{pak path: bytes}: cloned .bmt + DDS textures for every custom material."""
    out = {}
    for name, spec in defined(project).items():
        p = plan(project, name, spec)
        if spec.get("color"):
            tex = textures.solid_textures(spec["color"], roughness=float(spec.get("roughness_value", 0.1)),
                                          metallic=float(spec.get("metallic_value", 0.0)))
        else:
            tex = textures.material_textures(_src(project, spec["base_color"]), _src(project, spec.get("roughness")),
                                             _src(project, spec.get("metallic")), _src(project, spec.get("normal")),
                                             flip_v=bool(spec.get("flip_v")))
        if "glow" in p["textures"].values():
            tex["glow"] = textures.glow_texture(_src(project, spec.get("emissive")), flip_v=bool(spec.get("flip_v")))
        out[p["bmt"]] = clone_bmt(p["base_bytes"], p["replace"])
        for path, k in p["textures"].items():
            out[path] = tex[k]
        log(f"custom material {name}: {p['mtx']} (clone of {p['base_path'].rsplit(chr(92), 1)[-1]})")
    return out
