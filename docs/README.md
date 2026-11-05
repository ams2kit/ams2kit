# ams2kit documentation

## User guides

| File | Covers |
|---|---|
| [workflow.md](workflow.md) | Adding a car step by step (UI and CLI), project layout |
| [cli.md](cli.md) | Every command of `python -m ams2kit` |
| [safety.md](safety.md) | What ams2kit changes in the game folder, backups, uninstalling |
| [known-limitations.md](known-limitations.md) | Work in progress and known limitations |

## Research notes: adding a new car to Automobilista 2

These notes record what we learned while adding a **BYD Seal AWD** to Automobilista 2 (AMS2 v1.6.9.96)
as the first test case for ams2kit. AMS2 has no official car-modding SDK, so we worked the file formats
out ourselves, starting from the open-source PCarsTools.

These are working notes for future user tutorials, not a tutorial yet. Every claim is tagged where it matters:
**[proven]** = verified in game, **[file]** = verified against files only, **[guess]** = unverified.

> **About the script names in these notes.** The research was done with one-off scripts in the author's
> workspace (`scripts\`, `meb\`, `research\`, e.g. `build_byd_paks.py`, `install_byd.py`, `run_test.py`).
> Those scripts are **not part of this repository**; everything reusable from them now lives in the
> `ams2kit` package (see the top-level [README](../README.md) and [DESIGN.md](../DESIGN.md)). Paths such
> as `research\...` refer to that workspace.

### Research documents

| File | Covers |
|---|---|
| [01-pak-files.md](01-pak-files.md) | `.bff` pak format, encryption, CRC, `PakDirInfo.dat` registry, pak tools |
| [02-registering-a-car.md](02-registering-a-car.md) | Mod loader, `.crd` vehicle definition, vehicle list, driveline, car classes |
| [03-physics.md](03-physics.md) | `.vdfm` / engine / gearbox / chassis / suspension / stats files and how to edit them |
| [04-meshes-and-render.md](04-meshes-and-render.md) | `.meb` meshes, `.vhf` render file, swapping a new body onto a donor car, the donor `.blend` round trip |
| [05-menu-art-and-text.md](05-menu-art-and-text.md) | Car-select images, manufacturer logo, menu stats, text tables |
| [06-testing-automation.md](06-testing-automation.md) | Command-line switches, test launch onto a track, telemetry, screenshots, test scripts |
| [08-pitfalls.md](08-pitfalls.md) | Every trap we fell into, in one list |
| [09-shcb-format.md](09-shcb-format.md) | The ShCB keyed binary format of the physics files (parse / serialize) |
| [10-cockpit-bin.md](10-cockpit-bin.md) | The cockpit properties `.bin` file and retargeting it to a new car |
| [11-electric-drive.md](11-electric-drive.md) | No native EV powertrain: how an electric car is emulated with the ICE model (torque table, single speed, regen) |
| [12-physics-names.md](12-physics-names.md) | Why vdfm renames crashed (section pad check), car-named physics (`independent` mode) |
| [13-tyres.md](13-tyres.md) | Where the tyre size lives (vdfm wheel block), tyre sets, resizing the skinned tyre meshes |
| [14-physics-fields.md](14-physics-fields.md) | Key hash cracked (lookup2 of the upper-case rF-style name); field dictionary for every physics file; BYD calibration fields |
| [16-sound.md](16-sound.md) | The `.csdbin` sound setup, FMOD bank and FSB5 layout, FADPCM, sound kits and replacing samples |

### The approach that works: clone a donor car

A new car is built as a **clone of an existing car (the "donor")**, here the Lamborghini Veneno:

1. Decrypt the donor's three paks (`<Car>.bff`, `<Car>_Cockpit.bff`, `<Car>_Livery.bff`) into
   unencrypted copies. The game accepts unencrypted paks **[proven]**.
2. Write new paks (`BYD_Seal*.bff`). They keep every donor file at its original path and add:
   - copies of the files the game finds through the car's name (`byd_seal.*`);
   - a new `byd_seal.vdfm` that points at our own engine and gearbox;
   - the edited chassis and suspension, which **replace the donor's files inside our pak**;
   - the new body meshes, written under the donor's mesh names;
   - menu images.
3. Register the new paks in `Pakfiles\PakDirInfo.dat`. Unregistered paks are ignored.
4. Add a mod folder (`UserData\Mods\BYD_Seal\`) with a vehicle list that points at our `.crd`.
5. Write a few loose files (manufacturer logo, menu images, physics copies).

The original research scripts did this in the order below; ams2kit's `build`, `install` and `test`
commands now do the same for any project.

```
build_byd_physics.py   donor physics  -> edited engine/gearbox/chassis/suspension
build_byd_modfiles.py  donor .crd     -> mod folder + byd_seal.crd
build_byd_paks.py      donor paks     -> byd_build\paks\BYD_Seal*.bff
install_byd.py install|uninstall      -> copies into the game, registers the paks, writes loose files
run_test.py <name>                    -> all of the above, then launches straight onto a track and measures
```

### Status of the BYD Seal demo (2026-11-02)

**Done:**
- Listed in Street Cars with its own image and BYD logo.
- Drives as a single-speed EV: 390 kW, 670 Nm, 2,185 kg, 2.92 m wheelbase, about 187 km/h limit.
- Real-size BYD body.
- Automated testing; see doc 06.

**Still open:**
- Veneno interior and V12 sound.
- The menu's "Engine" row has no EV label.
- No custom class.
- Collision shape is still the Veneno's.
- Rear tyres sit about 7.5 cm wide of the body.
