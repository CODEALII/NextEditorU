"""Dependency-free 3D inspection/editor shell and native CSV/BFRES editor.

The perspective viewport is an editor preview, never proof of in-game behavior.
OBJ preview import is separate from explicit experimental native mesh replacement.
"""
from __future__ import annotations

import copy
import json
import math
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk


def read_obj(path):
    """Read vertex/face geometry, including OBJ negative vertex indices."""
    vertices, faces = [], []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        fields = line.split("#", 1)[0].split()
        if not fields:
            continue
        if fields[0] == "v":
            xyz = tuple(float(value) for value in fields[1:4])
            if len(xyz) != 3 or not all(math.isfinite(v) for v in xyz):
                raise ValueError("OBJ vertex must contain three finite coordinates")
            vertices.append(xyz)
        elif fields[0] == "f":
            face = []
            for item in fields[1:]:
                index = int(item.split("/")[0])
                if index == 0:
                    raise ValueError("OBJ vertex indices start at one")
                index = index - 1 if index > 0 else len(vertices) + index
                if not 0 <= index < len(vertices):
                    raise ValueError("OBJ face references a missing vertex")
                face.append(index)
            if len(face) < 3:
                raise ValueError("OBJ face must contain at least three vertices")
            faces.append(tuple(face))
    if not vertices or not faces:
        raise ValueError("OBJ needs vertices and polygon faces")
    return vertices, faces


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
    if not isinstance(project, dict) or not isinstance(project.get("nodes"), list) or not isinstance(project.get("routes"), list):
        return ["Project must contain node and route lists"]
    if not all(isinstance(item, dict) for item in project["nodes"] + project["routes"]):
        return ["Nodes and routes must be objects"]
    issues, ids = [], set()
    for node in project.get("nodes", []):
        name = node.get("id", "")
        if not name or name in ids:
            issues.append(f"Empty or duplicate node: {name}")
        ids.add(name)
        if not all(isinstance(node.get(k), (int, float)) and math.isfinite(node[k]) for k in ("x", "y", "z")):
            issues.append(f"Invalid coordinates: {name}")
    adjacency = {name: set() for name in ids}
    route_ids = set()
    for route in project.get("routes", []):
        route_id = route.get("id", "")
        if not route_id or route_id in route_ids:
            issues.append(f"Empty or duplicate route: {route_id}")
        route_ids.add(route_id)
        a, b = route.get("start"), route.get("end")
        if a not in ids or b not in ids:
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


