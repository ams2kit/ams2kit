# 12: Car-named physics files (car independence)

**Status:** the cause of the old crashes is found and fixed in ams2kit, with tests. Car-named
("independent") physics is the default for new projects (`[physics] independent = true`) and works in game.

## Summary

- **Both historical crashes had one cause: the game rejected our `.vdfm` file.** The names themselves were
  never the problem.
- A vdfm (like an mrdf or a cockpit `.bin`) is a serialized struct with a section table. Each entry stores the
  section's size **and its pad to 16 bytes**. The game rejects the whole file unless the sizes plus the pads add
  up exactly to the file length.
- Our writers updated the string-table size but not its pad byte (`0x1D`). So any rename that changed the
  table length **modulo 16** produced a file the game silently refused.
- With the file refused, the car has no engine, gearbox or tyre names, and the game crashes on the missing
  tyre set ("null tyre set"). There is no error message.
- This explains every historical result:

| Build | String table | Result |
|---|---|---|
| Camaro, donor names | 54 bytes (unchanged) | worked |
| Camaro, engine/gearbox `byd_seal` (in-place writer) | 54 → 63 bytes, pad left at 10: 63+10 ≠ 64 | **crashed** |
| Veneno, `byd_seal` or `byd_seal_engine`/`_gearbox` (in-place writer) | the writer never shrinks the recorded size (92), pad 4 still right | worked |
| Veneno, repacked by `physics.write_vdfm` | new length, old pad: invalid unless the length ≡ 92 (mod 16) | **crashed** |
| Any base-name rename (old `build_vdfm`) | length changed | **crashed** ("null tyre set") |

`tests/test_physnames.py::test_known_in_game_results` reproduces this table offline.

**After the fix, every part can be car-named except the tyres:**

- **Can be renamed:** chassis (`0x38`), engine (`0x48`), gearbox (`0x70`), suspension (`0x78`) and collision (`0x80`).
- **Must stay a base-game tyre set:** tyres (`0x88`). Keeping the donor's tyre set is legitimate: the Camaro SS
  itself uses `chevrolet_camaro_zl1`.

## The container layout rule [file + proven]

The file starts with `'Q'`, a section count and a header pad, then one 8-byte entry per section:
`u32 size, u8 kind, u8 pad`. The rule the game enforces:

```
offset = header pad + 0x10 + 8 * count
for each entry:  offset += size + pad          (pad = -size % 16)
valid = (offset == file length)
```

The vdfm header at `0x10` is therefore 4 entries, not "u32[8]":

| Entry | Size | Kind | Pad |
|---|---|---|---|
| `0x10` | `0x1c0` struct (or `0x1b8`, pad 8 = "flags 0x801") | 1 data | `0x14 >> 8` |
| `0x18` | string pool length | `0x30` | byte `0x1D` = `-len % 16` (the "?" column at `0x1C` in doc 09) |
| `0x20` | 8 × reloc count | `0x31` | 0 or 8 |
| `0x28` | 12 type table (`5fb528ef`, v`0x11`) | `0x50` | 4 |

- All 791 base vdfms, all 786 mrdfs and all 382 cockpit bins satisfy `pad == -size % 16`.
- A refused file gives no error message, only a car without physics.

ams2kit:
- `physics.serial_layout_ok(b)` implements this check.
- `physics.serial_fix_pads(b)` sets every pad.
- `physics.write_vdfm` calls both and raises `ValueError` if the result fails.
- `buildphys.write_vdfm_in_place` (old name kept) wraps `write_vdfm(..., new_id=True)`. Names of any
  length work.
- `cockpit.CockpitBin.to_bytes` writes the pads too.
- `doctor` fails a build whose vdfm doesn't pass the check, or whose tyres field differs from the donor's.

## What each vdfm name field points at

| File offset | Points at | Renamable |
|---|---|---|
| `0x30` | the vdfm's own name (replaced at load by the name it was loaded by) | n/a |
| `0x38` | `vehicles\physics\chassis\<name>.cdfbin` | yes |
| `0x48` | `vehicles\physics\engines\<name>.edfbin` | yes |
| `0x70` | `vehicles\physics\gearbox\<name>.gdfbin` | yes |
| `0x78` | `vehicles\physics\suspension\<name>.sdfbin` | yes |
| `0x80` | collision object `COLLISION_CONVEX_<name>`, file `collision\<name>.xml`, then `.joi.xml` | yes (see below) |
| `0x88` | the **tyre-set name** (from `TyresHD.xml`) | **no** |

