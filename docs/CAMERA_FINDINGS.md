# Verified serialized course-select offset tables

Inspected 2026-10-20, read-only. These findings establish serialization, not the
final effects on camera movement, clipping, interpolation, player positioning,
or level events. No executable patch was generated.

## Target and reproduction

The provided `code/red-pro2.rpx` has SHA256
`ebd147ce4cdedb563db3ac6278186ca5dea282ad315271925b8bb5ac16c7dc8e`.
Every address below is a virtual address from **that exact ELF**, not a portable
file offset or an offset valid for other regions/revisions. The camera-loader
function names are not present in the inspected upstream symbols and are left
unnamed here.

```
py tools/inspect_camera.py "NSMBU Modding Project/content/Common/course_select/MarioOffsetDataW1.bin"
py tools/inspect_camera.py "NSMBU Modding Project/content/Common/course_select/LookOffsetDataW1.bin"
```

Optional disassembly is read-only and requires Capstone. The research installation
was isolated under ignored `build/analysis-deps`:

```
py -m pip install --target build/analysis-deps capstone
py tools/inspect_camera.py --rpx "NSMBU Modding Project/code/red-pro2.rpx" --range 0x029ce124:0x029ce1f4 --capstone-path build/analysis-deps
py tools/inspect_camera.py --rpx "NSMBU Modding Project/code/red-pro2.rpx" --range 0x029ce628:0x029ce6f4 --capstone-path build/analysis-deps
```

The tool parses RPX section headers, decompresses flagged sections in memory,
checks their declared sizes, and locates the requested range by ELF address.
It does not extract or modify executable sections. Capstone 5.0.9 can mislabel
Wii U paired-single instructions as VMX instructions; the proof below uses only
ordinary integer, branch and floating-point load/store instructions. Raw words
are included in its output for independent verification.

## Endianness evidence

Both loaders set stream byte order to `1`: Mario at `0x029ce124` (`li r4,1`),
then `0x029ce12c` (`bl 0x02a16c38`); Look at `0x029ce628`/`0x029ce62c`.
The called routine at `0x02a16c38` is `stw r4,8(r3); blr`.

This matches public SEAD `Stream::setBinaryEndian`, which stores `mSrcEndian`,
and `Endian::cLittle = 1`. Primary sources in the inspected Tsuru checkout
`69a01d3a1ef8ecfc85a26141977a5ace87fec23f`:

