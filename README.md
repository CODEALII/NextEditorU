# NSMBU World Studio

**A research and editing toolkit for New Super Mario Bros. U world maps.**

World Studio reads and edits selected world-map resources, builds experimental topology and terrain patches, and provides an integrated desktop editor with a persistent 3D world viewport. It is an actively researched prototype: resource handling and offline export are tested, Mario movement on the overworld is confirmed, and a complete playable custom overworld is not yet verified.

![World Studio project progress dashboard](docs/progress.svg)

Progress details and dated findings: [PROGRESS.md](PROGRESS.md) · [Runtime test notes](docs/INTEGRATION.md)

## What works today

- Read Yaz0/SARC archives and export patched archives while preserving untouched members. Export manifests list every changed member with before/after SHA-256 hashes and byte sizes, alongside archive-level hashes.
- Read and edit World 1 point and route tables; validate references before export.
- Choose route movement types from the source archive's existing type values. Changed/new route rows with empty or unknown types are blocked from export; unchanged source values remain preserved.
- Inspect supported BFRES skeletons and apply bounded bone-transform changes.
- Export an experimental three-node progression patch using existing route data.
- Import a bounded rigid OBJ or static GLB 2.0 terrain surface and project its upward-facing triangles onto the existing main grass mesh. The embedded viewport now shows this export-equivalent projected shape, not the raw imported topology. Export preserves source vertex/index topology, material, diffuse UVs and baked-light UVs, displaces only overlapping upward-facing source vertices, and recomputes normals and bounds; terrain collision and Cemu appearance still require in-game verification. Both formats offer scale, XYZ rotation (including a Z-up to Y-up preset) and translation before preview or export. GLB import accepts one embedded BIN buffer, static identity-transformed triangle meshes, float32 positions/normals, and float32 or normalized unsigned-byte/short `TEXCOORD_0`, with a 64 MiB file, 65,535-vertex, 200,000-triangle and 4,096-primitive limit. External/data-URI buffers, compressed data, skinning, morph targets, non-identity node transforms, required extensions and GLB material rendering are unsupported and reported or rejected clearly.
- Embed the offline WebGL world renderer as a persistent main editor pane on Windows through a local Tk child WebView2. The 3D viewport and 2D graph stay visible side by side in an adjustable split, with the nodes/routes list and properties beside them. The viewport receives most of the split and keeps the model unobstructed by default; Preview controls opens the renderer's lighting, camera, filters, visibility and shape inspector. Selecting a point in either view highlights and focuses it in the other; native point and route-table edits update WebGL overlays without rebuilding BFRES geometry or textures. Terrain geometry changes rebuild the scene.
- Render 42 supported static shapes from the local World 1 BFRES (70,193 vertices and 106,736 triangles), with route overlays, per-shape visibility controls, viewport and list mesh selection, geometry/material details, read-only texture SRT metadata, base-color and diagnostic BC3/BC4/BC5 map previews with supported storage formats and dimensions, visible per-shape warnings when a base texture falls back to approximate color, focus-to-mesh framing, front/side/top camera presets, editable preview target coordinates, adjustable preview-light direction/intensity, deduplicated wireframe, and sampled vertex-normal views. A dedicated `_c0` diagnostic decodes GX2 `0x00A` UNorm8x4 and `0x80F` half-float4 vertex colors, reports raw channel ranges, and clamps RGB to 0–1 for display; shader meaning and alpha behavior remain unverified. The viewer reads supported `_a0` GX2 wrap modes: Wrap and Mirror map directly, Clamp is marked as an edge approximation, and unsupported modes are reported with an explicit Repeat fallback. Repeated preview builds reuse parsed indexes for the unchanged local BFRES and shader archive.
- Selecting a UV-mapped shape also shows its raw triangle layout, stored UV bounds, the number of vertices outside the 0–1 tile, and valid/invalid triangle counts. Dense charts are sampled and extreme ranges are clipped for display. The chart does not apply texture SRT or claim shader accuracy.
- Inspect SHARCFB v8 archives without decoding proprietary GX2 instructions. When the local common shader archive is available, the material inspector resolves BFRES shader-program assignments, sampler/uniform symbols, material-option permutation candidates, and declared shader-input to BFRES vertex-attribute bindings with stored formats. Shape-specific skinning selection and actual game shader execution remain unresolved.
- Decode shared BC1/BC3 base-color textures for all 42 local W1 shapes with verified `_u0` data, including alpha cutouts. The reader supports float32x2, UNorm16x2, SNorm16x2, and UNorm8x2 UV formats; texture transforms and shader operations remain unverified.
- Inspect BC5 SNORM R/G channels for eight shared `_n0` maps across 26 UV meshes, or enable optional tangent-space lighting reconstructed from those maps and generated mesh tangents. The lighting preview is approximate; channel orientation and game material settings remain unverified.
- Pack scene geometry into compact typed buffers for the viewer; the current generated page with all supported decoded W1 maps is 22,034,943 bytes (21.01 MiB). This payload size is not a load-performance benchmark.
- Validate directed reachability with `validate-graph`, and block project exports when a new local destination lacks a route chain or an edited route disconnects a destination that was connected in the baseline.
- Read and edit discovered camera-offset tables; analyze, inventory, and round-trip event data offline. The Cobra catalog reports script priorities, counts, and numeric command IDs without guessing their effect or linking them to world points.
- Use the Tk editor to inspect the map, drag supported rest-pose points in the graph or embedded 3D viewport, edit fields from the side panel or 3D selection, save, and undo or redo up to 31 edits with Ctrl+Z / Ctrl+Y. 3D drags commit through the hierarchy-aware world-to-local converter; transforms that cannot be safely inverted are rejected. The 3D view is built in a background worker; edits are paused only during a full geometry rebuild, while point/route changes update overlays incrementally. Its Recent menu remembers the last ten paths separately for native worlds and lightweight previews in the user's local application settings, and reopens them through the normal unsaved-edit guard. Changed native sessions and saved lightweight-preview projects get a debounced recovery snapshot capped at 64 MiB and bound to the source file hash; reopening offers restore. Overwriting a changed project preserves two recent versions as neighboring backup files. Export validation rejects malformed rows and invalid bone positions; unsupported transforms stay in a labeled preview layout.
- Run the local automated suite against synthetic fixtures and the user-provided local dump.

