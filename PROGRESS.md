# NSMBU World Studio progress

## 2026-10-20 — verified resource/tooling milestone

Completed:
- Inspected provided dump without modifying it. Inventory of all 13 course-select
  SZS archives and local RPX string evidence is in `docs/RESOURCE_FINDINGS.md`.
- Investigated Tsuru, Cobra, CSScript, Pyamoto and newer upstream headers. Pinned
  commits, licenses, addresses with version caveats: `docs/RESEARCH.md`.
- Implemented strict Yaz0/SARC reading and layout-preserving replacement. Unknown
  members retain their offsets and contents; unchanged exports are byte-identical.
- Implemented CP932 point/route CSV round-trip with original line/quote retention.
- Parsed actual Wii U BFRES model/skeleton dictionaries and local bone transforms.
  Surgical translation export changes only intended float/flag bytes.
- Built an experimental W101 -> W102 -> W103 normal progression resource patch.
  W102 uses existing `RW102W1T0,RW1T0W103`. Stock row order and all script-sensitive
  points remain; W103 has no new normal unlock targets. The tower remains present.
- Added standalone standard-library tkinter editor with projected 3D viewport,
  native table editing, local XYZ editing, project persistence, validation/export,
  original island OBJ preview. Python 3.14/tkinter 9 are installed; no dependency
  installation is needed. OBJ is not converted to BFRES.
- Seven automated tests pass, including actual dump round-trip/export preservation,
  index/reference rejection and byte-range checks for bone patches.

## 2026-10-20 — editor, geometry subcase, emulator integration

- Native editor visually inspected and corrected: known level bones shown by
  default, optional auxiliary layout, fit view, scrolling property controls.
  Export runs in a worker while edits are locked and status remains responsive.
- Original OBJ import can replace exactly one verified rigid grass shape while
  keeping materials/pointers/allocations/counts; normals, UVs, bounds regenerated.
  A 29-vertex/54-triangle original island is in `examples/island-game.obj`.
  This is a partial landscape replacement, not a fully original world.
- Added bounded LZ77 Yaz0 compression. W1 recompression is about 6.73 MB vs the
  original 6.66 MB; full decompression round-trip verified.
- CSV edited cells retain explicit original quoting, including single-item and
  empty array cells, instead of relying on a generic CSV writer's minimal quotes.
- All twelve per-world archives parsed successfully with the native BFRES reader.
- Cemu 1.26.2f (folder misleadingly named 2.6) tested in an isolated copied setup.
  Legacy wizard/keyboard compatibility fixes are in `tools/prepare_cemu.py`.
  Shared permanent settings, saves, installed updates and Cloudy overrides excluded.
- Original-resource baseline and quote-preserving topology-patched World 1 both
  reached a visibly rendered, animated world map. Active packs/paths/hashes were
  checked. Runtime logs stay locally under ignored `local/evidence/`.
- For traversal testing, copied the existing local common save into the isolated
  test only; its original is untouched. A separate fresh test save was preserved.
  The loaded snapshot starts Mario at the tower. This is not fresh progression QA.
- Automated key taps were not reliably observed by the game. Human movement test
  is in progress; no claim of a verified W102-to-W103 traversal yet.
- The experimental island pack now loads to the World 1 map in a separate Cemu
  instance. It does not crash during map load. The visible render has broad dark
  green patches over the western plains; without a controlled baseline replay,
  this is a warning, not a visual-pass result. Geometry and material/culling
  behavior remain unverified.
- Generated final quote-preserving island artifact is `build/island-quoted/`;
  SHA256 `4f356d954f48a6ffe1954b78c59a8d874c5c4867bc042b3a6f1dd90d25a39b81`.

## 2026-10-21 — camera, event and route experiments

- Added bounded parsers/editors for the actual World 1 Mario and look offset
  tables. All 18 companion files round-trip byte-for-byte. Only their XYZ
  vectors are editable; unknown fields and the effect of each bank remain
  preserved or explicitly unverified.
- Added a direct-route variant: the existing tower path bone is renamed for
  W103 and the last native route segment is redirected. All original point rows
  and indices remain. Export and project reload pass; in-game traversal and
  scripts that may refer to the old bone name have not been tested.
- Added a local Cobra bridge and verified export/unchanged encode against the
  real RPX event table. Fixed two upstream encoder defects through a small
  separately licensed patch. The resulting WMSC round-trip preserves all 121
  IDs and 993 commands. No in-game event loader was installed or tested.
- Implemented safe equal-length BFRES bone-name replacement by rebuilding the
  existing name dictionary, retaining its entry order and offsets. This is
  suitable for the direct-route experiment only after runtime validation.
- Full local suite: **51 tests passed in 77.548 seconds**, including actual
  resource checks and original-file protection. This does not verify gameplay.

## 2026-10-21 — main terrain mesh import correction

- The first geometry target, `beltmodel14__mtGrass`, spans only a narrow strip
  of the World 1 model. Replacing it with the example island made a large
  uncovered area appear, so that earlier visual result is not a valid island
  test.
- Switched the experimental exporter to `polySurface1489__mtGrass`, the main
  grass shape, and now imports OBJ corner UVs/normals with seam splitting.
  `_u1` baked-light coordinates are sampled from the original surface by
  nearest XZ vertex; `_c0` is set to neutral white. This is structurally tested,
  while the texture/channel interpretation and runtime appearance remain
  hypotheses until compared in Cemu.
- OBJ parsing and mesh exporter tests: **10 passed**. A corrected isolated
  Cemu pack was prepared at `build/cemu-island-mainlight`, but a controlled
  baseline comparison and final traversal observation are still outstanding.
- The user then reported that Mario **does not move** in the manual route test.
  This is a failed gameplay check; the exact input/state cause and the route's
  behavior remain undiagnosed.
- New export report: `build/island-mainlight/`; its manifest correctly says
  `game_tested:false`. No game file or original save was overwritten.

## 2026-10-21 — first native BFRES base texture in the preview

- Parsed the local W1 BFRES material/FTEX references and inventoried 113 textures
  across BC1, BC3, BC4, BC5 UNorm and BC5 SNORM. The main grass material's
  `Grass_alb` is a 256x256 BC1 texture using GX2 2D Thin1 layout.
- Added a bounds-checked extractor for that material reference, a BC1 decoder,
  and a mode-4 GX2 detiler based on pinned BfresLibrary source. Known-address
  vectors, synthetic tiled fixtures and the local W1 detiled hash are covered.
- The offline WebGL preview now displays `Grass_alb` on the main grass mesh using
  the BFRES `_u0` coordinates. Other materials still use approximate colors;
  light maps, game shaders and animation are not evaluated.
- The detiled texture matches SHA-256
  `5b3259554630cc41ab604eefaa55cff6035e00db99ddde509c1ee0b60bf65220` and
  decodes to 256x256 opaque RGBA pixels. WebGL mapping has not been visually
  inspected in a browser, and Cemu terrain appearance remains unverified.
- `texture_preview.py` handles only 2D Thin1, single-sample BC1. The four other
  W1 formats and broader material support remain future work.
- Full offline suite after this milestone: **78 tests passed**. Generated viewer
  JavaScript passes `node --check`; browser-level rendering and gameplay are
  still unverified.

## 2026-10-21 — Cemu movement test input audit

- The user's report that Mario does not move remains a failed gameplay check.
- Read-only inspection found two Cemu input profiles: the isolated baseline
  copy uses a keyboard profile with arrow keys; the separate user Cemu profile
  selects a DirectInput wireless controller. Keyboard input would not control
  the latter. The isolated Cemu process running during this inspection was the
  unpatched baseline; the exact window used for the prior test is unknown.
- This narrows a possible cause but does not prove it. Retest the patched build
  only after confirming the active Cemu window, its enabled World Studio pack,
  and an input source accepted by that window. Keep route/gameplay status failed
  until the character visibly traverses the expected nodes.
- The exact mainlight archive passes `validate-graph --entry W101 --require
  W102 --require W103`; W102's two existing path bones are present. This is
  static reachability evidence only. The same-profile baseline-then-patch
  movement check remains a human Cemu test.

## 2026-10-21 - BC3 albedos and compact W1 preview

