# NSMBU World Studio

**A research and editing toolkit for New Super Mario Bros. U world maps.**

World Studio reads and edits selected world-map resources, builds experimental topology and terrain patches, and provides a standalone visual editor. It is an actively researched prototype: resource handling and offline export are tested, while in-game movement currently fails in the reported route test. This project does not yet produce a complete playable custom overworld.

![World Studio project progress dashboard](docs/progress.svg)

Progress details and dated findings: [PROGRESS.md](PROGRESS.md) · [Runtime test notes](docs/INTEGRATION.md)

## What works today

- Read Yaz0/SARC archives and export patched archives while preserving untouched members. Export manifests list every changed member with before/after SHA-256 hashes and byte sizes, alongside archive-level hashes.
- Read and edit World 1 point and route tables; validate references before export.
- Inspect supported BFRES skeletons and apply bounded bone-transform changes.
- Export an experimental three-node progression patch using existing route data.
- Import a bounded rigid OBJ mesh into a known grass shape while retaining its material and layout. OBJ import offers scale, XYZ rotation (including a Z-up to Y-up preset) and translation before preview or replacement; UVs stay intact and normals/winding follow the transform. Files are parsed with clear size and geometry limits, and the editor reports imported vertices and polygon counts.
- Open an offline WebGL viewer for 42 supported static shapes from the local World 1 BFRES (70,193 vertices and 106,736 triangles), with route overlays, per-shape visibility controls, viewport and list mesh selection, geometry/material details, read-only texture SRT metadata, base-color and diagnostic BC3/BC4/BC5 map previews with supported storage formats and dimensions, focus-to-mesh framing, front/side/top camera presets, editable preview target coordinates, adjustable preview-light direction/intensity, deduplicated wireframe, and sampled vertex-normal views.
- Inspect SHARCFB v8 archives without decoding proprietary GX2 instructions. When the local common shader archive is available, the material inspector resolves BFRES shader-program assignments, sampler/uniform symbols, material-option permutation candidates, and declared shader-input to BFRES vertex-attribute bindings with stored formats. Shape-specific skinning selection and actual game shader execution remain unresolved.
- Decode shared BC1/BC3 base-color textures for all 42 local W1 shapes with verified `_u0` data, including alpha cutouts. The reader supports float32x2, UNorm16x2, SNorm16x2, and UNorm8x2 UV formats; texture transforms and shader operations remain unverified.
- Inspect BC5 SNORM R/G channels for eight shared `_n0` maps across 26 UV meshes, or enable optional tangent-space lighting reconstructed from those maps and generated mesh tangents. The lighting preview is approximate; channel orientation and game material settings remain unverified.
- Pack scene geometry into compact typed buffers for the viewer; the current generated page with all supported decoded W1 maps is 22,034,943 bytes (21.01 MiB). This payload size is not a load-performance benchmark.
- Validate directed reachability with `validate-graph`, and block project exports when a new local destination lacks a route chain or an edited route disconnects a destination that was connected in the baseline.
- Read and edit discovered camera-offset tables; analyze and round-trip event data offline.
- Use the standalone Tk editor to inspect the map, drag supported rest-pose points in the camera-facing plane, edit supported fields, save project files, and undo or redo up to 31 recent edits with Ctrl+Z / Ctrl+Y. Native 3D preview generation runs in a background worker while the editor remains responsive, with stage updates as it reads geometry, decodes textures, resolves shader metadata, and opens the page; edits are locked until completion. Export validation rejects malformed table rows and invalid bone positions before writing; unsupported transforms are kept in a labeled preview layout.
- Run the local automated suite against synthetic fixtures and the user-provided local dump.

The WebGL viewer supports BC1/BC3 base-color maps, BC5 SNORM normal-map channels, BC5 UNorm `_o0` channels, and BC4 UNorm diagnostics from `_o1`, `_b0`, `_s0`, and `_x2` in the observed local GX2 2D Thin1 layout. A selector switches among 19 BC4 maps attached to the 42 supported W1 shapes. The inspector also shows `_x0`/`_x1` BC3 thumbnails and exact sampler names declared by each resolved material shader program, including route-mask, edge-mask, light-map, bake-map, spec-mask, and normal-map symbols. Those views remain diagnostic texel displays; shader calculations and active compiled variations are not evaluated. An AGL-style option lookup reports a candidate material permutation index, while the form-specific skinning selection is unresolved. The inspector reports bounded `texmtx` SRT fields and matching shader uniform names where available, but does not apply UV transforms or claim which texture coordinate operation the program performs. Optional BC5 tangent-space lighting uses generated mesh tangents and reconstructed Z, but channel orientation and game material lighting remain unverified. Preview-light controls are illustrative. The viewer does not reproduce complete game shaders, animation, or arbitrary BFRES variants. The editor deliberately blocks unsupported node/index changes. Camera and event formats have offline tooling, but their in-game behavior and runtime integration are not verified. Read [Research and format findings](docs/RESEARCH.md), [Resource findings](docs/RESOURCE_FINDINGS.md), [Camera findings](docs/CAMERA_FINDINGS.md), and [Event findings](docs/EVENTS.md) for the evidence and limits of each feature.

