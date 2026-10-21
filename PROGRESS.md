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
