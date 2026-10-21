# Runtime evidence and test protocol

## Confirmed in this run

- Installed emulator binary identifies itself as **Cemu 1.26.2f**.
- Isolated runtime: `build/cemu-integration`, own `mlc01`, original game RPX
  opened read-only. No installed update in the isolated MLC; log confirms v64
  module checksum `0x6caea914`.
- Baseline uses only the copied installed Title Screen Crash Fix. Visually
  reached Story Mode and World 1 at Crushing-Cogs Tower with animated scenery.
- Patched test logs explicitly activate **World Studio Chain** plus CrashFix.
  Resource SHA256 `19dfe2d9d6f5427236e5336c2418d486962daa62982ed74d76533527c3a9995e`
  identifies `build/chain-quoted/content/Common/course_select/CS_W1.szs`.
  The patched world map also loads and visibly renders at the tower.
- Existing local common save was copied to the isolated MLC to access traversal
  without completing levels using unreliable automated key taps. Its original
  was not modified. Fresh isolated save was retained in `local/evidence/`.
- A separate isolated `build/cemu-island` instance also reached the World 1
  map with the island geometry graphic pack active. It did not crash while
  loading. In the observed view, broad dark green surfaces cover part of the
  western plains. The target was later found to cover only a narrow strip of
  the model, so that run is not a valid full-island visual test. Mesh rendering,
  materials and culling are **not verified**.
- A corrected export now targets the main grass shape and preserves the original
  baked-light UV channel by nearest-surface projection. Its isolated test pack
  is prepared at `build/cemu-island-mainlight`; this build has **not yet been
  visually compared** against the original map. The projected baked-light UV
  interpretation remains an implementation hypothesis pending that test.
- The original W1 input hash remains
  `d2547f5bfa9963d05916816301a0b53e8916ab62628210409be232228b117cf0`.
- Latest manual traversal report: **Mario does not move**. This confirms the
  current gameplay test is failing, but does not identify whether the cause is
  controller/input state, map state, or the patched route. No traversal pass is
  claimed; reproduce with the active input profile and record the exact start
  node and attempted direction before changing route data.

Earlier attempts displayed black after initial dialogs. They were inconclusive:
input setup, UI navigation and CSV quoting changed before the successful patched
world-map observation. Do not attribute a root cause without a controlled replay.
No crash stack or failing game function was identified.

## Legacy emulator details actually encountered

- `gp_download=false` opens the legacy first-start wizard. Set true to mark that
  step completed; this setting does not itself download packs.
- `permanent_storage=false` avoids shared `%LOCALAPPDATA%/Cemu` MLC preferences.
- Use native backslash graphic-pack filenames and make the generated pack
  default-enabled in the isolated test. Verify activation in the log.
- Controller XML is visibly recognized by this installed binary. Legacy INI is
  also generated for compatibility; both carry equivalent mappings. The input
  dialog showed GamePad + Keyboard with A=Z. Input recognition of automated taps
  was unreliable; menu touch/click navigation worked.

## Still required before declaring the prototype playable

1. Reproduce the reported no-movement result from a known node and record the
   active input profile; then determine whether the tower path blocks travel,
   stops at the tower, or reaches W103.
2. Confirm the displayed destination is Acorn Plains 3 and launch that level.
3. On a fresh save, clear 1-1 then 1-2. Confirm the intended new unlocks and
   restrictions without relying on already-cleared tower flags.
4. Save/reload and check current node, completion and unlocking persistence.
5. Compare the corrected main-grass island export with a controlled baseline;
   verify material, baked-light UVs, normals and culling. Other stock terrain
   remains by design.
6. Check camera transitions, multiplayer movement, opening/ambush events and
   death/return behavior. No generic executable patch is currently supplied.

Local logs are evidence of configuration/boot, not proof of traversal. The JSON
export manifests intentionally retain `game_tested:false`; human observations
belong in this document and PROGRESS.md with their exact scope.
