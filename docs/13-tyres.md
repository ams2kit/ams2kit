# 13: Tyre and wheel size

**Status:** where the size lives is found [file + proven]; ams2kit sets it (`[chassis] tyre_size`), resizes the
visual tyres and fits the rims to them. The in-game check is pending (check list at the end).

## Summary

- **The physics tyre size is in the car's `.vdfm`, not in the tyre set.** Per wheel (FL, FR, RL, RR):

  | File offset | Content |
  |---|---|
  | `0x98 + 12*i` | wheel position x, y, z: the visual hub (= `.vhf` hub MATRIX = tyre mesh CARCASS bone; y = hub height above the design ground) |
  | `0xC8 + 8*i` | tyre **width**, tyre **diameter** (m) |

  Examples: Lancer R 0.245/0.635 all round; Veneno 0.255/0.664 front, 0.355/0.714 rear (255/30R20, 355/25R21);
  Camaro SS 0.245/0.71 front, 0.275/0.71 rear.
- **The game uses radius = 0.5 × diameter** [proven] (for example the spawn height: spring offset + 0.5 × diameter).
- **Data check** [file]: for **251 of 267** base cars, vdfm
  diameter / 2 equals the tyre mesh radius (half its AABB height) within 1 cm; median difference 0.7 mm. The
  rest are karts, old F1/formula cars and a few with stylised meshes.
- **The tyre set** (vdfm `0x88`, a name from the boot list `TyresHD.xml`, 177 sets) holds the tyre model
  (grip, heat, carcass, a compound list such as `Street` / `Slick`) and **a width per axle** (key `bd034c23`),
  but **no radius**. A mod still
  can't add a set, but it can point at **any** base set.
- Things that are **not** the radius: chassis `1824eaa8` (CG height; equals 0.3235 on the Lancer only by
  coincidence), suspension wheel-body inertia, suspension wheel-centre y (equals the radius on about half the
  cars, whose physics frame has its origin on the ground; the others, e.g. Lancer 0.2033, Camaro 0.2185, are offset).

## Visual tyres

- Tyre meshes are skinned. Bones: `bone_TIRE_xx_CARCASS / RIM / ROAD / SIDEWALL_LEFT / SIDEWALL_RIGHT`. Their bind
  transforms are identity rotations with **car-space** translations: CARCASS = the hub (= vdfm wheel position),
  RIM = bead (Lancer: 0.2285 below the hub = 18 in), ROAD = contact point (0.3233 below = mesh radius),
  SIDEWALLs = ±0.15 m sideways at the bulge. Vertices are wheel-local (centre 0, axle = x).
- The render reads tyre dimensions from the bone binds (the y difference of two binds), so vertices and bone offsets must be scaled together.
- `tyres.resize_tyre_meb`: x × (new width / donor vdfm width); radius mapped linearly from [donor bead, donor
  outer] onto [new rim radius, new outer] (the sidewall keeps its profile); normals/tangents through the map's
  Jacobian; bone offsets from CARCASS mapped the same way. CARCASS stays where it is. New outer radius =
  new diameter / 2 + the donor's (mesh − physics) offset (Lancer +5.8 mm), so the tyre sinks into the road
  exactly as the donor's does.
- The bone binds keep the donor's hub x/z even when the hubs move (wheelbase/track change). Earlier builds did
  this and their wheels rendered correctly in game.
- Reusing another car's tyre meshes would also work, but the resize covers every donor and every LOD.

## ams2kit

`car.toml`:
```toml
[chassis]
tyre_size = "245/45R19"        # both axles; "" keeps the donor's size
tyre_size_rear = ""            # rear if different, e.g. "275/40R19"
tyre_set = "chevrolet_camaro_zl1"   # tyre model (grip): any base set; "" = the donor's
resize_tyre_meshes = true
wheel_radius_m = 0.0           # EV gearing override; 0 = tyre diameter / 2
```
- `python -m ams2kit tyres <project> [size] [--race]` prints the donor's and the requested sizes and the base
  sets ranked by their per-axle width and the sizes of the cars that use them (road compounds first).
- **buildphys:** writes the vdfm width/diameter, moves the vdfm wheel positions with the wheel moves (like the
  .vhf hubs; `AMS2KIT_KEEP_VDFM_WHEELS=1` keeps the donor's), sets `0x88` to `tyre_set` (checked against
  `TyresHD.xml`). The EV rolling radius is now diameter / 2 of the driven axle (Specs size, else the donor's
  vdfm) instead of the tyre mesh height.
- **Meshes:** `actions._mesh_files` gives the Blender pipeline the resized tyres, so the donor .blend shows them
  and the fit tool's `rim_fit: "tyre"` sizes the rims to the new bead (re-export the donor .blend after changing
  the size). `build.py` writes the resized tyres (`build\tyres\`) as car-owned meshes with the vhf paths and
  culling spheres updated.
- **doctor:** fails only when the tyres field isn't a base set, or when the vdfm sizes don't match the Specs;
  warns when the chosen set's widths are more than 3 cm off the Specs.
- Tests: `tests\test_tyres.py`.

## BYD Seal on the Lancer R (`kit_projects\BYD_Seal_Lancer`)

| | Before | After |
|---|---|---|
| Physics tyre | Lancer 0.245 × 0.635 m (r 0.3175) | 245/45R19: 0.245 × 0.7031 m (r 0.3515) |
| Visual tyre | r 0.3233, bead 0.2285 (18 in) | r 0.3573, bead 0.2413 (19 in) |
| Rim scale (fit) | 0.81 | 0.858 / 0.863 (front / rear) |
| Tyre set | `LancerR` (Slick, 0.22 m) | `chevrolet_camaro_zl1` (Street, 0.245 / 0.275 m; ran on the BYD Camaro build) |
| EV final drive | about 4.98 (r 0.3235, tyre mesh) | 5.409 (r 0.3515) |

Previews: `research\wheels\wheels_sheet.png` (before / after / build output), `before_*.png`, `after_*.png`,
`built_*.png`. Run script: `research\wheels\run_byd_lancer.py`. Backup of the previous car.blend, donor .blend
and meshes: `research\wheels\backup_lancer\`.

## In-game check list
See the report of 2026-11-03 (also below).
1. Install the BYD_Seal_Lancer build, load a track: no crash (the vdfm changed in its wheel block and tyre set).
2. Showroom/track side view: the tyres fill the arches, rims sit in the tyres (no gap or poke-through), and
   the tyres touch the road (they neither float nor sink more than a few mm).
3. Drive: the tyre sidewalls deform at the bottom, not in mid-air (ROAD bone posed at the contact patch).
4. Telemetry: at 100 km/h, wheel rotation ≈ 27.78 / 0.3515 = 79 rad/s; top speed still ≈ 187-192 km/h at 8000 rpm.
5. Compare: a stock Lancer R still has its own tyres and handling.
