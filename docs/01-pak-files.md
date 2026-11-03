# 01: Pak files (`.bff`) and the pak registry

All game content lives in `.bff` paks under `Pakfiles\`, in subfolders such as `Vehicles\`,
`TRACKS\`, `Scripts\` and others. Each car has three paks:

- `Vehicles\<Car>.bff`: meshes, materials, physics, render files.
- `Vehicles\<Car>_Cockpit.bff`: the interior.
- `Vehicles\<Car>_Livery.bff`: the liveries.

## Format (PC, AMS2 / PCARS2 lineage) [file]

| Part | Details |
|---|---|
| Header | `0x130` bytes, magic `" KAP"`. The byte at **`0x12D`** is the encryption flag: **0 = none, and the game loads it [proven]**. |
| TOC | One `0x2A`-byte entry per file: `uid u64, offset u64, stored size u32, original size u32, mtime u64, compression u8, pad u8, crc u32`. |
| TOC CRC | At entry `+0x22`: **`~crc32(bytes as stored)`**, i.e. the compressed or encrypted bytes. **Must be recomputed** when you write a pak, or the game stops with a CRC error [proven]. |
| Path uid | Bob Jenkins **lookup8** hash of the lower-case path (`pak_tool.path_uid`). |
| Extension header | Starts with `Reiza.xml` / `PC`, followed by the name table: 1-byte length + path, one per file. |
| Load groups | An optional `DHSA` block of (first, count, span) groups. Livery paks have none. |
| Data | Aligned to 16 bytes. |
| Compression | Per file: `0` stored, `1` zlib (raw deflate or zlib header), `3`/`4` **Oodle** (`oo2core_4_win64.dll` ships with the game). |

### Encryption (base-game paks) [file]

When the flag is set:
- The TOC and the file data are **RC4**-encrypted. The keys are PCarsTools' `_keys_PC2AndAbove` set,
  deobfuscated and **truncated at the first `0x00`**; the Lancer pak used key 4. Find the key by
  decrypting the first 64 TOC bytes and checking for zero padding.
- The extension/name table is encrypted with **Scribe**, a cipher like RC6 (16-byte blocks). The table itself is
  `align16(ext_size - 0x308)` bytes (what PCarsTools reads); the writer also Scribe-encrypts zero padding after it
  in whole blocks up to `sec_pos` (or the data offset if there is no section block). The region is **not** always a
  multiple of 16: the last `(end - start) % 16` bytes are plain zeros (e.g. `VW_Virtus_GTS_Livery.bff`;
  32 liveries plus `vehiclespersistent.bff`), and in `vehiclespersistent.bff` encryption also stops 64 KiB in, followed by plain zero blocks.
  `pak_decrypt_twin.ext_region` handles both: round down to 16, then drop trailing all-zero blocks. [proven, all 1494 encrypted vehicle paks]

**New car paks do not need any encryption.** Write them with flag 0 and correct CRCs.

## `Pakfiles\PakDirInfo.dat` ("RIDP"): the pak registry [proven]

The game **ignores any pak that isn't listed here**. Each entry is:

```
uid("pakfiles\vehicles\<name>.bff")   lookup8 of the lower-case relative path
metadata end                          offset where the file data starts
max load-group stored span
max load-group original size
0x31                                  constant flag
```

The list is **unsorted**: append new entries at the end. A game update may rewrite this file, so
re-run `install_byd.py install` after updates. Keep a backup of the original
(ams2kit keeps one in `%LOCALAPPDATA%\ams2kit\backup\PakDirInfo.dat`).

## How files resolve across paks [proven]

- Files resolve **by full path across all mounted paks**. A file in our car pak at a donor path
  (for example `vehicles\lamborghini_veneno\lambo_veneno_body_loda.meb` or
  `vehicles\physics\chassis\lamborghini_veneno.cdfbin`) overrides the donor's copy **while our car is loaded**.
- Text tables (`text\*.tdb`, loaded from `BOOTFLOW.bff` at boot) are **not** overridden by car
  paks or by loose files. See doc 05.

## Tools

| Script | Use |
|---|---|
| `pak_tool.py` | Read and write **unencrypted** paks: `read_pak(path)` gives `Pak(name, entries, groups, ...)`; `write_pak(pak, path)` recomputes uids, CRCs and alignment. An `Entry` has `.path` and `.data()`; `Entry.from_file(path, bytes, mtime)` makes a new one. |
| `pak_decrypt_twin.py` | Writes a decrypted copy of an encrypted pak, with CRCs recomputed. That's how the donor paks were made (`byd_build\plain\`). |
| `pak_extract.py <pak> <out> <substr>...` | Pulls selected files out of an **encrypted** pak (RC4 + zlib/Oodle). As a module: `open_pak(path)` returns `(f, key, entries)`, and `read_entry(f, key, e)`. |
| `verify_pak.py` | Compares a pak against extracted files. |
| `pakdirinfo.py` | `read`, `write`, `entry_for(pak_file, rel_path)` for the registry. |
| `tools\PCarsTools` 1.1.4 | Nenkai's extractor; needs .NET 6, so run it with `DOTNET_ROLL_FORWARD=Major` on newer .NET. |

To find which pak holds a file, loop over `glob(Pakfiles/**/*.bff)` with `pak_extract.open_pak` and
filter the entry names. Several one-off searches in this project did exactly that.
