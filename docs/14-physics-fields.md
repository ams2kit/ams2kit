# 14: Physics field dictionary

**Status:** the key hash is cracked [proven]. About 200 keys are named exactly; most of the rest
that matter are identified from rFactor conventions, in-game tests and values across 505 chassis,
220 engines and the other base files.

- Code: `ams2kit/fields.py`, with the generated survey in `fields_survey.py`. Tests:
  `tests/test_fields.py`.

## 1. The key hash [proven]

A key is **Bob Jenkins' lookup2** (`hash()`, 1996, `initval` 0) of the **upper-case property
name**. The file stores the hash little-endian. For example, `KERS Wheel Drive` hashes to
`0x24502ad5`, written as the bytes `d5 2a 50 24`.

```python
fields.key_for_name("RPMTorque")   == "8b0ab771"
fields.key_for_name("BrakeTorque") == "4ba4817a"
fields.key_for_name("[FRONTLEFT]") == "7d16e29f"   # object keys are the section headers
```

How it was found:
- Seven keys already had names from earlier docs (RPMTorque, BrakeTorque, SpringRange, Mass,
  Inertia, CGHeight, ...).
- These names come from the rFactor HDV/ENG vocabulary (`[GENERAL]`, `[FRONTWING]`, `[BODYAERO]`,
  `FLBrakeTorque`, `RPMTorque100`...).
- Testing about 20 classic string hashes on those pairs gave hits only for `lookup2(upper)`.

Hashing a large list of candidate property names then named about 200 keys. They are stored in
`fields_survey.HASH_NAMES`.

**The physics files are compiled rFactor-style data files:**

| File | rFactor equivalent | Sections |
|---|---|---|
| `.cdfbin` | HDV | `[GENERAL] [FRONTWING] [REARWING] [DIFFUSER] [BODYAERO]` (unnamed suspension section) `[CONTROLS] [ENGINE] [DRIVELINE] [DAMAGE] [FRONTLEFT]` (FR) `[REARLEFT] [REARRIGHT]` |
| `.edfbin` | ENG | |
| `.hdtbin` | TBC (tyre) | `[SLIPCURVE] [COMPOUND] FRONT: REAR: ALL:` |
| `.sdfbin` | | `[BODY]`, `[BAR]`, hinge |

AMS2 renamed many properties, so a large share of the keys does not hash to the classic rF names.
Brute force over 1-3 token combinations produced only noise.

**Setup pattern:** `XRange = (start, step, count)` plus `XSetting` (a u8 index), so value =
`start + step * setting`. `count = 0` means fixed. A car without a feature carries a constant range,
for example `(0.9, 0, 0)` for the TC range on cars without TC.

Corrections to earlier docs:
- `e9ded999 / ba614262 / ac8de939 / c7c23d06` are **`Undertray00`-`03`** (body scrape points, with
  `86ae662b` = undertray spring/damper/friction), not axle reference points. The four "aero
  points?" (`f3141524...`) are `Undertray04`-`07`, and `a243c615/e4f96117` are `Undertray08/09`.
- In `.bbfbin`, `3a74a835` hashes to `Boost`, not `Max Boost` (that is `02d86a19`). `8eacad13` is
  `Boost Time`. The values-based meanings in `ev.BOOST_KEYS` still stand.

## 2. Method (for the remaining keys)

1. Survey every key in every file kind: its section, type, file count and sample values
   (`fields_survey.SURVEY`).
2. Use rFactor conventions, consistency across cars and in-game tests for the rest. Each entry is
   labelled `proven`, `strong`, `guess` or `unknown`.

## 3. The engine torque multipliers [proven]

The torque table (`RPMTorque`) is interpolated and then scaled. With `p_peak` = the rpm of maximum
power:

```
if drag < 0:  drag *= chassis[27844d75] * engine[27844d75]              # engine-braking mult
T_mult = chassis[a3bf1e60] * engine[a3bf1e60]
P_mult = chassis[c3667d2e] * engine[c3667d2e]
w = gaussian(rpm - p_peak)                                              # 1 at/above peak power
torque *= T_mult + (P_mult - T_mult) * w   (approximately: torque-mult below peak power, power-mult at it)
```

- The chassis `[ENGINE]` section (`3f9e4598`) holds these keys; the engine file's own copies are
  multiplied in.
