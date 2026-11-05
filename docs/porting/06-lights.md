# Lights

Lamps need three things to look right: the right **slot** (the donor's lights mesh), the right
**look when off** (housing, lens, chrome) and the right **glow when on** (light id + glow map).

## How the game lights a lamp

- The donor's lights material has a **glow map** (`emissiveTexture`, e.g. `vw_virtus_lights_glow.dds`).
  It is an emissive colour map: red where tail lamps are, white on headlights, sampled with the
  face's UVs.
- **Which lamp a face belongs to is a per-vertex light id**, stored in one of the extra texcoord streams
  (TEXCOORD4 on the Virtus lights mesh) as `(id, value)`, e.g. `(7, -0.7)`. On body meshes the same
  stream is an ordinary UV set, so it must not be overwritten there.
- The game switches ids on and off (headlights, tail lamps, brakes, reverse). A face glows when its id is
  on and its texel is lit in the glow map.
- Light flare billboards (`*_lightglows_*` meshes) carry the same ids at the donor's lamp positions.

## Finding the donor's ids

Read the donor's lights mesh and group vertices by id: their position (side, front/rear, height) and
the glow-map region they sample tell you which lamp each id is. VW Virtus GTS:

| Id | Where | Glow region | Lamp |
|---|---|---|---|
| 1 / 2 | front, left / right | headlight | headlights |
| 17 | front, both sides | headlight | running / position lights |
| 7 / 8 | rear, left / right, upper | red stripes | tail and brake lamps |
| 9 / 10 | rear, left / right, lower | white strip | reverse |
| 12 | centre, top of the rear window | third brake light | brake (third light) |

To check: decode the glow map (`mesh.texels.decode_dds`), read the lights mesh (`mesh.meb_read`), and
for each id print the mean vertex position and mean UV. Do this for every new donor; ids may differ
between cars.

## Config

Give lamp materials a glowing class and their ids:

```json
"material_classes": {
  "Glow Red": "LIGHT_GLOW_RED",
  "Glow DRL": "LIGHT_GLOW",
  "Reflector Red Dark": "LIGHT_RED",
  "Chrome Lines": "LIGHT",
  "Material Atlas Taillight AR": "CUSTOM:TAILAR:LIGHT",
  "Glass Red": "CUSTOM:TAILLENS:GLASS"
},
"light_ids": {
  "Glow Red": [7, 8],
  "Glow DRL": 17
}
```

- A list of ids is resolved per vertex by the nearest donor lamp, so `[7, 8]` gives left faces 7 and right
  faces 8. The fit tags the faces (`ams2_light`); the mesh writer writes the id and the donor's value
  for it.
- `LIGHT_GLOW*` classes pick a texel that is lit in the glow map; plain `LIGHT*` classes pick unlit
  texels, for reflectors and chrome that must not glow.
- Light-material faces without an id copy the nearest non-lamp donor vertex. Before this, new faces got a
  straight-line fit of the stream, i.e. fractional ids like 9.3, and the Jetta's brake LEDs never lit.
- A lamp object mixed with other classes (e.g. lens + LEDs in one object) goes to the body slot unless
  every class is a light class; the id is still written if that slot's donor mesh has it. The build warns
  `light ids [...] are not in this donor slot` otherwise.

## Lenses and textured lamp parts

- A smoked or red outer lens over the LEDs: a solid-colour custom material on a donor **window**
  material, e.g. `color = "#2c0404c0"` (dark red, 75% opaque). The real 2025 GLI has a smoked lens; a
  clear red one looked cheap.
- Textured lamp internals (the model's taillight atlas): a custom material on the donor's lights
  material, `CUSTOM:<NAME>:LIGHT`. Custom light materials get their **own black glow map** (or the
  `emissive` image you give), so they never glow by accident; only the `LIGHT_GLOW*` faces light up.
- Plate lights: `SKIP` unless the donor has a matching id.

## Checking

- Showroom: lamps off; look at housings, lenses and chrome.
- On track: headlights on (tail lamps dim), braking (tail lamps bright, third brake light), reverse.
  Screenshot from behind the car.
- Audit the built mesh: list the ids per mesh and the mean x per id (left/right correct, no fractional
  values). Known gap: a third brake light that the source model keeps in the interior is not mapped yet.
