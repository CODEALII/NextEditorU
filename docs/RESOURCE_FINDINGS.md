# Local resource inspection

Inspected 2026-10-20. All input files were opened read-only. No original game
payload is included in this document. Short field examples explain the format.

## Reproduction

```
py tools/inspect_resources.py "NSMBU Modding Project/content/Common/course_select/CS_W1.szs"
py tools/inspect_resources.py "NSMBU Modding Project/content/Common/course_select/CS_WorldMap.szs"
```

`tools/inspect_resources.py` is a standalone standard-library inventory helper;
its `yaz0` and `sarc` functions can inspect entries in memory. It does not extract
assets or modify any files. Use `PYTHONIOENCODING=utf-8` when printing CP932 text
on a Windows terminal whose default encoding cannot display Japanese.

## Confirmed archive layout

All 13 SZS files in `content/Common/course_select` were successfully decompressed
and their SARC member tables parsed. They use Yaz0 compression around SARC.
The SARC BOM is `FE FF` (big endian). World archives are:
`CS_W1`, `CS_W2a`, `CS_W3`, `CS_W4`, `CS_W5a`, `CS_W5b`, `CS_W6a`, `CS_W7`,
`CS_W8a`, `CS_W8b`, `CS_W9a`, `CS_W9b`, plus `CS_WorldMap`.

Every per-world archive contains `point<world>.csv`, `route<world>.csv`, and
`CS_<world>.bfres`. Some also contain SHARC/SHARCFB shader resources.
`CS_WorldMap.szs` contains a BFRES and two shader resources, **no CSV files**.
The per-world archives are therefore the first topology investigation target.

For W1:

| Entry | Bytes |
| --- | ---: |
| `routeW1.csv` | 2052 |
| `pointW1.csv` | 1646 |
| `CS_W1.bfres` | 11546624 |

Original `CS_W1.szs`: 6656908 bytes; Yaz0 declared/decompressed size 11571200;
SHA256 `d2547f5bfa9963d05916816301a0b53e8916ab62628210409be232228b117cf0`.
Original `CS_WorldMap.szs`: 426676 bytes; decompressed size 1521118;
SHA256 `eb6045fcb1dd86cb8fb0b80366f473bfacdf7dcc3f54aaae23ffcd5bc160fd52`.

## CSV observations (not a complete runtime schema)

W1 CSV bytes decode successfully with CP932. Records use CRLF; Python universal
newline conversion can make them appear doubled, so binary decode or
`newline=""` is important. There is no header. Point records have nine fields;
route records have three. Quoted cells contain comma-separated lists.

Example point record: `1,W101,,"W102","RW101W102",,"",,`.
The first cell is an index; second is a point identifier. The third cell contains
flags such as `restart`, `fixY`, `merge,restart,stop`, `dokan`, or `focus`.
Observed fields 3 and 4 reference destination points and route names respectively;
fields 6 and 7 hold additional point/route references in some records. Whether
these are normal/secret exit unlock fields must be confirmed from loader code
and emulator behavior, not inferred from the CSV alone.

Example route record: `RW101W102,道,`. Other observed second-cell values include
`坂`, `石`, `ジャンプ`, `雲`. Their exact movement-type interpretation is not
proven by this resource inspection.

Route identifiers often encode `R` plus two four-character point/bone IDs.
Intermediate `F...` and `K...` segments occur. Point CSV references can denote a
longer logical route than an individual route CSV row: W102 references
`RW102W1T0` while route CSV includes `RW102F021`, `RF021K022`, and subsequent
segments ending at `W1T0`. A validator must not reject every point route reference
that lacks an identical route CSV row without checking BFRES.

## BFRES observations

All world BFRES entries begin `FRES 03 00 00 01 FE FF 00 10` (version bytes and
big-endian BOM observed directly). W1 BFRES ASCII string entries include `W101`,
`W102`, `W103`, `W104`, `W105`, `F021`, `K022`, `RW101W102`, `RW102W1S0`,
`RW102W1T0`, `CS_W1`, `CS_W1_Synchro`, `CS_W1_World`, `courseOBJ`.
They also include similarly named material references. This establishes shared
names across CSV and BFRES but **does not by itself establish that a string is a
bone, a model, a shape, or a route animation**. No raw string-search offset
should be presented as a runtime address.

W1 BFRES string `RW101W102` occurs at file offset 470408; `W101` at 470936.
These are reproducible byte positions in the inspected asset only.

Sibling binary resources: `LookOffsetDataW1.bin` through W9 are 744 bytes each;
`MarioOffsetDataW1.bin` through W9 are 5376 bytes each. Their field schemas are
not confirmed here and should remain opaque until traced to loader code.

## Emulator / executable environment

- Python launcher available: Python 3.14.7; Git and Node available.
- `C:\Users\Ali\Documents\Cemu_2.6\Cemu.exe` exists. Directory naming is not
  executable-version evidence. Existing `log.txt` identifies its prior run as
  **Cemu 1.26.2f**, title `00050000-10101d00`, title version v64, updated RPX hash
  `050034fc`, loaded module checksum `6caea914`.
- No Cemu, Java, or Ghidra process was running at inspection time.
- No Ghidra command on PATH or matching installation found in the limited checked
  Desktop, Downloads, Program Files, Scoop apps and Documents top-level folders.
  This is not an exhaustive disk search.
- Supplied `code/app.xml` declares update title ID `0005000E10101D00`, version
  `0040`, SDK 20806. `red-pro2.rpx` exists and is 8356928 bytes. A clean full base
  game is not established merely by these update metadata files.
