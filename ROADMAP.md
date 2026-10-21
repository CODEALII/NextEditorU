# Development roadmap

World Studio is an offline research prototype. Items below describe work still needed for a genuinely playable custom overworld; a passing parser or export test does not satisfy an in-game acceptance check.

## Highest priority: verify route movement

The reported Cemu test says Mario does not move. Static validation confirms that the exported graph reaches W102 and W103 and that the required W102 path bones exist, but runtime movement is still failed. Retest with one known Cemu window, the World Studio pack visibly enabled, and an input device mapped to that window. Then verify the original route as a control, the custom route, level launch, fresh progression unlock, save/reload, and camera transitions. Keep each result tied to the exact pack and input profile.

The isolated `cemu-island-mainlight` process now has a log confirming both the
World Studio Chain and crash-fix packs activated and reached the title screen.
The saved profile maps keyboard input, but computer-use key taps did not advance
the title prompt. A working game input source is still needed before route QA.

## Rendering fidelity

- Implemented: 42 rigid static shapes, 70,193 vertices, 106,736 triangles, route overlays, shape filtering, visibility toggles, and 17 shared BC1/BC3 albedos on 36 UV meshes from the local W1 BFRES.
- Implemented: WebGL context, shader/program and mesh-initialization errors show a high-contrast overlay.
- Implemented: perspective depth planes follow the model bounding radius and camera distance, with a safe near-plane floor while zoomed inside the scene bounds.
- Implemented: a BC5 SNORM channel inspector for six local `_n0` maps, with fail-closed sampler-slot checks and signed block decoding; it is explicitly diagnostic and does not alter lighting.
- Implemented: an on/off wireframe mode built from deduplicated triangle edges for the viewer's supported static shapes.
- Implemented: a sampled vertex-normal overlay capped at about 5,000 vectors across the scene, with normalized direction and model-scaled length.
- Implemented: accessible shape-name buttons select a mesh row and populate a safe-text inspector with material, vertex/triangle counts, UV availability, and supported base/BC5 texture references.
- Implemented: adjustable preview-light azimuth, elevation, and intensity controls feed normalized shader lighting while retaining the original default direction; these controls do not modify game data or claim game shader fidelity.
- Next: verify the new viewer controls with the user's browser/GPU; add viewport picking, material controls, and camera presets/target controls.
- Investigate BC5 UNORM masks and BC4 slots with material-slot evidence before rendering them. Add UV transforms, transparent material modes, baked light maps, and additional GX2 tile layouts only with local references and fixed regression vectors.
- Broaden geometry parsing to multiple meshes, more vertex encodings, hierarchy transforms, skinning, and other BFRES variants. The current static geometry subset must reject unsupported layouts clearly.

## Terrain pipeline

- Keep the tested OBJ replacement limited to the existing main grass shape, with byte-range preservation and an export manifest.
- Simple planar concave OBJ faces now use ear clipping; malformed, non-planar, duplicate-corner and over-1,024-corner faces are rejected.
- Compare corrected terrain output against a controlled stock Cemu baseline. Investigate the previous dark patch observation and verify UV, color, culling, and lighting behavior.
- Add strict import diagnostics, coordinate/scale conversion controls, geometry summaries, and archive reimport validation.
- Investigate GLB/glTF as an authoring input. Do not claim arbitrary mesh insertion until a BFRES structure and in-game result prove it.

## Topology, events, and camera

- Implemented: project, editor, and export validation require a directed segment chain for newly added same-world destinations. Route edits recheck baseline-connected destinations and block an export if an edit disconnects one; pre-existing gaps and cross-world links are not treated as new failures.
- Extend graph validation only as each native reference is identified: level destinations, event dependencies, and progression conditions.
- Support route creation and node placement after safe bone naming, point indexes, and engine/script references are understood. Preserve unknown data and block unresolved exports.
- Improve camera offset editing with a clear table inspector, then map each bank and transition to in-game behavior.
- Keep the Cobra event table bridge offline until a loader or game-side hook is verified. Round-trip success alone does not establish that the game consumes an edited table.

## Editor and project workflow

- Implemented: native graph labels route around point markers and each other, with
  contrast backing plates; checked in a fresh local editor window.
- Implemented: bounded Ctrl+Z/Ctrl+Y history covers native point/route rows,
  BFRES position drafts, camera vectors and terrain imports; project switches
  reset the history and undo marks the project dirty. Add drag-to-move and route
  drawing after native index/reference safety is established.
- Add reliable selection and transform controls with project-level regression tests.
- Add recent projects, recoverable sessions, backup rotation, changed-file manifests, and export/reimport comparison.
- Profile large models and projects before adding background parsing or more caching. Current local W1 preview data takes about 8.1 MB after typed-array packing.

## Central acceptance milestone

Create and export a three-level custom world with original terrain, custom connected routes, working level entry, clear-triggered progression, save/reload support, and correct camera movement. Validate the same exported build in Cemu or on hardware and publish the exact steps and evidence. Until then, describe World Studio as a modding prototype and do not label a custom world playable.
