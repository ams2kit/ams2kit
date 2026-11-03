# 11: Electric drive

**Short answer:** AMS2 has no electric powertrain that a car can select. Every car, hybrids
included, drives through the ICE model: the `.edfbin` torque table, idle, clutch and gearbox. Hybrids
add an electric motor on top, through the **boost** system (`.bbfbin`, vdfm field `0xF8`).

So an EV is still an "ICE with a motor curve". We can, however, get rid of most ICE behaviour:
- no stall and no clutch pedal (a centrifugal clutch in a custom driveline group);
- lift-off regen (the engine-braking column of the torque table);
- realistic rotor inertia.

A true front motor plus rear motor is possible only experimentally, through a hybrid boost file.

Code: `ams2kit\ams2kit\ev.py`, tests in `ams2kit\tests\test_ev.py`. Research scripts and dumps are in
`research\ev\`.

## Findings

### 1. There is no Formula E car
`FE-G1` is **Formula Edge**: three 1995 V10 cars, `Formula_Edge_G1M1..3`, on the ordinary
`RWD_MODERN_SEQUENTIAL_FORMULA_A_FLEX_v3` group.

None of the 267 catalog cars is a pure EV. The cars with electric parts are:

| Car | Driveline group | Boost file | Type | Wheel drive |
|---|---|---|---|---|
| Formula Ultimate 2016/2019/2024 (F1 hybrids) | `RWD_MODERN_SEQUENTIAL_FORMULA_ULTIMATE_FLEX_v3` | `formula_ultimate_2019.bbfbin` | 4 | REAR |
| BMW M Hybrid V8, Porsche 963, Lamborghini SC63 | `RWD_MODERN_SEQUENTIAL_DPI_FLEX_MR_v3` | `lmdh_8000.bbfbin` | 7 | REAR |
| Cadillac V-Series.R, Alpine A424 | same | `lmdh_8800.bbfbin` | 7 | REAR |
| Aston Martin Valkyrie (road) | `RWD_MODERN_SEQUENTIAL_VALKYRIE_FLEX_MR_v3` | `aston_martin_valkyrie.bbfbin` | 3 | REAR |
| **Lamborghini Revuelto** | **`AWD_VENENO_SEQUENTIAL_SVA_FLEX_v3`** (our donor's group) | `lamborghini_revuelto.bbfbin` | 7 | **FOUR**, split 0.62 |
| Formula Reiza (KERS shots) | | `formula_a.bbfbin` | 3 | REAR |
| Formula USA 2023 (push-to-pass), Stock Car V8s | | `formula_usa_g4` / `stockv8_*pushtopass` | 6 / none | n/a |

Some driveline records belong to cars that are not in the catalog:
- `AWD_LMP1H`: Audi R18, Porsche 919, Toyota TS040/050, Marek RP339H...
- `AWD_DUAL-CLUTCH_FRONT-HYBRID`: Acura NSX 2017, Porsche 918.

These groups contain a `HYBRID_front_diff` whose input shaft is `shaft_dummy`, which is not connected to
the engine. So hybrid torque reaches those front wheels from code, not through the driveline graph.

### 2. Driveline: the `electricmotor` component exists but is unused [file]

`driveline.rg` declares two layouts:
- `LAYOUT electricmotor` (one attribute, `pto` = the power take-off shaft, "Electric Motor power take off
  shaft");
- `LAYOUT l_pistonmotor` (`engine:pto`).

Only two records use them:
- the test group `Basic_RWD_offline` uses `RECORD electricmotor` and `pistonmotor`;
- `RWD_L51` uses `electric_L51`, but it is **commented out** (`#electric_L51`).

No shipping car has an electric motor in its driveline.

The game has an `ElectricMotor` driveline component, but it only forwards a torque supplied from
elsewhere; there are no motor parameters (curve, rpm, battery) in the driveline.

### 3. Hybrid physics files [file]

**There are no special file types.** The extensions across all 524 base paks are
`.cdfbin .cmfbin .edfbin .fmfbin .gdfbin .sdfbin .tbfbin .bbfbin`. There is no `.emfbin`.

**Hybrid engines are ordinary ICE `.edfbin` files.** No engine key is specific to hybrids (we surveyed
all 521 files, `research\ev\keysurvey.py`).

