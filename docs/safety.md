# Safety: what ams2kit changes in your game folder

ams2kit **never modifies the base game's paks**. Donor files are read from them read-only.

## Install

Install writes the following, and records every file in a receipt
(`%LOCALAPPDATA%\ams2kit\installs\<Name>.json`):

- your car's paks: `Pakfiles\Vehicles\<Name>*.bff`;
- entries for those paks in `Pakfiles\PakDirInfo.dat` (the game's pak registry). The original file is
  backed up **once**, before the first change, to `%LOCALAPPDATA%\ams2kit\backup\PakDirInfo.dat`;
- a mod folder `UserData\Mods\<Name>\` (vehicle list, `.crd`);
- a few loose files for your car under `Vehicles\<car>\` and `GUI\` (menu art, logo).

It refuses to overwrite any existing file it did not write itself.

## Other changes (only when you use the feature)

- *Setup → steam_appid.txt*: creates/removes `steam_appid.txt` next to `AMS2AVX.exe`.
- *Test / Menu*: start the game with extra command-line switches and **force-close a running
  `AMS2AVX.exe`** first (unsaved progress in a running game is lost).
- Game updates can rewrite `PakDirInfo.dat`; reinstall your car after an update.

Back up your game profile (`Documents\Automobilista 2\`) before testing a new car, as with any mod.
Don't use modified cars in online races.

## Uninstall a car

`python -m ams2kit uninstall <project>` (or the UI's Uninstall button). It deletes exactly the files in
the receipt, removes the registry entries and deletes the receipt.

## Remove ams2kit completely

1. Uninstall every car (the UI's Setup page lists installed cars).
2. If anything looks wrong, restore `%LOCALAPPDATA%\ams2kit\backup\PakDirInfo.dat` into
   `<game>\Pakfiles\`, or let Steam *Verify integrity of game files*.
3. Delete `steam_appid.txt` from the game folder if you enabled it.
4. Delete `%LOCALAPPDATA%\ams2kit\`, your projects folder and the ams2kit folder.

## The local UI

The UI server listens on `127.0.0.1` only and refuses requests from other web pages. It can read and
write files in your projects folder and start Blender and the game, so don't expose it to a network.
