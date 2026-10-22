"""Validation helpers for native overworld point and route tables.

These checks deliberately keep game-specific reachability explicit. Native
point CSVs also contain helper, trigger, and camera points, so callers must
identify the playable entry and required locations instead of treating every
point as a level node.
"""
import hashlib
from collections import Counter, deque
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


def native_road_type_choices(route_rows):
    """Return distinct nonempty road-type values from the source route table."""
    result = []
    seen = set()
    for row in route_rows:
        if (not isinstance(row, (list, tuple)) or len(row) != 3 or
                not isinstance(row[1], str) or not row[1].strip() or row[1] in seen):
            continue
        seen.add(row[1])
        result.append(row[1])
    return result


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


def build_native_connection_draft(point_rows, route_rows, known_references,
                                  known_bones, source_index, target,
                                  destination_kind, road_type, world_prefix):
    """Prepare a non-mutating point/path/route draft from existing BFRES IDs.

    The draft is offered only when endpoint names describe one unique shortest
    path and every missing route-table row can be built from an existing BFRES
    segment. It does not infer game movement or unlock semantics.
    """
    if (type(source_index) is not int or not 0 <= source_index < len(point_rows) or
            not isinstance(world_prefix, str) or not re.fullmatch(r"W[1-9]", world_prefix)):
        raise ValueError("Choose a valid source point and world prefix")
    source = point_rows[source_index]
    if (not isinstance(source, (list, tuple)) or len(source) != 9 or
            not isinstance(source[1], str) or not source[1].startswith(world_prefix)):
        raise ValueError("The source must be a supported point in the selected world")
    source_name = source[1]
    if destination_kind not in ("normal", "secret"):
        raise ValueError("Destination field must be normal or secret")
    target_rows = [row for row in point_rows
                   if isinstance(row, (list, tuple)) and len(row) == 9 and
                   row[1] == target and row[1] != source_name and
                   row[1].startswith(world_prefix)]
    if len(target_rows) != 1:
        raise ValueError("Choose one other point in the same world")

    path_ids = native_macro_path_choices(known_references, known_bones, world_prefix)
    # General path pickers preserve valid links into other worlds. A local
    # connection draft must not route through a remote world because the local
    # route graph deliberately excludes those edges. Keep non-world helper
    # bones (for example F001) while removing segments with foreign W endpoints.
    path_ids = [route_id for route_id in path_ids
                if all(not endpoint.startswith("W") or endpoint.startswith(world_prefix)
                       for endpoint in (route_id[1:5], route_id[5:9]))]
    chain = suggest_native_macro_path_chain(path_ids, source_name, target)
    if not chain:
        raise ValueError("No unique shortest BFRES path chain reaches this destination")

    available = set(native_route_segment_choices(
        route_rows, known_references, known_bones, world_prefix,
        point_rows=point_rows))
    existing = {
        row[0] for row in route_rows
        if isinstance(row, (list, tuple)) and len(row) == 3 and
        isinstance(row[0], str) and _ROUTE_ID.fullmatch(row[0])
    }
    missing = [route_id for route_id in chain if route_id not in existing]
    unavailable = [route_id for route_id in missing if route_id not in available]
    if unavailable:
        raise ValueError("BFRES path rows cannot be safely added: " + ", ".join(unavailable))
    route_drafts = [build_native_route_row(route_id, road_type, available, route_rows)
                    for route_id in missing]
    destination_column = 3 if destination_kind == "normal" else 6
    return {
        "source_index": source_index,
        "source": source_name,
        "target": target,
        "destination_kind": destination_kind,
        "destination_column": destination_column,
        "path_column": destination_column + 1,
        "chain": tuple(chain),
        "route_rows": route_drafts,
    }