- Base values: **Lancer R 0.85 / 0.85**, Camaro SS 1.04 / 1.04, most cars 1 / 1. These are rF's
  `GeneralTorqueMult / GeneralPowerMult / GeneralEngineBrakeMult`, but the names don't hash.

## 4. Dictionary (main fields)

### Chassis

The full list is in `fields.FIELDS["chassis"]`, with about 230 described and 731 surveyed.

| Key | Name | Unit / meaning | Conf. |
|---|---|---|---|
| `670b57ab` | Mass | kg | proven |
| `bbb39f0b` | Inertia | kg m², 3 axes | proven |
| `1824eaa8` | CGHeight | m | proven |
| `beba677b` | CGRearRange | rear weight fraction (Lancer 0.41, Camaro 0.435, Veneno 0.57) | strong (name hashed) |
| `df8d93cf` | CGRightRange | right weight fraction 0.5 | strong |
| `a0530c50` / `6f70f3c7` | FuelTankPos / FuelTankMotion | m / (N/m, damping ratio) | strong |
| `19389974` / `99f0bbf8` | FuelRange / FuelSetting | litres (1, 1, capacity) / default | strong |
| `3363edfd` | BodyDragBase | **= ½ρ·Cd·A**, so F_drag ≈ value·v² (Lancer 0.44 → CdA 0.72; GT3 0.414 plus wings) | strong |
| `67caa092` | body aero 2 | 0.1 Lancer … 0.6 F1; positive on downforce cars, so not plain lift | guess |
| `2cfb70da` / `23ec212a` | FWDragParams / FWLiftParams | (base, per setting, per setting²); lift < 0 = downforce | strong |
| `67dcb6b3` / `83d385b9` | RWDragParams / RWLiftParams | same | strong |
| `ad3c2013` / `15765486` | FWRange / RWRange | wing setup ranges | proven name |
| `ebdda812` / `1744ed31` / `38d18ee7` | FWCenter / RWCenter / BodyCenter | centres of pressure | proven name |
| `*Left/Right/Up/Down/Aft/Fore/Rot` | FW/RW/Body | aero response per flow direction (rF) | strong |
| `e5b9a9d6` / `66001e25` | Front/RearAntiSwayRange | N/m | strong |
| `69d49b3b` / `55c9ea65` / `1a73fe3e` / `33763373` | toe F/R, caster L/R ranges | deg | strong |
| `a6321357` / `fdba6473` | RearBrakeRange / Setting | **rear** brake fraction = 0.01 × setting (Lancer 35, Veneno 45, F1 44) | strong |
| `d0003859` / `dabdb981` | BrakePressureRange / Setting | 0.5 + 0.01 × setting; every base car uses 40 (= 0.90) | strong |
| `b3d2e5a0` / `639d2bd2` | TC range / default level | (0, 0.099, 10) with TC, (0.9, 0, 0) without | strong |
| `249e0313` / `b2be8e7e` | ABSStrength range / default | (0, 0.1, 10) with ABS, (0.96, 0, 0) without; default 8 | strong (name hashed) |
| `bc1266e0` / `bc907f88` / `f29af810` | ABSstandard / TCstandard / SCstandard | fitted as standard (1; null without) | strong (names hashed) |
| `07f76e47` / `255afb23` / `26075add` | ABSSlip1 / ABSSlip2 / ABSMinMax | target slip / limits | proven name |
| `3043ce21` / `f734a1fe` | SteerLockRange / steering wheel range | deg (wheel lock / lock-to-lock rotation) | strong |
| `a3bf1e60` / `c3667d2e` / `27844d75` | torque / power / engine-brake mult | factor (section 3) | **proven** |
| `9435f2cb` | WheelDrive | string REAR / FOUR / FRONT | proven |
| `ff0c2207` | ForwardGears | count | strong |
| `366e8707` | BaulkTorque | Nm | proven name |

Per corner (`[FRONTLEFT]`, FR `d6537908`, `[REARLEFT]`, `[REARRIGHT]`):