The WebGL viewer supports BC1/BC3 base-color maps, BC5 SNORM normal-map channels, BC5 UNorm `_o0` channels, and BC4 UNorm diagnostics from `_o1`, `_b0`, `_s0`, and `_x2` in the observed local GX2 2D Thin1 layout. A selector switches among 19 BC4 maps attached to the 42 supported W1 shapes. The inspector also shows `_x0`/`_x1` BC3 thumbnails and exact sampler names declared by each resolved material shader program, including route-mask, edge-mask, light-map, bake-map, spec-mask, and normal-map symbols. Those views remain diagnostic texel displays; shader calculations and active compiled variations are not evaluated. An AGL-style option lookup reports a candidate material permutation index, while the form-specific skinning selection is unresolved. The inspector reports bounded `texmtx` SRT fields and matching shader uniform names where available, but does not apply UV transforms or claim which texture coordinate operation the program performs. Optional BC5 tangent-space lighting uses generated mesh tangents and reconstructed Z, but channel orientation and game material lighting remain unverified. Preview-light controls are illustrative. The viewer does not reproduce complete game shaders, animation, or arbitrary BFRES variants. The editor deliberately blocks unsupported node/index changes. Camera and event formats have offline tooling, but their in-game behavior and runtime integration are not verified. Read [Research and format findings](docs/RESEARCH.md), [Resource findings](docs/RESOURCE_FINDINGS.md), [Camera findings](docs/CAMERA_FINDINGS.md), and [Event findings](docs/EVENTS.md) for the evidence and limits of each feature.

For the integrated viewport, the editor list and graph select supported point/route overlays in WebGL, and viewport point/route clicks select the corresponding list row. Left-dragging an editable native point commits its world position back to BFRES local coordinates, enters Undo history, and refreshes its overlay; child transforms that cannot be inverted are rejected. Point positions and route overlays refresh incrementally. Terrain geometry replacement reloads the viewport scene; model geometry is not rebuilt for ordinary point or route-table edits. Items without a displayed world overlay (including unsupported-layout points) cannot be selected from the 3D canvas, and BFRES model-shape selection remains in the renderer's own inspector. The embedded host uses tkwry 0.1.9 and the installed WebView2 Runtime; if it cannot initialize, use the external-preview debug action. These editor features are not proof of in-game runtime behavior.

## Current runtime status

Mario movement is confirmed on the unmodified Clean profile: a process-bound Cemu test used two-second holds and showed movement from Crushing-Cogs Tower to the right-hand course node and onward to a lower junction. The modified Chain profile reached the overworld, but its movement comparison did not start from the confirmed same node, so traversal of the changed W102-to-W103 route is not verified. A `Z` press at an unconfirmed road junction did not establish level launch. Level starts, unlock progression, save persistence after clearing a course, and camera behavior remain unverified. The earlier Mainlight terrain build showed dark-green overlaps because its 29-vertex/54-triangle OBJ replaced a 22,236-vertex/32,374-triangle grass shape. The exporter now projects terrain onto the existing mesh while preserving its topology and UVs; the new result has passed offline tests but has not yet been checked in Cemu. See [the integration log](docs/INTEGRATION.md).

## Get started

Requirements: Windows, Python 3.14 with Tkinter, Microsoft Edge WebView2 Runtime, and the optional `tkwry` host for the embedded viewport. Install it with `python -m pip install -r requirements.txt`. A legally obtained NSMBU dump is needed for resource work; Cemu is optional for isolated runtime tests. If `tkwry` is unavailable, the app offers the existing external preview as a fallback.

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

Require the explicit World 1 entry/required-location graph profile when exporting:

```powershell
python -m worldstudio export build/my-chain/three-level-chain.nws.json --out build/my-chain/profile-checked.szs --profile profiles/w1-core-progression.json
```

This optional check blocks export if W101 cannot reach W102 and W103. It checks
the selected static profile only; it does not model save flags or game unlocks.
The native editor offers the same opt-in check from the **Graph check** toolbar
menu. **Validate** and SZS export both apply the selected JSON profile; selecting
a new source world clears it so a check cannot silently carry over.

After exporting a saved project, reimport the archive and compare every member,
the export manifest, and any camera companion files against a fresh export:

```powershell
python -m worldstudio verify-export build/my-chain/three-level-chain.nws.json build/my-chain/content/Common/course_select/CS_W1.szs
```

This checks offline package consistency; its report keeps `game_tested` false.

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

For the checked-in World 1 static reachability profile, run `python -m worldstudio validate-graph --profile profiles/w1-core-progression.json`. The profile pins W101 as an explicit start and W102/W103 as required reachable locations; this checks native table connectivity and does not model events, unlock state, Mario movement, level loading, or save persistence.

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
