"""Hidden Tk regression checks for bone edits and world/local separation."""
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
import unittest

from worldstudio.editor import NativeStudio


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


if __name__ == "__main__":
    unittest.main()
