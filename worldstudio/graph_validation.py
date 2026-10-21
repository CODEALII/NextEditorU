"""Validation helpers for native overworld point and route tables.

These checks deliberately keep game-specific reachability explicit. Native
point CSVs also contain helper, trigger, and camera points, so callers must
identify the playable entry and required locations instead of treating every
point as a level node.
"""
import json
import re
from pathlib import Path


_POINT_ID = re.compile(r"[WF][A-Za-z0-9]{3}\Z")
_ROUTE_ID = re.compile(r"R[A-Za-z0-9]{8}\Z")
_GRAPH_PROFILE_FORMAT = "nsmbu-world-graph-profile-v1"
_MAX_GRAPH_PROFILE_BYTES = 64 * 1024


def load_native_graph_profile(path, expected_world_prefix=None):
    """Load explicit entry/required nodes for a repeatable static graph check."""
    path = Path(path)

    def reject_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Graph profile contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        with path.open("rb") as source:
            data = source.read(_MAX_GRAPH_PROFILE_BYTES + 1)
        if len(data) > _MAX_GRAPH_PROFILE_BYTES:
            raise ValueError(f"Graph profile exceeds {_MAX_GRAPH_PROFILE_BYTES} bytes")
        profile = json.loads(data.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Graph profile must be valid UTF-8 JSON") from error
    if not isinstance(profile, dict):
        raise ValueError("Graph profile must be a JSON object")
    expected_fields = {"format", "world_prefix", "entry_points", "required_locations"}
    if set(profile) != expected_fields:
        raise ValueError("Graph profile fields must be format, world_prefix, entry_points, and required_locations")
    if profile["format"] != _GRAPH_PROFILE_FORMAT:
        raise ValueError(f"Unsupported graph profile format {profile['format']!r}")
    world_prefix = profile["world_prefix"]
    if not isinstance(world_prefix, str) or not re.fullmatch(r"W[1-9]", world_prefix):
        raise ValueError("Graph profile world_prefix must be W1 through W9")
    if expected_world_prefix and world_prefix != expected_world_prefix:
        raise ValueError(
            f"Graph profile is for {world_prefix}, but the source archive is {expected_world_prefix}")

    result = {"world_prefix": world_prefix}
    for field in ("entry_points", "required_locations"):
        values = profile[field]
        if not isinstance(values, list) or not values or len(values) > 256:
            raise ValueError(f"Graph profile {field} must contain 1 to 256 point IDs")
        if any(not isinstance(value, str) or not _POINT_ID.fullmatch(value) or
               not value.startswith(world_prefix) for value in values):
            raise ValueError(f"Graph profile {field} contains an invalid {world_prefix} point ID")
        if len(set(values)) != len(values):
            raise ValueError(f"Graph profile {field} contains duplicate point IDs")
        result[field] = tuple(values)
    return result


def native_point_path_route_ids(point_rows):
    """Return syntactically valid route IDs listed in native point path fields."""
    route_ids = set()
    for row in point_rows:
        if not isinstance(row, (list, tuple)) or len(row) != 9:
            continue
        for column in (4, 7):
            value = row[column]
            if not isinstance(value, str):
                continue
            route_ids.update(
                token.strip() for token in value.split(",")
                if _ROUTE_ID.fullmatch(token.strip())
            )
    return sorted(route_ids)


def native_route_segment_choices(route_rows, known_references, known_bones,
                                 world_prefix=None, point_rows=()):
    """Return unused BFRES route IDs whose local endpoint bones resolve."""
    references = set(known_references)
    bones = set(known_bones)
    existing = {
        row[0] for row in route_rows
        if (isinstance(row, (list, tuple)) and len(row) == 3 and
            isinstance(row[0], str) and _ROUTE_ID.fullmatch(row[0]))
    }
    candidates = []
    for name in references:
        if not isinstance(name, str) or not _ROUTE_ID.fullmatch(name) or name in existing:
            continue
        endpoints = (name[1:5], name[5:9])
        if all(
                endpoint in bones or
                (world_prefix and endpoint.startswith("W") and
                 not endpoint.startswith(world_prefix))
                for endpoint in endpoints):
            candidates.append(name)
    point_paths = set(native_point_path_route_ids(point_rows))
    return sorted(candidates, key=lambda name: (name not in point_paths, name))


def native_macro_path_choices(known_references, known_bones, world_prefix=None):
    """Return BFRES path IDs whose local endpoint bones resolve."""
    references = set(known_references)
    bones = set(known_bones)
    candidates = []
    for name in references:
        if not isinstance(name, str) or not _ROUTE_ID.fullmatch(name):
            continue
        endpoints = (name[1:5], name[5:9])
        if all(
                endpoint in bones or
                (world_prefix and endpoint.startswith("W") and
                 not endpoint.startswith(world_prefix))
                for endpoint in endpoints):
            candidates.append(name)
    return sorted(candidates)


def build_native_route_row(route_id, road_type, available_route_ids,
                           existing_route_rows=()):
    """Build a route CSV row from an unused, existing BFRES route ID.

    This only constructs the native table record. It does not add BFRES route
    geometry or update point destination/path-chain fields.
    """
    if not isinstance(route_id, str) or not _ROUTE_ID.fullmatch(route_id):
        raise ValueError("Choose an existing BFRES route segment ID")
    if route_id not in set(available_route_ids):
        raise ValueError("Choose an unused route segment found in the current BFRES")
    if not isinstance(road_type, str) or not road_type.strip():
        raise ValueError("Choose a road type found in the current route table")

    for row in existing_route_rows:
        if isinstance(row, (list, tuple)) and row and row[0] == route_id:
            raise ValueError(f"Route segment {route_id} already exists")
    return [route_id, road_type.strip(), ""]


def _tokens(value):
    return [token.strip() for token in value.split(",") if token.strip()]


def _field_changed(row, initial_rows, index, column):
    return (initial_rows is None or index >= len(initial_rows) or
            column >= len(initial_rows[index]) or row[column] != initial_rows[index][column])


def _route_adjacency(route_rows, world_prefix=None):
    """Build the directed graph encoded by native R<start><end> segments."""
    adjacency = {}
    for row in route_rows:
        if (not isinstance(row, (list, tuple)) or len(row) != 3 or
                not isinstance(row[0], str) or not _ROUTE_ID.fullmatch(row[0])):
            continue
        name = row[0]
        start, end = name[1:5], name[5:9]
        if world_prefix and any(endpoint.startswith('W') and
                                not endpoint.startswith(world_prefix)
                                for endpoint in (start, end)):
            continue
        adjacency.setdefault(start, set()).add(end)
    return adjacency


def _route_topology_changed(route_rows, initial_routes):
    """Detect changes to the directed route edges, ignoring display columns."""
    if initial_routes is None:
        return False

    def route_ids(rows):
        return sorted(
            row[0] for row in rows
            if isinstance(row, (list, tuple)) and len(row) == 3 and
            isinstance(row[0], str) and _ROUTE_ID.fullmatch(row[0])
        )

    return route_ids(route_rows) != route_ids(initial_routes)


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


def _macro_path_reaches(path_names, start, target):
    """Check a simple ordered macro chain, skipping ambiguous path lists."""
    segments = []
    for name in path_names:
        if not _ROUTE_ID.fullmatch(name):
            return None
        segments.append((name[1:5], name[5:9]))

    current = start
    ordered = True
    for segment_start, segment_end in segments:
        if segment_start != current:
            ordered = False
            break
        current = segment_end
    if ordered:
        return current == target

    # Some stock records carry multiple branches in one path field. Only call
    # an ordering mismatch when the IDs still describe one unambiguous chain.
    outgoing = {}
    incoming = {}
    for segment_start, segment_end in segments:
        outgoing.setdefault(segment_start, set()).add(segment_end)
        incoming.setdefault(segment_end, set()).add(segment_start)
    if any(len(ends) > 1 for ends in outgoing.values()) or any(
            len(starts) > 1 for starts in incoming.values()):
        return None

    current = start
    used = set()
    while current in outgoing:
        next_nodes = outgoing[current]
        if len(next_nodes) != 1:
            return None
        next_node = next(iter(next_nodes))
        edge = (current, next_node)
        if edge in used:
            return None
        used.add(edge)
        current = next_node
    if len(used) != len(segments):
        return None
    # The segments form a valid chain, but their stored sequence is wrong.
    return False


def native_macro_path_chain_reaches(path_value, start, destinations, known_references):
    """Return static endpoint-chain status for one native point path field.

    True/False means the selected IDs are known and describe the ordered
    source-to-destination chain (or a definitive mismatch). None means the
    available BFRES name inventory or destination list is insufficient.
    This checks encoded names only; it does not establish runtime behavior.
    """
    if not isinstance(path_value, str) or not isinstance(start, str):
        return None
    targets = _tokens(destinations) if isinstance(destinations, str) else []
    if len(targets) != 1 or not _POINT_ID.fullmatch(start) or not _POINT_ID.fullmatch(targets[0]):
        return None
    paths = _tokens(path_value)
    references = set(known_references or ())
    if any(not _ROUTE_ID.fullmatch(path) or path not in references for path in paths):
        return None
    return _macro_path_reaches(paths, start, targets[0])


def _known_local_inventory(point_rows, route_rows, known_references, world_prefix):
    """Check local point and route row structure without rejecting old gaps."""
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
        local_endpoints = (endpoint for endpoint in (row[0][1:5], row[0][5:9])
                           if endpoint.startswith(world_prefix))
        if any(endpoint not in known_references for endpoint in local_endpoints):
            return False

    for row in point_rows:
        for column in (3, 6):
            if not isinstance(row[column], str):
                return False
            for destination in _tokens(row[column]):
                if not _POINT_ID.fullmatch(destination):
                    return False
    return True


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

    When both point and local route rows have valid, locally resolvable
    inventories, newly added same-world destinations must connect through
    directed route segments. A changed single local destination is also checked
    against its paired BFRES macro-path references when those references are
    resolvable. Ambiguous multi-destination legacy rows and cross-world links
    are excluded. If route edges change, existing destinations are rechecked
    only when the baseline already had a path, so pre-existing gaps are not
    misreported.

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
                if (world_prefix and endpoint.startswith('W') and
                        not endpoint.startswith(world_prefix)):
                    continue
                if endpoint not in known_references:
                    issues.append(f"{name}: missing endpoint model reference {endpoint}")

    route_topology_changed = _route_topology_changed(route_rows, initial_routes)
    check_route_connectivity = (
        initial_points is not None and initial_routes is not None and
        len(initial_points) == len(point_rows) and
        _known_local_inventory(initial_points, initial_routes,
                               known_references, world_prefix) and
        _known_local_inventory(point_rows, route_rows,
                               known_references, world_prefix)
    )
    route_adjacency = (_route_adjacency(route_rows, world_prefix)
                       if check_route_connectivity else {})
    initial_route_adjacency = (_route_adjacency(initial_routes, world_prefix)
                               if check_route_connectivity else {})

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
            previous_destination_list = []
            if (initial_points is not None and index < len(initial_points) and
                    isinstance(initial_points[index], (list, tuple)) and
                    len(initial_points[index]) == 9 and initial_points[index][1] == name and
                    isinstance(initial_points[index][column], str)):
                previous_destination_list = _tokens(initial_points[index][column])
            previous_destinations = set(previous_destination_list)
            destinations = _tokens(row[column])
            paired_path_column = column + 1
            paired_path_changed = _field_changed(row, initial_points, index,
                                                 paired_path_column)
            for destination in destinations:
                if not _POINT_ID.fullmatch(destination):
                    if changed_destination_list:
                        issues.append(f"{name}: malformed destination {destination}")
                    continue
                if destination in point_names:
                    adjacency[name].add(destination)
                elif (changed_destination_list and world_prefix and
                      destination.startswith(world_prefix)):
                    issues.append(f"{name}: unresolved local destination {destination}")
                if (check_route_connectivity and world_prefix and
                        name.startswith(world_prefix) and destination.startswith(world_prefix)):
                    newly_added = destination not in previous_destinations
                    had_baseline_path = _reachable(initial_route_adjacency, name, destination)
                    must_recheck = newly_added or (route_topology_changed and had_baseline_path)
                    if must_recheck and not _reachable(route_adjacency, name, destination):
                        issues.append(f"{name}: no directed route-segment path to {destination}")
                    if (len(destinations) == 1 and len(previous_destination_list) <= 1 and
                            (changed_destination_list or paired_path_changed) and
                            name.startswith(world_prefix) and destination in point_names):
                        path_names = _tokens(row[paired_path_column])
                        if not path_names:
                            issues.append(f"{name}: missing BFRES macro-path chain to {destination}")
                        elif all(path in references and _ROUTE_ID.fullmatch(path)
                                 for path in path_names):
                            reaches = _macro_path_reaches(path_names, name, destination)
                            if reaches is False:
                                issues.append(f"{name}: BFRES macro-path chain does not reach {destination}")
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
