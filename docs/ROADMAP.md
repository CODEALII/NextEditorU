# Development roadmap

This backlog follows verified project dependencies. “Done offline” means parsers, tests or exports passed; it does not claim in-game behavior.

## Highest priority

1. **Diagnose route movement in Cemu.** Reproduce the reported no-movement result from a known map node, record active focus/controller bindings, then test the unchanged graph and each isolated route experiment. Do not change topology until the input state is controlled.
2. **Validate terrain rendering against a controlled baseline.** Compare the main-grass export with stock in the isolated profile and determine whether baked-light UVs, alpha/culling, shape bounds or geometry cause the dark patches.
3. **Broaden the preview data model safely.** Preserve per-shape mesh/submesh, vertex-buffer, material and bone references. Add attribute codecs and hierarchy transforms only for layouts found in local resources; continue rejecting unsupported formats with a precise diagnostic.

## Next editing milestones

4. Add selectable scene objects and editable transforms with a reversible undo/redo history.
5. Add explicit world graph profiles for entry points, required levels and optional branches; keep gameplay unlock semantics separate until verified.
6. Expand terrain import beyond one fixed-capacity grass shape only after mesh insertion or replacement has a demonstrated archive roundtrip.
7. Extend texture inspection to the other W1 formats (BC3, BC4 and BC5), then add wireframe and normal overlays after the corresponding scene metadata is represented.
8. Investigate animation formats and camera runtime behavior using concrete local files and targeted evidence.

## Runtime acceptance gate

A custom overworld is not complete until a controlled Cemu or hardware run demonstrates route movement, level launch, fresh-save unlock progression, save/reload persistence, camera transitions and the terrain appearance. Record the exact build/profile and retain `game_tested:false` on exports until those checks pass.

## Completed offline subcase

World 1 texture references and FTEX metadata are inventoried. The viewer now decodes and displays the `Grass_alb` BC1 base texture on the main grass shape using a bounded GX2 2D Thin1 path. Synthetic color/address fixtures and a local-dump detile hash verify this one supported layout. Other W1 texture formats and visual WebGL fidelity remain open.
