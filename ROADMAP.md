# Development roadmap

World Studio is an offline research prototype. Items below describe work still needed for a genuinely playable custom overworld; a passing parser or export test does not satisfy an in-game acceptance check.

## Highest priority: verify route movement

The reported Cemu test says Mario does not move. Static validation confirms that the exported graph reaches W102 and W103 and that the required W102 path bones exist, but runtime movement is still failed. The isolated baseline window and keyboard mapping are now identified, yet computer-use taps do not reach the emulated controller. First obtain a working input source; then compare baseline and patched routes in the same profile and verify level launch, fresh progression unlock, save/reload, and camera transitions. Keep each result tied to the exact pack and input profile.

The isolated `cemu-island-mainlight` process has a log confirming both the
World Studio Chain and crash-fix packs activated and reached the title screen.
In the isolated baseline window, Cemu displayed Acorn Plains-1 with a Keyboard
profile mapping `D` to right, but neither a `D` nor Right key tap moved Mario.
Computer-use input is not a usable game controller here; a working input source
is still needed before baseline/patch route QA.

## Rendering fidelity

- Implemented: 42 rigid static shapes, 70,193 vertices, 106,736 triangles, route overlays, shape filtering, visibility toggles, and 20 shared BC1/BC3 albedos on all 42 W1 shapes with decoded UV attributes.
- Implemented: `_u0` vertex decoding for observed GX2 `0x80D` float32x2, `0x7` UNorm16x2, `0x207` SNorm16x2, and `0x4` UNorm8x2 formats. W1 inventory and synthetic normalization/bounds tests cover all four; shader UV transforms remain unknown.
- Implemented: WebGL context, shader/program and mesh-initialization errors show a high-contrast overlay.
- Implemented: perspective depth planes follow the model bounding radius and camera distance, with a safe near-plane floor while zoomed inside the scene bounds.
- Implemented: a BC5 SNORM channel inspector for eight local `_n0` maps across 26 shapes, with fail-closed sampler-slot checks and signed block decoding; it is explicitly diagnostic and does not alter lighting.
- Implemented: an optional BC5 tangent-space lighting preview reconstructs Z and derives tangent frames from supported mesh geometry and UVs. It is disabled by default; channel orientation and game material settings remain unverified.
- Implemented: an on/off wireframe mode built from deduplicated triangle edges for the viewer's supported static shapes.
- Implemented: a sampled vertex-normal overlay capped at about 5,000 vectors across the scene, with normalized direction and model-scaled length.
- Implemented: accessible shape-name buttons select a mesh row and populate a safe-text inspector with material, vertex/triangle counts, UV availability, and supported base/BC5 texture references.
- Implemented: adjustable preview-light azimuth, elevation, and intensity controls feed normalized shader lighting while retaining the original default direction; these controls do not modify game data or claim game shader fidelity.
- Implemented: each supported shape has bounded local geometry framing, and the inspector's Focus mesh action centers the camera on that mesh and adjusts its distance using the mesh radius.
- Implemented: clicking the viewport uses a depth-tested, texture-alpha-aware ID pass to select the visible shape under the pointer; high-DPI coordinate mapping and ID decoding have synthetic coverage, and a local W1 headless Chrome click selected the expected terrain mesh.
- Implemented: the inspector shows cached 96-pixel previews of supported BC1/BC3 base-color and BC5 diagnostic textures, with separate labels; these remain inspectable samples and do not imply full material fidelity.
- Implemented: `_o0` textures encoded as BC5 UNorm in the observed local W1 material tables can be decoded and toggled as stored R/G channel diagnostics. The local scan attaches `Mask` and `MaskOpaque` to 13 UV meshes; the assigned route program declares `_o0` as `cTexMapRouteMask`.
- Implemented: `_o1` textures encoded as BC4 UNorm in the local W1 route materials can be decoded and toggled as grayscale channel diagnostics. `RouteW1_msk` attaches to eight UV meshes; the assigned route program declares `_o1` as `cTexMapEdgeMask`.
- Implemented: Front, Side and Top camera presets orient the viewer around its current focus point, expose their selected state accessibly, and clear that state when the user resumes orbiting.
- Implemented: the camera panel exposes editable preview-target X/Y/Z coordinates in model units, updates after mesh focus and Fit view, and rejects non-finite or out-of-range values without changing the active target.
- Implemented: selected-mesh texture cards report dimensions, supported stored formats, and exact sampler-symbol names when the BFRES material resolves to a local SHARCFB program. These labels describe declared shader interfaces; they do not reproduce the material's shader calculations.
- Implemented: local W1 BC4 UNorm sampler maps in `_b0`, `_o1`, `_s0`, and `_x2` can be chosen in a diagnostic selector. The four slots expose 19 maps across 42 supported shapes. A 36-material/258-reference scan found no paired-table mismatches; four fixed BC4 sampler vectors cover the slots. The assigned shader declarations name `_b0`/`_b1` bake maps, `_s0` spec mask, and `_o1` edge mask; channel displays still show stored texels only.
- Implemented: bounded, read-only extraction of type-31 `texmtxN` SRT fields for the tested W1 materials. The inspector displays stored mode, scale, rotation and translation without applying a UV matrix or assigning the parameter to a sampler.
- Implemented: read-only BC3 UNorm thumbnails for the observed `_x0` and `_x1` sampler references. The preview preserves stored texels for inspection without applying them to material shading or assigning them shader meaning.
- Implemented: a bounded SHARCFB v8 metadata reader and `inspect-shaders` CLI. The local W1 BFRES material assignment resolves to five programs in `nw4f_cs_shader.sharcfb`; the WebGL inspector now shows assigned program names, sampler symbols, declared `texmtx` uniforms, an AGL-style mixed-radix material-option candidate, and each shader-input-to-BFRES-attribute binding with the actual stored vertex format. The shape-specific skinning variation remains unresolved.
- Verified in headless Chrome/SwiftShader: the local W1 page rendered 42 shapes, Top became active, model-space target entry changed the focus, the selected route mesh showed `RouteW1_msk | 128x256 | BC4 UNorm`, and no WebGL error overlay appeared. The user's browser/GPU is still unverified.
- Next: verify the controls on the user's browser/GPU. Use the resolved shader interface and candidate permutation to investigate one W1 material's uniform offsets, shape-specific variation, and GX2 texture-coordinate operations before using its maps in shading.
- Investigate UV transforms, transparent material modes, baked light maps, and additional GX2 tile layouts using local evidence and fixed regression vectors; do not infer shader meaning from a sampler name.
- The assigned route program declares `texmtx0` and `texmtx1`; determine their active variation, sampler association, matrix convention, and GX2 operations before applying either value. They remain inspection metadata only.
- The assigned programs declare `_x0`/`_x1` as `cLightMap0`/`cLightMap1`; determine their coordinate inputs and combination formulas before implementing a material path. Current thumbnails show decoded source values only.
- Broaden geometry parsing to multiple meshes, more vertex encodings, hierarchy transforms, skinning, and other BFRES variants. The current static geometry subset must reject unsupported layouts clearly.

