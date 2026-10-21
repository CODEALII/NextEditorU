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

Repeat `--entry` to allow multiple starts and `--require` for each required destination. To validate an edited saved project, pass its `.nws.json` file before these flags. Reachability follows the point table's normal and secret destination lists; it does not simulate unlock state, route movement, level loading or save persistence.

The WebGL page is generated locally from parsed scene data. For the supplied W1 BFRES it decodes the `Grass_alb` BC1 base texture on the main grass shape; all other materials remain approximate colors. The texture decoder is checked against a fixed SHA-256 of the local detiled texture, while embedded JavaScript can be syntax-checked with Node. Browser rendering still needs a visual check. Game shaders, other textures and animation are not evaluated.

## Cemu integration checks

Follow [INTEGRATION.md](INTEGRATION.md) to prepare an isolated profile and preserve the original game tree and saves. Use the normal game resources as a baseline before enabling a generated graphic pack. Record the active pack, input profile, starting node, exact direction tested, destination shown, level result and save/reload result.

Do not treat a successful boot or rendered map as a traversal pass. Keep every export manifest's `game_tested` field false until route, level, progression, persistence and camera checks have actually been observed.
