# Adding a car, step by step

## In the UI

1. **Start the UI:** double-click `ams2kit.bat`, or run `python -m ams2kit`. A browser tab opens at
   `http://127.0.0.1:8765/` (the server only listens on your own machine).
2. **Setup:** check that the game folder and Blender were detected (set them by hand if not).
   Optionally enable `steam_appid.txt`, which lets the automated tests start the game without Steam's
   launch-options prompt.
3. **New car:** pick a donor close to your car (size, drivetrain, class), then enter an internal name
   (letters, digits, `_`, e.g. `My_Car`), a display name, manufacturer and class. ams2kit creates the
   project and unpacks the donor into it.
4. **Specs:** power, torque, rev limit (or EV settings), gears, mass, wheelbase, tracks, tyre size and
   menu stats. Fields left at 0 keep the donor's value.
5. **Model (optional):** click *Export donor .blend*. Open `<project>\model\donor_<car>.blend` in Blender,
   read the `AMS2KIT_README` text block, replace the donor's body with yours and save as
   `<project>\model\car.blend`. Use exactly that name: the file is always `car.blend`, whatever your car
   is called. Then *Build meshes*. Skip this step to keep the donor's body.
   Details: [04-meshes-and-render.md](04-meshes-and-render.md).
6. **Physics (optional):** the Physics page lists every field of the donor's physics files; override any
   of them ([14-physics-fields.md](14-physics-fields.md)).
7. **Art:** pick livery colours, add a logo PNG, render the car-select images.
   **Sound (optional):** use another car's engine sound, or replace single samples of it with your own WAVs
   ([16-sound.md](16-sound.md)).
8. **Build**, then **Check** (the Doctor; fix anything it reports), then **Install**.
   **Share** makes `build\share\<Name>.zip` for friends: they extract it and run `install.bat`.
9. **Test:** start one Custom Race with your car by hand once (so the game remembers it), then run
   *Test* to let the AI drive and collect telemetry. Or start the game normally and find your car in its
   class.

## On the command line

```powershell
python -m ams2kit donors gt3                         # find a donor
python -m ams2kit new "C:\cars\My_Car" My_Car BMW_M4_GT3
# edit C:\cars\My_Car\car.toml (or use the UI's Specs page)
python -m ams2kit export-blend "C:\cars\My_Car"      # optional: donor .blend for your model
python -m ams2kit build-meshes "C:\cars\My_Car"      # after saving model\car.blend
python -m ams2kit art     "C:\cars\My_Car"
python -m ams2kit sounds v8                          # optional: [sound] kit = "<car>" in car.toml
python -m ams2kit sound-extract "C:\cars\My_Car"     # optional: kit samples -> sound\original\
python -m ams2kit build   "C:\cars\My_Car"
python -m ams2kit doctor  "C:\cars\My_Car"
python -m ams2kit install "C:\cars\My_Car"
python -m ams2kit test    "C:\cars\My_Car" 120       # AI drives for 120 s
```

All commands: [cli.md](cli.md).

## Project layout

```
<project>/
  car.toml          everything you set (the UI edits this)
  donor/            unpacked donor (plain paks, physics, crd, driveline record)
  model/            donor_<car>.blend (exported) and car.blend (yours)
  art/              logo + rendered car-select images
  sound/            extracted kit samples (original/) and your replacements (replace/<bank>/)
  build/            generated physics, meshes, paks, mod files, test results
```

Settings, caches, install receipts and the registry backup live in `%LOCALAPPDATA%\ams2kit\`.
Projects go to `Documents\ams2kit projects\` unless you choose another folder in Setup.
