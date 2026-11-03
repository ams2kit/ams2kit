# 02: Getting a new car into the car list

## The mod loader [proven]

AMS2 has a built-in mod loader for extra vehicles. Each mod is a folder under `<game>\UserData\Mods\<ModName>\`:

| File | Content |
|---|---|
| `<ModName>.xml` | Reflection XML with a `ModDetails` record (`Name`, `DisplayName`). |
| `vehiclelist.lst` | One line per car: `vehicles\byd_seal\byd_seal.crd`. |
| `driveline.rg` | A driveline record for the car; see below. |

At startup the game merges the mod's vehicle list into the global `VehicleDetails` list
(the base list has 512 entries). It also writes
`Documents\Automobilista 2\modsupport\driveline`.

`driveline.rg` reuses an existing driveline under a new record name:

```
RECORD AWD_BYD_SEAL_01 l_driveline
	name "BYD_SEAL"
	contents AWD_VENENO_SEQUENTIAL_SVA_FLEX_v3
	dl:minhz	6000
```

## The `.crd` vehicle definition

A `.crd` is reflection XML:
- a header of `<class ...>` blocks that declare every property and its type;
- a `<data class="VehicleDetails">` block with the values.

Start from the donor's crd, which lives in `BOOTFLOW.bff`:
`vehicles\lamborghini_veneno\lamborghini_veneno.crd`. Put ours at `<game>\Vehicles\byd_seal\byd_seal.crd`
**and** inside the car pak.

Props we set (see `build_byd_modfiles.py`, `PROPS`):

| Prop | Value / meaning |
|---|---|
| `Name` | `BYD_Seal`. The internal name; menu image paths are built from it (doc 05). |
| `Vehicle Name`, `ShortVehicleName`, `VehicleModel` | Display names. |
| `VehicleManufacturer` | `BYD`. The logo is looked up as `manufacturerlogos\<lowercase, no spaces>.dds`. |
| `XLASTID` | **558**: the next id after the base game's highest. 9001 looked suspicious, and we avoided it. |
| `Vehicle Class` | `Street`: the car appears under Street Cars. |
| `Vehicle Render Model` | `BYD_Seal.vhf`. |
| `Vehicle Physics Model` | `BYD_Seal`, which resolves `vehicles\physics\vehicles\byd_seal.vdfm`. |
| `Driver Character`, `Cockpit properties` | Still the donor's (`Lamborghini_Veneno`, `Lamborghini_Veneno_Cockpit.bin`). |
| `Vehicle Description`, `Vehicle Year`, `Region`, `Country`, wheel diameters, `Engine Placement` | Display info. |

### The silent-failure trap [proven]

The game **silently rejects the whole
crd** ("Failed to load the data") if the header declares a property the data section doesn't
contain. The car then never appears, and nothing is logged. To drop a prop (we dropped `DLC ID` and
the exhaust positions), **delete its `<prop name="X" type=...>` line from the header too**.
This was the root cause of "the car doesn't show in the list" after many other guesses.

Things that turned out **not** to matter: `XLASTID` (558 vs 9001), DLC-style registration.
Loose crd files that override **base** cars are not read.

## Car classes

`Vehicle Class` must be an existing class (`Street`, `GT3`, ...). Adding a **custom class** with its
own logo is still open. The class logos are in `GUI\VehicleClassLogosHUD` and the class list is in
the boot data; this needs research.

## Liveries

The livery names and ids come from `<car>.rcf` (`NAMES` block, `<NAME LIVERY="51" NAME="...">`); the
Veneno uses ids 51–59. Our copy still has the Veneno's livery names ("Lamborghini Veneno #01").
