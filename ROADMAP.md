# Development roadmap

World Studio is an offline research prototype. Items below describe work still needed for a genuinely playable custom overworld; a passing parser or export test does not satisfy an in-game acceptance check.

## Highest priority: get a route to launch its level

On 2026-10-22, process-bound Cemu tests using the Chain archive moved Mario from
the visible Acorn Plains node to a road junction and then to the island course
card **Blooper's Secret Lair**. Configured `Z` opened the course and a later
capture shows live side-scrolling gameplay. The active `WorldStudioChain` SZS
and its installed copy both had SHA-256
`19dfe2d9d6f5427236e5336c2418d486962daa62982ed74d76533527c3a9995e`; the game
UI does not expose the selected island's internal point ID.

The direct Clean comparison from that same junction is still required to
attribute the visible transition to the edited W102→W103 link. Existing paired
Chain and Clean movement runs used controller-profile hash
`7f27b62eb731fdd4c4eae10b2f8a77f19a0fba233c0a469067db2034900f4d9b` (Wii U
GamePad). A later Clean retry used hash
`d4f9fcf8da2748ac094f479d53c96661fb60c559fc564e41805bfc4ecae3879c` (Wii U
Pro Controller); it held A for two seconds but showed no node change and was
aborted before further input. The key map is the same, but the emulated
controller type differs, so that retry is not a matched route comparison.
When Cemu testing resumes, repeat the Clean sequence from the known junction
with the same GamePad profile, identical held `W`/`S` sequence and verified
focus before each input; pass `--compare-controller-to` with the Chain profile
to make the runner enforce that match before launch. Then verify a course
clear, fresh-save progression, save/reload and camera transitions. Keep each
result tied to the exact pack, input profile and save snapshot. See
`docs/INTEGRATION.md` for process IDs, archive hashes, screenshots and the test
protocol.

## Rendering fidelity

