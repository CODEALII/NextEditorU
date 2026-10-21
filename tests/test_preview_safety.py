import tempfile
import unittest
from pathlib import Path

from worldstudio.editor import validate_preview
from worldstudio.preview3d import build_document
from worldstudio.project import resolve_project_path, store_project_path


class PreviewSafetyTests(unittest.TestCase):
    def test_malformed_json_shapes_return_diagnostics(self):
        self.assertIn("Project must be a JSON object", validate_preview([]))
        project = {"nodes": [
            {"id": [], "x": 0, "y": 0, "z": 0},
            {"id": "valid", "x": True, "y": 0, "z": 0}],
            "routes": [{"id": {}, "start": [], "end": {}}]}
        issues = validate_preview(project)
        self.assertTrue(any("identifier" in issue for issue in issues))
        self.assertTrue(any("coordinates" in issue for issue in issues))
        self.assertTrue(any("endpoint" in issue for issue in issues))

    def test_self_routes_are_rejected(self):
        project = {"nodes": [{"id": "A", "x": 0, "y": 0, "z": 0}],
                   "routes": [{"id": "AA", "start": "A", "end": "A"}]}
        self.assertIn("Self route: AA", validate_preview(project))

    def test_3d_viewer_is_offline_and_escapes_scene_strings(self):
        page = build_document({"title": "</script><script>alert(1)</script>", "shapes": [],
                               "nodes": [], "routes": []})
        self.assertIn("WebGL", page)
        self.assertIn("Could not initialize the WebGL renderer", page)
        self.assertIn("approximate material colors", page)
        self.assertIn("aUv", page)
        self.assertIn("texture2D(uTexture,vUv)", page)
        self.assertNotIn("https://", page)
        self.assertNotIn("</script><script>alert(1)", page)
        self.assertIn("<\\/script>", page)

    def test_viewer_accepts_embedded_base_texture_without_remote_resources(self):
        page = build_document({"shapes": [{"name": "grass", "uvs": [[0, 0]],
                                           "texture": {"name": "Grass_alb", "width": 1,
                                                       "height": 1, "rgbaBase64": "AAAAAA=="}}],
                               "textureNotice": "Grass_alb base texture", "nodes": [], "routes": []})
        self.assertIn("Grass_alb", page)
        self.assertIn("rgbaBase64", page)
        self.assertIn("gl.texImage2D", page)
        self.assertIn("gl.TEXTURE_WRAP_S,gl.REPEAT", page)
        self.assertNotIn("https://", page)

    def test_project_asset_paths_survive_moving_project_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "one" / "project.json"
            asset = root / "shared" / "terrain.obj"
            asset.parent.mkdir(); asset.touch()
            stored = store_project_path(asset, project)
            self.assertFalse(Path(stored).is_absolute())
            self.assertEqual(Path(resolve_project_path(stored, project)), asset.resolve())
            moved = root / "two" / "project.json"
            moved.parent.mkdir()
            moved_asset = root / "shared" / "terrain.obj"
            self.assertEqual(Path(resolve_project_path(stored, moved)), moved_asset.resolve())


if __name__ == "__main__":
    unittest.main()
