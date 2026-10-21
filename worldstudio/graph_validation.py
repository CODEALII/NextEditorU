"""Validation helpers for native overworld point and route tables.

These checks deliberately keep game-specific reachability explicit. Native
point CSVs also contain helper, trigger, and camera points, so callers must
identify the playable entry and required locations instead of treating every
point as a level node.
"""
import re


_POINT_ID = re.compile(r"[WF][A-Za-z0-9]{3}\Z")
_ROUTE_ID = re.compile(r"R[A-Za-z0-9]{8}\Z")


def _tokens(value):
    return [token.strip() for token in value.split(",") if token.strip()]


def _field_changed(row, initial_rows, index, column):
    return (initial_rows is None or index >= len(initial_rows) or
            column >= len(initial_rows[index]) or row[column] != initial_rows[index][column])


def validate_native_world(
    point_rows,
    route_rows,
    *,
    known_references=None,
    initial_points=None,
    initial_routes=None,
    world_prefix=None,
    entry_points=(),
    required_locations=(),
):
    """Return deterministic diagnostics for native point/route table edits.

    ``known_references`` is normally the model's conservative BFRES name
    inventory. When ``initial_points`` or ``initial_routes`` is supplied,
    expensive cross-resource references are checked only on changed rows; this
    avoids turning pre-existing, partially inventoried game data into errors.

    Reachability follows point destination columns (normal and secret) as
    directed links. ``entry_points`` and ``required_locations`` are explicit
    because the native table includes non-playable helper points and does not
    label all gameplay roles itself.
    """
    issues = []
    point_names = set()
    point_rows_by_name = {}
    for index, row in enumerate(point_rows):
        if not isinstance(row, (list, tuple)) or len(row) != 9:
            issues.append(f"Point row {index}: expected 9 columns")
            continue
        name = row[1]
        if not isinstance(name, str) or not _POINT_ID.fullmatch(name):
            issues.append(f"Point row {index}: invalid point name {name!r}")
            continue
        if name in point_names:
            issues.append(f"Duplicate point {name}")
        point_names.add(name)
        point_rows_by_name[name] = row

    route_names = set()
    for index, row in enumerate(route_rows):
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            issues.append(f"Route row {index}: expected 3 columns")
            continue
        name = row[0]
        if not isinstance(name, str) or not _ROUTE_ID.fullmatch(name):
            issues.append(f"Route row {index}: invalid route name {name!r}")
            continue
        if name in route_names:
            issues.append(f"Duplicate route segment {name}")
        route_names.add(name)

        name_changed = _field_changed(row, initial_routes, index, 0)
        if name_changed and known_references is not None:
            for endpoint in (name[1:5], name[5:9]):
                if endpoint not in known_references:
                    issues.append(f"{name}: missing endpoint model reference {endpoint}")

    references = set(known_references) if known_references is not None else None
    adjacency = {name: set() for name in point_names}
    for index, row in enumerate(point_rows):
        if not isinstance(row, (list, tuple)) or len(row) != 9:
            continue
        name = row[1]
        if name not in point_names:
            continue
        for column in (3, 6):
            if not isinstance(row[column], str):
                issues.append(f"{name}: invalid destination list in column {column}")
                continue
            for destination in _tokens(row[column]):
                if not _POINT_ID.fullmatch(destination):
                    if _field_changed(row, initial_points, index, column):
                        issues.append(f"{name}: malformed destination {destination}")
                    continue
                if destination in point_names:
                    adjacency[name].add(destination)
                elif (_field_changed(row, initial_points, index, column) and world_prefix and
                      destination.startswith(world_prefix)):
                    issues.append(f"{name}: unresolved local destination {destination}")
        if references is not None:
            for column in (4, 7):
                if not _field_changed(row, initial_points, index, column):
                    continue
                if not isinstance(row[column], str):
                    issues.append(f"{name}: invalid path list in column {column}")
                    continue
                for path in _tokens(row[column]):
                    if not _ROUTE_ID.fullmatch(path):
                        issues.append(f"{name}: malformed path {path}")
                    elif path not in references:
                        issues.append(f"{name}: missing BFRES macro-path bone {path}")

    entries = tuple(dict.fromkeys(entry_points))
    required = tuple(dict.fromkeys(required_locations))
    for entry in entries:
        if entry not in point_names:
            issues.append(f"Missing entry point {entry}")
    for location in required:
        if location not in point_names:
            issues.append(f"Missing required location {location}")
    valid_entries = [entry for entry in entries if entry in adjacency]
    if required and not valid_entries:
        issues.append("No valid entry point for reachability check")
    elif required:
        reachable = set(valid_entries)
        pending = list(valid_entries)
        while pending:
            current = pending.pop()
            for destination in adjacency[current] - reachable:
                reachable.add(destination)
                pending.append(destination)
        for location in required:
            if location in point_names and location not in reachable:
                issues.append(f"Unreachable location {location}")

    return sorted(set(issues))
