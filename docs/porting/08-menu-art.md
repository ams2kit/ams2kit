# Menu art

## What the game wants

- One car-select image per donor livery id (`<car>_livery_<id>.dds`, ids from the donor's livery list).
  Missing ids show white boxes.
- 2048×768, DXT5 with alpha, 12 mips: the car only, on transparency, semi-transparent windows, no shadow
  or floor. Base-game images have the car's front to the right, seen from slightly above bonnet height.
- The manufacturer logo only works as a loose file (`gui\manufacturerlogos\<maker>.dds`).

## Rendering

`python -m ams2kit render <project>` then `art <project>`. Settings in `car.toml [art]`:

```toml
[art]
liveries = { "51" = "#9e1b22", "52" = "#1d3f7a" }
livery_names = { "51" = "Kings Red Metallic", "52" = "Monterey Blue Pearl" }
render_azimuth = 34.0
render_blend = "model/jetta_src.blend"      # render the source model with its own materials
render_paint = ["Gris Franela [mciyg2wz]"]  # its paint material(s), recoloured per livery
render_front = "+Y"                         # the way that model faces
```

- **Render the source model, not `car.blend`.** The fitted file has flat-colour donor stand-ins; the
  source has real materials. The first menu images (from `car.blend` in EEVEE) looked flat and toy-like
  next to the base cars.
- The renderer (`blender/render_menu.py`) uses Cycles on the GPU, the Khronos PBR Neutral view (AgX turned
  red paint orange), a dark studio world with softboxes, a 70 mm lens at 4° elevation, and dark
  reflective window glass so the interior doesn't glow through.
- Window materials are found by name (`window`, `windscreen`, glass without lamp words). A tinted window
  named `... Tinted Light` was once taken for a lamp and came out white.
- `art/livery_<id>.png` files you supply win over renders.
- Paths given to Blender must be absolute: Blender resolves relative paths from the .blend's folder, so
  renders silently went elsewhere.

## Checking

Compare the select screen with a base car of the same class (`menu <project>` or the showroom script in
[Testing](09-testing.md) saves `<name>_select.png`). Look at size in frame, lighting, paint colour, and
window darkness.
