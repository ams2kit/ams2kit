# 06: Testing without clicking through menus

## Hidden command-line switches [proven]

Pass them as `-name` or `-name value`.

**Useful ones:**

| Switch | Effect |
|---|---|
| `-runTest 0` | Runs the internal Scribe script `Scribe_Internal/Scripts/Tests/CustomRace.script.object` (in `Scripts\INTERNALSCRIPT.bff`). It **starts a Custom Race straight away with the profile's last car and track, the AI drives the player car, and the game exits to desktop at session end.** `1` / `2` run multiplayer browser/create tests. |
| `-novr` | Ignore VR even if a headset is configured. |
| `-windowed` / `-borderless` / `-windowsize` | Window mode. `graphicsconfigdx11.xml` `windowed="1"` also works. |
| `-doNotPauseOnFocusLoss` | Keep running while another window has focus. |
| `-enableSharedMem` | Turn on the Project CARS 2 style shared-memory telemetry (`$pcars2$`). |
| `-pcars2udp` | UDP telemetry. |
| `-noMsgBox` | Suppress message boxes. |
| `-AudioNULL` | No audio. |

**Others:** `devcameras`, `forceSessionSpecificMeshesVisible`, `showLiveryIDs`, `looseloadtext`,
`skipcrowds`, `disableLogging`, `FpsCap`, `forceLevel`, `sessionprefix`, `log`, `configDetail`. Most
are untested.

Internal autotest scripts also exist (`scribe_internal\scripts\autotest\...`: `perftest`,
`alltracksload`, `allvehiclesload`). They pick a car and track by name ("BMW Z4 GT3", "Brands
Hatch GP") with `auto_ai` / `auto_laps` overrides, but we found no switch that launches them.

**To use `-runTest 0`:** set up a Custom Race once by hand (car, track, opponents) and start it; the
profile remembers the choice. From then on every `-runTest 0` launch drops straight onto the track.

## Launching

- Launch **detached** (PowerShell `Start-Process`). A process started in the background from a tool
  shell dies when that shell call ends.
- Steam asks "allow running with custom arguments?" on every launch with arguments. Putting
  `steam_appid.txt` (content `1066890`) next to the exe stops that, because the exe then doesn't
  restart through Steam. Steam must still be running.
- A VR user's config must be restored afterwards (`graphicsconfigdx11.xml`, keep a backup copy).

## Telemetry: `telemetry.py` [proven]

The shared memory follows the Project CARS 2 `SharedMemory.h` layout (version 14,
`ParticipantInfo` = 100 bytes). Verified offsets:
- 6444 car name, 6508 class, 6576 track, 6640 variation;
- 6848 speed (m/s), 6852 rpm, 6856 max rpm, 6864 throttle;
- 6876 gear, 6880 gear count;
- 6956–6964 local acceleration (z = longitudinal).

```
python telemetry.py probe                  one sample, all fields
python telemetry.py log run.csv 120        20 Hz CSV
python telemetry.py summary run.csv        top speed, max rpm, gears, 0-100, accel per speed band
```

The AI run has no standing start, so 0-100 shows as unavailable. Use the 0–50 / 50–100 km/h
full-throttle acceleration instead (about 0.75 g ≈ 3.8 s for 0–100).

**Proving a physics file is used:** build a deliberately extreme variant (e.g. `BYD_MASS=6000`) and
compare acceleration per speed band.

## Screenshots and input: `game_harness.py` [proven]

```
python game_harness.py status | shot out.png | click x y | key <name> [ms]
```

- It finds the game window and grabs the client area with Pillow.
- Clicks use 1920×1080 frame coordinates.
- Keys are sent as **scan codes** through `SendInput`, which the game reads.
- **Menu coordinates** (1080p): Single Race (500, 360); on Custom Event, the vehicle panel (640, 380)
  opens Select Vehicle.
- During an AI-driven `runTest` the default view is a bumper camera. The `C` key did not change it;
  bindings live in the encrypted `controllersettings.sav`.

## Test scripts

| Script | Does |
|---|---|
| `run_test.py <name> [--seconds N] [--shots] [--no-build]` | kill game → build physics, mod files, paks → install → launch `-runTest 0` → wait until shared memory shows our car moving → log telemetry → kill → report `RESULT: ok / crash` and the telemetry summary. Builder env vars pass through (`BYD_MASS`, `BYD_NO_MODEL`, `BYD_ENGINE_TYPE`, ...). |
| `menu_check.py <name>` | Launch to the menus, screenshot Custom Event and Select Vehicle, crop the stats table. |

One automated run takes about 3–4 minutes. Crash dumps land in `%LOCALAPPDATA%\Temp\AMS2AVX*.dmp`.