The hybrid lives in the `.bbfbin` ("boost") file, which is in the car pak under `vehicles\physics\turbo\`.
Its vdfm field is `0xF8`. For example, the Revuelto vdfm has:

```
engine lamborghini_revuelto
gearbox lamborghini_revuelto
suspension lamborghini_veneno
boost lamborghini_revuelto
chassis/tyres/base lamborghini_revuelto
```

**The Veneno vdfm has no boost field.**

The file is loaded from `Turbo/<name>.bbfbin`. The boost system knows these property names, for example:

```
Max Boost, Boost Time, Boost Delay, Max Boost Time, Fill With Brakes, Full Charge,
Max Regen Power(+Ramp), Max Regen Torque, Max Torque, AWD Torque Split, Require Engine On,
Total Power Limit, KERS Wheel Drive, Torque Fill, GearDeployment Balanced/Build/Qual/Attack,
Charging Threshold RPM/G, Max Lap Energy, RPMDeployment, Use Deployment Modes, Boost Launch...
```

The mapping from keys to these names is partly proven (in-game behaviour) and partly guessed (from values). It is in `ev.BOOST_KEYS`:

| Key | Meaning | Evidence |
|---|---|---|
| `da4efba7` | Model type: 3 KERS, 4 F1 ERS, 5 classic, 6 push-to-pass, 7 hybrid deploy | proven |
| `4423f779` | Full charge, J: F1 4.0 MJ, LMDh 4.86, Revuelto 5.0, Valkyrie 4.68 | values |
| `3a74a835` | Max boost, kW: F1 120, LMDh 50, Valkyrie 120, Revuelto 138 (the Revuelto mrdf power 997 hp ≈ V12 + 138 kW) | values; boost is disabled if this is 0 |
| `8eacad13` | Max boost time, s: F1 33.33 = 4 MJ / 120 kW; LMDh 97 = 4.86 MJ / 50 kW | values; disabled if 0 |
| `e31a9a4e` | Motor max torque, Nm: F1 200 (the real MGU-K figure), Valkyrie 280 | values |
| `d52a5024` | **KERS Wheel Drive**, a string-table offset. Values `REAR` / `FOUR` / `FRONT` | proven |
| `cbfaf20d` | AWD torque split: Revuelto 0.62 (with FOUR), 1 elsewhere | values |
| `1f1fd9e4` × 42 | Total power limit vs throttle, 0 to 1.025 in steps of 0.025, in kW: LMDh up to 500 kW (the class limit) | exactly 42 rows required |
| `8ffb007b` | RPM deployment rows; `b77598d6` / `d6613dbc` / `64b089f5` / `747d8677` = gear deployment Qual / Attack / Balanced / Build | proven |
| `13123e7d` | Max lap energy (F1 4 MJ). `d88ea3c8` / `32ca0d59` are probably the regen power and torque (low confidence) | values |

**Gearboxes:** the hybrids have normal multi-speed boxes (F-Ultimate 8, Revuelto 8, LMDh 61 options).

**The Revuelto runs 8 gears on the same `AWD_VENENO_SEQUENTIAL_SVA_FLEX_v3` group as the Veneno's
7.** So the gear count is **not** fixed by the driveline group. The earlier "1-gear box exploded"
result (docs/08) has another, still unknown cause. Karts and the Super Trophy Truck are effectively
single-speed setups (3 ratio options).

**Menu stats `.mrdf`:**

| Car | Gears | Torque | Power | Boost / aspiration | Layout |
|---|---|---|---|---|---|
| Revuelto | 8 | 1070 Nm | 997 hp (combined) | 0 / 0 | 4 |
| F-Ultimate | 8 | | | 2 / 1 | 1 |
| LMDh | 7 | | | 2 / 1 | 2 |

### 4. ShCB string tables are decryptable [file, new]

The "RC4" string section is XORed with **one fixed keystream for every file**, starting at offset 0.
For example, all RWD hybrid `.bbfbin` files carry `d6 5c 7a 7d ef` = `REAR\0`, and the Revuelto's
`c2 56 6e 7d ef` = `FOUR\0`.

We recovered 107 bytes of the keystream from known plaintext, and they are cross-checked across files
(`ev.STRTAB_KEYSTREAM`, `research\ev\ks3.py`). The decrypted contents:

| File | Strings |
|---|---|
| `.edfbin` | Engine layout: `V8`, `V12`, `S4`, `F6`, `SINGLE` (kart) |
| `.cdfbin` | Compounds (`Soft`, `Medium`, `Hard`, `Wet`), setup map names, and the **drive wheels `REAR` / `FOUR` / `FRONT`** |
| `.sdfbin` | Body names: `DRIVER_HEAD`, `FUEL_TANK`, `BODY`, `FL_SPINDLE`, `FL_WHEEL`, `REAR_AXLE`, `FL_FORE_UPPER`... |

This makes `FRONT` writable in a `.bbfbin`, and it answers the open question in doc 09.

### 5. Sound [file]

Sound is chosen by the car pak's **`vehicles\<car>\<car>.csdbin`**. This is a reflection struct (header
`51 02 01 05`, like the vdfm) that names the FMOD banks and events:
- `Audio/AMS2/Vehicles/Sort/L/Lamborghini_Veneno_AMS2` (+ `_AI`);
- `event:/AMS2/Vehicles/Sort/L/Lamborghini/Veneno/EnginePlayer/Lamborghini_Veneno_EngineExt` / `_EngineInt`;
- the starter, the rev limiter (`RevLimiterTC_Marcas`), gear shifts (`GearShift_C8_Z06`), backfire,
  brakes and wind.

Sound is not chosen by the engine name or the crd. The banks are in
`<game>\Audio\AMS2\Vehicles\Sort\...\*.bank`.

There is **no electric motor sound** in the game. The hybrids' electric whine is baked into their engine
banks (`M_Hybrid`, `F_Hybrid_Gen1`, `F_Ultimate_2022`). `MasterBank.strings.bank` has `Kers` and `Whine`
fragments only.

## Can a mod car be a pure EV?

| Wish | Possible? | How |
|---|---|---|
| No idle stall, no clutch pedal | **yes (needs test 1)** | Custom RECORDGROUP with an `l_centrifugal_clutch` (`ev.ev_driveline_rg`). |
| No gear shifts | partly | 1:1 gears (the current hack). The gear number still shows, and the AI "shifts". |
| Motor torque and power curve | **yes** | `ev.motor_rows` (flat torque, constant power, limiter). |
| Regen | **lift-off: yes** (drag column). Brake-pedal blending: no | `motor_rows(regen_kw=, regen_nm=)` |
| Separate front 160 kW and rear 230 kW motors | **experimental** | Engine = rear motor; boost type 7 with `KERS Wheel Drive FRONT` = front motor (test 3). With the AWD Veneno group, both axles share one motor through the centre diff (`C_right_ratio` setup). |
| Top speed 187 km/h | **yes** | Limiter rpm + final drive (`ev.final_drive_for`). |
| EV sound | **no** (without authoring an FMOD bank) | Keep the donor's csdbin, or repoint it to another car's bank (untested). |

Constraints that still apply (docs/03, 08):
- keep the vdfm base names;
- override files at the donor's paths inside our pak;
- keep the engine and gearbox names.

A boost file needs a vdfm that **already has** field `0xF8`, because adding a relocation entry means
repacking, which crashed the game. So test 3 needs the Revuelto vdfm as the physics donor.

## Recipe (ams2kit)

### A. Recommended now: EV-ified ICE on the current Veneno donor

1. **Engine** (`engines\lamborghini_veneno_lp750-4.edfbin`, donor name):
   - `rows = ev.motor_rows(390, T, 8000, regen_kw=60, regen_nm=300)`, with
     `T = 390e3 / (2π/60 · corner_rpm)`. The current build uses a corner at 3547 rpm, which gives 1050 Nm.
   - Set the rows with `Engine.set_torque_curve(rows)` (the drag column is the regen). Keep
     `rev_limit 8000` and the 0 rpm row.
   - Leave the idle (`4d239754`, 850/950) alone; the clutch below handles it.
2. **Gearbox:** 7 × 1:1 gears, bevel 1:1, final drive
   `ev.final_drive_for(187, 8000, 0.3545)` = 5.717 (63/11). This is unchanged.
3. **Driveline** (`UserData\Mods\BYD_Seal\driveline.rg`):
   ```python
   ev.ev_driveline_rg("BYD_Seal", "AWD_VENENO_SEQUENTIAL_SVA_FLEX_v3", game_rg_text, suffix="BYD_EV",
                      clutch_torque=3000, clutch_rpm=(900, 1500))
   ```
   This writes our `RECORD BYD_SEAL_BYD_EV_01 l_driveline` and a copy of the group,
   `..._BYD_EV`, in which `clutch_GT3_650Nm` is replaced by `clutch_BYD_EV_centrifugal`
   (same shafts, engages between 900 and 1500 rpm, above the 850 idle, so there is no creep and no stall).
   - Optional: `crank_mass=ev.reflected_inertia(0.04, 16000, 8000)` = 0.16. The simulated rotor turns at
     half speed, so the inertia scales ×4; the Veneno crank is 0.10.
4. **Stats `.mrdf`:** gear count 1, boost 0, aspiration 0, torque 670, power 530 hp
   (as `buildphys` does now).
5. **Sound:** leave the csdbin as it is for now.

### B. Experimental: two motors via the hybrid boost

1. Use the **Lamborghini Revuelto** as the physics donor. It has the same suspension file
   (`lamborghini_veneno.sdfbin`), the same driveline group, a vdfm with `boost`, its own chassis, tyres
   and base name `lamborghini_revuelto`, and is DLC `lamborghinidreampackpt2`.
2. **Engine** = the rear motor: `ev.motor_rows(230, T_rear, 8000, regen_kw=..)`.
3. **`turbo\lamborghini_revuelto.bbfbin`** = the front motor:
   ```python
   ev.boost_set(revuelto_bbfbin, wheel_drive="FRONT", max_boost_kw=160, max_torque_nm=<test>,
                full_charge_j=2_000_000_000, max_boost_time_s=1e5)
   ```
   - The large charge and time make the battery effectively unlimited.
   - The torque reference (motor or crank) is unknown; try 310 Nm.
4. **Driveline:** an RWD copy for the engine (for example `ev_driveline_rg(..., "<RWD road group>", ...)`),
   because the front axle is driven by the boost.

## Test plan (integrator)

Log telemetry with `python ams2kit\ams2kit\telemetry.py log run.csv 120` (columns: speed, rpm, gear,
throttle, brake, local_accel_z). Drive at Interlagos or any long straight.

### Test 1: custom driveline group plus centrifugal clutch (most important; recipe A step 3 only)

- **Build:** the current BYD build, plus the `driveline.rg` from `ev_driveline_rg` above, copied into
  `UserData\Mods\BYD_Seal\`.
- **Check first:** `Documents\Automobilista 2\modsupport\driveline` (OneDrive) contains the new
  RECORDGROUP.
- **Expect:**
  1. The car loads and drives. If it crashes or won't select, mod `driveline.rg` files cannot define
     groups or records; then keep the plain record.
  2. Standing still in gear with throttle 0: rpm ≈ 850 and the engine doesn't stall when braking to a stop.
  3. Full-throttle launch: rpm jumps to about 1100–1500 and then follows the speed, at
     rpm ≈ 42.8 × km/h (8000 rpm at 187 km/h).
  4. No clutch pedal is needed.
- **Also report:** whether the installed `driveline.rg`, which now redefines the existing group name
  `RWD_H-PATTERN_SYNCHRO_MEDIUM_MEDIUM_ROAD_2_FLEX_v3`, caused any problem.

### Test 2: lift-off regen (recipe A step 1)

- Coast from 150 km/h to 50 km/h at throttle 0, brake 0. Compare `local_accel_z` with the previous build.
- With `regen_kw=60` and 2,100 kg, expect about 1.0 m/s² of extra deceleration at 100 km/h
  (F = P/v ≈ 2.2 kN) and about 1.7 m/s² at 60 km/h. It fades below about 600 rpm (14 km/h).

### Test 3 (optional): `electricmotor` component

- `ev_driveline_rg(..., electric_motor_on="driveshaft_AWD_front_POST")`.
- **Expect:** probably nothing, or a crash. Report any change in acceleration.

### Test 4 (optional, before recipe B)

- Drive the stock **Revuelto**:
  - Does the HUD show a battery or KERS bar?
  - Does the deploy happen automatically, or does it need the Boost / ERS buttons?
  - Is the car selectable without the DLC (ownership)?
- Then build recipe B and compare 0–100 km/h and the 100–187 km/h pull with recipe A.

## Unknowns

- Whether mod `driveline.rg` files may define RECORDs and RECORDGROUPs. The README says
  "Additional driveline records ... can be defined here"; test 1 checks it.
- Which object provides the `fe::ElectricMotor` torque.
- The exact semantics of the type-7 boost: torque reference, deploy logic, AI use, and whether
  `Require Engine On` blocks a "dummy ICE".
- The cause of the old 1-gear failure, since the driveline gear count is not fixed.
- A writer for the csdbin format, and whether the engine events of another car can stand in for a
  motor whine.
