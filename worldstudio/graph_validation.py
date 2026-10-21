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


def _route_adjacency(route_rows):
    """Build the directed graph encoded by native R<start><end> segments."""
    adjacency = {}
    for row in route_rows:
        if (not isinstance(row, (list, tuple)) or len(row) != 3 or
                not isinstance(row[0], str) or not _ROUTE_ID.fullmatch(row[0])):
            continue
        name = row[0]
        adjacency.setdefault(name[1:5], set()).add(name[5:9])
    return adjacency


def _reachable(adjacency, start, target):
    pending = [start]
    visited = {start}
    while pending:
        current = pending.pop()
        if current == target:
            return True
        for neighbor in adjacency.get(current, set()) - visited:
            visited.add(neighbor)
            pending.append(neighbor)
    return False


def _known_local_inventory(point_rows, route_rows, known_references, world_prefix):
    """Check that supplied local rows are structurally complete and resolvable."""
    if known_references is None or not world_prefix:
        return False

    point_names = set()
    for row in point_rows:
        if (not isinstance(row, (list, tuple)) or len(row) != 9 or
                not isinstance(row[1], str) or not _POINT_ID.fullmatch(row[1]) or
                row[1] in point_names or row[1] not in known_references):
            return False
        point_names.add(row[1])

    route_names = set()
    for row in route_rows:
        if (not isinstance(row, (list, tuple)) or len(row) != 3 or
                not isinstance(row[0], str) or not _ROUTE_ID.fullmatch(row[0]) or
                row[0] in route_names):
            return False
        route_names.add(row[0])
        if any(endpoint not in known_references for endpoint in
               (row[0][1:5], row[0][5:9])):
            return False

    for row in point_rows:
        for column in (3, 6):
            if not isinstance(row[column], str):
                return False
            for destination in _tokens(row[column]):
                if not _POINT_ID.fullmatch(destination):
                    return False
                if not destination.startswith(world_prefix):
                    continue
                if destination not in point_names:
                    return False
    return True


def _complete_local_inventory(point_rows, route_rows, known_references, world_prefix):
    """Reject partial baselines before using them as route-connectivity oracles.

    Every same-world destination in the baseline must have a directed segment
    path. Cross-world edges are excluded because their route tables live in a
    different archive.
    """
    if not _known_local_inventory(point_rows, route_rows,
                                  known_references, world_prefix):
        return False
    adjacency = _route_adjacency(route_rows)
    return all(
        _reachable(adjacency, row[1], destination)
        for row in point_rows
        for column in (3, 6)
        for destination in _tokens(row[column])
        if destination.startswith(world_prefix)
    )


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

    When complete baseline point and route inventories are available, changed
    same-world destinations must also be connected by directed route segments.
    Cross-world destinations are excluded because their route tables live in a
    different archive.

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

    check_route_connectivity = (
        initial_points is not None and initial_routes is not None and
        len(initial_points) == len(point_rows) and
        _complete_local_inventory(initial_points, initial_routes,
                                  known_references, world_prefix) and
        _known_local_inventory(point_rows, route_rows,
                               known_references, world_prefix)
    )
    route_adjacency = _route_adjacency(route_rows) if check_route_connectivity else {}

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
            changed_destination_list = _field_changed(row, initial_points, index, column)
            for destination in _tokens(row[column]):
                if not _POINT_ID.fullmatch(destination):
                    if changed_destination_list:
                        issues.append(f"{name}: malformed destination {destination}")
                    continue
                if destination in point_names:
                    adjacency[name].add(destination)
                    if (check_route_connectivity and changed_destination_list and
                            name.startswith(world_prefix) and destination.startswith(world_prefix) and
                            not _reachable(route_adjacency, name, destination)):
                        issues.append(f"{name}: no directed route-segment path to {destination}")
                elif (changed_destination_list and world_prefix and
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
