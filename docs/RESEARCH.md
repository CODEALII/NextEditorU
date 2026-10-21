# NSMBU overworld research

Research date: 2026-10-20. Sources were cloned from their public upstreams into `external/` and inspected locally. These are source-confirmed interfaces, not proof that a patch has run on the user's game. Any addresses below belong to upstream maps/headers and must be matched to the actual executable/version before use.

## Reproducible source snapshots

| Project | Commit inspected | License file | Relevant contribution |
| --- | --- | --- | --- |
| [Cobra](https://github.com/RoadrunnerWMC/Cobra) | `0b8d3927a4466e5061367dbb69c03fcd3eeaec3b` | `LICENSE`, GPL-3.0 | RPX/RAM event-script analysis, text export, WMSC encoding |
| [Tsuru](https://github.com/Zenith-Team/Tsuru) | `69a01d3a1ef8ecfc85a26141977a5ace87fec23f` | `LICENSE`, MPL-2.0 | Legacy code injection, actors, script loader, symbol map |
| [NSMBU-CSScript](https://github.com/Ryguy0777/NSMBU-CSScript) | `26797c51b20af47dfcf59256bac0dcc192ed26aa` | `LICENSE.txt`, MPL-2.0 | Current RedCore module for externally supplied WMSC scripts |
| [Pyamoto](https://github.com/Zenith-Team/Pyamoto) | `0420d3b1487f41bc9095691b2d02555888e28a02` | `license.txt`, GPL-3.0 | Course editor, Yaz0/SARC workflows; not a complete overworld editor |
| [RedCore](https://github.com/Zenith-Team/RedCore) | `a1b7ff2c38699e9086dcb11d5e0ce4a80abbee6c` | `LICENSE.txt`, MPL-2.0 | Current C++ API and target/address conversion maps |
| [nsmbu/headers](https://github.com/nsmbu/headers) | `bb923aede585a06924669c0d496bb4b784ab6f2c` | No top-level license found | Public reverse-engineered interfaces; research only, do not vendor into distributed code without resolving licensing |

Run `git -C external/<name> rev-parse HEAD` to reproduce each identity. Clones are independent upstream repositories and must not be added wholesale to the tooling repository. Respect file-level licenses when reusing implementation code.

## Node and route topology

The strongest current public evidence is in [CourseSelectPathPoint.h](https://github.com/nsmbu/headers/blob/bb923aede585a06924669c0d496bb4b784ab6f2c/course_select/CourseSelectPathPoint.h):

- `CourseSelectPathPoint` has a name, four ordinary successor names, and four secret successor names. Public accessors are `getName`, `getNextPoint(idx)`, and `getNextPointSecret(idx)`.
- The source declares `FixedSafeString<5>` for each of those names. These are runtime C++ objects, **not five-byte disk records**.
- It declares attribute, enemy, trap and placement flag groups and asserts a runtime object size of `0x448`.
- Attributes include stop/link flags, scale/fixed-coordinate/focus flags, and several course-point types. Flag meanings beyond their upstream names have not been verified in gameplay.
- Many other members remain unknown. The header does not establish the disk serializer or level-launch mapping.

[CourseSelectPath.h](https://github.com/nsmbu/headers/blob/bb923aede585a06924669c0d496bb4b784ab6f2c/course_select/CourseSelectPath.h) exposes `getPoint(u32)` at upstream address `0x021D23AC`, while the rest of that class is explicitly TODO. [CourseSelectMgr.h](https://github.com/nsmbu/headers/blob/bb923aede585a06924669c0d496bb4b784ab6f2c/course_select/CourseSelectMgr.h) exposes `getPath(u8 world_no, u8 sub_world_no)` at `0x021F9FC8`.

These functions also appear in `external/RedCore/syms.map` under `CourseSelectPath` and `CourseSelectMgr`. They are a concrete starting point for local executable disassembly and a runtime diagnostic hook. Their existence does not by itself prove a compatible arbitrary graph replacement patch.

## Rendering and geometry

[CourseSelectMap.h](https://github.com/nsmbu/headers/blob/bb923aede585a06924669c0d496bb4b784ab6f2c/course_select/CourseSelectMap.h) exposes:

| Upstream interface | Upstream address |
| --- | --- |
| `loadModel(world, worldSubLetter)` | `0x021F56CC` |
| `getBoneWorldMatrix(world, worldSubLetter, name, out)` | `0x021F5800` |
| `getBoneWorldPos(out, world, worldSubLetter, name)` | `0x021F59A8` |
| `initialize()` | `0x021F6C14` |
| `calc()` | `0x021F6FE8` |
| `draw(layer)` | `0x021F7114` |

The header represents nine model lists. `MapModel.h` exposes separate `mModel`, `mModelWorld`, and `mModelTrap` pointers to `AnimModel` objects, and records the world and subletter. This supports investigation of model/bone relationships. A dependency of route positions on particular BFRES bone names is a hypothesis until confirmed from local assets/disassembly.

The local dump contains `content/Common/course_select/CS_W1.szs` and corresponding resources for other worlds, plus `CS_WorldMap.szs`, `MarioOffsetDataW1.bin` through W9 and `LookOffsetDataW1.bin` through W9. Filename observations alone do not establish binary field semantics. Do not treat offset binaries as node connectivity without further evidence.

Pyamoto's `miyamoto/app.py` explicitly detects Yaz0 compression, decompresses it, and uses SarcLib for archive handling. That is useful existing packaging functionality; it does not establish arbitrary BFRES geometry authoring support. An SZS extension should be checked for its actual compression/archive magic.

## Events and scripts

[Cobra's NSMBU documentation](https://github.com/RoadrunnerWMC/Cobra/blob/0b8d3927a4466e5061367dbb69c03fcd3eeaec3b/docs/nsmbu.md) distinguishes version-specific script tables and terminators. It states that Wii U script command IDs are initialized at runtime rather than fully present in static RPX data. `export_nsmbu.py` analyzes PPC instruction patterns to recover these IDs, and recognizes RPX ELF files and Cemu RAM dumps.

For the US releases, that document lists:

| Version | Scripts table | Count | Terminator |
| --- | --- | --- | --- |
| 1.0.0 | `0x10044A60` | 119 | 341 |
| 1.1.0 / 1.2.0 | `0x10044A98` | 119 | 342 |
| 1.3.0 | `0x100458B8` | 121 | 344 |

These addresses are **not portable file offsets**. They are upstream US virtual addresses. Cobra can auto-detect important addresses rather than blindly applying this table.

Cobra WMSC is an external mod format, not a stock game resource. Its README specifies `WMS0`, game `U`, a three-character variant such as `130`, file size, sparse sorted script IDs, priority/offset records, and eight-byte command/argument pairs. Script data is encoded big endian for Wii U. The stock executable requires a loader patch for these files.

[NSMBU-CSScript README](https://github.com/Ryguy0777/NSMBU-CSScript/blob/26797c51b20af47dfcf59256bac0dcc192ed26aa/README.md) requires a v1.3.0 WMSC at `content/Common/course_select/scripts.wmsc`, and describes Cemu GraphicPack and Telkin deployment. `include/csscript/Cobra.h` checks `WMS`, version `0`, game `U`, variant `130`, then resolves script offsets into pointers. `src/Main.cpp` hooks script command argument/type/priority access. Those hooks are for events; a WMSC file is **not a node/route graph file**.

## Current toolchain and target caution

Tsuru's checked-in `DEPRECATED.md` is dated 2026-09-14 and recommends Project RedHadron. RedCore is the current modern API; its project configuration and `conv/` directory distinguish US, EU, JP, bundle and standalone Luigi targets. Do not apply legacy Tsuru raw addresses without selecting the exact target and checking instructions.

The current NSMBU-CSScript and RedCore READMEs describe Tachyon with Node.js 24+, `tachyon pm install`, `tachyon compile US`, and `tachyon launch US`. These are upstream instructions, not a claim that the local SDK is installed or the module was compiled.

## Local resource evidence and BFRES bone layout

The user-provided W1 SZS was decompressed and its SARC entries read without writing the source. It contains `routeW1.csv` (2,052 bytes), `pointW1.csv` (1,646 bytes), and `CS_W1.bfres` (11,546,624 bytes). Both CSVs decode as Shift-JIS. The point table includes normal destination names and corresponding lists of macro route names, while the route CSV lists smaller route segments with movement labels such as the Japanese word for road, slope or jump.

Stock point records support multiple macro route references for a single destination: W1C0 has destination W201 and references RW1C0W2J0, RW2J0W2M0, RW2M0W201. W1S0 has destination W501 with four route references. Therefore connecting W102 to W103 with existing RW102W1T0 and RW1T0W103 follows an observed stock syntax, but bypassing the tower and its unlock/event logic remains an emulator integration question.

For geometry inspection, [BfresLibrary](https://github.com/KillzXGaming/BfresLibrary/tree/65c005275deed1e085069e72fea523247f955b87) was cloned to `external/BfresLibrary`; its license is MIT. Its primary parser source establishes the following Wii U layout:

- `Shared/Core/ResFileLoader.cs:ReadOffset`: nonzero 32-bit offsets are relative to the address of the offset field itself.
- `WiiU/ResFileParser.cs:Load`: the FRES models dictionary pointer is at 0x20.
- `Shared/Common/ResDict.cs`: an 8-byte dictionary header is followed by a 16-byte root entry and 16-byte data entries; key pointer is entry+8 and value pointer is entry+12.
- `Shared/Models/Model.cs`: FMDL skeleton pointer is model+0x0C.
- `Shared/Models/Skeleton/Skeleton.cs`: FSKL bone count is at +8; the bone dictionary pointer is at +0x10.
- `Shared/Models/Skeleton/Bone.cs`: Wii U bone name pointer +0, index +4, parent index +6, flags +0x10, scale +0x14, rotation +0x20, translation +0x30, user-data dictionary pointer +0x3C. Versions below 0x03040000 include an additional inverse matrix after this header.
- Translation-zero optimization flags are bit 27 (local) and bit 31 (cumulative). A nonzero translation edit must account for them. Moving skinned geometry also requires matrix/animation considerations; changing a bone field alone does not establish a correct mesh export.

Navigating those structures in the actual W1 BFRES confirmed version `0x03000001` and seven model dictionaries. The main model `CS_W1` has 158 bones. The following positions are local bone translations, not a proof of final rendered world-space positions:

| Bone | BFRES offset | Local translation | Parent index |
| --- | --- | --- | --- |
| W101 | 0x57A8 | (180.0068054, 60, -60.4845695) | 0 |
| W102 | 0x5818 | (420.0068054, 60, -60.4845695) | 0 |
| W103 | 0x5888 | (90.0068054, 300, -870.4845581) | 0 |
| RW102W1T0 | 0x3128 | (0.0070038, 60, -0.4845963) | 0 |
| RW1T0W103 | 0x51F8 | (0.0070038, 107.8915024, -1600.4846191) | 0 |

These offsets belong only to this exact extracted BFRES, and should be discovered through dictionaries rather than hardcoded in export logic. Macro route names proposed for the three-node prototype are thus confirmed to exist in the source skeleton. Relocating only level-point bones may leave route animation positions inconsistent; coupled route transforms need testing.

## Narrow custom geometry implementation

`worldstudio/mesh.py` implements an independently tested capacity-bounded subcase, rather than a general BFRES importer. An initial experiment replaced `beltmodel14__mtGrass` (2,348 vertices; XZ bounds about -378..827 and -1748..-1082). Those bounds cover only a narrow strip, while the example island extends to Z=500. Replacing that shape with the full island therefore targeted the wrong surface and made the render ambiguous. The exporter now targets `CS_W1_World/polySurface1489__mtGrass`, the main grass surface, with 22,236 vertices, 97,122 triangle indices, 17 submesh partitions and 33 bounding nodes. Its identity root bone permits model-local coordinates without inverse-skinning conversion. Its attributes are `_p0` float32x3 (`0x811`), `_n0` signed normalized 10:10:10:2 (`0x20B`), `_c0` UNorm8x4 (`0x00A`), `_u0` float32x2 (`0x80D`), and `_u1` unsigned normalized 16:16 (`0x7`).

The implementation accepts an original vertex/polygon mesh within those capacities, reads OBJ corner UVs/normals when present (splitting seam vertices), generates smooth normals and planar XZ UVs for missing attributes, projects `_u1` from the original surface by nearest XZ vertex to retain its baked-light map coordinates, fills `_c0` white, replaces positions and indices, degenerates unused triangles, and updates all existing bounding boxes and the shape radius. White is the neutral value for the shader's UNorm vertex-color input. The `mtGrass` material has baked-light texture references and `var_shadow=1`; assigning planar world UVs to its packed `_u1` channel was an unsupported assumption and likely contributed to the dark initial render. The UV projection is structurally tested but still requires Cemu comparison. The exporter retains original material references, vertex/index counts, all allocation sizes, submesh partitions and pointers. It refuses unsupported skinning, shared vertex buffers, format/version changes, capacity overruns and noncontiguous submesh partitions. Convex faces keep the prior fan order; simple planar concave faces use ear clipping with their original corner indexes, preserving UV/normal associations. Non-planar, self-intersecting, duplicate-corner and over-1,024-corner faces are rejected. Other shapes are unchanged, so this does not remove the entire stock landmass or its decorative meshes.

Primary layout evidence: BfresLibrary `Shared/Models/VertexBuffer.cs`, `VertexAttrib.cs`, `Shared/Common/Buffer.cs`, `Shared/Models/Shape/Shape.cs`, `Mesh.cs`, `SubMesh.cs`, `Bounding.cs`, and `Shared/GX2/Enums.cs` at commit `65c005275deed1e085069e72fea523247f955b87`. The Wii U buffer stores its data relative pointer at +0x14; shape mesh pointer is +0x24; submesh offsets are byte offsets into the index buffer.

Validation completed: three synthetic fixture tests in `tests/test_mesh.py` pass, including index/position/normal/bounds readback and unchanged-byte checks outside permitted regions. An in-memory replacement against the actual W1 BFRES with the original 13-vertex/18-triangle island completed, retained the 11,546,624-byte length, and reloaded identical skeletons. No source game file was written. This verifies structural export and buffer readback, **not** actual rendering, materials, lighting or camera culling in Cemu.

## Static BFRES geometry preview

`worldstudio/mesh.py:extract_rigid_model` reads a deliberately narrow Wii U BFRES subset: version `0x03000001`, one identity root bone, rigid shapes with one vertex buffer, float32x3 positions (`0x811`), packed SNORM 10:10:10:2 normals (`0x20B`), float32x2 UVs (`0x80D`) where present, and contiguous zero-based u16 triangle lists. Each extracted shape retains its name and material. Against the local `CS_W1.bfres`, the parser returns 42 shapes, 70,193 vertices and 106,736 triangles. `worldstudio/preview3d.py` writes an offline WebGL page with depth testing, directional lighting, route overlays, a shape filter, visibility toggles, deduplicated wireframe edges, sampled vertex-normal lines and shared texture caching. Its perspective near/far planes follow the model radius and camera distance, with a positive near floor for zooming inside the bounds; Node-backed tests exercise camera ranges, edge and normal-line generation, and JavaScript parsing. This only improves preview inspection and depth precision; it does not prove game rendering behavior.

The supplied W1 BFRES has 113 FTEX textures across BC1 UNorm (25), BC3 UNorm (23), BC4 UNorm (42), BC5 UNorm (3) and BC5 SNORM (20). Its `mtGrass` material references `Grass_alb`, a 256x256 BC1 texture using single-layer, single-sample GX2 2D Thin1 (tileMode 4, pitch 64 blocks, swizzle metadata `0x20000`). The bounds-checked extractor follows the pinned [BfresLibrary Material](https://github.com/KillzXGaming/BfresLibrary/blob/65c005275deed1e085069e72fea523247f955b87/BfresLibrary/Shared/Models/Material/Material.cs), [TextureRef](https://github.com/KillzXGaming/BfresLibrary/blob/65c005275deed1e085069e72fea523247f955b87/BfresLibrary/Shared/Common/TextureRef.cs) and [FTEX reader](https://github.com/KillzXGaming/BfresLibrary/blob/65c005275deed1e085069e72fea523247f955b87/BfresLibrary/WiiU/Texture/Texture.cs) to resolve material albedos.

`worldstudio/texture_preview.py` decodes BC1, BC3 and BC5 SNORM in the observed 2D Thin1 compressed-block layout. The BC5 decoder reads two signed BC4 channels, and reuses the pinned [GX2.cs](https://github.com/KillzXGaming/BfresLibrary/blob/65c005275deed1e085069e72fea523247f955b87/BfresLibrary/WiiU/Texture/GX2/GX2.cs) 128-bpp block-address path shared with BC3. Signed normalized interpolation follows the Khronos [BC4 signed format definition](https://registry.khronos.org/DataFormat/specs/1.3/dataformat.1.3.html#_bc4_signed); the standard marks endpoint pair (-127, -128) implementation-dependent, so the decoder rejects that pair. A local scan found no such pairs in the W1 BC5 SNORM maps. BC5's two-channel block layout is corroborated by Microsoft's [DirectXTex decoder](https://github.com/microsoft/DirectXTex/blob/main/DirectXTex/BC.cpp). Tests cover fixed address vectors, unique in-range tiled surfaces, synthetic round-trips, odd-edge crops and local W1 fingerprints. For `RouteW1_alb` (128x256 BC3, pitch 32, swizzle `0x10000`), raw tiled bytes hash to `34573278d6094c477acec437cef79f518f20d6f22712d2f60b44f451f87617f1`; detiled bytes hash to `e73b121700fbccc80ca7ccf2d6c691df996f487fde4778b5566f8359e6b8f9d3`.

The local BFRES identifies textures by material references and sampler dictionary. In this W1 file, all 36 inspected materials have matching TextureRef and Sampler counts, and pairing in sampler dictionary order identifies `_n0` as the normal-map slot: `RouteW1_nml` is BC5 SNORM (`0x235`), while `_o0` uses BC5 UNORM for a mask. The preview therefore accepts a normal only when its referenced texture name ends in `_nml`, its format is `0x235`, and its paired sampler is `_n0`; mismatched counts fail closed. This is observed W1 evidence, not a universal BFRES slot guarantee. Across supported UV meshes, six unique `_nml` textures attach to 22 shapes. The viewer remaps R/G channels to colors for inspection; it does not reconstruct Z, infer channel orientation, or use them in lighting.

For `RouteW1_nml` (128x256 BC5 SNORM, tileMode 4, pitch 32, nine reported mips), the local FTEX data size is 32,768 bytes and contains the top-level image used by this viewer. Raw bytes hash to `c03491af2d4bc380b4df0147fe1cab318f36bbf66e2d004b32a04b9028def17e`; detiled blocks hash to `23b5fd8bde69c9b2fbb1f63741d6237558bb69b5e5f39cf9df29865dedd39418`. The decoder preview does not claim that lower mips are extracted.

The local W1 model resolves 17 unique BC1/BC3 albedos and applies them to all 36 shapes with UVs; no referenced UV material fell back during the checked extraction. RGBA textures are encoded once in a shared catalog. The preview cuts out alpha below 50%, and geometry is packed into little-endian typed arrays. For the same local scene, the generated HTML payload measured about 16.8 MB before packing and 8.1 MB after. A decoded RouteW1 BC3 image shows the sandy path and green border. The generated scene JavaScript passes `node --check`, and headless Chrome with SwiftShader renders the full W1 scene, overlays, textures and labels. This confirms the software-rendered preview path; user-browser hardware acceleration and interaction remain unchecked.

BC5 SNORM is exposed only as a channel diagnostic. BC5 UNORM masks, BC4 specular/mask/baked-light slots, sampler behavior, UV transforms, baked lighting, shader parameters, material animation and skeletal animation are not evaluated. General model support remains narrow: multiple meshes per shape, skinning, non-identity bone transforms and arbitrary BFRES layouts are unsupported. Local extraction, hashes and decoder images do not prove that the viewer reproduces the game's rendered world.

## Directed graph checks

`worldstudio/graph_validation.py` validates native point/route table structure and can check directed reachability when the caller supplies entry points and required locations. When complete baseline point and route inventories are available, changed same-world destination declarations must also have a directed chain of `R<start><end>` route segments. Partial inventories and cross-world links are skipped because one archive cannot prove their full topology. This is explicit because the native point table also contains helpers and triggers that are not all playable level nodes. The `validate-graph` CLI combines the check with existing native project validation. On the supplied World 1 archive, `python -m worldstudio validate-graph --entry W101 --require W102 --require W103` passes. A negative check with `W199` fails as expected. This is a static table check; it does not model game state, unlock conditions, route animation, level launch or save behavior.

## Confirmed versus still unverified

Confirmed from source: runtime graph successor-name arrays, relevant lookup/model interfaces, script loader format/path, version-specific script behavior, current versus deprecated SDK status, license identities above.

Still unverified here: exact parser semantics of every CSV column, route interpolation, save/unlock semantics, level-launch dispatch, camera state transitions, arbitrary BFRES import compatibility, and runtime behavior of a custom three-node island. Those require further executable analysis and a Cemu/console run. A standalone editor simulation cannot serve as evidence for any of them.
