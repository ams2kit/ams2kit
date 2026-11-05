# 16: Engine sound: sound kits and FMOD bank samples

Code: `ams2kit\ams2kit\sound.py`; tests: `ams2kit\tests\test_sound.py`. UI: the **Sound** step.

## Where a car's sound comes from [file]

The car pak's **`vehicles\<car>\<car>.csdbin`** picks the sound (doc 11, section 5). The crd does not
name it. Our builds already carry a car-named copy of the donor's csdbin, so a car sounds like its donor.

The csdbin is a serialized-struct file (header `51 02 01 05`, the same container as the vdfm, doc 12)
with five sections:

| Kind | Content |
|---|---|
| `0x01` | The struct: floats (sound parameters), then a pool of NUL-terminated strings at its end. |
| `0x10` | Relocations: u64 offsets of the pointer fields in section `0x01`; each holds an offset into that section. |
| `0x32` | A second string table (`AMS2_open_wheeler`, `RaceCarSemiSlick_V4_set4`: tyre sound sets?). |
| `0x33` | (field offset, string offset) pairs for section `0x32`. |
| `0x50` | 12 bytes: type id. |

The pool strings are FMOD bank paths without extension (`Audio/AMS2/Vehicles/Sort/L/Lamborghini_Veneno_AMS2`,
loaded from `<game>\Audio\...\<name>.bank`), FMOD event paths (`event:/AMS2/.../Lamborghini_Veneno_EngineExt`)
and a few bank-relative names (`Exhaust/Car/Exhaust/Backfire/GT_Backfire_Ext`).

`sound.write_csd` rebuilds the pool and fixes the pointers. With no change it reproduces **all 267** base
csdbins byte for byte, and its output passes the section-size check (`physics.serial_layout_ok`).

Each car names its **engine banks** (main + `_AI`, under `Audio/AMS2/Vehicles/Sort/` or, for the VW TSI
cars, `Audio/VW_DEMO/Engine/`) and shared banks (rev limiter, gear shift, turbo, gear whine). 162 distinct
engine sounds over 267 cars; some engine banks serve up to 8 cars. Every car also names
`Audio/Surface/WindBuffeting`, which doesn't exist on disk, so the game tolerates a missing bank.

## Sound kits [file]

A **kit** is another car's whole csdbin, copied over the car-named one: banks, events and the struct's
parameters together (they belong to that engine). `[sound] kit = "<car name>"`, or the Sound page.
`sound.kits()` reads every car's csdbin once and caches the list in `%LOCALAPPDATA%\ams2kit\sound_kits.json`.

Not yet verified in game: that the game reads the car-named csdbin rather than the donor-path one
(both are in our pak). **[guess, needs an in-game test]**

## FMOD banks [file]

FMOD Studio banks, `RIFF` form `FEV `, format version `0x50` (all 533 banks of the game). The FMOD
runtime is linked into the exe (no fmod DLL). Event paths are not in the car banks: they live in
`Audio\MasterBank.strings.bank` (a compressed trie, not decoded yet).

```
RIFF 'FEV '
  FMT  (u32 0x50, u32 0x46)
  LIST PROJ
    BNKI         bank GUID ...
    LIST IBSS/GBSS/MBSS/BEFX/...   buses, effects (per-event input/master buses, group buses)
    LIST EVTS    events (EVNT/EVTB: GUID first)
    ...          timelines, parameters, instruments, curves
    LIST WAVS    waveforms: WAV = GUID, u16 0x0C, u16 FSB index, u16 0, u32 subsound index,
                 u32 1 when the sample stays compressed in memory (Vorbis) else 0
    SNDH         u16 2n+1, u16 8, n x (u32 absolute offset, u32 size) of the FSB5 blocks
    STDT         (empty in car banks)
  SND  (padding so the FSB5 starts 32-byte aligned) FSB5 ...      one per FSB block
```

Car banks hold one or two FSB5 blocks: mode `0x10` **FADPCM** (FMOD's ADPCM; idle/low loops, starters)
and mode `0x0F` **Vorbis** (most engine loops). FSB5 sample headers are the usual u64 bit field (rate
index, channel code, data offset in 32-byte units, frame count) plus chunks: 3 = loop (start, end
inclusive), 11 = Vorbis setup CRC + seek table, 13 = peak volume, 5 = unknown (a loop start copy).

### FADPCM [file]

Frames of 0x8C bytes = 256 samples of one channel; channels interleave frame by frame. Frame: u32 coef
indexes and u32 shifts (one nibble per 32-sample subframe), s16 hist1, s16 hist2, then 128 bytes of
nibbles (low nibble first). Coefficients (×64): (0,0) (60,0) (122,60) (115,52) (98,55).
Check: each frame's stored history is the encoder's input before the frame; our decoder ends the
previous frame within a median 17 LSB of it on the Veneno bank (a wrong table gives ~6000).

Vorbis needs a real decoder: ams2kit hands single-subsound FSB5 files to `vgmstream-cli` when it is set
in Setup (optional).

## Replacing samples [file; in game: untested]

`sound.rebuild_bank` keeps the bank byte for byte and only:
1. appends a new FSB5 block with the replacement samples as **PCM16** (FMOD plays any FSB codec);
2. points the replaced waveforms (WAV chunks) at it (FSB index, subsound, "decompressed" flag);
3. rewrites SNDH and the RIFF/PROJ sizes.

So the events, RPM/load crossfades, effects and the other samples are untouched, and no encoder is
needed. The build writes the bank to `build\install\Audio\AMS2KIT\<car>\<bank>.bank` (installed with the
receipt like every loose file) and points the car's csdbin at `Audio/AMS2KIT/<car>/<bank>`.

Limits:
- The rebuilt bank keeps the original's **GUIDs** (bank, events, waveforms), so the game can load only
  one of the two: don't race the car alongside a car that uses the same engine bank (Check lists them).
  Changing the GUIDs would need the csdbin to name events by `{guid}` instead of by path, and the event
  path → GUID map from the strings bank. **[next step]**
- Lengths may change; loops come from the WAV's `smpl` chunk, else the original loop (scaled).
- Shared banks (gear shift, limiter, turbo) are left alone: editing them would change every car.
- FMOD Studio cannot open `.bank` files and we don't have the game's FMOD project, so "editing in FMOD"
  means rendering new samples (from FMOD Studio, a DAW or recordings), not editing the events.