- Existing Cemu settings target `Games/NSMBU/code/red-pro2.rpx`, with update
  resources in `mlc01/usr/title/0005000e/10101d00`. The prior log/settings enable
  `Cloudy SMBU 2`, graphics, LOD and crash-fix packs. These can override resources
  or affect integration results. A test must use an isolated pack and verify
  which update/base/archive is actually loaded before attributing behavior.

No emulator run was performed by this inspection task. CSV parsing and archive
inspection establish offline resource structure, not in-game movement,
unlocking, camera, level launch, or geometry compatibility.

## RPX static evidence

```
py tools/inspect_resources.py --rpx "NSMBU Modding Project/code/red-pro2.rpx"
```

The supplied executable is ELF32 big endian, ELF identification bytes
`7f454c46010201cafe00000000000000`. Its section table has 37 entries of 40
bytes. Section 3 is compressed using the Wii U RPX section flag `0x08000000`;
its four-byte uncompressed-length prefix plus zlib data decode to 1847488
bytes. All decoded section lengths passed the declared-length check. Section 3
declares virtual address `0x10000000`. The following are **string addresses in
this specific ELF**, not discovered function addresses or universal patch sites:

| ELF virtual address | String |
| --- | --- |
| `0x10043064` | `course_select/CS_W1.szs` |
| `0x100447d0` | `course_select/%s.szs` |
| `0x100447f4` | `pointW%x.csv` |
| `0x10044804` | `pointW%x%c.csv` |
| `0x10044814` | `routeW%x%c.csv` |
| `0x10044824` | `routeW%x.csv` |
| `0x1018a0bc` | `course_select/MarioOffsetDataW%d.bin` |
| `0x1018a0e4` | `course_select/LookOffsetDataW%d.bin` |

These give reproducible starting points for Ghidra cross-references. This
inspection did not trace callers or establish the semantics of their fields.

## Isolated emulator setup helper

`tools/prepare_cemu.py --cemu <Cemu directory or executable> --patch
build/three-level-chain --out <new distinct directory>` copies the emulator,
runtime resources, installed system-title resources if available, CrashFix,
and the generated patch into a new output directory. It writes fresh settings
with only CrashFix and WorldStudioChain enabled, its own `mlc01`, no online
account, no Discord presence and no automatic updates. It refuses an existing
output directory and does not launch anything.

The generated `launch.ps1` accepts an explicit game RPX path, sets the isolated
working directory, and invokes `-g <RPX> -m <isolated mlc01>`. Keyboard profile:
Z = A, X = B, C = X, V = Y, Enter = Plus, arrows = D-pad, WASD = left stick.
Schema evidence comes from the inspected local XML profiles and official Cemu
source:

- [InputManager.cpp](https://github.com/cemu-project/Cemu/blob/main/src/input/InputManager.cpp): XML loading and mapping entries.
- [KeyboardController.cpp](https://github.com/cemu-project/Cemu/blob/main/src/input/api/Keyboard/KeyboardController.cpp): Keyboard controller identity.
- [VPADController.h](https://github.com/cemu-project/Cemu/blob/main/src/input/emulated/VPADController.h): button mapping ID enumeration.
- [wxWindowSystem.cpp](https://github.com/cemu-project/Cemu/blob/main/src/gui/wxgui/wxWindowSystem.cpp): Windows virtual-key interpretation.
- [LaunchSettings.cpp](https://github.com/cemu-project/Cemu/blob/main/src/config/LaunchSettings.cpp): `-g` and `-m` arguments.

Current upstream source was inspected; compatibility with the local legacy
binary remains a runtime check. A temporary-fixture test passed for setup,
fresh XML settings, expected mapping IDs, preservation of input bytes, and
refusal to overwrite an existing destination. No emulator executable was
launched by that fixture test.

Legacy setup detail verified against official [v2.0 CemuApp.cpp](https://github.com/cemu-project/Cemu/blob/v2.0/src/gui/CemuApp.cpp)
and [v2.0 CemuConfig.cpp](https://github.com/cemu-project/Cemu/blob/v2.0/src/config/CemuConfig.cpp):
`gp_download` maps to `did_show_graphic_pack_download`, and false triggers the
first-run wizard. The helper therefore sets it **true** to mark setup complete;
this is not an automatic-download switch. It also sets `permanent_storage` false
to prevent legacy Cemu using shared `%LOCALAPPDATA%/Cemu/perm_setting.xml`
([PermanentStorage.cpp](https://github.com/cemu-project/Cemu/blob/v2.0/src/config/PermanentStorage.cpp)).
Both emitted values passed a temporary XML fixture assertion.

Legacy input detail: the helper now emits both `controllerProfiles/controller0.txt`
and `.xml`. Cemu 1.26's INI syntax is `[General]` with `emulate = Wii U GamePad`
and `api = Keyboard`; `[Controller]` mappings use `key_90` for Z, `key_13` for
Enter, etc. These are decimal Windows virtual-key values. The `button_` prefix
is for controller bitmasks, not keyboard keys. Official
[v2.0 InputManager.cpp](https://github.com/cemu-project/Cemu/blob/v2.0/src/input/InputManager.cpp)
lines 385-407 migrate legacy `key_` values to XML with decimal parsing, and lines
226-257 show that keyboard does not require a controller GUID. A temporary
fixture confirmed exact equality between the generated INI and XML mappings.
