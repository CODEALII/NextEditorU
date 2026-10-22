# Runtime evidence and test protocol

## Profile-gated project export — 2026-10-22

- `python -m worldstudio export <project> --out <archive> --profile <json>`
  now runs the selected versioned entry/required-location profile before
  writing. The gate is explicit and optional; it validates encoded graph
  reachability, not event scripts or in-game unlock rules.
- The local W1 test accepts the baseline project and rejects one with W101's
  outgoing destination removed (W102 and W103 become unreachable). It confirms
  no rejected archive is written and compares the source SZS byte-for-byte.
  Successful export manifests still retain `game_tested:false`.
- The native editor's **Graph check** toolbar menu selects the same optional
  JSON profile for Validate and SZS export and clears it when switching source
  archives. This offline gate does not demonstrate route traversal or
  progression in Cemu.
- A successful profile-gated export records the normalized profile, its
  canonical SHA-256 and the static check result in the sidecar manifest.
  `verify-export --profile` recalculates and compares this provenance; the
  manifest continues to mark `game_tested:false`.

## Ambiguous albedo references in local world models — 2026-10-22

- For materials with multiple `*_alb` references, the preview now uses `_a0`
  pairing only if exactly one candidate occupies that slot. A unique suffix
  match is unchanged; if the pairing is still ambiguous or its format/layout is
  unsupported, the shape keeps its labeled fallback color.
- A read-only re-scan improved texture attachment from 51 to 53 shapes in W4,
  73 to 74 in W5a, and 27 to 33 in W8b. The W8b regression confirms
  `mtYamaPink` resolves to `Yama_Pink_alb`; the twelve-world test records
  texture and shape coverage. This is local reference metadata, not proof of
  shader meaning or game rendering.

## Terrain viewport matches topology-preserving export — 2026-10-22

- With imported OBJ/GLB terrain, the embedded viewport now applies the same
  topology-preserving BFRES projection as export, then displays the re-extracted
  positions and normals while retaining the source material and UV channels.
- The local GLB archive roundtrip regression compares viewport geometry against
  the exported BFRES and confirms exact equality for positions, normals,
  indices and UVs. This reduces preview/export mismatch; it does not verify
  in-game terrain appearance or collision.

## Static GLB terrain archive roundtrip — 2026-10-22

- Added a local-W1 integration test for importing an embedded GLB mesh into a
  project, saving/reopening the project, exporting an SZS and re-extracting its
  BFRES grass shape. The export displaces terrain vertices while keeping source
  vertex count, triangle indices and UVs intact; the original SZS remains
  byte-identical.
- Regression: `tests.test_gltf.GlbReaderTests.test_glb_project_export_roundtrip_preserves_native_grass_topology`.
  This proves the offline data path only. The resulting terrain appearance and
  collision still require a controlled Cemu run.

## Rejected embedded 3D drag refresh — 2026-10-22

- WebGL previews supported point movement during a drag. When native world/local
  transform validation rejects that move, the editor now schedules an
  incremental overlay refresh from the unchanged project state, avoiding a
  stale visual position.
- Regression: a non-invertible child transform is rejected and the refresh is
  queued. The combined editor/graph/WebGL safety suites pass (**89 tests**).
  This is an automated editor-state check, not an interactive mouse or Cemu
  gameplay verification.

## Route road-type edit validation — 2026-10-22

- The native route inspector now uses a read-only selector populated from the
  source archive's existing road-type values. The add-segment dialog uses the
  same source whitelist. This prevents free-text typos from reaching the CSV.
- Export validation rejects empty or unknown values on changed/new route rows,
  while leaving unchanged legacy values intact. The local W1 table contains
  five observed values; this does not establish the engine meaning of any type.
- GUI, project, and graph regressions pass (**75 tests**); the full repository
  suite passes (**336 tests**). A separate test changed a road type in the real
  local W1 project, confirmed export created no output, and compared the source
  SZS byte-for-byte before/after. This is static data validation only; route
  movement in Cemu remains unverified.

## Embedded editor viewport smoke check — 2026-10-21

- Opened the local World 1 `CS_W1.szs` in a fresh Tk editor window on Windows
  with tkwry 0.1.9 and WebView2. The local WebGL page reached ready state and
  rendered 42 static BFRES shapes (70,193 vertices; 106,736 triangles), with
  path/node overlays inside the application. The main editing area keeps the
  3D viewport and native 2D graph visible side-by-side in an adjustable split,
  with the nodes/routes list and property controls alongside them. Preview
  lighting, camera, filters, and shape inspector are available in a collapsible
  Controls drawer so they do not cover the model at the initial embedded width.
