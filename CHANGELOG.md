# Changelog

## Status (2026-11-03)

Work in progress, not yet released. Works end to end for the donors it was developed with
(Lamborghini Veneno, Chevrolet Camaro SS, Mitsubishi Lancer R, VW Virtus GTS); see the README's
"Work in progress / known limitations".

## 0.1.0 (unreleased)

First public version.

- Donor catalog from the installed game; new car projects (`car.toml`) cloned from a donor.
- Pak reading (encrypted base-game paks, read-only) and writing (plain paks); `PakDirInfo.dat` registry.
- Donor `.blend` export and `.blend` → `.meb` build (Blender 5.x, headless), with derived LODs, damage
  and cockpit copies; model fit tool (`fit_model_into_donor`) with texture-checked texels.
- Physics: ShCB parser/serializer, typed accessors, Specs → physics (ICE and emulated EV), car-named
  ("independent") physics files, physics field dictionary and per-project overrides.
- Tyre sizes (physics wheel block, base tyre sets, resized visual tyres).
- Plain-paint liveries, manufacturer logo, car-select images.
- Doctor checks; install/uninstall with receipts and a registry backup.
- Automated in-game test (AI drive, telemetry, screenshots, crash detection) and menu screenshots.
- Local web UI and CLI.
- Physics page "Curves" tab: drag-to-edit torque curve (with derived power, rev-limit handle and the
  donor's curve for reference) and gearing chart (rpm vs road speed, drag a gear to change its ratio).
  Both edit the Specs values (`torque_curve`, `rev_limit`, `gears`, `final_drive`). Charts use
  vue-chartjs (Chart.js) with chartjs-plugin-dragdata.

### Sound

- Sound kits: a car can use any installed car's engine sound (`[sound] kit`, Sound step, `sounds`).
- Sample replacement (experimental): `sound-extract` decodes the kit's engine banks to WAVs (FADPCM
  natively, Vorbis through an optional `vgmstream-cli`); WAVs in `sound/replace/<bank>/` are packed into
  a copy of the bank as PCM and installed under `Audio\AMS2KIT\<car>\` (docs/16).
- Doctor checks the csdbin's engine banks exist and warns about cars sharing a replaced bank.

### Release preparation

- Removed hard-coded personal paths: Blender is auto-detected (`game.find_blender()`: Setup,
  `%AMS2KIT_BLENDER%`, Program Files, `PATH`), the Oodle DLL comes from the detected game folder, and
  the tests find their data through `tests/_paths.py` (`AMS2KIT_GAME`, `AMS2KIT_TEST_WORK`,
  `AMS2KIT_TEST_MODEL`, `AMS2KIT_TEST_FIT`).
- The UI's mesh export/build now uses the Blender chosen in Setup (it was pinned to Blender 5.2).
- The local UI server refuses requests from other web pages (Origin check) and DNS-rebinding hosts
  (Host check).
- Removed dead code (`buildphys.ev_curve`) and unused imports.
- Removed reverse-engineering details (exe addresses, crash addresses, loader notes) from code comments,
  docstrings and physics field descriptions; removed the crash-dump analysis tool `read_minidump.py`.
- Research notes copied into `docs/` (file-format level; reverse-engineering internals left out), plus
  user guides (`docs/workflow.md`, `cli.md`, `safety.md`, `known-limitations.md`).
- README, CONTRIBUTING, REVIEW, requirements and `.gitignore` added.
- Licensed under MIT (`LICENSE`); PCarsTools-derived files listed in `THIRD_PARTY_NOTICES.md`.
- The direct launcher moved to a separate project.
