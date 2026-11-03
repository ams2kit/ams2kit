# 04: Meshes and the render model

Full format notes: `meb\FINDINGS.md` in the author's research workspace (not in this repository; layout,
streams, tangents, bones, damage morphs). The code is `ams2kit\mesh\meb_read.py` and `meb_write.py`.
This page is the summary plus how we used it.

## `.meb` mesh files [proven]

- No compression. The only obfuscation is **the X component of POSITION** (stream format id 20),
  XOR-encrypted per vertex with a key derived from a hash of the **upper-cased file name**
  (Jenkins lookup2, `CreateHash32NoCase`).
- **Renaming a mesh requires re-encrypting it** under the new name: `meb_write.serialize(m, new_name)`.
- `meb_read.py` and `meb_write.py` handle all 176 donor meshes and round-trip them byte-identical.
- Game space is X = left, Y = up, Z = rear.
- `_dmg` files are damage morphs with 0 index buffers.
- Each sub-mesh (index buffer) names its material (`.mtx`/`.bmt` path) and has its own AABB and sphere.

## How the game finds meshes [proven]

The car's `.vhf` (text XML) lists every object by **full mesh path**. Next to it, the `.vhf.bml` and
`.bmt` are binary XML (BLMY); we have no writer for those. Because files resolve by full path across
paks, the simplest route is:

> **Write the new body under the donor's mesh names and put those files in our pak.**

`meb\build_veneno_slots.py` does this and writes `meb\byd_veneno_slots\` plus `manifest.json`
(pak path → file), which `build_byd_paks.py` applies (`apply_mesh_overrides`). Set `BYD_NO_MODEL=1`
to skip it. The slots are:
- the BYD body in `body_lod{a,b,c}` (+`_dmg`);
- lights in `lights_lod{a,b}`;
- the far LOD in `chassis_lodd`;
- the rims in `wheel_*`.

The Veneno-only parts (boot lid, front bumper, rear wing, chassis A–C, wiper, light glows) are hidden
by **collapsing their vertices**.

**Side effect:** our meshes sit at Veneno paths, so a real Veneno on the same track would show
the BYD body while our pak is loaded. A tutorial for independent cars needs a `.vhf.bml` writer.

## Fitting the body to the physics

- v1: scale 0.843 to the Veneno's wheel positions. It rendered correctly, but the tyres stuck out about 10 cm.
- v2 (current): real size, scale 0.91114 of the source model, wheel centres at the physics wheel
  points (±0.810, 0.333, −1.46) and (±0.8125, 0.358, 1.46).
- Still open:
  - the Veneno rear tyres (0.38 m wide) stick out about 7.5 cm;
  - the body exceeds the `.vhf` culling sphere by 0.16 m, so it may pop out at screen edges;
  - lights render grey, rims black, and there are no BYD textures yet.

## Blender workflow

- The source model was a `.blend` file (136k tris, separate wheels, 1 UV set).
- Open it with `--disable-autoexec` and never save over it.
- Export script: `meb\work\blender_export_slots.py`. The Blender MCP was also available for inspection.
- glTF would work equally well as a source format; anything Blender can import does.

## Donor .blend round trip (ams2kit) [proven offline, not yet tested in game]

Code: `ams2kit\mesh\blend_bridge.py` (API), `mesh\donor_layout.py` (name classification and
rebuild plan), `mesh\vhf_nodes.py` (node matrices), `mesh\meshweld.py` (welding), and the headless Blender
scripts in `ams2kit\blender\` (`export_donor.py`, `import_blend.py`, `render_preview.py`, `_common.py`).
Tests: `tests\test_blend_bridge.py` (run `python -m unittest tests.test_blend_bridge -v` in the
repository root).

```python
export_donor_blend(mesh_files, out_blend, *, wheel_centres=None, vhf_text=None, blender_exe=None,
                   donor_name=None, work_dir=None) -> dict
build_from_blend(blend_path, donor_mesh_files, out_dir, *, blender_exe=None, force_rebuild=False,
                 include_unchanged=False, work_dir=None, keep_dump=False) -> {pak path: output file}