| Key | Name | Meaning |
|---|---|---|
| `4ba4817a` | **BrakeTorque** | Nm at 100 % pedal (proven name) |
| `a5123d0d` / `ceaa7a97` | SpringRange / SpringSetting | N/m |
| `44495d88` / `51374153` | SpringMult / DamperMult | motion-ratio multipliers |
| `d7c60d7a` | RideHeightRange | |
| `0c43d9d0`, `3089ec3d`, `bcc0a291`, `bc6d0ef7` | slow/fast bump/rebound damping ranges | N/(m/s) |
| `70026d2b` / `1f7d2d8e` | BumpStage2 / ReboundStage2 | knee speeds |
| `b3d821f7` / `177b8a89` | BumpTravel / ReboundTravel | |
| `7fc6f841` / `cb91f163` / `71746eeb` | bump stop spring / rising spring / damper | |
| `24e19cb2` | CamberRange | |
| `a6dac6bf` / `bb9616f6` | PressureRange / setting | kPa |
| `bb592cd5` | PackerRange | |
| `57510f51` | SpinInertia | |
| `beb9bbab` / `1911eace` | PushrodSpindle / PushrodBody | |
| `097ad24b`, `ed3fc221` | brake disc and pad ranges | |
| `1ee5b64c`, `bd59c842`, `6ea60dfb`, `1cd55c78` | brake wear / failure / heating / cooling | |
| `92aa0624`, `e795a8d0`, `d0031855` | brake temperature points | guess |

### Engine

52 keys described.

| Key | Name | Meaning |
|---|---|---|
| `8b0ab771` | RPMTorque | rpm, drag, torque (proven) |
| `4665ae87` | EngineInertia | kg m² (strong; Veneno 0.28, F1 0.05) |
| `4d239754` | IdleRPMLogic | |
| `40f1d2b9` | IdleThrottle | |
| `7902b6bd` | LaunchRPMLogic | |
| `dea72eb7` | RevLimitRange | rev limit in element 0 |
| `19668af9` | RevLimitLogic | |
| `d39464af` | limiter cut and width | |
| `afd78add`, `54106db1`, `f6e39fd9`, `b30f25fc`, `a700d23a`, `67171586`, `6ada2b3a` | thermal (OptimumOilTemp, CombustionHeat, EngineSpeedHeat, ...) | strong |
| `f75f822b` / `527b76cd` | LifetimeAvg / LifetimeVar | proven names |
| `0acea858` | LifetimeOilTemp | |
| `c1f4543c` / `ceb17525` | EngineEmission / EngineSound | positions |
| `92c7cd7c` | EngineSize | proven |
| `af00b3ba` | Layout | proven |
| `515f5e83` | RPMBoost | proven |
| `ba65dd60` | BoostTorque | proven |
| `04454929` | throttle map | |
| `4ae2dd6c` / `d2a29232` | FuelConsumption / FuelEstimate | guess. `d2a29232` is 0.85 on the Lancer but is **not** used by the torque lookup |

### Other files

| File | Fields | Source |
|---|---|---|
| Gearbox | Ratio / bevel / forward-gear and final-drive objects | proven |
| Clutch | TorqueCap, SlipFactor, Inertia, wear and heat | names hashed |
| Failures | CoolantLeak, OilLeak, Misfires, LooseWheel, FW/RWDetach (+ unnamed parameter tuples) | |
| Turbo | Turbo1/2 Size, Twin Turbo, SurgeSlope, plus 26 unnamed | |
| Boost | `ev.BOOST_KEYS` plus hash names | |
| Suspension | `[BODY]`, `[BAR]`, hinge, Name/Mass/Inertia/Pos/Ori/posbody/negbody/neg/axis | all proven |
| Tyres | DryLatLong, WetLatLong, LatPeak, LongPeak, LoadSens, DrySlide/WetSlide, SpringBase, SpringkPa, Damper, Width, Tread*, AI* | names hashed |

### Driveline (`driveline.rg`, text)

Brake records (`l_brake`: disc, slip_factor, wheel) only couple the brake to its wheel shaft. **Brake
torque lives in the chassis corner sections (`BrakeTorque`)**, with bias and pressure in `[CONTROLS]`.

## 5. BYD Seal calibration answers

### (a) Braking

The fields are:
- per-corner `BrakeTorque` (`4ba4817a`);
- bias `RearBrakeSetting` (`fdba6473`, rear % with range `a6321357`);
- pressure `BrakePressureSetting` (`dabdb981`, 0.5 + 0.01·s; base cars use 0.90).

