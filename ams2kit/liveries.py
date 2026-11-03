"""Plain-paint liveries: every livery is the car's paint in one colour (no stripes, decals or materials).

The donor's livery list (`<car>.rcf`, XML) maps livery ids to texture/material swaps. For toolkit cars each
`<CONDITION LIVERY="id">` becomes a single swap of the body paint texture for a solid-colour texture at
the car's own path, and the livery names follow the colours.
"""
import re, struct
from collections import Counter

# default palette: (name, #rrggbb), cycled when the donor has more livery ids
PALETTE = [
    ("Arctic White", "#e8e9eb"), ("Cosmos Black", "#0c0d0f"), ("Shadow Grey", "#3b3e43"), ("Aurora Silver", "#a7abb0"),
    ("Racing Red", "#a3121a"), ("Atlantis Blue", "#5a7fb4"), ("Midnight Blue", "#16223f"), ("Graphite", "#26282c"),
    ("Sand Beige", "#cdbf9f"), ("Lime Green", "#6cc018"), ("Sunset Orange", "#d8641c"), ("Champagne", "#b7a27f"),
    ("Ocean Teal", "#1f6f73"), ("Burgundy", "#5a1420"), ("Signal Yellow", "#e8c11a"), ("Forest Green", "#22402b"),
    ("Pearl White", "#f2efe7"), ("Titanium", "#6f7378"), ("Electric Purple", "#4b2a7a"), ("Copper", "#8a4b2a"),
]


def livery_ids(rcf_text):
    return sorted({int(i) for i in re.findall(r'<NAME LIVERY="(\d+)"', rcf_text)})


def palette(ids, colors=None, names=None):
    """{id: (name, hex)}: the user's colours/names (car.toml [art] liveries / livery_names) over the default palette."""
    colors, names = colors or {}, names or {}
    out = {}
    for n, lid in enumerate(ids):
        name, hexc = PALETTE[n % len(PALETTE)]
        user = colors.get(str(lid)) or colors.get(lid)
        if user and user.lower() != hexc.lower():
            hexc, name = user, user.upper()
        out[lid] = (names.get(str(lid)) or names.get(lid) or name, hexc)
    return out


def paint_texture(rcf_text):
    """The texture the paint material samples (what liveries swap): common_paint.dds when present."""
    swaps = re.findall(r'<REPLACE TEXTURE="([^"]+)" NEWTEXTURE=', rcf_text)
    for s in swaps:
        if s.lower().endswith("common_paint.dds"):
            return s
    counted = Counter(s.lower() for s in swaps)
    return counted.most_common(1)[0][0] if counted else r"vehicles\textures\common_paint.dds"


def texture_path(car_key, lid):
    return f"vehicles\\textures\\{car_key}\\{car_key}_paint_{lid}.dds"


def plain_rcf(rcf_text, car_key, display_name, colours):
    """Rewrite livery conditions and names for plain colours. `colours` = {id: (name, hex)}."""
    paint = paint_texture(rcf_text)

    def condition(m):
        lid = int(m.group(1))
        if lid not in colours:
            return m.group(0)
        return (f'<CONDITION LIVERY="{lid}">\n\t\t<REPLACE TEXTURE="{paint}" NEWTEXTURE="{texture_path(car_key, lid)}" />\n'
                f'\t</CONDITION>')
    text = re.sub(r'<CONDITION LIVERY="(\d+)">.*?</CONDITION>', condition, rcf_text, flags=re.S)

    def name(m):
        lid = int(m.group(1))
        if lid not in colours:
            return m.group(0)
        label = f"{display_name} - {colours[lid][0]}".replace("&", "&amp;").replace('"', "&quot;")
        return f'<NAME LIVERY="{lid}" NAME="{label}" />'
    return re.sub(r'<NAME LIVERY="(\d+)" NAME="[^"]*"\s*/>', name, text)


def solid_dds(hexc, size=64):
    """Uncompressed A8R8G8B8 DDS of one colour with a full mip chain."""
    h = hexc.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    mips, s = 0, size
    body = b""
    while s >= 1:
        body += bytes((b, g, r, 255)) * (s * s)
        mips += 1
        s //= 2
    hdr = bytearray(128)
    hdr[0:4] = b"DDS "
    struct.pack_into("<7I", hdr, 4, 124, 0x1 | 0x2 | 0x4 | 0x8 | 0x1000 | 0x20000, size, size, size * 4, 0, mips)
    struct.pack_into("<8I", hdr, 76, 32, 0x41, 0, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    struct.pack_into("<I", hdr, 108, 0x1000 | 0x8 | 0x400000)   # texture | complex | mipmap
    return bytes(hdr) + body
