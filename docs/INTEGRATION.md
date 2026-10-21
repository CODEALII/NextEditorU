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
- Read-only input-profile check on 2026-10-21 found two different setups: the
  isolated `build/cemu-island-baseline` profile is GamePad + Keyboard and maps
  left/right to the arrow keys; the user's separate Cemu profile is GamePad +
  DirectInput / Wireless Controller. Keyboard arrow presses would not exercise
  that DirectInput profile. The running isolated process was the unpatched
  baseline at the time of inspection. It is unknown which window/profile was
  active during the failed manual test, so this is a plausible input mismatch,
  not a confirmed root cause.
- Offline validation of the exact mainlight pack archive found no broken graph
  references. W102 points to W103 through `RW102W1T0` and `RW1T0W103`, and both
  path bones are present. This proves the declared resource references exist,
  not that Cemu can move along them. The mainlight profile has no captured boot
  log, so activation and runtime behavior for that exact pack remain unverified.

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
  also generated for compatibility. Movement-axis and arrow-key mappings match;
  an older integration profile has different face-button mappings for IDs 3/4,
  while the later mainlight XML and INI match. The input dialog showed GamePad +
  Keyboard with A=Z. Automated tap recognition was unreliable; menu click
  navigation worked.

## Still required before declaring the prototype playable

1. In one Cemu window/profile, verify baseline movement at W101 by holding `D`
   briefly (left-stick right). Then load the patched archive in the same profile
   and test W102→W103 with the same key. Record the active window/profile and
   the displayed start and destination. Baseline motion with patched immobility
   isolates a route/patch issue; failure in both leaves focus/input unresolved.
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
