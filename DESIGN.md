# ams2kit: design

ams2kit is a user-friendly toolkit for adding new cars to Automobilista 2 by cloning a donor car.
The background research is in [`docs/`](docs/README.md); read those first.

## User workflow (what the UI walks through)
1. **Setup:** detect the game folder and Blender.
2. **New car:** pick a **donor** from the list of installed cars, then enter a name, manufacturer
   and class. This creates a project folder with `car.toml`.
3. **Donor export:** `ams2kit` writes `<project>\model\donor_<car>.blend`. It holds every donor
   mesh, organised so the user can see what to replace, with wheel markers placed at the physics
   wheel centres.
4. The user models or imports their car **in that .blend** and saves it as `<project>\model\car.blend`
   (or keeps editing the same file).
5. **Specs:** power, torque, rev limit or EV, gears, mass, wheelbase/track, CG, top speed, menu stats.
6. **Art:** livery colours, logo file, and car-select images rendered from the .blend.
   **Sound:** pick a sound kit (any car's engine sound) and optionally replace its samples.
7. **Build, then Doctor, then Install, then Test** (automated in-game run + menu screenshots).

## Package layout (`ams2kit/`)
| Module | Area | Purpose |
|---|---|---|
| `paks.py` (+ `pak_tool.py`, `pak_extract.py`, `pak_decrypt_twin.py`, `BPakFileEncryption.cs`) | core | read encrypted/plain paks, write plain paks (decryption ported from PCarsTools, see THIRD_PARTY_NOTICES.md) |
| `pakdirinfo.py` | core | `PakDirInfo.dat` (the game's pak registry) |
| `game.py` | core | find install/Blender, settings (`%LOCALAPPDATA%\ams2kit\config.json`), list cars (donor catalog) |
| `project.py` | core | `car.toml` load/save, project paths |
| `donor.py` | core | unpack a donor into the project (`<project>\donor\`) |
| `shcb.py` | physics | generic parse/serialize/dump of ShCB keyed binaries (docs/09) |
| `physics.py` | physics | typed accessors on top of shcb: engine/gearbox/chassis/suspension/vdfm/mrdf |
| `buildphys.py`, `ev.py` | physics | Specs → physics files; electric drive emulation (docs/11, docs/12) |
| `fields.py` (+ generated `fields_survey.py`) | physics | physics field dictionary and overrides (docs/14) |
| `cockpit.py` | core | cockpit properties `.bin` retarget (docs/10) |
| `mesh/meb_read.py`, `mesh/meb_write.py` | mesh | .meb format |
| `mesh/blend_bridge.py` (+ `donor_layout.py`, `vhf_nodes.py`, `meshweld.py`, `texels.py`) + `blender/*.py` | mesh | donor → .blend export, model fit, .blend → .meb build (docs/04) |
| `build.py`, `crd.py`, `art.py`, `liveries.py` | core | project → paks + mod files, menu art, plain-paint liveries |
| `sound.py` | core | sound kits (another car's csdbin), FMOD bank/FSB5 read, FADPCM decode, sample replacement (docs/16) |
| `tyres.py` | core | tyre size: vdfm wheel block, base tyre sets, resized skinned tyre meshes (docs/13) |
| `install.py`, `doctor.py`, `testing.py` (+ `telemetry.py`, `game_harness.py`) | core | install/validate/test |
| `ui/` | core | local web UI (stdlib http server + a Vue page built from `frontend/` with Vite into `ui/static/`), `python -m ams2kit ui` |
| `__main__.py` | core | CLI (see README) |

Rules:
- Use only the Python standard library plus Pillow and numpy.
- Never modify base-game paks. Back up everything before touching game files.
- Scripts that run inside Blender (`blender/`) use only `bpy` plus the mesh modules (add the package
  to `sys.path`). Blender runs headless: `blender.exe --factory-startup --disable-autoexec -b ...`; the
  executable comes from `game.find_blender()` (Setup page, `%AMS2KIT_BLENDER%`, newest
  `Program Files\Blender Foundation\Blender *`, then `PATH`).
- No personal paths in code: user data goes to `%LOCALAPPDATA%\ams2kit\`, projects to the folder set in
  Setup (default `Documents\ams2kit projects`).
