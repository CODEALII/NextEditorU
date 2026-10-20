"""Lossless CSV projects and auditable local exports.

The row order is an engine-facing ID. No implicit sorting or renumbering occurs.
Unknown fields, quoting and line endings survive unless that row is edited.
"""
import csv
import hashlib
import io
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
        self.positions = {name: list(b[0].position) for name, b in self.skeletons.bones.items()
                          if len(b) == 1 and re.fullmatch(r'W[A-Za-z0-9]{3}', name)}
        self.layout = {}
        self.terrain = None
        self.geometry = None
        return self

    def validate(self):
        errors = []
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
            if name not in self.references:
                errors.append(f'{name}: missing model reference; CSV alone cannot create a bone')
            if i >= len(self.points.initial) or r[0:2] != self.points.initial[i][0:2]:
                errors.append(f'Point row {i}: changing engine indices/names requires a verified script remap')
            changed = i >= len(self.points.initial) or r != self.points.initial[i]
            for col in (3, 6) if changed else ():
                if i < len(self.points.initial) and r[col] == self.points.initial[i][col]:
                    continue
                for dest in tokens(r[col]):
                    if dest not in self.references and dest not in seen:
                        # Cross-world destinations may live in another archive.
                        if dest[:2] == name[:2]:
                            errors.append(f'{name}: unresolved local destination {dest}')
            for col in (4, 7) if changed else ():
                if i < len(self.points.initial) and r[col] == self.points.initial[i][col]:
                    continue
                for route in tokens(r[col]):
                    if not re.fullmatch(r'R[A-Za-z0-9]{8}', route):
                        errors.append(f'{name}: malformed path {route}')
                    elif route not in self.references:
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

    def _connected(self, start, end):
        edges = {}
        for r in self.routes.rows:
            if not r or len(r[0]) != 9:
                continue
            a, b = r[0][1:5], r[0][5:9]
            edges.setdefault(a, set()).add(b)
            edges.setdefault(b, set()).add(a)
        visited, queue = set(), [start]
        while queue:
            node = queue.pop()
            if node == end:
                return True
            if node not in visited:
                visited.add(node)
                queue.extend(edges.get(node, set()) - visited)
        return False

    def save(self, path):
        path = Path(path).resolve()
        if path == self.game_root or self.game_root in path.parents:
            raise ValueError('Store projects outside the source game resource directory')
        content = json.dumps({'format': 'nsmbu-world-studio', 'version': 1,
            'source': str(self.source), 'source_sha256': self.source_sha256,
            'points': self.points.rows, 'routes': self.routes.rows,
            'layout': self.layout, 'positions': self.positions, 'terrain': self.terrain,
            'geometry': self.geometry}, indent=2)
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
        self.positions = data.get('positions', self.positions)
        self.terrain = data.get('terrain')
        self.geometry = data.get('geometry')
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
        patched_model = self.skeletons.patch_positions(self.positions)
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
            'note': 'Local artifact contains user-owned resources. Do not redistribute.'}
        manifest_path = output.with_suffix(output.suffix + '.manifest.json')
        if output.exists() or manifest_path.exists():
            raise FileExistsError('Output or manifest already exists; choose a new export path')
        write_new(output, blob)
        write_new(manifest_path, json.dumps(manifest, indent=2).encode())
        return manifest