- Implemented: 42 rigid static shapes, 70,193 vertices, 106,736 triangles, route overlays, shape filtering, visibility toggles, and 20 shared BC1/BC3 albedos on all 42 W1 shapes with decoded UV attributes.
- Implemented: native 3D preview selects the source archive's matching `<archive>_World` model when present. All twelve supplied world models now decode in the tested static subset: W1/W2a/W3/W4/W5a/W5b/W6a/W7/W8a/W8b/W9a/W9b yield 42/58/40/53/76/27/61/34/18/42/3/20 shapes. It supports observed float16x4 positions with W=1 and rigid attachment to supported rest-pose bones, including rotation, translation and positive scale with inverse-transpose normal handling. Segment-scale compensation and camera-facing billboard branches remain unsupported.
- Verified: supported BC1/BC3 base-color maps attach across all twelve static world models. Local coverage ranges from 2 maps on W9a to 32 each on W2a and W4; ambiguous multi-albedo materials, unsupported texture layouts and missing albedo references keep the explicit approximate-color fallback, with bounded per-shape reasons marked in the mesh list and inspector.
- Implemented: the WebGL viewer reads the `_a0` GX2 S/T wrap modes for base-color textures. Wrap and Mirror map to their WebGL equivalents; GX2 Clamp uses `CLAMP_TO_EDGE` with an approximation note, while unsupported border and MirrorOnce modes visibly fall back to Repeat. A scan of all twelve supplied world models found 76 non-Repeat base samplers among 415 albedo materials, all using power-of-two dimensions; the local preview regression checks this for every displayed non-Repeat texture.
- Implemented: `_u0` vertex decoding for observed GX2 `0x80D` float32x2, `0x7` UNorm16x2, `0x207` SNorm16x2, and `0x4` UNorm8x2 formats. W1 inventory and synthetic normalization/bounds tests cover all four; shader UV transforms remain unknown.
- Implemented: local W3/W5a/W7/W8a/W8b models also use `_u0` GX2 `0x808` Float16x2 and `0x204` SNORM8x2. Both are decoded into finite preview UV arrays; eight actual shape instances across the local models now carry those coordinates. Synthetic edge cases cover half-floats and signed-byte normalization; shader UV transforms remain unknown.
- Implemented: `_c0` diagnostics decode observed GX2 `0x00A` UNorm8x4 and `0x80F` half-float4 values, show unclamped raw ranges in the inspector, and clamp displayed RGB to 0–1. This inspects stored channels without assigning material or shader semantics.
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
- Implemented: selecting a UV mesh shows a raw UV chart, 0–1 tile, stored bounds, out-of-range vertex count, and valid/invalid triangle counts. Dense charts are sampled; no SRT or sampler transform is applied.
- Implemented: raw UV inspection now decodes every supported named `_uN` attribute and offers a per-mesh selector. The local W1 model exposes `_u1` on 42 shapes and `_u2` on 13; charts remain raw data and do not infer sampler use.
- Implemented: local W1 BC4 UNorm sampler maps in `_b0`, `_o1`, `_s0`, and `_x2` can be chosen in a diagnostic selector. The four slots expose 19 maps across 42 supported shapes. A 36-material/258-reference scan found no paired-table mismatches; four fixed BC4 sampler vectors cover the slots. The assigned shader declarations name `_b0`/`_b1` bake maps, `_s0` spec mask, and `_o1` edge mask; channel displays still show stored texels only.
- Implemented: bounded, read-only extraction of type-31 `texmtxN` SRT fields for the tested W1 materials. The inspector displays stored mode, scale, rotation and translation without applying a UV matrix or assigning the parameter to a sampler.
- Implemented: read-only BC3 UNorm thumbnails for the observed `_x0` and `_x1` sampler references. The preview preserves stored texels for inspection without applying them to material shading or assigning them shader meaning.
- Implemented: a bounded SHARCFB v8 metadata reader and `inspect-shaders` CLI. The local W1 BFRES material assignment resolves to five programs in `nw4f_cs_shader.sharcfb`; the WebGL inspector now shows assigned program names, sampler symbols, declared `texmtx` uniforms, an AGL-style mixed-radix material-option candidate, and each shader-input-to-BFRES-attribute binding with the actual stored vertex format. The supported rigid shape's BFRES `VertexSkinCount` is also exposed, while its mapping to `NUM_SKINNING_VTX` remains unresolved.
- Implemented: the shader inspector names unresolved shape-specific macros and displays the stored vertex-skin count. A local W1 regression pins the main-grass program candidate, sampler declarations, BFRES UV bindings, base texture, and stored `texmtx1`. This distinguishes the observed shape field from the still-unknown AGL skinning-value array and does not treat the candidate as the runtime shader.
- Verified in headless Chrome/SwiftShader: the local W1 page rendered 42 shapes, Top became active, model-space target entry changed the focus, the selected route mesh showed `RouteW1_msk | 128x256 | BC4 UNorm`, and no WebGL error overlay appeared. The user's browser/GPU is still unverified.
- Next: verify controls on the user's browser/GPU. Continue investigating one W1 material's uniform data, shape-specific variation, and GX2 texture-coordinate operations before using its maps in shading; the main-grass contract is now covered by an offline regression, but these shader details remain unsupported.
- Investigate UV transforms, transparent material modes, baked light maps, and additional GX2 tile layouts using local evidence and fixed regression vectors; do not infer shader meaning from a sampler name.
- The assigned route program declares `texmtx0` and `texmtx1`; determine their active variation, sampler association, matrix convention, and GX2 operations before applying either value. They remain inspection metadata only.
- The assigned programs declare `_x0`/`_x1` as `cLightMap0`/`cLightMap1`; determine their coordinate inputs and combination formulas before implementing a material path. Current thumbnails show decoded source values only.
- Broaden geometry parsing to multiple meshes, more vertex encodings, hierarchy transforms, skinning, and other BFRES variants. The current static geometry subset must reject unsupported layouts clearly.

## Terrain pipeline

