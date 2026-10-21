# Verified local overworld event-script workflow

`tools/cobra_bridge.py` invokes the independent [Cobra](https://github.com/RoadrunnerWMC/Cobra) checkout through a subprocess, with Cobra's required working directory. It neither copies/imports Cobra implementation into World Studio nor installs or deploys an event loader. Outputs must use a new directory outside the game dump, input directories and Cobra checkout; existing output directories are refused. Arguments use a subprocess list without a shell.

## Confirmed from the actual user-provided executable

The bridge successfully analyzed and exported `NSMBU Modding Project/code/red-pro2.rpx` on 2026-10-20. Its size is 8,356,928 bytes and SHA-256 is `ebd147ce4cdedb563db3ac6278186ca5dea282ad315271925b8bb5ac16c7dc8e`.

| Cobra discovery | Actual local result |
| --- | --- |
| Static initialization function | `0x021E1EE0` |
| Scripts table | `0x100458B8` |
| First script | `0x101C9CB0` |
| Script count | 121 |
| Terminator command | 344 |
| Detected variant | `1.3.0_NSLU` (Cobra's NSMBU 1.3.0 / NSLU grouping) |

These are **local RPX analysis results**, rather than addresses copied from an upstream US table. Cobra reconstructs runtime-initialized command IDs using its existing interpreter. The detection groups versions; it does not by itself identify every regional/standalone/bundle property or demonstrate runtime patch compatibility.

Evidence is preserved under ignored local directories:

- `local/cobra-analysis-verified/stdout.log` and `provenance.json`;
- `local/cobra-events-verified/scripts.txt`, `version.json`, logs and provenance;
- `local/cobra-events-verified-encoded/scripts.wmsc`, logs and provenance.

The unedited exported text encoded successfully to a 9,412-byte `WMS0U130` file with 121 script IDs, exactly 0 through 120, and 993 command/argument pairs. Its SHA-256 is `fdb8c2d86ba0acb56d16a5d00a24304e263ad5ced55bc7293e693427f868b45d`. Independent tests compare every encoded command, argument and priority to the exported text, verify command offsets/ranges, and check terminator 344. An additional encode using the inherited symbolic name `end` produces identical bytes.

The post-encode report now also resolves command IDs from Cobra's local NSMBU variant registry, applying parent-to-child renumbering, additions and deletions. The detected local `1.3.0_NSLU` output has no IDs outside that registry. If an ID is absent, the report emits `command_registry_warning` and lists it under `unrecognized_command_ids`; it remains a numeric ID and the WMSC is still exported. If the variant or registry cannot be resolved, `command_registry_checked` is false and the unknown-ID list is `null`. This is an advisory compatibility lint, not proof that a command is valid in-game.

This proves a local **RPX → event text → structurally validated WMSC** workflow. It is not an RPX byte roundtrip or an in-game event test. Exported original scripts and WMSC remain ignored local data; do not redistribute them as original tooling.

## Two reproducible upstream encoding defects and the local correction

The inspected Cobra commit is `0b8d3927a4466e5061367dbb69c03fcd3eeaec3b`. Its unmodified encoder fails on this exact export:

1. `convert_to_low_level` accesses the local variable `id` before assigning it while traversing inherited script/command names. The local correction stores renumbering layers, then applies them from parent to child after finding a named ID. Numeric fallback IDs remain literal numeric IDs.
2. `encode_wmsc` writes the verbose variant identifier `1.3.0_NSLU` where the specified WMSC field requires three bytes, causing its header-length assertion to fail. The local correction maps documented NSMBU variants to `100`, `110`, and `130`.

The exact GPL-covered change is supplied in `patches/cobra-encode-variable.patch`, SHA-256 `1f6a901ed0fd194fefbbcedbeef3902416588181e5935dddcc4e0d5432b27407`. The upstream file is Copyright 2021 RoadrunnerWMC, licensed GPL-3.0-or-later; the portable patch retains those terms. A verbatim copy of Cobra's GPL license accompanies it at `patches/COPYING.Cobra`, and the original headers remain in the checkout. The bridge itself is an original subprocess wrapper; the portable patch contains upstream-derived context and modifications. The separate BFRES Patricia trie code is explicitly adapted from MIT-licensed BfresLibrary with its notice in `worldstudio/bfres_names.py`.

The bridge never applies this patch silently. It records the upstream commit, the exact tracked diff as `cobra-local.patch`, the diff SHA, Python source-file SHAs and all input/output SHAs in each successful output's provenance.

For a **fresh, unmodified clone at that exact commit**, these PowerShell commands explicitly check and apply the portable correction. The current workspace clone already has it applied.

```powershell
if ((git -C external/Cobra rev-parse HEAD) -ne '0b8d3927a4466e5061367dbb69c03fcd3eeaec3b') { throw 'Unexpected Cobra commit' }
if (git -C external/Cobra status --porcelain --untracked-files=no) { throw 'Cobra has local changes; inspect them before applying' }
if ((Get-FileHash patches/cobra-encode-variable.patch -Algorithm SHA256).Hash -ne '1F6A901ED0FD194FEFBBCEDBEEF3902416588181E5935DDDCC4E0D5432B27407') { throw 'Patch hash mismatch' }
git -C external/Cobra apply --check ../../patches/cobra-encode-variable.patch
if ($LASTEXITCODE -ne 0) { throw 'Patch does not match this checkout' }
git -C external/Cobra apply ../../patches/cobra-encode-variable.patch
```

## Running new analyses and exports

Run from the World Studio project root. The output directory names below must not exist yet; choose another name for each run. Export/encode never default to writing beside the original executable.

```powershell
python tools/cobra_bridge.py analyze 'NSMBU Modding Project/code/red-pro2.rpx' --output local/my-analysis
python tools/cobra_bridge.py export 'NSMBU Modding Project/code/red-pro2.rpx' --output local/my-events
python tools/cobra_bridge.py encode local/my-events/scripts.txt local/my-events/version.json --output local/my-encoded-events
python -m unittest tests.test_cobra_bridge -v
```

Failed runs retain their logs and `success: false` provenance for diagnosis. The initial unpatched failures are retained in `local/cobra-events-roundtrip/` and `local/cobra-events-roundtrip-fixed/`.

## Integration boundary

Cobra WMSC controls overworld events, not the native node/route graph. [NSMBU-CSScript](https://github.com/Ryguy0777/NSMBU-CSScript) supplies a separate executable loader; its loader is not installed in the user dump by this workflow. The available Cemu 1.26 setup and modern RedCore/Telkin loader have not been demonstrated compatible here. Therefore no `scripts.wmsc` is deployed into game content, and event commands are not presented as tested camera/progression integration. Preserve the original executable and use a separately verified loader/target before any later runtime experiment.
