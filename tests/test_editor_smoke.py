"""Hidden Tk regression checks for bone edits and world/local separation."""
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
import threading
import time
import unittest

from worldstudio.editor import NativeStudio, ObjTransformDialog, WorldStudio


class NativeFixture:
    def __init__(self):
        self.source = Path("synthetic.szs")
        self.points = SimpleNamespace(rows=[
            ["0", "W101", "", "W102", "RW101W102", "", "", "", ""],
            ["1", "W102", "", "", "", "", "", "", ""],
            ["2", "F001", "", "", "", "", "", "", ""],
            ["3", "Fbad", "", "", "", "", "", "", ""]])
        self.routes = SimpleNamespace(rows=[["RF001K001", "road", ""]])
        self.path_model = "Primary"
        names = ["W101", "W102", "F001", "K001", "RF001K001", "Fbad"]
        self.skeletons = SimpleNamespace(models={"Primary": [
            SimpleNamespace(name=name, index=i, parent=0 if i else -1, model="Primary")
            for i, name in enumerate(names)]})
        self.positions = dict(zip(names, ([100, 0, 0], [300, 0, 0], [10, 0, 0], [20, 0, 0], [4, 0, 0], [999999, 0, 0])))
        self.layout, self.terrain, self.geometry = {}, None, None

    @property
    def world_positions(self):
        # Deterministic synthetic hierarchy; Fbad deliberately unsupported.
        origin = self.positions["W101"][0]
        return {"W101": list(self.positions["W101"]), "W102": list(self.positions["W102"]),
                "F001": [origin + self.positions["F001"][0], 0, 0],
                "K001": [origin + self.positions["K001"][0], 0, 0],
                "RF001K001": [origin + self.positions["RF001K001"][0], 0, 0]}


class EditorSmokeTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk unavailable: {error}")
        self.root.withdraw()
        self.native = NativeFixture()
        self.app = NativeStudio(self.root, self.native)
        self.root.update()

    def tearDown(self):
        if hasattr(self, "root"):
            self.root.destroy()

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

    def test_3d_preview_build_runs_off_tk_thread_and_keeps_events_live(self):
        started = threading.Event()
        release = threading.Event()
        worker_results = []

        def build(graph):
            worker_results.append((threading.current_thread(), graph))
            started.set()
            release.wait(2)
            return "3D preview opened · 1 shape · 1 triangle"

        self.app._build_3d_preview = build
        self.app.open_3d_preview()
        self.assertTrue(self.app.exporting)
        self.assertTrue(started.wait(1))
        callbacks = []
        self.root.after(0, lambda: callbacks.append("responsive"))
        self.root.update()
        self.assertEqual(callbacks, ["responsive"])
        self.assertIsNot(worker_results[0][0], threading.current_thread())
        self.assertEqual([node["id"] for node in worker_results[0][1]["nodes"]], ["W101", "W102"])

        release.set()
        deadline = time.monotonic() + 2
        while self.app.exporting and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.app.exporting)
        self.assertIn("3D preview opened", self.app.status.get())

    def test_lightweight_editor_keeps_its_direct_obj_preview_path(self):
        studio = object.__new__(WorldStudio)
        status = SimpleNamespace(set=lambda value: setattr(status, "value", value))
        studio.status = status
        studio._build_3d_preview = lambda graph: "3D preview opened · imported OBJ"

        studio.open_3d_preview()

        self.assertEqual(status.value, "3D preview opened · imported OBJ")

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


if __name__ == "__main__":
    unittest.main()