## Terrain pipeline

- Keep the tested OBJ replacement limited to the existing main grass shape, with byte-range preservation and an export manifest.
- Implemented: OBJ parsing is streamed and bounded to 64 MiB, 64 KiB per line, one million lines, 500,000 attribute records/vertices, 200,000 faces, and 500,000 total corners; coordinates and UVs have explicit finite ranges, and editor status reports source vertex/polygon counts.
- Implemented: import-time conversion applies nonzero per-axis scale, XYZ rotation, and translation; a Z-up-to-Y-up preset uses a -90° X rotation. UVs are preserved, normals use inverse-transpose scaling, mirrored transforms reverse face winding, and the source OBJ remains unchanged.
- Implemented: baked-light UV transfer uses an exact nearest-XZ spatial tree, so far-offset imported vertices do not scan distance-scaled empty grid rings.
- Implemented: saved terrain geometry is validated before export, including required fields, topology, and finite supported attributes; malformed projects fail before output creation.
- Implemented: OBJ imports surface compatibility notes when material libraries/assignments, vertex colors, smoothing groups, object/group boundaries or non-polygon geometry are ignored.
- Implemented: one-entry local caches reuse BFRES material/texture indexes and the parsed shader container across repeated preview builds; cache keys use exact immutable source bytes.
- Simple planar concave OBJ faces now use ear clipping; malformed, non-planar, duplicate-corner and over-1,024-corner faces are rejected.
- Compare corrected terrain output against a controlled stock Cemu baseline. Investigate the previous dark patch observation and verify UV, color, culling, and lighting behavior.
- Add strict import diagnostics, coordinate/scale conversion controls, geometry summaries, and archive reimport validation.
- Investigate GLB/glTF as an authoring input. Do not claim arbitrary mesh insertion until a BFRES structure and in-game result prove it.

## Topology, events, and camera

- Implemented: project, editor, and export validation require a directed segment chain for newly added same-world destinations. Route edits recheck baseline-connected destinations and block an export if an edit disconnects one; pre-existing gaps and cross-world links are not treated as new failures.
- Implemented: a route segment may reference endpoints in another world without requiring those bones in the current BFRES. Local endpoints are still validated, and cross-world segments cannot satisfy local reachability checks.
- Extend graph validation only as each native reference is identified: level destinations, event dependencies, and progression conditions.
- Support route creation and node placement after safe bone naming, point indexes, and engine/script references are understood. Preserve unknown data and block unresolved exports.
- Improve camera offset editing with a clear table inspector, then map each bank and transition to in-game behavior.
- Keep the Cobra event table bridge offline until a loader or game-side hook is verified. Round-trip success alone does not establish that the game consumes an edited table.

## Editor and project workflow

- Implemented: native graph labels route around point markers and each other, with
  contrast backing plates; checked in a fresh local editor window.
- Implemented: bounded Ctrl+Z/Ctrl+Y history covers native point/route rows,
  BFRES position drafts, camera vectors and terrain imports; project switches
  reset the history and undo marks the project dirty.
- Implemented: native point dragging moves supported rest-pose points in the
  camera-facing plane, converts world targets back through the parent rest
  rotation, stores unsupported transforms only in the labeled editor layout,
  and records one undo step on release. Route drawing and placement of new
  engine-backed points remain blocked on native index/script-reference safety.
- Add transform handles and route-edit controls with project-level regression tests.
- Implemented: changed archive members have before/after hashes and sizes in the export manifest; overwriting a changed native project keeps one adjacent, openable previous-version backup.
- Add recent projects, recoverable sessions, multi-version backup rotation, and export/reimport comparison.
- Implemented: archive, camera companion and manifest export writes roll back files created by the current export if a later output write fails.
- Profile larger models/projects before further caching. Three local W1 texture-catalog runs had a median of 3.784 s without the material index cache and 3.152 s with it (16.7% in that stage only). Three cold shader-container loads had a 1.898 s median; warm reads returned in 0.004 s median while retaining 17,993,893 bytes of extracted shader archive data in-process. These are local component timings, not end-to-end browser or rendering benchmarks.

## Central acceptance milestone

Create and export a three-level custom world with original terrain, custom connected routes, working level entry, clear-triggered progression, save/reload support, and correct camera movement. Validate the same exported build in Cemu or on hardware and publish the exact steps and evidence. Until then, describe World Studio as a modding prototype and do not label a custom world playable.