## Current runtime status

The experimental topology patch changes the intended three-node path, but the latest manual Cemu attempt reported that **Mario does not move**. The cause has not been identified, so topology traversal, level launch, unlock progression, and save persistence are not claimed to work. The corrected terrain exporter is prepared in an isolated test pack, but its appearance has not been visually confirmed. See [the integration log](docs/INTEGRATION.md).

## Get started

Requirements: Windows, Python 3.14 with Tkinter, a legally obtained NSMBU dump for resource work, and Cemu for optional isolated runtime tests.

```powershell
python -m worldstudio gui
```

Or double-click `Launch World Studio.cmd`. By default the editor looks for the local game resource at `NSMBU Modding Project/content/Common/course_select/CS_W1.szs`. The dump is not included in this repository.

Inspect resources and create a sample topology export:

```powershell
python -m worldstudio inspect
python -m worldstudio demo --out build/my-chain
python -m worldstudio gui build/my-chain/three-level-chain.nws.json
```

Inspect the named interface in a local shader archive:

```powershell
python -m worldstudio inspect-shaders "NSMBU Modding Project/content/Common/course_select/CS_WorldMap.szs" --program mtWorldMap
python -m worldstudio inspect-shaders "NSMBU Modding Project/content/Common/shader/shaderfb.szs" --entry nw4f_cs_shader.sharcfb --program nw4f_cs_route_shader
python -m worldstudio inspect-shaders "NSMBU Modding Project/content/Common/shader/shaderfb.szs" --entry nw4f_cs_shader.sharcfb --program nw4f_cs_route_shader --json
```

The default is a compact terminal summary; add `--json` for the full parsed metadata.

Check a route from an explicit start to required locations:

```powershell
python -m worldstudio validate-graph --entry W101 --require W102 --require W103
```

Pass a saved `.nws.json` project path as the first argument to validate edits. Local route endpoints must resolve to the current BFRES; remote-world endpoints are left unresolved because their archive is outside the project. Remote segments cannot satisfy local reachability. This verifies the declared graph only; it does not simulate in-game movement or unlock rules.

The experimental mesh export accepts the included original sample island:

```powershell
python -m worldstudio demo --island assets/island.obj --out build/my-island
```

Exports go to new paths and include manifests. Never copy them over the original game files. For the isolated Cemu workflow, see [docs/INTEGRATION.md](docs/INTEGRATION.md) and `tools/prepare_cemu.py`.

## Verify locally

```powershell
python -m unittest discover -s tests -v
python -m compileall -q worldstudio tests tools
```

A fresh headless Chrome/SwiftShader render of the local W1 scene, mesh inspector, and preview-light panel was visually inspected. This verifies the software-rendered preview path; user-browser GPU behavior remains open. Cemu movement, level launches, progression and save compatibility are still unverified. See [TESTING.md](docs/TESTING.md) for local checks and [ROADMAP.md](ROADMAP.md) for the next milestones.

## Repository map

| Path | Purpose |
| --- | --- |
| `worldstudio/` | Resource readers, patch/export logic, and Tk editor |
| `tools/` | Cemu test setup and inspection/event bridge tools |
| `tests/` | Synthetic and user-dump-backed regression tests |
| `docs/` | Research notes, integration evidence, and progress graphic |
| `assets/` | Original CC0 preview geometry |
| `examples/` | Original CC0 game-space test geometry |
| `patches/` | Small upstream Cobra encoder fix and its license |

## Safety and licensing

No Nintendo game dump, executable, save, emulator build, or generated game-resource pack is distributed here. Supply your own legally obtained game files; local dump, build, and evidence folders are ignored by Git. The included island OBJ files are original project geometry and carry CC0 notices in their headers.

There is no repository-wide code license yet. The Cobra-related patch and bridge preserve the upstream GPL license notice in `patches/COPYING.Cobra`; see [docs/RESEARCH.md](docs/RESEARCH.md) for provenance and pinned upstream references.

## Contributing

Keep findings tied to reproducible evidence, preserve unknown resource bytes, and distinguish offline tests from Cemu or hardware observations. Update `PROGRESS.md` and the relevant format note when behavior changes. Do not add user-owned game dumps, saves, executables, generated packs, or credentials to commits.