- A screenshot review caught that passing the WebView host directly to the
  viewport pane let its geometry manager displace the parent. The WebView now
  lives in a dedicated child frame. A later live W1 screenshot confirmed both
  the 3D model and graph remain visible with the editor sidebar. Selecting W102
  in the list focused it in the viewport and graph; clicking W104 in 3D selected
  its row and properties. That scene contained 42 shapes, 70,193 vertices and
  106,736 triangles.
- GUI regression tests cover split-pane persistence, WebView host containment,
  viewport-to-editor selection, and incremental point/route overlay refresh
  without rebuilding BFRES geometry. Items without a world-map overlay cannot
  be selected from the 3D canvas; BFRES shape clicks remain in the renderer's
  inspector. Full game rendering, animation and in-game behavior remain outside
  this editor smoke check.

- On 2026-10-22, relaunched the native World 1 editor and visually confirmed
  the full island model and graph remain visible at startup, with the viewport
  now receiving 64% of the editing split and only Fit view / Preview controls
  overlaid. The Computer Use input bridge returned `foreground window did not
  report a process id` for a drawer click, so opening the drawer was not visually
  confirmed in this run. Its embedded HTML/CSS and generated JavaScript are
  covered by tests; this desktop screenshot does not validate 3D dragging.

## Embedded 3D point editing — 2026-10-22

- In the native editor, left-dragging a visible world point now moves its 3D
  overlay in the camera plane and commits the final world position through the
  existing hierarchy-aware world-to-local converter. The selection bridge
  updates the inspector; the edit enters shared Undo history, and the existing
  overlay refresh sends the committed position back without rebuilding BFRES
  geometry. Preview-only point IDs do not enable this native drag path.
- Safety checks reject malformed/out-of-range coordinates and child transforms
  whose inverse is unavailable. The synthetic regression verifies a root point
  move, selection, dirty state and Undo; another confirms an unsupported child
  transform stays unchanged. Renderer tests cover drag/RPC wiring. These tests
  do not replace a live visual drag check in the editor or a Cemu gameplay test.

## Embedded 3D drag input validation — 2026-10-22

- The renderer now waits until a left drag exceeds three screen pixels before
  moving a point. It applies the full accumulated pointer delta on that first
  move, so sub-threshold cursor jitter cannot leave the WebGL overlay slightly
  out of sync with the native editor.
- A Node regression executes the production camera-plane conversion for an
  identity and a rotated view; editor tests separately verify local-coordinate
  conversion, Undo and safe rejection. Full suite: **333 tests passed**.
- The Computer Use input bridge still failed before a real 3D mouse drag could
  be tested. Renderer math and synthetic editor wiring are verified; an actual
  visible drag and Cemu runtime effects remain unverified.

## Prepared topology-preserving terrain retest — 2026-10-21

- Exported a new local-only `CS_W1.szs` from the checked-in island OBJ using the
  topology-preserving projection and a 128-unit edge blend. Archive SHA-256:
  `92a9c5db7cad1f16726f3e5e7df45cf4cdbe03d47bdb8077374ddea066a6af52`.
- The export displaced 2,451 vertices of the existing 22,236-vertex main grass
  mesh; 417 are blended across the patch edge. All 32,374 triangles, material,
  diffuse UVs and baked-light UVs remain unchanged. The manifest reports
  `game_verified:false`.
- Prepared isolated profile `build/cemu-terrain-projection-20261021-v2`; its
  preflight is ready, its packaged archive hash matches the generated patch, and
  WASD plus Z=A mappings are configured. It has not been booted yet, so no Cemu
  appearance or collision result is established.
- A later preflight found that this profile's saved controller map had drifted
  to the wrong WASD IDs and its isolated MLC had no NSMBU saves. The old
  controller files are preserved under
  `local/evidence/cemu-input-test/terrain-profile-repair-20261021`; the profile
  now uses the same runtime-confirmed keyboard mapping and Clean save snapshot.
  Recheck passes with identical personal/common save hashes and the expected
  terrain archive hash
  `92a9c5db7cad1f16726f3e5e7df45cf4cdbe03d47bdb8077374ddea066a6af52`. It
  remains unbooted; no visual or collision conclusion follows.