- Added BC3 color/alpha decoding and the pinned GX2 128-bpp Thin1 microtile
  ordering. A synthetic surface round-trips across macro tiles and fixed address
  vectors; the local `RouteW1_alb` raw and detiled hashes are regression-tested.
- Material extraction now accepts only the observed BC1/BC3 base-color formats.
  The actual W1 BFRES resolves 17 unique textures across all 36 UV-bearing shapes;
  no UV material fell back. Decoded textures share one catalog, with bounds of
  4M pixels per texture and 16M pixels per preview scene. The viewer cuts out
  alpha below 50% and names each texture in the shape filter tooltip.
- Packed positions, normals, UVs and indexes as little-endian typed arrays. The
  same local 42-shape scene fell from about 16.8 MB to 8.1 MB. Its generated
  JavaScript passes `node --check`; the decoded BC3 route image shows a sandy
  path with green edging.
- Headless Chrome with SwiftShader renders the full scene, routes, labels and
  textures. Screenshot: `local/evidence/preview-w1-headless-swiftshader.png`
  (ignored local evidence). User-browser GPU behavior and Cemu rendering remain
  unverified.
- Synthetic extraction, decoder and viewer tests cover the new behavior. The complete
  local suite passed **91 tests in 72.403 seconds** after the raw-asset hash
  assertion; Python compileall passed.
- Only BC1/BC3 base colors are rendered. BC4/BC5 maps, game material settings,
  UV transforms, baked lighting, shaders, animation and arbitrary BFRES layouts
  remain unsupported. No in-game or Cemu claim changes.

## 2026-10-21 - SHARCFB interface and BFRES input inspection

- Added a bounds-checked, read-only SHARCFB v8 parser for little- and
  big-endian archives. It checks archive sections, record ranges, binary stage
  order and program variation bounds, and reports symbols without copying or
  decoding GX2 instruction payloads. The `inspect-shaders` CLI has compact
  output by default and full metadata with `--json`.
- Resolved the local World 1 BFRES assignments against the five programs in
  `nw4f_cs_shader.sharcfb`. All 42 supported shapes get their exact assigned
  program, matched sampler symbols, declared uniforms, and checked
  shader-input-to-BFRES-attribute mapping with the source attribute's stored
  format and offset.
- The selected route material reports AGL-style material-option candidate
  `190 / 576`. This follows the pinned Tsuru AGL lookup order; its separate
  shape-specific `NUM_SKINNING_VTX` lookup remains unresolved. The candidate is
  not claimed as the game's final active shader.
- The inspector groups these fields in an expandable panel. For the local
  route mesh it shows `_u4` / `aTexCoordRouteMask` mapped to BFRES `_u2`
  (`0x80D`, offset 24), and `_u3` / `aTexCoordBake0` mapped to `_u1`
  (`0x7`, offset 44). No unsupported vertex format is decoded, and no sampler
  UV behavior or shader calculation is inferred.
- Headless Chrome with SwiftShader rendered all 42 shapes, selected
  `hoge69__mtRW101W102a`, and exposed the candidate and input bindings without
  a WebGL error overlay. Ignored local evidence is
  `local/evidence/preview-w1-shader-bindings.png`.
- Verification: **178 tests passed in 109.583 seconds**; focused parser, mesh
  and viewer tests passed; `compileall`, `git diff --check`, and graph
  reachability from W101 to W102/W103 passed. This does not validate game
  shaders, final active variation, Cemu rendering, or Mario's route movement.

Next: identify the form-specific skinning value and trace one shader's declared
uniform and texture-coordinate operations using independently checkable local
evidence. Keep route movement marked failed until a Cemu traversal is observed.

Not yet proven / outstanding:
- Actual game traversal, level launch, clear-triggered unlock/save persistence,
  camera behavior and cutscene interactions for the topology experiment.
- A fully original in-game island: arbitrary mesh/material import/export is absent.
  The original OBJ now has a bounded native mesh-export path targeting the main
  grass shape, but its in-game rendering is not yet verified and other stock
  shapes remain.
- New node/route bones and safe engine/script index remapping. Draft add/delete
  is allowed in the editor but export blocks unresolved references/index changes.
- Runtime camera behavior and event integration, animation authoring, executable
  loader integration, and verified patches for engine limitations. Bounded
  camera-table editing and offline event-table conversion are implemented, but
  they do not yet establish in-game behavior.

Next steps: reproduce the reported movement failure with the current Cemu input
state, compare the corrected main-grass island render against a controlled
baseline, then verify level launch, fresh clear-triggered unlocks and save
persistence. No claimed completion of the full custom-overworld mission.

## 2026-10-21 - topology, OBJ and viewer safety checks

- OBJ polygon import now keeps the original fan order for convex faces and uses
  ear clipping for simple planar concave faces. Non-planar, self-intersecting,
  duplicate-corner and faces above 1,024 corners fail with explicit errors.
  Tests cover both windings, area, UV-corner association and rejection paths.
- Native graph validation now checks changed same-world destinations against
  directed route-segment chains when the supplied baseline inventories are
  complete and locally resolvable. It skips partial inventories and cross-world
  links. The W1 graph and both route demo variants still validate cleanly.
- WebGL context, shader/program and mesh initialization failures now leave a
  high-contrast viewer error overlay instead of an empty canvas.
- Full suite: **99 tests passed in 94.045 seconds**. `compileall`, inline viewer
  JavaScript `node --check`, the SVG parser and the W1 `validate-graph` command
  passed.
- The isolated `cemu-island-mainlight` log confirms `World Studio Chain` and
  `Title Screen Crash Fix` activate. A fresh test save was created in its own
  MLC, SpotPass was declined, and the game reached its title screen. Route
  movement is still unverified: computer-use key taps did not pass the title
  prompt, so no traversal result can be inferred from this boot.

## 2026-10-21 — selectable meshes and geometry inspector

- Added keyboard-accessible mesh-name buttons alongside independent visibility
  checkboxes. Selection highlights the active row and reports its material,
  vertex/triangle counts, UV presence, base texture, and BC5 diagnostic map.
- Inspector values are inserted as text, so BFRES-provided names are not parsed
  as markup. Automated Node interaction coverage verifies row changes and the
  displayed geometry and texture data; generated viewer JavaScript is syntax
  checked. Full regression: **122 tests passed in 94.541 seconds**; `compileall`,
  `git diff --check`, and the local W101→W102→W103 route validation passed. A
  normal browser visual check remains outstanding.

Next: run the patched map with an input source Cemu actually accepts, record the
stock route as a control, then retest Mario's movement and the corrected terrain
against the same known Cemu profile. Level start, progression, persistence,
camera behavior and a fully playable custom world remain open.

## 2026-10-21 - Native graph label readability

- The native graph now places route and point labels around node markers and
  existing labels, using compact dark backing plates for contrast. This removes
  the W1 label collisions observed in the prior editor screenshot.
- Verified visually in a fresh native editor instance with the local `CS_W1.szs`;
  Python `compileall` and `git diff --check` passed. The change affects editor
  presentation only and provides no new evidence about game behavior.

## 2026-10-21 - Bounded editor undo and redo

- Added `Ctrl+Z` / `Ctrl+Y` / `Ctrl+Shift+Z` and toolbar controls backed by a
  32-state history. It covers native point and route rows, local BFRES position
  drafts, camera offset vectors, and imported terrain geometry. Project load or
  reload resets the history; restoring an edit marks the project dirty.
- Regression coverage verifies branch truncation, history limits, reset, and
  end-to-end native bone and route-row undo/redo in the hidden Tk editor.
- The full offline suite passed **102 tests in 99.180 seconds**; `compileall`
  passed. A fresh native editor window shows the controls disabled until the
  first edit, and the graph labels remain readable. Gameplay status is unchanged.

## 2026-10-21 - Route connectivity guards project export

- Connected native route validation to `WorldProject.validate()`, which is used
  by the editor and export. Adding a same-world destination without a directed
  segment chain is rejected; changing route edges rechecks baseline-connected
  destinations and refuses an export if one is disconnected.
- Kept pre-existing path gaps and cross-world endpoints out of new route errors.
  The local W1 inventory includes two route endpoints from other worlds that do
  not appear in this archive's BFRES, so the check only requires locally
  resolvable endpoints and compares each existing destination against its own
  baseline path.
