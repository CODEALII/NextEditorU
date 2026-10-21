# NSMBU World Studio

**A research and editing toolkit for New Super Mario Bros. U world maps.**

World Studio reads and edits selected world-map resources, builds experimental topology and terrain patches, and provides a standalone visual editor. It is an actively researched prototype: resource handling and offline export are tested, while in-game movement currently fails in the reported route test. This project does not yet produce a complete playable custom overworld.

![World Studio project progress dashboard](docs/progress.svg)

Progress details and dated findings: [PROGRESS.md](PROGRESS.md) · [Runtime test notes](docs/INTEGRATION.md)

## What works today

- Read Yaz0/SARC archives and export patched archives while preserving untouched members.
- Read and edit World 1 point and route tables; validate references before export.
- Inspect supported BFRES skeletons and apply bounded bone-transform changes.
- Export an experimental three-node progression patch using existing route data.
- Import a bounded rigid OBJ mesh into a known grass shape while retaining its material and layout.
- Read and edit discovered camera-offset tables; analyze and round-trip event data offline.
- Use the standalone Tk editor to inspect the map, edit supported fields, and save project files.
- Run a 56-test local suite against synthetic fixtures and the user-provided local dump.

The editor deliberately blocks unsupported node/index changes. Camera and event formats have offline tooling, but their in-game behavior and runtime integration are not verified. Read [Research and format findings](docs/RESEARCH.md), [Resource findings](docs/RESOURCE_FINDINGS.md), [Camera findings](docs/CAMERA_FINDINGS.md), and [Event findings](docs/EVENTS.md) for the evidence and limits of each feature.

## Current runtime status

The experimental topology patch changes the intended three-node path, but the latest manual Cemu attempt reported that **Mario does not move**. The cause has not been identified, so topology traversal, level launch, unlock progression, and save persistence are not claimed to work. The corrected terrain exporter is prepared in an isolated test pack, but its appearance has not been visually confirmed. See [the integration log](docs/INTEGRATION.md).

## Get started

Requirements: Windows, Python 3.14 with Tkinter, a legally obtained NSMBU dump for resource work, and Cemu for optional isolated runtime tests.

```powershell
python -m worldstudio gui
```

Or double-click `Launch World Studio.cmd`. By default the editor looks for the local game resource at `NSMBU Modding Project/content/Common/course_select/CS_W1.szs`. The dump is not included in this repository.

Inspect resources and create a sample topology export:

```powershell
python -m worldstudio inspect
python -m worldstudio demo --out build/my-chain
python -m worldstudio gui build/my-chain/three-level-chain.nws.json
```

The experimental mesh export accepts the included original sample island:

```powershell
python -m worldstudio demo --island assets/island.obj --out build/my-island
```

Exports go to new paths and include manifests. Never copy them over the original game files. For the isolated Cemu workflow, see [docs/INTEGRATION.md](docs/INTEGRATION.md) and `tools/prepare_cemu.py`.

## Verify locally

```powershell
python -m unittest discover -s tests -v
python -m compileall -q worldstudio tests tools
```

The latest verified local run passed **56 tests**. This confirms offline parsers, exporters, guards, and round-trips; it does not establish that the game accepts every patch or that gameplay works.

## Repository map

| Path | Purpose |
| --- | --- |
| `worldstudio/` | Resource readers, patch/export logic, and Tk editor |
| `tools/` | Cemu test setup and inspection/event bridge tools |
| `tests/` | Synthetic and user-dump-backed regression tests |
| `docs/` | Research notes, integration evidence, and progress graphic |
| `assets/` | Original CC0 preview geometry |
| `examples/` | Original CC0 game-space test geometry |
| `patches/` | Small upstream Cobra encoder fix and its license |

## Safety and licensing

No Nintendo game dump, executable, save, emulator build, or generated game-resource pack is distributed here. Supply your own legally obtained game files; local dump, build, and evidence folders are ignored by Git. The included island OBJ files are original project geometry and carry CC0 notices in their headers.

There is no repository-wide code license yet. The Cobra-related patch and bridge preserve the upstream GPL license notice in `patches/COPYING.Cobra`; see [docs/RESEARCH.md](docs/RESEARCH.md) for provenance and pinned upstream references.

## Contributing

Keep findings tied to reproducible evidence, preserve unknown resource bytes, and distinguish offline tests from Cemu or hardware observations. Update `PROGRESS.md` and the relevant format note when behavior changes. Do not add user-owned game dumps, saves, executables, generated packs, or credentials to commits.
