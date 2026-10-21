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
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from .mesh import MAX_FACE_CORNERS, transform_obj_geometry
from .recent_projects import RecentProjects
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


def obj_geometry_summary(vertices, faces):
    """Describe OBJ source counts without implying native export support."""
    label = "face" if len(faces) == 1 else "faces"
    return f"{len(vertices):,} vertices · {len(faces):,} polygon {label}"


def apply_obj_transform(geometry, settings):
    vertices, faces, uvs, normals = geometry
    return transform_obj_geometry(vertices, faces, uvs, normals, **settings)


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
                              ("Save project", self.save), ("Import OBJ", self.import_obj),
                              ("Add node", self.add_node), ("Add route", self.add_route),
                              ("Delete selected", self.delete), ("Validate", self.validate),
                              ("3D model preview", self.open_3d_preview), ("Fit view", self.fit)]:
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
        self.viewport_hint = ttk.Label(self, text="Graph editor preview: drag to orbit · wheel to zoom · click a node to edit. "
                  "Use 3D model preview for depth-tested world geometry.", padding=(10, 5), foreground="#9fb4c7")
        self.viewport_hint.pack(fill="x")
        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8)
        self.canvas = tk.Canvas(body, background="#101d29", highlightthickness=0)
        body.add(self.canvas, weight=4)
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
        ttk.Label(panel, text="Camera (editor preview)", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(12, 4))
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

    def clear_tree_filter(self):
        self.tree_filter_var.set("")
        self.refresh()

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
            return (required.issubset(payload) and
                    isinstance(payload["points"], list) and
                    isinstance(payload["routes"], list) and
                    isinstance(payload["positions"], dict) and
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
                self.mesh = read_obj(terrain)
            except (OSError, ValueError) as error:
                self.status.set(f"Terrain unavailable: {error}")

    def open_3d_preview(self):
        """Build the offline preview in a worker so Tk remains responsive."""
        if not hasattr(self, "native"):
            # The lightweight OBJ editor has no shared native state or export
            # worker lifecycle. Keep its existing direct preview path intact.
            try:
                self.status.set(self._build_3d_preview(None))
            except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
                self.status.set(f"3D preview unavailable: {error}")
                messagebox.showerror("3D preview unavailable", str(error), parent=self)
            return
        if getattr(self, "exporting", False):
            return
        try:
            # view_project reads Tk variables, so capture its detached graph on
            # the UI thread before the worker starts.
            graph = self.view_project()
        except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
            self.status.set(f"3D preview unavailable: {error}")
            messagebox.showerror("3D preview unavailable", str(error), parent=self)
            return
        self.set_export_busy(True)
        self.status.set("Building the 3D preview in the background… editor controls are locked.")

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
        self.after(60, self.poll_preview)

    def poll_preview(self):
        try:
            succeeded, result = self.preview_results.get_nowait()
        except queue.Empty:
            self.after(60, self.poll_preview)
            return
        if succeeded is None:
            self.status.set(result)
            self.after(60, self.poll_preview)
            return
        self.set_export_busy(False)
        if succeeded:
            self.status.set(result)
        else:
            self.status.set(f"3D preview failed: {result}")
            messagebox.showerror("3D preview unavailable", str(result), parent=self)

    def _build_3d_preview(self, graph, progress=None):
        """Build and open a preview using the locked editor's read-only state."""
        def report(message):
            if progress is not None:
                progress(message)

        nodes, routes = [], []
        try:
            if hasattr(self, "native"):
                from .mesh import DEFAULT_SHAPE, _geometry, extract_rigid_model
                from .preview_textures import (attach_base_color_textures,
                                               attach_sampler_diagnostic_textures,
                                               attach_normal_map_textures,
                                               attach_texture_srt_parameters)
                report("Preview: reading static BFRES geometry…")
                shapes = extract_rigid_model(self.native.model)
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
                    report("Preview: decoding supported material and texture maps…")
                    textures, warned_materials = attach_base_color_textures(self.native.model, shapes)
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
                        except (OSError, ValueError, TypeError, OverflowError) as error:
                            shader_metadata_issue = str(error)
                textured_shapes = sum(bool(shape.get("texture")) for shape in shapes)
                normal_textured_shapes = sum(bool(shape.get("normalTexture")) for shape in shapes)
                texture_notice = (
                    f"BC1/BC3 base-color maps: {len(textures)} unique textures on {textured_shapes} UV meshes. "
                    "Alpha below 50% is cut out; material settings, light maps, game shaders and animation are not evaluated."
                )
                if warned_materials:
                    texture_notice += f" {len(warned_materials)} material(s) use approximate colors."
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
                    vertices, indices, normals, uvs = _geometry(
                        geometry["vertices"], geometry["faces"], geometry.get("uvs"), geometry.get("normals"))
                    for shape in shapes:
                        if shape["name"] == DEFAULT_SHAPE:
                            shape.update(positions=vertices, normals=normals, indices=indices,
                                         material="World Studio imported grass mesh")
                            if uvs is not None and all(uv is not None for uv in uvs):
                                shape["uvs"] = uvs
                            else:
                                shape.pop("uvs", None)
                            break
                visible_nodes = {n["id"]: n for n in graph["nodes"]
                                 if not n.get("fallback") and all(type(n.get(k)) in (int, float) for k in ("x", "y", "z"))}
                nodes = [{"id": n["id"], "x": float(n["x"]), "y": float(n["y"]), "z": float(n["z"])}
                         for n in visible_nodes.values()]
                for route in graph["routes"]:
                    if route.get("start") in visible_nodes and route.get("end") in visible_nodes:
                        routes.append({"start": route["start"], "end": route["end"],
                                       "kind": "secret" if route.get("unlock") == "secret" else "normal"})
                title = f"{self.native.source.name} · W1 world"
                model_name = "CS_W1_World • native BFRES static geometry"
                badges = ["BFRES source", "Static rest pose",
                          f"BC1/BC3 textures ×{len(textures)}" if textures else "Approximate materials"]
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
                shapes = [{"name": "Imported OBJ", "material": "Preview mesh", "positions": vertices,
                           "normals": normals, "indices": indices}]
                title = "World Studio · imported mesh"
                model_name = "OBJ • 3D mesh preview"
                badges = ["OBJ source", "Read-only preview"]
            from .preview3d import open_preview
            report("Preview: packing geometry and opening the WebGL page…")
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
            open_preview(scene)
            return f"3D preview opened · {len(shapes)} shapes · {triangle_count:,} triangles"
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
            self.canvas.create_line(a[:2], b[:2], fill="#65b9c6" if geometry else "#f2c65e",
                                    width=2 if geometry else 4, arrow="none" if geometry else "last")
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
            path = Path(path)
            project = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(project, dict):
                raise ValueError("Not a World Studio preview project object")
            if project.get("format") != "worldstudio-preview-v1":
                raise ValueError("Not a World Studio preview project")
            issues = validate_preview(project)
            if issues:
                raise ValueError("\n".join(issues))
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
        path = filedialog.askopenfilename(filetypes=[("Wavefront OBJ", "*.obj")], parent=self)
        if path:
            try:
                mesh, compatibility_warnings = read_obj(path, include_report=True)
                transform = ObjTransformDialog(self.winfo_toplevel())
                if transform.result is None:
                    return
                mesh = apply_obj_transform((*mesh, None, None), transform.result)[:2]
                self.project["terrain"], self.mesh = str(Path(path).resolve()), mesh
                self.dirty = True
                self._record_edit()
                self.fit()
                self.status.set(f"OBJ preview imported · {obj_geometry_summary(*mesh)} · "
                                f"{obj_transform_summary(transform.result)}. BFRES export is not implemented."
                                + (" Compatibility: " + "; ".join(compatibility_warnings) + "."
                                   if compatibility_warnings else ""))
            except (OSError, ValueError) as error:
                messagebox.showerror("Cannot import OBJ", str(error), parent=self)

    def close(self):
        if self.may_discard():
            self.master.destroy()


class NativeStudio(WorldStudio):
    """Edit native point/route tables while preserving unsupported columns."""

    def __init__(self, master, native, project_path=None):
        self.native = native
        self.exporting = False
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
        self.canvas.bind("<Map>", self._schedule_auto_fit, add="+")
        self.canvas.bind("<Configure>",
                         lambda event: self._schedule_auto_fit(event, delay_ms=90), add="+")
        self.after_idle(self._schedule_auto_fit)
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
        self.viewport_hint.configure(text="Graph editor: drag a point to move it in the camera plane · drag empty space to orbit · wheel to zoom · click a point to edit. Open 3D model preview for depth-tested BFRES geometry.")
        self.description.configure(text="Native point/segment fields are saved to CSV and exported in the SZS archive. "
            "Known bone XYZ edits modify BFRES; model names and engine indices remain protected. "
            "Camera controls affect this viewport only. Import OBJ previews terrain. Use OBJ mesh replaces one existing grass mesh experimentally; other terrain remains.")
        toolbar = self.winfo_children()[0]
        replacements = {"New preview": "Reload source", "Add node": "Add draft point", "Add route": "Add segment"}
        for child in toolbar.winfo_children():
            if isinstance(child, ttk.Button) and child.cget("text") in replacements:
                child.configure(text=replacements[child.cget("text")])
        bar = ttk.Frame(self, padding=(8, 0))
        bar.pack(fill="x", before=self.winfo_children()[1])
        ttk.Button(bar, text="Open native world SZS", command=self.open_szs).pack(side="left", padx=2)
        ttk.Button(bar, text="Export validated SZS", command=self.export_szs).pack(side="left", padx=2)
        ttk.Button(bar, text="Use OBJ mesh (experimental)", command=self.use_obj_mesh).pack(side="left", padx=2)
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
        self._finish_tree_refresh(selection, shown, total)
        if not selection or not self.tree.selection():
            self.tree.yview_moveto(0)
        self.draw()

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
        kind, index = selection[0].split(":", 1)
        if kind == "bone":
            self.native_selection = kind, index
            self.selected = ("route", index) if index.startswith("R") else ("node", index)
            for child in self.form.winfo_children():
                child.destroy()
            self.properties, self.position_properties = {}, {}
            bones = self.native.skeletons.models[self.native.path_model]
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
            entry = ttk.Entry(self.form, textvariable=var)
            entry.grid(row=i, column=1, sticky="ew", padx=(5, 0), pady=3)
            if ((kind == "point" and i in (0, 1)) or
                    (kind == "segment" and i == 0)):
                entry.configure(state="readonly")
        if kind == "point":
            self.show_native_position(row[1], len(row))
        self.form.columnconfigure(1, weight=1)
        self.draw()

    def show_native_position(self, name, start):
        actual = name in self.native.positions
        position = self.native.positions.get(name) or self.native.layout.get(name) or [0, 0, 0]
        caption = "BFRES local XYZ — child paths move with their parent" if actual else "Preview layout XYZ — does not change game transforms"
        if actual and name not in self.native.world_positions:
            caption += "; rest transform unsupported, displayed as layout"
        ttk.Label(self.form, text=caption, wraplength=290).grid(row=start, columnspan=2, sticky="w", pady=(8, 3))
        for offset, key in enumerate(("x", "y", "z")):
            ttk.Label(self.form, text=key).grid(row=start + offset + 1, column=0, sticky="w")
            var = tk.StringVar(value=str(position[offset]))
            self.position_properties[key] = var
            ttk.Entry(self.form, textvariable=var).grid(row=start + offset + 1, column=1, sticky="ew", padx=(5, 0), pady=3)

    def apply(self):
        if self.exporting:
            return
        selection = getattr(self, "native_selection", None)
        if selection is None:
            return
        kind, index = selection
        try:
            position = [float(self.position_properties[k].get()) for k in ("x", "y", "z")] if kind in ("point", "bone") else None
            if position and not all(math.isfinite(value) for value in position):
                raise ValueError("Coordinates must be finite")
        except ValueError as error:
            messagebox.showerror("Invalid coordinates", str(error), parent=self)
            return
        if kind == "bone":
            self.native.positions[index] = position
            self.dirty = True
            self._record_edit()
            self.refresh()
            self.status.set(f"Updated {index} local XYZ; hierarchy rest positions refreshed. Animation behavior remains unverified.")
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

    def add_route(self):
        if self.exporting:
            return
        name = simpledialog.askstring("Draft segment", "Existing BFRES route segment name (R + two four-character points):", parent=self)
        if name:
            self.native.routes.rows.append([name.strip(), "道", ""])
            self.dirty = True
            self._record_edit()
            self.refresh()

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
        issues = self.native.validate()
        messagebox.showinfo("Native resource validation", "\n".join(issues[:35]) if issues else
                            "Native graph and model references pass static validation.\nGame behavior still requires Cemu testing.", parent=self)

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
        path = filedialog.askopenfilename(filetypes=[("Wavefront OBJ preview", "*.obj")], parent=self)
        if path:
            try:
                mesh, compatibility_warnings = read_obj(path, include_report=True)
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
                self.status.set(f"OBJ preview imported · {obj_geometry_summary(*mesh)} · "
                                f"{obj_transform_summary(transform.result)}; native mesh replacement is disabled."
                                + (" Compatibility: " + "; ".join(compatibility_warnings) + "."
                                   if compatibility_warnings else ""))
            except (OSError, ValueError) as error:
                messagebox.showerror("Cannot import OBJ", str(error), parent=self)

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
        path = filedialog.askopenfilename(filetypes=[("Experimental grass mesh OBJ", "*.obj")], parent=self)
        if path:
            try:
                (vertices, faces, uvs, normals), compatibility_warnings = read_obj(
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
                self.status.set(f"Experimental OBJ candidate · {obj_geometry_summary(vertices, faces)} · "
                                f"{obj_transform_summary(transform.result)}. Replaces one existing grass mesh; "
                                "capacity and layout checks run during export."
                                + (" Compatibility: " + "; ".join(compatibility_warnings) + "."
                                   if compatibility_warnings else ""))
            except (OSError, ValueError) as error:
                messagebox.showerror("Cannot use OBJ mesh", str(error), parent=self)

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
                if isinstance(widget, (ttk.Button, ttk.Entry, ttk.Checkbutton, ttk.Scale, ttk.Treeview)) and not widget.instate(["disabled"]):
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
            self.status.set(f"Exported verified archive: {result.get('output', '')}. {terrain}Cemu verification is still required.")
        else:
            self.status.set(f"Export failed: {result}")
            messagebox.showerror("Export failed", str(result), parent=self)

    def export_szs(self):
        if self.exporting:
            return
        issues = self.native.validate()
        if issues:
            messagebox.showerror("Export blocked", "\n".join(issues[:35]), parent=self)
            return
        path = filedialog.asksaveasfilename(defaultextension=".szs", filetypes=[("New world mod archive", "*.szs")], initialfile=self.native.source.name, parent=self)
        if path:
            native = self.native
            self.set_export_busy(True)
            self.status.set("Exporting and compressing Yaz0… controls are locked while archive verification runs.")
            def worker():
                try:
                    self.export_results.put((True, native.export(path)))
                except Exception as error:
                    # The worker never accesses Tk; all status/dialog work occurs
                    # in poll_export on the GUI thread, including unexpected errors.
                    self.export_results.put((False, str(error)))
            threading.Thread(target=worker, name="worldstudio-export", daemon=True).start()
            self.after(60, self.poll_export)


class ObjTransformDialog(tk.Toplevel):
    """Choose import-space conversion without modifying the OBJ source file."""

    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("OBJ coordinates and scale")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        ttk.Label(self, text="Convert OBJ into the world-map model space",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=16, pady=(14, 5))
        ttk.Label(self, text="Scale is applied first, then rotation X → Y → Z, then translation. "
                  "Coordinates are local model units; the source OBJ remains unchanged.",
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
            messagebox.showerror("Invalid OBJ transform", str(error), parent=self)
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
