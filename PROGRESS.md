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

Current integration work:
- Cemu 1.26.2f is installed (the folder says 2.6). An existing Cloudy SMBU 2 pack and
  shared update installation would interfere with tests. Preparing separate
  emulator settings, saves and mod pack under ignored `build/`.
- First visual review of editor found cluttered auxiliary fallback positions;
  correcting presentation before delivery.

Not yet proven / outstanding:
- Actual game traversal, level launch, clear-triggered unlock/save persistence,
  camera behavior and cutscene interactions for the topology experiment.
- A fully original in-game island: arbitrary mesh/material import/export is absent.
  The supplied original OBJ is editor preview only, not a game-compatible island.
- New node/route bones and safe engine/script index remapping. Draft add/delete
  is allowed in the editor but export blocks unresolved references/index changes.
- General events/camera binary editing, animation authoring, executable loader
  disassembly, verified patches for engine limitations.

Next steps: run controlled baseline/patched game tests; implement/reuse BFRES mesh
conversion with retained game materials; extend only after reproducible runtime
evidence. No claimed completion of the full custom-overworld mission.