- Launch after a compatible NSMBU RPX is available with:
  `& .\build\cemu-terrain-projection-20261021-v2\launch.ps1 -GameRpx '<absolute path to red-pro2.rpx>'`.
  Then rerun `tools/cemu_preflight.py` with `--require-run` and compare the map
  against the stock-looking route-only Chain profile.

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
  archive (`8a473f413788cb5b3fab07f5f6ae174a6948159b39cc6019df97ef7ae24c3d35`)
  and, in a later run documented below, reached the World 1 map. Its movement
  and course entry are not verified.
- In a later live check at Acorn Plains-2, two individual `W` presses changed
  Mario's facing but did not move him off the node. The Computer Use key API
  exposes only a press, not a timed hold, so these taps do not test the required
  travel duration and do not show that the route is broken.
- Follow-up Direct-profile run (PID 8868, separate MLC): the game passed the
  title/save/controller flow and loaded the World 1 map at the Crushing-Cogs
  Tower. Its active-pack log and archive preflight match the expected
  `WorldStudioChain` build exactly (SHA-256
  `8a473f413788cb5b3fab07f5f6ae174a6948159b39cc6019df97ef7ae24c3d35`). A
  single `D` tap, GamePad-A (`Z`) tap, and mouse click on Mario/the tower
  entrance left the map open and Mario at the tower. This is a verified
  map-load result, not a traversal or level-entry result. The Computer Use API
  only sends key presses, so this run could not reproduce the two-second held
  input from the earlier Clean/Chain comparison.
- After closing Direct normally, `--compare-save-to` confirmed its personal
  and common save files still match Clean byte-for-byte (8-byte personal file
  and 45,364-byte common file). This only establishes that loading and leaving
  this map did not change these saves; course-clear progression and persistence
  remain untested.
- The later Chain profile (archive SHA-256
  `19dfe2d9d6f5427236e5336c2418d486962daa62982ed74d76533527c3a9995e`) was
  also closed and compared to Clean. Its personal and common save hashes match
  Clean exactly, including the earlier uncontrolled map-state change. This does
  not test a course-clear progression transition.
- Before the latest Chain retest, Clean, Chain and Direct passed
  `tools/cemu_preflight.py` with current-run title/module and pack checks, and
  `--compare-save-to` confirmed byte-identical save snapshots. The later Direct
  and Chain processes have now both exited, and their save files still match
  Clean. The clean run excludes World Studio Chain; each
  modified profile enables it and its packaged archive matches the test input
  exactly. No fresh-save progression or terrain-appearance result is established.

### Current-session follow-up

- A new Cemu 1.26.2f process used `build/cemu-chain-route-retest-20261021` with
  the isolated save. Preflight confirmed the active World Studio Chain pack,
  archive SHA-256
  `19dfe2d9d6f5427236e5336c2418d486962daa62982ed74d76533527c3a9995e`, WASD
  on the left stick, Z=A and byte-identical personal/common saves versus Clean.
- At the Crushing-Cogs Tower, one D tap visibly moved Mario to the next
  right/down road node and the camera followed. A second D tap at that junction
  did not reach the next visible course ring. The destination point ID is not
  confirmed, so this proves movement on the patched map but not traversal of the
  modified W102-to-W103 segment. Ignored local screenshots:
  `cemu-chain-tower-before-d.png` and `cemu-chain-after-first-d.png`.
- A Z tap at the road junction left the map open. Since Mario was not verified
  on a course node, this does not establish a failed level launch. The separate
  Mainlight profile had no A binding, so its earlier Z attempt was invalid for
  course-start testing.
- The Mainlight build loaded with the exact archive hash
  `80c593995585f59757c3a728b1dbd558efd79158757dd9e1ba87729c281e4bce` and
  visibly showed large dark-green overlaps/clipped terrain. It is not a visual
  pass. The screenshot `cemu-mainlight-terrain-observed.png` is in ignored local
  evidence; the route-only Chain view retained stock-looking terrain.