render_preview(blend_path, out_png, *, view='front34', blender_exe=None) -> out_png
```
`blender_exe=None` uses the Blender ams2kit finds (Setup page, `%AMS2KIT_BLENDER%`, Program Files, PATH).
- `mesh_files` is `{pak path: bytes}` for every `.meb` in the main and cockpit paks.
- `vhf_text` is the `.vhf` text, or a list of texts for main + cockpit.
- `wheel_centres` are the physics wheel centres in game space, e.g. `{'FL': (x, y, z), ...}`; `lf` and
  `WHEEL_FL` also work. Without them the vhf hub nodes are used.
- `build_from_blend` writes `out_dir\<pak path>` plus `out_dir\manifest.json`. For every file the
  manifest records:
  - action, status, verts, tris, materials;
  - AABB, sphere, the donor sphere, and `sphere_excess_m` (how far the new sphere exceeds the donor's,
    which equals the `.vhf` culling sphere);
  - `cockpit_pak`, `derived_from`, reader check result and notes.
- The returned dict lists only the files that differ from the donor.

### Coordinate convention
- Blender = (game.x, game.z, game.y): Blender X = car left, Y = car rear, Z = up.
  - The car faces −Y, which is Blender's "Front" view (numpad 1).
  - This is the same orientation as the BYD source model and `build_from_obj`.
- The swap is a reflection, so triangle winding is reversed in both directions.
- Object matrices are converted with M_blender = S·M_game·S, where S swaps Y and Z.
- Mesh data is kept local to its node: the object matrix is the `.vhf` node matrix.
  - Wheel-corner meshes (rim, tyre, disc, caliper) instead use a frame at the physics wheel centre,
    with the vhf rotation.
  - **[G]** This assumes the game places wheel nodes at the physics positions. For the Veneno rear,
    physics and vhf differ by 2.2 cm (0.859 vs 0.837).
- On import, each object's evaluated world mesh is mapped back into its slot's frame, so moving
  objects around works.

### .blend organisation
- **Objects:** one object per `.meb`, named after the file stem.
  - Custom properties: `ams2_slot`, `ams2_pak_path`, `ams2_role`, `ams2_note`, `ams2_frame_game`, plus
    `ams2_skinned` on skinned meshes.
  - One material slot per index buffer. The material is named after the donor `.mtx` path and also
    carries it in `ams2_mtx`.
- **Visible collections:** `REPLACE_Body` (exterior LOD A), `Lights`, `Glass`, `Wheels/Wheel_FL..RR`,
  `Interior`, `Other`, `Guides`.
- **Hidden collections:** `Cockpit` (cockpit-pak-only meshes), `Flares` (light-glow quads), `LODs`,
  `CockpitView` (`*_cpit` copies of exterior parts), `Damage`.
- **Guides:**
  - empties `WHEEL_FL..RR` at the wheel centres, drawn as circles of tyre radius;
  - the `GROUND_guide` plane, an info text and a "FRONT" marker;
  - text block `AMS2KIT_README`, which explains the workflow;
  - text block `ams2kit_slots.json`: the frame and a geometry fingerprint per slot.
- **Stream storage:**
  - TEXCOORD0 → UV map `UVMap` (v flipped to Blender's v-up).
  - Other texcoords → UV maps `TEXCOORDk`. 1-component sets and 3rd components go in float corner
    attributes (`TEXCOORDk`, `TEXCOORDk_W`).
  - COLOR0 → byte colour attribute `COLOR0`.
  - `ams2_donor` is a point flag.
  - `ams2_co`, `ams2_nrm`, `ams2_tan4` and `ams2_tan5` hold the exact donor positions, normals and
    tangents. They are reused for donor vertices the user did not move, because Blender's int16 custom
    normals cannot reproduce every donor normal.

### Build rules
- **Slot matching:**
  - the object named exactly like the slot;
  - otherwise an object with `ams2_slot` set to the slot;
  - plus objects with custom property `ams2_target = <slot>`, which are merged in.
- **Status:**
  - unchanged (fingerprint equal) → donor bytes, byte-identical;
  - missing or empty → collapsed mesh (hidden);
  - edited → rebuilt from the evaluated mesh (modifiers applied, triangulated, split per material,
    welded by material, vertex, normal, UVs and colour). New geometry is welded by position, because
    imported models are often fully split.
- **Derived meshes:** lower LODs, `_blur` rims and `*_cpit` copies follow their part's LOD A when that
  was edited.
  - They use the donor's triangle ratio, applied with Blender Weld + Decimate (collapse).
  - If the user edits one of these objects, that version wins.
  - **Far-LOD union:** a LOD level that only one part has stands in for the whole car. Examples: Veneno
    `chassis_lodd`, and `body_lodd` on the Camaro, BMW and Lancer. That slot gets the union of all
    exterior LOD A parts.
  - Material variants: `*_RIM` becomes the donor's `*_RIM_LODC` in a `_lodc` mesh.
- **Damage:** `_dmg` = undeformed copy of the rebuilt base (0 index buffers, base bounds), the same as
  `build_veneno_slots.py`.
- **Skinned meshes** (tyres, wipers) can only be kept or deleted. Tyres can be resized to a tyre size outside
  Blender (`tyres.py`, `[chassis] tyre_size`, doc 13).
- **Vertex limit:** above 65,535 welded vertices the mesh is decimated automatically, and derived LODs
  take that decimation into account.
- **Stream fill for new vertices:** the template's stream layout is kept exactly.
  - TEXCOORD0 = the user's UVs.
  - Other texcoords come from the donor, per material: a constant if the donor values are constant,
    otherwise a least-squares linear fit on position clamped to the donor range. This generalises
    `livery_uv()`.
  - COLOR0 = white, with the donor's alpha.
  - Tangents come from `tangents_np`, the vectorised `compute_tangents`.
  - Material custom properties override these: `ams2_uv0` = `user` | `fit` | `u,v`;
    `ams2_tc<k>` = `fit` | `a,b`; `ams2_col` = `r,g,b,a`.
- **Materials:** faces with a non-donor material fall back to the slot's first donor material, and the
  build warns. **User textures are not supported yet.**
- Unassigned mesh objects are reported as warnings.

### Results
- **Round trip** (export → unchanged .blend → build):

  | Donor | Meshes | Plain build | Forced rebuild equivalent |
  |---|---|---|---|
  | Lamborghini Veneno | 109 | 0 files changed | 109/109 |
  | Chevrolet Camaro SS | 114 | 0 files changed | 114/114 |
  | BMW M4 GT3 | 110 | 0 files changed | 110/110 |
  | Mitsubishi Lancer R | 102 | 0 files changed | 102/102 |

  - "Equivalent" means: same layout, materials, indices and vertex order; positions within 2.4e-7;
    normals and UVs exact; tangents 100% agreement.
  - The Veneno and Camaro cases are in the unit test. The BMW and Lancer were run with
    `research\blend\run_roundtrip.py`.
- **Edit test:** delete one part and move the body. The deleted part and its LODs, damage and cockpit
  copies collapse; the body's LODs, damage and cockpit copy are rebuilt.
- **BYD proof** (`research\blend\byd_test\`):
  - Steps: export the Veneno .blend with the BYD wheel centres; `make_byd_car.py` appends the source
    model (read-only), scales it by 0.91114, fits it to the `WHEEL_*` empties (≈1.3 cm error) and
    assigns donor materials by class.
  - Result: 61 changed files, with the same slots as `meb\byd_veneno_slots\`.
    - body_loda: 57,081 tris, the same as the reference.
    - lights: 16,290 tris, the same as the reference.
    - Rims at the donor rim radius; Veneno-only parts collapsed.
  - Differences from the reference:
    - LOD B/C are decimated (the reference reused LOD A);
    - the BYD body also goes into `body_cpit`;
    - `bonnet_cpit`, `chassis_cpit` and `wiper_cpit` are hidden.
  - The body exceeds the vhf culling sphere by 0.16 m, as before.
  - Previews: `preview_sheet.png` (donor, BYD in donor, re-imported build output, far LOD).

### Fitting a model into a donor .blend (`fit_model_into_donor`)
```python
fit_model_into_donor(donor_blend, model_blend, out_blend, *, config=None, scale=None, wheel_objects=None,
                     material_classes=None, rim_fit=None, blender_exe=None, work_dir=None) -> fit log
