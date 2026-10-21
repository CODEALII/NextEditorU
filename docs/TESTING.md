# Testing and verification

## Automated offline checks

Run from the repository root:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q worldstudio tests tools
```

The suite uses synthetic fixtures and, when present, the user-supplied files under `NSMBU Modding Project/`. Local game files are read in memory and are not included in exports or commits.

Check a directed route from a declared start to one or more required points:

```powershell
python -m worldstudio validate-graph --entry W101 --require W102 --require W103
```

Repeat `--entry` to allow multiple starts and `--require` for each required destination. To validate an edited saved project, pass its `.nws.json` file before these flags. Reachability follows the point table's normal and secret destination lists. When the initial local point and route inventories are complete, changed same-world destinations must also have a directed route-segment chain. This does not simulate unlock state, route movement, level loading or save persistence.

The WebGL page is generated locally from parsed scene data. For the supplied W1 BFRES it decodes 17 shared BC1/BC3 albedo textures across all 36 shapes with UVs, applies a 50% alpha cutout, and packs geometry into little-endian typed buffers. Local W1 tests check the `Grass_alb` and `RouteW1_alb` raw/detiled hashes, then validate the complete texture catalog. To check generated viewer JavaScript against the actual dump, assemble a scene with `extract_rigid_model` and `attach_base_color_textures`, pass it to `build_document`, extract the inline script and run `node --check`. A headless Chrome run with SwiftShader rendered the full local scene and was visually inspected; user-browser hardware acceleration and interaction remain unchecked. BC4/BC5 maps, material parameters, UV transforms, light maps, game shaders and animation are not evaluated.

The native editor has bounded undo/redo (`Ctrl+Z`, `Ctrl+Y`, or the toolbar). It covers point and route rows, BFRES local-position drafts, camera offset vectors, and terrain imports. Loading or reloading a project clears the history. Undo marks the project dirty; save and export still run their normal validation.

## Cemu integration checks

Follow [INTEGRATION.md](INTEGRATION.md) to prepare an isolated profile and preserve the original game tree and saves. Use the normal game resources as a baseline before enabling a generated graphic pack. Record the active pack, input profile, starting node, exact direction tested, destination shown, level result and save/reload result.

Do not treat a successful boot or rendered map as a traversal pass. Keep every export manifest's `game_tested` field false until route, level, progression, persistence and camera checks have actually been observed.