- [seadEndian.h](https://github.com/Zenith-Team/Tsuru/blob/69a01d3a1ef8ecfc85a26141977a5ace87fec23f/lib/sead/engine/library/include/prim/seadEndian.h): `cBig=0`, `cLittle=1`.
- [seadStream.h](https://github.com/Zenith-Team/Tsuru/blob/69a01d3a1ef8ecfc85a26141977a5ace87fec23f/lib/sead/engine/library/include/stream/seadStream.h): stream field layout and read methods.
- [seadStream.cpp](https://github.com/Zenith-Team/Tsuru/blob/69a01d3a1ef8ecfc85a26141977a5ace87fec23f/lib/sead/engine/library/modules/src/stream/seadStream.cpp): setter and endian argument propagation to float/u32 reads.

The ordinary float-reference read at `0x02a16e40` calls the float-return reader
at `0x02a16d00`, then `stfs f1,0(r31)`. The u32-reference read at
`0x02a16d80` calls `0x02a16c80` then stores the returned integer. Together with
the explicit little-endian stream setting, these establish the numeric wire
format independently of whether decoded values look plausible.

## MarioOffsetData: exact packed layout

All nine provided world files contain exactly **5376 bytes**:
two banks, each with 128 records. Each record is **21 bytes**, without alignment
padding: Python `struct.Struct('<5s3fI')`.

| Record offset | Size | Verified serialized value |
| --- | ---: | --- |
| 0 | 5 | Raw name bytes, commonly four ASCII characters followed by NUL |
| 5 | 4 | First little-endian float32 component |
| 9 | 4 | Second little-endian float32 component |
| 13 | 4 | Third little-endian float32 component |
| 17 | 4 | Little-endian unsigned 32-bit value, meaning unverified |

Bank `b`, slot `i` starts at `(b*128+i)*21`, with `b=0..1`, `i=0..127`.
Raw name bytes and the unsigned field must be preserved; NUL termination,
boolean semantics and unused-byte cleanup are not imposed by the tooling.

Loader evidence:

- `0x029ce0b8` constructs string address `0x1018a0bc`,
  `course_select/MarioOffsetDataW%d.bin`; world argument is incremented by one.
- `0x029ce150`: outer count 2; `0x029ce15c`: per-bank count `0x80`.
- `0x029ce178..0x029ce1b0`: loop reads exactly five bytes via `0x02a16c40`.
- `0x029ce1c8`, `0x029ce1d4`, `0x029ce1e0`: three float-reference reads.
- `0x029ce1f0`: one unsigned 32-bit reference read.
- Name comparison with runtime table entries precedes assignment at
  `0x029ce338..0x029ce404`. Components are stored at runtime record +0x14,
  +0x18, +0x1c; trailing integer at +0x20. Runtime record stride is 0x24,
  which must **not** be confused with serialized stride 21.
- `0x029ce410..0x029ce420` advances the bank and repeats twice.

Example observed W1 bank 0 data:

| Slot | Name bytes | Components | Unknown u32 |
| --- | --- | --- | ---: |
| 0 | `W1S0\0` | (0, 60, 0) | 1 |
| 1 | `W101\0` | (110, 60, -260) | 0 |
| 2 | `W102\0` | (0, 60, -260) | 0 |
| 3 | `W103\0` | (0, 300, 440) | 0 |
| 4 | `W104\0` | (-200, 180, 300) | 1 |

The filename and point names suggest camera/player-relative positions, but the
consuming code and coordinate-space semantics were not traced. The editor must
label these as raw components, not promise a particular camera effect.

## LookOffsetData: exact packed layout

All nine provided files contain **744 bytes**: two banks of 31 records, each
three little-endian float32 components, Python `struct.Struct('<3f')`.
There is no serialized name, integer, header or inter-record padding.
Bank `b`, slot `i` starts at `(b*31+i)*12`, `b=0..1`, `i=0..30`.

Loader evidence:

- Function entry `0x029ce500`; `0x029ce5a8` constructs string pointer
  `0x1018a0e4`, `course_select/LookOffsetDataW%d.bin`.
- `0x029ce61c` supplies exact size `0x2e8` (744).
- `0x029ce638` sets outer count 2; `0x029ce654` inner count `0x1f` (31).
- `0x029ce66c`, `0x029ce678`, `0x029ce684` read three floats.
- Values are stored at runtime record +0x0c, +0x10, +0x14; runtime stride
  advances by 0x18 at `0x029ce6d8`.
- `0x029ce6e4..0x029ce6f0` advances runtime bank by 0x2e8 and repeats.
- `0x029ce73c..0x029ce74c` advances worlds, outer count nine.

W1 bank 0 slot 6 is (0, 50, 12); all other W1 vectors are zero. W3 has
nonzero bank 0 slots 4=(-140,0,0), 7=(-104,0,0), 10=(-172,0,0),
13=(-260,0,0). Other supplied Look world files are zero-filled. The mapping
from these slot numbers to game states, nodes or events remains unverified.
Do not equate them with CSV row indices merely because some numbers coincide.

## Known interfaces and unresolved meaning

The inspected [nsmbu-headers checkout](https://github.com/nsmbu/headers/tree/bb923aede585a06924669c0d496bb4b784ab6f2c)
does not provide a `CourseSelectCamera.h` or decoded camera offset-table class.
[CourseSelectPathPoint.h](https://github.com/nsmbu/headers/blob/bb923aede585a06924669c0d496bb4b784ab6f2c/course_select/CourseSelectPathPoint.h)
does expose flags `FixX`, `FixY`, `FixZ`, `Focus`, `Scale`, `Stop`, etc., plus
normal/secret successor-name arrays. The corresponding CSV flag text is visible
in actual resources, but which flags affect camera, Mario, route movement or
multiple consumers is not fully established.

Tsuru `modules/customactors.yaml` identifies a hook at `0x021b9350` with comment
`CourseSelectCamera::onCreate()`. This is upstream annotation, not a locally
confirmed class layout; it must not be treated as an offset-table parser address.
`DVCameraParam`/`DVCameraParamList` headers belong to distant-view systems and
should not be repurposed as a course-select camera schema.

The two offset banks plausibly correspond to subworld variants, given the two
runtime banks and course-select world structure. This remains a hypothesis;
the new API intentionally calls them bank 0 and bank 1.
Observed non-placeholder named records in bank 1 occur only in W5 (29), W8
(20), and W9 (55), consistent with the a/b archive split in those worlds.
This correlation supports the hypothesis but does not trace its consumer.
The trailing Mario u32 is emphatically not established as a boolean: values
including 32, 64, 65 and 72 occur in the actual tables.

## Topology loader cross-reference starting points

The same RPX contains confirmed string construction instructions near the
course-select path code:

| Instruction | Constructed string address | String |
| --- | --- | --- |
| `0x021d0a38` | `0x100447f4` | `pointW%x.csv` |
| `0x021d0a78` | `0x10044804` | `pointW%x%c.csv` |
| `0x021d0ab0` | `0x10044814` | `routeW%x%c.csv` |
| `0x021d0acc` | `0x10044824` | `routeW%x.csv` |

Use `--range 0x021d0a20:0x021d0ad8` to reproduce. Those references narrow the
loader region but do not yet prove the semantics of every CSV column or the
unlock behavior. No guessed executable patches follow from these references.

## Implemented and tested

`worldstudio/camera.py` provides strict `OffsetTable.parse(data, kind)`,
`record(bank,index)`, immutable `with_vector(bank,index,components)`, and
`build()`. Unknown fields and all five raw name bytes survive export. It rejects
wrong sizes/counts, invalid banks/slots, nonfinite or non-float32 components,
and malformed unsigned fields. It never opens or writes source files itself.

`py -m unittest discover -s tests -p test_camera.py -v`: seven tests passed,
including all 18 local offset files byte-identically round-tripped in memory,
synthetic little-endian fixtures, preserved negative-zero bits/raw name bytes,
isolated 12-byte component edits, and malformed-input guards. These are offline
format tests. **No camera resource edit was tested in Cemu by this task.**