- On the local W1 archive, the stock project validates cleanly and removing any
  of 84 route rows was detected to break at least one previously connected
  destination. A regression test removes a discovered segment and verifies
  project validation and export both reject it before writing output. A
  synthetic three-node test covers the same guard without game files.
- In-game route movement is still failed/unverified; this is a static export
  safety check and does not establish runtime traversal or level launching.
- Regression: **106 tests passed in 94.611 seconds**. `compileall`,
  `git diff --check`, and local W1 `validate-graph --entry W101 --require
  W102 --require W103` all passed.

## 2026-10-21 - Radius-aware WebGL depth planes

- The preview now derives its perspective near/far planes from the model radius
  and current camera distance. This narrows the depth range at fit and zoom-out
  while retaining a positive near floor when the camera moves inside the model
  bounds. Missing, non-finite or non-positive radius data uses a safe default.
- A Node-backed regression checks fit, maximum zoom-out, close-up and invalid
  camera inputs. The generated page for the local W1 model passes `node --check`
  with all 42 shapes and 17 textures (8,078,351 HTML characters).
- Final local regression for these changes: **108 tests passed in 93.883
  seconds**. `compileall`, the W1 `validate-graph` command and `git diff --check`
  passed. Cemu rendering and user-browser GPU behavior remain unverified.

## 2026-10-21 - BC5 SNORM channel inspection

- Added bounded extraction for material-referenced BC5 SNORM `_nml` textures.
  It verifies the local W1 sampler dictionary has the matching `_n0` slot and
  rejects unsupported formats or reference/sampler count mismatches.
- Added signed BC4 channel decoding and reused the tested 128-bpp GX2 Thin1
  block address path. Interpolation uses normalized endpoints, and the
  implementation-dependent `(-127, -128)` endpoint order is rejected. The
  viewer now has an opt-in “BC5 channels” mode that shows R/G diagnostic colors
  on six unique maps across 22 UV meshes. It does not reconstruct Z, infer
  tangent-space orientation, or change lighting.
- Added a wireframe mode with deduplicated triangle edges. A Node regression
  verifies its edge output while the generated page syntax test covers both
  controls.
- Added a sampled vertex-normal overlay with model-scaled line length and a
  scene-wide sampling cap; a Node regression verifies the generated vectors.
- Local W1 `RouteW1_nml` fixture: 128x256, format `0x235`, pitch 32, nine mips
  reported, 32,768-byte top-level image. Raw and detiled hashes are recorded in
  `docs/RESEARCH.md`; synthetic and local tests cover signed endpoints, crops,
  malformed sizes, slot validation and shared GX2 addressing.
- Focused texture, extractor and viewer tests: **42 passed**. The full offline
  suite passed **121 tests in 95.439 seconds**; `compileall`, `git diff --check`,
  and the local W1 route-validation command passed. The generated W1 page has
  42 shapes, 17 albedos, six BC5 maps and valid inline JavaScript. The WebGL
  controls are automated-test-covered; their visible appearance in the user's
  browser and Cemu is still unverified.

## 2026-10-21 — preview lighting controls

- Added azimuth, elevation, and intensity sliders to the WebGL viewer. They
  control only the illustrative preview shader; the default direction preserves
  the existing approximate light and no game data is changed.
- A Node-backed control test dispatches a slider input and checks the shader
  direction, intensity, and accessible value labels. Browser visual inspection
  passed in headless Chrome with SwiftShader. The render of the 42-shape local
  W1 model shows the inspector and all three lighting sliders at 1440×900;
  screenshot is in ignored `local/evidence/preview-w1-lighting.png`. User-browser
  GPU behavior remains unverified. The full suite passed **123 tests in 99.609
  seconds**; `compileall`, `git diff --check`, and local route validation passed.

## 2026-10-21 — focus camera on a selected mesh

- Each preview mesh now records a finite local bounding center and radius. Its
  inspector adds a Focus mesh action that centers the camera on the chosen
  shape and scales the view distance to that shape; Fit view returns to the
  whole-scene center.
- Node-backed tests cover empty and non-empty bounds, focus distance, and
  selection-to-focus wiring. The W1 page still renders in headless Chrome;
  actual pointer interaction in a user's browser remains outstanding. Full
  regression: **125 tests passed in 99.005 seconds**; `compileall`,
  `git diff --check`, and local W1 graph validation passed.

## 2026-10-21 — viewport mesh picking

- Added a WebGL color-ID pass that selects the top visible mesh under a click,
  respects depth and base-texture alpha cutouts, and maps high-DPI canvas pixels
  back to the right identifier. Drag gestures still orbit or pan the camera.
- Synthetic tests cover ID encoding/decoding, high-DPI mapping, texture-cutout
  shader wiring, and click-versus-drag dispatch. A headless Chrome run against
  the local 42-shape W1 BFRES selected `polySurface1489__mtGrass` at a projected
  surface point and showed the mesh inspector. Evidence:
  `local/evidence/preview-w1-pick-rAF.png` (ignored local evidence). Full
  regression: **127 tests passed in 97.515 seconds**; `compileall`,
  `git diff --check`, and local W1 graph validation passed.

## 2026-10-21 — Cemu baseline input retest

- Identified the isolated baseline Cemu window by executable path and confirmed
  its GamePad/Keyboard profile maps `D` to right. The game was at the Acorn
  Plains-1 node. After dismissing the open input-settings panel, both `D` and
  Right-arrow taps left Mario visibly stationary.
- This fails the baseline input check, so it cannot distinguish route data from
  emulator input. Logged the evidence in `docs/INTEGRATION.md`; a physical or
  otherwise accepted controller source is still needed for traversal QA.

## 2026-10-21 — texture thumbnails in mesh inspector

- Added cached, nearest-sampled inspector thumbnails capped at 96×96 pixels for
  supported base-color and BC5 diagnostic maps. Pixel sampling validates RGBA
  dimensions and avoids allocating a full-resolution canvas for previews.
- Headless Chrome rendered the actual `RouteW1_alb` image beside the separate
  `RouteW1_nml` diagnostic sample on the selected route mesh. Screenshot:
  `local/evidence/preview-w1-texture-inspector-bc5.png` (ignored evidence).
  Full regression: **129 tests passed in 88.426 seconds**; `compileall`,
  `git diff --check`, and local W1 graph validation passed.

## 2026-10-21 — native graph point dragging

- Native graph points can now be dragged in the camera-facing plane; dragging
  empty space continues to orbit. Supported BFRES points convert the target
  model-space rest position through the inverse parent rotation before their
  local XYZ is changed. Unsupported transforms stay in the labeled editor
  layout and never become guessed game coordinates.
- A completed drag is one undo/redo edit. Tests cover camera-plane basis math,
  rotated-parent world/local roundtrips, unsupported parents, and a Tk editor
  drag with undo and redo. The local W1 points were also checked: **66 supported
  points round-trip with zero local-coordinate error**. Cemu behavior is
  unchanged and still unverified.
- Baseline full suite: **129 tests passed in 88.915 seconds**. Focused checks
  after implementation: **15 tests passed**. Full post-change suite:
  **135 tests passed in 91.155 seconds**; `compileall`, `git diff --check`,
  and the W101 → W102/W103 validator also passed.

## 2026-10-21 — optional BC5 tangent-space preview

- Added an opt-in BC5 lighting mode, separate from the diagnostic channel
  display and disabled unless a mapped mesh has usable UV-derived tangents.
  Tangents are accumulated from indexed triangles, orthogonalized against the
  vertex normals, and retain mirrored-UV handedness. The shader reconstructs
  positive Z from signed R/G and applies the preview TBN frame.
- Node tests cover regular and mirrored UV bases and reject fully degenerate
  UV triangles. Headless Chrome/SwiftShader loaded the actual local W1 scene:
  all **22 of 22** mapped UV meshes received tangent buffers; the mode toggled
  on with no page or WebGL initialization errors. Screenshot:
  `local/evidence/preview-w1-bc5-lighting-on.png` (ignored local evidence).