- An archived process-bound Chain run provides a sustained-input observation:
  PID 29036 used the exact patched pack hash
  `19dfe2d9d6f5427236e5336c2418d486962daa62982ed74d76533527c3a9995e` and held
  `D` for 1,500 ms. Its map-check/before screenshots show Mario at a road
  junction; the after screenshot shows him on the visible black course node to
  the right. The process result records focus, key-down/up, matching runtime
  pack hashes, and a normal exit (`chain-modified-d-1500-result.json`, SHA-256
  `29405c8a71212c43f705707aeff4a1338ca222494606926d9ff8b09e9ff227e7`). This
  confirms movement on that patched map, but the screenshots do not identify
  either internal point ID or prove the starting point was W102. It therefore
  does not verify the specific W102-to-W103 edge or provide a matched Clean
  comparison from the same point. Level launch, fresh-save unlocks and
  save/reload progression remain unverified.

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
- Earlier manual traversal report: **Mario does not move**. At that point the
  active input profile and map state were uncertain. This observation is
  superseded by the controlled Chain run and the user's confirmation that WASD
  movement works, recorded in the current-session follow-up below; it is not a
  current movement failure diagnosis.
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
  W102-to-W103 traversal. The current-session follow-up above confirms movement
  from the tower to a neighboring road node, but not that modified segment.
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

## Controlled sustained-input baseline and Chain attempt — 2026-10-21

- A fresh isolated Clean run (`clean-gamepad-input-v3-direction-matrix-final2`)
  reached the World 1 map at Crushing-Cogs Tower. Cemu PID 24744 / HWND
  196740416 was focused and verified before each two-second key hold. The
  profile enabled only CrashFix; WorldStudioChain was absent. The configured
  GamePad profile SHA-256 was
  `7f27b62eb731fdd4c4eae10b2f8a77f19a0fba233c0a469067db2034900f4d9b`.
- Comparing each before/after screenshot: W left Mario at the tower. A moved
  him to the black course node to the right. S moved him onward to the lower
  path junction. D produced no further visible node movement in this sample.
  This verifies that the process-bound two-second hold runner can produce
  visible overworld movement on the clean baseline; it does not identify the
  destination point ID or test level entry.
- Personal and common save files were unchanged. Their SHA-256 values remained
  `5de5ecae3f91c13841ac5a16f0511b7af765ff63628cb95ce65bde721689c9df` (8
  bytes) and `23ed86557c2b223fde2742a548f3e6acbab78f2b1cdaed2db110b0dc5e47a178`
  (45,364 bytes). The run log SHA-256 was
  `32b60977ba1afbffe5d1811980e63e5808f0f296ea16a32c6853286fcef736d1`.
  Screenshots and per-key timestamps are retained in
  `local/evidence/cemu-input-test/clean-gamepad-input-v3-direction-matrix-final2-*`.
- The matching Chain profile passed its boot/pack checks: the active
  `WorldStudioChain` archive and profile copy both hash to
  `19dfe2d9d6f5427236e5336c2418d486962daa62982ed74d76533527c3a9995e`; the
  controller hash and initial save hashes match Clean. The intended W/A/S/D
  comparison did not run. A held Z/A input crossed the controller/story start
  screens and reached the world map before the explicit map-confirmation gate;
  the map screenshot showed Mario already moving, so that state cannot be
  treated as the same start point. The Cemu process then exited normally
  (exit code 0) before the map gate was confirmed. This is not evidence of a
  route failure or a Cemu crash. See
  `chain-gamepad-input-v3-controller-confirm-result.json` and
  `chain-gamepad-input-v3-direction-matrix-final2-result.json` alongside their
  screenshots.
- The exact static edit is on point row `W102` (engine row 2). Stock lists
  destinations `W1T0,W1K1` with macro path `RW102W1T0`; Chain lists destination
  `W103` with `RW102W1T0,RW1T0W103`. The local route-chain validator returns
  `True` for Chain's ordered W102-to-W103 macro path and `None` for stock's
  fan-out row. This identifies the route to measure, but does not show that
  Cemu traverses either segment at runtime. The normal route-graph reachability
  check passes on both archives, so it cannot substitute for the movement test.
- Next comparison must start the Chain profile at the confirmed tower and then
  run the identical W/A/S/D two-second sequence, capturing a clean map-check
  screenshot before input. Until that is completed, the Chain route behavior
  remains unverified.
- A subsequent retry (`chain-gamepad-input-v3-direction-matrix-retry`) did not
  reach game input: process-bound focus verification timed out after 120 seconds
  because Brave PID 19680 was foreground instead of the launched Cemu PID 24848.
  The runner closed its own Cemu process and wrote the failed result; no gameplay
  observation was made. The next attempt must activate the returned Cemu window
  promptly or use a permitted non-Computer-Use focus path before sending input.
- The test runner now polls the launched child process or exact attached Cemu
  PID at interactive checkpoints. If the game exits while the operator is
  confirming the map or destination, it reports that exit immediately and saves
  the partial run record instead of blocking indefinitely. Focused tests cover
  live Enter confirmation and both process-exit paths.

