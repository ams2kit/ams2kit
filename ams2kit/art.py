"""Menu art: car-select images (one per livery) and the manufacturer logo, as game-ready DDS (docs/05).

Images come from <project>/art/livery_<id>.png if the user supplies them, else from a Blender render of
the project's car .blend. DDS headers are copied from base-game files of the same kind.
"""
import json, re, subprocess, tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from . import donor as donor_mod, game, paks

HERE = Path(__file__).parent
CAR_W, CAR_H, CAR_MIPS = 2048, 768, 12
LOGO_W, LOGO_H, LOGO_MIPS = 200, 100, 8


def livery_ids(project):
    info = donor_mod.info(project)
    folder = info.get("folder", f"vehicles\\{info['key']}")
    rcf = donor_mod.file(project, f"{folder}\\{info['key']}.rcf")
    ids = re.findall(rb'LIVERY="(\d+)"', rcf.read_bytes()) if rcf.exists() else []
    return sorted({int(i) for i in ids}) or [51]


def hex_to_linear(h):
    h = h.lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb)




def livery_palette(project):
    """{id: (name, hex)} for every donor livery id (plain paint, see liveries.py)."""
    from . import liveries
    a = project.cfg["art"]
    return liveries.palette(livery_ids(project), a.get("liveries"), a.get("livery_names"))


def colours(project):
    return {i: hexc for i, (_, hexc) in livery_palette(project).items()}


def render(project, blend=None, log=print):
    """Menu images from the model. [art] render_blend: render another .blend (e.g. the source model with its own
    materials) instead of model.blend; render_paint: its paint material names; render_front: "+Y" if it faces +Y."""
    a = project.cfg["art"]
    blend = Path(blend or project.root / (a.get("render_blend") or project.cfg["model"]["blend"])).resolve()
    if not blend.exists():
        raise FileNotFoundError(f"model not found: {blend}")
    out = (project.art_dir / "render").resolve()   # absolute: Blender resolves relative paths from the .blend's folder
    out.mkdir(parents=True, exist_ok=True)
    cols = [f"l{i}={','.join(f'{c:.4f}' for c in hex_to_linear(h))}" for i, h in colours(project).items()]
    extra = [f"--front={a.get('render_front') or '-Y'}"]
    if a.get("render_paint"):
        extra.append("--paint=" + "|".join(a["render_paint"]))
    cmd = [str(game.find_blender()), "-b", str(blend), "--python", str(HERE / "blender" / "render_menu.py"), "--",
           str(out), "2400", "900", str(a["render_azimuth"]), *cols, *extra]
    log("rendering menu images in Blender...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or "WROTE" not in r.stdout:
        raise RuntimeError("Blender render failed:\n" + (r.stdout + r.stderr)[-3000:])
    return out


def _mips(img, n):
    out, (w, h) = [img], img.size
    while len(out) < n:
        w, h = max(1, w // 2), max(1, h // 2)
        out.append(img.resize((w, h), Image.LANCZOS))
    return out


def _clean(img):
    a = np.array(img.convert("RGBA"))
    a[a[..., 3] == 0, :3] = 0
    return Image.fromarray(a)


def _dxt5(img):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.dds"
        img.save(p, pixel_format="DXT5")
        return p.read_bytes()[128:]


def _headers(gamedir):
    """128-byte DDS headers of a base car image (DXT5, 12 mips) and a base logo (BGRA, 8 mips)."""
    cache = game.DATA_DIR / "dds_headers.bin"
    if cache.exists():
        b = cache.read_bytes()
        return b[:128], b[128:]
    pak = Path(gamedir) / "Pakfiles"
    with paks.PakReader(pak / "GUIVEHICLEIMAGES.bff") as r:
        car = r.read(next(p for p in r.paths if p.lower().endswith("_livery_51.dds")))[:128]
    with paks.PakReader(pak / "GUIMANUFACTURERLOGOS.bff") as r:
        logo = r.read(next(p for p in r.paths if p.lower().endswith("lamborghini.dds")))[:128]
    game.DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(car + logo)
    return car, logo


def car_image(src):
    """Crop to the car and place it in the 2048x768 frame like the base images (car bottom at y~670)."""
    im = Image.open(src).convert("RGBA")
    ys, xs = np.where(np.array(im)[..., 3] > 8)
    im = im.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    s = min(1645 / im.width, 545 / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    canvas = Image.new("RGBA", (CAR_W, CAR_H), (0, 0, 0, 0))
    canvas.alpha_composite(im, (950 - im.width // 2, 670 - im.height))
    return _clean(canvas)


def logo_image(src, colour=None):
    im = Image.open(src).convert("RGBA")
    ys, xs = np.where(np.array(im)[..., 3] > 0)
    im = im.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    s = min(180 / im.width, 60 / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    if colour:  # solid fill using the logo's alpha (white reads well on the dark menu)
        a = np.array(im)
        a[..., :3] = colour
        im = Image.fromarray(a)
    canvas = Image.new("RGBA", (LOGO_W, LOGO_H), (0, 0, 0, 0))
    canvas.alpha_composite(im, ((LOGO_W - im.width) // 2, (LOGO_H - im.height) // 2))
    return _clean(canvas)


def logo_path(manufacturer):
    return f"gui\\manufacturerlogos\\{manufacturer.lower().replace(' ', '')}.dds"


def build(project, gamedir, log=print, logo_white=True):
    car_hdr, logo_hdr = _headers(gamedir)
    art = project.art_dir
    manifest = {}
    renders = art / "render"
    ids = list(colours(project))
    sources = {}
    for lid in ids:
        for cand in (art / f"livery_{lid}.png", renders / f"l{lid}.png"):
            if cand.exists():
                sources[lid] = cand
                break
    have = [sources[i] for i in ids if i in sources]
    if have and len(have) < len(ids):
        log(f"warning: images for {len(have)} of {len(ids)} liveries; reusing them for the rest (render again for all)")
    for n, lid in enumerate(ids):
        src = sources.get(lid) or (have[n % len(have)] if have else None)
        if src is None:
            continue
        img = car_image(src)
        rel = f"gui\\vehicleimages\\vehicleimages_{project.key}\\{project.key}_livery_{lid}.dds"
        body = b"".join(_dxt5(m) for m in _mips(img, CAR_MIPS))
        dst = art / "dds" / rel.replace("\\", "/")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(car_hdr + body)
        img.save(art / f"preview_{lid}.png")
        manifest[rel] = {"file": str(dst.relative_to(art)).replace("\\", "/")}
    logo = project.cfg["art"]["logo"]
    if logo:
        src = Path(logo) if Path(logo).is_absolute() else project.root / logo
        img = logo_image(src, (255, 255, 255) if logo_white else None)
        rel = logo_path(project.cfg["car"]["manufacturer"])
        body = b"".join(np.array(m.convert("RGBA"))[..., [2, 1, 0, 3]].tobytes() for m in _mips(img, LOGO_MIPS))
        dst = art / "dds" / rel.replace("\\", "/")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(logo_hdr + body)
        img.save(art / "preview_logo.png")
        manifest[rel] = {"file": str(dst.relative_to(art)).replace("\\", "/")}
    (art / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    log(f"menu art: {len(manifest)} files")
    return manifest
