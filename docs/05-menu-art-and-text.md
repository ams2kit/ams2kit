# 05: Menu art, logo, stats and text

## Car-select / livery images [proven]

- Path: `gui\vehicleimages\vehicleimages_<crd Name>\<crd Name>_livery_<livery id>.dds`
  For us that's `vehicleimages_byd_seal\byd_seal_livery_51..59.dds`.
- Format: 2048×768, DXT5/BC3, 12 mips, the car cut out on a transparent background, front-right
  three-quarter view. The base cars' images are in `GUIVEHICLEIMAGES.bff`.
- The game reads them from our car pak and from loose files under `<game>\GUI\vehicleimages\...`.
  The installer writes both.
- There is also a per-livery override string that we haven't used.

How we made them (`gui_art\work\`):
- Rendered the source model in Blender, headless, with a transparent background
  (`render_seal.py`), one paint colour per livery.
- `build_gui_art.py` frames the renders like the donor's images and writes the DDS files, reusing
  the donor's 128-byte header and Pillow's DXT5 encoder.
- A clean render cut-out looks more like the game's own images than a background-removed photo does.

## Manufacturer logo [proven]

- Path: `gui\manufacturerlogos\<VehicleManufacturer lowercase, spaces removed>.dds`.
  For example "Aston Martin Racing" maps to `astonmartinracing.dds`.
- Format: 200×100, uncompressed A8R8G8B8, 8 mips. The base logos are in `GUIMANUFACTURERLOGOS.bff`.
- **The logo is read only as a loose file**: `<game>\GUI\manufacturerlogos\byd.dds`. A copy inside
  the car pak showed a white placeholder box. The installer writes the loose file.
- The BYD wordmark came from Wikimedia Commons (public-domain SVG); sources are in `gui_art\SOURCES.md`.

## Menu stats

- The Select Vehicle screen shows power, torque, weight, wheelbase, drivetrain, gears and
  displacement from the car's **`.mrdf`** (offsets in doc 03). Shift type and electronics come from
  the physics/driveline.
- The **"Engine" row** shows a *layout label*: mrdf `0x64` indexes the engine-label strings in
  `text\vehicledetails.tdb`. We mapped the indices from real cars:

| Index | Label | Example car |
|---|---|---|
| 0 | gas turbine | Lotus 56 |
| 1 / 2 / 3 / 4 | V6 / V8 / V10 / V12 | Acura NSX / Aston Martin Vantage GT3 / Audi R8 / Veneno |
| 5 / 6 / 7 | Straight 4 / 5 / 6 | Alpine A110 / Audi quattro S1 / BMW M4 |
| 8 / 9 | Rotary 2 / Rotary 3 | — / Mazda MX-5 Radbul |
| 10 / 11 | Flat 4 / Flat 6 | Toyota 86 / Porsche 911 |
| 12 / 13 | W16 / W12 | *unused by any car* |
| 14 / 15 | Single / Twin cylinder | karts |
| 16 / 17 / 18 | Flat 8 / mixed / V4 hybrid | Porsche 908/03 / Ford GT40 / Porsche 919 |
| ≥ 19 | falls back to a stale value ("4.19L") | |

  There is **no electric label**. The BYD currently uses 18 ("V4").

## Text tables (`text\*.tdb`)

- Text tables are in `BOOTFLOW.bff`: `text\vehicledetails.tdb`, `game.tdb`, and others.
- Format: UTF-16 strings, each preceded by a hash and a u32 length; there is one copy per language.
- They are loaded at boot, and **neither loose files nor car-pak copies override them** [proven].
- `gui_art\text\vehicledetails.tdb` holds a ready patch: the unused label 13 "W12" becomes "EV ",
  the same length, in 8 languages. Using it would mean rebuilding the **base** `BOOTFLOW.bff`
  unencrypted, re-registering it, and redoing that after every game update. Not done; it needs a
  decision.