- This demonstrates the optional renderer path only. BC5 channel orientation,
  green-channel convention and NSMBU material settings remain unverified.
  Full regression: **136 tests passed in 91.231 seconds**; `compileall`,
  `git diff --check`, and the W101 → W102/W103 graph validator also passed.

## 2026-10-21 — bounded OBJ import feedback

- Changed OBJ parsing to stream UTF-8 lines and reject oversized files/lines,
  excessive line/record/face/corner counts, and out-of-range coordinates before
  conversion. UV-seam splitting has a separate vertex cap. These guards apply
  to preview and experimental replacement inputs; they do not widen the
  supported BFRES export layout.
- Import status now reports vertex and polygon counts and labels preview-only
  imports separately from an experimental main-grass replacement candidate.
  Regression tests cover the limits and reparse the checked-in island OBJ
  (29 vertices, 54 triangle faces).
- Full suite: **141 tests passed in 91.322 seconds**; `compileall`,
  `git diff --check`, and the W101 → W102/W103 graph validator passed.

## 2026-10-21 — OBJ coordinate and scale conversion

- Added an import dialog for non-destructive per-axis scale, XYZ rotation and
  translation before preview or experimental terrain replacement. A Z-up to
  Y-up preset rotates -90 degrees around X; status reports the applied values.
- Conversion preserves UVs, applies inverse-transpose scaling to normals and
  reverses face winding for mirrored scales. It refuses zero scale and results
  outside the tested model-unit range. Tests verify axis conversion, nonuniform
  normal transforms, mirrored faces and invalid scales.
- Full regression: **145 tests passed in 91.962 seconds**. `compileall`,
  `git diff --check`, and the W101 → W102/W103 graph validator passed.

## 2026-10-21 — BC5 UNorm sampler diagnostics

- Added bounded BC5 UNorm decoding and GX2 Thin1 detiling for the local W1
  `_o0` sampler path. It is labeled channel inspection; the game's slot
  semantics remain unknown. The viewer separates it from BC5 SNORM normals
  and optional approximate normal lighting.
- Local W1 table checks resolve two unique `_o0` maps (`Mask`, `MaskOpaque`)
  on 11 UV meshes. Raw and detiled fingerprints for `MaskOpaque` are recorded
  in `docs/RESEARCH.md`. Chrome/SwiftShader loaded all 42 shapes, enabled the
  diagnostic mode, and displayed the selected map without an error overlay;
  screenshot evidence is ignored under `local/evidence/`.
- Focused texture, BFRES-reference and WebGL tests: **56 passed**. Full
  regression: **150 tests passed in 93.243 seconds**; `compileall`,
  `git diff --check`, and W101 → W102/W103 reachability passed.

## 2026-10-21 — BC4 UNorm `_o1` diagnostics

- Added BC4 UNorm block decoding, 64-bpp GX2 Thin1 detiling, and a grayscale
  sampler-view mode separate from `_o0` BC5 and `_n0` normal-map controls.
  Material inspection and search now show each supported sampler map explicitly.
- The supplied W1 tables map `RouteW1_msk` (128×256, pitch 32) to `_o1` on six
  materials and seven UV meshes. Raw/detiled hashes are in `docs/RESEARCH.md`.
  Chrome/SwiftShader loaded all 42 shapes, enabled the `_o1` mode and displayed
  the route channel with no WebGL error overlay; evidence is in ignored
  `local/evidence/preview-w1-bc4-o1-diagnostic.png`.
- Focused texture, BFRES-reference and WebGL checks: **60 passed**. Full
  regression: **154 tests passed in 94.857 seconds**. `compileall`,
  `git diff --check`, SVG parsing, and W101 → W102/W103 reachability passed.

## 2026-10-21 — WebGL camera orientation presets

- Added Front, Side and Top controls to the viewer's inspector panel. Presets
  rotate around the current focus point; orbiting clears the selected state,
  while Fit view restores the whole-scene default framing.
- Added a Node-backed orientation test and UI wiring checks. Focused and full
  viewer safety tests: **23 passed**. Full regression: **155 tests passed in
  94.661 seconds**; `compileall`, `git diff --check`, and W101 → W102/W103
  reachability passed.

## 2026-10-21 — editable WebGL preview target

- Added an expandable X/Y/Z target editor in model units. Applying coordinates
  changes only the preview focus and clears pan; focusing a mesh and Fit view
  keep the controls synchronized. Non-finite and out-of-range targets are
  rejected without changing the current view target.
- Focused viewer tests: **24 passed**. Full regression: **156 tests passed in
  94.473 seconds**; `compileall`, `git diff --check`, and W101 → W102/W103
  reachability passed.

## 2026-10-21 — material texture metadata in the inspector

- Texture cards now show each supported map's decoded dimensions and stored
  GX2 format. The texture catalogs retain the format values for BC1/BC3 base
  maps and BC5 SNORM normal maps; sampler slots remain explicitly diagnostic.
- Focused WebGL and BFRES texture checks: **38 passed**. Full regression:
  **157 tests passed in 96.340 seconds**; `compileall`, `git diff --check`,
  and W101 → W102/W103 reachability passed.
- Headless Chrome/SwiftShader validation loaded all **42** W1 shapes, activated
  Top, applied target `(12.5, -3, 7.25)`, selected a route mesh and reported
  its `RouteW1_msk | 128x256 | BC4 UNorm` map without a WebGL error overlay.
  Screenshot evidence stays ignored under `local/evidence/`.

## 2026-10-21 — selectable multi-slot BC4 diagnostics

- Extended bounded BC4 decoding and local reference checks to the observed
  `_b0`, `_s0`, and `_x2` slots alongside `_o1`. The selector exposes all four
  slots and 16 supported maps across the 42-shape W1 scene; each mesh inspector
  row names its sampler. All remain grayscale channel diagnostics because the
  game's material semantics are unknown.
- Added fixed raw/detiled local-W1 vectors for one map in each added slot and
  reference-pairing coverage. Focused checks passed: **26 viewer tests** and
  **15 BFRES texture tests**.
- Headless Chrome/SwiftShader loaded 42 shapes, switched through `_o1`, `_b0`,
  `_s0`, and `_x2`, updated the inspector labels, and reported no WebGL error.
  The captured `_x2` view is ignored at
  `local/evidence/preview-w1-bc4-slots-controls.png`.
- Full regression: **160 tests passed in 101.599 seconds**. `compileall`,
  `git diff --check`, progress SVG parsing, and W101 → W102/W103 reachability
  passed.

## 2026-10-21 — read-only material texture SRT inspection

- Added a bounded reader for supported W1 `texmtxN` Texture SRT records and
  exposed the stored mode, scale, rotation and translation in a collapsed,
  scrollable material-inspector panel. The preview does not apply the values
  or claim which sampler consumes them.
- Local W1 validation found 36 identity `texmtx1` entries and 11 non-identity
  `texmtx0` values with negative V translation. Five parser tests passed,
  including synthetic malformed records; all 27 preview safety tests passed.
- Headless Chrome/SwiftShader loaded 42 shapes, opened the route material's SRT
  details, showed translations `-3` and `0`, and reported no WebGL error.
  The screenshot is ignored at
  `local/evidence/preview-w1-texture-srt-controls.png`.
- Full regression: **166 tests passed in 98.874 seconds**. `compileall`,
  `git diff --check`, SVG parsing, and W101 → W102/W103 reachability passed.

## 2026-10-21 — W1 `_x0` and `_x1` sampler thumbnails

- Added bounded BC3 UNorm (`0x33`) extraction and GX2 Thin1 decoding for the
  observed `_x0` and `_x1` W1 sampler pairs. The inspector now shows their
  decoded 16×16 texels beside each other with sampler, name, size and format;
  it labels both as diagnostic data and does not use them for shading.
- Local table checks mapped `lmDifCSW1a` and `lmSpcCSW1a` to 36 supported UV
  meshes each. Regression tests cover raw, detiled and decoded RGBA hashes for
  both images, synthetic malformed format pairings, and catalog attachment.
- Headless Chrome/SwiftShader loaded all 42 shapes, selected a course-ring
  material, displayed both sampler cards, and reported no JavaScript or WebGL
  errors. Ignored capture: `local/evidence/preview-w1-x0-x1-inspector.png`.