## Cemu test-profile repair and latest focus-blocked run — 2026-10-21

- Fresh preflight found that the isolated Clean and Chain profiles had drifted
  from the currently verified keyboard map: both stored WASD on IDs 17–20,
  while Cemu 1.26.2f uses IDs 18–21 for left-stick up/down/left/right. Their
  saves also differed: Clean common save SHA-256
  `23ed86557c2b223fde2742a548f3e6acbab78f2b1cdaed2db110b0dc5e47a178`, Chain
  common save SHA-256
  `7397c8582c406fe0a60b7e2d19fca5658093da4dbc30f92334ba035e6a0e931e`. The
  previous Chain controller files and complete user-save tree were preserved
  under `local/evidence/cemu-input-test/profile-repair-20261021` before repair.
- Regenerated both controller profiles from the repository's tested Cemu
  serializer and copied the Clean save snapshot to Chain. Both profiles now
  preflight with the same controller hash
  `7f27b62eb731fdd4c4eae10b2f8a77f19a0fba233c0a469067db2034900f4d9b`, WASD
  mapped to IDs 18–21, Z mapped to GamePad A, and identical personal/common
  save hashes. The Chain archive and enabled profile copy remain byte-identical
  at SHA-256
  `19dfe2d9d6f5427236e5336c2418d486962daa62982ed74d76533527c3a9995e`.
- The process-bound runner now selects the main game-title HWND if Cemu also
  exposes an auxiliary GamePad window, refuses ambiguous main windows, and
  records a first screenshot before requesting focus. Its focused runner,
  profile-preflight and profile-preparation suites pass (**33 tests**); the
  complete repository suite passes (**327 tests**). Early failures record the
  reason, final save hashes and Cemu log hash. Editor teardown also releases
  its embedded WebView and pending viewport/auto-fit callbacks.
- The latest attempt (`chain-route-focus-wait-20261021`) started from no active
  Cemu process and launched the expected isolated executable as PID 19124,
  HWND 51185206. Foreground stayed on Brave PID 19680 throughout the 300-second
  focus window. The runner sent no keys, closed its own Cemu with exit code 0,
  and saved a white pre-focus capture plus result JSON. The current Cemu log
  SHA-256 is
  `9c085d323653a63364614d8fe41919eb297869c4747cfb59672b9d82778e8703`. The
  white capture is not a view of the intended game state; no movement result
  can be inferred. `chain-route-focus-wait-20261021-result.json` and its BMP
  are in ignored `local/evidence/cemu-input-test/`.
- Remaining action for a controlled comparison: activate the exact isolated
  Cemu window during a live runner focus wait, then confirm the overworld
  starting point before the same two-second W/A/S/D sequence. The Clean baseline
  was previously verified with this same controller-profile hash, but the
  modified Chain route still has no new traversal evidence.

## Cemu node-by-node movement confirmation

The process-bound runner supports `--start-label "Crushing-Cogs Tower"` to
show the expected map starting point in its explicit screenshot confirmation.
For ordered movement tests, `--sequence w a s d --pause-after-each-step` captures
before/after images around each held direction and pauses between steps for an
operator to confirm the visible next node before continuing. The runner records
each confirmation and re-verifies the exact Cemu window focus before the next key.
This makes the test result easier to reproduce and interpret; it does not add
new in-game movement evidence by itself. The next Cemu retest was deferred by
the user, so no new emulator instance was started for this change.

## Current Clean/Chain preflight and ready movement comparison — 2026-10-22

- Rechecked both existing isolated profiles without launching Cemu. Clean has
  only CrashFix active; Chain activates `WorldStudioChain`, and its packaged
  `CS_W1.szs` matches the expected archive at SHA-256
  `19dfe2d9d6f5427236e5336c2418d486962daa62982ed74d76533527c3a9995e`.
  Both profiles use the verified keyboard GamePad mapping (WASD on IDs 18–21,
  Z as GamePad A), have a current NSMBU run in their logs, and contain identical
  personal/common save files. Both `cemu_preflight.py` checks returned ready
  with no issues. These are configuration and file-integrity checks only.