visual_wheel_centres(vhf_text, donor_physics_centres=None, new_physics_centres=None) -> {corner: (x, y, z)}
```
- Runs `blender\fit_model.py` on the donor .blend. The model .blend is only appended from (read-only).
- **Found automatically:**
  - donor objects from the slot roles and collections: the body host in REPLACE_Body, the lights host,
    rims and tyres per corner;
  - donor material per class (PAINT, GLASS, PLASTIC, GLOSS, LIGHT, RIM), from `.mtx` name heuristics
    and the body, lights and rim materials ranked by triangle count;
  - texture hints for new glass, light and rim faces: the donor's most common UV for that material;
  - scale from the wheelbase and placement on the `WHEEL_*` empties;
  - rim radius = donor tyre inner radius + 5 mm. Donor rims sit about 5 mm under the bead.
- **Hidden automatically:**
  - all other REPLACE_Body parts;
  - the Glass, Flares and wiper objects;
  - cockpit-only exterior parts: body/wiper roles, cockpit glass, `extanim`.
- **Model-specific input** (`config`, a JSON file; keys in `FIT_DEFAULTS`):
  - `exterior_root` / `exterior_objects`, `exterior_exclude`;
  - `wheel_objects`, `tyre_materials`, `rim_materials`;
  - `material_classes`; unknown materials are guessed from their names, with a warning;
  - optional overrides: `scale`, `rim_fit`, `donor_materials`, `uv_hints`, the hide flags, `extra_hide`
    and `keep`.
- The BYD config is `research\blend\byd_camaro\byd_seal_fit.json`.
- Reproducing the hand-tuned Veneno build: run with `veneno_repro_overrides.json` (the old texels,
  `rim_fit: donor_rim`, no cockpit glass/extanim hiding). The output is byte-identical (109/109 files).
- **Wheel frames:** on some donors the physics frame is not the visual frame.
  - Camaro SS physics wheel centres: y = 0.2185, z = −1.354 / +1.496.
  - Camaro SS vhf hubs: y = 0.35, z = −1.451 / +1.360.
  - So the `WHEEL_*` markers must use `visual_wheel_centres()`: the vhf hubs plus the change in physics
    geometry. The physics points must not be used directly.
  - For the Veneno both frames coincide.

### Fit-tool additions from the Jetta GLI build (2026-11-03) [offline, in-game test pending]
Config: `research\jetta\jetta_fit.json`. Run script: `research\jetta\run_fit.py`. Donor: VW Virtus GTS.
- **glTF input:** import the .glb into a new .blend first (`research\jetta\import_glb.py`).
  - `auto_orient` (default on) turns a model that faces +Y round by 180°; `rotate_z_deg` sets the angle explicitly.
  - `exterior_root` may now be an empty.
  - `exterior_exclude` accepts fnmatch patterns.
  - Wheels that share one mesh datablock are made single-user before the rim cut (before this fix, all four rims came out empty).
- **`part_slots`** `{model object pattern: donor body object}` spreads a detailed body over several body slots,
  e.g. bumper_f, bumper_r and underface.
  - Each .meb holds at most 65,535 vertices. A 140k-triangle body was otherwise decimated (ratio 0.61), and the
    paint looked lumpy.
  - Caveat: parts go into slots that are not body-shaped (doors in bumper_r). If the game detaches bumpers on
    heavy damage, those parts would detach with them.
- **`cockpit_body`** `{*_cpit object: {objects, min_z}}`: full-detail model parts for the body as seen from the seat.
  - Without it, `body_cpit` is derived from the body LOD A, decimated by the donor's ratio.
  - Parts sent to other slots would have no cockpit copy at all.
- **`interior`** replaces the donor's interior and cockpit meshes (`fit_model.fit_interior`):
  - model `root`, `steering_root` and `exclude`;
  - `material_classes` maps each model material to a class, and `donor_materials` maps each class to a donor
    `.mtx`. New faces get a flat colour from that donor material's most common texel;
  - `targets` per donor object, which can be a dict {kind, objects, exclude, materials_from}. This splits a big
    interior over `interior_cpit` plus the (otherwise hidden) cockpit-pak `windows_cpit` slot, so it is not decimated;
  - `decimate` per target (e.g. the exterior-view `interior_loda` at 0.15);
  - `align_steering`: the model wheel's centre and axis (PCA) are moved onto the donor wheel's, which is what the
    steering node rotates about. For the Jetta: 4 cm, 2-4°.
- **Culling spheres:** `build.vhf_fit_spheres` grows the car's text-.vhf SPHERE entries to cover the rebuilt meshes
  (object, then parent groups, then root). The `sphere_excess_m` warnings in the mesh manifest are therefore
  handled at pak build time.
- **Texture-checked texels** (`mesh\texels.py`, passed as `fit_model_into_donor(..., texels=...)`; in game, first build).
  - **Problem:** the old "most common donor UV" hint landed on the red tail-light quadrant of the shared 16×16
    `common_glass_various_diff.dds`, so the Jetta's windows came out red in game.
  - **How it works now:**
    - Material → `.bmt` → diffuse `.dds`: the donor paks are searched first, then the game's top-level paks
      (index cached as `%LOCALAPPDATA%\ams2kit\texture_index.json`).
    - The texture is decoded with Pillow and every class gets a scored texel: GLASS (neutral, translucent),
      LIGHT, LIGHT_RED, LIGHT_AMBER, RIM, GLOSS, PLASTIC/INTERIOR (neutral dark).
  - **How it is written:** the texel goes into each new face's own UVs (`ams2_uv0 = user`). Classes that share a
    donor material can therefore differ: red tail lights and white headlights both use `VW_VIRTUS_LIGHTS`.
  - **Logging:** the fit log's `texels` lists each pick with its colour.
  - **Also:** SKIP faces inside mixed objects are now dropped.
- **Slot materials matter:** a slot keeps its donor vertex streams. Paint parts sent to the underface slot (no
  TEXCOORD2/4) rendered solid black in game.
  - The fit tool warns when a `part_slots` target doesn't use a material its parts need.
  - The build notes every material that isn't the slot's own.
- **`render_preview(view='cockpit:x,y,z[,yaw]')`** renders the driver's view from a game-space eye point (cockpit .bin
  +0x88; the Virtus value is 0.334, 1.228, 0.109).

### Open points
- In-game test of rebuilt and derived meshes.
- Cockpit-only donor parts (e.g. the Veneno `bonnet_cpit`) stay visible from the driver's seat unless
  the user deletes them.
- Far-LOD decimation of many small objects is coarse.
- Damage morphs are undeformed.
- No user textures or materials yet: this needs a `.bmt` (BLMY) writer.
