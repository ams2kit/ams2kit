# Code review notes (release preparation, 2026-11-03)

What was fixed is listed in [CHANGELOG.md](CHANGELOG.md) under "Release preparation". This file lists
what was found but deliberately **not** changed (too big, behaviour-changing, or owned by work in
progress). Good first issues are marked *(small)*.

## Publication / legal (decide before the first public push)

1. **PCarsTools-derived files** (`BPakFileEncryption.cs`, copied; `pak_decrypt_twin.py` and `pak_tool.py`,
   ported) are credited in `THIRD_PARTY_NOTICES.md`. Confirm PCarsTools' license is compatible with
   redistribution, and decide whether you are comfortable shipping the decryption keys inside
   `BPakFileEncryption.cs`. Alternative: have users point ams2kit at their own PCarsTools checkout.
2. **Reverse-engineering content** (done): doc 07 is not published, and exe addresses, function names,
   memory layouts and crash addresses were removed from docs 02-14, from code comments and docstrings
   and from the physics field descriptions. The crash-dump tool `read_minidump.py` was deleted.
   Confidence values (`proven`/`strong`/... and `ev.BOOST_KEYS`' "loader") are unchanged.
3. **`ams2kit/fields_survey.py`** is generated from the base-game physics files (key hashes, type,
   file counts, one example value per key). It is facts about the format rather than game assets, but
   it is derived data; the generator is not in the repository.
4. The docs mention the BYD Seal and VW Jetta GLI test builds and their (third-party) source models by
   description only; no model files are included.
5. The direct launcher (`launcher.py`, `launcher_native.py`, `native/`, `launch_hook.js`, `presets/`,
   `docs/15`, the `launch` command) was moved to a separate project during this review.

## Bugs / robustness (not fixed)

6. `testing.py` and `telemetry.py` are still used by the in-game test; check nothing in the separate
   launcher project relied on ams2kit internals that may change.
7. `testing.launch()` builds a PowerShell command line with the game path inside single quotes: a game
   folder containing `'` breaks it. Use `subprocess.Popen([...], creationflags=DETACHED_PROCESS)` or
   escape `'` as `''`. *(small)*
8. `testing.kill()` force-kills any running `AMS2AVX.exe` without asking; the UI should warn before a
   Test/Menu run if the game is open.
9. `testing.menu_check()` clicks fixed 1920x1080 coordinates after fixed sleeps; it breaks on other
   window sizes, languages or slower machines.
10. `actions.open_path(..., with_app="blender")` runs `str(None)` when Blender is not found; raise a clear
    error instead. *(small)*
11. File handles opened without `with` (`testing.summarise/performance`, `telemetry.summary`,
    `blend_bridge.fit_model_into_donor` texels, `shcb` main). Harmless on CPython but
    noisy under `-W error`. *(small)*
12. `telemetry.log()` prints the car/track line to stdout from library code; route it through the
    caller's `log`. *(small)*
13. The UI server has no request size limit on `/api/upload` and runs one background job at a time with
    no cancel. The new Origin/Host check blocks other web pages, but any local process can still use
    the API (by design, as for most local dev servers).
14. `game.find_game()` only looks at Steam libraries; no override by environment variable (the Setup
    page covers it).
15. `doctor.py` has two `except Exception: pass` blocks that can hide real check failures; report them
    as warnings instead.

## Dead or unused code (kept on purpose)

16. Unreferenced helpers kept as documented API: `ev.wheel_force`, `physics.open_physics`,
    `mesh.meb_read.pos_key`. Remove or cover with tests. *(small)*
17. `mesh.texels.project_texels` (texture-checked texels for a whole project) is not wired into the UI or
    `actions.py` yet; the fit tool takes texels as a parameter. Wire it in or mark it experimental.
18. `actions.job("export_blend")` imports `buildphys` without using it. *(small)*
19. Developer entry points (`pak_extract`, `pak_decrypt_twin`, `telemetry`, `game_harness`,
    `mesh/meb_read.py`, `mesh/meb_write.py`, `shcb`) have their own `__main__` blocks
    with ad-hoc argument parsing. Fine for now; consider moving them under `python -m ams2kit dev ...`.
    `meb_write.py --obj` still defaults the material path to `vehicles\BYD_Seal\`.

## Structure / packaging ideas

20. No `pyproject.toml`; the tool runs from the folder. A `pyproject.toml` with a console script would
    allow `pipx install`. Note that `BPakFileEncryption.cs` and `ui/static/*` must be included as package data.
21. Tests depend on data outside the repository (extracted game files, example car projects). A small
    synthetic fixture set (hand-made ShCB/meb/pak samples, no game data) would let CI run more than the
    pure-logic tests.
22. Windows-only by design (`winreg`, `ctypes.WinDLL`, `os.startfile`, `taskkill`); `game.py` imports
    `winreg` at module level, so even the pure tests cannot import it elsewhere.
23. Large modules (`fields.py`, `blend_bridge.py`, `blender/fit_model.py`, `physics.py`) mix data, logic
    and docs; splitting them would help contributors.
