# CLI reference

`python -m ams2kit <command> ...` (run from the repository folder). With no command it opens the UI.

| Command | What it does |
|---|---|
| `ui [--port N] [--no-browser]` | Local web UI (default port 8765; the next free port is used if taken). |
| `donors [filter]` | List installed cars usable as donors (internal name, class, display name). |
| `new <dir> <Name> <Donor>` | Create a project folder and unpack the donor into it. |
| `export-blend <project>` | Write `model\donor_<car>.blend` for modelling. Needs Blender. |
| `build-meshes <project>` | Convert `model\car.blend` into game meshes. Needs Blender. |
| `render <project>` | Render car-select images from the `.blend`. Needs Blender. |
| `art <project>` | Build menu art (car-select images, logo) as game DDS files. |
| `build <project>` | Build the car's paks and mod files into `<project>\build\`. |
| `doctor <project>` | Validate a build (registry, CRCs, names, physics layout, tyres...). |
| `install <project>` | Copy the build into the game and register its paks (with a receipt). |
| `uninstall <project>` | Remove exactly the files the install wrote and unregister the paks. |
| `share <project>` | Zip the last build with an installer for friends: `build\share\<Name>.zip` ([safety](safety.md#sharing-a-car)). |
| `test <project> [seconds]` | Start the game, let the AI drive, log telemetry, take screenshots. |
| `menu <project>` | Start the game and screenshot the car-select menus. |
| `tyres <project> [size [rear]] [--race]` | Donor/Specs tyre sizes and the closest base tyre sets. |
| `sounds [filter] [--by-size]` | List the cars whose engine sound a car can use (`[sound] kit`), with how many recordings each has (`--by-size`: fewest first). |
| `sound-extract <project>` | Decode the kit's engine banks to `sound\original\` as WAVs ([16](16-sound.md)). |
| `dump <physics file>` | Print a ShCB physics file (`.edfbin`, `.cdfbin`, ...) as text. |

Commands print a log and finish with a JSON result.

Developer entry points with their own usage in the module docstring:
`python -m ams2kit.pak_extract`, `python -m ams2kit.telemetry`, `python -m ams2kit.game_harness`,
`python ams2kit/mesh/meb_read.py`, `python ams2kit/mesh/meb_write.py`.

## Environment variables

| Variable | Effect |
|---|---|
| `AMS2KIT_BLENDER` | `blender.exe` to use when none is set in Setup. |
| `AMS2KIT_VGMSTREAM` | `vgmstream-cli` to decode Vorbis sound samples when none is set in Setup. |
| `AMS2KIT_INDEPENDENT`, `AMS2KIT_RENAME_COLLISION` | Force car-named physics / collision for one build ([12](12-physics-names.md)). |
| `AMS2KIT_NO_COCKPIT_BIN` | Build without a cockpit properties file ([10](10-cockpit-bin.md)). |
| `AMS2KIT_GAME`, `AMS2KIT_TEST_WORK`, `AMS2KIT_TEST_MODEL`, `AMS2KIT_TEST_FIT` | Test data locations ([CONTRIBUTING](../CONTRIBUTING.md)). |