- Keep the tested OBJ replacement limited to the existing main grass shape, with byte-range preservation and an export manifest.
- Implemented: OBJ parsing is streamed and bounded to 64 MiB, 64 KiB per line, one million lines, 500,000 attribute records/vertices, 200,000 faces, and 500,000 total corners; coordinates and UVs have explicit finite ranges, and editor status reports source vertex/polygon counts.
- Implemented: import-time conversion applies nonzero per-axis scale, XYZ rotation, and translation; a Z-up-to-Y-up preset uses a -90° X rotation. UVs are preserved, normals use inverse-transpose scaling, mirrored transforms reverse face winding, and the source OBJ remains unchanged.
- Implemented: baked-light UV transfer finds the closest non-degenerate source triangle in XZ and interpolates its UVs barycentrically. Ambiguous overlapping projections and degenerate source topology fall back to the exact nearest-vertex spatial tree.
- Implemented: terrain export reports the maximum XZ distance from imported vertices to the projected source surface (or nearest-vertex fallback) and records a configurable 128-unit review warning; the warning is surfaced in the editor and export manifest, without claiming visual correctness.
- Implemented: saved terrain geometry is validated before export, including required fields, topology, and finite supported attributes; malformed projects fail before output creation.
- Implemented: OBJ imports surface compatibility notes when material libraries/assignments, vertex colors, smoothing groups, object/group boundaries or non-polygon geometry are ignored.
- Implemented: import and preview static glTF 2.0 triangle meshes from embedded GLB or JSON `.gltf`, with bounded float32 positions/normals, float32 or normalized unsigned-byte/short UVs, hierarchical TRS and affine node matrices, and clear rejection of compressed data, skinning, morphs, repeated-node DAGs and unsupported layouts. JSON glTF allows up to 16 local relative sidecar buffers or base64 data URIs, rejects network and paths escaping the source folder, and validates declared byte lengths under a 64 MiB aggregate limit. Repeated meshes on separate scene nodes are expanded under geometry limits. Node transforms apply inverse-transpose normal conversion and mirrored winding. Material rendering and in-game results remain unverified.
- Implemented: one-entry local caches reuse BFRES material/texture indexes and the parsed shader container across repeated preview builds; cache keys use exact immutable source bytes.
- Simple planar concave OBJ faces now use ear clipping; malformed, non-planar, duplicate-corner and over-1,024-corner faces are rejected.
- Compare corrected terrain output against a controlled stock Cemu baseline. Investigate the previous dark patch observation and verify UV, color, culling, and lighting behavior.
- Add strict import diagnostics, coordinate/scale conversion controls, geometry summaries, and archive reimport validation.
- Consider additional explicitly tested static vertex encodings. Do not claim arbitrary mesh insertion until a BFRES structure and in-game result prove it.

## Topology, events, and camera

- Implemented: repeatable static reachability profiles use an explicit versioned schema, world-prefix binding, bounded JSON input, duplicate-key and point-ID checks, and a checked-in W1 profile for W101 to W102/W103. The test establishes native graph connectivity only; event references and game progression semantics remain unidentified.
- Implemented: the Cobra bridge can inventory an exported event text file by script ID, priority, command count and numeric command-ID frequency, with source hashes and optional local-registry checks. The report deliberately omits arguments and command semantics; point, unlock and runtime links remain unidentified.
- Implemented: project, editor, and export validation require a directed segment chain for newly added same-world destinations. Changed local destinations are also checked against paired BFRES macro-path references when the listed bones form one unambiguous linear chain. Branched legacy lists, pre-existing gaps and cross-world links are preserved. Route edits recheck baseline-connected destinations and block an export if an edit disconnects one.
- Implemented: a route segment may reference endpoints in another world without requiring those bones in the current BFRES. Local endpoints are still validated, and cross-world segments cannot satisfy local reachability checks.
- Extend graph validation only as each native reference is identified: level destinations, event dependencies, and progression conditions.
- Implemented: the native Add segment dialog offers unused BFRES route IDs whose local endpoint bones resolve, lists IDs already referenced by point path chains first, reuses a road type present in the source table, and rejects duplicate segments. It adds only the route CSV row; point destination/path-chain wiring and game use remain unverified.
- Implemented: selected native points can open a route-connection draft that uses a unique shortest path from resolved BFRES endpoint names within the same world, adds missing route-table rows, and replaces either the normal or secret destination/path pair in one undoable edit. Tied, unreachable, remote-world or unresolvable chains remain unavailable; export validation still applies, and Cemu behavior is unverified.
- Implemented: native point path-chain fields have an ordered BFRES-ID picker with add, remove, reorder, and an explicit unique-shortest-chain suggestion for a single destination. New IDs must be present in the BFRES and have resolvable local endpoints; existing unresolved strings are retained unless removed, and untouched fields roundtrip exactly. Tied paths yield no suggestion. Route-table wiring, destination editing and in-game movement remain separate and unverified.
- Implemented: native normal and secret point destinations use an ordered point-ID picker with add, remove and reorder actions. It preserves unresolved IDs until removed, excludes a self-destination from new choices, waits for Apply before editing the CSV, and participates in undo/redo. For a single destination with a unique existing BFRES chain, the selected-point connection draft can now update its destination/path pair and missing route rows together; manual edits remain available. The native validator still gates export, and game behavior is unverified.
- Continue full route creation and node placement after route-geometry links, safe bone naming, point indexes, and engine/script references are understood. Preserve unknown data and block unresolved exports.
- Implemented: the camera companion inspector lists each raw record for both banks, with stored name, XYZ components and unknown-u32 values visible; selected vectors can be edited without changing protected fields. Camera Apply participates in project history, and an open inspector now refreshes on Undo/Redo. Bank meanings and actual camera movement still require in-game mapping.
- Keep the Cobra event table bridge offline until a loader or game-side hook is verified. Round-trip success alone does not establish that the game consumes an edited table.

