# Materials

## Flat-colour texels

Faces with a non-custom class get a single texel of a donor texture written into their UVs. ams2kit
picks it by decoding the texture (`mesh/texels.py`): each class has a scoring rule (GLASS neutral and
translucent, LIGHT bright, LIGHT_RED saturated red, RIM mid grey, PLASTIC dark...). For materials with a
glow map, the `LIGHT_GLOW*` rules also require the texel to be lit in the glow map.

- The picks are in `model/texels.json` and in `fit_log.json → texels` with their colour. Read them when a
  part comes out the wrong colour.
- Classes sharing one donor material can still differ (red tail lamps and white headlights both use the
  lights material) because the texel is per face.

## The car's own textures: custom materials

For anything with detail, clone a donor material and give it the car's textures (`car.toml`):

```toml
[materials.ATLAS]
base = "VW_VIRTUS_MISC"                       # donor material to clone (its shader and settings)
base_color = "model/textures/atlas_basecolor.png"
roughness = "model/textures/atlas_roughness.png"
metallic = "model/textures/atlas_metallic.png"

[materials.TAILLENS]                          # a solid colour instead of images
base = "VW_VIRTUS_WINDOWS2"                   # a glass material: alpha makes it translucent
color = "#2c0404c0"
roughness_value = 0.05
```

Then map model materials to it in the fit config: `"Material Atlas": "CUSTOM:ATLAS"`. Those faces keep
the model's own UVs. `CUSTOM:<NAME>:<CLASS>` also chooses the slot kind, e.g. `CUSTOM:TAILAR:LIGHT` keeps
a textured lamp part in the donor's lights mesh.

- **Choose the base by shader and slot.** Body trim: the donor's misc/trim material. Rims: the donor's
  rim material (`rim_custom_material`). Lamp parts: the donor's lights material. Lenses: a window
  material. The clone keeps the base's vertex layout expectations.
- Keys: `base`, `base_color`, `roughness`, `metallic`, `normal`, `emissive` (light materials),
  `flip_v`, or `color` (+ `roughness_value`, `metallic_value`) for a solid colour.
- How it works: the donor's compiled material file is copied with its name and texture paths replaced
  by strings of the same length, saved under the car's folder with the car's DDS files.

## PBR to the game's shader

`textures.py` converts PBR maps to the legacy inputs: diffuse, specular (RGB strength, A gloss) and a
normal map, as uncompressed DDS with mips.

- Metals keep their colour in the diffuse. A first version made coloured metals grey, so a red metal
  accent rendered silver; the conversion is now saturation-aware.
- Glass materials read the diffuse alpha as opacity.

## Atlases

Many configurator models use one atlas (a grid of swatches: chrome, gloss black, red accent, badge
artwork) shared by most trim. One custom material on that atlas fixes grille, badges, mirror caps,
window trim and exhaust tips at once. That was the single biggest visual improvement on the Jetta.

Check the atlas orientation (see [Source model](01-source-model.md)): if colours land on the wrong
parts, the images are flipped.
