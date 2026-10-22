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
import struct
from unittest.mock import patch

from worldstudio.editor import (CameraDataWindow, NativeStudio, ObjTransformDialog, PathChainDialog,
                                WorldStudio, demo_project, fit_preview_scale,
                                preview_geometry_sha256, project_preview_point, read_import_mesh)
from worldstudio.camera import OffsetTable
from worldstudio.recent_projects import RecentProjects
from worldstudio.graph_profile_preferences import GraphProfilePreferences
from worldstudio.project import WorldProject, resolve_project_path
from worldstudio.session_recovery import SessionRecovery
from worldstudio.graph_validation import build_native_connection_draft


class NativeFixture:
    def __init__(self):
        self.source = Path("synthetic.szs")
        self.source_sha256 = "a" * 64
        self.point_name = "pointW1.csv"
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
        self.recent_tmp = tempfile.TemporaryDirectory()
        self.graph_profile_preferences = GraphProfilePreferences(
            Path(self.recent_tmp.name) / "graph-profiles.json")
        self.app = NativeStudio(self.root, self.native,
                                graph_profile_preferences=self.graph_profile_preferences)
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

    def test_editor_destroy_cancels_pending_recovery_callback(self):
        project_path = Path(self.recent_tmp.name) / "pending-recovery.json"
        project_path.write_text('{"saved": true}', encoding="utf-8")
        self.app._set_recovery_context(project_path)
        self.app.dirty = True
        self.app.recovery_delay_ms = 60_000
        self.app._schedule_recovery()

        self.assertIsNotNone(self.app._recovery_after_id)
        self.app.destroy()
        self.assertIsNone(self.app._recovery_after_id)
        del self.app
        # Processing Tk events after child teardown must not dispatch a stale
        # bound-method callback against the destroyed editor widget.
        self.root.update()

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

    def test_graph_profile_can_be_enabled_and_disabled_in_native_editor(self):
        profile_path = Path(__file__).parents[1] / "profiles" / "w1-core-progression.json"
        with patch("worldstudio.editor.filedialog.askopenfilename", return_value=str(profile_path)):
            self.app.choose_graph_profile()

        self.assertEqual(self.app.graph_profile_path, profile_path)
        self.assertEqual(self.app.graph_profile_label.get(),
                         "Graph check: w1-core-progression.json")
        self.assertIn("W101", self.app.status.get())
        self.assertIn("not inferred", self.app.status.get())
        self.assertEqual(self.graph_profile_preferences.get(self.native.source_sha256),
                         profile_path.resolve())

        self.app.replace_native(self.native, None)
        self.assertEqual(self.app.graph_profile_path, profile_path.resolve())
        self.assertEqual(self.app.graph_profile_label.get(),
                         "Graph check: w1-core-progression.json")

        self.app.clear_graph_profile()
        self.assertIsNone(self.app.graph_profile_path)
        self.assertEqual(self.app.graph_profile_label.get(), "Graph check: off")
        self.assertIsNone(self.graph_profile_preferences.get(self.native.source_sha256))

    def test_saved_graph_profile_is_restored_only_when_valid_for_open_world(self):
        profile_path = Path(__file__).parents[1] / "profiles" / "w1-core-progression.json"
        self.graph_profile_preferences.set(self.native.source_sha256, profile_path)
        self.app._restore_graph_profile()
        self.assertEqual(self.app.graph_profile_path, profile_path.resolve())
        self.assertEqual(self.app.graph_profile_label.get(),
                         "Graph check: w1-core-progression.json")

        other_world = NativeFixture()
        other_world.point_name = "pointW2.csv"
        other_world.source_sha256 = "b" * 64
        self.graph_profile_preferences.set(other_world.source_sha256, profile_path)
        self.app.native = other_world
        self.app.graph_profile_path = None
        self.app.graph_profile_label.set("Graph check: off")
        self.app._restore_graph_profile()
        self.assertIsNone(self.app.graph_profile_path)
        self.assertEqual(self.app.graph_profile_label.get(), "Graph check: off")
        self.assertIn("unavailable", self.app.status.get())

    def test_profile_gate_blocks_native_export_before_output_picker(self):
        self.app.graph_profile_path = Path("profiles/w1-core-progression.json")
        with patch("worldstudio.__main__._validate_with_graph_profile",
                   return_value=["W102 is unreachable"]), \
             patch("worldstudio.editor.messagebox.showerror") as show_error, \
             patch("worldstudio.editor.filedialog.asksaveasfilename") as choose_output:
            self.app.export_szs()

        show_error.assert_called_once()
        self.assertIn("W102 is unreachable", show_error.call_args.args[1])
        choose_output.assert_not_called()

    def test_validate_uses_the_same_selected_profile_as_export(self):
        self.app.graph_profile_path = Path("profiles/w1-core-progression.json")
        with patch("worldstudio.__main__._validate_with_graph_profile",
                   return_value=["Unreachable location W103"]), \
             patch("worldstudio.editor.messagebox.showerror") as show_error, \
             patch("worldstudio.editor.messagebox.showinfo") as show_info:
            self.app.validate()

        show_error.assert_called_once()
        self.assertIn("Unreachable location W103", show_error.call_args.args[1])
        show_info.assert_not_called()

        with patch("worldstudio.__main__._validate_with_graph_profile",
                   return_value=[]), \
             patch("worldstudio.editor.messagebox.showinfo") as show_info:
            self.app.validate()

        self.assertIn("selected graph profile", show_info.call_args.args[1])
        self.assertIn("Cemu testing", show_info.call_args.args[1])

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

    def test_selected_point_exposes_existing_path_connection_workflow(self):
        self.app.tree.selection_set("point:0")
        self.app.select_tree()
        self.root.update()

        buttons = [widget for widget in self.app.form.winfo_children()
                   if isinstance(widget, ttk.Button)]
        self.assertTrue(any(widget.cget("text") == "Build route connection…"
                            for widget in buttons))

    def test_applying_connection_refreshes_properties_overlay_and_undo_redo_together(self):
        self.native.references.add("RW101W102")
        self.app.tree.selection_set("point:0")
        self.app.select_tree()
        self.root.update()
        before_points = [row[:] for row in self.native.points.rows]
        before_routes = [row[:] for row in self.native.routes.rows]
        bones = {bone.name for rows in self.native.skeletons.models.values() for bone in rows}
        draft = build_native_connection_draft(
            self.native.points.rows, self.native.routes.rows,
            self.native.references, bones, 0, "W102", "secret", "road", "W1")

        with patch.object(self.app, "_schedule_viewport_overlay_update") as overlay_update:
            self.app._apply_point_connection_draft(draft)

        self.assertEqual(self.native.points.rows[0][6:8], ["W102", "RW101W102"])
        self.assertEqual(self.native.routes.rows,
                         before_routes + [["RW101W102", "road", ""]])
        self.assertEqual(self.app.properties[6].get(), "W102")
        self.assertEqual(self.app.properties[7].get(), "RW101W102")
        self.assertEqual(self.app.native_selection, ("point", 0))
        overlay_update.assert_called_once()

        self.app.undo()
        self.assertEqual(self.native.points.rows, before_points)
        self.assertEqual(self.native.routes.rows, before_routes)
        self.app.redo()
        self.assertEqual(self.native.points.rows[0][6:8], ["W102", "RW101W102"])
        self.assertEqual(self.native.routes.rows,
                         before_routes + [["RW101W102", "road", ""]])

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

    def test_path_chain_suggestion_replaces_values_only_after_explicit_use(self):
        original = "RWbad,RW101W102"
        suggestion = ["RW101K001", "RK001W103"]

        def apply_suggestion():
            dialog = next(child for child in self.root.winfo_children()
                          if isinstance(child, PathChainDialog))
            self.assertEqual(tuple(dialog.items.get(0, "end")), tuple(original.split(",")))
            self.assertIsNotNone(dialog.suggest_button)
            dialog.use_suggested_chain()
            self.assertEqual(tuple(dialog.items.get(0, "end")), tuple(suggestion))
            dialog.apply()

        dialog = PathChainDialog(
            self.root, original, suggestion, suggested_chain=suggestion,
            chain_status=lambda _tokens: ("Static chain", "#8fd6a4"),
            help_text="Explicitly use the static suggestion.")
        self.root.after(0, apply_suggestion)
        self.root.wait_window(dialog)

        self.assertEqual(dialog.result, ",".join(suggestion))

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

    def test_selected_route_is_highlighted_in_the_native_2d_graph(self):
        self.app.show_auxiliary.set(True)
        self.app.refresh()
        self.app.tree.selection_set("segment:0")
        self.app.select_tree()
        route_items = self.app.canvas.find_withtag("route:RF001K001")
        self.assertEqual(len(route_items), 1)
        self.assertEqual(self.app.canvas.itemcget(route_items[0], "fill"), "#38edb6")
        self.assertEqual(float(self.app.canvas.itemcget(route_items[0], "width")), 5.0)

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
            self.assertEqual(len(scene["textures"]), 20)
            self.assertEqual(sum(bool(shape.get("texture")) for shape in scene["shapes"]), 34)
            self.assertEqual({fmt: sum(texture["format"] == fmt for texture in scene["textures"].values())
                              for fmt in {texture["format"] for texture in scene["textures"].values()}},
                             {0x31: 19, 0x33: 1})
            self.assertTrue(all("shaderMetadata" not in shape for shape in scene["shapes"]))
            self.assertTrue(scene["nodes"])
            self.assertTrue(all(node.get("editorId", "").startswith(("point:", "bone:"))
                                for node in scene["nodes"]))
            point_index = {row[1]: index for index, row in enumerate(studio.native.points.rows)
                           if len(row) > 1}
            self.assertTrue(all(shape.get("boundBone") for shape in scene["shapes"]))
            for shape in scene["shapes"]:
                bone = shape["boundBone"]
                expected = (f"point:{point_index[bone]}" if bone in point_index else
                            f"bone:{bone}" if bone in studio.native.positions and
                            bone.startswith(("K", "R", "F")) else None)
                self.assertEqual(shape.get("editorId"), expected, shape["name"])
            positions = [point for shape in scene["shapes"] for point in shape["positions"]]
            low = [min(point[axis] for point in positions) for axis in range(3)]
            high = [max(point[axis] for point in positions) for axis in range(3)]
            for node in scene["nodes"]:
                self.assertTrue(all(low[axis] <= node[key] <= high[axis]
                                    for axis, key in enumerate(("x", "y", "z"))))
        finally:
            top.destroy()

    def test_local_static_object_bone_edits_update_preview_and_export(self):
        root = Path(__file__).resolve().parents[1]
        source = root / "NSMBU Modding Project/content/Common/course_select/CS_W5a.szs"
        if not source.is_file():
            self.skipTest("User-provided local W5a dump unavailable")
        source_copy = Path(self.recent_tmp.name) / "CS_W5a.szs"
        original_archive = source.read_bytes()
        source_copy.write_bytes(original_archive)
        native = WorldProject.open(source_copy)
        self.assertTrue(native.object_positions)
        bone_name = next(iter(native.object_positions))
        with self.assertRaisesRegex(ValueError, "invalid Euler rotation"):
            native.skeletons.patch_object_transforms(
                rotations={bone_name: [0.0, 36001.0, 0.0]})
        with self.assertRaisesRegex(ValueError, "scale components"):
            native.skeletons.patch_object_transforms(
                scales={bone_name: [0.0, 1.0, 1.0]})
        native.object_rotations["W101"] = [0.0, 0.0, 0.0]
        self.assertTrue(any("Object rotation 'W101': transform is not supported" in issue
                            for issue in native.validate()))
        native.object_rotations.pop("W101")
        studio_top = tk.Toplevel(self.root)
        studio_top.withdraw()
        studio = NativeStudio(studio_top, native)
        project_dir = None
        try:
            object_iid = f"object:{bone_name}"
            self.assertTrue(studio.tree.exists(object_iid))
            studio.tree.selection_set(object_iid)
            studio.select_tree()
            self.assertEqual(studio.native_selection, ("object", bone_name))
            recovery_payload = studio._capture_edit_state()
            recovery_payload["object_scales"]["W101"] = [1.0, 1.0, 1.0]
            self.assertFalse(studio._recovery_payload_valid(recovery_payload))
            self.assertEqual(studio.position_properties["x"].get(), str(native.object_positions[bone_name][0]))
            starting_position = list(native.object_positions[bone_name])
            starting_rotation = list(native.object_rotations[bone_name])
            starting_scale = list(native.object_scales[bone_name])

            graph = studio.view_project()
            before_scene = studio._build_3d_preview(graph)
            shape_name = native.object_shape_bindings[bone_name][0]
            before_matches = [shape for shape in before_scene["shapes"] if shape["name"] == shape_name]
            self.assertTrue(before_matches, (shape_name, [shape["name"] for shape in before_scene["shapes"]]))
            before = before_matches[0]
            self.assertEqual(before.get("editorId"), f"object:{bone_name}")
            old_positions = before["positions"]
            scheduled = []
            studio.preview_scene = before_scene
            studio._preview_geometry_signature = studio._current_preview_geometry_signature()
            studio._schedule_embedded_preview_build = lambda: scheduled.append("rebuild")
            studio._schedule_viewport_overlay_update = lambda: scheduled.append("overlay")
            moved_position = list(starting_position)
            moved_position[0] += 12.0
            studio.position_properties["x"].set(str(moved_position[0]))
            studio.apply()
            self.assertEqual(native.object_positions[bone_name], moved_position)
            self.assertIn("rebuild", scheduled)
            studio.undo()
            self.assertEqual(native.object_positions[bone_name], starting_position)
            studio.redo()
            self.assertEqual(native.object_positions[bone_name], moved_position)
            after_scene = studio._build_3d_preview(graph)
            after = next(shape for shape in after_scene["shapes"] if shape["name"] == shape_name)
            self.assertNotEqual(after["positions"], old_positions)
            deltas = [[new[axis] - old[axis] for axis in range(3)]
                      for old, new in zip(old_positions, after["positions"])]
            for delta in deltas:
                for axis in range(3):
                    self.assertAlmostEqual(delta[axis], deltas[0][axis], places=4)
            self.assertGreater(sum(abs(value) for value in deltas[0]), 1.0)

            studio.tree.selection_set(object_iid)
            studio.select_tree()
            moved_rotation = list(starting_rotation)
            moved_rotation[1] += 20.0
            moved_scale = list(starting_scale)
            moved_scale[0] *= 1.15
            studio.object_rotation_properties["y"].set(str(moved_rotation[1]))
            studio.object_scale_properties["x"].set(str(moved_scale[0]))
            studio.apply()
            self.assertEqual(native.object_rotations[bone_name], moved_rotation)
            self.assertEqual(native.object_scales[bone_name], moved_scale)
            transformed_scene = studio._build_3d_preview(graph)
            transformed = next(shape for shape in transformed_scene["shapes"]
                               if shape["name"] == shape_name)
            self.assertNotEqual(transformed["positions"], after["positions"])
            studio.undo()
            self.assertEqual(native.object_rotations[bone_name], starting_rotation)
            self.assertEqual(native.object_scales[bone_name], starting_scale)
            studio.redo()
            self.assertEqual(native.object_rotations[bone_name], moved_rotation)
            self.assertEqual(native.object_scales[bone_name], moved_scale)

            project_dir = tempfile.TemporaryDirectory()
            project_path = Path(project_dir.name) / "object-edits.nws.json"
            native.save(project_path)
            reopened = WorldProject.load(project_path)
            self.assertEqual(reopened.object_positions, native.object_positions)
            self.assertEqual(reopened.object_rotations, native.object_rotations)
            self.assertEqual(reopened.object_scales, native.object_scales)
            output = Path(project_dir.name) / "object-edited.szs"
            native.export(output)
            exported = WorldProject.open(output)
            self.assertEqual(exported.object_positions[bone_name], native.object_positions[bone_name])
            for actual, expected in zip(exported.object_rotations[bone_name],
                                        native.object_rotations[bone_name]):
                self.assertAlmostEqual(actual, expected, places=4)
            for actual, expected in zip(exported.object_scales[bone_name],
                                        native.object_scales[bone_name]):
                self.assertAlmostEqual(actual, expected, places=5)
            self.assertEqual(source_copy.read_bytes(), original_archive)
        finally:
            if project_dir is not None:
                project_dir.cleanup()
            studio_top.destroy()

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
    def test_preview_geometry_fingerprint_tracks_gltf_sidecar_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scene_path = root / "terrain.gltf"
            binary_path = root / "terrain.bin"

            def write_sidecar(last_x):
                binary = (struct.pack("<9f", 0, 0, 0, 0, 0, 1, last_x, 0, 0) +
                          struct.pack("<3H", 0, 1, 2))
                binary_path.write_bytes(binary)
                document = {
                    "asset": {"version": "2.0"},
                    "buffers": [{"uri": "terrain.bin", "byteLength": len(binary)}],
                    "bufferViews": [
                        {"buffer": 0, "byteLength": 36},
                        {"buffer": 0, "byteOffset": 36, "byteLength": 6},
                    ],
                    "accessors": [
                        {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
                        {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
                    ],
                    "meshes": [{"primitives": [{"attributes": {"POSITION": 0},
                                                  "indices": 1}]}],
                    "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0,
                }
                scene_path.write_text(json.dumps(document), encoding="utf-8")

            write_sidecar(1)
            project_path = root / "preview.json"
            project = demo_project()
            project["terrain"] = "terrain.gltf"
            project["terrain_geometry_sha256"] = preview_geometry_sha256(
                read_import_mesh(scene_path))
            project_path.write_text(json.dumps(project), encoding="utf-8")

            editor = object.__new__(WorldStudio)
            status = SimpleNamespace(value="", set=lambda value: setattr(status, "value", value))
            editor.status = status
            editor.project = None
            editor.project_path = None
            editor.selected = None
            editor.dirty = False
            editor.recent_projects = RecentProjects(root / "recent.json")
            editor.refresh = lambda: None
            editor._reset_edit_history = lambda: None
            editor._record_recent_project = lambda path: None
            editor._set_recovery_context = lambda *args, **kwargs: None
            editor._clear_recovery = lambda *args: None

            editor.open_project_path(project_path)
            self.assertEqual(editor.mesh[0], [(0., 0., 0.), (0., 0., 1.), (1., 0., 0.)])

            write_sidecar(2)
            editor.open_project_path(project_path)
            self.assertEqual(editor.mesh, ([], []))
            self.assertIn("terrain geometry changed since import", status.value)

    def test_relative_terrain_survives_open_save_and_save_to_another_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_dir = root / "source"
            terrain_path = source_dir / "assets" / "island.obj"
            terrain_path.parent.mkdir(parents=True)
            terrain_path.write_text(
                "v 0 0 0\nv 1 0 0\nv 0 0 1\nf 1 2 3\n", encoding="utf-8")
            source_project = source_dir / "preview.json"
            source_data = demo_project()
            source_data["terrain"] = "assets/island.obj"
            source_data["terrain_transform"] = {
                "scale": [2, 1, 1],
                "rotation_degrees": [-90, 0, 0],
                "translation": [1, 2, 3],
            }
            source_data["terrain_geometry_sha256"] = preview_geometry_sha256(
                read_import_mesh(terrain_path))
            source_project.write_text(json.dumps(source_data), encoding="utf-8")

            editor = object.__new__(WorldStudio)
            editor.project = None
            editor.project_path = None
            editor.selected = None
            editor.dirty = False
            status = SimpleNamespace(value="", set=lambda value: setattr(status, "value", value))
            editor.status = status
            editor.recent_projects = RecentProjects(root / "recent.json")
            editor.refresh = lambda: None
            editor._reset_edit_history = lambda: None
            editor._record_recent_project = lambda path: None
            editor._set_recovery_context = lambda *args, **kwargs: None
            editor._clear_recovery = lambda *args: None

            editor.open_project_path(source_project)
            self.assertEqual(Path(editor.project["terrain"]), terrain_path.resolve())
            self.assertEqual(editor.mesh[0], [(1., 2., 3.), (3., 2., 3.), (1., 3., 3.)])
            self.assertTrue(editor.save())
            same_location = json.loads(source_project.read_text(encoding="utf-8"))
            self.assertEqual(resolve_project_path(same_location["terrain"], source_project),
                             str(terrain_path.resolve()))
            self.assertEqual(same_location["terrain_transform"], source_data["terrain_transform"])
            self.assertEqual(same_location["terrain_geometry_sha256"],
                             source_data["terrain_geometry_sha256"])

            save_as_path = root / "relocated" / "preview-copy.json"
            editor.project_path = None
            with patch("worldstudio.editor.filedialog.asksaveasfilename",
                       return_value=str(save_as_path)):
                self.assertTrue(editor.save())
            relocated = json.loads(save_as_path.read_text(encoding="utf-8"))
            self.assertEqual(resolve_project_path(relocated["terrain"], save_as_path),
                             str(terrain_path.resolve()))
            self.assertEqual(relocated["terrain_transform"], source_data["terrain_transform"])
            self.assertEqual(relocated["terrain_geometry_sha256"],
                             source_data["terrain_geometry_sha256"])
            editor.open_project_path(save_as_path)
            self.assertEqual(editor.mesh[0], [(1., 2., 3.), (3., 2., 3.), (1., 3., 3.)])

            terrain_path.write_text(
                "v 0 0 0\nv 1 0 0\nv 0 0 2\nf 1 2 3\n", encoding="utf-8")
            editor.open_project_path(save_as_path)
            self.assertEqual(editor.mesh, ([], []))
            self.assertIn("terrain geometry changed since import", status.value)

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
