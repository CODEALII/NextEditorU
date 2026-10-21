# Development roadmap

This backlog follows verified project dependencies. “Done offline” means parsers, tests or exports passed; it does not claim in-game behavior.

## Highest priority

1. **Diagnose route movement in Cemu.** The separate `cemu-clean-baseline` profile has now loaded the supplied RPX with CrashFix only and its own MLC. Its first boot created a fresh save and stopped at the SpotPass information screen; input mapping, the map, and movement have not yet been observed there. Continue after resolving that first-run prompt, then record controller bindings and compare the unchanged graph with each isolated route experiment. Do not change topology until the input state is controlled.
2. **Validate terrain rendering against a controlled baseline.** Compare the main-grass export with stock in the isolated profile and determine whether baked-light UVs, alpha/culling, shape bounds or geometry cause the dark patches.
3. **Broaden the preview data model safely.** Preserve per-shape mesh/submesh, vertex-buffer, material and bone references. Add attribute codecs and hierarchy transforms only for layouts found in local resources; continue rejecting unsupported formats with a precise diagnostic.

Implemented offline subcase: static W1 extraction and the selected-mesh inspector now decode all supported named `_uN` coordinate attributes. The local W1 inventory contains `_u1` on 42 shapes and `_u2` on 13; a selector compares each raw chart without assigning sampler meaning. The static geometry parser still rejects multi-mesh, multi-buffer, skinned and other unsupported BFRES layouts.

Implemented offline subcase: the native preview chooses the `<archive>_World` model matching the opened course-select archive. The local W1/W2a/W3/W4/W5b/W6a/W7/W8a/W9a/W9b models produce 42/58/40/53/27/61/34/18/3/20 static shapes. The decoder supports observed float16x4 positions with W=1 and translation-only roots. W7 produces 19 decoded BC1 base-color maps and W9a produces 2; their 3D geometry and graph nodes share the tested W7 coordinate bounds. Remaining blockers include non-root shape bindings, rotated/scaled roots and other vertex encodings.

## Next editing milestones

4. Add selectable scene objects and editable transforms with a reversible undo/redo history.
5. Add explicit world graph profiles for entry points, required levels and optional branches; keep gameplay unlock semantics separate until verified.
6. Expand terrain import beyond one fixed-capacity grass shape only after mesh insertion or replacement has a demonstrated archive roundtrip.
7. Investigate animation formats and camera runtime behavior using concrete local files and targeted evidence.

## Runtime acceptance gate

A custom overworld is not complete until a controlled Cemu or hardware run demonstrates route movement, level launch, fresh-save unlock progression, save/reload persistence, camera transitions and the terrain appearance. Record the exact build/profile and retain `game_tested:false` on exports until those checks pass.

## Completed offline subcase

World 1 texture references and FTEX metadata are inventoried. The viewer now decodes and displays the `Grass_alb` BC1 base texture on the main grass shape using a bounded GX2 2D Thin1 path. Synthetic color/address fixtures and a local-dump detile hash verify this one supported layout. Other W1 texture formats and visual WebGL fidelity remain open.