## Editor and project workflow

- Implemented: the native graph viewport fits its nodes using the same
  perspective projection as drawing, coalesces the initial fit until layout is
  ready, and refits on resize only until the user orbits/zooms. The Fit view
  action restores automatic fitting. Synthetic coverage checks rotated depth
  bounds, resizing and invalid coordinates.
- Implemented: native graph labels route around point markers and each other, with
  contrast backing plates; checked in a fresh local editor window.
- Implemented: live case-insensitive filtering across native point IDs, route
  segments and supported BFRES bone XYZ entries; clearing a hidden selection also
  clears its edit form and native selection state.
- Implemented: bounded Ctrl+Z/Ctrl+Y history covers native point/route rows,
  BFRES position drafts, camera vectors and terrain imports; project switches
  reset the history and undo marks the project dirty.
- Implemented: native point dragging moves supported rest-pose points in the
  camera-facing plane, converts world targets back through the parent rest
  rotation, stores unsupported transforms only in the labeled editor layout,
  and records one undo step on release. Route drawing and placement of new
  engine-backed points remain blocked on native index/script-reference safety.
- Add transform handles and route-edit controls with project-level regression tests.
- Implemented: changed archive members have before/after hashes and sizes in the export manifest; overwriting a changed native or OBJ-preview project rotates two adjacent, openable previous-version backups.
- Implemented: a Recent menu stores up to ten native and ten preview paths in user settings, filters by editor type, and uses the existing unsaved-change guard when reopening.
- Implemented: preview projects resolve relative terrain references against the project file on open, preserving the same asset on save and Save As from a different directory.
- Implemented: preview projects persist imported terrain scale, XYZ rotation and translation and reapply them when the referenced mesh is reopened or saved to a new project location. Older preview projects without a transform remain in source coordinates; in-game terrain appearance and collision remain unverified.
- Implemented: newly imported preview terrain records separate SHA-256 fingerprints for parsed positions/topology and UV/normal attributes. On reopen, changes to either are detected and the stale scene is withheld until re-import; older projects without the attribute fingerprint remain loadable. Source material-only changes are not fingerprinted because OBJ material libraries and assignments are not imported.
- Implemented: native sessions opened from an SZS source or saved JSON, plus saved preview projects, receive a debounced, checksummed recovery snapshot with a 64 MiB limit; snapshots bind to the source-file path/hash, and reopening offers restore while save/discard clears recovery data.
- Implemented: `verify-export` reimports a saved-project export, compares every archive member against a fresh export, validates the manifest and checks camera companion outputs; runtime behavior remains separate.
- Implemented: archive, camera companion and manifest export writes roll back files created by the current export if a later output write fails.
- Profile larger models/projects before further caching. Three local W1 texture-catalog runs had a median of 3.784 s without the material index cache and 3.152 s with it (16.7% in that stage only). Three cold shader-container loads had a 1.898 s median; warm reads returned in 0.004 s median while retaining 17,993,893 bytes of extracted shader archive data in-process. These are local component timings, not end-to-end browser or rendering benchmarks.

## Central acceptance milestone

Create and export a three-level custom world with original terrain, custom connected routes, working level entry, clear-triggered progression, save/reload support, and correct camera movement. Validate the same exported build in Cemu or on hardware and publish the exact steps and evidence. Until then, describe World Studio as a modding prototype and do not label a custom world playable.
