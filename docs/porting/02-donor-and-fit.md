# Donor & fit

## Choosing a donor

The new car is a clone of an installed car: it keeps the donor's shaders, vertex layouts, cockpit
setup, sounds and (unless replaced) physics. Pick the closest match:

- **Body style and size**: a sedan for a sedan. The donor's body slots, glass and lights meshes are what
  your parts are poured into; similar shapes give similar slot boundaries.
- **Drivetrain** (FWD/RWD/AWD) and **class** (road car, GT3...): physics and driveline come from it.
- **Materials**: a donor with a misc/trim material, a lights material with a glow map, and a rim
  material makes the material work much easier ([Materials](04-materials.md)).
- `python -m ams2kit donors <filter>` lists candidates. The Jetta used the VW Virtus GTS (a sedan from the
  same family); the BYD Seal used the Lamborghini Veneno (only for its AWD layout; the body fit was harder).

## The donor .blend

`python -m ams2kit export-blend <project>` writes `model/donor_<donor>.blend`: one object per game mesh,
named after the file, in collections (`REPLACE_Body`, `Lights`, `Glass`, `Wheels/Wheel_FL..RR`,
`Interior`, hidden `Cockpit`, `Flares`, `LODs`, `CockpitView`, `Damage`), with `WHEEL_*` markers at the
wheel centres. Open it once and note:

- which body objects exist (`body_loda`, `bumper_f_loda`, `bumper_r_loda`, `underface_loda`...);
- the lights object and its materials;
- the interior and cockpit objects (`interior_loda`, `interior_cpit`, `windows_cpit`,
  `steeringwheel_*`);
- the donor's materials by name (`VW_VIRTUS_MISC`, `VW_VIRTUS_LIGHTS`, `VW_POLO_GTS_RIM`...).

Format details: [04-meshes-and-render.md](../04-meshes-and-render.md).

## The fit

`fit_model_into_donor` appends the source model into a copy of the donor .blend, scales and places it
on the wheel markers, sorts its parts into donor slots and assigns donor (or custom) materials. The
result is `model/car.blend`, which `build-meshes` turns into game meshes. A runner script keeps the
steps together (`model/run_fit.py`):

```python
import json, os, sys
sys.path.insert(0, r"<ams2kit repository>")
from ams2kit.mesh import blend_bridge as BB, texels as TX
from ams2kit import actions, materials as MAT, project as PM

PROJ = r"<project>"
HERE = os.path.join(PROJ, "model")
pr = PM.Project(PROJ)
steps = sys.argv[1:] or ["fit", "build"]
if "fit" in steps:
    tx = TX.project_texels(pr, log=print)                      # texture-checked flat colours
    json.dump(tx, open(os.path.join(HERE, "texels.json"), "w"), indent=1)
    log = BB.fit_model_into_donor(os.path.join(HERE, "donor_<donor>.blend"), os.path.join(HERE, "<car>_src.blend"),
                                  os.path.join(HERE, "car.blend"), config=os.path.join(HERE, "<car>_fit.json"),
                                  texels=tx, custom_materials=MAT.mtx_paths(pr))
    json.dump(log, open(os.path.join(HERE, "fit_log.json"), "w"), indent=1)
if "build" in steps:
    print(actions.job("build_meshes", {"path": PROJ})(print))
    man = json.load(open(os.path.join(PROJ, "build", "meshes", "manifest.json")))
    print("warnings:", *man["warnings"], sep="\n  ")
```

Then `python -m ams2kit build <project>` and `install <project>`.

## Fit config skeleton

```json
{
 "exterior_root": "EXTERIOR",
 "exterior_exclude": ["Ext_Door_Limiter_*"],
 "wheel_objects": {"FL": "Rim_FL", "FR": "Rim_FR", "RL": "Rim_RL", "RR": "Rim_RR"},
 "rim_materials": ["Material Atlas"],
 "material_classes": {"Car Paint": "PAINT", "Windows": "GLASS", "Trim": "PLASTIC"},
 "part_slots": {},
 "light_ids": {},
 "interior": null
}
```

Every key, with defaults, is listed in `FIT_DEFAULTS` in `ams2kit/mesh/blend_bridge.py`. The page for
each part explains its keys. Materials without a class are guessed from their name with a warning: give
every material an explicit class.

## Reading the results

- `fit_log.json`: scale, wheel fit error, which donor objects and materials were used, the texel picked
  for each class (with its colour), warnings.
- `build/meshes/manifest.json`: per mesh the action (`mesh`, `dmg`, `collapse`, `donor`), vertex and
  triangle counts, `sphere_excess_m`, reader check, and the warnings list. Read the warnings after every
  build; most problems show up there first (a material a slot doesn't suit, a light id the slot lacks).
- `render_preview(car.blend, out.png, view="front34")` gives a quick Blender look, but the game is the
  judge ([Testing](09-testing.md)).
