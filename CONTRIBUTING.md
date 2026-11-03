# Contributing to ams2kit

Thanks for helping. ams2kit is a small, work-in-progress fan project; issues with clear reproduction
steps (donor car, the Doctor output, the job log) are as valuable as code.

## Ground rules

- **No game content, ever.** Do not commit files extracted from Automobilista 2 (`.bff`, `.meb`, `.dds`,
  `.vhf`, `.bmt`, `.crd`, physics `*.bin` files, ...), car projects, builds, screenshots of builds with
  third-party models, or third-party car models. `.gitignore` blocks the common ones; check
  `git status` before you commit. Tests read game data from the local installation at run time.
- **No personal paths.** Use `ams2kit.game.find_game()` / `find_blender()`, `game.DATA_DIR`
  (`%LOCALAPPDATA%\ams2kit`) and project paths; tests use `tests/_paths.py`.
- **Dependencies:** Python standard library plus Pillow and numpy. Scripts in `ams2kit/blender/` run
  inside Blender and use only `bpy`, numpy and the mesh modules. Anything else needs a good reason and
  must stay optional.
- **Never modify base-game paks**, and keep every game-folder change recorded in the install receipt so
  uninstall stays exact.
- Match the existing style: compact functions, docstrings that say *why*, comments for game behaviour
  that was found by experiment. Format findings go into the matching `docs/NN-*.md` with a
  **[proven]** / **[file]** / **[guess]** tag. Keep the docs at file-format level: no executable
  addresses, disassembly or patching details.

## Development setup

```powershell
py -3 -m pip install --user -r requirements.txt
python -m ams2kit                 # UI
python -m unittest discover -s tests          # from the repository root
```

## Tests

Most tests need data that cannot be in the repository, and skip when it is missing:

| Needs | Tests | Set with |
|---|---|---|
| AMS2 installed | pak decryption, cockpit `.bin`, donor `.blend` round trip (also needs Blender) | auto-detected, or `AMS2KIT_GAME=<game folder>` |
| Extracted research files (`phys\PHYSICSPERSISTENT_extracted`, `research\shcb\physics_all`, ...) | ShCB/physics round trips, field dictionary, EV, tyres, car-named physics | `AMS2KIT_TEST_WORK=<workspace>` (default: the folder that contains the repository) |
| Example car projects (`kit_projects\...`) | some tyre and physics-name tests | same workspace |
| A car model `.blend` + fit config | `TestFitModel` | `AMS2KIT_TEST_MODEL=<model.blend>`, `AMS2KIT_TEST_FIT=<fit.json>` |
| Blender | `test_blend_bridge` | auto-detected, or `AMS2KIT_BLENDER=<blender.exe>` |

The `test_shcb` all-cars round trip builds its cache from the game paks on first run (a few minutes).
Pure-logic tests (hashes, EV maths, tyre size parsing, culling spheres) always run.

Please run the full suite before a pull request and mention which tests were skipped on your machine.

## Pull requests

- One topic per pull request; describe what you tested in game (donor, track, result).
- Do not commit generated caches, logs, or `__pycache__`.
- New CLI commands go in `ams2kit/__main__.py` and the README's CLI table; new UI actions go through
  `ams2kit/actions.py` so the CLI and UI share them.
- Known issues and cleanup ideas are listed in [REVIEW.md](REVIEW.md); pick one if you want a start.

## License

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE).
Code derived from PCarsTools keeps its own terms ([THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)).
