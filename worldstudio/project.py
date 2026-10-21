"""Lossless CSV projects and auditable local exports.

The row order is an engine-facing ID. No implicit sorting or renumbering occurs.
Unknown fields, quoting and line endings survive unless that row is edited.
"""
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from .archive import Archive
from .bfres import Skeletons


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_new(path, data):
    """Create once: neither existing exports nor original files are overwritten."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f:
        f.write(data)


class Table:
    def __init__(self, data):
        self.raw = data
        self.lines = data.decode('cp932').splitlines(keepends=True)
        # splitlines handles the dump's CRLF as well as CRCRLF variants.
        self.lines = [line for line in self.lines if line.strip('\r\n')]
        self.rows = [next(csv.reader([line.rstrip('\r\n')])) for line in self.lines]
        self.initial = [r[:] for r in self.rows]
        self.newline = '\r\r\n' if b'\r\r\n' in data else '\r\n' if b'\r\n' in data else '\n'
        self.quoted = []
        for line in self.lines:
            fields = re.findall(r'(?:"(?:[^"]|"")*"|[^,\r\n]*)(?:,|$)', line.rstrip('\r\n'))
            self.quoted.append([f.startswith('"') for f in fields[:len(self.rows[len(self.quoted)])]])

    def encode(self):
        if self.rows == self.initial:
            return self.raw
        result = []
        for i, row in enumerate(self.rows):
            if i < len(self.initial) and row == self.initial[i]:
                result.append(self.lines[i])
            else:
                # The game has its own CSV/list parser. Keep explicit quotes on
                # array cells even when their edited value has only one item.
                fields = []
                for j, value in enumerate(row):
                    quoted = i < len(self.quoted) and j < len(self.quoted[i]) and self.quoted[i][j]
                    if quoted or any(c in value for c in ',"\r\n'):
                        fields.append('"' + value.replace('"', '""') + '"')
                    else:
                        fields.append(value)
                result.append(','.join(fields) + self.newline)
        return ''.join(result).encode('cp932')


def tokens(value):
    return [t.strip() for t in value.split(',') if t.strip()]


class WorldProject:
    @classmethod
    def open(cls, path):
        self = cls()
        self.source = Path(path).resolve()
        self.game_root = next((p.parent for p in self.source.parents if p.name.lower() == 'content'), self.source.parent)
        self.archive = Archive(self.source.read_bytes())
        self.source_sha256 = sha(self.archive.original)
        points = [n for n in self.archive.entries if re.fullmatch(r'pointW\w+\.csv', n)]
        routes = [n for n in self.archive.entries if re.fullmatch(r'routeW\w+\.csv', n)]
        models = [n for n in self.archive.entries if n.endswith('.bfres')]
        if len(points) != 1 or len(routes) != 1 or len(models) != 1:
            raise ValueError('Expected one point CSV, route CSV and BFRES in world archive')
        self.point_name, self.route_name, self.model_name = points[0], routes[0], models[0]
        self.points = Table(self.archive.read(self.point_name))
        self.routes = Table(self.archive.read(self.route_name))
        self.model = self.archive.read(self.model_name)
        # String inventory is conservative reference checking, not a BFRES parser.
        self.references = set(m.decode('ascii') for m in re.findall(rb'(?<![A-Za-z0-9_])[A-Za-z0-9_]{4,64}\x00', self.model))
        self.references = {n.rstrip('\x00') for n in self.references}
        self.skeletons = Skeletons(self.model)
        self.references.update(self.skeletons.bones)
        point_names = {r[1] for r in self.points.rows}
        self.path_model = max(self.skeletons.models,
            key=lambda m: sum(b.name in point_names for b in self.skeletons.models[m]))
        self.positions = {b.name: list(b.position) for b in self.skeletons.models[self.path_model]
                          if len(self.skeletons.bones[b.name]) == 1 and
                          re.fullmatch(r'(?:[WFK][A-Za-z0-9]{3}|R[A-Za-z0-9]{8})', b.name)}
        self.layout = {}
        self.terrain = None
        self.geometry = None
        self.bone_renames = []
        self.camera_tables = {}
        self.camera_original = {}
        self.camera_edits = {}
        self.camera_load_errors = []
        from .camera import OffsetTable
        world = re.search(r'pointW([1-9])', self.point_name)
        if world:
            for prefix, kind in (('Mario', 'mario'), ('Look', 'look')):
                name = f'{prefix}OffsetDataW{world[1]}.bin'
                companion = self.source.parent / name
                if companion.is_file():
                    raw = companion.read_bytes()
                    try:
                        self.camera_tables[name] = OffsetTable.parse(raw, kind)
                        self.camera_original[name] = raw
                    except ValueError as exc:
                        self.camera_load_errors.append(f'{name}: {exc}')
        return self

    @property
    def world_positions(self):
        return self.skeletons.world_positions(self.path_model, self.positions)

    def camera_table(self, filename):
        if filename not in self.camera_tables:
            raise ValueError(f'Unknown or unsupported camera table: {filename}')
        table = self.camera_tables[filename]
        for key, vector in self.camera_edits.get(filename, {}).items():
            try:
                bank, index = map(int, key.split(':'))
            except (ValueError, AttributeError) as exc:
                raise ValueError(f'Invalid camera record identifier {key!r}') from exc
            table = table.with_vector(bank, index, vector)
        return table

    def set_camera_vector(self, filename, bank, index, vector):
        table = self.camera_table(filename).with_vector(bank, index, vector)
        key = f'{bank}:{index}'
        edits = self.camera_edits.setdefault(filename, {})
        if table.record(bank, index).vector == self.camera_tables[filename].record(bank, index).vector:
            edits.pop(key, None)
        else:
            edits[key] = list(table.record(bank, index).vector)
        if not edits:
            self.camera_edits.pop(filename, None)

    def validate(self):
        errors = []
        for filename in self.camera_edits:
            try:
                self.camera_table(filename).build()
            except (ValueError, TypeError) as exc:
                errors.append(str(exc))
        references = set(self.references)
        rename_targets = set()
        for rename in self.bone_renames:
            model, old, new = rename.get('model'), rename.get('old'), rename.get('new')
            if model not in self.skeletons.models or old not in {b.name for b in self.skeletons.models.get(model, [])}:
                errors.append(f'Unknown source bone for rename: {model}/{old}')
                continue
            if not isinstance(new, str) or not new.isascii() or len(new) != len(old) or new in rename_targets or new in references:
                errors.append(f'Invalid or colliding bone rename: {old} -> {new}')
                continue
            rename_targets.add(new)
            references.discard(old)
            references.add(new)
        seen = set()
        for i, r in enumerate(self.points.rows):
            if len(r) != 9:
                errors.append(f'Point row {i}: expected 9 columns')
                continue
            name = r[1]
            if not re.fullmatch(r'[WF][A-Za-z0-9]{3}', name):
                errors.append(f'Point row {i}: invalid point name {name!r}')
            if name in seen:
                errors.append(f'Duplicate point {name}')
            seen.add(name)
            if name not in references:
                errors.append(f'{name}: missing model reference; CSV alone cannot create a bone')
            if i >= len(self.points.initial) or r[0:2] != self.points.initial[i][0:2]:
                errors.append(f'Point row {i}: changing engine indices/names requires a verified script remap')
            changed = i >= len(self.points.initial) or r != self.points.initial[i]
            for col in (3, 6) if changed else ():
                if i < len(self.points.initial) and r[col] == self.points.initial[i][col]:
                    continue
                for dest in tokens(r[col]):
                    if dest not in references and dest not in seen:
                        # Cross-world destinations may live in another archive.
                        if dest[:2] == name[:2]:
                            errors.append(f'{name}: unresolved local destination {dest}')
            for col in (4, 7) if changed else ():
                if i < len(self.points.initial) and r[col] == self.points.initial[i][col]:
                    continue
                for route in tokens(r[col]):
                    if not re.fullmatch(r'R[A-Za-z0-9]{8}', route):
                        errors.append(f'{name}: malformed path {route}')
                    elif route not in references:
                        errors.append(f'{name}: missing BFRES macro-path bone {route}')
        if len(self.points.rows) != len(self.points.initial):
            errors.append('Point row count changed: engine/script index remapping not implemented')
        route_seen = set()
        for i, r in enumerate(self.routes.rows):
            if len(r) != 3 or not re.fullmatch(r'R[A-Za-z0-9]{8}', r[0]):
                errors.append(f'Route row {i}: expected route name, road type, reserved column')
                continue
            if r[0] in route_seen:
                errors.append(f'Duplicate route segment {r[0]}')
            route_seen.add(r[0])
            if i >= len(self.routes.initial) or r != self.routes.initial[i]:
                for endpoint in (r[0][1:5], r[0][5:9]):
                    if endpoint not in self.skeletons.bones:
                        errors.append(f'{r[0]}: missing endpoint bone {endpoint}')
        return sorted(set(errors))

    def save(self, path):
        path = Path(path).resolve()
        if path == self.game_root or self.game_root in path.parents:
            raise ValueError('Store projects outside the source game resource directory')
        content = json.dumps({'format': 'nsmbu-world-studio', 'version': 1,
            'source': str(self.source), 'source_sha256': self.source_sha256,
            'points': self.points.rows, 'routes': self.routes.rows,
            'layout': self.layout, 'positions': self.positions, 'terrain': self.terrain,
            'geometry': self.geometry, 'bone_renames': self.bone_renames,
            'camera_edits': self.camera_edits,
            'camera_source_sha256': {n: sha(v) for n,v in self.camera_original.items()}}, indent=2)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.worldstudio-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(content)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if data.get('format') != 'nsmbu-world-studio' or data.get('version') != 1:
            raise ValueError('Unsupported project format')
        self = cls.open(data['source'])
        if self.source_sha256 != data['source_sha256']:
            raise ValueError('Source archive changed since project creation')
        self.points.rows = data['points']
        self.routes.rows = data['routes']
        self.layout = data.get('layout', {})
        self.positions.update(data.get('positions', {}))
        self.terrain = data.get('terrain')
        self.geometry = data.get('geometry')
        self.bone_renames = data.get('bone_renames', [])
        self.camera_edits = data.get('camera_edits', {})
        for name in self.camera_edits:
            expected = data.get('camera_source_sha256', {}).get(name)
            if name not in self.camera_original or expected != sha(self.camera_original[name]):
                raise ValueError(f'Camera source changed or is missing: {name}')
        return self

    def export(self, output):
        errors = self.validate()
        if errors:
            raise ValueError('\n'.join(errors))
        if sha(self.source.read_bytes()) != self.source_sha256:
            raise ValueError('Source archive has changed; reload it before exporting')
        output = Path(output).resolve()
        if output == self.game_root or self.game_root in output.parents:
            raise ValueError('Export outside original game resources')
        camera_outputs = {}
        for name in self.camera_edits:
            if sha((self.source.parent / name).read_bytes()) != sha(self.camera_original[name]):
                raise ValueError(f'Camera source changed: {name}')
            encoded = self.camera_table(name).build()
            if encoded != self.camera_original[name]:
                camera_outputs[name] = encoded
        patched_model = self.skeletons.patch_positions(self.positions)
        rename_reports = []
        if self.bone_renames:
            from .bfres_names import rename_bone
            for rename in self.bone_renames:
                patched_model, report = rename_bone(patched_model,
                    rename['model'], rename['old'], rename['new'])
                rename_reports.append(report)
        geometry_report = None
        if self.geometry is not None:
            from .mesh import replace_rigid_mesh
            patched_model, geometry_report = replace_rigid_mesh(patched_model,
                self.geometry['vertices'], self.geometry['faces'])
        modified = {self.point_name: self.points.encode(), self.route_name: self.routes.encode(),
                    self.model_name: patched_model}
        blob = self.archive.replace(modified)
        check = Archive(blob)
        if check.read(self.model_name) != patched_model:
            raise ValueError('Export verification: model differs from intended patch')
        for name, value in modified.items():
            if check.read(name) != value:
                raise ValueError(f'Export verification failed for {name}')
        for name in self.archive.entries:
            if name not in modified and check.read(name) != self.archive.read(name):
                raise ValueError(f'Export verification changed unrelated entry {name}')
        manifest = {'source_sha256': self.source_sha256, 'output_sha256': sha(blob),
            'output': str(output), 'changed_entries': [n for n,v in modified.items() if v != self.archive.read(n)],
            'bfres_unchanged': patched_model == self.model, 'game_tested': False,
            'terrain_exported': geometry_report is not None, 'geometry': geometry_report,
            'bone_renames': rename_reports,
            'camera_files': {n: {'source_sha256': sha(self.camera_original[n]), 'output_sha256': sha(v)}
                             for n,v in camera_outputs.items()},
            'note': 'Local artifact contains user-owned resources. Do not redistribute.'}
        manifest_path = output.with_suffix(output.suffix + '.manifest.json')
        paths = [output, manifest_path, *(output.parent / n for n in camera_outputs)]
        if len(set(paths)) != len(paths):
            raise ValueError('Archive and companion output paths collide')
        if any(p.exists() for p in paths):
            raise FileExistsError('Output, companion or manifest already exists; choose a new export path')
        write_new(output, blob)
        for name, encoded in camera_outputs.items():
            write_new(output.parent / name, encoded)
        write_new(manifest_path, json.dumps(manifest, indent=2).encode())
        return manifest
