"""Lossless CSV projects and auditable local exports.

The row order is an engine-facing ID. No implicit sorting or renumbering occurs.
Unknown fields, quoting and line endings survive unless that row is edited.
"""
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from .archive import Archive
from .bfres import Skeletons

PROJECT_BACKUP_GENERATIONS = 2


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_new(path, data):
    """Create once: neither existing exports nor original files are overwritten."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with path.open('xb') as f:
            created = True
            f.write(data)
    except Exception:
        if created:
            try:
                path.unlink()
            except OSError:
                pass
        raise


def _atomic_replace(path, data):
    """Atomically replace one project file without exposing a partial write."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.worldstudio-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _project_backup_path(path, generation):
    path = Path(path)
    suffix = '.backup.json' if generation == 1 else f'.backup-{generation}.json'
    return path.with_name(path.stem + suffix)


def save_project_bytes(path, data):
    """Atomically write a JSON project and rotate two changed prior versions."""
    path = Path(path)
    if not isinstance(data, bytes):
        raise TypeError('Project contents must be bytes')
    backup = None
    if path.is_file():
        previous = path.read_bytes()
        if previous != data:
            for generation in range(PROJECT_BACKUP_GENERATIONS, 1, -1):
                older = _project_backup_path(path, generation - 1)
                if older.is_file():
                    _atomic_replace(_project_backup_path(path, generation), older.read_bytes())
            backup = _project_backup_path(path, 1)
            _atomic_replace(backup, previous)
    _atomic_replace(path, data)
    return backup


def store_project_path(value, project_file):
    """Store asset references relative to the project whenever drives allow."""
    if not value:
        return value
    asset = Path(value).resolve()
    base = Path(project_file).resolve().parent
    try:
        return asset.relative_to(base).as_posix()
    except ValueError:
        try:
            return os.path.relpath(asset, base)
        except ValueError:
            return str(asset)


