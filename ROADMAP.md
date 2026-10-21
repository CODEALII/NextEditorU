# Development roadmap

World Studio is an offline research prototype. Items below describe work still needed for a genuinely playable custom overworld; a passing parser or export test does not satisfy an in-game acceptance check.

## Highest priority: diagnose route movement

The reported Cemu test says Mario does not move. Static validation confirms that the exported graph reaches W102 and W103 and that the required W102 path bones exist, but runtime movement is still failed. Retest with one known Cemu window, the World Studio pack visibly enabled, and an input device mapped to that window. Then verify the original route as a control, the custom route, level launch, fresh progression unlock, save/reload, and camera transitions. Keep each result tied to the exact pack and input profile.

## Rendering fidelity

- Implemented: 42 rigid static shapes, 70,193 vertices, 106,736 triangles, route overlays, shape filtering, visibility toggles, and 17 shared BC1/BC3 albedos on 36 UV meshes from the local W1 BFRES.
- Next: test user-browser hardware acceleration and interaction, then add material and texture inspectors, selectable meshes, wireframe/normals overlays, and camera/light controls.
- Research BC4/BC5 data as normal or mask textures before assigning it to color output. Add UV transforms, transparent material modes, baked light maps, and additional GX2 tile layouts only with local references and fixed regression vectors.
- Broaden geometry parsing to multiple meshes, more vertex encodings, hierarchy transforms, skinning, and other BFRES variants. The current static geometry subset must reject unsupported layouts clearly.

## Terrain pipeline

- Keep the tested OBJ replacement limited to the existing main grass shape, with byte-range preservation and an export manifest.
- Compare corrected terrain output against a controlled stock Cemu baseline. Investigate the previous dark patch observation and verify UV, color, culling, and lighting behavior.
- Add strict import diagnostics, coordinate/scale conversion controls, geometry summaries, and archive reimport validation.
- Investigate GLB/glTF as an authoring input. Do not claim arbitrary mesh insertion until a BFRES structure and in-game result prove it.

## Topology, events, and camera

- Extend graph validation only as each native reference is identified: route endpoints, level destinations, event dependencies, and progression conditions.
- Support route creation and node placement after safe bone naming, point indexes, and engine/script references are understood. Preserve unknown data and block unresolved exports.
- Improve camera offset editing with a clear table inspector, then map each bank and transition to in-game behavior.
- Keep the Cobra event table bridge offline until a loader or game-side hook is verified. Round-trip success alone does not establish that the game consumes an edited table.

## Editor and project workflow

- Add reliable selection, transform controls, route drawing, undo/redo, and keyboard shortcuts with project-level regression tests.
- Add recent projects, recoverable sessions, backup rotation, changed-file manifests, and export/reimport comparison.
- Profile large models and projects before adding background parsing or more caching. Current local W1 preview data takes about 8.1 MB after typed-array packing.

## Central acceptance milestone

Create and export a three-level custom world with original terrain, custom connected routes, working level entry, clear-triggered progression, save/reload support, and correct camera movement. Validate the same exported build in Cemu or on hardware and publish the exact steps and evidence. Until then, describe World Studio as a modding prototype and do not label a custom world playable.