def apply_native_connection_draft(point_rows, route_rows, draft):
    """Return copied point/route tables with a validated connection applied.

    The input tables are never mutated. This also rechecks that the draft still
    targets the same point and that every path ID will have a route-table row,
    so callers can replace both tables together as one editor history step.
    """
    if not isinstance(draft, dict):
        raise ValueError("Route connection draft is invalid")
    source_index = draft.get("source_index")
    source_name = draft.get("source")
    target = draft.get("target")
    destination_column = draft.get("destination_column")
    path_column = draft.get("path_column")
    chain = draft.get("chain")
    new_rows = draft.get("route_rows")
    if (type(source_index) is not int or not 0 <= source_index < len(point_rows) or
            not isinstance(source_name, str) or not isinstance(target, str) or
            destination_column not in (3, 6) or path_column != destination_column + 1 or
            not isinstance(chain, (list, tuple)) or not chain or
            any(not isinstance(route_id, str) or not _ROUTE_ID.fullmatch(route_id)
                for route_id in chain) or
            len(set(chain)) != len(chain) or
            not isinstance(new_rows, list)):
        raise ValueError("Route connection draft has invalid fields")
    world_match = re.match(r"W[1-9]", source_name)
    if (not _POINT_ID.fullmatch(source_name) or not _POINT_ID.fullmatch(target) or
            not world_match or not target.startswith(world_match.group(0)) or
            any(endpoint.startswith("W") and
                not endpoint.startswith(world_match.group(0))
                for route_id in chain for endpoint in (route_id[1:5], route_id[5:9]))):
        raise ValueError("Route connection draft leaves its source world")
    source_row = point_rows[source_index]
    if (not isinstance(source_row, (list, tuple)) or len(source_row) != 9 or
            source_row[1] != source_name):
        raise ValueError("Route connection source changed; rebuild the draft")
    if sum(isinstance(row, (list, tuple)) and len(row) == 9 and row[1] == target
           for row in point_rows) != 1:
        raise ValueError("Route connection destination changed; rebuild the draft")
    if _macro_path_reaches(chain, source_name, target) is not True:
        raise ValueError("Route connection path no longer reaches its destination")

    existing = {
        row[0] for row in route_rows
        if isinstance(row, (list, tuple)) and len(row) == 3 and
        isinstance(row[0], str) and _ROUTE_ID.fullmatch(row[0])
    }
    added = set()
    if any(not isinstance(row, (list, tuple)) for row in route_rows):
        raise ValueError("Current route table contains an unsupported row")
    copied_routes = [list(row) for row in route_rows]
    for row in new_rows:
        if (not isinstance(row, (list, tuple)) or len(row) != 3 or
                not isinstance(row[0], str) or not _ROUTE_ID.fullmatch(row[0]) or
                row[0] in existing or row[0] in added or
                not isinstance(row[1], str) or not row[1].strip()):
            raise ValueError("Route connection contains an invalid or duplicate route row")
        added.add(row[0])
        copied_routes.append(list(row))
    if not set(chain).issubset(existing | added):
        raise ValueError("Route connection path is missing one or more route-table rows")

    if any(not isinstance(row, (list, tuple)) for row in point_rows):
        raise ValueError("Current point table contains an unsupported row")
    copied_points = [list(row) for row in point_rows]
    copied_points[source_index][destination_column] = target
    copied_points[source_index][path_column] = ",".join(chain)
    return copied_points, copied_routes


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


def suggest_native_macro_path_chain(path_ids, start, target):
    """Return a unique shortest ordered BFRES path chain, or ``None``.

    The suggestion uses only encoded route endpoints. If more than one
    shortest chain exists, the caller must leave the field unchanged for the
    user to choose; this does not infer which chain the game prefers.
    """
    if (not isinstance(start, str) or not _POINT_ID.fullmatch(start) or
            not isinstance(target, str) or not _POINT_ID.fullmatch(target) or
            start == target):
        return None
    outgoing = {}
    try:
        candidates = iter(path_ids or ())
    except TypeError:
        return None
    seen = set()
    for route_id in candidates:
        if not isinstance(route_id, str) or not _ROUTE_ID.fullmatch(route_id):
            continue
        if route_id in seen:
            continue
        seen.add(route_id)
        outgoing.setdefault(route_id[1:5], []).append((route_id[5:9], route_id))
    for edges in outgoing.values():
        edges.sort()

    distance = {start: 0}
    path_count = {start: 1}
    previous = {}
    queue = deque((start,))
    while queue:
        current = queue.popleft()
        for next_node, route_id in outgoing.get(current, ()):
            next_distance = distance[current] + 1
            if next_node not in distance:
                distance[next_node] = next_distance
                path_count[next_node] = path_count[current]
                previous[next_node] = (current, route_id)
                queue.append(next_node)
            elif distance[next_node] == next_distance:
                path_count[next_node] = min(2, path_count[next_node] + path_count[current])
    if target not in distance or path_count[target] != 1:
        return None
    result = []
    current = target
    while current != start:
        predecessor = previous.get(current)
        if predecessor is None:
            return None
        current, route_id = predecessor
        result.append(route_id)
    result.reverse()
    return result


