"""Hidden Tk regression checks for bone edits and world/local separation."""
from pathlib import Path
from types import ModuleType, SimpleNamespace
import tkinter as tk
from tkinter import ttk
import threading
import time
import tempfile
import unittest
import json
from unittest.mock import patch

from worldstudio.editor import (CameraDataWindow, NativeStudio, ObjTransformDialog, PathChainDialog,
                                WorldStudio, demo_project, fit_preview_scale,
                                project_preview_point)
from worldstudio.camera import OffsetTable
from worldstudio.recent_projects import RecentProjects
from worldstudio.project import WorldProject, resolve_project_path
from worldstudio.session_recovery import SessionRecovery


class NativeFixture:
    def __init__(self):
        self.source = Path("synthetic.szs")
        self.points = SimpleNamespace(rows=[
            ["0", "W101", "", "W102", "RW101W102", "", "", "", ""],
            ["1", "W102", "", "", "", "", "", "", ""],
            ["2", "F001", "", "", "", "", "", "", ""],
            ["3", "Fbad", "", "", "", "", "", "", ""]])
        self.routes = SimpleNamespace(rows=[["RF001K001", "road", ""]],
                                       initial=[["RF001K001", "road", ""]])
        self.path_model = "Primary"
        names = ["W101", "W102", "F001", "K001", "RF001K001", "Fbad"]
        self.skeletons = SimpleNamespace(models={"Primary": [
            SimpleNamespace(name=name, index=i, parent=0 if i else -1, model="Primary")
            for i, name in enumerate(names)]})
        self.references = set(names) | {"RW102F001"}
        self.positions = dict(zip(names, ([100, 0, 0], [300, 0, 0], [10, 0, 0], [20, 0, 0], [4, 0, 0], [999999, 0, 0])))
        self.layout, self.terrain, self.geometry = {}, None, None
        self.camera_tables = {"MarioOffsetDataW1.bin": OffsetTable.parse(bytes(5376), "mario")}
        self.camera_edits = {}

    def camera_table(self, filename):
        table = self.camera_tables[filename]
        for key, vector in self.camera_edits.get(filename, {}).items():
            bank, index = map(int, key.split(":"))
            table = table.with_vector(bank, index, vector)
        return table

    def set_camera_vector(self, filename, bank, index, vector):
        self.camera_edits.setdefault(filename, {})[f"{bank}:{index}"] = list(vector)

    @property
    def world_positions(self):
        # Deterministic synthetic hierarchy; Fbad deliberately unsupported.
        origin = self.positions["W101"][0]
        return {"W101": list(self.positions["W101"]), "W102": list(self.positions["W102"]),
                "F001": [origin + self.positions["F001"][0], 0, 0],
                "K001": [origin + self.positions["K001"][0], 0, 0],
                "RF001K001": [origin + self.positions["RF001K001"][0], 0, 0]}

    def validate(self):
        return []


class PerspectiveFitTests(unittest.TestCase):
    def test_fit_scale_keeps_rotated_depth_bounds_inside_the_canvas(self):
        points = [(-900, -240, -1250), (840, 420, 950), (120, 180, 1450),
                  (-160, 310, -420)]
        center = (-30, 90, 100)
        yaw, pitch, width, height = -0.55, 0.65, 1100, 760
        scale = fit_preview_scale(points, center, yaw, pitch, width, height)
        margin = min(56, max(18, min(width, height) * 0.06))
        projected = [project_preview_point(point, center, yaw, pitch, scale, width, height)
                     for point in points]
        self.assertGreater(scale, 0.0001)
        self.assertTrue(all(margin <= x <= width - margin and
                            margin <= y <= height - margin for x, y, _ in projected))

    def test_fit_scale_uses_the_resized_viewport_and_rejects_nonfinite_bounds(self):
        points = [(-600, 0, -700), (600, 0, 700)]
        center = (0, 0, 0)
        small = fit_preview_scale(points, center, -0.55, 0.65, 900, 600)
        large = fit_preview_scale(points, center, -0.55, 0.65, 1600, 900)
        self.assertGreater(large, small)
        with self.assertRaises(ValueError):
            fit_preview_scale([(float("inf"), 0, 0)], center, 0, 0, 800, 600)


class EditorSmokeTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk unavailable: {error}")
        self.root.withdraw()
        self.native = NativeFixture()
        self.app = NativeStudio(self.root, self.native)
        self.recent_tmp = tempfile.TemporaryDirectory()
        self.app.recent_projects = RecentProjects(Path(self.recent_tmp.name) / "recent.json")
        self.root.update()

    def tearDown(self):
        if hasattr(self, "root"):
            if hasattr(self, "app"):
                self.app.may_discard = lambda: True
                self.app.close()
            else:
                self.root.destroy()
        if hasattr(self, "recent_tmp"):
            self.recent_tmp.cleanup()

    def test_recent_projects_filter_by_editor_kind_and_respect_cancel(self):
        root = Path(self.recent_tmp.name)
        native_path = root / "world.szs"
        preview_path = root / "preview.json"
        self.app.recent_projects.record(native_path, "native")
        self.app.recent_projects.record(preview_path, "preview")
        self.assertEqual([Path(item["path"]).name for item in self.app.recent_project_entries()],
                         ["world.szs"])

        opened = []
        self.app.dirty = True
        self.app.may_discard = lambda: False
        self.app.open_project_path = lambda path: opened.append(path)
        self.app.open_recent_project(str(native_path))
        self.assertEqual(opened, [])

    def test_saved_preview_session_can_recover_after_restart(self):
        root = Path(self.recent_tmp.name)
        project_path = root / "preview.json"
        top = tk.Toplevel(self.root)
        top.withdraw()
        preview = WorldStudio(top)
        preview.recent_projects = RecentProjects(root / "preview-recents.json")
        preview.recovery_store = SessionRecovery(root / "recoveries")
        preview.recovery_delay_ms = 5
        preview.project_path = project_path
        try:
            self.assertTrue(preview.save())
            preview._set_recovery_context(project_path)
            preview.project["nodes"][0]["x"] = 42
            preview.dirty = True
            preview._record_edit()
            deadline = time.monotonic() + 0.5
            while not preview.recovery_store.path_for(project_path, "preview").exists() and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.005)
            self.assertTrue(preview.recovery_store.path_for(project_path, "preview").is_file())

            preview.project["nodes"][0]["x"] = 0
            preview.dirty = False
            with patch("worldstudio.editor.messagebox.askyesno", return_value=True):
                preview._offer_recovery()

            self.assertEqual(preview.project["nodes"][0]["x"], 42)
            self.assertTrue(preview.dirty)
            self.assertTrue(preview.history.can_undo is False)
            with patch("worldstudio.editor.messagebox.askyesnocancel", return_value=False):
                self.assertTrue(preview.may_discard())
            self.assertIsNone(preview.recovery_store.load(
                project_path, "preview", preview._recovery_baseline_sha256))
        finally:
            top.destroy()

    def test_saved_native_session_can_recover_after_restart(self):
        root = Path(self.recent_tmp.name)
        project_path = root / "native-project.json"
        project_path.write_text('{"saved": true}', encoding="utf-8")
        self.app.recovery_store = SessionRecovery(root / "recoveries")
        self.app.recovery_delay_ms = 5
        self.app._set_recovery_context(project_path)
        try:
            self.native.positions["K001"][0] = 88
            self.app.dirty = True
            self.app._record_edit()
            deadline = time.monotonic() + 0.5
            recovery_path = self.app.recovery_store.path_for(project_path, "native")
            while not recovery_path.exists() and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.005)
            self.assertTrue(recovery_path.is_file())

            self.native.positions["K001"][0] = 20
            self.app.dirty = False
            with patch("worldstudio.editor.messagebox.askyesno", return_value=True):
                self.app._offer_recovery()

            self.assertEqual(self.native.positions["K001"][0], 88)
            self.assertTrue(self.app.dirty)
            with patch("worldstudio.editor.messagebox.askyesnocancel", return_value=False):
                self.assertTrue(self.app.may_discard())
            self.assertIsNone(self.app.recovery_store.load(
                project_path, "native", self.app._recovery_baseline_sha256))
        finally:
            self.app._clear_recovery(project_path)
            self.app._set_recovery_context(None)

    def test_native_session_from_szs_recovers_without_modifying_source(self):
        root = Path(self.recent_tmp.name)
        source_path = root / "world.szs"
        original_source = b"synthetic source archive baseline"
        source_path.write_bytes(original_source)
        self.native.source = source_path
        self.app.recovery_store = SessionRecovery(root / "recoveries")
        self.app.recovery_delay_ms = 5
        self.app.replace_native(self.native, None)
        self.assertEqual(self.app._recovery_project_path, source_path)
        try:
            self.native.points.rows[0][2] = "unsaved draft"
            self.app.dirty = True
            self.app._record_edit()
            deadline = time.monotonic() + 0.5
            recovery_path = self.app.recovery_store.path_for(source_path, "native")
            while not recovery_path.exists() and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.005)
            self.assertTrue(recovery_path.is_file())
            self.assertEqual(source_path.read_bytes(), original_source)

            self.native.points.rows[0][2] = ""
            self.app.dirty = False
            with patch("worldstudio.editor.messagebox.askyesno", return_value=True):
                self.app._offer_recovery()

            self.assertEqual(self.native.points.rows[0][2], "unsaved draft")
            self.assertTrue(self.app.dirty)
            self.assertEqual(source_path.read_bytes(), original_source)
        finally:
            self.app._clear_recovery(source_path)
            self.app._set_recovery_context(None)

    def test_auxiliary_uses_world_coordinates_and_omits_macro_points(self):
        self.assertEqual([node["id"] for node in self.app.project["nodes"]], ["W101", "W102"])
        self.app.show_auxiliary.set(True)
        self.app.toggle_auxiliary()
        nodes = {node["id"]: node for node in self.app.project["nodes"]}
        self.assertEqual(nodes["F001"]["x"], 110)
        self.assertEqual(nodes["K001"]["x"], 120)
        self.assertNotIn("RF001K001", nodes)
        self.assertTrue(nodes["Fbad"]["fallback"])
        self.assertNotEqual(nodes["Fbad"]["x"], self.native.positions["Fbad"][0])
        self.assertIn("layout", nodes["Fbad"]["level"])
        self.assertEqual(sum(route.get("style") == "geometry" for route in self.app.project["routes"]), 1)

    def test_native_tree_filter_searches_ids_without_mutating_resources(self):
        points_before = [row[:] for row in self.native.points.rows]
        routes_before = [row[:] for row in self.native.routes.rows]

        self.app.tree_filter_var.set("w102")
        self.app.refresh()

        self.assertEqual(self.app.tree.get_children(), ("point:1",))
        self.assertEqual(self.app.tree_filter_status.cget("text"), "Showing 1 of 7 items")
        self.assertEqual(self.native.points.rows, points_before)
        self.assertEqual(self.native.routes.rows, routes_before)

        self.app.clear_tree_filter()
        self.assertEqual(len(self.app.tree.get_children()), 7)
        self.assertEqual(self.app.tree_filter_status.cget("text"), "7 items")

    def test_add_route_dialog_builds_a_draft_from_an_existing_bfres_segment(self):
        before = [row[:] for row in self.native.routes.rows]
        self.native.points.rows[1][4] = "RW102F001"

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        def complete_dialog():
            dialog = next(child for child in self.app.winfo_children()
                          if isinstance(child, tk.Toplevel))
            controls = list(descendants(dialog))
            combos = [widget for widget in controls if isinstance(widget, ttk.Combobox)]
            self.assertEqual(len(combos), 2)
            combos[0].set("RW102F001")
            combos[1].set("road")
            self.assertIn("listed in native point path fields",
                          self.app.status.get())
            add_button = next(widget for widget in controls
                              if isinstance(widget, ttk.Button) and
                              widget.cget("text") == "Add segment")
            self.assertTrue(add_button.instate(("!disabled",)))
            add_button.invoke()

        self.root.after(0, complete_dialog)
        self.app.add_route()

        self.assertEqual(self.native.routes.rows,
                         before + [["RW102F001", "road", ""]])
        self.assertTrue(self.app.dirty)
        self.assertIn("point destinations and path chains were not changed",
                      self.app.status.get())
        self.app.undo()
        self.assertEqual(self.native.routes.rows, before)

    def test_path_chain_dialog_adds_and_reorders_bfres_ids_preserving_unknown_ids(self):
        def edit_chain():
            dialog = next(child for child in self.root.winfo_children()
                          if isinstance(child, PathChainDialog))
            dialog.choice.set("RW102F001")
            dialog.add_selected()
            dialog.items.selection_clear(0, "end")
            dialog.items.selection_set(2)
            dialog.move_selected(-1)
            dialog.apply()

        dialog = PathChainDialog(
            self.root, "RWbad,RW101W102", ["RW101W102", "RW102F001"])
        self.root.after(0, edit_chain)
        self.root.wait_window(dialog)

        self.assertEqual(dialog.result, "RWbad,RW102F001,RW101W102")

    def test_path_chain_dialog_returns_exact_original_when_untouched(self):
        original = " RWbad , RW101W102 , "

        def apply_unchanged():
            dialog = next(child for child in self.root.winfo_children()
                          if isinstance(child, PathChainDialog))
            dialog.apply()

        dialog = PathChainDialog(self.root, original, ["RW101W102"])
        self.root.after(0, apply_unchanged)
        self.root.wait_window(dialog)

        self.assertEqual(dialog.result, original)

    def test_path_chain_dialog_refreshes_static_route_status_when_order_changes(self):
        def status(tokens):
            reaches = tokens == ["RW101K001", "RK001W103"]
            if reaches:
                return "Ordered chain reaches W103", "#8fd6a4"
            return "Order does not reach W103", "#ffba86"

        def reorder_and_check():
            dialog = next(child for child in self.root.winfo_children()
                          if isinstance(child, PathChainDialog))
            self.assertEqual(dialog.status_label.cget("text"), "Ordered chain reaches W103")
            dialog.items.selection_set(0)
            dialog.move_selected(1)
            self.assertEqual(dialog.status_label.cget("text"), "Order does not reach W103")
            dialog.cancel()

        dialog = PathChainDialog(
            self.root, "RW101K001,RK001W103", ["RW101K001", "RK001W103"],
            chain_status=status)
        self.root.after(0, reorder_and_check)
        self.root.wait_window(dialog)

    def test_point_path_picker_updates_the_selected_row_and_undo_restores_it(self):
        before = self.native.points.rows[0][4]
        self.app.tree.selection_set("point:0")
        self.app.select_tree()
        self.root.update()
        path_variable = self.app.properties[4]
        opened = []

        def finish_dialog():
            dialog = next(child for child in self.root.winfo_children()
                          if isinstance(child, PathChainDialog))
            opened.append(dialog)
            dialog.choice.set("RW102F001")
            dialog.add_selected()
            dialog.apply()

        edit_button = next(
            widget for widget in self.app.form.winfo_children()
            if isinstance(widget, ttk.Button) and widget.cget("text") == "Edit order")
        self.assertTrue(edit_button.instate(("!disabled",)))
        self.root.after(0, finish_dialog)
        edit_button.invoke()

        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0].result, "RW101W102,RW102F001")
        self.assertEqual(path_variable.get(), "RW101W102,RW102F001")
        self.assertIs(self.app.properties[4], path_variable)
        self.assertEqual(self.native.points.rows[0][4], before)
        self.app.apply()
        self.assertEqual(self.native.points.rows[0][4], "RW101W102,RW102F001")
        self.app.undo()
        self.assertEqual(self.native.points.rows[0][4], before)

    def test_point_destination_picker_preserves_unknown_targets_and_undoes(self):
        before = self.native.points.rows[0][3]
        self.app.tree.selection_set("point:0")
        self.app.select_tree()
        self.root.update()
        destination_variable = self.app.properties[3]
        destination_variable.set("W199")
        target_buttons = [widget for widget in self.app.form.winfo_children()
                          if isinstance(widget, ttk.Button) and
                          widget.cget("text") == "Edit targets"]
        self.assertEqual(len(target_buttons), 2)

        def finish_dialog():
            dialog = next(child for child in self.root.winfo_children()
                          if isinstance(child, PathChainDialog))
            self.assertEqual(dialog.title(), "Edit point destinations")
            self.assertNotIn("W101", dialog.value_ids)
            self.assertEqual(tuple(dialog.items.get(0, "end")), ("W199",))
            dialog.choice.set("W102")
            dialog.add_selected()
            dialog.apply()

        edit_button = next(
            widget for widget in self.app.form.winfo_children()
            if isinstance(widget, ttk.Button) and widget.cget("text") == "Edit targets")
        self.root.after(0, finish_dialog)
        edit_button.invoke()

        self.assertEqual(destination_variable.get(), "W199,W102")
        self.assertEqual(self.native.points.rows[0][3], before)
        self.app.apply()
        self.assertEqual(self.native.points.rows[0][3], "W199,W102")
        self.app.undo()
        self.assertEqual(self.native.points.rows[0][3], before)
        self.app.redo()
        self.assertEqual(self.native.points.rows[0][3], "W199,W102")

    def test_camera_table_window_tracks_apply_undo_and_redo(self):
        window = CameraDataWindow(self.app, visible=False)
        self.app.camera_window = window
        window.records.selection_set("0")
        window.select_record()
        window.vector["x"].set("12")
        window.apply()
        self.assertEqual(window.records.item("0", "values")[2], "12.0")

        self.app.undo()
        self.assertEqual(window.records.item("0", "values")[2], "0.0")
        self.assertEqual(window.vector["x"].get(), "0.0")

        self.app.redo()
        self.assertEqual(window.records.item("0", "values")[2], "12.0")
        self.assertEqual(window.vector["x"].get(), "12.0")

    def test_native_tree_filter_clears_properties_when_selected_item_is_hidden(self):
        self.app.tree.selection_set("bone:K001")
        self.root.update()
        self.assertEqual(self.app.native_selection, ("bone", "K001"))
        self.assertTrue(self.app.form.winfo_children())

        self.app.tree_filter_var.set("W101")
        self.app.refresh()
        self.root.update()

        self.assertEqual(self.app.tree.get_children(), ("point:0",))
        self.assertEqual(self.app.tree.selection(), ())
        self.assertIsNone(self.app.selected)
        self.assertIsNone(self.app.native_selection)
        self.assertEqual(self.app.position_properties, {})
        self.assertEqual(self.app.form.winfo_children(), [])

    def test_embedded_viewport_selection_bridge_uses_existing_tree_selection(self):
        self.app._on_viewport_select({"editorId": "point:0"})
        self.assertEqual(self.app.tree.selection(), ("point:0",))
        self.assertEqual(self.app.native_selection, ("point", 0))
        self.app._on_viewport_select({"editorId": "segment:0"})
        self.assertEqual(self.app.tree.selection(), ("segment:0",))
        self.assertEqual(self.app.native_selection, ("segment", 0))
        self.assertEqual(self.app.selected, ("route", "RF001K001"))
        self.app._on_viewport_select({"editorId": "missing:99"})
        self.assertEqual(self.app.tree.selection(), ("segment:0",))

    def test_route_road_type_editor_uses_existing_source_types(self):
        self.app.tree.selection_set("segment:0")
        self.app.select_tree()
        road_type = next(widget for widget in self.app.form.winfo_children()
                         if isinstance(widget, ttk.Combobox))
        self.assertTrue(road_type.instate(("readonly",)))
        self.assertEqual(road_type.cget("values"), ("road",))

    def test_loaded_scene_keeps_3d_and_graph_panes_visible(self):
        calls = []
        self.app._ensure_embedded_view = lambda: None
        self.app._embedded_preview_dir = self.recent_tmp
        self.app.preview_widget = SimpleNamespace(
            load_url=lambda url: calls.append(("load", url)),
            when_ready=lambda callback: calls.append(("ready", callback)),
            ready=False)
        with patch("worldstudio.preview3d.build_document", return_value="<!doctype html>") as build_document:
            self.app._show_embedded_scene({"shapes": [], "nodes": [], "routes": []})
        build_document.assert_called_once_with(
            {"shapes": [], "nodes": [], "routes": []}, embedded=True)

        panes = self.app.view_split.panes()
        self.assertIn(str(self.app.viewport_pane), panes)
        self.assertIn(str(self.app.graph_frame), panes)
        self.assertEqual([kind for kind, _ in calls], ["load", "ready"])
        ready_callback = calls[-1][1]
        ready_callback()

    def test_webview_host_frame_keeps_viewport_pane_managed(self):
        class FakeWebView:
            def __init__(self, frame, **_kwargs):
                self.frame = frame

            def pack(self, **kwargs):
                self.frame.pack(**kwargs)

            def when_failed(self, _callback):
                pass

            def rpc(self, *_args, **_kwargs):
                return lambda callback: callback

        fake_tkwry = ModuleType("tkwry")
        fake_tkwry.WebView = FakeWebView
        fake_tkwry.NewWindowResponse = SimpleNamespace(Deny="deny")
        with patch.dict("sys.modules", {"tkwry": fake_tkwry}):
            self.app._ensure_embedded_view()

        self.assertIn(str(self.app.viewport_pane), self.app.view_split.panes())
        self.assertEqual(self.app.preview_widget.frame.master, self.app.viewport_frame)

    def test_editor_selection_and_point_edits_update_webgl_without_scene_reload(self):
        scripts = []
        self.app.preview_scene = {"shapes": [{"name": "existing BFRES geometry"}]}
        self.app.preview_widget = SimpleNamespace(ready=True, eval_js=scripts.append)
        self.app.tree.selection_set("point:0")
        self.app.select_tree()
        self.assertTrue(any("selectEditorItem(\"point:0\")" in script for script in scripts))

        scripts.clear()
        self.native.positions["W101"][0] = 155
        self.app._update_viewport_overlays()

        self.assertEqual(len(scripts), 2)  # Overlay buffers, then selected-item focus.
        prefix = "window.worldStudioView && window.worldStudioView.updateOverlays("
        self.assertTrue(scripts[0].startswith(prefix))
        payload = json.loads(scripts[0][len(prefix):-2])
        point = next(node for node in payload["nodes"] if node["id"] == "W101")
        self.assertEqual(point["x"], 155)
        self.assertEqual(point["editorId"], "point:0")
        self.assertTrue(any("selectEditorItem(\"point:0\")" in script for script in scripts[1:]))

    def test_embedded_3d_drag_updates_bfres_local_point_and_supports_undo(self):
        self.app.preview_scene = {"shapes": []}
        self.app.preview_widget = SimpleNamespace(ready=True, eval_js=lambda _script: None)
        before = list(self.native.positions["W101"])

        self.assertTrue(self.app._on_viewport_move({
            "editorId": "point:0", "position": [125, 15, 5]}))

        self.assertEqual(self.native.positions["W101"], [125, 15, 5])
        self.assertEqual(self.app.tree.selection(), ("point:0",))
        self.assertTrue(self.app.dirty)
        self.app.undo()
        self.assertEqual(self.native.positions["W101"], before)

    def test_embedded_3d_drag_rejects_noninvertible_child_transform(self):
        before = list(self.native.positions["W102"])
        with patch.object(self.app, "_schedule_viewport_overlay_update") as refresh:
            self.assertFalse(self.app._on_viewport_move({
                "editorId": "point:1", "position": [325, 0, 0]}))
        refresh.assert_called_once_with()
        self.assertEqual(self.native.positions["W102"], before)
        self.assertIn("cannot be inverted safely", self.app.status.get())

    def test_bone_edit_does_not_touch_csv_and_selection_survives(self):
        before = [row[:] for row in self.native.points.rows]
        segments = [row[:] for row in self.native.routes.rows]
        self.app.tree.selection_set("bone:K001")
        self.app.select_tree()
        self.app.position_properties["x"].set("50")
        self.app.apply()
        self.root.update()
        self.assertEqual(self.native.positions["K001"][0], 50)
        self.assertEqual(self.native.world_positions["K001"][0], 150)
        self.assertEqual(self.native.points.rows, before)
        self.assertEqual(self.native.routes.rows, segments)
        self.assertEqual(self.app.tree.selection(), ("bone:K001",))
        self.app.delete()
        self.assertIn("K001", self.native.positions)
        self.app.tree.selection_set("segment:0")
        self.app.select_tree()
        self.app.apply()
        self.assertEqual(self.app.tree.selection(), ("segment:0",))

    def test_native_edits_support_undo_and_redo(self):
        self.app.tree.selection_set("bone:K001")
        self.app.select_tree()
        self.app.position_properties["x"].set("50")
        self.app.apply()
        self.assertEqual(self.native.positions["K001"][0], 50)

        self.app.undo()
        self.assertEqual(self.native.positions["K001"][0], 20)
        self.assertTrue(self.app.history.can_redo)
        self.app.redo()
        self.assertEqual(self.native.positions["K001"][0], 50)

        self.app.tree.selection_set("segment:0")
        self.app.select_tree()
        self.app.properties[1].set("revised-road")
        self.app.apply()
        self.assertEqual(self.native.routes.rows[0][1], "revised-road")
        self.app.undo()
        self.assertEqual(self.native.routes.rows[0][1], "road")
        self.app.redo()
        self.assertEqual(self.native.routes.rows[0][1], "revised-road")

    def test_route_bone_identifier_is_readonly_and_preserved_on_apply(self):
        self.app.tree.selection_set("segment:0")
        self.app.select_tree()
        self.assertTrue(self.app.form.grid_slaves(row=0, column=1)[0].instate(("readonly",)))

        self.app.properties[0].set("RENAMED")  # Defend against direct variable edits.
        self.app.properties[1].set("revised-road")
        self.app.apply()
        self.assertEqual(self.native.routes.rows[0][0], "RF001K001")
        self.assertEqual(self.native.routes.rows[0][1], "revised-road")

        self.app.undo()
        self.assertEqual(self.native.routes.rows[0], ["RF001K001", "road", ""])
        self.app.redo()
        self.assertEqual(self.native.routes.rows[0], ["RF001K001", "revised-road", ""])

    def test_3d_preview_build_runs_off_tk_thread_and_keeps_events_live(self):
        started = threading.Event()
        release = threading.Event()
        worker_results = []

        def build(graph, progress=None):
            worker_results.append((threading.current_thread(), graph))
            if progress is not None:
                progress("Preview: reading test geometry…")
            started.set()
            release.wait(2)
            return {"shapes": [{}], "stats": {"triangles": 1}, "nodes": [], "routes": []}

        self.app._build_3d_preview = build
        self.app._ensure_embedded_view = lambda: None
        self.app._show_embedded_scene = lambda scene: None
        self.app.open_3d_preview()
        self.assertTrue(self.app._preview_building)
        self.assertTrue(started.wait(1))
        callbacks = []
        self.root.after(0, lambda: callbacks.append("responsive"))
        self.root.update()
        self.assertEqual(callbacks, ["responsive"])
        deadline = time.monotonic() + 1
        while "reading test geometry" not in self.app.status.get() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertIn("reading test geometry", self.app.status.get())
        self.assertIsNot(worker_results[0][0], threading.current_thread())
        self.assertEqual([node["id"] for node in worker_results[0][1]["nodes"]], ["W101", "W102"])

        release.set()
        deadline = time.monotonic() + 2
        while self.app._preview_building and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.app._preview_building)
        self.assertIn("3D world ready", self.app.status.get())

    def test_static_preview_loads_a_supported_non_w1_world_model(self):
        root = Path(__file__).resolve().parents[1]
        source = root / "NSMBU Modding Project/content/Common/course_select/CS_W7.szs"
        if not source.is_file():
            self.skipTest("User-provided local W7 dump unavailable")
        source_copy = Path(self.recent_tmp.name) / "CS_W7.szs"
        source_copy.write_bytes(source.read_bytes())
        top = tk.Toplevel(self.root)
        top.withdraw()
        studio = NativeStudio(top, WorldProject.open(source_copy))
        try:
            scene = studio._build_3d_preview(studio.view_project())
            self.assertEqual(scene["model"], "CS_W7_World • native BFRES static geometry")
            self.assertEqual(len(scene["shapes"]), 34)
            self.assertEqual(len(scene["textures"]), 19)
            self.assertEqual(sum(bool(shape.get("texture")) for shape in scene["shapes"]), 33)
            self.assertTrue(all(texture["format"] == 0x31 for texture in scene["textures"].values()))
            self.assertTrue(all("shaderMetadata" not in shape for shape in scene["shapes"]))
            self.assertTrue(scene["nodes"])
            self.assertTrue(all(node.get("editorId", "").startswith(("point:", "bone:"))
                                for node in scene["nodes"]))
            positions = [point for shape in scene["shapes"] for point in shape["positions"]]
            low = [min(point[axis] for point in positions) for axis in range(3)]
            high = [max(point[axis] for point in positions) for axis in range(3)]
            for node in scene["nodes"]:
                self.assertTrue(all(low[axis] <= node[key] <= high[axis]
                                    for axis, key in enumerate(("x", "y", "z"))))
        finally:
            top.destroy()

    def test_lightweight_editor_keeps_its_direct_obj_preview_path(self):
        studio = object.__new__(WorldStudio)
        status = SimpleNamespace(set=lambda value: setattr(status, "value", value))
        studio.status = status
        studio._preview_building = False
        studio._ensure_embedded_view = lambda: None
        studio.preview_widget = None
        studio._build_3d_preview = lambda graph: {"shapes": [], "stats": {"triangles": 0}}
        studio._show_embedded_scene = lambda scene: None

        studio.open_3d_preview()

        self.assertEqual(status.value, "3D world ready · imported preview geometry")

    def test_lightweight_preview_save_keeps_the_previous_project_and_reports_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "preview.json"
            studio = object.__new__(WorldStudio)
            studio.project_path = path
            studio.recent_projects = RecentProjects(Path(folder) / "recent.json")
            studio.project = {"format": "worldstudio-preview-v1", "terrain": None,
                              "nodes": [], "routes": [], "camera": {}}
            studio.dirty = True
            status = SimpleNamespace(set=lambda value: setattr(status, "value", value))
            studio.status = status

            self.assertTrue(studio.save())
            first_save = path.read_bytes()
            studio.project["camera"]["yaw"] = 0.5
            studio.dirty = True

            self.assertTrue(studio.save())

            backup = path.with_name("preview.backup.json")
            self.assertEqual(backup.read_bytes(), first_save)
            self.assertIn(str(backup), status.value)
            self.assertEqual(studio.recent_projects.list("preview"), [
                {"kind": "preview", "path": str(path.resolve())}])

    def test_dragging_a_native_root_point_is_one_undoable_edit(self):
        original = list(self.native.positions["W101"])
        x, y, _ = next(hit for hit in self.app.hit_points if hit[2] == "W101")
        start = SimpleNamespace(x=round(x), y=round(y))
        self.app.press(start)
        self.app.orbit(SimpleNamespace(x=start.x + 24, y=start.y - 10))
        self.app.release(SimpleNamespace(x=start.x + 24, y=start.y - 10))

        moved = list(self.native.positions["W101"])
        self.assertNotEqual(moved, original)
        self.assertEqual(self.app.tree.selection(), ("point:0",))
        self.assertTrue(self.app.history.can_undo)
        self.app.undo()
        self.assertEqual(self.native.positions["W101"], original)
        self.app.redo()
        self.assertEqual(self.native.positions["W101"], moved)

    def test_obj_transform_dialog_z_up_preset_returns_y_up_rotation(self):
        def apply_preset_when_open():
            dialog = next((child for child in self.root.winfo_children()
                           if isinstance(child, ObjTransformDialog)), None)
            if dialog is None:
                self.root.after(5, apply_preset_when_open)
                return
            dialog.set_z_up_preset()
            dialog.apply()

        self.root.after(5, apply_preset_when_open)
        dialog = ObjTransformDialog(self.root)
        self.assertEqual(dialog.result["rotation_degrees"], (-90., 0., 0.))
        self.assertEqual(dialog.result["scale"], (1., 1., 1.))