**Target:** a 2,185 kg car plus a 75 kg driver at 1.04 g needs about 23.1 kN, which at r = 0.3515 m
is **about 8.1 kNm of total wheel torque**.

The current Lancer-based build has 3800 F / 3600 R Nm, pressure 0.9 and 35 % rear. Two possible
bias conventions give very different capacities:
- rF style (bias splits 2× the per-wheel torque): about 13.4 kNm, i.e. grip-limited.
- Bias as a plain fraction: about 6.7 kNm, i.e. **0.86 g, short of the target**.

Recommendation: raise BrakeTorque by about 1.35× (**≈ 5100 F / 4850 R**), which covers the target
under either convention. Keep the rear setting around 33-35 (the Seal is about 49/51 static, with
about 0.16 g of load transfer at 1 g). Then the tyre grip and ABS set the 37.8 m.

The exact bias formula is **not yet known**. Verify with a full-pedal straight-line
stop in telemetry (player-driven: AI braking is modulated).

### (b) Aero

**Drag:** `BodyDragBase` (`3363edfd`) = ½ρ·Cd·A. For the Seal, 0.6125 × 0.219 × 2.3 = **0.31**. The
current build already writes 0.24, which is CdA 0.39 (low). Also zero the wing drag `2cfb70da` and
`67dcb6b3` element 0, or count them in the total.

**Lift:** front wing `23ec212a` (Lancer +0.032, i.e. slight lift) and rear wing `83d385b9` (Lancer 0).
A road car needs no downforce: leave them near 0. `67caa092` is uncertain; keep the donor's value.

The units come from the rF convention plus cross-car consistency (GT3 body 0.414 + front 0.02 +
rear 0.14 = 0.57, i.e. CdA 0.94). Confirm with a coast-down
(`a = (BodyDragBase·v² + rolling) / m`).

### (c) TC / ABS defaults

- **TC:** `TCstandard` (`bc907f88`) = 1, range `b3d2e5a0` = (0, 0.099, 10), default `639d2bd2`
  (Lancer 6).
- **ABS:** `ABSstandard` (`bc1266e0`) = 1, range `249e0313` = (0, 0.1, 10), default `b2be8e7e` = 8.
  ABS slip targets are `07f76e47` / `255afb23`.
- The Lancer donor already has both. Cars without the aids use the constant ranges (0.9, 0, 0) /
  (0.96, 0, 0) and null settings.

### (d) Delivered torque

The chassis `[ENGINE]` `a3bf1e60` (torque mult) and `c3667d2e` (power mult) multiply the torque table
(proven, section 3). **The Lancer donor has 0.85 / 0.85**, which explains most of the measured
76 %. The rest is probably the slipping centrifugal clutch or driveline losses. The current build
already writes 1.0 / 1.0.

Also check:
- the engine file's own `a3bf1e60` / `c3667d2e` / `27844d75` (multiplied in; absent from most engines);
- `RPMBoost` (`515f5e83`) on turbo donors (flatten to 1);
- the limiter `d39464af` and `LaunchRPMLogic` `7902b6bd` scaled with the rev limit.

### (e) Tyre grip

Grip lives in the tyre set (`.hdtbin`, boot-loaded, **must be a base set**):
- `DryLatLong` (`b31155cd`): μ lateral and longitudinal per axle;
- also `LatPeak` / `LongPeak` / `LoadSens` / `DrySlide`.

Examples: `chevrolet_camaro_zl1` 1.10 F / 1.18 R; `lancerr` 1.125; `lancerrs` 1.14. Some sets use a
different scale (Evo IX / VI sets 2.1-2.2). A mod cannot edit a set without affecting every car
that uses it, so **choose the set** (`[chassis] tyre_set`). No chassis or suspension field scales
grip. Only `PressureSetting` (`bb9616f6`) and camber act on it indirectly.

## 6. Open items

- Settle how brake bias and brake pressure combine (the "2x split" question).
- Prove the BodyDragBase units and identify `67caa092` / `56e0a3ab`.
- About 500 chassis keys (AI, FFB, damage, many `[GENERAL]` scalars) are only surveyed.
  `fields.describe` reports them as `unknown` with their section, type and a sample value.