- Full regression: **168 tests passed in 102.949 seconds**. `compileall`,
  `git diff --check`, progress SVG parsing, and W101 → W102/W103 reachability
  passed. User-browser GPU behavior and in-game material behavior remain open.
- After the final preview-notice wording update, the focused texture and
  viewer-safety suites passed again (**17 + 27 tests**); compile and diff checks
  also passed.

## 2026-10-21 — End-to-end terrain export regression

- Added a local-dump integration test covering OBJ import, project save/load,
  SZS export, archive reopen, and re-extraction of the replaced grass shape.
  It checks the imported vertex and triangle payload, unchanged unrelated
  archive entries, and that the source dump remains byte-identical.
- The focused integration test passed (**1 test**), and the full regression
  passed (**179 tests in 127.269 seconds**). `compileall`, `git diff --check`,
  and W101 → W102/W103 reachability also passed. Cemu appearance, collision,
  route traversal, and level starts remain unverified.

## 2026-10-21 — Decode all observed W1 UV formats

- Extended static BFRES extraction to decode the four observed `_u0` formats:
  float32x2 (`0x80D`), UNorm16x2 (`0x7`), SNorm16x2 (`0x207`), and UNorm8x2
  (`0x4`). Synthetic tests cover normalized endpoints and stride-bound checks;
  the local W1 inventory accounts for all 42 shapes (36 + 3 + 2 + 1).
- With those coordinates, all **42** shapes resolve supported base-color maps
  (20 unique), eight normal maps attach to 26 shapes, two `_o0` maps to 13,
  and the BC4 selector exposes **19** maps across the four checked slots.
  Sampler views remain diagnostic, and UV transforms/shader operations are not
  inferred.
- Focused texture/viewer tests passed (**45 tests**). The full suite passed
  (**181 tests in 127.088 seconds**); `compileall`, `git diff --check`, and
  W101 → W102/W103 reachability passed. The generated local W1 preview page is
  22,034,943 bytes (21.01 MiB) with decoded maps embedded; this is not a load
  performance benchmark. The page is ignored at
  `local/evidence/preview-w1-uv-formats.html`.
- Headless Chrome did not produce a current screenshot because the installed
  command forwarded to the existing browser session. The updated viewer is
  covered by generated-JavaScript and data tests, but this UV milestone has no
  fresh browser screenshot. Cemu route movement and terrain appearance remain
  unverified.

## 2026-10-21 — Cross-world route checks and export rollback

- Corrected local graph validation to accept route segments with remote-world
  endpoints while continuing to require current-world endpoint bones. Cross-
  world segments remain excluded from local reachability. Regression tests
  reproduced the prior false rejection in both the pure validator and project
  validation before the fix; 16 focused graph/project tests now pass.
- Export now removes archive and companion files it created if a later
  companion or manifest write fails. A fault-injection test verifies an
  interrupted manifest write leaves no partial archive behind.
- Updated README's viewer payload figure to the current generated W1 page size:
  22,034,943 bytes (21.01 MiB). This is a file-size measurement, not a load
  performance claim.
- Full suite: **184 tests passed in 129.793 seconds**. `compileall`,
  `git diff --check`, and the W101 → W102/W103 reachability command passed.

## 2026-10-21 — Bound terrain lightmap UV transfer

- Replaced expanding empty-grid rings with a balanced spatial tree over
  occupied source cells. Nearest XZ matching remains exact while distant OBJ
  coordinates no longer scale the search by the gap to the stock terrain.
- A synthetic 10×10 source grid compares four far-offset results against
  brute-force nearest points and counts fewer than half the full-scan distance
  evaluations. One hundred randomized grids with twelve distant queries each
  also matched brute-force results.
- The focused mesh suite passed (**14 tests**) and the full suite passed
  (**185 tests in 130.928 seconds**); `compileall` and `git diff --check` also
  passed. In-game baked-light UV interpretation remains an unverified
  assumption until the corrected terrain is visually compared in Cemu.

## 2026-10-21 — Validate saved terrain geometry

- Reproduced a project-state bug where `geometry = {}` passed validation and
  later raised a raw `KeyError('vertices')` during export. Validation now
  checks the terrain object, required fields, and full supported geometry
  constraints; malformed records return a terrain-specific diagnostic and
  block export before any archive is created.
- Regression coverage checks missing fields and degenerate faces against a
  real local W1 source archive. The full suite passed (**186 tests in
  132.356 seconds**); `compileall` and `git diff --check` passed.

## 2026-10-21 — Reject malformed saved edits before export

- Hardened project validation against non-text point/route fields and malformed
  table rows. Invalid rows now produce row-specific diagnostics instead of
  raising type errors in name, destination, or route parsing.
- Saved position edits are checked against unique supported path-model bones,
  three finite numeric coordinates, and the BFRES patcher's +/-1e7 limit.
  Invalid edits stop export before output creation. The project loader also
  checks key container, path, and SHA-256 field types before applying saved
  state.
- Regression tests reproduce malformed point/route cells, an unknown bone,
  short/non-finite/out-of-range position vectors, and assert that no export is
  created. The full suite passed (**188 tests in 134.533 seconds**), with
  `compileall`, `git diff --check`, and W101 → W102/W103 reachability passing.
- No in-game findings changed: route movement, terrain appearance, level
  launches, progression, and save behavior remain unverified.

## 2026-10-21 — Keep native 3D preview generation off the Tk thread

- Moved native BFRES extraction, texture/material diagnostics, bounds
  calculation, typed-buffer packing, page writing, and browser launch to a
  background worker. The native graph is captured on the UI thread because it
  reads Tk state; editor changes and close are locked until the preview opens
  or reports an error.
- Kept the lightweight OBJ editor's direct preview path intact. Worker status
  and error dialogs are handled by the UI event loop.
- A Tk smoke test holds the worker, verifies the UI processes a scheduled
  callback, checks the graph snapshot and worker thread, then verifies status
  completion and unlock. The editor smoke suite passed (**7 tests**); the full
  suite passed (**190 tests in 134.483 seconds**). `compileall` and
  `git diff --check` passed.
- No render-fidelity or game-behavior claims changed. BFRES animations and full
  game shaders remain unsupported; Cemu route traversal and terrain appearance
  remain unverified.

## 2026-10-21 — Add per-entry export fingerprints

- Export manifests now include source and output SHA-256 hashes, byte sizes,
  and size deltas for each changed archive member, while retaining the existing
  `changed_entries` list and archive-level hashes.
- The local roundtrip regression independently recomputes every reported
  member hash and size from the source and reopened output archive. This makes
  exported CSV/BFRES changes auditable without treating byte changes as proof
  of game behavior.

## 2026-10-21 — Report native preview build stages

- The native 3D preview worker now reports its current stage through the Tk
  event loop while reading BFRES geometry, decoding supported maps, resolving
  local shader-interface metadata, and packing/opening the offline page.
- The editor smoke test confirms a worker status update reaches the UI while
  Tk continues servicing other events and edits remain locked until completion.
- The focused editor smoke suite passed (**7 tests**); the full suite passed
  (**190 tests in 133.396 seconds**), with `compileall` and `git diff --check`.

## 2026-10-21 — Preserve the previous project save

- Saving changed native or OBJ-preview project content over an existing file
  now keeps the two most recent prior versions beside it as `name.backup.json`
  and `name.backup-2.json`, using atomic replacement for each file. Unchanged
  saves do not rotate either backup, the regular JSON picker can open both, and
  the status bar reports the newest backup path. Rotation across multiple files
  is not transactional if a later replacement fails.
- A local regression reloads both the saved and backup projects and checks
  that each contains the intended version. Tests also perform multiple saves to
  verify that the newest two prior versions remain loadable and older history
  is rotated out. Recent-project discovery and recoverable sessions remain open.
- Tests cover native project loading and the lightweight editor's save/status
  path. The full suite passed (**195 tests in 152.289 seconds**), with
  `compileall` and `git diff --check`.

## 2026-10-21 — Add recent project access

- The editor now keeps up to ten native-resource/project paths and ten
  lightweight-preview paths in a versioned settings file under the user's
  local application data directory. The toolbar's Recent menu filters entries
  for the active editor and shows both file and parent folder.
