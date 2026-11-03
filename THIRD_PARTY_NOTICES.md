# Third-party notices

## PCarsTools

ams2kit's pak support is derived from **PCarsTools** by Nenkai:
<https://github.com/Nenkai/PCarsTools>

| File in this repository | Relationship |
|---|---|
| `ams2kit/BPakFileEncryption.cs` | Copied from PCarsTools (`PCarsTools/Encryption/BPakFileEncryption.cs`); ams2kit reads the key tables from it at run time. Not compiled or modified. |
| `ams2kit/pak_decrypt_twin.py` | Python port of PCarsTools' pak decryption (RC4 / "Scribe" table decryption). |
| `ams2kit/pak_tool.py` | Python port of PCarsTools' `BHashCode` (Bob Jenkins' lookup8) path hashing. |

These files remain subject to the PCarsTools license and copyright; the MIT license in [LICENSE](LICENSE)
covers the rest of ams2kit. Please check the PCarsTools repository for its current license terms and keep
this notice with any redistribution.

Thanks to Nenkai for publishing PCarsTools.