- To compare the same held movement sequence, run the process-bound runner once
  per profile from the repository root, using the same game RPX and options:

  ```powershell
  $rpx = '.\NSMBU Modding Project\code\red-pro2.rpx'
  python tools/cemu_input_test.py --profile build/cemu-clean-gamepad-input-v3-20261021 --rpx $rpx --case clean-w102-link --start-label 'Crushing-Cogs Tower' --sequence a d --hold-ms 2000 --pause-after-each-step --pack-name WorldStudioChain
  python tools/cemu_input_test.py --profile build/cemu-chain-profile-gated-20261022 --rpx $rpx --case chain-w102-link --start-label 'Crushing-Cogs Tower' --sequence a d --hold-ms 2000 --pause-after-each-step --pack-name WorldStudioChain --pack-file build/profile-gated-chain-patch/content/Common/course_select/CS_W1.szs --graph-profile profiles/w1-core-progression.json --compare-save-to build/cemu-clean-gamepad-input-v3-20261021
  ```

  Each run refuses another active Cemu process, waits for the exact game window
  to be foreground before every input, and pauses after the first direction so
  the operator can confirm the visible node. If `A` does not reach the same
  expected W102 node in both runs, stop and record that difference instead of
  interpreting the following `D` result as a W102-to-W103 traversal. The
  runner independently enforces the profile/manifest/archive/save preflight
  before launching Cemu and saves any prelaunch rejection as a result JSON.
  At each manual gate, press `N` or `Esc` to stop before another input is sent
  (`N` also works when stdin is not an interactive terminal). The result JSON
  records the aborted gate, screenshots, saves and log hashes; an isolated Cemu
  started by the runner is closed normally, while an attached instance is left
  running.
  The command sequence is a ready protocol, not a new gameplay result.

## Profile-provenance Cemu package — 2026-10-22

- Re-exported the saved Chain project through the current profile-gated
  exporter. The output SHA-256 is exactly
  `19dfe2d9d6f5427236e5336c2418d486962daa62982ed74d76533527c3a9995e`, the
  same archive already used in the prior Chain attempts. `verify-export` with
  `profiles/w1-core-progression.json` passes and records profile hash
  `08990ee33aed7627c479ebe79b18200a30a6ccb8e5aeef13839547f0ef55820b` for
  W101→W102/W103. The export still says `game_tested:false`.
- Created a new isolated profile at
  `build/cemu-chain-profile-gated-20261022` from that export, using a copied
  save tree that preflight confirms byte-identical to Clean. Its Cemu 1.26
  keyboard profile has WASD on left-stick IDs 18–21 and Z on GamePad A. The
  profile was subsequently launched for the matched movement test below.
- `tools/cemu_preflight.py --graph-profile <profile.json>` now checks the
  selected profile against the packaged `CS_W1.szs.manifest.json`, verifies
  the manifest's archive hash against the bytes Cemu will load, and requires a
  passing profile for World 1. This gate is opt-in for old profiles. For this
  new profile, preflight returned `ready:true`, with matching saves, pack and
  graph profile. That is test setup evidence, not gameplay evidence.

## Matched Clean/Chain movement run — 2026-10-22

- Both isolated profiles were booted with the same controller profile
  SHA-256 `7f27b62eb731fdd4c4eae10b2f8a77f19f0a233c0a469067db2034900f4d9b`,
  start label `Crushing-Cogs Tower`, and two-second held sequence `A`, then
  `D`. The Chain profile loaded the exact `WorldStudioChain` archive at SHA-256
  `19dfe2d9d6f5427236e5336c2418d486962daa62982ed74d76533527c3a9995e`; its
  graph manifest passed `profiles/w1-core-progression.json`. The common save
  hash matched Clean at
  `23ed86557c2b223fde2742a548f3e6acbab78f2b1cdaed2db110b0dc5e47a178`.
- Screenshots show that A moves Mario from the confirmed tower start to the
  same visible Acorn Plains course node in both profiles. On the next held D,
  Mario remains on that node in both profiles and changes facing. Since the
  game UI does not display the internal point ID, this verifies baseline
  movement and matching visible behavior, not traversal of W102→W103. It does
  not establish a route-data failure; the tested D direction does not move on
  the stock profile either. Level entry, progression, persistence, and terrain
  remain untested.
- Run records are
  `local/evidence/cemu-input-test/clean-w102-w103-20261022-result.json` and
  `local/evidence/cemu-input-test/chain-w102-w103-20261022-retry2-result.json`.
  The paired step screenshots use the same basename with `step-1-a-before`,
  `step-1-a-after`, `step-2-d-before`, and `step-2-d-after`. The Chain Cemu
  instance was left open after the attached test; a separate runner that had
  no interactive stdin was stopped without terminating the game.