All file parts are opened by path. There is no boot-time registry for chassis, suspension, engine, gearbox or
collision, so car-named files in our pak are enough.

### Tyres

- The tyre sets are loaded once at boot from `vehicles\physics\tyres\TyresHD.xml` (in `PHYSICSBOOTFLOW.bff`,
  a list of `<Item label="X.hdtbin">`). A set is found by its internal name, case-insensitively; for
  example, `camaro_zl1.hdtbin` holds the set `chevrolet_camaro_zl1`.
- An unknown name crashes the game. A mod can't add a tyre set without editing the boot pak, so **field
  `0x88` must name a base set**: the donor's or any other set from `TyresHD.xml` (ams2kit
  `[chassis] tyre_set`). The tyre *size* is not in the set (doc 13).

### Collision (`0x80`)

- The game looks up or creates the object `COLLISION_CONVEX_<field>` and loads `collision\<field>.xml` into
  it. The `.sys.xml` names the main object again (`ObjectNumber0="COLLISION_CONVEX_CAMARO_SS"`).
- Sub-shapes are named `COLLISION_CONVEX_<DONOR>_CHASSIS_LODA` and so on. They are matched after stripping
  the prefix, not keyed by the vdfm, so they keep the donor's names.
- `buildphys.retarget_collision` renames only the exact main-object token in `.xml` and `.sys.xml`.
- Collision is the least certain rename. That's why it's a separate switch.
- Keeping `0x80` on the donor name is already independent: our pak then holds byte-identical copies of the
  donor's collision files at the donor's paths, which change nothing for the donor car.

## ams2kit: independent mode

Set in `car.toml` (`[physics] independent = true`, `rename_collision = true`; both are the defaults for new
projects) or with `AMS2KIT_INDEPENDENT=1` (and `AMS2KIT_RENAME_COLLISION=1`) for one build.

What the build then does (`buildphys.build(project, independent=..., rename_collision=...)`):

- **vdfm:** `0x38`, `0x48`, `0x70` and `0x78` are set to the car key (`byd_seal`), plus `0x80` with
  `rename_collision`. Tyres, clutch and failures keep the donor's names. The file passes the layout check.
- **Car-named files:**
  - `vehicles\physics\chassis\byd_seal.cdfbin`
  - `suspension\byd_seal.sdfbin`
  - `engines\byd_seal.edfbin`
  - `gearbox\byd_seal.gdfbin`
  - with `rename_collision`, also `collision\byd_seal.xml/.joi.xml/.sys.xml` (main object
    `COLLISION_CONVEX_BYD_SEAL`)
- **Nothing at a donor path changes.** The pak still contains the donor's own files (it is a copy of the donor
  pak), byte-identical, so a stock donor car on the same track keeps its own engine, gearbox and weight.
- `names` in `build.json` gains `donor_base`, `donor_suspension`, `independent`, `collision` and `tyres`.
- `build.py` uses `donor_base` for its car-named base-physics copies. The clutch (`Road_800Nm`) and failures
  (`Generic_TCR`) are shared base files that we don't edit, so they stay as they are.

Tests: `python -m unittest tests.test_physnames -v`. They cover:
- the layout check on every base vdfm, mrdf and cockpit bin;
- the table of in-game results;
- random name lengths on 40 donors;
- collision retargeting;
- default versus independent Camaro builds.

## If a car crashes on load

- Run `python -m ams2kit doctor <project>`; it reports a vdfm that fails the layout check.
- Check a file directly:
  `python -c "from ams2kit import physics as P; print(P.serial_layout_ok(open(r'<vdfm>','rb').read()))"`.
- Crash dumps land in `%LOCALAPPDATA%\Temp\AMS2AVX*.dmp`; attach them to an issue.
- If collision renaming is the suspect, set `rename_collision = false`.
