"""Dependency-free 3D inspection/editor shell and native CSV/BFRES editor.

The perspective viewport is an editor preview, never proof of in-game behavior.
OBJ preview import is separate from explicit experimental native mesh replacement.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import queue
import re
import tempfile
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from .bfres import Skeletons
from .gltf import read_glb, read_gltf
from .graph_validation import (
    apply_native_connection_draft,
    build_native_connection_draft,
    build_native_route_row,
    native_macro_path_choices,
    native_macro_path_chain_reaches,
    suggest_native_macro_path_chain,
    native_point_path_route_ids,
    native_road_type_choices,
    native_route_segment_choices,
)
from .mesh import MAX_FACE_CORNERS, transform_obj_geometry
from .recent_projects import RecentProjects
from .graph_profile_preferences import GraphProfilePreferences
from .session_recovery import SessionRecovery, StaleRecoveryError


MAX_OBJ_FILE_BYTES = 64 * 1024 * 1024
MAX_OBJ_LINE_BYTES = 64 * 1024
MAX_OBJ_LINES = 1_000_000
MAX_OBJ_RECORDS = 500_000
MAX_OBJ_FACES = 200_000
MAX_OBJ_TOTAL_FACE_CORNERS = 500_000


def camera_plane_world_delta(dx, dy, yaw, pitch, projection_scale):
    """Map pointer movement onto the camera-facing plane in model coordinates."""
    try:
        dx, dy, yaw, pitch, projection_scale = map(float, (dx, dy, yaw, pitch, projection_scale))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Drag movement must be finite and projection scale positive") from error
    values = (dx, dy, yaw, pitch, projection_scale)
    if not all(math.isfinite(value) for value in values) or projection_scale <= 0:
        raise ValueError("Drag movement must be finite and projection scale positive")
    camera_x, camera_y = dx / projection_scale, -dy / projection_scale
    rotated_z = -math.sin(pitch) * camera_y
    return (
        math.cos(yaw) * camera_x + math.sin(yaw) * rotated_z,
        math.cos(pitch) * camera_y,
        -math.sin(yaw) * camera_x + math.cos(yaw) * rotated_z,
    )


def _rotate_preview_point(point, center, yaw, pitch):
    x, y, z = [float(point[i]) - float(center[i]) for i in range(3)]
    x, z = x * math.cos(yaw) - z * math.sin(yaw), x * math.sin(yaw) + z * math.cos(yaw)
    y, z = y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)
    return x, y, z


def _project_camera_point(x, y, z, view_scale, width, height):
    scale = float(view_scale)
    perspective = scale * 900 / max(100, 900 + z * scale)
    return float(width) / 2 + x * perspective, float(height) / 2 - y * perspective, z


def project_preview_point(point, center, yaw, pitch, view_scale, width, height):
    """Project one model-space point with the native editor's perspective view."""
    camera_point = _rotate_preview_point(point, center, yaw, pitch)
    return _project_camera_point(*camera_point, view_scale, width, height)


def fit_preview_scale(points, center, yaw, pitch, width, height, *, max_scale=8.0):
    """Find the largest perspective scale that keeps points inside the viewport."""
    try:
        center = tuple(float(value) for value in center[:3])
        yaw, pitch, width, height, max_scale = map(float, (yaw, pitch, width, height, max_scale))
    except (TypeError, ValueError, OverflowError, IndexError) as error:
        raise ValueError("Fit view requires finite points, camera values and viewport dimensions") from error
    if (len(center) != 3 or
            not all(math.isfinite(value) for value in (*center, yaw, pitch, width, height, max_scale)) or
            width <= 0 or height <= 0 or max_scale <= 0):
        raise ValueError("Fit view requires finite points, camera values and viewport dimensions")
    low, high = [math.inf] * 3, [-math.inf] * 3
    point_count = 0
    try:
        for point in points:
            values = tuple(float(point[index]) for index in range(3))
            if not all(math.isfinite(value) for value in values):
                raise ValueError("Fit view requires finite points, camera values and viewport dimensions")
            camera_point = _rotate_preview_point(values, center, yaw, pitch)
            for index, value in enumerate(camera_point):
                low[index] = min(low[index], value)
                high[index] = max(high[index], value)
            point_count += 1
    except (TypeError, ValueError, OverflowError, IndexError) as error:
        raise ValueError("Fit view requires finite points, camera values and viewport dimensions") from error
    if point_count == 0:
        return 1.0
    bounds_corners = [(x, y, z) for x in (low[0], high[0])
                      for y in (low[1], high[1]) for z in (low[2], high[2])]
    margin = min(56.0, max(18.0, min(width, height) * 0.06))
    half_width = max(1.0, width / 2 - margin)
    half_height = max(1.0, height / 2 - margin)

    def fits(view_scale):
        for camera_point in bounds_corners:
            x, y, _ = _project_camera_point(*camera_point, view_scale, width, height)
            if not math.isfinite(x) or not math.isfinite(y):
                return False
            if abs(x - width / 2) > half_width or abs(y - height / 2) > half_height:
                return False
        return True

    low, high = 0.0001, max_scale
    if not fits(low):
        return low
    if fits(high):
        return high
    for _ in range(48):
        middle = (low + high) / 2
        if fits(middle):
            low = middle
        else:
            high = middle
    return low


def read_obj(path, include_attributes=False, include_report=False):
    """Read a bounded Wavefront OBJ and optionally report ignored features."""
    path = Path(path)
    if path.stat().st_size > MAX_OBJ_FILE_BYTES:
        raise ValueError(f"OBJ exceeds the {MAX_OBJ_FILE_BYTES // (1024 * 1024)} MiB file-size limit")
    vertices, texcoords, source_normals, raw_faces = [], [], [], []
    compatibility_warnings = set()
    total_face_corners = 0
    bytes_read = 0

    def finish(mesh):
        return (mesh, tuple(sorted(compatibility_warnings))) if include_report else mesh

    def resolve(raw, values, label):
        if not raw:
            return None
        index = int(raw)
        if index == 0:
            raise ValueError(f"OBJ {label} indices start at one")
        index = index - 1 if index > 0 else len(values) + index
        if not 0 <= index < len(values):
            raise ValueError(f"OBJ face references a missing {label}")
        return index

    with path.open("rb") as stream:
        for line_number, raw_line in enumerate(stream, 1):
            if line_number > MAX_OBJ_LINES:
                raise ValueError(f"OBJ exceeds the {MAX_OBJ_LINES:,} line limit")
            bytes_read += len(raw_line)
            if bytes_read > MAX_OBJ_FILE_BYTES:
                raise ValueError(f"OBJ exceeds the {MAX_OBJ_FILE_BYTES // (1024 * 1024)} MiB file-size limit")
            if len(raw_line) > MAX_OBJ_LINE_BYTES:
                raise ValueError(f"OBJ line {line_number} exceeds the {MAX_OBJ_LINE_BYTES // 1024} KiB line limit")
            try:
                line = raw_line.decode("utf-8-sig" if line_number == 1 else "utf-8")
            except UnicodeDecodeError as error:
                raise ValueError(f"OBJ line {line_number} is not valid UTF-8 text") from error
            fields = line.split("#", 1)[0].split()
            if not fields:
                continue
            if fields[0] == "v":
                if len(fields) >= 7:
                    compatibility_warnings.add("OBJ vertex colors are ignored")
                if len(vertices) >= MAX_OBJ_RECORDS:
                    raise ValueError(f"OBJ exceeds the {MAX_OBJ_RECORDS:,} vertex-record limit")
                xyz = tuple(float(value) for value in fields[1:4])
                if len(xyz) != 3 or not all(math.isfinite(value) and abs(value) <= 1e7 for value in xyz):
                    raise ValueError("OBJ vertex must contain three finite coordinates within ±10,000,000")
                vertices.append(xyz)
            elif fields[0] == "vt":
                if len(texcoords) >= MAX_OBJ_RECORDS:
                    raise ValueError(f"OBJ exceeds the {MAX_OBJ_RECORDS:,} texture-coordinate-record limit")
                uv = tuple(float(value) for value in fields[1:3])
                if len(uv) != 2 or not all(math.isfinite(value) and abs(value) <= 1e5 for value in uv):
                    raise ValueError("OBJ texture coordinate must contain two finite values within ±100,000")
                texcoords.append(uv)
            elif fields[0] == "vn":
                if len(source_normals) >= MAX_OBJ_RECORDS:
                    raise ValueError(f"OBJ exceeds the {MAX_OBJ_RECORDS:,} normal-record limit")
                normal = tuple(float(value) for value in fields[1:4])
                if len(normal) != 3 or not all(math.isfinite(value) and abs(value) <= 1e7 for value in normal):
                    raise ValueError("OBJ normal must contain three finite coordinates")
                source_normals.append(normal)
            elif fields[0] == "f":
                corner_count = len(fields) - 1
                if corner_count > MAX_FACE_CORNERS:
                    raise ValueError(f"OBJ face exceeds the {MAX_FACE_CORNERS}-corner limit")
                if len(raw_faces) >= MAX_OBJ_FACES:
                    raise ValueError(f"OBJ exceeds the {MAX_OBJ_FACES:,} face limit")
                total_face_corners += corner_count
                if total_face_corners > MAX_OBJ_TOTAL_FACE_CORNERS:
                    raise ValueError(f"OBJ exceeds the {MAX_OBJ_TOTAL_FACE_CORNERS:,} total face-corner limit")
                face = []
                for item in fields[1:]:
                    parts = item.split("/")
                    if len(parts) > 3 or not parts[0]:
                        raise ValueError("Invalid OBJ face corner")
                    face.append((resolve(parts[0], vertices, "vertex"),
                                 resolve(parts[1] if len(parts) > 1 else "", texcoords, "texture"),
                                 resolve(parts[2] if len(parts) > 2 else "", source_normals, "normal")))
                if len(face) < 3:
                    raise ValueError("OBJ face must contain at least three vertices")
                raw_faces.append(tuple(face))
            elif fields[0] in {"mtllib", "usemtl"}:
                compatibility_warnings.add(
                    "OBJ material libraries and assignments are ignored; the preview or replacement uses one existing material")
            elif fields[0] in {"o", "g"}:
                compatibility_warnings.add(
                    "OBJ object and group boundaries are merged into one mesh")
            elif fields[0] == "s":
                compatibility_warnings.add(
                    "OBJ smoothing groups are ignored; missing normals use generated smooth normals")
            elif fields[0] in {"l", "p", "curv", "curv2", "surf", "parm", "trim", "hole", "scrv", "sp"}:
                compatibility_warnings.add(
                    "Non-polygon OBJ geometry records are ignored; only polygon faces are imported")
    if not vertices or not raw_faces:
        raise ValueError("OBJ needs vertices and polygon faces")
    if not include_attributes:
        return finish((vertices, [tuple(corner[0] for corner in face) for face in raw_faces]))
    # BFRES stores one attribute set per vertex; OBJ permits independent corner attributes.
    split_vertices, split_uvs, split_normals, faces, remap = [], [], [], [], {}
    for face in raw_faces:
        split_face = []
        for position, uv, normal in face:
            key = position, uv, normal
            if key not in remap:
                if len(split_vertices) >= MAX_OBJ_RECORDS:
                    raise ValueError(f"OBJ exceeds the {MAX_OBJ_RECORDS:,} attribute-split vertex limit")
                remap[key] = len(split_vertices)
                split_vertices.append(vertices[position])
                split_uvs.append(texcoords[uv] if uv is not None else None)
                split_normals.append(source_normals[normal] if normal is not None else None)
            split_face.append(remap[key])
        faces.append(tuple(split_face))
    return finish((split_vertices, faces, split_uvs, split_normals))


def read_import_mesh(path, *, include_attributes=False, include_report=False):
    """Read a bounded OBJ, GLB, or local-buffer glTF mesh through one editor path."""
    path = Path(path)
    if path.suffix.lower() in (".glb", ".gltf"):
        reader = read_glb if path.suffix.lower() == ".glb" else read_gltf
        geometry, warnings = reader(path, include_report=True)
        if not include_attributes:
            geometry = geometry[:2]
        return (geometry, warnings) if include_report else geometry
    if path.suffix.lower() == ".obj":
        return read_obj(path, include_attributes=include_attributes,
                        include_report=include_report)
    raise ValueError("Only Wavefront OBJ, Binary glTF (.glb), and local-buffer glTF (.gltf) meshes are supported")


def obj_geometry_summary(vertices, faces):
    """Describe OBJ source counts without implying native export support."""
    label = "face" if len(faces) == 1 else "faces"
    return f"{len(vertices):,} vertices · {len(faces):,} polygon {label}"


def apply_obj_transform(geometry, settings):
    vertices, faces, uvs, normals = geometry
    return transform_obj_geometry(vertices, faces, uvs, normals, **settings)


def normalize_obj_transform(settings):
    """Validate and normalize a saved preview project's mesh conversion."""
    keys = ("scale", "rotation_degrees", "translation")
    if not isinstance(settings, dict) or set(settings) != set(keys):
        raise ValueError("terrain_transform must contain scale, rotation_degrees and translation")
    limits = {"scale": 1e4, "rotation_degrees": 36000., "translation": 1e5}
    normalized = {}
    for key in keys:
        values = settings[key]
        if not isinstance(values, (list, tuple)) or len(values) != 3:
            raise ValueError(f"terrain_transform {key} must contain three numbers")
        if any(type(value) not in (int, float) or not math.isfinite(value) or
               abs(value) > limits[key] for value in values):
            raise ValueError(f"terrain_transform {key} must be finite and within ±{limits[key]:g}")
        normalized[key] = tuple(float(value) for value in values)
    if any(abs(value) < 1e-12 for value in normalized["scale"]):
        raise ValueError("terrain_transform scale components must be nonzero")
    return normalized


def obj_transform_summary(settings):
    identity = {"scale": (1., 1., 1.), "rotation_degrees": (0., 0., 0.),
                "translation": (0., 0., 0.)}
    if settings == identity:
        return "source coordinates"
    scale = ", ".join(f"{value:g}" for value in settings["scale"])
    rotation = ", ".join(f"{value:g}°" for value in settings["rotation_degrees"])
    translation = ", ".join(f"{value:g}" for value in settings["translation"])
    return f"scale ({scale}), rotation ({rotation}), offset ({translation})"


def demo_project():
    return {"format": "worldstudio-preview-v1", "nodes": [
        {"id": "A", "x": -120, "y": 12, "z": 0, "level": "01-01"},
        {"id": "B", "x": 0, "y": 30, "z": -30, "level": "01-02"},
        {"id": "C", "x": 120, "y": 12, "z": 30, "level": "01-03"}],
        "routes": [{"id": "AB", "start": "A", "end": "B", "unlock": "clear A"},
                   {"id": "BC", "start": "B", "end": "C", "unlock": "clear B"}],
        "camera": {"yaw": -0.55, "pitch": 0.65, "scale": 1.0},
        "terrain": str(Path(__file__).resolve().parents[1] / "assets" / "island.obj")}


def validate_preview(project):
    if not isinstance(project, dict):
        return ["Project must be a JSON object"]
    if not isinstance(project.get("nodes"), list) or not isinstance(project.get("routes"), list):
        return ["Project must contain node and route lists"]
    if not all(isinstance(item, dict) for item in project["nodes"] + project["routes"]):
        return ["Nodes and routes must be objects"]
    issues, ids = [], set()
    if "terrain_transform" in project:
        try:
            normalize_obj_transform(project["terrain_transform"])
        except (TypeError, ValueError, OverflowError) as error:
            issues.append(f"Invalid terrain transform: {error}")
    for node in project.get("nodes", []):
        name = node.get("id", "")
        if not isinstance(name, str) or not name.strip():
            issues.append("Node identifier must be a nonempty string")
        elif name in ids:
            issues.append(f"Duplicate node: {name}")
        else:
            ids.add(name)
        if not all(type(node.get(k)) in (int, float) and math.isfinite(node[k]) for k in ("x", "y", "z")):
            issues.append(f"Invalid coordinates: {name}")
    adjacency = {name: set() for name in ids}
    route_ids = set()
    for route in project.get("routes", []):
        route_id = route.get("id", "")
        if not isinstance(route_id, str) or not route_id.strip():
            issues.append("Route identifier must be a nonempty string")
        elif route_id in route_ids:
            issues.append(f"Duplicate route: {route_id}")
        else:
            route_ids.add(route_id)
        a, b = route.get("start"), route.get("end")
        if not isinstance(a, str) or not isinstance(b, str) or a not in ids or b not in ids:
            issues.append(f"Missing route endpoint: {route_id}")
        elif a == b:
            issues.append(f"Self route: {route_id}")
        else:
            adjacency[a].add(b)
            adjacency[b].add(a)
    if ids:
        visited, pending = set(), [next(iter(ids))]
        while pending:
            current = pending.pop()
            if current not in visited:
                visited.add(current)
                pending.extend(adjacency[current] - visited)
        if ids - visited:
            issues.append("Disconnected nodes: " + ", ".join(sorted(ids - visited)))
    return issues


class EditHistory:
    """Bounded cursor over caller-owned snapshots for editor undo and redo."""

    def __init__(self, initial_state, limit=32):
        self.limit = max(2, int(limit))
        self.states = [initial_state]
        self.index = 0

    @property
    def can_undo(self):
        return self.index > 0

    @property
    def can_redo(self):
        return self.index < len(self.states) - 1

    def push(self, state):
        del self.states[self.index + 1:]
        self.states.append(state)
        if len(self.states) > self.limit:
            del self.states[:len(self.states) - self.limit]
        self.index = len(self.states) - 1

    def reset(self, state):
        self.states = [state]
        self.index = 0

    def undo(self):
        if not self.can_undo:
            return None
        self.index -= 1
        return self.states[self.index]

    def redo(self):
        if not self.can_redo:
            return None
        self.index += 1
        return self.states[self.index]


