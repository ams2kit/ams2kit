# 08: Pitfalls (each of these cost us real time)

## Paks
- **TOC CRC must be recomputed.** It is `~crc32` of the bytes *as stored*. A wrong CRC gives an
  in-game CRC error, at the moment the car loads.
- **RC4 keys are null-terminated.** Truncate the PCarsTools keys at the first `0x00`.
- **New paks need a `PakDirInfo.dat` entry**, appended (the list is unsorted). Game updates may reset it.
- The name table is encrypted only up to `sec_pos`; the tail is padding.

## Car list
- **A crd prop declared in the header but missing from the data makes the car silently vanish.**
  Remove both the declaration and the value.
- Loose crd files for base cars are ignored, and XLASTID was a red herring.

## Physics
- **A vdfm whose section pads don't add up is silently rejected** (null tyre set, crash on
  load). Each section-table entry has a pad byte, and the sizes plus pads must equal the file
  length (doc 12). `physics.serial_layout_ok` checks this. With valid pads, the chassis, suspension, engine,
  gearbox and collision names can be the car's own. **The tyres field must stay a base-game tyre set.**
- **The tyre size is not in the tyre set:** it is the vdfm wheel block (width, diameter per wheel, doc 13).
  Keeping the donor's tyre set does not force the donor's tyre size.
- **Keep 7 gear slots** with the reused driveline. A 1-gear `.gdfbin` makes the physics explode
  (the "camera goes crazy").
- **Parse ShCB rows by key, not by assumed stride.** The engine torque table has 25 rows of 19 bytes.
- **The rev limit is a separate int** (`24 de a7 2e b7 13 00`). Without lowering it the car overshot
  the top speed (202 vs 187 km/h).
- The global `PHYSICSMENU.bff` holds menu copies of base cars' engine, chassis and suspension. The
  menu "Engine" row is **not** from the engine file but from the mrdf layout index.

- Repacking the `.vdfm` "crashed the game" only because the string section's pad byte (`0x1D`) was left
  stale; the in-place rewrite did too, once the table grew (Camaro). Fixed in `physics.write_vdfm` (doc 12).
- **Keep the donor's 0 rpm torque row** and set the bevel to 1:1 for an EV (otherwise the donor bevel shortens the gearing).
- **Car-named copies and loose files matter:** without loose `Vehicles\<car>\<car>.rcf` (livery list) etc. the car
  could not be selected and the Custom Event screen broke.

- **Wheels are drawn at the `.vhf` hub matrices, not at the physics wheel centres.** A new wheelbase/track
  must move those `MATRIX` offsets too (ams2kit `build.vhf_move_wheels`). Some donors' physics frame is offset
  from the visual frame (Camaro SS: physics wheel y 0.2185 vs vhf hub y 0.35).
- **Cockpit properties (`<car>_Cockpit.bin`) are looked up in the car's own folder.** Without a copy there
  the car drives but the cockpit/bonnet/helmet cameras are missing (cycling stops after the bumper cam); with
  a plain copy of the donor's file the game crashes on load: the .bin names the
  cockpit model (`Camaro_SS_Cockpit.vhf`), also loaded from the car's folder; missing -> null model -> crash.
  Fix: `cockpit.retarget_cockpit_bin` (see doc 10).
- **One livery image per donor livery id:** the Camaro has 20 liveries (51-70); missing ids show white boxes.

## Meshes
- **Never write the car's meshes at the donor's paths.** Our paks stay mounted, so the real donor car then
  shows our body (seen in the Showroom: a blue "Camaro SS" with the BYD body). ams2kit writes them as
  `vehicles\<car>\<car>_<donor file>.meb` (re-keyed) and points the car's text `.vhf` at them.
- **The game falls back to the text `.vhf` when the car has no `.vhf.bml`** [proven]: dropping the car's `.bml`
  copies makes the edited text render file (mesh paths, wheel hubs) take effect; no BLMY writer is needed.
- **The X position key depends on the file name.** Renaming a `.meb` without re-keying gives garbage geometry.
- Our meshes at donor paths also change the donor car's look while our pak is loaded.

## GUI
- Car-select images work from the car pak or loose files; **the manufacturer logo only works as a
  loose file**; **text tables only from the base boot pak.**
- The engine label list has no "Electric".

## Tooling and environment
- The scratch path was too long for some Win32 tools; work in a short path (e.g. `C:\ams2work`).
- PCarsTools needs .NET 6, so set `DOTNET_ROLL_FORWARD=Major`.
- `Program Files (x86)` parentheses break some `.bat` files; work from a short path without parentheses.
- **Python string escapes in Windows paths:** `"\b"` and `"\v"` silently became control characters
  several times (`"text\vehicledetails.tdb"`, `"\byd_ev_"`). Use raw strings or `\\`.
- Background game launches from a tool shell die with the shell; use `Start-Process`.
- Steam's custom-arguments prompt: use `steam_appid.txt`.
- The game set up for VR: test with `-novr -windowed`, then restore the user's graphics config.
