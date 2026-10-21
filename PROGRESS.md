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
- New export report: `build/island-mainlight/`; its manifest correctly says
  `game_tested:false`. No game file or original save was overwritten.

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

Next steps: compare the corrected main-grass island render against a controlled
baseline, complete the pending human traversal/launch test, then verify fresh
clear-triggered unlocks and save persistence. No claimed completion of the full
custom-overworld mission.
