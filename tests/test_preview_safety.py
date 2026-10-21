import base64
import json
import re
import struct
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
        self.assertIn("texel.a<0.5)discard", page)
        self.assertNotIn("https://", page)
        self.assertNotIn("</script><script>alert(1)", page)
        self.assertIn("<\\/script>", page)

    def test_webgl_startup_failures_show_an_obvious_viewer_fallback(self):
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        script = re.search(r"<script>(.*?)</script>", page, re.DOTALL).group(1)
        self.assertIn("function showError(message){error.textContent=message;error.style.display='grid'}", script)
        self.assertIn("try{gl=canvas.getContext('webgl'", script)
        self.assertIn("if(!gl)showError('WebGL is unavailable in this browser.", script)
        self.assertIn("catch(e){showError('Could not initialize the WebGL renderer:", script)
        self.assertIn("#error{display:none;position:absolute;inset:0;z-index:4", page)

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

    def test_viewer_resolves_shared_texture_catalog_and_shape_filter(self):
        page = build_document({
            "textures": {"RouteW1_alb": {"name": "RouteW1_alb", "width": 1,
                                          "height": 1, "rgbaBase64": "AAAAAA=="}},
            "shapes": [{"name": "route-mesh", "material": "mtRoute", "uvs": [[0, 0]],
                        "texture": "RouteW1_alb", "positions": [[0, 0, 0]],
                        "normals": [[0, 1, 0]], "indices": [0]}],
            "nodes": [], "routes": []})
        self.assertIn('"texture":"RouteW1_alb"', page)
        self.assertIn('"RouteW1_alb":{"name":"RouteW1_alb"', page)
        self.assertIn("scene.textures?.[shape.texture]", page)
        self.assertIn("textureCache.set(payload.name,texture)", page)
        self.assertIn("mesh.textureName).toLowerCase()", page)

    def test_viewer_packs_geometry_as_little_endian_typed_arrays(self):
        shape = {"name": "mesh", "material": "mat",
                 "positions": [(float(i), 1.25, -2.5) for i in range(100)],
                 "normals": [(0.0, 1.0, 0.0)] * 100,
                 "uvs": [(0.25, 0.75)] * 100,
                 "indices": [0, 1, 2]}
        scene = {"shapes": [shape], "nodes": [], "routes": []}
        page = build_document(scene)
        encoded_scene = json.loads(re.search(r"const scene=(.*?);", page).group(1))
        packed = encoded_scene["shapes"][0]
        self.assertNotIn("positions", packed)
        self.assertEqual(packed["indexCount"], 3)
        self.assertEqual(struct.unpack("<3f", base64.b64decode(packed["positionsPacked"])[:12]),
                         (0.0, 1.25, -2.5))
        self.assertEqual(struct.unpack("<3H", base64.b64decode(packed["indicesPacked"])), (0, 1, 2))
        self.assertIn("shape.positionsPacked?unpackArray", page)
        self.assertEqual(len(shape["positions"]), 100)

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
