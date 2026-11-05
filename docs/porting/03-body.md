# Body

## Material classes

Every model material gets a class in `material_classes`:

| Class | Goes to | Used for |
|---|---|---|
| `PAINT` | the donor's paint material (livery colour) | body paint |
| `GLASS` | the donor's window material | windows, clear lenses |
| `PLASTIC` / `GLOSS` | the donor's trim materials | black trim, chrome-ish trim (flat colour) |
| `LIGHT`, `LIGHT_RED`, `LIGHT_AMBER` | the donor's lights material, flat colour | reflectors, lamp chrome |
| `LIGHT_GLOW`, `LIGHT_GLOW_RED`, `LIGHT_GLOW_AMBER` | the lights material, glowing texel | LEDs, lamp elements ([Lights](06-lights.md)) |
| `CUSTOM:<NAME>[:<CLASS>]` | the car's own material (keeps the model's UVs) | atlases, badges, grilles ([Materials](04-materials.md)) |
| `SKIP` | dropped | plate lights, decals you don't want |

Non-custom classes paint new faces with **one texel** of the donor texture (a flat colour). Anything with
detail (grilles, badges, textured plastics) needs a custom material.

## Window glass

- Windows must be `GLASS`. A glass texel picked naively can be any colour of a shared glass atlas: the
  Jetta's windows came out red until texels were chosen by reading the texture (`mesh/texels.py`).
- Tinted rear windows, sunroof glass and lamp lenses can share the class; lamp lenses usually want their
  own custom material ([Lights](06-lights.md)).

## Spreading the body over slots: `part_slots`

- One game mesh holds at most 65,535 vertices. A 140k-triangle body poured into `body_loda` alone was
  decimated to 61% and the paint looked lumpy.
- `part_slots` maps model object patterns to donor body objects, first match wins:

```json
"part_slots": {
  "Ext_Trunk_Lid_Light#Glass*": "vw_virtus_gts_body_loda",
  "Ext_Body#Material_Atlas": "vw_virtus_gts_bumper_f_loda",
  "Ext_Body_Grille*": "vw_virtus_gts_bumper_f_loda",
  "Ext_Door_*": "vw_virtus_gts_bumper_r_loda",
  "Ext_Trunk_Lid*": "vw_virtus_gts_bumper_r_loda",
  "Ext_Body_Exhaust*": "vw_virtus_gts_underface_loda"
}
```

- **A slot keeps its donor vertex streams.** Parts need a slot whose donor faces use the same material
  kind. Paint sent to the underface slot (which has no livery texcoords) rendered solid black. The fit
  warns when a target doesn't use a material its parts need, and the build lists every material that
  isn't the slot's own.
- If the game detaches bumpers on heavy damage, the parts in those slots go with them.
- `split_sides: ["pattern"]` splits matching objects into `<name>@L` / `<name>@R` (left = +X) before
  `part_slots`, for per-side slots.

## LODs, damage, culling

- Lower LODs, damage copies and the `*_cpit` (seen-from-seat) copies are derived automatically from LOD A
  with the donor's triangle ratios. Edit one in the .blend and your version wins.
- Far LODs: a LOD level only one part has (e.g. `body_lodd`) gets the union of the whole exterior,
  decimated. It is coarse with many small objects.
- Meshes larger than the donor's would be culled at screen edges. The build grows the culling spheres in
  the car's render file; the manifest's `sphere_excess_m` warnings are informational.
- `exterior_exclude` drops parts entirely (door limiters, sunroof glass you don't want).

## Hidden donor parts

The fit hides every donor body part it doesn't fill, plus the donor's glass, flares and wiper objects
and cockpit-only exterior parts. Check the showroom from all sides: a donor part left visible shows up as
a ghost shape (`extra_hide` hides more, `keep` keeps one).
