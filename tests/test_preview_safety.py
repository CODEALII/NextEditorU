import base64
import json
import math
import re
import shutil
import struct
import subprocess
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

    def test_depth_planes_follow_scene_radius_and_remain_safe_when_zoomed_in(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise viewer camera math")
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        script = re.search(r"<script>(.*?)</script>", page, re.DOTALL).group(1)
        match = re.search(r"function cameraPlanes\(distance,radius\)\{[^}]*\}", script)
        self.assertIsNotNone(match)
        self.assertIn("cameraPlanes(distance,sceneRadius)", script)
        probe = match.group(0) + "\nconsole.log(JSON.stringify([cameraPlanes(2.65,1),cameraPlanes(16,1),cameraPlanes(.2,1),cameraPlanes(0,0)]))"
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True, text=True)
        fit, zoomed_out, close, invalid = json.loads(result.stdout)
        for near, far in (fit, zoomed_out, close, invalid):
            self.assertTrue(0 < near < far)
            self.assertTrue(all(map(lambda value: value == value and abs(value) != float("inf"), (near, far))))
        self.assertLess(fit[1] / fit[0], 3)
        self.assertLess(zoomed_out[1] / zoomed_out[0], 1.2)
        self.assertLess(fit[0], 2.65 - 1)
        self.assertGreater(zoomed_out[1], 16 + 1)

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
        self.assertIn("textureCache.set(key,texture)", page)
        self.assertIn("mesh.normalTextureName+' '+mesh.diagnosticTextureName+' '+mesh.maskTextureName).toLowerCase()", page)

    def test_viewer_exposes_bc5_diagnostic_and_optional_approximate_lighting(self):
        page = build_document({
            "normalTextures": {"RouteW1_nml": {"name": "RouteW1_nml", "width": 1,
                                                "height": 1, "rgbaBase64": "AAAAAA=="}},
            "diagnosticTextures": {"MaskOpaque": {"name": "MaskOpaque", "width": 1,
                                                     "height": 1, "rgbaBase64": "AAAAAA=="}},
            "maskTextures": {"RouteW1_msk": {"name": "RouteW1_msk", "width": 1,
                                               "height": 1, "rgbaBase64": "AAAAAA=="}},
            "normalTextureNotice": "BC5 SNORM channels are diagnostic only.",
            "diagnosticTextureNotice": "BC5 UNorm _o0 channels are diagnostic only.",
            "maskTextureNotice": "BC4 UNorm _o1 channels are diagnostic only.",
            "shapes": [{"name": "route-mesh", "material": "mtRoute", "uvs": [[0, 0]],
                        "normalTexture": "RouteW1_nml", "diagnosticTexture": "MaskOpaque",
                        "maskTexture": "RouteW1_msk",
                        "positions": [[0, 0, 0]],
                        "normals": [[0, 1, 0]], "indices": [0]}],
            "nodes": [], "routes": []})
        self.assertIn('<button id="bc5-view" disabled>BC5 SNORM off</button>', page)
        self.assertIn('<button id="normal-map" disabled>BC5 lighting off</button>', page)
        self.assertIn('<button id="sampler-view" disabled>_o0 BC5 UNorm off</button>', page)
        self.assertIn('<button id="bc4-view" disabled>_o1 BC4 off</button>', page)
        self.assertIn('scene.normalTextures?.[shape.normalTexture]', page)
        self.assertIn('scene.diagnosticTextures?.[shape.diagnosticTexture]', page)
        self.assertIn('scene.maskTextures?.[shape.maskTexture]', page)
        self.assertIn('uniform float uShowNormalTexture', page)
        self.assertIn('uniform float uShowDiagnosticTexture', page)
        self.assertIn('uniform float uShowMaskTexture', page)
        self.assertIn('texture2D(uDiagnosticTexture,vUv)', page)
        self.assertIn('texture2D(uMaskTexture,vUv)', page)
        self.assertIn('uniform float uUseNormalMap', page)
        self.assertIn('attribute vec4 aTangent', page)
        self.assertIn('sqrt(max(0.0,1.0-dot(xy,xy)))', page)
        self.assertIn('Approximate BC5 tangent-space lighting is active', page)
        self.assertIn('BC5 SNORM channels are diagnostic only.', page)
        self.assertIn('normalTextureName', page)
        self.assertIn('diagnosticTextureName', page)
        self.assertIn('maskTextureName', page)
        self.assertIn('BC5 UNorm _o0 · diagnostic', page)
        self.assertIn('BC4 UNorm _o1 · diagnostic', page)
        self.assertIn('sampler channels are shown for inspection only; material meaning is unverified.', page)
        self.assertIn('R/G channels are shown as diagnostic colors only', page)
        self.assertNotIn('https://', page)
        self.assertIn('<button id="wireframe">Wireframe off</button>', page)
        self.assertIn('gl.drawElements(showWireframe?gl.LINES:gl.TRIANGLES', page)
        self.assertIn('<button id="normals">Normals off</button>', page)
        self.assertIn('if(m.visible)drawOverlay(m.normalOverlay', page)

    def test_tangent_generation_builds_an_orthonormal_uv_basis(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise viewer tangent generation")
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        start = page.index("function makeTangents(")
        end = page.index("\nlet meshes=[];", start)
        helper = page[start:end]
        probe = helper + r"""
const p=[0,0,0,1,0,0,0,1,0],n=[0,0,1,0,0,1,0,0,1],uv=[0,0,1,0,0,1];
const regular=makeTangents(p,n,uv,new Uint16Array([0,1,2]));
const mirrored=makeTangents(p,n,[0,0,0,1,1,0],new Uint16Array([0,1,2]));
const degenerate=makeTangents(p,n,[0,0,0,0,0,0],new Uint16Array([0,1,2]));
console.log(JSON.stringify({regular:Array.from(regular),mirrored:Array.from(mirrored),degenerate}));
"""
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True, text=True)
        values = json.loads(result.stdout)
        self.assertEqual(values["regular"], [1, 0, 0, 1] * 3)
        self.assertEqual(values["mirrored"][3::4], [-1, -1, -1])
        self.assertIsNone(values["degenerate"])

    def test_mesh_selection_inspector_shows_geometry_uv_and_texture_references(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise viewer mesh selection")
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        start = page.index("const list=document.getElementById('shapes')")
        end = page.index("\nfor(const mesh of meshes)addShapeRow(mesh);", start)
        helper = page[start:end]
        probe = r"""
const registry={shapes:element(),selection:element()};
const document={getElementById:id=>registry[id],createElement:tag=>element(tag)};
function element(tag){const e={tagName:tag,children:[],dataset:{},listeners:{},attributes:{},style:{},className:'',textContent:'',hidden:false,append(...items){this.children.push(...items)},appendChild(item){this.children.push(item);return item},replaceChildren(...items){this.children=items},setAttribute(k,v){this.attributes[k]=v},addEventListener(k,fn){this.listeners[k]=fn},classList:{add(name){e.className=[...new Set((e.className+' '+name).trim().split(/\s+/))].join(' ')},remove(name){e.className=e.className.split(/\s+/).filter(x=>x!==name).join(' ')},contains(name){return e.className.split(/\s+/).includes(name)}}};return e}
let focusedMesh=null;function focusMesh(mesh){focusedMesh=mesh}
""" + helper + r"""
const a={name:'Grass <test>',material:'mtGrass',color:[.2,.4,.6],textureName:'Grass_alb',normalTextureName:'Grass_nml',vertexCount:12,triangleCount:8,hasUvs:true,visible:true};
const b={name:'Rock',material:'mtRock',color:[.3,.3,.3],textureName:'',normalTextureName:'',vertexCount:9,triangleCount:4,hasUvs:false,visible:true};
addShapeRow(a);addShapeRow(b);a.row.children[2].listeners.click();
if(!a.row.classList.contains('selected'))throw Error('selected row is not marked');
const first=registry.selection.children.map(x=>x.textContent).join('\n');
if(!first.includes('Grass <test>')||!first.includes('12 vertices / 8 triangles')||!first.includes('Grass_alb')||!first.includes('Grass_nml (BC5 SNORM map)'))throw Error(first);
registry.selection.children.at(-1).listeners.click();if(focusedMesh!==a)throw Error('focus action is not linked to selection');
b.row.children[2].listeners.click();
if(a.row.classList.contains('selected')||!b.row.classList.contains('selected'))throw Error('selection did not move');
if(!registry.selection.children.map(x=>x.textContent).join('\n').includes('UV coordinates: absent'))throw Error('missing UV status');
if(a.row.children[2].tagName!=='button'||a.row.children[2].attributes['aria-label']!=='Inspect Grass <test>')throw Error('selection button is not accessible');
registry.selection.children.at(-1).listeners.click();if(focusedMesh!==b)throw Error('focus action did not follow selection');
console.log('mesh selection inspector ok');
"""
        result = subprocess.run([node, "-e", probe], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "mesh selection inspector ok")

    def test_mesh_bounds_are_centered_and_have_a_safe_radius(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise viewer mesh bounds")
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        start = page.index("function shapeBounds(")
        end = page.index("\nconst textureCache=", start)
        helper = page[start:end]
        probe = helper + "\nconsole.log(JSON.stringify([shapeBounds([0,2,4,4,6,8]),shapeBounds([])]))"
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True, text=True)
        bounds, empty = json.loads(result.stdout)
        self.assertEqual(bounds["center"], [2, 4, 6])
        self.assertAlmostEqual(bounds["radius"], math.sqrt(12))
        self.assertEqual(empty, {"center": [0, 0, 0], "radius": 1})

    def test_texture_preview_downsamples_rgba_with_bounded_dimensions(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise texture preview sampling")
        source = bytes((
            255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 0, 255,
            255, 0, 255, 255, 0, 255, 255, 255, 0, 0, 0, 255, 255, 255, 255, 255,
        ))
        payload = {"name": "sample", "width": 4, "height": 2,
                   "rgbaBase64": base64.b64encode(source).decode("ascii")}
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        start = page.index("function texturePreviewPixels(")
        end = page.index("\nconst textureThumbnailCache=", start)
        helper = page[start:end]
        probe = helper + "\nconst thumb=texturePreviewPixels(" + json.dumps(payload) + ",2);console.log(JSON.stringify([thumb.width,thumb.height,Array.from(thumb.data)]))"
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True, text=True)
        width, height, data = json.loads(result.stdout)
        self.assertEqual((width, height), (2, 1))
        self.assertEqual(data, [0, 255, 255, 255, 255, 255, 255, 255])

    def test_mesh_inspector_exposes_cached_base_and_bc5_thumbnails(self):
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        self.assertIn("texturePreview:texturePayload,normalPreview:normalPayload", page)
        self.assertIn("textureThumbnail(payload,kind)", page)
        self.assertIn("BC5 SNORM · diagnostic", page)
        self.assertIn("Base color · ${payload.name}", page)

    def test_viewport_pick_ids_and_hidpi_pixel_coordinates(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise viewer picking helpers")
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        start = page.index("function pickIdColor(")
        end = page.index("\nfunction shapeBounds", start)
        helper = page[start:end]
        probe = helper + r"""
const ids=[0,1,41,255,65535];
for(const index of ids){const bytes=Array.from(pickIdColor(index),x=>Math.round(x*255));if(meshIndexFromPixel(bytes)!==index)throw Error('pick ID round trip failed: '+index)}
const point=canvasPixel(160,80,{left:10,top:20,width:300,height:200},600,400);
const edge=canvasPixel(0,0,{left:10,top:20,width:300,height:200},600,400);
console.log(JSON.stringify([point,edge,meshIndexFromPixel([0,0,0,255])]));
"""
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), [[300, 279], [0, 399], -1])

    def test_viewport_picking_uses_depth_and_respects_texture_cutouts(self):
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        self.assertIn("pickProgram=program(", page)
        self.assertIn("gl.readPixels(point[0],point[1],1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel)", page)
        self.assertIn("texture2D(uTexture,vUv).a<0.5", page)
        self.assertIn("gl.drawElements(gl.TRIANGLES,mesh.count,gl.UNSIGNED_SHORT,0)", page)
        self.assertIn("selectMesh(meshes[index])", page)
        self.assertIn("previous.button===0&&Math.hypot(e.clientX-previous.startX,e.clientY-previous.startY)<4", page)
        self.assertIn("Click a shape to select", page)

    def test_focus_mesh_centers_the_camera_and_uses_mesh_radius(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise viewer camera focus")
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        start = page.index("const bounds=scene.bounds||")
        end = page.index("\nfunction cameraPreset", start)
        focus = re.search(r"function focusMesh\(mesh\)\{[^}]*\}", page)
        self.assertIsNotNone(focus)
        helper = page[start:end] + "\n" + focus.group(0)
        probe = "const scene={bounds:{center:[1,2,3],radius:100},camera:{}};\n" + helper + "\n" + \
                "focusMesh({center:[20,30,40],radius:10});\nconsole.log(JSON.stringify([viewCenter,target,distance]))"
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True, text=True)
        center, target, distance = json.loads(result.stdout)
        self.assertEqual(center, [20, 30, 40])
        self.assertEqual(target, [0, 0, 0])
        self.assertEqual(distance, 26.5)

    def test_camera_presets_provide_front_side_and_top_orientations(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise viewer camera presets")
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        for name in ("front", "side", "top"):
            self.assertIn(f'data-camera-preset="{name}" aria-pressed="false"', page)
        self.assertIn("button.addEventListener('click',()=>{const preset=cameraPreset(button.dataset.cameraPreset)", page)
        self.assertIn("other.setAttribute('aria-pressed',String(active))", page)
        start = page.index("function cameraPreset(name){")
        end = page.index("\nconst cameraPresetButtons", start)
        helper = page[start:end]
        probe = helper + "\nconsole.log(JSON.stringify(['front','side','top','unknown'].map(cameraPreset)))"
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True, text=True)
        front, side, top, unknown = json.loads(result.stdout)
        self.assertEqual(front, [0, 0.12])
        self.assertAlmostEqual(side[0], math.pi / 2)
        self.assertEqual(side[1], 0.12)
        self.assertEqual(top, [0, 1.25])
        self.assertIsNone(unknown)

    def test_preview_light_controls_feed_a_normalized_shader_direction(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise preview lighting controls")
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        for control in ("light-azimuth", "light-elevation", "light-intensity"):
            self.assertIn(f'id="{control}" type="range"', page)
        self.assertIn("uLightDirection", page)
        self.assertIn("uLightIntensity", page)
        self.assertIn("control.addEventListener('input',syncPreviewLight)", page)
        start = page.index("function lightDirection(")
        end = page.index("\nlet showWireframe=", start)
        helper = page[start:end]
        probe = r"""
const elements={};
for(const id of ['light-azimuth','light-elevation','light-intensity','light-azimuth-value','light-elevation-value','light-intensity-value'])elements[id]={value:id==='light-azimuth'?'-49.4':id==='light-elevation'?'56':'100',listeners:{},addEventListener(name,fn){this.listeners[name]=fn}};
const document={getElementById:id=>elements[id]};
""" + helper + r"""
elements['light-azimuth'].value='0';elements['light-elevation'].value='0';elements['light-intensity'].value='150';
elements['light-intensity'].listeners.input();
console.log(JSON.stringify({direction:Array.from(previewLightDirection),intensity:previewLightIntensity,labels:[elements['light-azimuth-value'].value.charCodeAt(1),elements['light-elevation-value'].value.charCodeAt(1),elements['light-intensity-value'].value]}));
"""
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True, text=True)
        output = json.loads(result.stdout)
        direction = output["direction"]
        self.assertAlmostEqual(math.sqrt(sum(component * component for component in direction)), 1.0)
        for actual, expected in zip(direction, (0.0, 0.0, 1.0)):
            self.assertAlmostEqual(actual, expected, delta=0.01)
        self.assertAlmostEqual(output["intensity"], 1.5)
        self.assertEqual(output["labels"], [176, 176, "150%"])

    def test_wireframe_edge_builder_deduplicates_triangle_edges(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise viewer wireframe edge generation")
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        start = page.index("function wireEdges(indices){")
        end = page.index("\nconst normalVertexTotal=", start)
        helper = page[start:end]
        probe = helper + "\nconsole.log(JSON.stringify(Array.from(wireEdges([0,1,2,2,1,3]))))"
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), [0, 1, 1, 2, 0, 2, 1, 3, 2, 3])

    def test_sampled_vertex_normal_vectors_follow_source_positions(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise viewer normal-vector generation")
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        start = page.index("const normalVertexTotal=")
        end = page.index("\nlet meshes=[];", start)
        helper = page[start:end]
        probe = ("const scene={stats:{vertices:2},bounds:{radius:10},shapes:[]};\n" + helper +
                 "\nconsole.log(JSON.stringify(Array.from(makeNormalLines([0,0,0,2,0,0],[0,2,0,0,0,-3]))))")
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), [0, 0, 0, 0, 1, 0, 2, 0, 0, 2, 0, -1])

    def test_generated_viewer_javascript_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to parse generated viewer JavaScript")
        scene = {"shapes": [{"name": "mesh", "material": "mat", "positions": [],
                             "normals": [], "indices": [], "uvs": [],
                             "normalTexture": "Normal_nml"}],
                 "normalTextures": {"Normal_nml": {"name": "Normal_nml", "width": 1,
                                                       "height": 1, "rgbaBase64": "AAAAAA=="}},
                 "nodes": [], "routes": []}
        page = build_document(scene)
        script = re.search(r"<script>(.*?)</script>", page, re.DOTALL).group(1)
        subprocess.run([node, "--check", "-"], input=script, check=True,
                       capture_output=True, text=True)

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
