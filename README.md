# NSMBU World Studio

A tested resource-editing prototype for user-owned **New Super Mario Bros. U,
Wii U** dumps. It edits actual point/route CSV tables and selected BFRES data.
The full custom-overworld mission is still in progress; see [PROGRESS.md](PROGRESS.md).

## Start on this PC

Python 3.14 with tkinter is already available. No packages need installing.
Run from this directory:

```powershell
python -m worldstudio gui
```

Or double-click `Launch World Studio.cmd`. Default input is the provided
`NSMBU Modding Project/content/Common/course_select/CS_W1.szs`.

Select points/segments in the right-hand table to edit native fields. Known
level-bone local XYZ is editable. Viewport orbit/zoom and camera sliders affect
the editor view only. Auxiliary points without computed world transforms are
hidden by default; their optional fallback layout is explicitly labeled.

Save a project JSON outside the original game directory, then export to a new
SZS path. Existing exports and original game directories are protected. A
manifest lists changed members/hashes and never labels an export game-tested.

**Import OBJ** previews terrain. **Use OBJ mesh (experimental)** additionally
selects one capacity-bounded native replacement: `CS_W1_World/beltmodel14__mtGrass`.
It preserves the existing material, layout and submesh partitions, generates
normals/UVs and bounds, and makes unused triangles degenerate. Other landscape
shapes remain. It accepts only the verified rigid grass layout, not arbitrary
BFRES files/materials/animations. OBJ units are model-local game units; the
original `examples/island-game.obj` is suitable for this experiment.

## Reproduce the topology experiment

```powershell
python -m worldstudio inspect
python -m worldstudio demo --out build/my-chain
python -m worldstudio gui build/my-chain/three-level-chain.nws.json
```

This changes normal progression to `W101 -> W102 -> W103`. W102 references the
existing two-part path through the tower area; it does not delete the tower.
All 72 point rows, including script-sensitive W1S0 and W1Item indices, stay in
place. Other map points and game scripts remain present. Runtime traversal and
clear-triggered progression must be verified before treating this as playable.

To combine topology with the original test mesh:

```powershell
python -m worldstudio demo --island examples/island-game.obj --out build/my-island
```

Do not copy either output over your originals. They are **local test artifacts
containing your own game resources**, not redistributable mod packages. Share
the original code/OBJ and project changes; regenerate resources locally.

## Isolated Cemu test

```powershell
python tools/prepare_cemu.py --cemu "C:\Users\Ali\Documents\Cemu_2.6\Cemu.exe" --patch build/my-chain --out build/my-cemu-test
& ./build/my-cemu-test/launch.ps1 -GameRpx "$PWD/NSMBU Modding Project/code/red-pro2.rpx"
```

The helper refuses existing output folders. It copies the installed emulator,
system fonts and existing CrashFix into a separate directory with new settings,
cache and saves. It enables only CrashFix and the generated World Studio pack.
It does not launch Cemu automatically. Legacy settings isolation is intentional:
`gp_download=true` marks setup completed; `permanent_storage=false` avoids shared
MLC preferences. Check the log's active packs and save/update paths on every run.

Keyboard: Z=A, X=B, C=X, V=Y, Enter=Plus, arrows=D-pad, WASD=left stick.
System fonts and CrashFix are copied from the installed emulator, never bundled
in this repository. The provided dump's metadata identifies an update title
v64; the local RPX boots in the tested emulator but other dumps need validation.

## Validation and limits

```powershell
python -m unittest discover -s tests -v
python tools/inspect_resources.py "NSMBU Modding Project/content/Common/course_select/CS_W1.szs"
```

Tests cover malformed archives, Yaz0 overlaps/window boundaries, exact unchanged
CSV bytes, graph reference/index guards, modified-byte boundaries, local actual
BFRES parsing/mesh injection, export round-trips and original-file preservation.
Actual-dump tests skip when no user-owned dump is present. Automated tests are
not proof of in-game movement, camera, saving or progression.

Adding/deleting draft points does not create the corresponding model bones or
remap executable/script indices; native export blocks those unsupported changes.
Moving a node alone does not regenerate its walking paths. Camera binaries,
animation and general event authoring are not implemented. New point/segment
bones and executable patches require further verified reverse engineering.

## Sources and licensing

Primary-source links, pinned revisions, upstream licenses and address caveats
are recorded in `docs/RESEARCH.md`; actual local observations and emulator schema
evidence are in `docs/RESOURCE_FINDINGS.md`. Third-party clones stay ignored in
`external/` and retain their own licenses. They are not copied into this code.
No Nintendo assets/executables are committed. The original example OBJ assets
are dedicated to CC0, as stated in their headers.
