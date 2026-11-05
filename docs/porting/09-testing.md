# Testing

## Showroom screenshots, automatically

`menu_nav.showroom(out_dir, name, car="Volkswagen Jetta GLI")` (also `python -m ams2kit menu <project>`):

1. starts its own game instance (refuses if the game is already running);
2. reads the menus with Windows' built-in OCR and clicks labels: Single Race → vehicle panel → Showroom;
3. saves `<name>_event.png`, `<name>_select.png`, `<name>_showroom.png` and orbit frames
   (`<name>_orbit_NN.png`; the showroom camera circles the car);
4. closes the game.

- The game draws its own menus (no accessibility tree), and OCR misses text on the colourful menu
  backgrounds unless captures are converted to grayscale. Captures only happen while the game window is in
  front, so a user's window is never captured.
- The menus show the profile's current car. If it is another car, the result is `car_mismatch`; make your
  car current (start one race with it, e.g. with a launcher preset) and run again.
- Put the orbit frames on one contact sheet and compare with the reference photos and a base car.

## On track

- Things only visible on track: lights (headlights, braking, reverse), wheels turning, the cockpit view,
  LOD switching at a distance, culling at screen edges.
- Use a chase camera behind the car for lamps. Have the user drive if automated input isn't reliable.
- `python -m ams2kit test <project> [seconds]` lets the AI drive and logs telemetry (needs one manual
  Custom Race with the car first).

## Troubleshooting

| Symptom | Likely cause / check |
|---|---|
| Car missing from the car list | The game ignored the car. Check the install (paks registered, mod folder), then bisect: rebuild without the latest change and test. Once, a reinstall of identical files fixed it; capture the broken state before reinstalling. A crd property declared but missing also hides the car ([08](../08-pitfalls.md)). |
| Part renders solid black | Its slot lacks the streams its material needs (e.g. paint in the underface slot). Move it with `part_slots`. |
| Part has the wrong flat colour | Read `fit_log.json → texels`; set a better class or use a custom material. |
| Colours on the wrong parts | Texture images flipped relative to the UVs: export from the .blend or `flip_v`. |
| Windows red / white / opaque | Glass class and texel; window material names in the menu renderer. |
| Lamps never light | Light ids missing or fractional, or the texel isn't lit in the glow map ([Lights](06-lights.md)). |
| Lamps glow all the time or in odd places | A light material with the donor's glow map at your UVs: custom light materials need their own glow map. |
| Donor car shows your body | Meshes written at donor paths. ams2kit writes car-owned paths; check for hand-made overrides. |
| Part pops out at screen edges | Culling sphere; check the build grew the spheres. |
| Lumpy paint | Body decimated over the vertex limit; spread it with `part_slots`. |

## Before calling it done

- Showroom orbit from all sides, close-ups of the front, rear and wheels next to the reference photos.
- Lights on track, braking from behind.
- Select screen next to a base car of the same class.
- Fit warnings and mesh-build warnings read and explained.
- `python -m ams2kit doctor <project>` passes.
