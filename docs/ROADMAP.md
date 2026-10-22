# Development roadmap

This backlog follows verified project dependencies. “Done offline” means parsers, tests or exports passed; it does not claim in-game behavior.

## Highest priority

1. **Verify the custom W102-to-W103 route in Cemu.** The process-bound two-second WASD test visibly moves Mario from Crushing-Cogs Tower to the right-hand course node and onward on the unmodified Clean profile. An archived Chain test with the exact patch hash held D for 1.5 seconds and visibly moved Mario from a road junction to the right-hand black course node, but neither internal point ID was captured; it is not a matched Clean comparison from the same confirmed start. Identify the exact start/destination point IDs, traverse the changed link with the same sustained input, and verify its course launch.
2. **Visually validate topology-preserving terrain projection.** The previous `cemu-island-mainlight` whole-shape replacement loaded with large dark-green overlaps and clipped surfaces. The project exporter now changes 2,451 intersecting heights with a 128-unit boundary blend while preserving all 32,374 target triangles and both UV channels; test the updated archive against the same isolated Cemu profile before treating terrain as playable.
3. **Broaden the preview data model safely.** Preserve per-shape mesh/submesh, vertex-buffer, material and bone references. The supported rigid-shape path now preserves validated contiguous submesh index ranges and exposes them in the inspector. Add attribute codecs and hierarchy transforms only for layouts found in local resources; continue rejecting unsupported formats with a precise diagnostic.

Implemented offline subcase: static W1 extraction and the selected-mesh inspector now decode all supported named `_uN` coordinate attributes. The local W1 inventory contains `_u1` on 42 shapes and `_u2` on 13; a selector compares each raw chart without assigning sampler meaning. The static geometry parser still rejects multi-mesh, multi-buffer, skinned and other unsupported BFRES layouts.

Implemented offline subcase: the native preview chooses the `<archive>_World` model matching the opened course-select archive. All twelve local models decode in the tested static subset: W1/W2a/W3/W4/W5a/W5b/W6a/W7/W8a/W8b/W9a/W9b produce 42/58/40/53/76/27/61/34/18/42/3/20 shapes. The decoder supports observed float16x4 positions with W=1 and rigid attachment to supported rest-pose bones, including rotation, translation and positive scale with inverse-transpose normal handling. Segment-scale compensation, camera-facing billboard branches and other vertex encodings remain unsupported. W7 produces 19 decoded BC1 base-color maps and W9a produces 2; their 3D geometry and graph nodes share the tested W7 coordinate bounds.

The BC1/BC3 base-color path has also been checked against all twelve local world models. It attaches decoded maps to 42/42 W1 shapes, 58/58 W2a, 39/40 W3, 53/53 W4, 74/76 W5a, 27/27 W5b, 61/61 W6a, 33/34 W7, 17/18 W8a, 33/42 W8b, 3/3 W9a and 20/20 W9b shapes. When a material has multiple `*_alb` references, a unique `_a0` sampler match can disambiguate them; this does not establish general shader semantics. Unsupported formats/layouts or missing albedo references keep the fallback color.

## Next editing milestones

4. Extend scene-object transforms beyond supported world points. The editor now exposes unique, supported rigid-shape child bones as local XYZ object transforms; selecting the row focuses its bound mesh, edits rebuild the preview, and edits export with Undo/Redo support. Rotation/scale editing, duplicated-bone bindings, unsupported transform branches, arbitrary BFRES geometry editing, and in-game object placement remain open.
5. The editor graph-profile gate now remembers its choice per source archive hash, revalidates it on reopen and applies the same profile to Validate and Export. Keep gameplay unlock semantics separate until verified.
6. Expand terrain import beyond one fixed-capacity grass shape only after mesh insertion or replacement has a demonstrated archive roundtrip.
7. Investigate animation formats and camera runtime behavior using concrete local files and targeted evidence.

## Runtime acceptance gate

A custom overworld is not complete until a controlled Cemu or hardware run demonstrates route movement, level launch, fresh-save unlock progression, save/reload persistence, camera transitions and the terrain appearance. Record the exact build/profile and retain `game_tested:false` on exports until those checks pass.

## Completed offline subcase

World 1 texture references and FTEX metadata are inventoried. The viewer now decodes and displays the `Grass_alb` BC1 base texture on the main grass shape using a bounded GX2 2D Thin1 path. Synthetic color/address fixtures and a local-dump detile hash verify this one supported layout. Other W1 texture formats and visual WebGL fidelity remain open.
