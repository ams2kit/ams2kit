# 09: The ShCB keyed binary format (physics `.*bin` files)

The car physics part files are all "ShCB" containers:

- `.edfbin` engine
- `.gdfbin` gearbox
- `.cdfbin` chassis
- `.sdfbin` suspension
- `.cmfbin` clutch
- `.fmfbin` failures
- `.tbfbin` turbo
- `.bbfbin` boost

The `.vdfm` and `.mrdf` files are **not** ShCB (see the end of this page).

The code is in `ams2kit\ams2kit\shcb.py` (generic) and `physics.py` (typed accessors). The tests are in
`ams2kit\tests\test_shcb.py`.

**Status [file]:** all **3,396** physics files of the 524 encrypted base-car paks parse and re-serialise
**byte-identically**. Only one of them, the Mini Cooper S 1965 gearbox, has a 12-byte construct
that the grammar doesn't explain; it is kept verbatim as a `Raw` entry. The cache of extracted files
is in `research\shcb\physics_all\<pak>\<dir>\<file>` (`research\shcb\extract_all.py`).

## Container [file, proven]

```
0x00  "ShCB"
0x04  u32  version 0x53dd0fe6 (constant)
0x08  u32  total size (= end of the last section)
0x0C  u16  section count (1 or 2)
0x0E  u16  flags (0 on disk; the game sets 0x8000 in memory after decrypting)
0x10  count x { u32 id, u32 size, u32 offset }
      sections follow, contiguous, in table order
```

The header is `0x1C` bytes with 1 section and `0x28` with 2. The sections are:

| id | Content |
|---|---|
| `0x1010baba` | The **body**: the keyed value stream described below. |
| `0x55864952` | The **string table**, RC4-encrypted. The key comes from a runtime global, so we haven't decrypted it and it is kept raw. In `.sdfbin` files, the suspension body name ids (`3a1e187c`) are byte offsets into this table. |

Some extracted copies carry junk after `total size` (the donor folder's `gt_gt3.cmfbin` has 102
bytes). It is kept as `trailer`. When you resize something, `serialize()` recomputes the section
sizes, the offsets and the total.

## Body grammar [file, high confidence]

The body is a flat stream of entries with no lengths or counts. An array is simply the same key
repeated, so **rows and gears can be added or removed freely**. Each entry starts with a tag byte `t`.

| `t` | Entry |
|---|---|
| `t & 0x20` set | **Keyed value**: `t`, `key[4]`, then a value of type `t & 0x1F`. |
| `0x60` / `0xE0` (type 0 with `0x40`) | **Object begin**: `t`, `key[4]` names the object or class. There is no value and no explicit end; the object runs until the next object begin. `0x60` is the first object (or a child), `0xE0` a following sibling. Only one chassis file (Sigma P1) has a `0x60` in the middle, which looks like a nested child. |
| `0x40 + n` (`t & 0x60 == 0x40`) | **Group** of `n` members (n up to 31): `ceil(n/2)` bytes of 4-bit member types (low nibble first), then `n` × (`key[4]` + value), with no per-member tag. It is used in `.sdfbin` only. |
| other | Not seen, except the Mini Cooper S 1965 gearbox (`04 aa08ac24 40` + 3 floats?). |

**Bit 7** (`0xA0`-`0xBF`, `0xE0`) is a flag that mostly belongs to the key (the same key in different files
usually has it the same way). In `.bbfbin` it also marks the first entry of a run of repeated keys.
Its meaning is unknown; it is preserved.

### Value types

| Type | Value |
|---|---|
| 0 | `u8` |
| 1 | `i32` |
| 2 | `f32` |
| 3 | `f64` |
| 4 | **Tuple** (below) |
| 6 | `u8` (bool or byte index; in `.sdfbin`, body references) |
| 8 | **Null** (no bytes): the exporter writes zero or default values this way |

The same key can appear with different types in different cars. The exporter compacts values:
- `0` becomes null or `u8`;
- small integers become `u8`;
- integral values may become `i32`, even for physically float fields.

For example, the Camaro SS torque rows store rpm as `i32`/`u8` and one torque value as `i32`. That's
why searching for `a3 02` failed on that car. **Always read numbers type-agnostically.**

### Tuples

The descriptor is `ceil((4 + 2n) / 8)` bytes:
- low nibble = element count `n` (up to 15);
- then `n` 2-bit codes from bit 4, LSB first: `0 = u8`, `1 = i32`, `2 = f32`, `3 = f64`.

The elements follow. Examples:

| Bytes | Meaning |
|---|---|
| `a3 02` | 3 × f32 (vectors, torque rows) |
| `83 02` | u8, f32, f32 (a torque row with rpm 0) |
| `13 00` | i32, u8, u8 (rev limit, 8500, 0, 0) |
| `53 00` | i32, i32, u8 (spring range start, step, count) |
| `02` | u8, u8 (gear cogs) |
| `23 02` | f32, u8, f32 (a point with y = 0) |

When values change type, `shcb.Value.set_tuple()` regenerates the descriptor. It keeps the old code
where the new value still fits; otherwise floats become f32 and integers become `u8`/`i32`.

## Key map (physics.py) [file]

The keys are 32-bit hashes of names we haven't identified. We tried CRC32, FNV, Jenkins, lookup2/8 and
murmur3 on a large list of candidate names, with no hits (doc 14 later cracked
the hash: lookup2 of the upper-case name). Shown as the 4 file bytes:

| File | Key | Meaning | Present |
|---|---|---|---|
| engine | `8b0ab771` (tuple, repeated) | Torque row: rpm, drag (engine braking, ≤0), torque in Nm. 16–86 rows. | all 521 |
| engine | `dea72eb7` tuple[0] | Rev limit, rpm | all |
| engine | `92c7cd7c` f32 | Displacement, litres | 407 of 521 (missing in 114, e.g. CART) |
| engine | `4d239754` tuple[0] | Idle rpm (850/950 Veneno, 700/750 Camaro), **tentative** | all |
| gearbox | object `88de240f` | Forward gears: repeated `9d58f964` (driver, driven) cogs. The fixed boxes list one pair per gear (Veneno: 7). Setup-capable boxes list every option (up to 64). | all 535 |
| gearbox | object `9765b7af` | Bevel `3c5bef62` (driver, driven) plus one or more final-drive pairs (key `9d58f964` again) | all |
| chassis | `670b57ab` | Mass in kg (i32, or f32 in 81 cars) | all 545 |
| chassis | `bbb39f0b` tuple3 | Inertia | all |
| chassis | `1824eaa8` f32 | CG height | all |
| chassis | `a5123d0d` ×4 tuple | Spring range per corner, FL FR RL RR: start, step, count (20) | all |
| chassis | `e9ded999` / `ba614262` / `ac8de939` / `c7c23d06` tuple3 | FL/FR/RL/RR reference points. In the Veneno z = ±1.351 (the four "±1.351" values the BYD build changed). **Not** the axle line in most cars: 453 of 521 differ from the wheel centres by up to 0.6 m in z and sit 0.2–0.3 m inboard. | all |
| suspension | object `7817b5d2` | **Body**: name id `3a1e187c` (string-table offset, used as the body id), mass `670b57ab`, inertia `bbb39f0b`, position `4209feea`, `aab5db49` (?) | 10–11 per car |
| suspension | object `8adfea7e` | **Hinge** (wheel spin axle): wheel body `9f9074d0`, carrier body `8a1e5909`, position body `4209feea`, axis `a213897d` | 4 per car |
| suspension | object `2f5a4bdb` | **Link**: name (optional), body A `9f9074d0` (0 = chassis), body B `8a1e5909`, point on A `4209feea`, point on B `5a44c7e0` | 14, 15 or 20 per car |

The wheel centres are the positions of the hinge wheel bodies (Veneno FL: (0.865, 0.333, −1.351)).

Each wheel's carrier, and every link attached to it, belongs to that corner. On the 27 cars with a
**solid rear axle**, the two rear hinges share one carrier body. That body moves with the axle (z only),
and its link points are assigned to a corner by their own x sign.

The Veneno has 48 movable points:
- 4 wheel and 4 carrier positions;
- 20 links × 2 points;
- plus 3 unpositioned chassis bodies.

## `.vdfm` (not ShCB) [file]

The header is `51 02 01 04 00 00 01 04`, then an 8-byte per-file id (bytes 8–16), then
`u32[8]` at `0x10`. This is really 4 section entries of `(u32 size, u8 kind, u8 pad, u16 0)`: the
"flags"/"?" columns below are kind plus pad. The game rejects the file unless the sizes plus the pads add up
to the file length (doc 12).

| Field | Content |
|---|---|
| `0x10` | Struct size (448 or 440) |
| `0x14` | Flags (1 or 0x801) |
| `0x18` | String table size |
| `0x1C` | ? |
| `0x20` | Relocation table size |
| `0x24` | 0x31 or 0x831 |
| `0x28` | Tail block size (12) |
| `0x2C` | 0x450 |

The rest of the layout:
- The struct is at `0x30`.
- **The string table is always at `0x1F0`** in all 791 files, `0x18` bytes long. It holds plain
  NUL-terminated names, shared when they are equal.
- The **relocation table** is at `align16(0x1F0 + size)`: u64 offsets (relative to `0x30`) of the
  pointer fields that are set. Their values are offsets into the string table.
- Then `align16`, the 12-byte block `01000000 5fb528ef 1x000000`, and padding to 16.

The pointer fields were identified by matching the strings against each car's pak contents:

| Field | Meaning |
|---|---|
| `0x38` | Chassis / base name |
| `0x48` | Engine |
| `0x50` | Clutch |
| `0x58` | Turbo (`.tbfbin`) |
| `0x68` | Failures |
| `0x70` | Gearbox |
| `0x78` | Suspension |
| `0x80` | Base name (collision?) |
| `0x88` | Tyres |
| `0xF8` | Boost (`.bbfbin`) |

The kart has no clutch field. `physics.write_vdfm(data, {"engine": ...}, new_id=True)` rebuilds the
table and the padding. Rebuilding with no changes is byte-identical for all 791 files.

## `.mrdf` statistics [file]

Fixed 224 bytes, header `51 02 01 02`. The field offsets are as in doc 03
(`physics.STATS_FIELDS`). Read them with `read_stats` and write them with `write_stats`.

## Open questions

- The meaning of tag bit 7.
- The Mini 1965 gearbox `04` construct.
- The string-table RC4 key, which would give the suspension body and link names. **Partly solved:**
  every file uses the same keystream from offset 0. 107 bytes are recovered by known plaintext, so
  body names, compounds and drive wheels are readable (`ev.STRTAB_KEYSTREAM`, doc 11).
- Key names (the hash function).
- Engine inertia, and other unlabelled scalars.
- Whether the gear count of setup-capable boxes is set elsewhere (the driveline, or the `.mrdf` gear
  count).