- Successful opens and saves add entries; opening a recent item runs the same
  unsaved-change check and validates/loads into local state before replacing the
  current document. Native history includes source SZS archives and saved JSON
  projects. Opening a native JSON project at startup now retains that project
  path for the next save.
- Store tests cover ordering, deduplication, type filtering, the ten-item cap,
  and malformed-file recovery. Tk smoke coverage verifies native filtering,
  cancel behavior, and preview-save registration. The full suite passed
  (**202 tests in 149.170 seconds**), with `compileall` and `git diff --check`.

## 2026-10-21 — Recover saved-project editing sessions

- Editing a native session loaded from a saved JSON project or SZS source, and
  editing a saved lightweight-preview project, schedules a checksummed recovery
  snapshot after a 750 ms quiet period. Snapshots are stored outside project
  and game files in the user's local application data, bound to the exact
  source-file path/hash and editor kind, and limited to 64 MiB.
- Reopening a matching source offers an explicit restore prompt. Invalid, stale,
  oversized, or mismatched snapshots are rejected; manual save or an explicit
  discard removes recovery data.
- Unit and Tk smoke tests cover checksum/baseline validation, size caps, actual
  debounced writing, restore acceptance, and discard cleanup for native JSON
  and lightweight-preview projects. The full suite passed (**209 tests in
  148.323 seconds**), with `compileall` and `git diff --check`.

## 2026-10-21 — Recover native sessions opened from SZS

- Extended native recovery to direct SZS sessions by binding snapshots to the
  archive path and its exact baseline hash. Restoring edits never writes into
  the original archive; saving to a native project JSON or explicitly
  discarding the session removes the source-bound snapshot.
- A Tk smoke test verifies that a raw-SZS session restores after reopening and
  that the source archive bytes stay unchanged. The full suite passed
  (**214 tests in 149.983 seconds**), with `compileall` and `git diff --check`.

## 2026-10-21 — Compare exports with a fresh project reimport

- Added `python -m worldstudio verify-export <project.json> <export.szs>` to
  validate an existing export against a fresh export generated from the saved
  project. It checks the manifest's source/output hashes and path, all archive
  members and contents, manifest change metadata, and any camera companion
  outputs. The JSON result explicitly reports `game_tested: false`.
- Synthetic tests cover a valid roundtrip, a changed reimported resource even
  when the output hash is updated, a manifest tied to a different project, and
  a changed camera companion file. The full suite passed (**213 tests in
  149.962 seconds**), with `compileall` and `git diff --check`.

## 2026-10-21 — Prepare a truly clean Cemu baseline

- Audited the existing isolated Cemu settings and found that the folders named
  `cemu-integration` and `cemu-island-baseline` both enable WorldStudioChain
  alongside CrashFix. Their logs confirm the patch was active, so previous
  references to those runs as clean baseline evidence are withdrawn.
- Added `--baseline` to `tools/prepare_cemu.py`. It creates a separate MLC
  without user saves, enables CrashFix only, omits the World Studio pack, and
  tells the tester to confirm the keyboard stick assignment in Cemu 1.26.
  `build/cemu-clean-baseline` was launched once; its Cemu window showed the
  empty library, and no RPX was loaded.
- The focused Cemu preparation suite passed (**8 tests**). The full suite is
  green, and the full suite passed (**216 tests in 158.984 seconds**), with
  `compileall` and `git diff --check`. Runtime movement remains unverified.
- The later UI-control attempt could not continue after the clean window opened:
  repeated state capture returned `foreground window did not report a process id`.
  No control mapping or in-game movement result is claimed.

## 2026-10-21 — Protect native route bone identifiers

- Native route IDs name existing BFRES bones, so the selected-route form now
  displays that column read-only. Apply also restores the original ID before
  writing the edited row, protecting against direct Tk variable changes.
- Road type and reserved columns remain editable. A Tk regression checks the
  readonly control, ID preservation, road-type editing, and undo/redo. The
  focused test and full suite passed (**217 tests in 150.266 seconds**), with
  `compileall` and `git diff --check`. This does not add route bones or establish
  traversal behavior.

## 2026-10-21 — Add raw UV diagnostics to the 3D inspector

- Selecting a mesh with stored UVs now shows a raw UV triangle chart, UV bounds,
  vertices outside the 0–1 tile, and valid/invalid triangle counts. Dense charts
  sample at most 20,000 triangles; extreme UV ranges are clipped visibly at
  ±1,024 units.
- The inspector labels the chart as raw coordinates and explicitly says no
  texture SRT or sampler transform is applied. This exposes UV layout for
  debugging without claiming shader-accurate texturing.
- Synthetic Node tests cover bounds, out-of-range counts, invalid indices and
  chart drawing; the focused preview safety suite passed (**29 tests**). The
  full suite passed (**218 tests in 148.525 seconds**), with `compileall` and
  `git diff --check`.
- Headless Chrome/SwiftShader loaded the real 42-shape W1 page, selected
  `beltmodel14__mtGrass`, and rendered its UV chart and stored bounds without a
  WebGL error overlay. Screenshot: `local/evidence/preview-w1-uv-chart.png`
  (ignored local evidence; this is not in-game rendering verification).

## 2026-10-21 — Report unsupported OBJ features

- OBJ imports now report when they ignore MTL/material assignments, vertex
  colors, smoothing groups, object/group boundaries, or non-polygon geometry.
  The warning appears in editor status after preview import or when preparing
  the experimental native grass replacement; CLI demo notes include it too.
- Existing geometry parsing and its default return shape stay compatible. A
  regression confirms the polygon faces still import while all five warning
  categories are reported for a mixed-feature fixture.
- The focused OBJ suite passed (**13 tests**); the full suite passed (**192
  tests in 138.027 seconds**), with `compileall` and `git diff --check`.

## 2026-10-21 — Reuse immutable BFRES and shader indexes

- Profiled the local W1 preview pipeline. Across three runs, texture catalog
  extraction/decoding had a 3.784-second median without the index cache and a
  3.152-second median with it, a 16.7% improvement in that component. This is
  not an end-to-end preview benchmark.
- Added one-entry caches keyed by exact immutable BFRES or shader-container
  bytes. Repeated material/sampler reads reuse the BFRES dictionaries; repeated
  preview opens reuse the SZS shader-container parse. Replacing source bytes
  invalidates each cache, and shader callers get a fresh dictionary.
- Three local cold shader-container loads had a 1.898-second median; warm
  reads were 0.004 seconds median. The cache retains 17,993,893 bytes of
  extracted SHARCFB payloads in-process. No shader semantics are cached or
  inferred.
- Synthetic cache tests and local W1 material/texture/shader checks passed.
  The full suite passed (**194 tests in 137.866 seconds**), with `compileall`
  and `git diff --check`.

## 2026-10-21 — Lint encoded event command IDs

- WMSC post-encode validation now resolves NSMBU command IDs through Cobra's
  variant inheritance, applying renumbering, additions and deletions in order.
  Unknown IDs are listed with a clear advisory; numeric fallback IDs remain
  unchanged and encoding succeeds. An unknown/malformed registry is reported
  as unchecked instead of blocking the export.
- Tests cover synthetic inheritance, actual `1.3.0_NSLU` and `DX` command sets,
  deletion after renumbering, malformed registry data, advisory behavior and
  the local RPX event encode. The full suite passed (**221 tests in 147.539
  seconds**), with `compileall` and `git diff --check`.
- The check validates registry membership only. It does not prove that a
  command is accepted by the game or that an event loader is installed.

## 2026-10-21 — Live Cemu movement-state audit

- Re-inspected the running isolated Cemu window. Input Settings shows the
  game-selected Keyboard profile with W/A/S/D on the left stick and arrows on
  the D-pad; the right stick is unbound. No controller settings were changed.
- The rendered map showed Mario at Acorn Plains-1 (W101). Two short `D` taps
  turned his facing but did not move him to the next node. The UI automation
  does not provide a sustained key hold, so this is not a held-movement test.