class WorldStudio(ttk.Frame):
    """Visual preview editor; native archive actions may be supplied by a caller."""

    def __init__(self, master, project=None):
        super().__init__(master)
        self.pack(fill="both", expand=True)
        self.project = copy.deepcopy(project or demo_project())
        self.project_path = None
        self.recent_projects = RecentProjects()
        self.recovery_store = SessionRecovery()
        self._recovery_project_path = None
        self._recovery_baseline_sha256 = None
        self._recovery_after_id = None
        self.recovery_delay_ms = 750
        self.dirty = False
        self.mesh = ([], [])
        self.selected = None
        self.properties = {}
        self.hit_points = []
        self.drag = None
        self.center = (0, 0, 0)
        self.status = tk.StringVar(value="Editor preview • game behavior has not been verified")
        self.preview_scene = None
        self.preview_widget = None
        self._preview_update_after = None
        self._preview_poll_after = None
        self._preview_open_after = None
        self._preview_building = False
        self._webview_error = None
        self._preview_geometry_signature = None
        self._embedded_preview_dir = None
        self._embedded_preview_revision = 0
        self._webview_host = None
        self._runtime_cleanup_done = False
        self._build()
        self._load_mesh()
        self.refresh()
        self.history = EditHistory(self._capture_edit_state())
        self._sync_history_buttons()
        self.master.bind("<Control-z>", self._undo_shortcut)
        self.master.bind("<Control-y>", self._redo_shortcut)
        self.master.bind("<Control-Shift-Z>", self._redo_shortcut)
        master.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self):
        self.master.title("NSMBU World Studio — preview editor")
        width = max(1040, min(1440, self.master.winfo_screenwidth() - 72))
        height = max(680, min(920, self.master.winfo_screenheight() - 112))
        self.master.geometry(f"{width}x{height}")
        self.master.minsize(min(width, 1040), min(height, 680))
        self.master.configure(background="#0f1720")
        style = ttk.Style(self.master)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("Segoe UI", 10))
        style.configure("TFrame", background="#0f1720")
        style.configure("TLabel", background="#0f1720", foreground="#e4edf5")
        style.configure("TButton", background="#1a2a38", foreground="#e7eff6",
                        bordercolor="#334a5d", padding=(9, 6), relief="flat")
        style.map("TButton", background=[("active", "#29445a"), ("disabled", "#1a222b")],
                  foreground=[("disabled", "#8090a0")])
        style.configure("TCheckbutton", background="#0f1720", foreground="#d8e3ec")
        style.map("TCheckbutton", background=[("active", "#0f1720")])
        style.configure("TEntry", fieldbackground="#172330", foreground="#edf4fa",
                        insertcolor="#edf4fa", bordercolor="#34495c")
        style.configure("TCombobox", fieldbackground="#172330", foreground="#edf4fa",
                        arrowcolor="#d9e4ed")
        style.configure("Treeview", background="#121e29", fieldbackground="#121e29",
                        foreground="#dce7f0", rowheight=26, bordercolor="#263746")
        style.map("Treeview", background=[("selected", "#1e5860")],
                  foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background="#1b2b39", foreground="#d9e6f0",
                        relief="flat", padding=(6, 7))
        style.map("Treeview.Heading", background=[("active", "#263d4f")])
        style.configure("TScale", background="#0f1720", troughcolor="#263747")
        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        for title, action in [("New preview", self.new), ("Open project", self.open),
                              ("Recent", self.show_recent_projects),
                              ("Save project", self.save), ("Import OBJ/glTF", self.import_obj),
                              ("Add node", self.add_node), ("Add route", self.add_route),
                              ("Delete selected", self.delete), ("Validate", self.validate),
                              ("Refresh 3D", self.open_3d_preview), ("Fit view", self.fit)]:
            button = ttk.Button(bar, text=title, command=action)
            button.pack(side="left", padx=2)
            if title == "Recent":
                self.recent_button = button
        history_bar = ttk.Frame(self, padding=(8, 0, 8, 4))
        history_bar.pack(fill="x")
        self.undo_button = ttk.Button(history_bar, text="Undo  Ctrl+Z", command=self.undo, state="disabled")
        self.undo_button.pack(side="left", padx=2)
        self.redo_button = ttk.Button(history_bar, text="Redo  Ctrl+Y", command=self.redo, state="disabled")
        self.redo_button.pack(side="left", padx=2)
        self.viewport_hint = ttk.Label(self, text="3D world viewport · drag to orbit · right-drag to pan · wheel to zoom · select points in the viewport or list.", padding=(10, 5), foreground="#9fb4c7")
        self.viewport_hint.pack(fill="x")
        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8)
        # Keep WebGL and the editable graph visible together. A Notebook made
        # the primary viewport easy to leave behind and hid graph context;
        # this nested splitter makes the 3D world a persistent editor pane.
        self.view_split = ttk.Panedwindow(body, orient="horizontal")
        self.viewport_pane = ttk.Frame(self.view_split)
        self.graph_frame = ttk.Frame(self.view_split)
        ttk.Label(self.viewport_pane, text="3D WORLD", padding=(8, 5),
                  foreground="#9fb4c7").pack(fill="x")
        ttk.Label(self.graph_frame, text="GRAPH EDITOR", padding=(8, 5),
                  foreground="#9fb4c7").pack(fill="x")
        self.viewport_frame = ttk.Frame(self.viewport_pane)
        self.viewport_frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.graph_frame, background="#101d29", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self._build_embedded_viewport()
        self.view_split.add(self.viewport_pane, weight=3)
        self.view_split.add(self.graph_frame, weight=2)
        self._view_split_positioned = False
        self.view_split.bind("<Map>", self._position_initial_view_split, add="+")
        body.add(self.view_split, weight=4)
        sidebar = ttk.Frame(body, width=370)
        body.add(sidebar, weight=1)
        sidebar_canvas = tk.Canvas(sidebar, width=350, highlightthickness=0, background="#0f1720")
        sidebar_canvas.pack(side="left", fill="both", expand=True)
        sidebar_scroll = ttk.Scrollbar(sidebar, orient="vertical", command=sidebar_canvas.yview)
        sidebar_scroll.pack(side="right", fill="y")
        sidebar_canvas.configure(yscrollcommand=sidebar_scroll.set)
        panel = ttk.Frame(sidebar_canvas, padding=14)
        panel_window = sidebar_canvas.create_window(0, 0, window=panel, anchor="nw")
        panel.bind("<Configure>", lambda event: sidebar_canvas.configure(scrollregion=sidebar_canvas.bbox("all")))
        sidebar_canvas.bind("<Configure>", lambda event: sidebar_canvas.itemconfigure(panel_window, width=event.width))
        ttk.Label(panel, text="Nodes and routes", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        filter_row = ttk.Frame(panel)
        filter_row.pack(fill="x", pady=(8, 2))
        ttk.Label(filter_row, text="Filter IDs").pack(side="left", padx=(0, 8))
        self.tree_filter_var = tk.StringVar(master=self.master, value="")
        self.tree_filter_entry = ttk.Entry(filter_row, textvariable=self.tree_filter_var)
        self.tree_filter_entry.pack(side="left", fill="x", expand=True)
        self.tree_filter_entry.bind("<KeyRelease>", lambda event: self.refresh())
        ttk.Button(filter_row, text="×", width=3, command=self.clear_tree_filter).pack(side="left", padx=(4, 0))
        self.tree_filter_status = ttk.Label(panel, text="", foreground="#91a8ba")
        self.tree_filter_status.pack(anchor="w", pady=(0, 4))
        tree_frame = ttk.Frame(panel)
        tree_frame.pack(fill="x", pady=8)
        self.tree = ttk.Treeview(tree_frame, columns=("type",), show="tree headings", height=12)
        self.tree.heading("#0", text="Identifier")
        self.tree.heading("type", text="Type")
        self.tree.column("#0", width=150)
        self.tree.column("type", width=75)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        tree_scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self.select_tree)
        self.form = ttk.Frame(panel)
        self.form.pack(fill="x")
        ttk.Button(panel, text="Apply selected properties", command=self.apply).pack(fill="x", pady=8)
        ttk.Label(panel, text="Graph camera", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(12, 4))
        for key, start, stop in [("yaw", -math.pi, math.pi), ("pitch", -1.3, 1.3)]:
            ttk.Label(panel, text=key.title()).pack(anchor="w")
            slider = ttk.Scale(panel, from_=start, to=stop,
                               command=lambda value, k=key: self.camera_change(k, value))
            slider.set(self.project.get("camera", {}).get(key, 0.6))
            slider.pack(fill="x")
        self.description = ttk.Label(panel, wraplength=300, text="Node level and route unlock fields describe the preview only. "
                  "Use the verified native resource tools for game-compatible archive modifications.")
        self.description.pack(fill="x", pady=12)
        ttk.Label(self, textvariable=self.status, padding=8).pack(fill="x")
        self.canvas.bind("<Configure>", lambda event: self.draw())
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.orbit)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<MouseWheel>", self.zoom)

    def _position_initial_view_split(self, _event=None):
        if self._view_split_positioned:
            return
        self._view_split_positioned = True
        self.after_idle(self._set_initial_view_split)

    def _set_initial_view_split(self):
        width = self.view_split.winfo_width()
        if width > 1:
            try:
                self.view_split.sashpos(0, int(width * 0.64))
            except tk.TclError:
                pass

    def clear_tree_filter(self):
        self.tree_filter_var.set("")
        self.refresh()

    def _build_embedded_viewport(self):
        """Reserve a persistent viewport and create WebView2 only when shown."""
        self.viewport_frame.configure(style="TFrame")
        self._viewport_placeholder = ttk.Label(
            self.viewport_frame, text="Preparing the local 3D world viewport…",
            justify="center", anchor="center")
        self._viewport_placeholder.pack(fill="both", expand=True)
        self.viewport_frame.bind("<Map>", self._on_viewport_mapped, add="+")

    def _ensure_embedded_view(self):
        if self.preview_widget or self._webview_error:
            return
        try:
            from tkwry import WebView
        except ImportError:
            self._webview_error = "tkwry is not installed"
            self._viewport_placeholder.configure(text=(
                "Embedded 3D needs the optional tkwry WebView2 host.\n"
                "Install it with: python -m pip install -r requirements.txt\n"
                "The renderer stays available through Open external preview."),
            )
            return
        self._viewport_placeholder.destroy()
        self._embedded_preview_dir = tempfile.TemporaryDirectory(prefix="nsmbu-worldstudio-view-")
        preview_dir = Path(self._embedded_preview_dir.name)
        (preview_dir / "index.html").write_text(
            "<!doctype html><html><body style='margin:0;background:#101923;color:#b8c9d7;font:14px Segoe UI'>Loading world viewport…</body></html>",
            encoding="utf-8")
        # tkwry.pack() manages its host frame. Isolate it in a child frame so
        # it cannot replace the viewport pane's geometry manager.
        self._webview_host = ttk.Frame(self.viewport_frame)
        self._webview_host.pack(fill="both", expand=True)
        self.preview_widget = WebView(
            self._webview_host,
            app=preview_dir, width=640, height=480, ephemeral=True, default_context_menus=False,
            on_new_window=lambda _event: __import__("tkwry").NewWindowResponse.Deny)
        self.preview_widget.pack(fill="both", expand=True)
        self.preview_widget.when_failed(self._embedded_view_failed)
        self.preview_widget.rpc("select_item", run_in="main")(self._on_viewport_select)
        self.preview_widget.rpc("move_item", run_in="main")(self._on_viewport_move)

    def _on_viewport_mapped(self, _event=None):
        self._ensure_embedded_view()
        if hasattr(self, "native") and self.preview_scene is None and not self._preview_building:
            self._schedule_embedded_preview_build()

    def _schedule_embedded_preview_build(self):
        if self._preview_open_after is None and not self._runtime_cleanup_done:
            self._preview_open_after = self.after_idle(self._run_scheduled_preview_build)

    def _run_scheduled_preview_build(self):
        self._preview_open_after = None
        if not self._runtime_cleanup_done:
            self.open_3d_preview()

    def _embedded_view_failed(self, error):
        self._webview_error = str(error)
        self.status.set(f"Embedded viewport unavailable: {error}")
        if self.preview_widget:
            try:
                self.preview_widget.destroy()
            except Exception:
                pass
            self.preview_widget = None
        if self._webview_host:
            try:
                self._webview_host.destroy()
            except tk.TclError:
                pass
            self._webview_host = None
        ttk.Label(
            self.viewport_frame,
            text=("The embedded WebView2 viewport could not start.\n"
                  "The external WebGL preview remains available from the toolbar.\n\n"
                  f"{error}"),
            justify="center", anchor="center", wraplength=640).pack(fill="both", expand=True)

    def _on_viewport_select(self, payload):
        """Route a WebGL click back through the same editor selection model."""
        if not isinstance(payload, dict):
            return
        iid = payload.get("editorId")
        if not isinstance(iid, str) or not self.tree.exists(iid):
            return
        self.tree.selection_set(iid)
        self.tree.see(iid)
        self.select_tree()

    def _on_viewport_move(self, payload):
        """Commit one 3D point drag through the native world/local edit model."""
        if getattr(self, "exporting", False) or not isinstance(payload, dict):
            return False
        editor_id = payload.get("editorId")
        position = payload.get("position")
        if (not isinstance(editor_id, str) or not editor_id.startswith("point:") or
                not isinstance(position, (list, tuple)) or len(position) != 3):
            return False
        try:
            index = int(editor_id.partition(":")[2])
            rows = self.native.points.rows
            if index < 0 or index >= len(rows) or len(rows[index]) < 2:
                return False
            target = [float(value) for value in position]
            if not all(math.isfinite(value) and abs(value) <= 1e7 for value in target):
                raise ValueError("Dragged world coordinates must be finite and within ±10,000,000")
            name = rows[index][1]
            node = next((item for item in self.project["nodes"] if item["id"] == name), None)
            preview_only = bool(node and node.get("fallback")) or name not in self.native.positions
            if preview_only:
                self.native.layout[name] = target
                mode = "editor layout only"
            else:
                converter = getattr(self.native.skeletons, "local_position_for_world", None)
                if converter is not None:
                    local = converter(self.native.path_model, name, target,
                                      overrides=self.native.positions)
                else:
                    bone = next((item for item in self.native.skeletons.models[self.native.path_model]
                                 if item.name == name), None)
                    if bone is None or bone.parent != -1:
                        raise ValueError("This point's hierarchy transform cannot be inverted safely")
                    local = target
                local = [float(value) for value in local]
                if not all(math.isfinite(value) and abs(value) <= 1e7 for value in local):
                    raise ValueError("Converted BFRES local coordinates exceed the supported range")
                self.native.positions[name] = local
                mode = "BFRES local XYZ"
            self._auto_fit = False
            self.dirty = True
            self._record_edit()
            self.refresh()
            iid = f"point:{index}"
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
                self.tree.see(iid)
                self.select_tree()
            self.status.set(f"Moved {name} in the 3D viewport · {mode}; undo is available")
            return True
        except (ValueError, KeyError, TypeError, OverflowError, IndexError) as error:
            # WebGL applies a drag optimistically while the pointer is down.
            # If native validation rejects the committed world/local transform,
            # rebuild its overlays from the authoritative editor model so the
            # embedded viewport cannot remain visually ahead of the document.
            self._schedule_viewport_overlay_update()
            self.status.set(f"Cannot move 3D point: {error}")
            return False

    def _sync_viewport_selection(self):
        if not self.preview_widget or not self.preview_widget.ready:
            return
        selection = self.tree.selection()
        iid = selection[0] if selection else ""
        self.preview_widget.eval_js(
            "window.worldStudioView && window.worldStudioView.selectEditorItem(" +
            json.dumps(iid) + ");")

    def _schedule_viewport_overlay_update(self):
        if not getattr(self, "native", None) or not self.preview_scene or not self.preview_widget:
            return
        if self._preview_update_after is not None:
            try:
                self.after_cancel(self._preview_update_after)
            except tk.TclError:
                pass
        self._preview_update_after = self.after(35, self._update_viewport_overlays)

    def _update_viewport_overlays(self):
        self._preview_update_after = None
        if not self.preview_scene or not self.preview_widget or not self.preview_widget.ready:
            return
        graph = self.view_project()
        nodes = []
        point_index = {row[1]: i for i, row in enumerate(self.native.points.rows) if len(row) > 1}
        for node in graph["nodes"]:
            if node.get("fallback"):
                continue
            item = {key: node[key] for key in ("id", "x", "y", "z")}
            index = point_index.get(node["id"])
            item["editorId"] = f"point:{index}" if index is not None else f"bone:{node['id']}"
            nodes.append(item)
        routes = []
        route_by_pair = {}
        for index, row in enumerate(self.native.routes.rows):
            if row and len(row[0]) == 9 and row[0].startswith("R"):
                route_by_pair[(row[0][1:5], row[0][5:9])] = (f"segment:{index}", row[0])
        for route in graph["routes"]:
            route_copy = dict(route)
            route_copy["editorId"] = route.get("editorId", "")
            match = route_by_pair.get((route.get("start"), route.get("end")))
            if match:
                route_copy["editorId"], route_copy["id"] = match
            routes.append(route_copy)
        payload = json.dumps({"nodes": nodes, "routes": routes}, ensure_ascii=True, separators=(",", ":"))
        self.preview_widget.eval_js("window.worldStudioView && window.worldStudioView.updateOverlays(" + payload + ");")
        self._sync_viewport_selection()

    def _tree_filter_matches(self, name, kind):
        query = self.tree_filter_var.get().strip().casefold()
        return not query or query in str(name).casefold() or query in str(kind).casefold()

    def _finish_tree_refresh(self, selection, shown, total):
        if selection and self.tree.exists(selection[0]):
            self.tree.selection_set(selection[0])
            self.tree.see(selection[0])
        else:
            current_selection = self.tree.selection()
            if current_selection:
                self.tree.selection_remove(*current_selection)
            self.selected = None
            if hasattr(self, "native_selection"):
                self.native_selection = None
            if hasattr(self, "position_properties"):
                self.position_properties = {}
            for child in self.form.winfo_children():
                child.destroy()
            self.properties = {}
        query = self.tree_filter_var.get().strip()
        self.tree_filter_status.configure(
            text=f"Showing {shown:,} of {total:,} items" if query else f"{total:,} items")

    def _capture_edit_state(self):
        if hasattr(self, "native"):
            native = self.native
            return {
                "kind": "native",
                "points": copy.deepcopy(native.points.rows),
                "routes": copy.deepcopy(native.routes.rows),
                "positions": copy.deepcopy(native.positions),
                "object_positions": copy.deepcopy(getattr(native, "object_positions", {})),
                "object_rotations": copy.deepcopy(getattr(native, "object_rotations", {})),
                "object_scales": copy.deepcopy(getattr(native, "object_scales", {})),
                "layout": copy.deepcopy(native.layout),
                "terrain": native.terrain,
                "geometry": native.geometry,
                "bone_renames": copy.deepcopy(getattr(native, "bone_renames", [])),
                "camera_edits": copy.deepcopy(getattr(native, "camera_edits", {})),
                "mesh": self.mesh,
            }
        project = copy.deepcopy(self.project)
        project.pop("camera", None)
        return {"kind": "preview", "project": project, "mesh": self.mesh}

    def _record_edit(self):
        self.history.push(self._capture_edit_state())
        self._sync_history_buttons()
        self._schedule_recovery()

    def _reset_edit_history(self):
        self.history.reset(self._capture_edit_state())
        self._sync_history_buttons()

    def _sync_history_buttons(self):
        if not hasattr(self, "history"):
            return
        if hasattr(self, "undo_button") and self.undo_button.winfo_exists():
            self.undo_button.configure(state="normal" if self.history.can_undo else "disabled")
        if hasattr(self, "redo_button") and self.redo_button.winfo_exists():
            self.redo_button.configure(state="normal" if self.history.can_redo else "disabled")

    def _undo_shortcut(self, event=None):
        self.undo()
        return "break"

    def _redo_shortcut(self, event=None):
        self.redo()
        return "break"

    def _restore_edit_state(self, state, action):
        if getattr(self, "exporting", False):
            return
        previous_mesh = self.mesh
        if state["kind"] == "native":
            native = self.native
            native.points.rows = copy.deepcopy(state["points"])
            native.routes.rows = copy.deepcopy(state["routes"])
            native.positions = copy.deepcopy(state["positions"])
            native.object_positions = copy.deepcopy(
                state.get("object_positions", getattr(native, "object_positions", {})))
            native.object_rotations = copy.deepcopy(
                state.get("object_rotations", getattr(native, "object_rotations", {})))
            native.object_scales = copy.deepcopy(
                state.get("object_scales", getattr(native, "object_scales", {})))
            native.layout = copy.deepcopy(state["layout"])
            native.terrain = state["terrain"]
            native.geometry = state["geometry"]
            if hasattr(native, "bone_renames"):
                native.bone_renames = copy.deepcopy(state["bone_renames"])
            if hasattr(native, "camera_edits"):
                native.camera_edits = copy.deepcopy(state["camera_edits"])
            self.mesh = state["mesh"]
        else:
            camera = copy.deepcopy(self.project.get("camera", {}))
            self.project = copy.deepcopy(state["project"])
            if camera:
                self.project["camera"] = camera
            self.mesh = state["mesh"]
        self.dirty = True
        self.selected = None
        if hasattr(self, "native_selection"):
            self.native_selection = None
        selection = self.tree.selection()
        if selection:
            self.tree.selection_remove(*selection)
        for child in self.form.winfo_children():
            child.destroy()
        self.properties = {}
        if hasattr(self, "position_properties"):
            self.position_properties = {}
        self.refresh()
        if state["kind"] == "native":
            camera_window = getattr(self, "camera_window", None)
            if camera_window is not None and camera_window.winfo_exists():
                camera_window.reload()
        if self.mesh is not previous_mesh:
            self.fit()
        self.status.set(f"{action} applied; save the project to keep changes")
        self._sync_history_buttons()
        self._schedule_recovery()

    def _cancel_recovery_write(self):
        after_id = getattr(self, "_recovery_after_id", None)
        if after_id is None:
            return
        try:
            self.after_cancel(after_id)
        except tk.TclError:
            pass
        self._recovery_after_id = None

    def _set_recovery_context(self, project_path, *, offer=False):
        self._cancel_recovery_write()
        self._recovery_project_path = Path(project_path) if project_path is not None else None
        self._recovery_baseline_sha256 = None
        if self._recovery_project_path is None:
            return
        try:
            baseline = self._recovery_project_path.read_bytes()
        except OSError as error:
            self.status.set(f"Session recovery unavailable: cannot read saved project ({error})")
            return
        self._recovery_baseline_sha256 = hashlib.sha256(baseline).hexdigest()
        if offer:
            self._offer_recovery()

    def _clear_recovery(self, project_path=None):
        self._cancel_recovery_write()
        target = Path(project_path) if project_path is not None else getattr(self, "_recovery_project_path", None)
        store = getattr(self, "recovery_store", None)
        if target is None or store is None:
            return
        try:
            store.delete(target, self._recent_project_kind())
        except (OSError, ValueError, RuntimeError) as error:
            self.status.set(f"Could not clear recovery snapshot: {error}")

    def _schedule_recovery(self):
        if (not self.dirty or self._recovery_project_path is None or
                self._recovery_baseline_sha256 is None or getattr(self, "exporting", False)):
            return
        self._cancel_recovery_write()
        self._recovery_after_id = self.after(self.recovery_delay_ms, self._write_recovery)

    def _write_recovery(self):
        self._recovery_after_id = None
        if (not self.dirty or self._recovery_project_path is None or
                self._recovery_baseline_sha256 is None or getattr(self, "exporting", False)):
            return
        try:
            self.recovery_store.save(
                self._recovery_project_path,
                self._recent_project_kind(),
                self._recovery_baseline_sha256,
                self._capture_edit_state(),
            )
        except (OSError, ValueError, RuntimeError) as error:
            self.status.set(f"Unsaved session recovery unavailable: {error}")

    def _recovery_payload_valid(self, payload):
        if not isinstance(payload, dict) or payload.get("kind") != self._recent_project_kind():
            return False
        mesh = payload.get("mesh")
        if not isinstance(mesh, (list, tuple)) or len(mesh) != 2:
            return False
        if payload["kind"] == "native":
            required = {"points", "routes", "positions", "layout", "terrain",
                        "geometry", "bone_renames", "camera_edits", "mesh"}
            object_positions = payload.get("object_positions", {})
            object_rotations = payload.get("object_rotations", {})
            object_scales = payload.get("object_scales", {})
            if not all(isinstance(values, dict) for values in
                       (object_positions, object_rotations, object_scales)):
                return False
            supported_objects = getattr(self.native, "object_shape_bindings", {})
            supported_scales = supported_objects
            model = getattr(self.native, "preview_model_name", None)
            supported_rotations = {
                bone.name for bone in self.native.skeletons.models.get(model, ())
                if bone.name in supported_objects and bone.flags & (1 << 12)
            }
            for values, supported, mode in (
                    (object_positions, supported_objects, "position"),
                    (object_rotations, supported_rotations, "rotation"),
                    (object_scales, supported_scales, "scale")):
                for name, xyz in values.items():
                    try:
                        if (name not in supported or not isinstance(xyz, (list, tuple)) or
                                len(xyz) != 3 or any(isinstance(value, bool) for value in xyz) or
                                any(not math.isfinite(float(value)) for value in xyz)):
                            return False
                        vector = tuple(float(value) for value in xyz)
                        if (mode == "position" and any(abs(value) > 1e7 for value in vector) or
                                mode == "rotation" and any(abs(value) > 36000 for value in vector) or
                                mode == "scale" and any(not 1e-4 <= value <= 1e4 for value in vector)):
                            return False
                    except (TypeError, ValueError, OverflowError):
                        return False
            return (required.issubset(payload) and
                    isinstance(payload["points"], list) and
                    isinstance(payload["routes"], list) and
                    isinstance(payload["positions"], dict) and
                    ("object_positions" not in payload or isinstance(payload["object_positions"], dict)) and
                    ("object_rotations" not in payload or isinstance(payload["object_rotations"], dict)) and
                    ("object_scales" not in payload or isinstance(payload["object_scales"], dict)) and
                    isinstance(payload["layout"], dict) and
                    isinstance(payload["bone_renames"], list) and
                    isinstance(payload["camera_edits"], dict) and
                    (payload["terrain"] is None or isinstance(payload["terrain"], str)) and
                    (payload["geometry"] is None or isinstance(payload["geometry"], dict)))
        project = payload.get("project")
        try:
            return isinstance(project, dict) and not validate_preview(project)
        except (ValueError, KeyError, TypeError, AttributeError):
            return False

    def _offer_recovery(self):
        if self._recovery_project_path is None or self._recovery_baseline_sha256 is None:
            return
        try:
            payload = self.recovery_store.load(
                self._recovery_project_path,
                self._recent_project_kind(),
                self._recovery_baseline_sha256,
            )
        except StaleRecoveryError as error:
            self._clear_recovery()
            messagebox.showwarning("Recovery snapshot is out of date", str(error), parent=self)
            return
        except (OSError, ValueError, RuntimeError) as error:
            self._clear_recovery()
            messagebox.showwarning("Recovery snapshot unavailable", str(error), parent=self)
            return
        if payload is None:
            return
        if not self._recovery_payload_valid(payload):
            self._clear_recovery()
            messagebox.showwarning("Recovery snapshot unavailable",
                                   "The saved edit snapshot does not match this editor.", parent=self)
            return
        if not messagebox.askyesno(
                "Recover unsaved edits?",
                "An autosaved edit session exists for this saved project. Restore those edits?",
                parent=self):
            self._clear_recovery()
            return
        previous = self._capture_edit_state()
        try:
            self._restore_edit_state(payload, "Recovery")
            issues = self.native.validate() if payload["kind"] == "native" else validate_preview(self.project)
            if issues:
                raise ValueError("\n".join(issues[:15]))
        except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError, AttributeError) as error:
            self._restore_edit_state(previous, "Recovery rollback")
            self.dirty = False
            self._reset_edit_history()
            self._clear_recovery()
            messagebox.showwarning("Recovery snapshot rejected", str(error), parent=self)
            return
        self._reset_edit_history()
        self.dirty = True
        self.status.set("Recovered unsaved edits. Save the project to keep them.")
        self._schedule_recovery()

    def undo(self):
        if getattr(self, "exporting", False):
            return
        state = self.history.undo()
        if state is not None:
            self._restore_edit_state(state, "Undo")

    def redo(self):
        if getattr(self, "exporting", False):
            return
        state = self.history.redo()
        if state is not None:
            self._restore_edit_state(state, "Redo")

    def camera_change(self, key, value):
        self.project.setdefault("camera", {})[key] = float(value)
        self.draw()

    def _load_mesh(self):
        self.mesh = ([], [])
        path = self.project.get("terrain")
        if path:
            try:
                from .project import resolve_project_path
                terrain = resolve_project_path(path, self.project_path) if self.project_path else path
                self.mesh = read_import_mesh(terrain)
                settings = self.project.get("terrain_transform")
                if settings is not None:
                    self.mesh = apply_obj_transform((*self.mesh, None, None),
                                                    normalize_obj_transform(settings))[:2]
            except (OSError, ValueError) as error:
                self.status.set(f"Terrain unavailable: {error}")

    def open_3d_preview(self):
        """Build/update the embedded world view without blocking Tk."""
        if getattr(self, "exporting", False) or getattr(self, "_preview_building", False):
            return
        self._ensure_embedded_view()
        if not hasattr(self, "native"):
            try:
                self.preview_scene = self._build_3d_preview(None)
                self._show_embedded_scene(self.preview_scene)
                self.status.set("3D world ready · imported preview geometry")
            except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
                self.status.set(f"3D preview unavailable: {error}")
                messagebox.showerror("3D preview unavailable", str(error), parent=self)
            return
        try:
            # view_project reads Tk variables, so capture its detached graph on
            # the UI thread before the worker starts.
            graph = self.view_project()
        except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
            self.status.set(f"3D preview unavailable: {error}")
            messagebox.showerror("3D preview unavailable", str(error), parent=self)
            return
        self._preview_building = True
        self.status.set("Building the 3D preview in the background… editor remains available.")

        def worker():
            try:
                result = self._build_3d_preview(
                    graph, progress=lambda message: self.preview_results.put((None, message)))
                self.preview_results.put((True, result))
            except Exception as error:
                # The worker never calls Tk; completion and errors are handled
                # by poll_preview on the GUI thread.
                self.preview_results.put((False, str(error)))

        threading.Thread(target=worker, name="worldstudio-preview", daemon=True).start()
        self._preview_poll_after = self.after(60, self.poll_preview)

    def open_external_preview(self):
        """Open the same scene in a browser for renderer debugging."""
        if not self.preview_scene:
            self.open_3d_preview()
            self.status.set("Building the world first; use Open external preview again when the viewport is ready.")
            return
        from .preview3d import open_preview
        try:
            path = open_preview(self.preview_scene)
            self.status.set(f"External WebGL preview opened for debugging: {path}")
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror("External preview unavailable", str(error), parent=self)

    def poll_preview(self):
        try:
            succeeded, result = self.preview_results.get_nowait()
        except queue.Empty:
            self._preview_poll_after = self.after(60, self.poll_preview)
            return
        if succeeded is None:
            self.status.set(result)
            self._preview_poll_after = self.after(60, self.poll_preview)
            return
        self._preview_building = False
        if succeeded:
            self.preview_scene = result
            self._show_embedded_scene(result)
            self.status.set(f"3D world ready · {len(result.get('shapes', []))} shapes · "
                            f"{result.get('stats', {}).get('triangles', 0):,} triangles")
        else:
            self.status.set(f"3D preview failed: {result}")
            messagebox.showerror("3D preview unavailable", str(result), parent=self)

    def _show_embedded_scene(self, scene):
        self._ensure_embedded_view()
        if not self.preview_widget:
            self.status.set("Embedded viewport needs tkwry; use Open external preview or install requirements.txt")
            return
        from .preview3d import build_document
        self._embedded_preview_revision += 1
        page = Path(self._embedded_preview_dir.name) / "index.html"
        page.write_text(build_document(scene, embedded=True), encoding="utf-8")
        self.preview_widget.load_url(
            f"https://tkwry.localhost/index.html?revision={self._embedded_preview_revision}")
        if hasattr(self, "native"):
            self._preview_geometry_signature = self._current_preview_geometry_signature()
        self.preview_widget.when_ready(self._on_embedded_view_ready)

    def _on_embedded_view_ready(self):
        """Apply current list selection after the embedded page navigates."""
        self._sync_viewport_selection()

    def _current_preview_geometry_signature(self):
        object_positions = getattr(self.native, "object_positions", {})
        object_rotations = getattr(self.native, "object_rotations", {})
        object_scales = getattr(self.native, "object_scales", {})
        return (self.native.terrain, id(self.native.geometry), tuple(sorted(
            (name, tuple(float(value) for value in xyz))
            for name, xyz in object_positions.items())), tuple(sorted(
            (name, tuple(float(value) for value in xyz))
            for name, xyz in object_rotations.items())), tuple(sorted(
            (name, tuple(float(value) for value in xyz))
            for name, xyz in object_scales.items())))

    def _export_scene_to_external(self):
        if self.preview_scene:
            from .preview3d import open_preview
            open_preview(self.preview_scene)

    def _build_3d_preview(self, graph, progress=None):
        """Build and open a preview using the locked editor's read-only state."""
        def report(message):
            if progress is not None:
                progress(message)

        nodes, routes = [], []
        try:
            if hasattr(self, "native"):
                from .mesh import (DEFAULT_MODEL, extract_rigid_model,
                                   project_terrain_for_preview)
                from .preview_textures import (attach_base_color_textures,
                                               attach_sampler_diagnostic_textures,
                                               attach_normal_map_textures,
                                               attach_texture_srt_parameters)
                report("Preview: reading static BFRES geometry…")
                preview_model_name = getattr(self.native, "preview_model_name",
                                              f"{self.native.source.stem}_World")
                if preview_model_name not in self.native.skeletons.models:
                    preview_model_name = (DEFAULT_MODEL if DEFAULT_MODEL in self.native.skeletons.models
                                          else self.native.path_model)
                preview_positions = dict(self.native.positions)
                preview_positions.update(getattr(self.native, "object_positions", {}))
                preview_model = self.native.skeletons.patch_positions(preview_positions)
                preview_model = Skeletons(preview_model).patch_object_transforms(
                    rotations=getattr(self.native, "object_rotations", {}),
                    scales=getattr(self.native, "object_scales", {}))
                shapes = extract_rigid_model(preview_model, preview_model_name)
                point_index = {row[1]: index for index, row in enumerate(self.native.points.rows)
                               if len(row) > 1}
                editable_bones = {
                    bone.name for bones in self.native.skeletons.models.values()
                    for bone in bones
                    if bone.name in self.native.positions and
                    bone.name not in point_index and bone.name.startswith(("K", "R", "F"))
                }
                for shape in shapes:
                    bound_bone = shape.get("boundBone")
                    if bound_bone in point_index:
                        shape["editorId"] = f"point:{point_index[bound_bone]}"
                    elif bound_bone in getattr(self.native, "object_positions", {}):
                        shape["editorId"] = f"object:{bound_bone}"
                    elif bound_bone in editable_bones:
                        shape["editorId"] = f"bone:{bound_bone}"
                terrain_projection_report = None
                textures = {}
                normal_textures = {}
                diagnostic_textures = {}
                mask_textures = {}
                texture_srt_failures = set()
                texture_srt_parameters = 0
                shader_metadata_failures = set()
                shader_metadata_issue = None
                warned_materials = set()
                warned_normal_materials = set()
                warned_diagnostic_materials = set()
                if self.native.geometry is None:
                    report(f"Preview: decoding supported {preview_model_name} base-color maps…")
                    textures, warned_materials = attach_base_color_textures(
                        self.native.model, shapes, model_name=preview_model_name)
                    if preview_model_name == DEFAULT_MODEL:
                        normal_textures, warned_normal_materials = attach_normal_map_textures(
                            self.native.model, shapes)
                        diagnostic_textures, warned_diagnostic_materials = attach_sampler_diagnostic_textures(
                            self.native.model, shapes)
                        for sampler_slot in ("_o1", "_b0", "_s0", "_x2", "_x0", "_x1"):
                            slot_textures, _ = attach_sampler_diagnostic_textures(
                                self.native.model, shapes, sampler_slot=sampler_slot)
                            mask_textures.update(slot_textures)
                        texture_srt_failures = attach_texture_srt_parameters(self.native.model, shapes)
                        srt_by_material = {shape["material"]: shape["textureSrt"] for shape in shapes
                                           if shape.get("textureSrt")}
                        texture_srt_parameters = sum(len(values) for values in srt_by_material.values())
                        shader_source = self.native.game_root / "content/Common/shader/shaderfb.szs"
                        if shader_source.is_file():
                            report("Preview: resolving local shader-interface metadata…")
                            try:
                                from .bfres_shader import attach_shader_metadata, load_shader_archives
                                shader_archives = load_shader_archives(shader_source)
                                shader_metadata_failures = attach_shader_metadata(
                                    self.native.model, shapes, shader_archives)
                            except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
                                shader_metadata_issue = str(error)
                textured_shapes = sum(bool(shape.get("texture")) for shape in shapes)
                normal_textured_shapes = sum(bool(shape.get("normalTexture")) for shape in shapes)
                texture_notice = (
                    f"BC1/BC3 base-color maps: {len(textures)} unique textures on {textured_shapes} UV meshes. "
                    "Alpha below 50% is cut out; material settings, light maps, game shaders and animation are not evaluated."
                )
                if warned_materials:
                    texture_notice += (f" {len(warned_materials)} material(s) use approximate colors; "
                                       "select an affected shape to see the fallback reason.")
                if texture_srt_parameters:
                    texture_notice += (f" {texture_srt_parameters} stored texmtx SRT parameter(s) are shown "
                                       "read-only in the inspector; none are applied to the preview.")
                if texture_srt_failures:
                    texture_notice += f" {len(texture_srt_failures)} material(s) have unsupported texture SRT data."
                shader_metadata_shapes = sum(bool(shape.get("shaderMetadata")) for shape in shapes)
                if shader_metadata_shapes:
                    texture_notice += (f" Assigned shader-program and sampler symbol names are shown for "
                                       f"{shader_metadata_shapes} shapes; compiled shading and active "
                                       "variation are not evaluated.")
                if shader_metadata_failures:
                    texture_notice += (f" Shader interface metadata is unavailable for "
                                       f"{len(shader_metadata_failures)} material(s).")
                if shader_metadata_issue:
                    texture_notice += " Shader symbol parsing failed; rendering continues without interface labels."
                normal_texture_notice = (
                    f"BC5 SNORM channel inspection: {len(normal_textures)} unique maps on "
                    f"{normal_textured_shapes} UV meshes. R/G are diagnostic channels only; no tangent-space "
                    "lighting is applied in this view. The optional reconstructed-normal preview is approximate; "
                    "channel orientation and game material lighting are unverified. Only top-level texture images "
                    "are previewed."
                )
                if warned_normal_materials:
                    normal_texture_notice += f" {len(warned_normal_materials)} material(s) have no supported _n0 map."
                diagnostic_textured_shapes = sum(bool(shape.get("diagnosticTexture")) for shape in shapes)
                diagnostic_texture_notice = (
                    f"BC5 UNorm sampler `_o0` diagnostics: {len(diagnostic_textures)} unique maps on "
                    f"{diagnostic_textured_shapes} UV meshes. R/G show stored channels only; sampler meaning "
                    "and game material behavior are not inferred. Only top-level texture images are previewed."
                )
                if warned_diagnostic_materials:
                    diagnostic_texture_notice += (
                        f" {len(warned_diagnostic_materials)} material(s) have no supported `_o0` BC5 UNorm map."
                    )
                mask_textured_shapes = sum(bool(shape.get("samplerTextures")) for shape in shapes)
                mask_texture_notice = (
                    f"Diagnostic sampler previews: {len(mask_textures)} unique maps across "
                    f"{mask_textured_shapes} UV meshes from `_o1`, `_b0`, `_s0`, `_x2`, `_x0`, and `_x1`. "
                    "BC4 channels can be viewed in grayscale on the mesh; BC3 `_x0`/`_x1` remain inspector thumbnails. "
                    "Assigned-program symbol names are shown when available; these previews show stored texels and "
                    "do not evaluate the game's shader calculations. "
                    "Only top-level texture images are previewed."
                )
                if self.native.geometry is not None:
                    geometry = self.native.geometry
                    report("Preview: projecting the terrain onto the exported BFRES topology…")
                    terrain_projection_report = project_terrain_for_preview(
                        self.native.model, shapes, geometry["vertices"], geometry["faces"],
                        model=preview_model_name, uvs=geometry.get("uvs"),
                        imported_normals=geometry.get("normals"))
                    texture_notice += (
                        " The terrain viewport uses the export-equivalent projection onto the existing "
                        "grass mesh; the imported mesh is a height source, not replacement topology."
                    )
                visible_nodes = {n["id"]: n for n in graph["nodes"]
                                 if not n.get("fallback") and all(type(n.get(k)) in (int, float) for k in ("x", "y", "z"))}
                nodes = [{"id": n["id"], "editorId": (f"point:{point_index[n['id']]}" if n["id"] in point_index else f"bone:{n['id']}"),
                          "x": float(n["x"]), "y": float(n["y"]), "z": float(n["z"])}
                         for n in visible_nodes.values()]
                route_index = {row[0]: index for index, row in enumerate(self.native.routes.rows) if row}
                for route in graph["routes"]:
                    if route.get("start") in visible_nodes and route.get("end") in visible_nodes:
                        routes.append({"id": route.get("id", ""),
                                       "editorId": f"segment:{route_index[route['id']]}" if route.get("id") in route_index else "",
                                       "start": route["start"], "end": route["end"],
                                       "kind": "secret" if route.get("unlock") == "secret" else "normal"})
                world_label = preview_model_name.removesuffix("_World")
                title = f"{self.native.source.name} · {world_label} world"
                model_name = f"{preview_model_name} • native BFRES static geometry"
                badges = ["BFRES source", "Static rest pose",
                          f"BC1/BC3 textures ×{len(textures)}" if textures else "Approximate materials"]
                if terrain_projection_report is not None:
                    badges.append("Export-equivalent projected terrain")
                if normal_textures:
                    badges.append(f"BC5 diagnostic maps ×{len(normal_textures)}")
                if diagnostic_textures:
                    badges.append(f"BC5 UNorm `_o0` maps ×{len(diagnostic_textures)}")
                if mask_textures:
                    badges.append(f"Sampler diagnostics ×{len(mask_textures)}")
                if texture_srt_parameters:
                    badges.append(f"Texture SRT ×{texture_srt_parameters} · read-only")
                if shader_metadata_shapes:
                    badges.append(f"Shader interfaces ×{shader_metadata_shapes}")
            else:
                from .mesh import _geometry
                vertices, indices, normals, _ = _geometry(self.mesh[0], self.mesh[1])
                source_format = Path(self.project.get("terrain") or "mesh.obj").suffix.upper().lstrip(".")
                shapes = [{"name": f"Imported {source_format} mesh", "material": "Preview mesh", "positions": vertices,
                           "normals": normals, "indices": indices}]
                title = f"World Studio · imported {source_format} mesh"
                model_name = f"{source_format} • 3D mesh preview"
                badges = [f"{source_format} source", "Read-only preview"]
            report("Preview: packing geometry for the embedded WebGL viewport…")
            all_points = [p for shape in shapes for p in shape["positions"]]
            all_points.extend((n["x"], n["y"], n["z"]) for n in nodes)
            low = [min(p[i] for p in all_points) for i in range(3)]
            high = [max(p[i] for p in all_points) for i in range(3)]
            center = [(low[i] + high[i]) / 2 for i in range(3)]
            radius = max((sum((p[i] - center[i]) ** 2 for i in range(3)) ** .5 for p in all_points), default=500)
            vertex_count = sum(len(shape["positions"]) for shape in shapes)
            triangle_count = sum(len(shape["indices"]) // 3 for shape in shapes)
            scene = {"title": title, "model": model_name, "badges": badges,
                     "shapes": shapes, "nodes": nodes, "routes": routes, "showPaths": bool(nodes),
                     "stats": {"vertices": vertex_count, "triangles": triangle_count},
                     "bounds": {"center": center, "radius": max(radius, 10)}}
            if hasattr(self, "native"):
                scene["textureNotice"] = texture_notice
                scene["textures"] = textures
                scene["normalTextureNotice"] = normal_texture_notice
                scene["normalTextures"] = normal_textures
                scene["diagnosticTextureNotice"] = diagnostic_texture_notice
                scene["diagnosticTextures"] = diagnostic_textures
                scene["maskTextureNotice"] = mask_texture_notice
                scene["maskTextures"] = mask_textures
            return scene
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            raise

    def project_point(self, point):
        camera = self.project.setdefault("camera", {})
        yaw, pitch = camera.get("yaw", -0.55), camera.get("pitch", 0.65)
        return project_preview_point(point, self.center, yaw, pitch,
                                     camera.get("scale", 1),
                                     self.canvas.winfo_width(), self.canvas.winfo_height())

    def draw_clear_label(self, text, x, y, obstacles, offsets, *, fill="#ffffff", font=("Segoe UI", 9, "bold")):
        """Place a readable canvas label without covering labels already drawn."""
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        best = None
        best_score = float("inf")
        for dx, dy in offsets:
            label_id = self.canvas.create_text(x + dx, y + dy, text=text, fill=fill,
                                               font=font, justify="center")
            bounds = self.canvas.bbox(label_id)
            self.canvas.delete(label_id)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            outside = max(0, 3 - left) + max(0, 3 - top) + max(0, right - width + 3) + max(0, bottom - height + 3)
            collisions = sum(
                left < other[2] + 4 and right + 4 > other[0] and
                top < other[3] + 4 and bottom + 4 > other[1]
                for other in obstacles
            )
            score = collisions * 1000 + outside * 100
            if score < best_score:
                best_score = score
                best = (x + dx, y + dy, bounds)
            if score == 0:
                break

        if best is None:
            return
        label_x, label_y, bounds = best
        left, top, right, bottom = bounds
        rectangle = self.canvas.create_rectangle(left - 4, top - 2, right + 4, bottom + 2,
                                                  fill="#122330", outline="#31495a", width=1)
        label_id = self.canvas.create_text(label_x, label_y, text=text, fill=fill,
                                           font=font, justify="center")
        self.canvas.tag_lower(rectangle, label_id)
        obstacles.append(bounds)

    def draw(self):
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        self.hit_points = []
        for offset in range(-500, 501, 100):
            for points in [((offset, -40, -500), (offset, -40, 500)), ((-500, -40, offset), (500, -40, offset))]:
                a, b = [self.project_point(p) for p in points]
                self.canvas.create_line(a[:2], b[:2], fill="#213747")
        vertices, faces = self.mesh
        transformed = [self.project_point(v) for v in vertices]
        for face in sorted(faces, key=lambda f: sum(transformed[i][2] for i in f) / len(f), reverse=True):
            coords = [value for i in face for value in transformed[i][:2]]
            self.canvas.create_polygon(coords, fill="#356d5a", outline="#71af89", width=1)
        nodes = {node["id"]: node for node in self.project.get("nodes", [])}
        projected = {name: self.project_point(tuple(node[k] for k in ("x", "y", "z")))
                     for name, node in nodes.items()}
        label_obstacles = []
        for name, (x, y, _) in projected.items():
            node = nodes[name]
            radius = 4 if node.get("style") == "geometry" else 8
            label_obstacles.append((x - radius - 2, y - radius - 2, x + radius + 2, y + radius + 2))
        for route in self.project.get("routes", []):
            if route.get("start") not in nodes or route.get("end") not in nodes:
                continue
            a, b = [projected[name] for name in (route["start"], route["end"])]
            geometry = route.get("style") == "geometry"
            selected_route = self.selected == ("route", route["id"])
            color = "#38edb6" if selected_route else "#65b9c6" if geometry else "#f2c65e"
            width = 5 if selected_route else 2 if geometry else 4
            self.canvas.create_line(a[:2], b[:2], fill=color, width=width,
                                    arrow="none" if geometry else "last",
                                    tags=("route", f"route:{route['id']}"))
            if not geometry:
                self.draw_clear_label(route.get("unlock", route["id"]),
                                      (a[0] + b[0]) / 2, (a[1] + b[1]) / 2,
                                      label_obstacles,
                                      ((0, -16), (0, 16), (16, 0), (-16, 0),
                                       (20, -18), (-20, -18), (20, 18), (-20, 18)),
                                      fill="#f2deb3", font=("Segoe UI", 8, "bold"))
        for name, node in nodes.items():
            x, y, _ = projected[name]
            auxiliary = node.get("style") == "geometry"
            selected = self.selected == ("node", name)
            color = "#ffffff" if selected else "#bc93e7" if node.get("fallback") else "#65b9c6" if auxiliary else "#f1c75f"
            radius = 4 if auxiliary and not selected else 8
            self.canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=color, outline="#102332", width=2)
            if not auxiliary or selected or node.get("fallback"):
                self.draw_clear_label(f"{name}  {node.get('level', '')}", x, y,
                                      label_obstacles,
                                      ((0, -22), (16, -17), (-16, -17), (0, 22),
                                       (28, 0), (-28, 0), (0, -38), (26, -30),
                                       (-26, -30), (0, 38), (38, 18), (-38, 18)))
            self.hit_points.append((x, y, name))
        self.canvas.create_text(15, 15, anchor="nw", fill="#bdd0dd", text="EDITOR PREVIEW / perspective projection", tags=("viewport_caption",))

    def refresh(self):
        selection = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        shown = total = 0
        for kind, key in [("node", "nodes"), ("route", "routes")]:
            for index, item in enumerate(self.project.get(key, [])):
                total += 1
                if not self._tree_filter_matches(item["id"], kind):
                    continue
                self.tree.insert("", "end", iid=f"{kind}:{index}", text=item["id"], values=(kind,))
                shown += 1
        self._finish_tree_refresh(selection, shown, total)
        self.draw()

    def select_tree(self, event=None):
        selection = self.tree.selection()
        if not selection:
            return
        kind, index = selection[0].split(":")
        item = self.project["nodes" if kind == "node" else "routes"][int(index)]
        self.selected = kind, item["id"]
        for child in self.form.winfo_children():
            child.destroy()
        self.properties = {}
        for row, (key, value) in enumerate(item.items()):
            ttk.Label(self.form, text=key).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
            var = tk.StringVar(value=str(value))
            self.properties[key] = var
            ttk.Entry(self.form, textvariable=var).grid(row=row, column=1, sticky="ew", pady=3)
        self.form.columnconfigure(1, weight=1)
        self.draw()

    def apply(self):
        if not self.selected:
            return
        kind, name = self.selected
        items = self.project["nodes" if kind == "node" else "routes"]
        old = next((item for item in items if item["id"] == name), None)
        if old is None:
            return
        candidate = {key: var.get().strip() for key, var in self.properties.items()}
        try:
            if not candidate.get("id") or any(item is not old and item["id"] == candidate["id"] for item in items):
                raise ValueError("Identifier must be nonempty and unique")
            if kind == "node":
                for key in ("x", "y", "z"):
                    candidate[key] = float(candidate[key])
                    if not math.isfinite(candidate[key]):
                        raise ValueError("Coordinates must be finite")
            else:
                ids = {item["id"] for item in self.project["nodes"]}
                if candidate.get("start") not in ids or candidate.get("end") not in ids:
                    raise ValueError("Route endpoints must reference existing nodes")
                if candidate["start"] == candidate["end"]:
                    raise ValueError("A route must connect two different nodes")
            if kind == "node" and candidate["id"] != name:
                for route in self.project["routes"]:
                    for key in ("start", "end"):
                        if route[key] == name:
                            route[key] = candidate["id"]
            old.clear()
            old.update(candidate)
            self.selected = kind, candidate["id"]
            self.dirty = True
            self._record_edit()
            self.refresh()
            self.status.set("Preview properties updated; save the project to keep changes")
        except (ValueError, TypeError) as error:
            messagebox.showerror("Invalid properties", str(error), parent=self)

    def add_node(self):
        name = simpledialog.askstring("New preview node", "Unique node identifier:", parent=self)
        if name is None:
            return
        if not name.strip() or any(node["id"] == name.strip() for node in self.project["nodes"]):
            messagebox.showerror("Invalid node", "A unique nonempty identifier is required", parent=self)
            return
        self.project["nodes"].append({"id": name.strip(), "x": 0, "y": 0, "z": 0, "level": ""})
        self.dirty = True
        self._record_edit()
        self.refresh()

    def add_route(self):
        window = tk.Toplevel(self)
        window.title("New preview route")
        names = [node["id"] for node in self.project["nodes"]]
        values = {}
        for row, key in enumerate(("id", "start", "end", "unlock")):
            ttk.Label(window, text=key, padding=6).grid(row=row, column=0)
            values[key] = tk.StringVar()
            control = ttk.Combobox(window, textvariable=values[key], values=names, state="readonly") if key in ("start", "end") else ttk.Entry(window, textvariable=values[key])
            control.grid(row=row, column=1, padx=8, pady=4)
        def submit():
            route = {key: value.get().strip() for key, value in values.items()}
            if not route["id"] or any(r["id"] == route["id"] for r in self.project["routes"]):
                messagebox.showerror("Invalid route", "A unique route identifier is required", parent=window)
                return
            if route["start"] not in names or route["end"] not in names or route["start"] == route["end"]:
                messagebox.showerror("Invalid route", "Choose two different existing nodes", parent=window)
                return
            self.project["routes"].append(route)
            self.dirty = True
            self._record_edit()
            self.refresh()
            window.destroy()
        ttk.Button(window, text="Create route", command=submit).grid(row=4, columnspan=2, pady=8)

    def delete(self):
        if not self.selected:
            return
        kind, name = self.selected
        key = "nodes" if kind == "node" else "routes"
        affected = sum(name in (route.get("start"), route.get("end"))
                       for route in self.project["routes"]) if kind == "node" else 0
        if kind == "node" and affected and not messagebox.askyesno(
                "Delete connected node?", f"This also removes {affected} connected route(s). Continue?", parent=self):
            return
        self.project[key] = [item for item in self.project[key] if item["id"] != name]
        if kind == "node":
            self.project["routes"] = [r for r in self.project["routes"] if name not in (r["start"], r["end"])]
        self.selected = None
        self.dirty = True
        self._record_edit()
        for child in self.form.winfo_children():
            child.destroy()
        self.refresh()

    def validate(self):
        issues = validate_preview(self.project)
        messagebox.showinfo("Preview graph validation", "\n".join(issues) if issues else
                            "Graph references and connectivity are valid.\nThis does not validate game resources or progression.", parent=self)

    def fit(self):
        points = [tuple(node[k] for k in ("x", "y", "z")) for node in self.project["nodes"]] + self.mesh[0]
        low = [min((point[i] for point in points), default=-150) for i in range(3)]
        high = [max((point[i] for point in points), default=150) for i in range(3)]
        self.center = tuple((low[i] + high[i]) / 2 for i in range(3))
        camera = self.project.setdefault("camera", {})
        camera["scale"] = fit_preview_scale(
            points, self.center, camera.get("yaw", -0.55), camera.get("pitch", 0.65),
            self.canvas.winfo_width(), self.canvas.winfo_height())
        self.draw()

    def press(self, event):
        self.drag = event.x, event.y, False

    def orbit(self, event):
        if self.drag is None:
            return
        x, y, moved = self.drag
        camera = self.project.setdefault("camera", {})
        camera["yaw"] = camera.get("yaw", 0) + (event.x - x) * 0.008
        camera["pitch"] = max(-1.3, min(1.3, camera.get("pitch", 0.6) + (event.y - y) * 0.008))
        self.drag = event.x, event.y, moved or abs(event.x - x) + abs(event.y - y) > 2
        self.draw()

    def release(self, event):
        if self.drag and not self.drag[2]:
            for x, y, name in self.hit_points:
                if (event.x - x) ** 2 + (event.y - y) ** 2 < 225:
                    index = next(i for i, node in enumerate(self.project["nodes"]) if node["id"] == name)
                    self.tree.selection_set(f"node:{index}")
                    self.tree.see(f"node:{index}")
                    self.select_tree()
                    break
        self.drag = None

    def zoom(self, event):
        camera = self.project.setdefault("camera", {})
        camera["scale"] = max(0.0001, min(8, camera.get("scale", 1) * (1.12 if event.delta > 0 else 1 / 1.12)))
        self.draw()

    def may_discard(self):
        if not self.dirty:
            return True
        kind = "native project" if self._recent_project_kind() == "native" else "preview project"
        answer = messagebox.askyesnocancel(f"Unsaved {kind}", "Save project changes before continuing?", parent=self)
        if answer is None:
            return False
        if answer:
            return bool(self.save())
        self._clear_recovery()
        return True

    def _recent_project_kind(self):
        return "preview"

    def recent_project_entries(self):
        return self.recent_projects.list(self._recent_project_kind())

    def _record_recent_project(self, path):
        try:
            self.recent_projects.record(path, self._recent_project_kind())
        except (OSError, ValueError, RuntimeError) as error:
            self.status.set(f"Project opened, but the recent-project list could not be saved: {error}")

    def show_recent_projects(self):
        entries = self.recent_project_entries()
        previous_menu = getattr(self, "_recent_menu", None)
        if previous_menu is not None:
            try:
                if previous_menu.winfo_exists():
                    previous_menu.destroy()
            except tk.TclError:
                pass
        menu = tk.Menu(self.master, tearoff=False, background="#172330", foreground="#e7eff6",
                       activebackground="#1e5860", activeforeground="#ffffff")
        self._recent_menu = menu
        if not entries:
            label = "No recent preview projects" if self._recent_project_kind() == "preview" else "No recent native projects"
            menu.add_command(label=label, state="disabled")
        else:
            for entry in entries:
                path = Path(entry["path"])
                parent = str(path.parent)
                if len(parent) > 52:
                    parent = "…" + parent[-51:]
                menu.add_command(label=f"{path.name}  —  {parent}",
                                 command=lambda project_path=entry["path"]:
                                 self.open_recent_project(project_path))
        x = self.recent_button.winfo_rootx()
        y = self.recent_button.winfo_rooty() + self.recent_button.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def open_recent_project(self, path):
        if self.may_discard():
            self.open_project_path(path)

    def new(self):
        if self.may_discard():
            self._clear_recovery()
            self.project, self.project_path = demo_project(), None
            self._set_recovery_context(None)
            self.selected, self.dirty = None, False
            self._load_mesh()
            self.refresh()
            self._reset_edit_history()

    def open(self):
        if not self.may_discard():
            return
        path = filedialog.askopenfilename(filetypes=[("World Studio preview", "*.json")], parent=self)
        if not path:
            return
        self.open_project_path(path)

    def open_project_path(self, path):
        try:
            path = Path(path).resolve()
            project = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(project, dict):
                raise ValueError("Not a World Studio preview project object")
            if project.get("format") != "worldstudio-preview-v1":
                raise ValueError("Not a World Studio preview project")
            issues = validate_preview(project)
            if issues:
                raise ValueError("\n".join(issues))
            from .project import resolve_project_path
            project["terrain"] = resolve_project_path(project.get("terrain"), path)
            self.project, self.project_path = project, Path(path)
            self.selected, self.dirty = None, False
            self._load_mesh()
            self.refresh()
            self.status.set(f"Opened {path}")
            self._reset_edit_history()
            self._record_recent_project(path)
            self._set_recovery_context(path, offer=True)
        except (OSError, ValueError, KeyError, TypeError) as error:
            messagebox.showerror("Cannot open project", str(error), parent=self)

    def save(self):
        path = self.project_path or filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("World Studio preview", "*.json")], parent=self)
        if not path:
            return False
        try:
            destination = Path(path)
            stored = copy.deepcopy(self.project)
            from .project import save_project_bytes, store_project_path
            stored["terrain"] = store_project_path(stored.get("terrain"), destination)
            content = (json.dumps(stored, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
            backup = save_project_bytes(destination, content)
            self._clear_recovery()
            self._clear_recovery(destination)
            self.project_path, self.dirty = destination, False
            self._set_recovery_context(destination)
            suffix = f" Previous version: {backup}" if backup else ""
            self.status.set(f"Saved preview project: {destination}{suffix}")
            self._record_recent_project(destination)
            return True
        except OSError as error:
            messagebox.showerror("Cannot save project", str(error), parent=self)
            return False

    def import_obj(self):
        path = filedialog.askopenfilename(filetypes=[("OBJ and glTF", "*.obj *.glb *.gltf"),
                                                     ("Wavefront OBJ", "*.obj"),
                                                     ("glTF models", "*.gltf *.glb")], parent=self)
        if path:
            try:
                mesh, compatibility_warnings = read_import_mesh(path, include_report=True)
                transform = ObjTransformDialog(self.winfo_toplevel())
                if transform.result is None:
                    return
                transform_settings = normalize_obj_transform(transform.result)
                mesh = apply_obj_transform((*mesh, None, None), transform_settings)[:2]
                self.project["terrain"], self.mesh = str(Path(path).resolve()), mesh
                self.project["terrain_transform"] = transform_settings
                self.dirty = True
                self._record_edit()
                self.fit()
                source_format = Path(path).suffix.upper().lstrip(".")
                self.status.set(f"{source_format} preview imported · {obj_geometry_summary(*mesh)} · "
                                f"{obj_transform_summary(transform.result)}. BFRES export is not implemented."
                                + (" Compatibility: " + "; ".join(compatibility_warnings) + "."
                                   if compatibility_warnings else ""))
            except (OSError, ValueError) as error:
                messagebox.showerror("Cannot import mesh", str(error), parent=self)

    def close(self):
        if self.may_discard():
            self.master.destroy()

    def _cleanup_runtime_resources(self):
        if self._runtime_cleanup_done:
            return
        self._runtime_cleanup_done = True
        for callback_name in ("_preview_poll_after", "_preview_update_after", "_preview_open_after",
                              "_fit_after_id", "_recovery_after_id"):
            callback_id = getattr(self, callback_name, None)
            if callback_id is not None:
                try:
                    self.after_cancel(callback_id)
                except tk.TclError:
                    pass
                setattr(self, callback_name, None)
        if self.preview_widget:
            try:
                self.preview_widget.destroy()
            except Exception:
                pass
            self.preview_widget = None
        if self._embedded_preview_dir:
            self._embedded_preview_dir.cleanup()
            self._embedded_preview_dir = None

    def destroy(self):
        self._cleanup_runtime_resources()
        super().destroy()


class NativeStudio(WorldStudio):
    """Edit native point/route tables while preserving unsupported columns."""

    def __init__(self, master, native, project_path=None, graph_profile_preferences=None):
        self.native = native
        self.exporting = False
        self.graph_profile_path = None
        self.graph_profile_label = tk.StringVar(master, value="Graph check: off")
        self.graph_profile_preferences = graph_profile_preferences or GraphProfilePreferences()
        self._auto_fit = True
        self._fit_after_id = None
        self.export_results = queue.Queue()
        self.preview_results = queue.Queue()
        self.disabled_for_export = []
        self.camera_window = None
        self.show_auxiliary = tk.BooleanVar(master, value=False)
        super().__init__(master, self.view_project())
        self.master.title("NSMBU World Studio — native world resources")
        self.project_path = Path(project_path) if project_path is not None else None
        self.status.set(f"Loaded {native.source.name} • coordinates: " +
                        ("BFRES hierarchy-transformed rest pose; unsupported branches use labeled layouts" if native.positions else "editor layout only; game transforms unknown"))
        self._restore_graph_profile()
        self.canvas.bind("<Map>", self._schedule_auto_fit, add="+")
        self.canvas.bind("<Configure>",
                         lambda event: self._schedule_auto_fit(event, delay_ms=90), add="+")
        self._fit_after_id = self.after_idle(self._schedule_auto_fit)
        self._set_recovery_context(self.project_path or native.source, offer=True)
        recent_path = self.project_path or Path(native.source)
        if recent_path.is_file():
            self._record_recent_project(recent_path)

    def _recent_project_kind(self):
        return "native"

    def view_project(self):
        nodes, routes = [], []
        points = self.native.points.rows
        world = self.native.world_positions
        point_names = [row[1] for row in points if len(row) > 1]
        names = list(point_names)
        if self.show_auxiliary.get():
            for bone in self.native.skeletons.models[self.native.path_model]:
                if len(bone.name) == 4 and bone.name[0] in "FK" and bone.name not in names:
                    names.append(bone.name)
        world_values = [world[name] for name in names if name in world]
        fallback_x = max((v[0] for v in world_values), default=0) + 500
        fallback_z = min((v[2] for v in world_values), default=0)
        fallback_count = 0
        for name in names:
            if not self.show_auxiliary.get() and (not name.startswith("W") or name not in world):
                continue
            position = world.get(name)
            fallback = position is None
            if fallback:
                position = self.native.layout.get(name)
            if position is None:
                # A separate labeled editor-layout area, never local XYZ posed
                # as world coordinates when hierarchy evaluation is unsupported.
                position = [fallback_x + (fallback_count % 4) * 180, 0, fallback_z + (fallback_count // 4) * 180]
                fallback_count += 1
            nodes.append(dict(id=name, x=position[0], y=position[1], z=position[2],
                              level="[layout: unsupported transform]" if fallback else "",
                              fallback=fallback, style="geometry" if not name.startswith("W") else "level"))
        for row in points:
            if len(row) < 2:
                continue
            name = row[1]
            for column, route_column, kind in [(3, 4, "normal"), (6, 7, "secret")]:
                if len(row) > route_column:
                    for destination in row[column].split(","):
                        if destination:
                            routes.append(dict(id=f"{name}:{kind}:{destination}", start=name,
                                               end=destination, unlock=kind))
        if self.show_auxiliary.get():
            for row in self.native.routes.rows:
                if row and len(row[0]) == 9 and row[0].startswith("R"):
                    start, end = row[0][1:5], row[0][5:9]
                    if start in world and end in world:
                        routes.append(dict(id=row[0], start=start, end=end, style="geometry"))
        return {"format": "native-view", "nodes": nodes, "routes": routes,
                "camera": getattr(self, "project", {}).get("camera", {"yaw": -0.55, "pitch": 0.65, "scale": 1}),
                "terrain": self.native.terrain}

    def _build(self):
        super()._build()
        self.viewport_hint.configure(text="3D World is the main view · drag a point to move it · drag empty space to orbit · right-drag to pan · wheel to zoom. Click points or routes to edit them.")
        self.description.configure(text="Native point/segment fields are saved to CSV and exported in the SZS archive. "
            "Known bone XYZ edits modify BFRES; model names and engine indices remain protected. "
            "Camera controls affect this viewport only. OBJ/glTF terrain import projects the upper surface onto existing grass vertices, preserving source topology and UVs; collision and in-game appearance still need Cemu testing.")
        toolbar = self.winfo_children()[0]
        replacements = {"New preview": "Reload source", "Add node": "Add draft point", "Add route": "Add segment"}
        for child in toolbar.winfo_children():
            if isinstance(child, ttk.Button) and child.cget("text") in replacements:
                child.configure(text=replacements[child.cget("text")])
        bar = ttk.Frame(self, padding=(8, 0))
        bar.pack(fill="x", before=self.winfo_children()[1])
        ttk.Button(bar, text="Open native world SZS", command=self.open_szs).pack(side="left", padx=2)
        ttk.Button(bar, text="Export validated SZS", command=self.export_szs).pack(side="left", padx=2)
        profile_menu = ttk.Menubutton(bar, textvariable=self.graph_profile_label)
        profile_options = tk.Menu(profile_menu, tearoff=False)
        profile_options.add_command(label="Select reachability profile…",
                                    command=self.choose_graph_profile)
        profile_options.add_command(label="Disable profile check",
                                    command=self.clear_graph_profile)
        profile_menu.configure(menu=profile_options)
        profile_menu.pack(side="left", padx=2)
        ttk.Button(bar, text="Use OBJ/glTF mesh (experimental)", command=self.use_obj_mesh).pack(side="left", padx=2)
        ttk.Button(bar, text="Open external preview", command=self.open_external_preview).pack(side="left", padx=2)
        ttk.Checkbutton(bar, text="Show path geometry / auxiliary points", variable=self.show_auxiliary,
                        command=self.toggle_auxiliary).pack(side="left", padx=10)
        extra_bar = ttk.Frame(self, padding=(8, 3))
        extra_bar.pack(fill="x", before=self.winfo_children()[2])
        ttk.Button(extra_bar, text="Camera data", command=self.open_camera_data).pack(side="left", padx=2)
        ttk.Button(extra_bar, text="Direct 1-2 → 1-3 (experimental)", command=self.direct_route).pack(side="left", padx=2)
        ttk.Label(extra_bar, text="Raw offset banks and direct-route traversal require in-game verification.").pack(side="left", padx=8)

    def _schedule_auto_fit(self, event=None, *, delay_ms=0):
        if not self._auto_fit or self.canvas.winfo_width() <= 1 or self.canvas.winfo_height() <= 1:
            return
        if self._fit_after_id is not None:
            try:
                self.after_cancel(self._fit_after_id)
            except tk.TclError:
                pass
        if delay_ms > 0:
            self._fit_after_id = self.after(delay_ms, self._fit_if_automatic)
        else:
            self._fit_after_id = self.after_idle(self._fit_if_automatic)

    def _fit_if_automatic(self):
        self._fit_after_id = None
        if self._auto_fit and self.canvas.winfo_width() > 1 and self.canvas.winfo_height() > 1:
            self.fit()

    def fit(self):
        self._auto_fit = True
        super().fit()
        if self.preview_widget and self.preview_widget.ready:
            self.preview_widget.eval_js("window.worldStudioView && window.worldStudioView.fitView();")

    def zoom(self, event):
        self._auto_fit = False
        super().zoom(event)

    def refresh(self):
        self.project = self.view_project()
        selection = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        shown = total = 0
        for kind, rows in [("point", self.native.points.rows), ("segment", self.native.routes.rows)]:
            for index, row in enumerate(rows):
                name = row[1] if kind == "point" and len(row) > 1 else row[0]
                total += 1
                if not self._tree_filter_matches(name, kind):
                    continue
                self.tree.insert("", "end", iid=f"{kind}:{index}", text=name, values=(kind,))
                shown += 1
        point_names = {row[1] for row in self.native.points.rows if len(row) > 1}
        for bone in self.native.skeletons.models[self.native.path_model]:
            if bone.name in self.native.positions and bone.name not in point_names and bone.name.startswith(("K", "R", "F")):
                total += 1
                if not self._tree_filter_matches(bone.name, "bone XYZ"):
                    continue
                self.tree.insert("", "end", iid=f"bone:{bone.name}", text=bone.name, values=("bone XYZ",))
                shown += 1
        object_model = getattr(self.native, "preview_model_name", self.native.path_model)
        for bone in self.native.skeletons.models.get(object_model, ()):
            if bone.name not in getattr(self.native, "object_positions", {}):
                continue
            total += 1
            if not self._tree_filter_matches(bone.name, "BFRES object"):
                continue
            self.tree.insert("", "end", iid=f"object:{bone.name}", text=bone.name,
                             values=("BFRES object",))
            shown += 1
        self._finish_tree_refresh(selection, shown, total)
        if not selection or not self.tree.selection():
            self.tree.yview_moveto(0)
        self.draw()
        if self.preview_scene and self._preview_geometry_signature != self._current_preview_geometry_signature():
            self._schedule_embedded_preview_build()
        else:
            self._schedule_viewport_overlay_update()

    def toggle_auxiliary(self):
        self.refresh()
        self.fit()

    def press(self, event):
        if self.exporting:
            self.drag = None
            return
        point_indices = {row[1]: index for index, row in enumerate(self.native.points.rows)
                         if len(row) > 1}
        candidates = [(x, y, name) for x, y, name in self.hit_points if name in point_indices]
        hit = min(candidates, key=lambda item: (event.x - item[0]) ** 2 + (event.y - item[1]) ** 2,
                  default=None)
        if hit is None or (event.x - hit[0]) ** 2 + (event.y - hit[1]) ** 2 >= 225:
            super().press(event)
            return

        _, _, name = hit
        index = point_indices[name]
        iid = f"point:{index}"
        if not self.tree.exists(iid):
            super().press(event)
            return
        self.tree.selection_set(iid)
        self.tree.see(iid)
        self.select_tree()
        node = next((item for item in self.project["nodes"] if item["id"] == name), None)
        if node is None:
            super().press(event)
            return
        preview_only = bool(node.get("fallback") or name not in self.native.positions)
        position = ([node[key] for key in ("x", "y", "z")] if preview_only else
                    self.native.world_positions.get(name))
        if position is None:
            preview_only = True
            position = [node[key] for key in ("x", "y", "z")]
        self.drag = {"kind": "point", "name": name, "index": index,
                     "start": (event.x, event.y), "last": (event.x, event.y),
                     "position": [float(value) for value in position],
                     "preview_only": preview_only, "moved": False}

    def orbit(self, event):
        if not isinstance(self.drag, dict):
            if (self.drag is not None and not self.drag[2] and
                    math.hypot(event.x - self.drag[0], event.y - self.drag[1]) > 2):
                self._auto_fit = False
            super().orbit(event)
            return
        if self.exporting:
            return
        drag = self.drag
        start_x, start_y = drag["start"]
        if not drag["moved"] and math.hypot(event.x - start_x, event.y - start_y) <= 2:
            drag["last"] = event.x, event.y
            return
        self._auto_fit = False
        last_x, last_y = drag["last"]
        dx, dy = event.x - last_x, event.y - last_y
        drag["last"] = event.x, event.y
        if not dx and not dy:
            return

        camera = self.project.setdefault("camera", {})
        yaw, pitch = camera.get("yaw", -0.55), camera.get("pitch", 0.65)
        view_scale = float(camera.get("scale", 1))
        depth = self.project_point(drag["position"])[2]
        projection_scale = view_scale * 900 / max(100, 900 + depth * view_scale)
        try:
            delta = camera_plane_world_delta(dx, dy, yaw, pitch, projection_scale)
            target = [value + change for value, change in zip(drag["position"], delta)]
            if not all(math.isfinite(value) and abs(value) <= 1e7 for value in target):
                raise ValueError("Dragged coordinates exceed the supported range")
            if drag["preview_only"]:
                self.native.layout[drag["name"]] = target
            else:
                converter = getattr(self.native.skeletons, "local_position_for_world", None)
                if converter is not None:
                    local = converter(self.native.path_model, drag["name"], target,
                                      overrides=self.native.positions)
                else:
                    bone = next((item for item in self.native.skeletons.models[self.native.path_model]
                                 if item.name == drag["name"]), None)
                    if bone is None or bone.parent != -1:
                        raise ValueError("This point's hierarchy transform cannot be inverted safely")
                    local = target
                if not all(math.isfinite(float(value)) and abs(float(value)) <= 1e7 for value in local):
                    raise ValueError("Dragged local coordinates exceed the supported range")
                self.native.positions[drag["name"]] = [float(value) for value in local]
            drag["position"] = target
            drag["moved"] = True
            self.dirty = True
            self.project = self.view_project()
            self.draw()
            mode = "preview layout only" if drag["preview_only"] else "BFRES rest-pose point"
            self.status.set(f"Moving {drag['name']} in the camera plane · {mode}; release to finish")
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            self.status.set(f"Cannot move {drag['name']}: {error}")
            self.drag = None

    def release(self, event):
        if isinstance(self.drag, dict):
            drag = self.drag
            self.drag = None
            if drag["moved"]:
                self._record_edit()
                self.refresh()
                iid = f"point:{drag['index']}"
                if self.tree.exists(iid):
                    self.tree.selection_set(iid)
                    self.tree.see(iid)
                    self.select_tree()
                mode = "preview layout only" if drag["preview_only"] else "BFRES local XYZ"
                self.status.set(f"Moved {drag['name']} in the camera plane · {mode}; undo is available")
            return
        if self.drag and not self.drag[2]:
            for x, y, name in self.hit_points:
                if (event.x - x) ** 2 + (event.y - y) ** 2 < 225:
                    index = next((i for i, row in enumerate(self.native.points.rows) if len(row) > 1 and row[1] == name), None)
                    item = f"point:{index}" if index is not None else f"bone:{name}"
                    if not self.tree.exists(item):
                        break
                    self.tree.selection_set(item)
                    self.tree.see(item)
                    self.select_tree()
                    break
        self.drag = None

    def draw(self):
        super().draw()
        if hasattr(self, "canvas"):
            label = "NATIVE WORLD GRAPH / hierarchy-transformed rest pose (no animations)"
            if self.show_auxiliary.get():
                label += "\nGold = progression • cyan = path segments / F,K geometry • purple = editor layout"
            self.canvas.itemconfigure("viewport_caption", text=label)

    def select_tree(self, event=None):
        if self.exporting:
            return
        selection = self.tree.selection()
        if not selection:
            return
        self._sync_viewport_selection()
        kind, index = selection[0].split(":", 1)
        if kind in ("bone", "object"):
            self.native_selection = kind, index
            self.selected = (("route", index) if index.startswith("R") else ("node", index)) if kind == "bone" else None
            for child in self.form.winfo_children():
                child.destroy()
            self.properties, self.position_properties = {}, {}
            self.object_rotation_properties, self.object_scale_properties = {}, {}
            model = (getattr(self.native, "preview_model_name", self.native.path_model)
                     if kind == "object" else self.native.path_model)
            bones = self.native.skeletons.models[model]
            bone = next(bone for bone in bones if bone.name == index)
            parent = next((f"{item.index}: {item.name}" for item in bones if item.index == bone.parent), "none (root)")
            metadata = [("bone", index), ("model", bone.model), ("parent", parent)]
            planned = next((rename["new"] for rename in getattr(self.native, "bone_renames", [])
                            if rename.get("old") == index and rename.get("model") == bone.model), None)
            if planned:
                metadata.append(("export alias", planned))
            for row_number, (key, value) in enumerate(metadata):
                ttk.Label(self.form, text=key).grid(row=row_number, column=0, sticky="w", pady=3)
                entry = ttk.Entry(self.form)
                entry.insert(0, str(value))
                entry.configure(state="readonly")
                entry.grid(row=row_number, column=1, sticky="ew", padx=(5, 0), pady=3)
            if kind == "object":
                shape_names = getattr(self.native, "object_shape_bindings", {}).get(index, ())
                metadata.append(("bound shapes", ", ".join(shape_names) or "static BFRES shape"))
                row_number = len(metadata) - 1
                ttk.Label(self.form, text=metadata[row_number][0]).grid(row=row_number, column=0, sticky="w", pady=3)
                entry = ttk.Entry(self.form)
                entry.insert(0, metadata[row_number][1])
                entry.configure(state="readonly")
                entry.grid(row=row_number, column=1, sticky="ew", padx=(5, 0), pady=3)
                self.show_native_position(
                    index, len(metadata), position_map=self.native.object_positions,
                    caption="BFRES object local XYZ — embedded shape transform")
                row = len(metadata) + 4
                self.object_rotation_properties = self.show_object_vector(
                    "Local rotation (degrees)", self.native.object_rotations.get(index),
                    row)
                self.object_scale_properties = self.show_object_vector(
                    "Local scale", self.native.object_scales.get(index), row + 4)
            else:
                self.show_native_position(index, len(metadata))
            self.form.columnconfigure(1, weight=1)
            self.draw()
            return
        rows = self.native.points.rows if kind == "point" else self.native.routes.rows
        row = rows[int(index)]
        self.native_selection = kind, int(index)
        self.selected = ("node", row[1]) if kind == "point" else ("route", row[0])
        for child in self.form.winfo_children():
            child.destroy()
        labels = ["engine index", "model point", "flags", "normal destinations", "normal path chain", "reserved 5", "secret destinations", "secret path chain", "reserved 8"] if kind == "point" else ["model segment", "road type", "reserved"]
        self.properties = {}
        self.position_properties = {}
        for i, value in enumerate(row):
            ttk.Label(self.form, text=labels[i] if i < len(labels) else f"column {i}").grid(row=i, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=value)
            self.properties[i] = var
            if kind == "segment" and i == 1:
                road_types = native_road_type_choices(self.native.routes.initial)
                if value and value not in road_types:
                    road_types.insert(0, value)  # Preserve an unknown stock value until explicitly changed.
                entry = ttk.Combobox(self.form, textvariable=var, values=road_types,
                                     state="readonly")
            else:
                entry = ttk.Entry(self.form, textvariable=var)
            entry.grid(row=i, column=1, sticky="ew", padx=(5, 0), pady=3)
            if kind == "point" and i in (4, 7):
                ttk.Button(
                    self.form, text="Edit order", width=9,
                    command=lambda field=var: self.edit_path_chain(field),
                ).grid(row=i, column=2, padx=(5, 0), pady=3)
            if kind == "point" and i in (3, 6):
                ttk.Button(
                    self.form, text="Edit targets", width=11,
                    command=lambda field=var, point_name=row[1]:
                        self.edit_point_destinations(field, point_name),
                ).grid(row=i, column=2, padx=(5, 0), pady=3)
            if ((kind == "point" and i in (0, 1)) or
                    (kind == "segment" and i == 0)):
                entry.configure(state="readonly")
        if kind == "point":
            self.show_native_position(row[1], len(row))
            ttk.Button(
                self.form, text="Build route connection…",
                command=lambda point_index=int(index):
                    self.build_point_connection(point_index),
            ).grid(row=len(row) + 4, column=0, columnspan=2, sticky="w", pady=(8, 2))
        self.form.columnconfigure(1, weight=1)
        self.draw()

    def edit_path_chain(self, variable):
        if self.exporting:
            return
        references = set(self.native.references)
        bones = {
            bone.name
            for model_bones in self.native.skeletons.models.values()
            for bone in model_bones
        }
        world_match = re.search(r"pointW([1-9])", getattr(self.native, "point_name", ""))
        world_prefix = f"W{world_match[1]}" if world_match else None
        route_ids = native_macro_path_choices(references, bones, world_prefix)
        chain_context = None
        selection = getattr(self, "native_selection", None)
        if selection and selection[0] == "point":
            point_index = selection[1]
            point_rows = self.native.points.rows
            if 0 <= point_index < len(point_rows):
                row = point_rows[point_index]
                path_column = next((column for column, field in self.properties.items()
                                    if field is variable), None)
                if path_column in (4, 7):
                    destination_column = path_column - 1
                    chain_context = (row[1], row[destination_column], references)

        def chain_status(tokens):
            if chain_context is None:
                return None
            start, destinations, known_references = chain_context
            reaches = native_macro_path_chain_reaches(
                ",".join(tokens), start, destinations, known_references)
            target_list = ([value.strip() for value in destinations.split(",") if value.strip()]
                           if isinstance(destinations, str) else [])
            if reaches is True:
                return (f"Static BFRES names form an ordered chain: {start} → {target_list[0]}. "
                        "This does not confirm in-game movement.", "#8fd6a4")
            if reaches is False:
                target = target_list[0] if len(target_list) == 1 else "the selected destination"
                return (f"Stored order does not form an ordered chain from {start} to {target}.",
                        "#ffba86")
            return ("Cannot confirm from names: destination is ambiguous or one or more IDs "
                    "are unresolved/branched.", "#ffd18a")

        suggested_chain = None
        if chain_context is not None:
            start, destinations, _known_references = chain_context
            targets = ([value.strip() for value in destinations.split(",") if value.strip()]
                       if isinstance(destinations, str) else [])
            if len(targets) == 1:
                suggested_chain = suggest_native_macro_path_chain(
                    route_ids, start, targets[0])
        chain_help = (
            "Existing values stay in place unless you explicitly choose a suggestion. "
            "A unique shortest chain was found from BFRES endpoint names; taking it "
            "replaces this list. This does not establish in-game route behavior."
            if suggested_chain else
            "Existing values remain in place, including unresolved IDs. Choosing a "
            "BFRES ID does not confirm its game behavior.")

        dialog = PathChainDialog(
            self.winfo_toplevel(), variable.get(), route_ids,
            chain_status=chain_status if chain_context is not None else None,
            suggested_chain=suggested_chain,
            help_text=chain_help)
        self.wait_window(dialog)
        if dialog.result is not None:
            variable.set(dialog.result)

    def edit_point_destinations(self, variable, point_name):
        if self.exporting:
            return
        point_ids = [row[1] for row in self.native.points.rows
                     if len(row) > 1 and row[1] != point_name]
        dialog = PathChainDialog(
            self.winfo_toplevel(), variable.get(), point_ids,
            dialog_title="Edit point destinations",
            heading="Ordered destination point IDs",
            item_label="Point ID",
            help_text=("Existing values stay in place, including unresolved IDs. "
                       "Edit the matching path-chain field separately; choosing a "
                       "destination does not confirm in-game connectivity."),
            apply_label="Apply destinations",
            unknown_label="Point ID not present in this archive; preserved unless removed: ",
        )
        self.wait_window(dialog)
        if dialog.result is not None:
            variable.set(dialog.result)

    def show_native_position(self, name, start, *, position_map=None, caption=None):
        position_map = self.native.positions if position_map is None else position_map
        actual = name in position_map
        position = position_map.get(name) or self.native.layout.get(name) or [0, 0, 0]
        caption = caption or ("BFRES local XYZ — child paths move with their parent" if actual else "Preview layout XYZ — does not change game transforms")
        if actual and position_map is self.native.positions and name not in self.native.world_positions:
            caption += "; rest transform unsupported, displayed as layout"
        ttk.Label(self.form, text=caption, wraplength=290).grid(row=start, columnspan=2, sticky="w", pady=(8, 3))
        for offset, key in enumerate(("x", "y", "z")):
            ttk.Label(self.form, text=key).grid(row=start + offset + 1, column=0, sticky="w")
            var = tk.StringVar(value=str(position[offset]))
            self.position_properties[key] = var
            ttk.Entry(self.form, textvariable=var).grid(row=start + offset + 1, column=1, sticky="ew", padx=(5, 0), pady=3)

    def show_object_vector(self, label, values, start):
        ttk.Label(self.form, text=label).grid(row=start, columnspan=2, sticky="w", pady=(8, 3))
        controls = {}
        if values is None:
            ttk.Label(self.form, text="Read-only transform format").grid(
                row=start + 1, columnspan=2, sticky="w")
            return controls
        for offset, axis in enumerate("xyz"):
            ttk.Label(self.form, text=axis).grid(row=start + offset + 1, column=0, sticky="w")
            variable = tk.StringVar(value=str(values[offset]))
            controls[axis] = variable
            ttk.Entry(self.form, textvariable=variable).grid(
                row=start + offset + 1, column=1, sticky="ew", padx=(5, 0), pady=3)
        return controls

    def apply(self):
        if self.exporting:
            return
        selection = getattr(self, "native_selection", None)
        if selection is None:
            return
        kind, index = selection
        try:
            position = [float(self.position_properties[k].get()) for k in ("x", "y", "z")] if kind in ("point", "bone", "object") else None
            if position and not all(math.isfinite(value) for value in position):
                raise ValueError("Coordinates must be finite")
            rotation = ([float(self.object_rotation_properties[k].get()) for k in ("x", "y", "z")]
                        if kind == "object" and self.object_rotation_properties else None)
            scale = ([float(self.object_scale_properties[k].get()) for k in ("x", "y", "z")]
                     if kind == "object" and self.object_scale_properties else None)
            if rotation is not None and not all(math.isfinite(value) and abs(value) <= 36000 for value in rotation):
                raise ValueError("Rotation must be finite and within +/-36000 degrees")
            if scale is not None and not all(math.isfinite(value) and 1e-4 <= value <= 1e4 for value in scale):
                raise ValueError("Scale components must be between 1e-4 and 1e4")
        except ValueError as error:
            messagebox.showerror("Invalid transform", str(error), parent=self)
            return
        if kind == "bone":
            self.native.positions[index] = position
            self.dirty = True
            self._record_edit()
            self.refresh()
            self.status.set(f"Updated {index} local XYZ; hierarchy rest positions refreshed. Animation behavior remains unverified.")
            return
        if kind == "object":
            self.native.object_positions[index] = position
            if rotation is not None:
                self.native.object_rotations[index] = rotation
            if scale is not None:
                self.native.object_scales[index] = scale
            self.dirty = True
            self._record_edit()
            self.refresh()
            self.status.set(f"Updated BFRES object {index} local transform; embedded preview rebuild queued. In-game appearance remains unverified.")
            return
        rows = self.native.points.rows if kind == "point" else self.native.routes.rows
        edited_row = [self.properties[i].get() for i in sorted(self.properties)]
        if kind == "segment" and edited_row:
            # A route row's first cell names an existing BFRES bone. Keep the
            # reference stable even if a caller changes the Tk variable directly.
            edited_row[0] = rows[index][0]
        rows[index] = edited_row
        if position is not None:
            name = rows[index][1]
            target = self.native.positions if name in self.native.positions else self.native.layout
            target[name] = position
        self.dirty = True
        self._record_edit()
        self.refresh()
        self.status.set("Native CSV updated. Validate before export; in-game behavior remains unverified.")

    def add_node(self):
        if self.exporting:
            return
        name = simpledialog.askstring("Draft point", "Model point name (new bones cannot be created; export may be blocked):", parent=self)
        if name:
            self.native.points.rows.append([str(len(self.native.points.rows)), name.strip(), "", "", "", "", "", "", ""])
            self.dirty = True
            self._record_edit()
            self.refresh()
            self.status.set("Draft point added. New engine indices require script remapping and cannot currently export.")

    def build_point_connection(self, point_index):
        """Create a reviewable route/point/path draft as one undoable edit."""
        if self.exporting:
            return
        if not 0 <= point_index < len(self.native.points.rows):
            return
        source_row = self.native.points.rows[point_index]
        if len(source_row) != 9:
            messagebox.showerror("Cannot build route", "The selected point row is malformed.", parent=self)
            return
        source_name = source_row[1]
        world_match = re.match(r"W[1-9]", source_name)
        if not world_match:
            messagebox.showerror(
                "Cannot build route",
                "Choose a W1–W9 point as the route start; other point roles are not inferred.",
                parent=self,
            )
            return
        world_prefix = world_match.group(0)
        bones = {
            bone.name
            for model_bones in self.native.skeletons.models.values()
            for bone in model_bones
        }
        references = set(self.native.references)
        road_types = native_road_type_choices(self.native.routes.initial)
        if not road_types:
            messagebox.showerror(
                "Cannot build route",
                "The source route table has no road type to reuse.", parent=self)
            return
        targets = [row[1] for i, row in enumerate(self.native.points.rows)
                   if i != point_index and len(row) == 9 and
                   row[1].startswith(world_prefix)]
        if not targets:
            messagebox.showerror(
                "Cannot build route",
                f"No other {world_prefix} points are available as destinations.", parent=self)
            return

        window = tk.Toplevel(self)
        window.title("Build route connection draft")
        window.transient(self.winfo_toplevel())
        window.resizable(False, False)
        body = ttk.Frame(window, padding=14)
        body.grid(sticky="nsew")
        ttk.Label(
            body, text=f"Connect {source_name} through existing BFRES paths",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        destination = tk.StringVar(value="")
        destination_kind = tk.StringVar(value="normal")
        road_type = tk.StringVar(value=road_types[0])
        ttk.Label(body, text="Destination point").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(body, textvariable=destination, values=targets,
                     state="readonly", width=24).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(body, text="Destination field").grid(row=2, column=0, sticky="w", pady=4)
        slot = ttk.Frame(body)
        slot.grid(row=2, column=1, sticky="w", pady=4)
        ttk.Radiobutton(slot, text="Normal", variable=destination_kind,
                        value="normal").pack(side="left")
        ttk.Radiobutton(slot, text="Secret", variable=destination_kind,
                        value="secret").pack(side="left", padx=(10, 0))
        ttk.Label(body, text="Road type for new rows").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(body, textvariable=road_type, values=road_types,
                     state="readonly", width=24).grid(row=3, column=1, sticky="ew", pady=4)
        chain_preview = tk.StringVar(value="Choose a destination to inspect existing BFRES paths.")
        ttk.Label(body, textvariable=chain_preview, wraplength=460,
                  foreground="#a9c2d5").grid(
                      row=4, column=0, columnspan=2, sticky="w", pady=(8, 4))
        ttk.Label(
            body,
            text=("This drafts an ordered path from BFRES endpoint names, adds missing route-table rows, "
                  "and replaces only the chosen normal/secret destination and path-chain pair. "
                  "Review the result before export; game movement and unlock behavior are not inferred."),
            wraplength=460,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 10))

        buttons = ttk.Frame(body)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e")
        create = ttk.Button(buttons, text="Build connection", state="disabled")
        create.pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side="right")
        state = {"draft": None}

        def update_preview(*_):
            target = destination.get()
            try:
                draft = build_native_connection_draft(
                    self.native.points.rows, self.native.routes.rows, references,
                    bones, point_index, target, destination_kind.get(),
                    road_type.get(), world_prefix) if target else None
            except ValueError as error:
                draft = None
                chain_preview.set(str(error) if target else
                                  "Choose a destination to inspect existing BFRES paths.")
            state["draft"] = draft
            if not draft:
                create.state(["disabled"])
                return
            chain = draft["chain"]
            if not chain:
                chain_preview.set(
                    "No unique shortest BFRES path chain was found. Existing data is unchanged.")
                create.state(["disabled"])
                return
            chain_preview.set(
                f"Static path: {source_name} → " + " → ".join(
                    [route_id[1:5] for route_id in chain] + [target]) +
                f". {len(draft['route_rows'])} route-table row(s) will be added.")
            create.state(["!disabled"] if road_type.get() in road_types else ["disabled"])

        def submit():
            draft = state.get("draft")
            target = destination.get()
            if not draft or target not in targets or road_type.get() not in road_types:
                return
            if point_index >= len(self.native.points.rows) or self.native.points.rows[point_index][1] != source_name:
                messagebox.showerror("Cannot build route", "The selected source point changed; reopen the dialog.", parent=window)
                return
            point = self.native.points.rows[point_index]
            destination_column = draft["destination_column"]
            path_column = draft["path_column"]
            if point[destination_column] or point[path_column]:
                if not messagebox.askyesno(
                        "Replace route fields?",
                        f"Replace {source_name}'s selected destination and path-chain fields?\n\n"
                        f"Destination: {point[destination_column] or '(empty)'}\n"
                        f"Path chain: {point[path_column] or '(empty)'}\n\n"
                        "The change will be one Undo step.", parent=window):
                    return
            try:
                draft = build_native_connection_draft(
                    self.native.points.rows, self.native.routes.rows, references,
                    bones, point_index, target, destination_kind.get(),
                    road_type.get(), world_prefix)
            except ValueError as error:
                messagebox.showerror("Cannot build route", str(error), parent=window)
                update_preview()
                return
            try:
                self._apply_point_connection_draft(draft)
            except ValueError as error:
                messagebox.showerror("Cannot build route", str(error), parent=window)
                update_preview()
                return
            window.destroy()

        for variable in (destination, destination_kind, road_type):
            variable.trace_add("write", update_preview)
        window.bind("<Return>", lambda _event: submit() if create.instate(("!disabled",)) else None)
        window.bind("<Escape>", lambda _event: window.destroy())
        window.grab_set()
        window.wait_window()

    def _apply_point_connection_draft(self, draft):
        """Commit both route tables and refresh the selected point properties."""
        point_rows, route_rows = apply_native_connection_draft(
            self.native.points.rows, self.native.routes.rows, draft)
        self.native.points.rows = point_rows
        self.native.routes.rows = route_rows
        self.dirty = True
        self._record_edit()
        self.refresh()
        point_index = draft["source_index"]
        iid = f"point:{point_index}"
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)
            self.select_tree()
        self.status.set(
            f"Drafted {draft['source']} → {draft['target']} with {len(draft['chain'])} "
            f"existing BFRES path segment(s); added {len(draft['route_rows'])} route row(s). "
            "Static names only; verify traversal in Cemu.")

    def add_route(self):
        if self.exporting:
            return
        bones = {
            bone.name
            for model_bones in self.native.skeletons.models.values()
            for bone in model_bones
        }
        world_match = re.search(r"pointW([1-9])", getattr(self.native, "point_name", ""))
        world_prefix = f"W{world_match[1]}" if world_match else None
        point_paths = set(native_point_path_route_ids(self.native.points.rows))
        route_ids = native_route_segment_choices(
            self.native.routes.rows, self.native.references, bones, world_prefix,
            point_rows=self.native.points.rows)
        if not route_ids:
            messagebox.showerror(
                "Cannot add route segment",
                "No unused BFRES route segments with resolvable local endpoints were found.",
                parent=self,
            )
            return

        route_types = native_road_type_choices(self.native.routes.initial)
        if not route_types:
            messagebox.showerror(
                "Cannot add route segment",
                "The current route table does not contain a road type to reuse.",
                parent=self,
            )
            return

        window = tk.Toplevel(self)
        window.title("Add draft route segment")
        window.transient(self.winfo_toplevel())
        window.resizable(False, False)
        body = ttk.Frame(window, padding=14)
        body.grid(sticky="nsew")
        ttk.Label(body, text="Add an existing BFRES segment to the route table.",
                  font=("TkDefaultFont", 10, "bold")).grid(
                      row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        segment_id = tk.StringVar(value="")
        road_type = tk.StringVar(value="")
        for row_index, (label, variable, choices) in enumerate((
                ("BFRES segment", segment_id, route_ids),
                ("Road type", road_type, route_types))):
            ttk.Label(body, text=label).grid(row=row_index + 1, column=0,
                                             sticky="w", padx=(0, 12), pady=4)
            ttk.Combobox(body, textvariable=variable, values=choices,
                         state="readonly", width=22).grid(
                             row=row_index + 1, column=1, sticky="ew", pady=4)

        ttk.Label(
            body,
            text=("IDs already listed in point path fields appear first. Other BFRES IDs follow. "
                  "This adds a CSV row only; point path fields remain unchanged."),
            wraplength=390,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(5, 10))

        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e")
        create = ttk.Button(buttons, text="Add segment", state="disabled")
        create.pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side="right")

        def update_route_preview(*_):
            try:
                row = build_native_route_row(
                    segment_id.get(), road_type.get(), route_ids,
                    self.native.routes.rows)
            except ValueError as error:
                self.status.set(str(error) if segment_id.get() else
                                "Choose an unused BFRES route segment.")
                create.state(["disabled"])
                return
            path_state = ("is also listed in native point path fields" if row[0] in point_paths
                          else "is not listed in native point path fields")
            self.status.set(f"Ready to add {row[0]}; it {path_state}.")
            create.state(["!disabled"])

        def submit():
            try:
                row = build_native_route_row(
                    segment_id.get(), road_type.get(), route_ids,
                    self.native.routes.rows)
            except ValueError as error:
                messagebox.showerror("Invalid route segment", str(error), parent=window)
                return
            self.native.routes.rows.append(row)
            self.dirty = True
            self._record_edit()
            self.refresh()
            self.status.set(
                f"Draft route {row[0]} added to CSV; point destinations and path chains were not changed.")
            window.destroy()

        create.configure(command=submit)
        for variable in (segment_id, road_type):
            variable.trace_add("write", update_route_preview)
        window.bind("<Return>", lambda _event: submit() if create.instate(("!disabled",)) else None)
        window.bind("<Escape>", lambda _event: window.destroy())
        window.grab_set()
        window.wait_window()

    def delete(self):
        if self.exporting:
            return
        selection = getattr(self, "native_selection", None)
        if selection is None:
            return
        kind, index = selection
        if kind == "bone":
            self.status.set("Bone deletion is unsupported; edit local XYZ or select a CSV draft row instead.")
            return
        rows = self.native.points.rows if kind == "point" else self.native.routes.rows
        del rows[index]
        self.native_selection = self.selected = None
        self.dirty = True
        self._record_edit()
        self.refresh()
        for child in self.form.winfo_children():
            child.destroy()
        self.status.set("Draft deletion. Point index changes block export until engine/script remapping exists.")

    def validate(self):
        try:
            issues = self._validation_issues()
        except (OSError, ValueError) as error:
            issues = [str(error)]
        if issues:
            messagebox.showerror("Native resource validation failed",
                                 "\n".join(issues[:35]), parent=self)
            return
        profile_note = (" The selected graph profile also reaches its required locations."
                        if self.graph_profile_path is not None else "")
        messagebox.showinfo(
            "Native resource validation",
            "Native graph and model references pass static validation."
            + profile_note + "\nGame behavior still requires Cemu testing.",
            parent=self)

    def open_szs(self):
        if not self.may_discard():
            return
        path = filedialog.askopenfilename(filetypes=[("World resource", "*.szs")], parent=self)
        if path:
            self.open_project_path(path)

    def replace_native(self, native, project_path):
        if self.exporting:
            return
        if self.camera_window is not None and self.camera_window.winfo_exists():
            self.camera_window.destroy()
        self.camera_window = None
        self.native, self.project_path = native, project_path
        self.graph_profile_path = None
        self.graph_profile_label.set("Graph check: off")
        self.native_selection = self.selected = None
        self.dirty = False
        self.project = self.view_project()
        self._load_mesh()
        self.tree.selection_remove(*self.tree.selection())
        self.refresh()
        self.fit()
        for child in self.form.winfo_children():
            child.destroy()
        self.status.set(f"Opened {native.source.name}; " + ("hierarchy-transformed BFRES rest pose; purple points use editor layout" if native.positions else "editor layout; game coordinates unavailable"))
        self._restore_graph_profile()
        self._reset_edit_history()
        self._set_recovery_context(project_path or native.source, offer=True)

    def open(self):
        if not self.may_discard():
            return
        path = filedialog.askopenfilename(filetypes=[("Native World Studio project", "*.json"),
                                                     ("World resource archive", "*.szs")], parent=self)
        if path:
            self.open_project_path(path)

    def open_project_path(self, path):
        try:
            from .project import WorldProject
            path = Path(path)
            if path.suffix.lower() == ".json":
                native = WorldProject.load(path)
                project_path = path
            elif path.suffix.lower() == ".szs":
                native = WorldProject.open(path)
                project_path = None
            else:
                raise ValueError("Choose a native World Studio JSON project or an SZS world resource")
            self.replace_native(native, project_path)
            self._record_recent_project(path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            messagebox.showerror("Cannot open native project", str(error), parent=self)

    def new(self):
        if self.may_discard():
            from .project import WorldProject
            try:
                self.replace_native(WorldProject.open(self.native.source), None)
            except (OSError, ValueError) as error:
                messagebox.showerror("Cannot reload original", str(error), parent=self)

    def save(self):
        if self.exporting:
            return False
        path = self.project_path or filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Native World Studio project", "*.json")], parent=self)
        if not path:
            return False
        try:
            backup = self.native.save(path)
            self._clear_recovery()
            self._clear_recovery(path)
            self.project_path, self.dirty = Path(path), False
            self._set_recovery_context(self.project_path)
            suffix = f" Previous version: {backup}" if backup else ""
            self.status.set(f"Saved native project: {path}{suffix}")
            self._record_recent_project(path)
            return True
        except (OSError, ValueError) as error:
            messagebox.showerror("Cannot save project", str(error), parent=self)
            return False

    def import_obj(self):
        if self.exporting:
            return
        path = filedialog.askopenfilename(filetypes=[("OBJ and glTF", "*.obj *.glb *.gltf"),
                                                     ("Wavefront OBJ", "*.obj"),
                                                     ("glTF models", "*.gltf *.glb")], parent=self)
        if path:
            try:
                mesh, compatibility_warnings = read_import_mesh(path, include_report=True)
                transform = ObjTransformDialog(self.winfo_toplevel())
                if transform.result is None:
                    return
                mesh = apply_obj_transform((*mesh, None, None), transform.result)[:2]
                self.native.terrain = str(Path(path).resolve())
                self.native.geometry = None
                self.mesh = mesh
                self.dirty = True
                self._record_edit()
                self.refresh()
                self.fit()
                source_format = Path(path).suffix.upper().lstrip(".")
                self.status.set(f"{source_format} preview imported · {obj_geometry_summary(*mesh)} · "
                                f"{obj_transform_summary(transform.result)}; native mesh replacement is disabled."
                                + (" Compatibility: " + "; ".join(compatibility_warnings) + "."
                                   if compatibility_warnings else ""))
            except (OSError, ValueError) as error:
                messagebox.showerror("Cannot import mesh", str(error), parent=self)

    def open_camera_data(self):
        if self.exporting:
            return
        if self.camera_window is not None and self.camera_window.winfo_exists():
            self.camera_window.lift()
            return
        if not getattr(self.native, "camera_tables", {}):
            details = "\n".join(getattr(self.native, "camera_load_errors", []))
            messagebox.showinfo("Camera data unavailable", "No supported companion offset tables were loaded.\n" + details, parent=self)
            return
        self.camera_window = CameraDataWindow(self)

    def direct_route(self):
        if self.exporting:
            return
        from .__main__ import direct_route_demo
        points = copy.deepcopy(self.native.points.rows)
        routes = copy.deepcopy(self.native.routes.rows)
        renames = copy.deepcopy(getattr(self.native, "bone_renames", []))
        try:
            direct_route_demo(self.native)
            generated = self.native.bone_renames
            replaced = {(rename["model"], rename["old"]) for rename in generated}
            self.native.bone_renames = [rename for rename in renames
                                       if (rename.get("model"), rename.get("old")) not in replaced] + generated
        except (ValueError, KeyError) as error:
            self.native.points.rows = points
            self.native.routes.rows = routes
            self.native.bone_renames = renames
            messagebox.showerror("Direct route unavailable", str(error), parent=self)
            return
        self.dirty = True
        self._record_edit()
        self.refresh()
        self.status.set("Experimental direct 1-2 → 1-3 applied: overwrote 3 progression rows and one path/segment; other drafts retained. Save and export separately; traversal remains unverified.")

    def use_obj_mesh(self):
        if self.exporting:
            return
        path = filedialog.askopenfilename(filetypes=[("Experimental OBJ/glTF grass mesh", "*.obj *.glb *.gltf"),
                                                     ("Wavefront OBJ", "*.obj"),
                                                     ("glTF models", "*.gltf *.glb")], parent=self)
        if path:
            try:
                (vertices, faces, uvs, normals), compatibility_warnings = read_import_mesh(
                    path, include_attributes=True, include_report=True)
                transform = ObjTransformDialog(self.winfo_toplevel())
                if transform.result is None:
                    return
                vertices, faces, uvs, normals = transform_obj_geometry(
                    vertices, faces, uvs, normals, **transform.result)
                self.native.geometry = {"vertices": vertices, "faces": faces,
                                        "uvs": uvs, "normals": normals}
                self.native.terrain = str(Path(path).resolve())
                self.mesh = vertices, faces
                self.dirty = True
                self._record_edit()
                self.refresh()
                self.fit()
                source_format = Path(path).suffix.upper().lstrip(".")
                self.status.set(f"Experimental {source_format} terrain patch · {obj_geometry_summary(vertices, faces)} · "
                                f"{obj_transform_summary(transform.result)}. Projects the upper surface onto "
                                "existing grass vertices while preserving topology and UVs; export validates overlap."
                                + (" Compatibility: " + "; ".join(compatibility_warnings) + "."
                                   if compatibility_warnings else ""))
            except (OSError, ValueError) as error:
                messagebox.showerror("Cannot use imported mesh", str(error), parent=self)

    def may_discard(self):
        if self.exporting:
            self.status.set("A background operation is running. Wait before changing or closing the project.")
            return False
        return super().may_discard()

    def set_export_busy(self, busy):
        self.exporting = busy
        self.master.configure(cursor="watch" if busy else "")
        if busy:
            self.disabled_for_export = []
            pending = list(self.winfo_children())
            while pending:
                widget = pending.pop()
                pending.extend(widget.winfo_children())
                if isinstance(widget, (ttk.Button, ttk.Menubutton, ttk.Entry, ttk.Checkbutton,
                                       ttk.Scale, ttk.Treeview)) and not widget.instate(["disabled"]):
                    widget.state(["disabled"])
                    self.disabled_for_export.append(widget)
        else:
            for widget in self.disabled_for_export:
                if widget.winfo_exists():
                    widget.state(["!disabled"])
            self.disabled_for_export = []

    def poll_export(self):
        try:
            succeeded, result = self.export_results.get_nowait()
        except queue.Empty:
            self.after(60, self.poll_export)
            return
        self.set_export_busy(False)
        if succeeded:
            terrain = "Experimental mesh included. " if result.get("terrain_exported") else ""
            graph = result.get("graph_validation") or {}
            graph_note = (f" Static profile passed: {', '.join(graph.get('required_locations', []))}."
                          if graph.get("passed") else "")
            geometry = result.get("geometry") or {}
            projection = geometry.get("baked_uv_projection") or {}
            projection_warning = projection.get("warning")
            warning = (f" Baked-light UV review: {projection_warning}. Check the export manifest."
                       if projection_warning else "")
            self.status.set(f"Exported verified archive: {result.get('output', '')}. {terrain}"
                            f"Cemu verification is still required.{graph_note}{warning}")
        else:
            self.status.set(f"Export failed: {result}")
            messagebox.showerror("Export failed", str(result), parent=self)

    def export_szs(self):
        if self.exporting:
            return
        try:
            issues = self._validation_issues()
        except (OSError, ValueError) as error:
            issues = [str(error)]
        if issues:
            messagebox.showerror("Export blocked", "\n".join(issues[:35]), parent=self)
            return
        path = filedialog.asksaveasfilename(defaultextension=".szs", filetypes=[("New world mod archive", "*.szs")], initialfile=self.native.source.name, parent=self)
        if path:
            native = self.native
            graph_profile = self.graph_profile_path
            self.set_export_busy(True)
            self.status.set("Exporting and compressing Yaz0… controls are locked while archive verification runs.")
            def worker():
                try:
                    if graph_profile is None:
                        result = native.export(path)
                    else:
                        result = native.export(path, graph_profile=graph_profile)
                    self.export_results.put((True, result))
                except Exception as error:
                    # The worker never accesses Tk; all status/dialog work occurs
                    # in poll_export on the GUI thread, including unexpected errors.
                    self.export_results.put((False, str(error)))
            threading.Thread(target=worker, name="worldstudio-export", daemon=True).start()
            self.after(60, self.poll_export)

    def _validation_issues(self):
        issues = set(self.native.validate())
        if self.graph_profile_path is not None:
            from .__main__ import _validate_with_graph_profile
            issues.update(_validate_with_graph_profile(self.native, self.graph_profile_path))
        return sorted(issues)

    def choose_graph_profile(self):
        if self.exporting:
            return
        path = filedialog.askopenfilename(
            title="Select a static graph reachability profile",
            filetypes=[("World graph profiles", "*.json"), ("JSON", "*.json")],
            parent=self)
        if not path:
            return
        from .graph_validation import load_native_graph_profile
        world = re.search(r"pointW([1-9])", getattr(self.native, "point_name", ""))
        world_prefix = f"W{world[1]}" if world else None
        try:
            profile = load_native_graph_profile(path, world_prefix)
        except (OSError, ValueError) as error:
            messagebox.showerror("Graph profile unavailable", str(error), parent=self)
            return
        self.graph_profile_path = Path(path)
        self.graph_profile_label.set(f"Graph check: {self.graph_profile_path.name}")
        try:
            self.graph_profile_preferences.set(self.native.source_sha256,
                                               self.graph_profile_path)
        except (OSError, ValueError) as error:
            self.status.set(f"Profile selected for this session but could not be saved: {error}")
            return
        self.status.set(
            f"Export gate enabled: {', '.join(profile['entry_points'])} must reach "
            f"{', '.join(profile['required_locations'])}; game unlock rules are not inferred.")

    def clear_graph_profile(self):
        if self.exporting:
            return
        self.graph_profile_path = None
        self.graph_profile_label.set("Graph check: off")
        try:
            self.graph_profile_preferences.set(self.native.source_sha256, None)
        except (OSError, ValueError) as error:
            self.status.set(f"Profile disabled for this session but preference could not be saved: {error}")
            return
        self.status.set("Graph-profile export gate disabled")

    def _restore_graph_profile(self):
        """Restore only a stored profile that still parses for this world."""
        source_hash = getattr(self.native, "source_sha256", None)
        path = self.graph_profile_preferences.get(source_hash)
        if path is None:
            return
        world = re.search(r"pointW([1-9])", getattr(self.native, "point_name", ""))
        world_prefix = f"W{world[1]}" if world else None
        try:
            from .graph_validation import load_native_graph_profile
            profile = load_native_graph_profile(path, world_prefix)
        except (OSError, ValueError) as error:
            self.graph_profile_path = None
            self.graph_profile_label.set("Graph check: off")
            self.status.set(f"Saved graph profile is unavailable; export gate remains off: {error}")
            return
        self.graph_profile_path = path
        self.graph_profile_label.set(f"Graph check: {path.name}")
        self.status.set(
            f"Restored graph export gate: {', '.join(profile['entry_points'])} must reach "
            f"{', '.join(profile['required_locations'])}; game unlock rules are not inferred.")


class PathChainDialog(tk.Toplevel):
    """Edit ordered IDs in a native point destination or path-chain field."""

    def __init__(self, parent, current_value, route_ids, chain_status=None, *,
                 suggested_chain=None,
                 dialog_title="Edit point path order",
                 heading="Ordered BFRES path IDs", item_label="BFRES ID",
                 help_text=("Existing values remain in place, including unresolved IDs. "
                            "Choosing a BFRES ID does not confirm its game behavior."),
                 apply_label="Apply chain",
                 unknown_label="Not found in current BFRES; preserved unless removed: "):
        super().__init__(parent)
        self.original = current_value
        self.value_ids = tuple(sorted(set(route_ids)))
        self.changed = False
        self.result = None
        self.chain_status = chain_status
        self.suggested_chain = tuple(suggested_chain or ())
        self.title(dialog_title)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        ttk.Label(self, text=heading,
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=14, pady=(12, 4))
        ttk.Label(
            self,
            text=help_text,
            wraplength=480,
        ).pack(anchor="w", padx=14, pady=(0, 8))

        self.status_label = None
        if self.chain_status is not None:
            self.status_label = ttk.Label(self, text="", wraplength=480)
            self.status_label.pack(anchor="w", padx=14, pady=(0, 8))

        content = ttk.Frame(self, padding=(14, 0))
        content.pack(fill="both", expand=True)
        list_frame = ttk.Frame(content)
        list_frame.pack(fill="both", expand=True)
        self.items = tk.Listbox(
            list_frame, height=9, width=45, selectmode="browse",
            exportselection=False, background="#121e29", foreground="#dce7f0",
            selectbackground="#1e5860", selectforeground="#ffffff",
            highlightbackground="#34495c", relief="flat",
        )
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.items.yview)
        self.items.configure(yscrollcommand=scrollbar.set)
        self.items.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        for token in self.original.split(","):
            token = token.strip()
            if token:
                self.items.insert("end", token)

        unresolved = [token for token in self._tokens() if token not in self.value_ids]
        if unresolved:
            ttk.Label(
                content,
                text=unknown_label + ", ".join(unresolved[:6]),
                wraplength=480,
                foreground="#ffd18a",
            ).pack(anchor="w", pady=(5, 0))

        add_row = ttk.Frame(self, padding=(14, 8, 14, 4))
        add_row.pack(fill="x")
        ttk.Label(add_row, text=item_label).pack(side="left", padx=(0, 8))
        self.route_choice = tk.StringVar(value="")
        self.choice = ttk.Combobox(
            add_row, textvariable=self.route_choice, values=self.value_ids,
            state="readonly", width=25,
        )
        self.choice.pack(side="left", fill="x", expand=True)
        self.add_button = ttk.Button(add_row, text="Add", command=self.add_selected)
        self.add_button.pack(side="left", padx=(8, 0))

        actions = ttk.Frame(self, padding=(14, 2, 14, 12))
        actions.pack(fill="x")
        self.remove_button = ttk.Button(actions, text="Remove", command=self.remove_selected)
        self.remove_button.pack(side="left")
        self.suggest_button = None
        if self.suggested_chain:
            self.suggest_button = ttk.Button(
                actions, text="Use suggested chain", command=self.use_suggested_chain)
            self.suggest_button.pack(side="left", padx=(8, 0))
        self.up_button = ttk.Button(actions, text="Move up", command=lambda: self.move_selected(-1))
        self.up_button.pack(side="left", padx=(8, 0))
        self.down_button = ttk.Button(actions, text="Move down", command=lambda: self.move_selected(1))
        self.down_button.pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Cancel", command=self.cancel).pack(side="right", padx=(8, 0))
        ttk.Button(actions, text=apply_label, command=self.apply).pack(side="right")

        self.items.bind("<<ListboxSelect>>", self.update_actions)
        self.route_choice.trace_add("write", self.update_actions)
        self.bind("<Escape>", lambda _event: self.cancel())
        self.update_actions()
        self.grab_set()

    def _tokens(self):
        return list(self.items.get(0, "end"))

    def update_actions(self, *_):
        tokens = self._tokens()
        selection = self.items.curselection()
        selected = selection[0] if selection else None
        candidate = self.route_choice.get()
        self.add_button.state([
            "!disabled" if candidate in self.value_ids and candidate not in tokens
            else "disabled"
        ])
        self.remove_button.state(["!disabled"] if selected is not None else ["disabled"])
        self.up_button.state(["!disabled"] if selected is not None and selected > 0 else ["disabled"])
        self.down_button.state([
            "!disabled" if selected is not None and selected + 1 < len(tokens)
            else "disabled"
        ])
        if self.status_label is not None:
            status = self.chain_status(tokens)
            if status:
                text, color = status
                self.status_label.configure(text=text, foreground=color)

    def add_selected(self):
        candidate = self.route_choice.get()
        if candidate not in self.value_ids or candidate in self._tokens():
            return
        index = self.items.size()
        self.items.insert("end", candidate)
        self.items.selection_clear(0, "end")
        self.items.selection_set(index)
        self.items.see(index)
        self.changed = True
        self.update_actions()

    def use_suggested_chain(self):
        if not self.suggested_chain:
            return
        self.items.delete(0, "end")
        for token in self.suggested_chain:
            self.items.insert("end", token)
        if self.suggested_chain:
            self.items.selection_set(0)
            self.items.see(0)
        self.changed = True
        self.update_actions()

    def remove_selected(self):
        selection = self.items.curselection()
        if not selection:
            return
        self.items.delete(selection[0])
        self.changed = True
        self.update_actions()

    def move_selected(self, delta):
        selection = self.items.curselection()
        if not selection:
            return
        current = selection[0]
        target = current + delta
        tokens = self._tokens()
        if target < 0 or target >= len(tokens):
            return
        tokens[current], tokens[target] = tokens[target], tokens[current]
        self.items.delete(0, "end")
        for token in tokens:
            self.items.insert("end", token)
        self.items.selection_set(target)
        self.items.see(target)
        self.changed = True
        self.update_actions()

    def cancel(self):
        self.result = None
        self.destroy()

    def apply(self):
        self.result = ",".join(self._tokens()) if self.changed else self.original
        self.destroy()


class ObjTransformDialog(tk.Toplevel):
    """Choose import-space conversion without modifying the source mesh file."""

    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("Mesh coordinates and scale")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        ttk.Label(self, text="Convert the imported mesh into world-map model space",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=16, pady=(14, 5))
        ttk.Label(self, text="Scale is applied first, then rotation X → Y → Z, then translation. "
                  "Coordinates are local model units; the source file remains unchanged.",
                  wraplength=560).pack(anchor="w", padx=16, pady=(0, 10))

        self.values = {key: tk.StringVar(value=value) for key, value in {
            "scale_x": "1", "scale_y": "1", "scale_z": "1",
            "rotation_x": "0", "rotation_y": "0", "rotation_z": "0",
            "translation_x": "0", "translation_y": "0", "translation_z": "0",
        }.items()}
        table = ttk.Frame(self, padding=(16, 0))
        table.pack(fill="x")
        ttk.Label(table, text="Axis", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=4)
        for column, caption in enumerate(("X", "Y", "Z"), 1):
            ttk.Label(table, text=caption, font=("Segoe UI", 9, "bold"), anchor="center").grid(
                row=0, column=column, sticky="ew", padx=4, pady=4)
        for row, (label, prefix) in enumerate((("Scale", "scale"), ("Rotation (degrees)", "rotation"),
                                                ("Translation (units)", "translation")), 1):
            ttk.Label(table, text=label).grid(row=row, column=0, sticky="w", pady=4)
            for column, axis in enumerate("xyz", 1):
                ttk.Entry(table, textvariable=self.values[f"{prefix}_{axis}"], width=12,
                          justify="center").grid(row=row, column=column, sticky="ew", padx=4, pady=4)
        for column in range(1, 4):
            table.columnconfigure(column, weight=1)

        controls = ttk.Frame(self, padding=(16, 8, 16, 14))
        controls.pack(fill="x")
        ttk.Button(controls, text="Z-up → Y-up", command=self.set_z_up_preset).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Reset", command=self.reset).pack(side="left")
        ttk.Button(controls, text="Use unchanged", command=self.use_unchanged).pack(side="right", padx=(6, 0))
        ttk.Button(controls, text="Apply conversion", command=self.apply).pack(side="right")
        self.bind("<Return>", lambda event: self.apply())
        self.bind("<Escape>", lambda event: self.destroy())
        self.grab_set()
        self.wait_window()

    def reset(self):
        for key, value in (("scale_x", "1"), ("scale_y", "1"), ("scale_z", "1"),
                           ("rotation_x", "0"), ("rotation_y", "0"), ("rotation_z", "0"),
                           ("translation_x", "0"), ("translation_y", "0"), ("translation_z", "0")):
            self.values[key].set(value)

    def set_z_up_preset(self):
        self.reset()
        self.values["rotation_x"].set("-90")

    def use_unchanged(self):
        self.result = {"scale": (1., 1., 1.), "rotation_degrees": (0., 0., 0.),
                       "translation": (0., 0., 0.)}
        self.destroy()

    def apply(self):
        try:
            def vector(prefix):
                return tuple(float(self.values[f"{prefix}_{axis}"].get()) for axis in "xyz")
            settings = {"scale": vector("scale"), "rotation_degrees": vector("rotation"),
                        "translation": vector("translation")}
            if not all(math.isfinite(value) for values in settings.values() for value in values):
                raise ValueError("Scale, rotation, and translation must be finite numbers")
            if any(abs(value) < 1e-12 for value in settings["scale"]):
                raise ValueError("Scale components must be nonzero")
            if any(abs(value) > 1e4 for value in settings["scale"]):
                raise ValueError("Scale components must be within ±10,000")
            if any(abs(value) > 36000 for value in settings["rotation_degrees"]):
                raise ValueError("Rotation components must be within ±36,000 degrees")
            if any(abs(value) > 1e5 for value in settings["translation"]):
                raise ValueError("Translation must be within ±100,000 model units")
        except ValueError as error:
            messagebox.showerror("Invalid mesh transform", str(error), parent=self)
            return
        self.result = settings
        self.destroy()


class CameraDataWindow(tk.Toplevel):
    """Raw numeric offset-table editor without guessed camera-state semantics."""

    def __init__(self, studio, visible=True):
        super().__init__(studio)
        self.withdraw()
        self.studio, self.native = studio, studio.native
        self.title("Camera data — raw offset banks")
        self.geometry("850x590")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.filename = tk.StringVar(value=next(iter(sorted(self.native.camera_tables))))
        self.bank = tk.StringVar(value="0")
        toolbar = ttk.Frame(self, padding=10)
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="Companion file").pack(side="left")
        files = ttk.Combobox(toolbar, textvariable=self.filename, values=sorted(self.native.camera_tables), state="readonly", width=35)
        files.pack(side="left", padx=8)
        files.bind("<<ComboboxSelected>>", self.reload)
        ttk.Label(toolbar, text="Bank").pack(side="left")
        banks = ttk.Combobox(toolbar, textvariable=self.bank, values=("0", "1"), state="readonly", width=4)
        banks.pack(side="left", padx=8)
        banks.bind("<<ComboboxSelected>>", self.reload)
        ttk.Label(self, wraplength=810, padding=(10, 0, 10, 10), text="These are raw offset vectors from companion files. Bank meanings and the final camera effect are unverified. Names and unknown_u32 remain read-only. The main editor camera sliders change only its viewport.").pack(fill="x")
        records_frame = ttk.Frame(self, padding=(10, 0))
        records_frame.pack(fill="both", expand=True)
        columns = ("index", "name", "x", "y", "z", "unknown")
        self.records = ttk.Treeview(records_frame, columns=columns, show="headings", selectmode="browse", height=15)
        for column, caption, width in (("index", "Record", 60), ("name", "Name (raw)", 120), ("x", "X", 115), ("y", "Y", 115), ("z", "Z", 115), ("unknown", "unknown_u32", 150)):
            self.records.heading(column, text=caption)
            self.records.column(column, width=width, minwidth=50)
        self.records.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(records_frame, orient="vertical", command=self.records.yview)
        scroll.pack(side="right", fill="y")
        self.records.configure(yscrollcommand=scroll.set)
        self.records.bind("<<TreeviewSelect>>", self.select_record)
        form = ttk.Frame(self, padding=10)
        form.pack(fill="x")
        self.vector = {}
        for column, key in enumerate(("x", "y", "z")):
            ttk.Label(form, text=key.upper()).grid(row=0, column=column * 2, padx=(0, 6))
            self.vector[key] = tk.StringVar()
            ttk.Entry(form, textvariable=self.vector[key], width=20).grid(row=0, column=column * 2 + 1, padx=(0, 12))
        ttk.Button(form, text="Apply XYZ to project", command=self.apply).grid(row=0, column=6)
        self.status = tk.StringVar(value="Choose a raw record. Apply stores the vector in the project; Save/Export run from the main editor.")
        ttk.Label(self, textvariable=self.status, padding=10, wraplength=810).pack(fill="x")
        self.reload()
        if visible:
            self.deiconify()

    def active(self):
        if self.studio.exporting:
            self.status.set("A background operation is running; offset edits and closing are locked.")
            return False
        if self.studio.native is not self.native:
            self.status.set("The source project changed. Reopen Camera data from the current project.")
            return False
        return True

    def reload(self, event=None):
        if not self.active():
            return
        selection = self.records.selection()
        try:
            table = self.native.camera_table(self.filename.get())
            bank = int(self.bank.get())
            self.records.delete(*self.records.get_children())
            for index in range(table.per_bank):
                record = table.record(bank, index)
                name = repr(record.name_raw) if record.name_raw is not None else "—"
                unknown = f"0x{record.unknown_u32:08X}" if record.unknown_u32 is not None else "—"
                self.records.insert("", "end", iid=str(index), values=(index, name, *[repr(v) for v in record.vector], unknown))
            target = selection[0] if selection and self.records.exists(selection[0]) else "0"
            self.records.selection_set(target)
            self.records.see(target)
            self.select_record()
        except (ValueError, KeyError, TypeError) as error:
            self.status.set(f"Cannot load offset records: {error}")

    def select_record(self, event=None):
        if not self.active() or not self.records.selection():
            return
        try:
            record = self.native.camera_table(self.filename.get()).record(int(self.bank.get()), int(self.records.selection()[0]))
            for key, value in zip(("x", "y", "z"), record.vector):
                self.vector[key].set(repr(value))
        except (ValueError, TypeError) as error:
            self.status.set(str(error))

    def apply(self):
        if not self.active() or not self.records.selection():
            return
        try:
            index, bank = int(self.records.selection()[0]), int(self.bank.get())
            vector = [float(self.vector[key].get()) for key in ("x", "y", "z")]
            self.native.set_camera_vector(self.filename.get(), bank, index, vector)
            self.studio.dirty = True
            self.studio._record_edit()
            self.reload()
            self.status.set(f"Applied {self.filename.get()} bank {bank}, record {index}. Final camera behavior remains unverified.")
            self.studio.status.set("Camera raw vector draft updated. Save the project and export companion files to test it.")
        except (ValueError, TypeError, KeyError) as error:
            messagebox.showerror("Invalid offset vector", str(error), parent=self)

    def close(self):
        if self.active():
            self.destroy()


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="NSMBU World Studio native resource editor")
    parser.add_argument("source", nargs="?", help="World SZS or saved native project JSON")
    parser.add_argument("--preview", action="store_true", help="Open original three-node island preview instead")
    args = parser.parse_args(argv)
    root = tk.Tk()
    if args.preview:
        WorldStudio(root)
    else:
        from .project import WorldProject
        source = Path(args.source) if args.source else Path(__file__).resolve().parents[1] / "NSMBU Modding Project/content/Common/course_select/CS_W1.szs"
        try:
            native = WorldProject.load(source) if source.suffix.lower() == ".json" else WorldProject.open(source)
            NativeStudio(root, native,
                         project_path=source if source.suffix.lower() == ".json" else None)
        except (OSError, ValueError, KeyError) as error:
            messagebox.showerror("Cannot open native world", str(error), parent=root)
            root.destroy()
            return 1
    root.mainloop()
    return 0


if __name__ == "__main__":
    main()
