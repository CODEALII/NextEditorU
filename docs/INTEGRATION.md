# Runtime evidence and test protocol

## Latest controlled retest — 2026-10-21

- Used three isolated Cemu 1.26.2f profiles with separate MLC folders and the
  same pre-test personal/common save snapshot. Preflight checks confirm all
  three save files remain byte-identical after the runs.
- Clean and Chain profiles both reached the World 1 map at the Crushing-Cogs
  Tower. In the controlled comparison, holding `D` for about two seconds moved
  Mario to the visible neighboring node in both profiles; its name was not
  captured. In a later isolated Chain run, a refreshed screenshot showed Mario
  at **Acorn Plains-2 — Tilted Tunnel**, but Computer Use reported external
  user input at the same time, so that follow-up movement cannot be attributed
  to a particular test key. The internal point ID is not confirmed.
- The Chain profile activated CrashFix and World Studio Chain. Its packaged
  `CS_W1.szs` SHA-256 is
  `19dfe2d9d6f5427236e5336c2418d486962daa62982ed74d76533527c3a9995e`, matching
  the generated test archive. Screenshots are retained locally (ignored under
  `build/`): `cemu-chain-map-stable.png`, `cemu-chain-after-d.png`, and
  `cemu-chain-enter-node.png`; the clean movement comparison is
  `cemu-clean-after-d-valid.png`.
- Pressing `Z` at Acorn Plains-2 left the Chain run on the world map after a
  2.5-second wait. A level launch was not observed. Archive inspection shows
  the test chain changes only `pointW1.csv`; stock data already connects W101
  to W102. Therefore the controlled first-node movement does not exercise the
  modified W102-to-W103 link. That link uses `RW102W1T0` and `RW1T0W103` and
  still needs a controlled traversal test. The Direct profile activated the expected
  archive (`8a473f413788cb5b3fab07f5f6ae174a6948159b39cc6019df97ef7ae24c3d35`);
  it remained in the title/demo flow and did not reach the map, so it provides
  no movement result.
- In a later live check at Acorn Plains-2, two individual `W` presses changed
  Mario's facing but did not move him off the node. The Computer Use key API
  exposes only a press, not a timed hold, so these taps do not test the required
  travel duration and do not show that the route is broken.
- Before the latest Chain retest, Clean, Chain and Direct passed
  `tools/cemu_preflight.py` with current-run title/module and pack checks, and
  `--compare-save-to` confirmed byte-identical save snapshots. The current Chain
  run has since moved Mario on the map and was still open when Computer Use
  detected user input; do not assume its save still matches until Cemu is closed
  and the comparison is rerun. The clean run excludes World Studio Chain; each
  modified profile enables it and its packaged archive matches the test input
  exactly. No fresh-save progression or terrain-appearance result is established.

These observations supersede older statements below that no sustained input
or traversal had been performed. The earlier notes remain as historical
evidence for their respective, inconclusive runs.

## Confirmed in this run

- Installed emulator binary identifies itself as **Cemu 1.26.2f**.
- Isolated runtime: `build/cemu-integration`, own `mlc01`, original game RPX
  opened read-only. No installed update in the isolated MLC; log confirms v64
  module checksum `0x6caea914`.
- A later audit found that the folders previously named `cemu-integration` and
  `cemu-island-baseline` both have `WorldStudioChain` and CrashFix enabled in
  `settings.xml`; their logs confirm both packs. Their successful World 1 map
  loads are patched-build observations, not a clean stock baseline. Earlier
  notes calling those runs baseline are withdrawn.
- A new `build/cemu-clean-baseline` folder uses a separate MLC and CrashFix
  only. Its current log confirms `red-pro2.rpx`, v64, module checksum
  `0x6caea914`, no World Studio Chain pack, and no save present at boot. The
  live Cemu window reached the title screen, which showed `Press 2!`; the
  SpotPass offer was declined. A fresh isolated save directory now exists. No
  map or traversal test has been reached.

  The Cemu input screen reports Wii U GamePad + Keyboard. Its configured keys
  are Z=A, X=B, C=X, V=Y, Enter=Plus, arrows=D-pad and WASD=left stick. The log
  does not record which controller profile was active or any input events. A
  fresh process-specific check confirmed `build/cemu-clean-baseline/Cemu.exe`
  itself was at the `Press 2!` prompt. Enter (configured as Plus) started the
  opening/demo sequence, which later returned to the title; it did not reach
  the map. A later screenshot of that same exact process showed the opening
  dinner scene again. A single Z press (configured as A) left the latest
  screenshot at `Press 2!` with no visible change. The prompt has not been
  matched to this GamePad profile. If it expects a Wii Remote's `2`
  button, this profile has no such binding, but that interpretation is not
  confirmed. Do not treat the title prompt as a movement test. Recreate the
  isolated baseline only if its files are missing:

  ```powershell
  python tools/prepare_cemu.py --cemu build/cemu-island-baseline --baseline --out build/cemu-clean-baseline
  ```

  Choose a new output name if the folder already exists.
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
- A corrected export now targets the main grass shape and projects imported
  vertices onto the closest non-degenerate source triangle in XZ, interpolating
  the original baked-light UVs barycentrically. Ambiguous overlapping projections
  and degenerate topology fall back to the nearest source vertex. Its isolated test pack
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
- Read-only inspection found two controller configurations: the generated
  isolated profile is GamePad + Keyboard, while the separate user profile is
  GamePad + DirectInput / Wireless Controller. The isolated XML, text profile
  and current input UI agree on WASD for the left stick and arrows for D-pad.
  The log does not prove which profile is active at the title screen.
