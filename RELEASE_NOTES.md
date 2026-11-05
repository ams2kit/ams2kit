# Release notes: 2026-11-04 to 2026-11-05

Two days of work, mostly from porting the **VW Jetta GLI** onto the VW Virtus GTS. The car now looks
close to the source model in game, with working brake lights.

## Highlights

- **Your own textures.** A car can now use its own textures (atlases, badges, grilles, rims) through
  clones of the donor's materials (`[materials]` in `car.toml`). PBR images are converted for the game's
  shader. Solid colours work for lenses, e.g. a smoked taillight lens.
- **Working tail and brake lights.** Lamp faces get the donor's light ids, so they light up with the tail
  lamps and brakes. Glowing parts sample a texel that is lit in the donor's glow map. Set per material
  with `light_ids` in the fit config. *Tested in game on the Jetta.*
- **Better car-select images.** Menu images render with Cycles in a dark studio, matching the base cars.
  They can render from the source model with its own materials (`[art] render_blend`).
- **Porting guide.** `docs/porting/` explains how to port a car: source model, donor and fit, body,
  materials, wheels, lights, interior, menu art, testing. It is written so an AI agent can follow it.
  The 3D Model page shows it as tabs.
- **Share a car.** `ams2kit share` (or the Build & install page) makes a zip with an installer, so
  friends can install your car without ams2kit.
- **Engine sounds.** A car can use any installed car's engine sound (new Sound step,
  `[sound] kit`). Replacing single samples with your own WAVs is experimental and *not yet tested in
  game*.

## UI

- Rewritten as a Vue 3 app (built with Vite; the build is committed, so running ams2kit still needs only
  Python).
- Physics page: drag-to-edit torque curve and gearing charts (Curves tab).
- Sound step: pick a sound kit, play and replace samples.
- 3D Model page: the porting guide in tabs.
- `tools/mock_ui.py`: try the UI without the game, Blender or a donor.

## Model fit and meshes

- `split_sides` splits a part into left and right halves for `part_slots` (e.g. one rear-caliper object
  into per-corner caliper slots).
- `rim_custom_material` gives the rims a textured material.
- `CUSTOM:<NAME>:<CLASS>` keeps a textured part in a chosen slot kind (e.g. lamp internals in the lights
  mesh).
- New light faces no longer get fractional light ids from a straight-line fit.
- Custom light materials get their own glow map, black by default, so they never glow by accident.

## Testing

- Menu screenshots read the screen with Windows OCR and click labels, instead of fixed coordinates and
  waits. They detect when the menus show another car than expected.

## Platforms

- ams2kit now starts on macOS and Linux (UI, projects, physics, tests). Driving the game and reading
  compressed base-game files stay Windows-only.

## Fixes

- Window glass named like a lamp ("... Tinted Light") rendered white in menu images.
- Menu renders were written next to the `.blend` instead of the project (relative paths).
- Coloured metals (e.g. a red accent) rendered grey with custom materials.
- The UI server now serves `.js` files as JavaScript on every Windows setup.

## Known gaps

- A third brake light that the source model keeps in its interior is not mapped yet.
- Sound sample replacement is untested in game.
- Brake-caliper far LODs are not derived.