class WorldStudio(ttk.Frame):
    """Visual preview editor; native archive actions may be supplied by a caller."""

    def __init__(self, master, project=None):
        super().__init__(master)
        self.pack(fill="both", expand=True)
        self.project = copy.deepcopy(project or demo_project())
        self.project_path = None
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
        master.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self):
        self.master.title("NSMBU World Studio — preview editor")
        self.master.geometry("1250x780")
        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        for title, action in [("New preview", self.new), ("Open project", self.open),
                              ("Save project", self.save), ("Import OBJ", self.import_obj),
                              ("Add node", self.add_node), ("Add route", self.add_route),
                              ("Delete selected", self.delete), ("Validate", self.validate),
                              ("Fit view", self.fit)]:
            ttk.Button(bar, text=title, command=action).pack(side="left", padx=2)
        self.viewport_hint = ttk.Label(self, text="3D preview: drag to orbit • mouse wheel to zoom • click a node to edit. "
                  "OBJ terrain and preview project events are not game exports.", padding=(10, 5))
        self.viewport_hint.pack(fill="x")
        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8)
        self.canvas = tk.Canvas(body, background="#142331", highlightthickness=0)
        body.add(self.canvas, weight=4)
        sidebar = ttk.Frame(body, width=370)
        body.add(sidebar, weight=1)
        sidebar_canvas = tk.Canvas(sidebar, width=350, highlightthickness=0, background="#f0f0f0")
        sidebar_canvas.pack(side="left", fill="both", expand=True)
        sidebar_scroll = ttk.Scrollbar(sidebar, orient="vertical", command=sidebar_canvas.yview)
        sidebar_scroll.pack(side="right", fill="y")
        sidebar_canvas.configure(yscrollcommand=sidebar_scroll.set)
        panel = ttk.Frame(sidebar_canvas, padding=10)
        panel_window = sidebar_canvas.create_window(0, 0, window=panel, anchor="nw")
        panel.bind("<Configure>", lambda event: sidebar_canvas.configure(scrollregion=sidebar_canvas.bbox("all")))
        sidebar_canvas.bind("<Configure>", lambda event: sidebar_canvas.itemconfigure(panel_window, width=event.width))
        ttk.Label(panel, text="Nodes and routes", font=("Segoe UI", 12, "bold")).pack(anchor="w")
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

    def camera_change(self, key, value):
        self.project.setdefault("camera", {})[key] = float(value)
        self.draw()

    def _load_mesh(self):
        self.mesh = ([], [])
        path = self.project.get("terrain")
        if path:
            try:
                self.mesh = read_obj(path)
            except (OSError, ValueError) as error:
                self.status.set(f"Terrain unavailable: {error}")

    def project_point(self, point):
        camera = self.project.setdefault("camera", {})
        yaw, pitch = camera.get("yaw", -0.55), camera.get("pitch", 0.65)
        x, y, z = [point[i] - self.center[i] for i in range(3)]
        x, z = x * math.cos(yaw) - z * math.sin(yaw), x * math.sin(yaw) + z * math.cos(yaw)
        y, z = y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)
        view_scale = camera.get("scale", 1)
        scale = view_scale * 900 / max(100, 900 + z * view_scale)
        return self.canvas.winfo_width() / 2 + x * scale, self.canvas.winfo_height() / 2 - y * scale, z

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
        for route in self.project.get("routes", []):
            if route.get("start") not in nodes or route.get("end") not in nodes:
                continue
            a, b = [self.project_point(tuple(nodes[name][k] for k in ("x", "y", "z")))
                    for name in (route["start"], route["end"])]
            self.canvas.create_line(a[:2], b[:2], fill="#f2c65e", width=4, arrow="last")
            self.canvas.create_text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 14,
                                    text=route.get("unlock", route["id"]), fill="#f2deb3")
        for name, node in nodes.items():
            x, y, _ = self.project_point(tuple(node[k] for k in ("x", "y", "z")))
            color = "#ffffff" if self.selected == ("node", name) else "#f1c75f"
            self.canvas.create_oval(x - 8, y - 8, x + 8, y + 8, fill=color, outline="#102332", width=3)
            self.canvas.create_text(x, y - 21, text=f"{name}  {node.get('level', '')}", fill="#ffffff", font=("Segoe UI", 10, "bold"))
            self.hit_points.append((x, y, name))
        self.canvas.create_text(15, 15, anchor="nw", fill="#bdd0dd", text="EDITOR PREVIEW / perspective projection", tags=("viewport_caption",))

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for kind, key in [("node", "nodes"), ("route", "routes")]:
            for index, item in enumerate(self.project.get(key, [])):
                self.tree.insert("", "end", iid=f"{kind}:{index}", text=item["id"], values=(kind,))
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
            if kind == "node" and candidate["id"] != name:
                for route in self.project["routes"]:
                    for key in ("start", "end"):
                        if route[key] == name:
                            route[key] = candidate["id"]
            old.clear()
            old.update(candidate)
            self.selected = kind, candidate["id"]
            self.dirty = True
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
            self.refresh()
            window.destroy()
        ttk.Button(window, text="Create route", command=submit).grid(row=4, columnspan=2, pady=8)

    def delete(self):
        if not self.selected:
            return
        kind, name = self.selected
        key = "nodes" if kind == "node" else "routes"
        self.project[key] = [item for item in self.project[key] if item["id"] != name]
        if kind == "node":
            self.project["routes"] = [r for r in self.project["routes"] if name not in (r["start"], r["end"])]
        self.selected = None
        self.dirty = True
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
        self.project.setdefault("camera", {})["scale"] = max(0.0001, min(self.canvas.winfo_width(), self.canvas.winfo_height()) / max(300, max(high[i] - low[i] for i in range(3)) * 1.6))
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
        answer = messagebox.askyesnocancel("Unsaved preview", "Save project changes before continuing?", parent=self)
        if answer is None:
            return False
        return bool(self.save()) if answer else True

    def new(self):
        if self.may_discard():
            self.project, self.project_path = demo_project(), None
            self.selected, self.dirty = None, False
            self._load_mesh()
            self.refresh()

    def open(self):
        if not self.may_discard():
            return
        path = filedialog.askopenfilename(filetypes=[("World Studio preview", "*.json")], parent=self)
        if not path:
            return
        try:
            project = json.loads(Path(path).read_text(encoding="utf-8"))
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
        except (OSError, ValueError, KeyError, TypeError) as error:
            messagebox.showerror("Cannot open project", str(error), parent=self)

    def save(self):
        path = self.project_path or filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("World Studio preview", "*.json")], parent=self)
        if not path:
            return False
        try:
            destination = Path(path)
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_text(json.dumps(self.project, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            temporary.replace(destination)
            self.project_path, self.dirty = destination, False
            self.status.set(f"Saved preview project: {destination}")
            return True
        except OSError as error:
            messagebox.showerror("Cannot save project", str(error), parent=self)
            return False

    def import_obj(self):
        path = filedialog.askopenfilename(filetypes=[("Wavefront OBJ", "*.obj")], parent=self)
        if path:
            try:
                mesh = read_obj(path)
                self.project["terrain"], self.mesh = str(Path(path).resolve()), mesh
                self.dirty = True
                self.fit()
                self.status.set("Imported OBJ for preview only. BFRES export is not implemented.")
            except (OSError, ValueError) as error:
                messagebox.showerror("Cannot import OBJ", str(error), parent=self)

    def close(self):
        if self.may_discard():
            self.master.destroy()


class NativeStudio(WorldStudio):
    """Edit native point/route tables while preserving unsupported columns."""

    def __init__(self, master, native):
        self.native = native
        self.exporting = False
        self.export_results = queue.Queue()
        self.disabled_for_export = []
        self.show_auxiliary = tk.BooleanVar(master, value=False)
        super().__init__(master, self.view_project())
        self.master.title("NSMBU World Studio — native world resources")
        self.status.set(f"Loaded {native.source.name} • coordinates: " +
                        ("BFRES local XYZ where known; remaining points use editor layout" if native.positions else "editor layout only; game transforms unknown"))
        self.canvas.bind("<Map>", lambda event: self.fit(), add="+")

    def view_project(self):
        nodes, routes = [], []
        points = self.native.points.rows
        for i, row in enumerate(points):
            if len(row) < 2:
                continue
            name = row[1]
            known = name in self.native.positions
            if not self.show_auxiliary.get() and (not name.startswith("W") or not known):
                continue
            position = getattr(self.native, "world_positions", {}).get(name) or self.native.positions.get(name) or self.native.layout.get(name)
            if position is None:
                # Layout is explicitly non-game data, never written to CSV/BFRES.
                angle = i * math.tau / max(1, len(points))
                position = [math.cos(angle) * 220, 0, math.sin(angle) * 220]
            nodes.append(dict(id=name, x=position[0], y=position[1], z=position[2], level="" if name in self.native.positions else "[layout]"))
            for column, route_column, kind in [(3, 4, "normal"), (6, 7, "secret")]:
                if len(row) > route_column:
                    for destination in row[column].split(","):
                        if destination:
                            routes.append(dict(id=f"{name}:{kind}:{destination}", start=name,
                                               end=destination, unlock=kind))
        return {"format": "native-view", "nodes": nodes, "routes": routes,
                "camera": getattr(self, "project", {}).get("camera", {"yaw": -0.55, "pitch": 0.65, "scale": 1}),
                "terrain": self.native.terrain}

    def _build(self):
        super()._build()
        self.viewport_hint.configure(text="Drag to orbit • wheel to zoom • Import OBJ = preview • Use OBJ mesh = experimental native replacement of one grass mesh; other terrain remains.")
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
        ttk.Checkbutton(bar, text="Show auxiliary points / layouts", variable=self.show_auxiliary,
                        command=self.toggle_auxiliary).pack(side="left", padx=10)

    def refresh(self):
        self.project = self.view_project()
        self.tree.delete(*self.tree.get_children())
        for kind, rows in [("point", self.native.points.rows), ("segment", self.native.routes.rows)]:
            for index, row in enumerate(rows):
                name = row[1] if kind == "point" and len(row) > 1 else row[0]
                self.tree.insert("", "end", iid=f"{kind}:{index}", text=name, values=(kind,))
        self.tree.yview_moveto(0)
        self.draw()

    def toggle_auxiliary(self):
        self.refresh()
        self.fit()

    def draw(self):
        super().draw()
        if hasattr(self, "canvas"):
            label = "NATIVE WORLD GRAPH / known W* bone positions"
            if self.show_auxiliary.get():
                label += " / [layout] points are editor coordinates"
            self.canvas.itemconfigure("viewport_caption", text=label)

    def select_tree(self, event=None):
        if self.exporting:
            return
        selection = self.tree.selection()
        if not selection:
            return
        kind, index = selection[0].split(":")
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
            if kind == "point" and i in (0, 1):
                entry.configure(state="readonly")
        if kind == "point":
            name = row[1]
            actual = name in self.native.positions
            position = self.native.positions.get(name) or self.native.layout.get(name) or [0, 0, 0]
            caption = "BFRES local XYZ — paths must be adjusted separately" if actual else "Preview layout XYZ — does not change game transforms"
            ttk.Label(self.form, text=caption, wraplength=290).grid(row=len(row), columnspan=2, sticky="w", pady=(8, 3))
            for offset, key in enumerate(("x", "y", "z")):
                ttk.Label(self.form, text=key).grid(row=len(row) + offset + 1, column=0, sticky="w")
                var = tk.StringVar(value=str(position[offset]))
                self.position_properties[key] = var
                ttk.Entry(self.form, textvariable=var).grid(row=len(row) + offset + 1, column=1, sticky="ew", padx=(5, 0), pady=3)
        self.form.columnconfigure(1, weight=1)
        self.draw()

    def apply(self):
        if self.exporting:
            return
        selection = getattr(self, "native_selection", None)
        if selection is None:
            return
        kind, index = selection
        rows = self.native.points.rows if kind == "point" else self.native.routes.rows
        try:
            position = [float(self.position_properties[k].get()) for k in ("x", "y", "z")] if kind == "point" else None
            if position and not all(math.isfinite(value) for value in position):
                raise ValueError("Coordinates must be finite")
        except ValueError as error:
            messagebox.showerror("Invalid coordinates", str(error), parent=self)
            return
        rows[index] = [self.properties[i].get() for i in sorted(self.properties)]
        if position is not None:
            name = rows[index][1]
            target = self.native.positions if name in self.native.positions else self.native.layout
            target[name] = position
        self.dirty = True
        self.refresh()
        self.status.set("Native CSV updated. Validate before export; in-game behavior remains unverified.")

    def add_node(self):
        if self.exporting:
            return
        name = simpledialog.askstring("Draft point", "Model point name (new bones cannot be created; export may be blocked):", parent=self)
        if name:
            self.native.points.rows.append([str(len(self.native.points.rows)), name.strip(), "", "", "", "", "", "", ""])
            self.dirty = True
            self.refresh()
            self.status.set("Draft point added. New engine indices require script remapping and cannot currently export.")

    def add_route(self):
        if self.exporting:
            return
        name = simpledialog.askstring("Draft segment", "Existing BFRES route segment name (R + two four-character points):", parent=self)
        if name:
            self.native.routes.rows.append([name.strip(), "道", ""])
            self.dirty = True
            self.refresh()

    def delete(self):
        if self.exporting:
            return
        selection = getattr(self, "native_selection", None)
        if selection is None:
            return
        kind, index = selection
        rows = self.native.points.rows if kind == "point" else self.native.routes.rows
        del rows[index]
        self.native_selection = self.selected = None
        self.dirty = True
        self.refresh()
        for child in self.form.winfo_children():
            child.destroy()
        self.status.set("Draft deletion. Point index changes block export until engine/script remapping exists.")

    def release(self, event):
        if self.drag and not self.drag[2]:
            for x, y, name in self.hit_points:
                if (event.x - x) ** 2 + (event.y - y) ** 2 < 225:
                    index = next(i for i, row in enumerate(self.native.points.rows) if row[1] == name)
                    self.tree.selection_set(f"point:{index}")
                    self.tree.see(f"point:{index}")
                    self.select_tree()
                    break
        self.drag = None

    def validate(self):
        issues = self.native.validate()
        messagebox.showinfo("Native resource validation", "\n".join(issues[:35]) if issues else
                            "Native graph and model references pass static validation.\nGame behavior still requires Cemu testing.", parent=self)

    def open_szs(self):
        if not self.may_discard():
            return
        path = filedialog.askopenfilename(filetypes=[("World resource", "*.szs")], parent=self)
        if path:
            try:
                from .project import WorldProject
                native = WorldProject.open(path)
                self.replace_native(native, None)
            except (OSError, ValueError) as error:
                messagebox.showerror("Cannot open world", str(error), parent=self)

    def replace_native(self, native, project_path):
        if self.exporting:
            return
        self.native, self.project_path = native, project_path
        self.native_selection = self.selected = None
        self.dirty = False
        self.project = self.view_project()
        self._load_mesh()
        self.refresh()
        self.fit()
        for child in self.form.winfo_children():
            child.destroy()
        self.status.set(f"Opened {native.source.name}; " + ("BFRES local XYZ where known; remaining points use editor layout" if native.positions else "editor layout; game coordinates unavailable"))

    def open(self):
        if not self.may_discard():
            return
        path = filedialog.askopenfilename(filetypes=[("Native World Studio project", "*.json")], parent=self)
        if path:
            try:
                from .project import WorldProject
                self.replace_native(WorldProject.load(path), Path(path))
            except (OSError, ValueError, KeyError, TypeError) as error:
                messagebox.showerror("Cannot open project", str(error), parent=self)

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
            self.native.save(path)
            self.project_path, self.dirty = Path(path), False
            self.status.set(f"Saved native project: {path}")
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
                mesh = read_obj(path)
                self.native.terrain = str(Path(path).resolve())
                self.native.geometry = None
                self.mesh = mesh
                self.dirty = True
                self.refresh()
                self.fit()
                self.status.set("OBJ imported for preview only; experimental native mesh replacement is disabled.")
            except (OSError, ValueError) as error:
                messagebox.showerror("Cannot import OBJ", str(error), parent=self)

    def use_obj_mesh(self):
        if self.exporting:
            return
        path = filedialog.askopenfilename(filetypes=[("Experimental grass mesh OBJ", "*.obj")], parent=self)
        if path:
            try:
                vertices, faces = read_obj(path)
                self.native.geometry = {"vertices": vertices, "faces": faces}
                self.native.terrain = str(Path(path).resolve())
                self.mesh = vertices, faces
                self.dirty = True
                self.refresh()
                self.fit()
                self.status.set("Experimental OBJ selected: replaces one grass mesh in BFRES; other terrain remains. Capacity/layout checks run during export.")
            except (OSError, ValueError) as error:
                messagebox.showerror("Cannot use OBJ mesh", str(error), parent=self)

    def may_discard(self):
        if self.exporting:
            self.status.set("Export is running. Wait for verification before changing or closing the project.")
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
            NativeStudio(root, native)
        except (OSError, ValueError, KeyError) as error:
            messagebox.showerror("Cannot open native world", str(error), parent=root)
            root.destroy()
            return 1
    root.mainloop()
    return 0


if __name__ == "__main__":
    main()