- Offline validation of the exact mainlight pack archive found no broken graph
  references. W102 points to W103 through `RW102W1T0` and `RW1T0W103`, and both
  path bones are present. This proves the declared resource references exist,
  not that Cemu can move along them. The mainlight profile has no captured boot
  log, so activation and runtime behavior for that exact pack remain unverified.
- A later live UI inspection of `build/cemu-island-baseline` showed the game
  profile using `Keyboard [Keyboard]`, with W/A/S/D assigned to the **left**
  stick and the right stick empty; arrow keys map to the D-pad. The UI labels
  this mapping as game-profile-controlled, so no settings were changed. This
  corrects the earlier misread that put D on the right stick.
- The live window showed Mario at Acorn Plains-1 (W101). Two short `D` key
  presses changed his facing but did not move him to the next map node. Computer
  Use sends taps rather than a sustained key hold, so this cannot distinguish a
  route failure from a too-short input and does not verify the reported
  W102-to-W103 traversal.
- The active patched test archive hash is
  `19dfe2d9d6f5427236e5336c2418d486962daa62982ed74d76533527c3a9995e`,
  matching `build/chain-quoted`; it is not `build/direct-route-v2`. The exact
  direct-route variant therefore remains untested. A subsequent live UI
  observation showed the clean CrashFix-only profile at the World 1 map, with
  Mario at W101; this updates the earlier title-screen-only observation. No
  sustained movement or arrival at W102 was observed. The latest Computer Use
  inventory in this session returned no native app windows, so the requested
  title click and held WASD test could not be issued or observed in this turn.

Earlier attempts displayed black after initial dialogs. They were inconclusive:
input setup, UI navigation and CSV quoting changed before the successful patched
world-map observation. Do not attribute a root cause without a controlled replay.
No crash stack or failing game function was identified.

## Original user Cemu process preflight

A read-only check of the only currently running Cemu process found the user
installation at `C:\Users\Ali\Documents\Cemu_2.6`. Its current log loads
NSMBU v64 but activates only graphics, LOD and CrashFix packs; it does not
activate World Studio Chain. Its `controller0.txt` selects DirectInput and a
Wireless Controller, not the keyboard GamePad profile. Therefore that live
process is not a valid WASD test of the custom route. The isolated direct-route
profile was subsequently launched as described above. The three isolated
profiles are `build/cemu-clean-route-retest-20261021`,
`build/cemu-chain-route-retest-20261021` and
`build/cemu-direct-route-retest-20261021`. All three have current run logs,
configured keyboard left-stick mappings and matching save snapshots. This
reused save is only for movement comparison, not a fresh-save progression test.

## Legacy emulator details actually encountered

- `gp_download=false` opens the legacy first-start wizard. Set true to mark that
  step completed; this setting does not itself download packs.
- `permanent_storage=false` avoids shared `%LOCALAPPDATA%/Cemu` MLC preferences.
- Use native backslash graphic-pack filenames and make the generated pack
  default-enabled in the isolated test. Verify activation in the log.
- Controller XML is visibly recognized by this installed binary. Legacy INI is
  also generated for compatibility. The generated XML and INI contain matching
  key mappings, but their effective stick assignment in Cemu 1.26 still needs
  confirmation. An older integration profile has different face-button
  mappings for IDs 3/4, while the later mainlight XML and INI match. Automated
  tap recognition was unreliable; menu click navigation worked.

## Still required before declaring the prototype playable

1. Re-run movement from the same recorded point and identify the exact point ID
   at the right-hand destination. Compare the clean, Chain and Direct archives
   from identical save snapshots and equal hold durations; current evidence
   proves movement in Clean and Chain only and does not isolate the cause.
2. Identify the destination node, activate it, and verify that it launches the
   intended level. The current Chain `Z` attempt remained on the map.
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
