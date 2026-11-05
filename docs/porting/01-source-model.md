# Source model

## Getting a model

- Any format Blender imports works: `.blend`, `.glb`/`.gltf`, `.fbx`, `.obj`. glTF from a car
  configurator or asset store is the common case (the Jetta was a `.glb`).
- What makes a model easy to port:
  - separate wheel objects (one per corner) and separate rim/tyre materials;
  - separate interior objects under their own root;
  - a material atlas or real textures (not only vertex colours);
  - lamps split into lens, housing, LED/glow materials.
- Expect 100k–1M triangles. The game's meshes hold at most 65,535 vertices each; the fit spreads big
  bodies over several slots ([Body](03-body.md)) and decimates what still doesn't fit.
- Test assets are fine for development; say so in screenshots that are shared.

## Importing read-only

Import into a **new** `.blend` with a headless script, never into the user's file:

```
blender -b --factory-startup --python import_glb.py -- <model.glb> <project>/model/<car>_src.blend <summary.json>
```

The script resets to an empty scene, runs `bpy.ops.import_scene.gltf`, saves the new file and dumps a
summary: every object (parent, bbox, triangles, materials, UV maps, skinned or not) and every material
(image textures, base colour). Read the summary before writing any config. For a `.blend` source,
open it with `--disable-autoexec` and append from it; never save over it.

## Inventory to write down

From the summary, list:

| What | Why |
|---|---|
| Exterior root (object or empty) and objects that are not exterior | `exterior_root`, `exterior_exclude` |
| The four wheel objects and the rim/tyre materials | `wheel_objects`, `rim_materials` |
| Interior root, steering wheel root | `interior.root`, `interior.steering_root` |
| Every material name | each needs a class in `material_classes` |
| Paint material(s) | `PAINT` class, `[art] render_paint` |
| Lamp materials (glow, lens, reflector, chrome) | [Lights](06-lights.md) |
| Image textures used (atlas, normal, ORM) | [Materials](04-materials.md) |

Object names in glTF imports often look like `Ext_Taillight#Glow_Red`: the part, then the material.
Config keys accept fnmatch patterns (`Ext_Door_*`), so this naming is useful.

## Orientation and scale

- ams2kit's convention: Blender Z up, the car's **front faces −Y**, metres.
- Many glTF models face +Y. The fit's `auto_orient` (default on) turns them 180°; `rotate_z_deg`
  forces an angle. The menu renderer needs `[art] render_front = "+Y"` if it renders the source file.
- Scale comes from the wheelbase: the fit places the model's wheels on the donor's `WHEEL_*` markers,
  which follow the Specs wheelbase and tracks. Fill in the real dimensions in Specs first.

## Textures: use what Blender shows

- Export the images **from the source .blend** (what Blender displays on the model) into
  `model/textures/`, rather than using texture files that came with the download.
- The Jetta's downloaded textures were stored upside down relative to its UVs. Using them gave cyan rims
  and a silver accent where red belonged. If you must use such files, set `flip_v = true` on the
  material ([Materials](04-materials.md)).
- Render the source model in Blender with its own materials (front, rear, close-ups of the grille and
  lamps) once: it is the reference for what the port should look like, next to the real-car photos.
