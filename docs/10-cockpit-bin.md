# 10: Cockpit properties (`<car>_cockpit.bin`)

The crd prop `Cockpit properties` (and `IMSA Cockpit properties` on some cars) names a small binary file,
for example `Camaro_SS_Cockpit.bin`. Base cars keep it in the global pak `HRDFPERSISTENT.bff` at
`vehicles\<folder>\<car>_cockpit.bin`, which has 383 of them. The game opens it **relative to the car's own
folder** (`vehicles\<crd Name>\`), so a pak or loose file works for a modded car.

Code: `ams2kit/cockpit.py`. Tests: `tests/test_cockpit.py`. All 382 base files round-trip byte for byte, and
in every one the header uid is the file's own path uid.

## Format (confidence: high for the layout, medium for field meanings)

The file is a serialized C++ struct plus a pointer-relocation table. It is not ShCB.

| Offset | What |
|---|---|
| `0x00` | `51 02 01 NN 08 00 01 04`. NN is the section count + 1: 5 (314 files), 3 (67 files) or 2 (1 file). |
| `0x08` | u64 lookup8 uid of the file's own path, lower case (`pak_tool.path_uid`). Not checked at load: copies with a wrong uid still loaded. |
| `0x10` | u32 data size. |
| `0x14` | u8 1 (the data section's kind), then u8 **pad** = `-data size % 16`, then u16 0. The game checks it (doc 12), and `to_bytes` recomputes it. The section tags carry their own pad in byte 1. |
| `0x18` | Section table: `(u32 size, u32 tag)` × (NN−1). |

The data block starts at `align16(end of the section table)`, at 0x40 or 0x30. Each section follows at the
next 16-byte boundary, and the file is padded to 16. Section kinds (the low byte of the tag):

- `0x10` pointer relocations: u64 data offsets of the pointer fields. A pointer value is a
  **data-relative** offset. Null pointers are left out of the list.
- `0x32` enum-name pool: `"eGauge_Tach\0eGauge_Speed\0..."`.
- `0x33` enum fixups: `(u64 field offset, u64 pool offset)`. At load, the enum field at that offset is set
  from its name.
- `0x50` type table: u32 count, then `{u32 type hash, u16 version, 2 chars}` (`5c b3 0e 51 07 00 "VC"`,
  `cf 72 d3 e5 03 00 "CB"`).

### Struct fields (data offsets)

| Off | Field |
|---|---|
| `0x00` | char*: gear-lever node in the cockpit vhf, for example `CAMARO_SS_GEARSHIFT_CPIT`. Often null. |
| `0x08` | char*: `"Container"`. |
| `0x10` | char*: **cockpit render model** `Camaro_SS_Cockpit.vhf`, loaded from the car folder. |
| `0x18` | char*: HUD/dash display, `display_camaro_ss` (global `HUDDISPLAY.bff gui\display_*`). Can be null. |
| `0x20`.. | `(u64 count, ptr)` arrays: gauges (0x28-byte entries: an enum `eGauge_*` and a ptr to a range or curve, such as tach 7500/9000), then more arrays (lights/LEDs?). |
| `0x88` | float3, probably the driver eye/cockpit camera position in car space (Camaro 0.38, 1.10, 0.31; Veneno 0.374, 0.90, −0.018). |

The cockpit vhf name doesn't always follow `<key>_Cockpit.vhf`: 79 files differ. For example, the CART
variants share one model: `CART_Lola_T95_cockpit_SO.vhf`.

## Why a plain donor copy crashes

- The game builds the player car's cockpit from the cockpit render model named at `0x10`, loaded from
  **the car's own folder** (`<car folder>\Camaro_SS_Cockpit.vhf`, `.bml` tried first).
- Our car folder `vehicles\byd_seal\` contained `byd_seal_cockpit.vhf`, not `camaro_ss_cockpit.vhf`, so
  the model was not found and the game crashed while looking up a dashboard node in the missing model.
  Both a donor-named and a car-named copy of the bin crash, because both still name `Camaro_SS_Cockpit.vhf`.
- Without any cockpit .bin, the cockpit setup is skipped. The car drives, but the cockpit, bonnet and
  helmet cameras are not registered, so camera cycling stops after the bumper cam.

## Fix (ams2kit build)

`build._cockpit_bins` does three things:

1. It writes `vehicles\<car>\<Name>_Cockpit.bin` = `cockpit.retarget_cockpit_bin(donor_bin, dkey, ckey, Name)`.
   - The vhf string becomes `<Name>_Cockpit.vhf`: the donor key is replaced case-insensitively.
   - The string is rewritten in place when it fits; otherwise it is appended to the data block.
   - The uid becomes that of the new path.
   - The gearshift node, the gauges and the display name stay the donor's. They name nodes inside the donor
     cockpit vhf, or the donor's global display.
2. It sets the crd `Cockpit properties` (and the IMSA one, if any) to that file name.
3. It makes sure the cockpit pak has `vehicles\<car>\<vhf name>` (+ `.bml`).
   - `_renamed_copies` already makes `byd_seal_cockpit.vhf(.bml)`.
   - For other names it copies the donor's file.

The game loads the bin from the car pak and from the loose `Vehicles\<car>\` copy.

`AMS2KIT_NO_COCKPIT_BIN=1` restores the old behaviour: no bin, no cockpit cameras, no crash.

Fallback that needs no binary edit: keep the donor bin unchanged and add
`vehicles\<car>\camaro_ss_cockpit.vhf` + `.vhf.bml` (donor copies) to the cockpit pak.

## Other per-car HRDFPERSISTENT files

The cockpit bin is resolved by path at runtime, in the car folder. The `.cgp/.cdp/.cdv/.vdp`, configanim,
motec and pitcontroller files were not traced. ams2kit already ships car-named copies of them.
