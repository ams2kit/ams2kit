# 03: Physics files

The physics live under `vehicles\physics\` in the car pak. Global copies exist in
`PHYSICSPERSISTENT.bff` (`.vdfm`, stats) and `PHYSICSMENU.bff` (chassis, engine, suspension used by menus).

```
vehicles\physics\vehicles\<car>.vdfm        top-level vehicle file: names its parts
vehicles\physics\engines\<engine>.edfbin    engine (torque curve, rev limit, ...)
vehicles\physics\gearbox\<gearbox>.gdfbin   gear ratios
vehicles\physics\chassis\<base>.cdfbin      mass, inertia, CG, spring ranges, axle positions
vehicles\physics\suspension\<base>.sdfbin   suspension geometry points
vehicles\physics\collision\<base>.xml (+ .joi.xml, .sys.xml)
vehicles\physics\clutches\*.cmfbin, failures\*.fmfbin
vehicles\physics\statistics\<car>.mrdf      menu stats only
```

## The ShCB keyed binary format [file]

Most physics `.*bin` files are "ShCB": a small header (with total size at `0x08` and body size at
`0x14`), then a stream of **keyed values**. Each value is a key of a few bytes followed by its data, and
key prefixes hint at the type:
- `0x21 ...` = int;
- `0x22 ...` = float;
- keys ending `a3 02` precede float vectors;
- `24 ... 13 00` precede an int.

There's no length table, so edit values **in place** (same size). Find keys by byte search, and assert
the old value before patching.

## `.vdfm`: vehicle definition [proven]

- A string table at **`0x1F0`** (92 bytes), referenced by 8-byte offsets (data base `0x30`). The fields are:
  - `0x48` engine;
  - `0x50` clutch (`GT_GT3`);
  - `0x68` failures (`Supercar`);
  - `0x70` gearbox;
  - `0x38 / 0x78 / 0x80 / 0x88` the "base name", used for chassis, suspension, tyres and collision.
- Bytes 8–16 are a per-file id; we randomise them for the new car.
- `0x98 + 12*i`: wheel positions (visual hubs); `0xC8 + 8*i`: **tyre width and diameter** per wheel. The physics
  radius is diameter / 2 (doc 13).
- The strings are plain names, not hashes, so the table can be rewritten freely (`build_vdfm()`).

**Superseded by doc 12.** The old trap was "renaming the base-name fields crashes the game (null tyre
set)". The real cause was our writer: it left the string section's **pad byte** (`0x1D`)
stale, so the game rejected the whole vdfm whenever the table length changed modulo 16, and the empty
struct had no tyre name.
- With the pad fixed (`physics.write_vdfm`), the following fields can carry the car's own name: chassis,
  suspension, engine, gearbox and collision (`buildphys` independent mode).
- Only **tyres (`0x88`) must stay a base-game tyre set**: they come from the boot list `TyresHD.xml`.

The original workaround still works (proven with a 6,000 kg diagnostic build): keep the donor's names and
override its chassis and suspension in our pak. But it also changes the real donor car while our pak is
mounted.

## Engine `.edfbin` [proven]

| Key | Content |
|---|---|
| `24 8b 0a b7 71 a3 02` | **Torque table row**: `rpm, drag(engine braking), torque` as 3 floats. The Veneno has **25 rows**, 19 bytes apart (key + 12 bytes). |
| `24 de a7 2e b7 13 00` | Rev limit (int rpm). The Veneno's is 8500. |
| `22 92 c7 cd 7c` | Displacement in litres (float; the Veneno's is 6.498). Setting it to 0 had no effect on driving. |

The EV curve (`build_byd_physics.py`):
- flat 1,050 Nm up to about 3,547 rpm;
- then constant 390 kW;
- 0 Nm at the 8,000 rpm limit;
- negative rows above that.

The simulated motor revs to 8,000 rpm instead of the real motor's ~15,000, so the torque is scaled up
to give the real force at the wheels. The physics engine also has an `ElectricMotor` class
(`fe::ElectricMotor`), which we haven't explored.

An early version of the builder assumed "5 rows, 76-byte stride from offset 120". That hit only every
4th row and left a jagged curve. **Always parse rows by key.**

## Gearbox `.gdfbin` [proven]

- Each gear is the flag `24 9D 58 F9 64 02` followed by 2 cog bytes (driver, driven).
- The bevel flag is `24 3C 5B EF 62 02`.
- The final drive is another gear entry.

The reused `AWD_VENENO_SEQUENTIAL` driveline **needs 7 gear slots**. A 1-gear box made the physics
blow up, and the user saw "the camera goes crazy". So an EV is built as **7 identical 1:1 gears**
plus the final drive (63/11 = 5.727, about 187 km/h at 8,000 rpm on the measured 0.3545 m rolling
radius). The AI still "shifts" through them, which is harmless.

## Chassis `.cdfbin` [proven]

| Key | Content |
|---|---|
| `21 67 0b 57 ab` | Mass, int kg (the Veneno's is 1570). |
| `24 bb b3 9f 0b a3 02` | Inertia, 3 floats. |
| `22 18 24 ea a8` | CG height, float. |
| `24 a5 12 3d 0d 53 00` | Spring range per corner: int start, int step. 4 entries. |
| `±1.351` floats (4×) | Axle positions = half the wheelbase. Replaced with ±1.46 for 2.92 m. |

## Suspension `.sdfbin` [proven]

- Points are float3 values after the keys `42 09 fe ea` or `5a 44 c7 e0`, each followed by `a3 02`.
- There are 48 of them: 8 wheel points and 40 mounting points.
- We moved each corner as a unit to the new wheelbase and track. Z is negative at the front; X is left.

## Menu stats `.mrdf` (statistics) [proven]

A fixed-layout record with plain floats and ints. Offsets:
- `0x20` top speed in m/s;
- `0x24` 0-100 time;
- `0x28 / 0x30` gear reaching 100 / 160;
- `0x3C` mass;
- `0x40` gear count;
- `0x44` torque in Nm;
- `0x48` power in hp;
- `0x4C` drivetrain (1 = AWD);
- `0x50 / 0x54` boost and aspiration;
- `0x64` **engine layout index** (doc 05);
- `0x84` wheelbase;
- `0x88` rear weight fraction;
- `0xA0` displacement in litres.

These values affect only the menu, not the driving.

## Collision

The collision XML's main object is named `COLLISION_CONVEX_<BASE>`. Ours is still the Veneno's
shape (open item).