def resolve_project_path(value, project_file):
    """Resolve relative project references while retaining v1 absolute paths."""
    if not value:
        return value
    asset = Path(value)
    if not asset.is_absolute():
        asset = Path(project_file).resolve().parent / asset
    return str(asset.resolve())


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
        preview_model = f'{self.source.stem}_World'
        if preview_model not in self.skeletons.models:
            world_models = [name for name in self.skeletons.models if name.endswith('_World')]
            if len(world_models) == 1:
                preview_model = world_models[0]
            else:
                from .mesh import DEFAULT_MODEL
                preview_model = DEFAULT_MODEL if DEFAULT_MODEL in self.skeletons.models else self.path_model
        self.preview_model_name = preview_model
        self.positions = {b.name: list(b.position) for b in self.skeletons.models[self.path_model]
                          if len(self.skeletons.bones[b.name]) == 1 and
                          re.fullmatch(r'(?:[WFK][A-Za-z0-9]{3}|R[A-Za-z0-9]{8})', b.name)}
        from .mesh import rigid_shape_bindings
        shape_bindings = rigid_shape_bindings(self.model, self.preview_model_name)
        self.object_shape_bindings = {}
        point_names = {row[1] for row in self.points.rows if len(row) > 1}
        path_position_names = set(self.positions)
        for shape_name, bone_name in shape_bindings.items():
            bone = next((item for item in self.skeletons.models[self.preview_model_name]
                         if item.name == bone_name), None)
            if (bone is None or bone.parent == -1 or bone_name in point_names or
                    bone_name in path_position_names or
                    len(self.skeletons.bones.get(bone_name, ())) != 1):
                continue
            self.object_shape_bindings.setdefault(bone_name, []).append(shape_name)
        self.object_positions = {
            bone.name: list(bone.position)
            for bone in self.skeletons.models[self.preview_model_name]
            if bone.name in self.object_shape_bindings
        }
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
        edits = self.camera_edits.get(filename, {})
        if not isinstance(edits, dict):
            raise ValueError(f'Camera edits for {filename} must be an object')
        for key, vector in edits.items():
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
        world = re.search(r'pointW([1-9])', self.point_name)
        world_prefix = f'W{world[1]}' if world else None
        if self.geometry is not None:
            if not isinstance(self.geometry, dict):
                errors.append('Terrain geometry must be an object')
            else:
                missing = [field for field in ('vertices', 'faces')
                           if field not in self.geometry]
                if missing:
                    errors.append('Terrain geometry missing required field(s): ' +
                                  ', '.join(missing))
                else:
                    try:
                        from .mesh import _geometry
                        _geometry(
                            self.geometry['vertices'], self.geometry['faces'],
                            uvs=self.geometry.get('uvs'),
                            imported_normals=self.geometry.get('normals'))
                    except (KeyError, TypeError, ValueError, OverflowError) as exc:
                        errors.append(f'Terrain geometry invalid: {exc}')
        camera_edits = getattr(self, 'camera_edits', {})
        if not isinstance(camera_edits, dict):
            errors.append('Camera edits must be an object')
            camera_edits = {}
        for filename in camera_edits:
            try:
                self.camera_table(filename).build()
            except (ValueError, TypeError) as exc:
                errors.append(str(exc))
        references = set(self.references)
        rename_targets = set()
        bone_renames = getattr(self, 'bone_renames', [])
        if not isinstance(bone_renames, list):
            errors.append('Bone renames must be a list')
            bone_renames = []
        for rename in bone_renames:
            if not isinstance(rename, dict):
                errors.append('Bone rename entries must be objects')
                continue
            model, old, new = rename.get('model'), rename.get('old'), rename.get('new')
            if not isinstance(model, str) or not isinstance(old, str):
                errors.append(f'Invalid bone rename entry: {rename!r}')
                continue
            if model not in self.skeletons.models or old not in {b.name for b in self.skeletons.models.get(model, [])}:
                errors.append(f'Unknown source bone for rename: {model}/{old}')
                continue
            if not isinstance(new, str) or not new.isascii() or len(new) != len(old) or new in rename_targets or new in references:
                errors.append(f'Invalid or colliding bone rename: {old} -> {new}')
                continue
            rename_targets.add(new)
            references.discard(old)
            references.add(new)

        positions = getattr(self, 'positions', {})
        if not isinstance(positions, dict):
            errors.append('Bone positions must be an object')
            positions = {}
        models = getattr(self.skeletons, 'models', {})
        bones = getattr(self.skeletons, 'bones', {})
        path_model = getattr(self, 'path_model', None)
        supported_position_bones = {
            bone.name for bone in models.get(path_model, [])
            if (len(bones.get(bone.name, ())) == 1 and
                re.fullmatch(r'(?:[WFK][A-Za-z0-9]{3}|R[A-Za-z0-9]{8})', bone.name))
        }
        for name, xyz in positions.items():
            if not isinstance(name, str) or name not in supported_position_bones:
                errors.append(f'Position {name!r}: bone is not unique in the supported path model')
                continue
            try:
                if (not isinstance(xyz, (list, tuple)) or len(xyz) != 3 or
                        any(isinstance(value, bool) for value in xyz)):
                    raise ValueError
                values = tuple(float(value) for value in xyz)
                if not all(math.isfinite(value) and abs(value) <= 1e7 for value in values):
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                errors.append(f'Position {name}: expected three finite coordinates within +/-1e7')

        object_positions = getattr(self, 'object_positions', {})
        if not isinstance(object_positions, dict):
            errors.append('BFRES object positions must be an object')
            object_positions = {}
        for name, xyz in object_positions.items():
            if (not isinstance(name, str) or name not in getattr(self, 'object_shape_bindings', {})):
                errors.append(f'Object position {name!r}: bone is not a unique supported rigid-shape binding')
                continue
            try:
                if (not isinstance(xyz, (list, tuple)) or len(xyz) != 3 or
                        any(isinstance(value, bool) for value in xyz)):
                    raise ValueError
                values = tuple(float(value) for value in xyz)
                if not all(math.isfinite(value) and abs(value) <= 1e7 for value in values):
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                errors.append(f'Object position {name}: expected three finite coordinates within +/-1e7')

        point_rows = getattr(self.points, 'rows', None)
        if not isinstance(point_rows, (list, tuple)):
            errors.append('Point table must be a list of rows')
            point_rows = []
        point_rows_valid = True
        seen = set()
        for i, r in enumerate(point_rows):
            if not isinstance(r, (list, tuple)):
                errors.append(f'Point row {i}: expected 9 text columns')
                point_rows_valid = False
                continue
            if len(r) != 9:
                errors.append(f'Point row {i}: expected 9 columns')
                point_rows_valid = False
                continue
            if any(not isinstance(value, str) for value in r):
                errors.append(f'Point row {i}: expected text in all 9 columns')
                point_rows_valid = False
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
        if len(point_rows) != len(self.points.initial):
            errors.append('Point row count changed: engine/script index remapping not implemented')
        route_rows = getattr(self.routes, 'rows', None)
        if not isinstance(route_rows, (list, tuple)):
            errors.append('Route table must be a list of rows')
            route_rows = []
        from .graph_validation import native_road_type_choices
        valid_road_types = set(native_road_type_choices(getattr(self.routes, 'initial', ())))
        route_rows_valid = True
        route_seen = set()
        for i, r in enumerate(route_rows):
            if not isinstance(r, (list, tuple)):
                errors.append(f'Route row {i}: expected 3 text columns')
                route_rows_valid = False
                continue
            if len(r) != 3:
                errors.append(f'Route row {i}: expected route name, road type, reserved column')
                route_rows_valid = False
                continue
            if any(not isinstance(value, str) for value in r):
                errors.append(f'Route row {i}: expected text in all 3 columns')
                route_rows_valid = False
                continue
            if not re.fullmatch(r'R[A-Za-z0-9]{8}', r[0]):
                errors.append(f'Route row {i}: expected route name, road type, reserved column')
                route_rows_valid = False
                continue
            if r[0] in route_seen:
                errors.append(f'Duplicate route segment {r[0]}')
            route_seen.add(r[0])
            route_initial = self.routes.initial[i] if i < len(self.routes.initial) else None
            road_type_changed = (
                not isinstance(route_initial, (list, tuple)) or len(route_initial) < 2 or
                not isinstance(route_initial[1], str) or r[1] != route_initial[1])
            if road_type_changed:
                if not r[1].strip():
                    errors.append(f'Route row {i}: road type cannot be empty')
                elif r[1] not in valid_road_types:
                    errors.append(
                        f'Route row {i}: unknown road type {r[1]!r}; choose a type used by the source table')
            if i >= len(self.routes.initial) or r != self.routes.initial[i]:
                for endpoint in (r[0][1:5], r[0][5:9]):
                    if (world_prefix and endpoint.startswith('W') and
                            not endpoint.startswith(world_prefix)):
                        continue
                    if endpoint not in self.skeletons.bones:
                        errors.append(f'{r[0]}: missing endpoint bone {endpoint}')
        if world and point_rows_valid and route_rows_valid:
            from .graph_validation import validate_native_world
            errors.extend(validate_native_world(
                point_rows,
                route_rows,
                known_references=references,
                initial_points=self.points.initial,
                initial_routes=self.routes.initial,
                world_prefix=f'W{world[1]}',
            ))
        return sorted(set(errors))

    def save(self, path):
        path = Path(path).resolve()
        if path == self.game_root or self.game_root in path.parents:
            raise ValueError('Store projects outside the source game resource directory')
        terrain = store_project_path(self.terrain, path)
        content = json.dumps({'format': 'nsmbu-world-studio', 'version': 1,
            'source': str(self.source), 'source_sha256': self.source_sha256,
            'points': self.points.rows, 'routes': self.routes.rows,
            'layout': self.layout, 'positions': self.positions,
            'object_positions': self.object_positions, 'terrain': terrain,
            'geometry': self.geometry, 'bone_renames': self.bone_renames,
            'camera_edits': self.camera_edits,
            'camera_source_sha256': {n: sha(v) for n,v in self.camera_original.items()}}, indent=2)
        return save_project_bytes(path, content.encode('utf-8'))

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('Project file must contain a JSON object')
        if data.get('format') != 'nsmbu-world-studio' or data.get('version') != 1:
            raise ValueError('Unsupported project format')
        source = data.get('source')
        if not isinstance(source, str) or not source:
            raise ValueError('Project source must be a file path string')
        source_sha256 = data.get('source_sha256')
        if not isinstance(source_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', source_sha256):
            raise ValueError('Project source hash must be a SHA-256 hex string')
        positions = data.get('positions', {})
        if not isinstance(positions, dict):
            raise ValueError('Project positions must be an object')
        object_positions = data.get('object_positions', {})
        if not isinstance(object_positions, dict):
            raise ValueError('Project BFRES object positions must be an object')
        layout = data.get('layout', {})
        if not isinstance(layout, dict):
            raise ValueError('Project layout must be an object')
        bone_renames = data.get('bone_renames', [])
        if not isinstance(bone_renames, list):
            raise ValueError('Project bone renames must be a list')
        camera_edits = data.get('camera_edits', {})
        if not isinstance(camera_edits, dict):
            raise ValueError('Project camera edits must be an object')
        camera_source_sha256 = data.get('camera_source_sha256', {})
        if not isinstance(camera_source_sha256, dict):
            raise ValueError('Project camera source hashes must be an object')
        terrain = data.get('terrain')
        if terrain is not None and not isinstance(terrain, str):
            raise ValueError('Project terrain path must be a string or null')
        self = cls.open(source)
        if self.source_sha256 != source_sha256:
            raise ValueError('Source archive changed since project creation')
        self.points.rows = data.get('points')
        self.routes.rows = data.get('routes')
        self.layout = layout
        self.positions.update(positions)
        self.object_positions.update(object_positions)
        self.terrain = resolve_project_path(terrain, path)
        self.geometry = data.get('geometry')
        self.bone_renames = bone_renames
        self.camera_edits = camera_edits
        for name in self.camera_edits:
            expected = camera_source_sha256.get(name)
            if name not in self.camera_original or expected != sha(self.camera_original[name]):
                raise ValueError(f'Camera source changed or is missing: {name}')
        return self

    def export(self, output, *, graph_profile=None):
        errors = self.validate()
        if errors:
            raise ValueError('\n'.join(errors))
        graph_validation = None
        if graph_profile is not None:
            from .graph_validation import validate_native_project_profile
            graph_validation, profile_issues = validate_native_project_profile(
                self, graph_profile)
            if profile_issues:
                raise ValueError('Graph validation failed:\n' + '\n'.join(profile_issues))
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
        patched_positions = dict(self.positions)
        patched_positions.update(self.object_positions)
        patched_model = self.skeletons.patch_positions(patched_positions)
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
                self.geometry['vertices'], self.geometry['faces'],
                uvs=self.geometry.get('uvs'),
                imported_normals=self.geometry.get('normals'),
                preserve_topology=True)
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
        entry_changes = {}
        for name, value in modified.items():
            original = self.archive.read(name)
            if value == original:
                continue
            entry_changes[name] = {
                'source_sha256': sha(original),
                'output_sha256': sha(value),
                'source_size_bytes': len(original),
                'output_size_bytes': len(value),
                'size_delta_bytes': len(value) - len(original),
            }
        manifest = {'source_sha256': self.source_sha256, 'output_sha256': sha(blob),
            'output': str(output), 'changed_entries': list(entry_changes),
            'entry_changes': entry_changes,
            'bfres_unchanged': patched_model == self.model, 'game_tested': False,
            'terrain_exported': geometry_report is not None, 'geometry': geometry_report,
            'graph_validation': graph_validation,
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
        created_outputs = []
        try:
            write_new(output, blob)
            created_outputs.append(output)
            for name, encoded in camera_outputs.items():
                companion = output.parent / name
                write_new(companion, encoded)
                created_outputs.append(companion)
            write_new(manifest_path, json.dumps(manifest, indent=2).encode())
            created_outputs.append(manifest_path)
        except Exception:
            for created_path in reversed(created_outputs):
                try:
                    created_path.unlink()
                except OSError:
                    pass
            raise
        return manifest
