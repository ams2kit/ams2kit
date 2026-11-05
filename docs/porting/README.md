# Porting a car: overview

This guide is written for an agent (or a person) asked to "put car X into the game". It collects what
we learned porting the **BYD Seal** (Veneno donor) and the **VW Jetta GLI** (VW Virtus GTS donor). Each
page is one part of the car; the 3D Model page of the UI shows the same pages as tabs.

| Page | Covers |
|---|---|
| [Source model](01-source-model.md) | Getting the model, importing it read-only, orientation, scale, textures |
| [Donor & fit](02-donor-and-fit.md) | Choosing a donor, the donor .blend, the fit config and runner |
| [Body](03-body.md) | Material classes, splitting the body over slots, vertex limits, culling spheres |
| [Materials](04-materials.md) | Flat-colour texels, the car's own textures (custom materials), PBR conversion |
| [Wheels](05-wheels.md) | Rims, tyres, brake discs and calipers, wheel positions |
| [Lights](06-lights.md) | Headlights, tail and brake lights: light ids, glow maps, lenses |
| [Interior & cockpit](07-interior-cockpit.md) | Interior meshes, steering wheel, the view from the seat |
| [Menu art](08-menu-art.md) | Car-select images, liveries, logo |
| [Testing](09-testing.md) | Checking in game, showroom screenshots, troubleshooting |

## The workflow at a glance

1. **Get the facts**: real specs (power, torque, mass, wheelbase, tracks, tyre size, gearing) and
   reference photos of the real car (front, rear, interior, lights on). Save them in the project
   (`SPECS.md`, `ref/`). You will compare against the photos many times.
2. **Pick a donor** of similar size, drivetrain and class, and create the project
   (`python -m ams2kit new <dir> <Name> <Donor>`).
3. **Import the source model** into a new `.blend` (never edit the original) and list its objects and
   materials ([Source model](01-source-model.md)).
4. **Export the donor .blend** (`export-blend`) and write the **fit config** (`model/<car>_fit.json`):
   which model objects are the exterior, the wheels, the interior, and a class for every material.
5. **Run the fit** (`fit_model_into_donor`) to get `model/car.blend`, then `build-meshes`, `build`,
   `install`.
6. **Look at it in game** (showroom screenshots, [Testing](09-testing.md)), compare with the reference
   photos, fix the worst thing, repeat. Typical order: body and glass → materials and badges → wheels →
   lights → interior → menu art.
7. **Physics and specs** are independent of the model: the Specs and Physics pages (docs 03, 11-14).

## Rules for agents

- **Never modify the user's source files** (the downloaded model, its `.blend`, the Downloads folder).
  Import or append into a new file; save outputs inside the project.
- **Never start, stop or click in the game while the user is playing.** Check the process list first;
  automated runs start and close their own game instance. Don't ask the user to close the game.
- **Check before guessing.** Read the file, decode the texture, inspect the mesh streams, take the
  screenshot. Most wrong turns in these ports came from assuming what a texture or a vertex stream held.
- **Verify every visual change in game**, not only in Blender previews: the game's shaders, light
  control and culling differ from Blender.
- **Bisect when something breaks.** Build with and without the latest change and compare in game; the
  game rarely says why it ignored a file.
- Keep one config change per build when chasing a visual problem, and keep a copy of the last good
  fit config (`<car>_fit.before_<change>.json`).
- Base-game paks are never modified; everything goes into the car's own paks and mod folder.

## Where things are

```
<project>/
  car.toml                 specs, [art], [materials], [sound], [model]
  SPECS.md, ref/           real-car facts and reference photos (yours)
  model/
    <car>_src.blend        the imported source model (read-only input to the fit)
    donor_<donor>.blend    exported donor (ams2kit)
    <car>_fit.json         fit config
    run_fit.py             fit + mesh build runner
    car.blend              fit output = what build-meshes reads
    fit_log.json           what the fit decided (texels, donor materials, warnings)
    texels.json            texture-checked texels per donor material
    textures/              images for custom materials (exported from the source .blend)
  build/meshes/manifest.json   per-mesh results and warnings
```