class PreviewProjectPathTests(unittest.TestCase):
    def test_relative_terrain_survives_open_save_and_save_to_another_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_dir = root / "source"
            terrain_path = source_dir / "assets" / "island.obj"
            terrain_path.parent.mkdir(parents=True)
            terrain_path.write_text("v 0 0 0\n", encoding="utf-8")
            source_project = source_dir / "preview.json"
            source_data = demo_project()
            source_data["terrain"] = "assets/island.obj"
            source_project.write_text(json.dumps(source_data), encoding="utf-8")

            editor = object.__new__(WorldStudio)
            editor.project = None
            editor.project_path = None
            editor.selected = None
            editor.dirty = False
            editor.status = SimpleNamespace(set=lambda value: None)
            editor.recent_projects = RecentProjects(root / "recent.json")
            editor._load_mesh = lambda: None
            editor.refresh = lambda: None
            editor._reset_edit_history = lambda: None
            editor._record_recent_project = lambda path: None
            editor._set_recovery_context = lambda *args, **kwargs: None
            editor._clear_recovery = lambda *args: None

            editor.open_project_path(source_project)
            self.assertEqual(Path(editor.project["terrain"]), terrain_path.resolve())
            self.assertTrue(editor.save())
            same_location = json.loads(source_project.read_text(encoding="utf-8"))
            self.assertEqual(resolve_project_path(same_location["terrain"], source_project),
                             str(terrain_path.resolve()))

            save_as_path = root / "relocated" / "preview-copy.json"
            editor.project_path = None
            with patch("worldstudio.editor.filedialog.asksaveasfilename",
                       return_value=str(save_as_path)):
                self.assertTrue(editor.save())
            relocated = json.loads(save_as_path.read_text(encoding="utf-8"))
            self.assertEqual(resolve_project_path(relocated["terrain"], save_as_path),
                             str(terrain_path.resolve()))

    def test_export_status_surfaces_baked_uv_projection_warning(self):
        editor = object.__new__(NativeStudio)
        status = SimpleNamespace(value="", set=lambda value: setattr(status, "value", value))
        editor.status = status
        editor.export_results = SimpleNamespace(get_nowait=lambda: (True, {
            "output": "world.szs", "terrain_exported": True,
            "geometry": {"baked_uv_projection": {
                "warning": "maximum XZ distance exceeds the review threshold"}}}))
        editor.set_export_busy = lambda busy: None

        editor.poll_export()

        self.assertIn("Baked-light UV review", status.value)
        self.assertIn("Check the export manifest", status.value)


if __name__ == "__main__":
    unittest.main()