- The active `WorldStudioChain` archive hash matches `build/chain-quoted`
  (`19dfe2d9d6f5427236e5336c2418d486962daa62982ed74d76533527c3a9995e`), not
  `build/direct-route-v2`. The clean CrashFix-only profile still has no RPX
  loaded. Route movement and the direct-route variant remain unverified.

## 2026-10-21 — Perspective-aware native graph framing

- The graph's Fit view now uses the same perspective projection as drawing and
  chooses the largest scale that keeps all model-space points inside the canvas.
  Initial fitting waits for widget layout; resize fitting coalesces configure
  events and stops when the user orbits or zooms, until Fit view is chosen again.
- Regression tests check rotated depth bounds, larger viewports and non-finite
  coordinates. The full suite passed (**223 tests in 172.707 seconds**), with
  `compileall` and `git diff --check`.
- This changes editor camera framing only; exported resource data is unchanged.

## 2026-10-21 — Search the native editor tree

- Added a live, case-insensitive filter for point IDs, route segments and
  supported BFRES bone XYZ entries, with visible match counts and a clear action.
- Filtering away the selected item now clears its property form and native
  selection/position state, so hidden stale edits cannot be applied.
- Tk editor smoke tests cover matching, clearing, unchanged source rows and
  hidden-selection cleanup. The full suite passed (**225 tests in 172.973
  seconds**), with `compileall` and `git diff --check`.

## 2026-10-21 — Inspect all supported W1 UV attributes

- Static BFRES extraction now decodes each named `_uN` attribute using the four
  already-tested GX2 two-component formats. The raw UV inspector lets users
  switch charts and shows each attribute's stored format.
- The local W1 model confirms `_u1` on 42 shapes and `_u2` on 13. Tests cover
  normalized decoding, local shape counts, viewer packing and selector changes.
  The full suite passed (**226 tests in 174.904 seconds**), with `compileall`
  and `git diff --check`.
- This exposes stored coordinates for comparison; sampler association, SRT math
  and game shader behavior remain unresolved, so the rendered material is unchanged.

## 2026-10-21 — Preview supported world models across archives

- Native preview now selects the matching `<archive>_World` BFRES model when
  present, and falls back to the existing W1 model for unsupported archives.
  Supported base-color decoding follows the selected model; W1-specific normal,
  sampler, SRT and shader metadata diagnostics remain limited to W1.
- Local offline fixtures confirm W7 renders 34 static shapes with 19 BC1 maps
  attached to 33 shapes, and W9a renders 3 shapes with 2 BC1 maps attached to
  all 3. A 12-archive survey found static parser incompatibilities in several
  other worlds; this is partial coverage, not arbitrary BFRES support.
- The W7 editor smoke test also checks that all parsed world nodes fall inside
  its geometry bounds. Full suite: **228 tests passed in 178.166 seconds**;
  `compileall` and `git diff --check` passed. Viewer/browser and in-game behavior
  were not tested; animation, general material fidelity, route movement and
  progression remain unverified.

## 2026-10-21 — Decode half-float positions in additional BFRES worlds

- Added a bounded decoder for GX2 format `0x80F` float16x4 positions. It uses
  XYZ only when the stored homogeneous W is finite and exactly 1 within the
  tested tolerance; unsupported W values fail with a shape-specific error.
  The format enum is corroborated by the checked-in Tsuru GX2 header, and local
  W3/W4/W9b position records all store W=1.
- The static parser now extracts 40 W3, 53 W4 and 20 W9b shapes, in addition
  to the previously supported W1/W7/W9a models. Synthetic tests cover valid and
  rejected W values; local archive tests check every returned shape has finite
  positions and triangle indices.
- Full suite: **231 tests passed in 183.284 seconds**; compileall and
  `git diff --check` passed. This remains offline static geometry validation.
- Cemu audit: the separate `cemu-clean-baseline` profile loaded the supplied
  RPX and its log confirms CrashFix only; first boot created a save and stopped
  at a SpotPass information screen. The misleading `cemu-island-baseline`
  profile has World Studio Chain enabled. No stock movement or terrain pass
  was observed; in-game route behavior remains unverified.

## 2026-10-21 — Apply translation-only BFRES root bones

- The static preview now applies the root bone's translation to rigid shape
  positions when the root scale and rotation are identity. This matches the
  documented direct shape-to-bone attachment field. Rotated/scaled roots remain
  explicitly unsupported.
- Local W2a, W5b, W6a and W8a models now parse 58, 27, 61 and 18 static shapes.
  Combined with W1/W3/W4/W7/W9a/W9b, ten of the twelve supplied world archives
  pass the tested static subset; W5a/W8b still contain non-root shape bindings.
- Full suite: **233 tests passed in 193.021 seconds**; compileall and
  `git diff --check` passed. No in-game geometry or camera result is inferred.

## 2026-10-21 — Transform rigid meshes by their BFRES bone

- Static shape extraction now applies the supported rest-pose rotation and
  translation for each shape's direct `BoneIndex` attachment, including normal
  rotation. It reuses the checked hierarchy transform reader and rejects bones
  whose scale branch is unsupported instead of drawing them at local origin.
- The W8b world model now parses all 42 static shapes. A local integration test
  verifies the non-root `ring4` shape receives its stored `(540, 49, -480)` rest
  translation; synthetic checks cover quaternion rotation and scaled-root
  rejection. Eleven of twelve supplied world archives now parse in this subset;
  W5a's scaled bone-attached meshes remain unsupported.
- Full suite: **235 tests passed in 204.003 seconds**; compileall and
  `git diff --check` passed. No animation or game render behavior is inferred.

## 2026-10-21 — Support positive-scale rigid BFRES bones

- Added bounded affine rest-pose transforms for rigid static shapes. Positive
  scales now compose with local rotations and parent transforms; normals use
  inverse-transpose handling. Segment-scale-compensated and camera-facing
  billboard branches remain explicitly unsupported.
- The local W5a model now parses all 76 rigid shapes. The test also verifies all
  other supported world models, and synthetic fixtures cover scaled roots,
  scaled child bones, transformed normals and rejected transform branches.
- Static parsing now covers all twelve supplied course-select world models
  (W1/W2a/W3/W4/W5a/W5b/W6a/W7/W8a/W8b/W9a/W9b). This is offline geometry
  validation only; material/animation fidelity and Cemu appearance are untested.
- Full suite: **241 tests passed in 208.765 seconds**; `compileall` and
  `git diff --check` passed. No in-game terrain or route behavior is inferred.

## 2026-10-21 — Verify base-color preview coverage across worlds

- Added a local-asset integration regression covering supported BC1/BC3
  texture decoding on all twelve static world models, including texture-map
  counts, attached-shape counts, encoded RGBA dimensions and accepted formats.
- W5a attaches 27 maps to 73 of 76 shapes; the full sweep also confirms
  supported albedos in W2a/W3/W4/W5b/W6a/W7/W8a/W8b/W9a/W9b. Unsupported or
  ambiguous material references retain the fallback color instead of choosing
  an unverified texture.
- Targeted integration test: **1 passed in 40.178 seconds**. Full suite: **242
  tests passed in 247.342 seconds**; `compileall` and `git diff --check` passed.
  This is offline preview validation only.

## 2026-10-21 — Cross-check paired macro paths on changed destinations

- Graph validation now checks the paired BFRES macro-path references for a
  changed, single local destination when the baseline and current local
  inventories resolve. A stale W101→W102 path no longer passes after changing
  its destination to W103; a matching direct or multi-hop macro path passes.
- Ambiguous multi-destination legacy rows and cross-world/incomplete inventories
  remain outside this added check. Runtime route behavior is still unverified.
- Focused graph suite: **16 tests passed**; the stock W1 `validate-graph`
  command reports no errors for W101→W103 reachability. Full suite: **244 tests
  passed in 248.483 seconds**; `compileall` and `git diff --check` passed.
  No runtime route result is inferred.

## 2026-10-21 — Explain base-texture preview fallbacks

- Affected UV shapes now carry the bounded reason their base-color texture
  could not be previewed, and the 3D inspector shows it as compatibility text.
  This makes unsupported formats and malformed references actionable while
  preserving approximate material colors and using safe text-only rendering.
- Full suite: **245 tests passed in 248.333 seconds**; `compileall` passed and
  `git diff --check` reported no whitespace errors. This is offline viewer
  validation only.

