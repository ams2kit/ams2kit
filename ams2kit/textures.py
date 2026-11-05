"""User textures for custom materials: PBR maps (base colour, roughness, metallic) to the game's
vehicles_basic shader inputs (diffuse, specular, normal), written as uncompressed DDS with mips.

The donor shader takes a diffuse map, a specular map (RGB = specular colour/strength, A = glossiness)
and a tangent-space normal map. Metals get a darkened diffuse and a specular tinted by their colour;
non-metals keep their colour and get a grey specular that fades with roughness.
"""
import struct

import numpy as np


def dds_argb(rgba):
    """Uncompressed A8R8G8B8 DDS with a full mip chain from an (H, W, 4) uint8 array (box-filtered mips)."""
    from PIL import Image
    top = Image.fromarray(np.asarray(rgba, dtype=np.uint8), "RGBA")
    w, h = top.size
    levels, body, lw, lh = 0, b"", w, h
    while True:
        lvl = top if (lw, lh) == (w, h) else top.resize((lw, lh), Image.BOX)
        body += np.asarray(lvl)[..., [2, 1, 0, 3]].tobytes()    # BGRA in memory = A8R8G8B8
        levels += 1
        if lw == 1 and lh == 1:
            break
        lw, lh = max(1, lw // 2), max(1, lh // 2)
    hdr = bytearray(128)
    hdr[0:4] = b"DDS "
    struct.pack_into("<7I", hdr, 4, 124, 0x1 | 0x2 | 0x4 | 0x8 | 0x1000 | 0x20000, h, w, w * 4, 0, levels)
    struct.pack_into("<8I", hdr, 76, 32, 0x41, 0, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    struct.pack_into("<I", hdr, 108, 0x1000 | 0x8 | 0x400000)
    return bytes(hdr) + body


def _load(path, size=None, mode="RGB", flip_v=False):
    from PIL import Image
    im = Image.open(path).convert(mode)
    if flip_v:
        im = im.transpose(Image.FLIP_TOP_BOTTOM)
    if size and im.size != size:
        im = im.resize(size, Image.NEAREST)
    return np.asarray(im, dtype=np.float32) / 255.0


def pbr_to_legacy(base, roughness=None, metallic=None, metal_diffuse=0.25, dielectric_spec=0.35):
    """(diffuse RGBA, specular RGBA) float arrays 0..1 from base colour (H, W, 3) and optional maps."""
    h, w = base.shape[:2]
    r = np.full((h, w), 0.6, np.float32) if roughness is None else roughness
    m = np.zeros((h, w), np.float32) if metallic is None else metallic
    gloss = np.clip(1.0 - r, 0, 1)
    # coloured metals (a candy-red trim): the shader's reflections are mostly white, so their colour has to
    # live in the diffuse; grey metals (chrome) stay dark-diffuse / bright-specular
    mx, mn = base.max(-1), base.min(-1)
    sat = np.where(mx > 1e-4, (mx - mn) / np.maximum(mx, 1e-4), 0.0)
    keep = metal_diffuse + (0.85 - metal_diffuse) * sat
    diff = base * (1 - m[..., None]) + base * (keep * m)[..., None]
    spec_d = (gloss ** 2 * dielectric_spec)[..., None] * np.ones(3)
    spec_m = base * (0.35 + 0.65 * gloss[..., None]) * (1 - 0.6 * sat)[..., None]
    spec = spec_d * (1 - m[..., None]) + spec_m * m[..., None]
    one = np.ones((h, w, 1), np.float32)
    return np.concatenate([diff, one], -1), np.concatenate([spec, gloss[..., None]], -1)


def solid_textures(color, roughness=0.1, metallic=0.0, size=16):
    """{'diff'|'spec'|'norm': DDS bytes} of one colour "#rrggbb[aa]" (alpha = opacity for glass shaders)."""
    h = color.lstrip("#")
    rgba = [int(h[i:i + 2], 16) / 255.0 for i in range(0, len(h), 2)] + [1.0] * (4 - len(h) // 2)
    base = np.ones((size, size, 3), np.float32) * np.array(rgba[:3], np.float32)
    diff, spec = pbr_to_legacy(base, np.full((size, size), roughness, np.float32), np.full((size, size), metallic, np.float32))
    diff[..., 3] = rgba[3]
    norm = np.ones((size, size, 4), np.float32) * np.array([0.5, 0.5, 1.0, 1.0], np.float32)
    to8 = lambda a: np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8)
    return {"diff": dds_argb(to8(diff)), "spec": dds_argb(to8(spec)), "norm": dds_argb(to8(norm))}


def glow_texture(path=None, flip_v=False):
    """DDS bytes of an emissive (glow) map: the image, or black (no glow) without one."""
    rgb = _load(path, flip_v=flip_v) if path else np.zeros((16, 16, 3), np.float32)
    a = np.concatenate([rgb[..., :3], np.ones(rgb.shape[:2] + (1,), np.float32)], -1)
    return dds_argb(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8))


def material_textures(base_path, roughness_path=None, metallic_path=None, normal_path=None, flip_v=False):
    """{'diff'|'spec'|'norm': DDS bytes} for a custom material from PBR image files. The images must be the
    way Blender shows them on the model; flip_v turns files that come upside down (some glTF exports)."""
    base = _load(base_path, flip_v=flip_v)
    size = (base.shape[1], base.shape[0])
    rough = _load(roughness_path, size, "L", flip_v) if roughness_path else None
    metal = _load(metallic_path, size, "L", flip_v) if metallic_path else None
    diff, spec = pbr_to_legacy(base, rough, metal)
    if normal_path:
        norm = np.concatenate([_load(normal_path, size, flip_v=flip_v), np.ones((size[1], size[0], 1), np.float32)], -1)
    else:
        norm = np.ones((size[1], size[0], 4), np.float32) * np.array([0.5, 0.5, 1.0, 1.0], np.float32)
    to8 = lambda a: np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8)
    return {"diff": dds_argb(to8(diff)), "spec": dds_argb(to8(spec)), "norm": dds_argb(to8(norm))}