def native_graph_route_editor_id(route, route_rows, path_ids):
    """Map a displayed point-to-point edge to its first editable route row.

    Graph edges are derived from point CSV destinations, while the route table
    stores BFRES segment IDs. Resolve a unique shortest segment chain and use
    its first segment as the row selection; ambiguous or incomplete chains stay
    unselectable rather than highlighting an unrelated segment.
    """
    if not isinstance(route, dict):
        return ""
    route_index = {
        row[0]: index for index, row in enumerate(route_rows)
        if (isinstance(row, (list, tuple)) and row and
            isinstance(row[0], str) and _ROUTE_ID.fullmatch(row[0]))
    }
    route_id = route.get("id")
    if route_id in route_index:
        return f"segment:{route_index[route_id]}"
    chain = suggest_native_macro_path_chain(
        path_ids, route.get("start"), route.get("end"))
    if not chain:
        return ""
    matched = next((segment for segment in chain if segment in route_index), None)
    return f"segment:{route_index[matched]}" if matched else ""


def native_graph_route_editor_ids(routes, route_rows):
    """Map graph edges to distinct route rows where their chains allow it."""
    route_index = {
        row[0]: index for index, row in enumerate(route_rows)
        if (isinstance(row, (list, tuple)) and row and
            isinstance(row[0], str) and _ROUTE_ID.fullmatch(row[0]))
    }
    segment_ids = list(route_index)
    chains = []
    for route in routes:
        if not isinstance(route, dict):
            chains.append([])
            continue
        direct = route.get("id")
        chain = ([direct] if direct in route_index else
                 suggest_native_macro_path_chain(
                     segment_ids, route.get("start"), route.get("end")) or [])
        chains.append(chain)
    counts = Counter(segment for chain in chains for segment in set(chain))
    editor_ids = []
    for chain in chains:
        matched = next((segment for segment in chain if counts[segment] == 1), None)
        editor_ids.append(f"segment:{route_index[matched]}" if matched else "")
    return editor_ids


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


def graph_profile_record(profile):
    """Return a canonical, hash-addressed record for a loaded graph profile."""
    effective_profile = {
        "format": _GRAPH_PROFILE_FORMAT,
        "world_prefix": profile["world_prefix"],
        "entry_points": list(profile["entry_points"]),
        "required_locations": list(profile["required_locations"]),
    }
    canonical = json.dumps(effective_profile, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    return {
        **effective_profile,
        "profile_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def validate_native_project_profile(project, profile_path):
    """Validate a native project against an explicit profile and describe it."""
    world = re.search(r"pointW([1-9])", getattr(project, "point_name", ""))
    if not world:
        raise ValueError("Cannot match graph profile to the source world")
    world_prefix = f"W{world[1]}"
    profile = load_native_graph_profile(profile_path, world_prefix)
    references = set(project.references)
    for rename in getattr(project, "bone_renames", []):
        references.discard(rename.get("old"))
        if rename.get("new"):
            references.add(rename["new"])
    issues = set(project.validate())
    issues.update(validate_native_world(
        project.points.rows, project.routes.rows, known_references=references,
        initial_points=project.points.initial, initial_routes=project.routes.initial,
        world_prefix=world_prefix,
        entry_points=profile["entry_points"],
        required_locations=profile["required_locations"]))
    record = {
        **graph_profile_record(profile),
        "passed": not issues,
        "scope": "native point/route table reachability; no event or game-state simulation",
    }
    return record, sorted(issues)