## 2026-10-21 — Surface fallback meshes in the viewer list

- Shapes using approximate color now show an accessible warning badge directly
  in the mesh list. The list filter also searches the bounded fallback reason,
  and selecting the shape reveals the same explanation in the inspector.
- The twelve-world local asset sweep now verifies that each UV shape has either
  a decoded base texture or its bounded fallback reason; non-UV shapes are not
  mislabeled. Focused integration test: **1 passed in 40.091 seconds**.
- Full suite: **245 tests passed in 245.891 seconds**; `compileall` passed and
  `git diff --check` reported no whitespace errors. This is offline viewer
  validation only.

## 2026-10-21 — Pin the main-grass shader resource contract

- Added a local W1 integration regression for `polySurface1489__mtGrass`: its
  SHARCFB program and 86/288 material-option candidate, unresolved
  `NUM_SKINNING_VTX`, sampler declarations, exact UV-input-to-BFRES-attribute
  bindings, `Grass_alb` BC1 resource, and stored identity `texmtx1` value.
- The test caught and now records that `aTexCoordBake0` is shader input `_u3`
  mapped to BFRES `_u1`; material inputs `_u1` and `_u2` instead both target
  `_u0` for the normal/spec-mask interfaces. This is static binding evidence,
  not proof that each input is consumed by the active game variation.
- The viewer's shader inspector now lists unresolved shape-specific macro
  names (for example, `NUM_SKINNING_VTX`) beside the candidate, and a DOM
  regression checks the displayed label. This exposes why the candidate is
  incomplete without treating the first-declared macro value as confirmed.
- Fresh pre-change baseline: **245 tests passed in 244.382 seconds**. After
  these changes, the full suite passed: **246 tests in 246.883 seconds**;
  `compileall` and `git diff --check` passed. No Cemu or game-render behavior
  was verified.
- Next: resolve the shape-specific skinning variation and GX2 coordinate
  operations from supported evidence before adding grass shading. In-game
  movement, level starts, and terrain appearance remain unverified.

## 2026-10-21 — Trace the BFRES shape skin-count input

- Cross-checked Tsuru AGL's second variation lookup: it indexes a caller-
  supplied skin-value array using `ResShape::GetVtxSkinCount()`. The Wii U
  BFRES shape reader stores this field in the local `FSHP` record. The preview
  parser now carries the stored value (zero for accepted rigid meshes) into
  the shader inspector.
- The inspector now shows `BFRES vertex skin count: 0` while stating that its
  mapping to `NUM_SKINNING_VTX` is unresolved. A local W1 regression verifies
  the main grass value and the UI test verifies both the value and limitation.
- Full suite: **246 tests passed in 245.627 seconds**; `compileall` and
  `git diff --check` passed. This narrows the reverse-engineering question but
  does not identify the AGL caller's skin-value array or confirm a runtime
  shader permutation.

## 2026-10-21 — Add bounded static GLB terrain import

- Added a Binary glTF 2.0 reader for embedded, static triangle meshes and
  connected it to the editor preview, transform controls and experimental
  single-grass-shape replacement path. OBJ remains supported.
- Enforced file/geometry limits and checked GLB chunks, scenes, accessors,
  alignment, strides, indices and finite values. External buffers, compressed
  buffer views, transforms, instancing, skinning, morphs, mixed optional
  attributes and unsupported primitive modes fail with clear errors.
- GLB materials, textures and animation are not evaluated; the game material
  stays from the replaced BFRES shape. No Cemu or in-game appearance test was
  performed.
- Focused GLB tests passed: **14 tests**; the full suite passed: **260 tests in
  248.027 seconds**. `compileall` and `git diff --check` passed.

## 2026-10-21 — Tighten path-reference and main-grass regressions

- Changed local single-destination edits now compare the paired BFRES path IDs
  with the destination when those IDs form a simple linear chain. The checker
  catches stale and out-of-order chains, while skipping the branched W104/W105
  stock lists rather than treating them as a linear route. A W1 regression and
  synthetic cases cover matching, stale, reversed and branched records.
- Strengthened the local main-grass shader-interface test to pin its full
  stored material options, sampler-symbol map, vertex-input bindings/formats/
  offsets, candidate macros, `Grass_alb` metadata and identity `texmtx1`. These
  remain resource/interface facts; runtime shader selection and evaluation are
  not established.
- Rechecked the isolated Cemu baseline. The log confirms the supplied v64 RPX,
  CrashFix only, separate MLC and no save at boot; the current live screen is
  still `Press 2!`. The configured profile is Wii U GamePad + Keyboard (Enter
  for Plus, Z for A, WASD for the left stick), but logs do not record the active
  profile or input events. No world map, traversal, level start or terrain
  comparison was observed. The user's earlier “Mario doesn't move” report
  remains a failed gameplay check pending a controlled test.
- Full regression suite: **261 tests passed in 252.313 seconds**. Focused graph,
  shader, and local resource checks also passed. Runtime game behavior remains
  unverified.

## 2026-10-21 — Recheck the clean Cemu title input

- Freshly selected the exact `build/cemu-clean-baseline/Cemu.exe` process and
  confirmed it was showing `Press 2!`. Enter (configured as Plus) started the
  opening/demo sequence and returned to the title; it did not reach the map.
- A later screenshot of the same process showed the opening dinner scene. One
  Z press (configured as A) left the latest screenshot at `Press 2!` with no
  visible change. The active controller profile and the title prompt's
  intended input remain unresolved. No route movement, level launch, or
  patched-game behavior was tested. This supersedes the earlier note that
  Enter did not advance the title at all.
- Updated `docs/INTEGRATION.md` and `ROADMAP.md` to preserve this distinction.

## 2026-10-21 — Improve sampler and terrain-preview feedback

- The WebGL viewer now reads each supported base-color `_a0` sampler's GX2 S/T
  wrap values. Wrap and Mirror use their corresponding WebGL modes; GX2 Clamp
  is labeled as a `CLAMP_TO_EDGE` approximation; unsupported MirrorOnce and
  border modes display a warning and use Repeat. A scan of all twelve supplied
  worlds found 76 non-Repeat albedo materials among 415 supported entries; all
  their textures are power-of-two, and the world-model regression now checks
  that condition. This remains a base-texture preview feature and does not
  resolve shader UV selection or SRT.
- Fixed relative terrain references in preview projects so opening, saving in
  place, and Save As to another directory keep pointing at the same OBJ.
- Terrain export now records maximum nearest-source XZ distance for baked-light
  UV projection in the export manifest and warns above the default 128-unit
  review threshold. The editor surfaces that warning; it is not visual QA.
- Verification: **270 tests passed in 257.844 seconds**; the expanded twelve-
  world sampler/NPOT regression passed separately in 39.777 seconds. `compileall`
  and `git diff --check` passed. Headless Chrome/SwiftShader loaded the W1 page
  with 42 shapes and 20 albedos without an error overlay (ignored capture:
  `local/evidence/preview-w1-wrap-sampler.png`). The clean Cemu check remained
  at its title prompt, so route movement, level launches, progression, and
  terrain appearance remain unverified.

## 2026-10-21 — Safer native route-table drafts

- Replaced free-text route-ID entry with BFRES-segment and road-type selectors.
  The editor now lists unused route IDs found in the BFRES whose local endpoint
  bones resolve, offers only road types already present in the route table,
  and rejects duplicate segments. The local W1 archive contains 13 such IDs
  absent from its 134-row route table.
- The dialog says that it adds only a route CSV row. It does not create route
  geometry or edit point destinations/path chains; successful static export
  therefore does not establish that the game can traverse the segment.
- Added synthetic graph checks and a Tk smoke test for selection, row creation,
  and undo. The focused graph-validation and editor smoke suites pass (22 and
  21 tests). The final full suite passed: **275 tests in 249.642 seconds**;
  `compileall` and `git diff --check` also passed.
- Cross-checked all 12 supplied `CS_W*.szs` world archives in memory: every
  baseline passed static validation; ten had unused BFRES route IDs and
  accepted one added table row, while W8a and W9a had no unused IDs. This does
  not verify route movement or point-chain behavior in game.
