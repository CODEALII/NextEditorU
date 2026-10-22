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
from worldstudio.preview3d import build_document, route_surface_needs_depth_bias
from worldstudio.project import resolve_project_path, store_project_path


class PreviewSafetyTests(unittest.TestCase):
    def test_native_route_surfaces_get_polygon_offset_without_affecting_terrain(self):
        self.assertTrue(route_surface_needs_depth_bias("beltmodel27__mtRW102W1S0a", "RW102W1S0a"))
        self.assertTrue(route_surface_needs_depth_bias("routeOpague1", "mtRouteOpague"))
        self.assertFalse(route_surface_needs_depth_bias("polySurface1489__mtGrass", "mtGrass"))
        page = build_document({"shapes": [{"name": "road", "depthBias": True,
                                            "positions": [], "indices": []}],
                               "nodes": [], "routes": []})
        self.assertIn("mesh.depthBias=metadata.depthBias===true", page)
        self.assertIn("clip.z-=uDepthBias*clip.w", page)
        self.assertIn("function applyRouteDepthOffset(enabled)", page)
        self.assertIn("gl.enable(gl.POLYGON_OFFSET_FILL);gl.polygonOffset(-1,-1)", page)
        self.assertIn("applyRouteDepthOffset(m.depthBias&&!showWireframe)", page)
        self.assertIn("applyRouteDepthOffset(mesh.depthBias)", page)
        self.assertIn("gl.uniform1f(gl.getUniformLocation(meshProgram,'uDepthBias'),0)", page)
        self.assertIn("const renderMeshes=[...meshes.filter(m=>!m.depthBias),...meshes.filter(m=>m.depthBias)]", page)
        self.assertIn("uRouteBlend>0.5&&texel.a<=0.001", page)
        self.assertIn("gl_FragColor=vec4(c,uRouteBlend>0.5?texel.a:1.0)", page)
        self.assertIn("gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);gl.depthMask(false)", page)
        self.assertIn("if(routeBlend){gl.depthMask(true);gl.disable(gl.BLEND)}", page)
        self.assertIn("applyRouteDepthOffset(false)", page)

    def test_embedded_graph_toggle_remains_visible_over_the_world(self):
        page = build_document({"shapes": [], "nodes": [{"id": "W101", "x": 0, "y": 0, "z": 0}], "routes": []}, embedded=True)
        self.assertIn(".embedded .embedded-controls{display:inline-flex!important}", page)
        self.assertIn("graph.classList.add('open','expanded')", page)
        self.assertIn('id="world-graph-svg"', page)

    def test_preview_project_rejects_invalid_saved_terrain_transform(self):
        project = {"format": "worldstudio-preview-v1", "nodes": [], "routes": [],
                   "terrain_transform": {"scale": [1, 0, 1],
                                         "rotation_degrees": [0, 0, 0],
                                         "translation": [0, 0, 0]}}

        issues = validate_preview(project)

        self.assertTrue(any("terrain_transform scale components must be nonzero" in issue
                            for issue in issues))

    def test_preview_project_rejects_malformed_terrain_geometry_fingerprint(self):
        project = {"format": "worldstudio-preview-v1", "nodes": [], "routes": [],
                   "terrain": "terrain.obj", "terrain_geometry_sha256": "xyz"}

        issues = validate_preview(project)

        self.assertIn("Invalid terrain geometry fingerprint", issues)

    def test_preview_project_rejects_malformed_terrain_attribute_fingerprint(self):
        project = {"format": "worldstudio-preview-v1", "nodes": [], "routes": [],
                   "terrain": "terrain.obj", "terrain_attributes_sha256": "bad"}

        issues = validate_preview(project)

        self.assertIn("Invalid terrain attribute fingerprint", issues)

    def test_embedded_preview_hides_inspector_by_default_and_exposes_toggle(self):
        scene = {"shapes": [], "nodes": [], "routes": []}
        embedded_page = build_document(scene, embedded=True)
        external_page = build_document(scene)

        self.assertIn('<body class="embedded">', embedded_page)
        self.assertIn('id="controls-toggle"', embedded_page)
        self.assertIn('id="graph-toggle"', embedded_page)
        self.assertIn('id="graph-expand"', embedded_page)
        self.assertIn("graph.classList.toggle('expanded')", embedded_page)
        self.assertIn("graphExpand.setAttribute('aria-pressed'", embedded_page)
        self.assertIn(".world-graph{display:none;position:absolute;z-index:2;right:12px;top:76px;width:min(380px,42vw);height:min(66vh,640px)", embedded_page)
        self.assertIn(".world-graph.expanded{width:min(500px,52vw);height:min(78vh,760px)", embedded_page)
        self.assertIn("graph.classList.add('open','expanded')", embedded_page)
        self.assertIn("#stage.graph-docked #view{right:auto;width:calc(100% - var(--world-graph-dock-width))}", embedded_page)
        self.assertIn("#stage.graph-docked .labels{right:var(--world-graph-dock-width)!important}", embedded_page)
        self.assertIn("stage.style.setProperty('--world-graph-dock-width'", embedded_page)
        self.assertIn("function syncGraphDock()", embedded_page)
        self.assertIn("graphToggle.addEventListener('click'", embedded_page)
        self.assertIn("syncGraphDock()", embedded_page)
        self.assertIn('id="world-graph-svg"', embedded_page)
        self.assertIn('viewBox="0 0 280 175"', embedded_page)
        self.assertIn("const width=280,rect=svg.getBoundingClientRect(),height=Math.max(175", embedded_page)
        self.assertIn("window.addEventListener('resize',syncGraphDock)", embedded_page)
        self.assertIn("const labelBoxes=[]", embedded_page)
        self.assertIn("const chosen=candidates.find", embedded_page)
        self.assertIn(".embedded .side{display:none}", embedded_page)
        self.assertIn("panel.classList.toggle('open')", embedded_page)
        self.assertIn(".embedded .side.open{left:12px;right:auto;top:104px;width:min(286px,calc(100vw - var(--world-graph-dock-width,0px) - 24px))}", embedded_page)
        self.assertIn("graph.classList.add('open','expanded')", embedded_page)
        self.assertIn("graphToggle.addEventListener('click'", embedded_page)
        self.assertIn("function updateGraphInset()", embedded_page)
        self.assertIn("line.setAttribute('class','edge'", embedded_page)
        self.assertIn("circle.setAttribute('class','node'", embedded_page)
        self.assertIn("updateGraphInset()", embedded_page)
        self.assertIn('<body class="">', external_page)
        self.assertNotIn('id="controls-toggle"', external_page)
        self.assertNotIn('id="graph-toggle"', external_page)

    def test_embedded_viewport_has_selection_and_incremental_overlay_api(self):
        page = build_document({"shapes": [], "nodes": [{"id": "W101", "editorId": "point:0",
                                                         "x": 0, "y": 0, "z": 0}],
                               "routes": [{"id": "RW101W102", "editorId": "segment:0",
                                           "start": "W101", "end": "W102"}]})
        self.assertIn("window.worldStudioView", page)
        self.assertIn("updateOverlays(data)", page)
        self.assertIn("selectEditorItem", page)
        self.assertIn("invoke('select_item'", page)
        self.assertIn("invoke('move_item'", page)
        self.assertIn("pickWorldNode", page)
        self.assertIn("overlays.selectedRoute", page)
        self.assertIn("id=\"world-graph\"", page)
        self.assertIn("data-editor-id", page)
        self.assertIn("updateSelectionOverlays()", page)
        self.assertIn("const object=meshes.find(mesh=>mesh.editorId===selectedEditorId)", page)
        self.assertIn("else if(object){selectMesh(object);if(focus)focusMesh(object)}", page)
        self.assertIn("drawOverlay(overlays.selectedRoute,[.24,1,.68,1]", page)
        self.assertIn("units=2*depth*Math.tan", page)
        self.assertIn("lastAppliedX:e.clientX", page)
        self.assertIn("const movedNow=drag.moved||Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)>3", page)

    def test_embedded_selected_route_overlay_tracks_selection_and_endpoints(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise viewport selection overlays")
        page = build_document({"shapes": [], "nodes": [
            {"id": "W101", "editorId": "point:0", "x": 1, "y": 2, "z": 3},
            {"id": "W102", "editorId": "point:1", "x": 4, "y": 5, "z": 6}], "routes": [
                {"id": "RW101W102", "editorId": "segment:0", "start": "W101", "end": "W102"}]})
        helper = page[page.index("function updateSelectionOverlays()"):]
        helper = helper[:helper.index("\n")]
        probe = """
const scene={nodes:[{id:'W101',editorId:'point:0',x:1,y:2,z:3},{id:'W102',editorId:'point:1',x:4,y:5,z:6}],routes:[{id:'RW101W102',editorId:'segment:0',start:'W101',end:'W102'}]};
const nodeMap=new Map(scene.nodes.map(node=>[node.id,node]));
let selectedEditorId='segment:0';
let overlays={selected:null,selectedRoute:null};
function replaceOverlay(_old,points,mode='LINES'){return points.length?{points,mode}:null}
""" + helper + "\nupdateSelectionOverlays();\nconsole.log(JSON.stringify(overlays));"
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True, text=True)
        overlays = json.loads(result.stdout)
        self.assertEqual(overlays["selected"], None)
        self.assertEqual(overlays["selectedRoute"]["mode"], "LINES")
        self.assertEqual(overlays["selectedRoute"]["points"], [[1, 2, 3], [4, 5, 6]])

    def test_embedded_drag_camera_plane_delta_tracks_screen_motion(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise viewer drag projection")
        page = build_document({"shapes": [], "nodes": [], "routes": []}, embedded=True)
        start = page.index("function cameraPlaneWorldDelta(")
        end = page.index("\n", start)
        helper = page[start:end]
        probe = helper + r"""
const identity=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const yaw90=[0,0,-1,0,0,1,0,0,1,0,0,0,0,0,0,1];
console.log(JSON.stringify([
  cameraPlaneWorldDelta(10,10,identity,100,0,100),
  cameraPlaneWorldDelta(10,0,yaw90,100,0,100)
]));
"""
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True, text=True)
        horizontal, rotated = json.loads(result.stdout)
        self.assertAlmostEqual(horizontal[0], 8.284271, places=5)
        self.assertAlmostEqual(horizontal[1], -8.284271, places=5)
        self.assertAlmostEqual(rotated[2], 8.284271, places=5)

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
        self.assertIn("texture2D(uTexture,vBaseUv)", page)
        self.assertIn("uRouteBlend<0.5&&texel.a<0.5", page)
        self.assertNotIn("https://", page)
        self.assertNotIn("</script><script>alert(1)", page)
        self.assertIn("<\\/script>", page)

    def test_vertex_color_diagnostic_packs_raw_channels_and_reports_display_clamping(self):
        node = shutil.which("node")
        colors = [(0.0, 0.5, 1.0, 1.0), (1.25, -0.25, 0.5, 0.9),
                  (0.2, 0.3, 0.4, 1.0)]
        page = build_document({"shapes": [{"name": "colored", "material": "mat",
                                            "positions": [(0, 0, 0), (1, 0, 0), (0, 1, 0)],
                                            "normals": [(0, 0, 1)] * 3,
                                            "indices": [0, 1, 2], "vertexColors": colors,
                                            "vertexAttributes": {"_c0": {"format": 0x80f}}}],
                               "nodes": [], "routes": []})
        embedded = json.loads(re.search(r"const scene=(.*?);", page).group(1))
        flat = [value for color in colors for value in color]
        self.assertEqual(base64.b64decode(embedded["shapes"][0]["vertexColorsPacked"]),
                         struct.pack("<12f", *flat))
        self.assertIn('<button id="vertex-colors" disabled>_c0 colors off</button>', page)
        self.assertIn("attribute vec4 aVertexColor", page)
        self.assertIn("gl.vertexAttribPointer(cLoc,4,gl.FLOAT,false,0,0)", page)
        self.assertIn("clamp(vVertexColor.rgb,0.0,1.0)", page)
        self.assertIn("shader behavior and the role of alpha are not evaluated.", page)
        self.assertIn("BFRES _c0${formatLabel} · raw ${rawRange}", page)
        if not node:
            self.skipTest("Node.js is required to exercise vertex color statistics")
        start = page.index("function vertexColorMetrics(")
        end = page.index("\nif(gl)", start)
        probe = page[start:end] + "\nconst values=" + json.dumps(flat) + ";" + \
            "console.log(JSON.stringify(vertexColorMetrics(new Float32Array(values))));"
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True,
                                text=True, encoding="utf-8")
        metrics = json.loads(result.stdout)
        self.assertEqual(metrics["vertexCount"], 3)
        self.assertEqual(metrics["finiteComponents"], 12)
        self.assertEqual(metrics["outOfDisplayRangeComponents"], 2)
        for actual, expected in zip(metrics["min"], [0, -0.25, 0.4, 0.9]):
            self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(metrics["max"], [1.25, 0.5, 1, 1]):
            self.assertAlmostEqual(actual, expected)
        with self.assertRaisesRegex(ValueError, "match the position count"):
            build_document({"shapes": [{"positions": [(0, 0, 0)],
                                         "vertexColors": []}], "nodes": [], "routes": []})

    def test_texture_fallback_reason_is_shown_as_inspector_text(self):
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        self.assertIn("textureWarning:shape.textureWarning||''", page)
        self.assertIn("row.className='inspector-row texture-warning';row.textContent='Texture fallback: '+mesh.textureWarning", page)
        self.assertIn("warning.className='shape-warning';warning.textContent='!'", page)
        self.assertIn("warning.title='Texture fallback: '+mesh.textureWarning", page)
        self.assertIn("+(mesh.textureWarning||'')", page)

    def test_material_sampler_wrap_modes_reach_webgl_texture_state(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise WebGL sampler wrap setup")
        wrap = {"samplerSlot": "_a0", "s": "mirror", "t": "clamp",
                "gx2": {"s": 1, "t": 2},
                "labels": {"s": "Mirror", "t": "Clamp"},
                "warnings": ["GX2 Clamp on T is approximated with WebGL CLAMP_TO_EDGE."]}
        scene = {"shapes": [{"name": "test", "material": "mat", "textureWrap": wrap}],
                 "nodes": [], "routes": []}
        page = build_document(scene)
        packed = json.loads(re.search(r"const scene=(.*?);", page).group(1))
        self.assertEqual(packed["shapes"][0]["textureWrap"], wrap)
        self.assertIn("textureWrap:shape.textureWrap||null", page)
        self.assertIn("createTexture(texturePayload,'base',shape.textureWrap)", page)
        self.assertIn("Sampler wrap note: '+warning", page)

        helper_start = page.index("function gx2WrapToWebGL(gl,mode){")
        helper_end = page.index("\nfunction wireEdges", helper_start)
        helper = page[helper_start:helper_end]
        probe = helper + r"""
globalThis.atob=value=>Buffer.from(value,'base64').toString('binary');
let nextId=0;const parameters=[];
const gl={REPEAT:101,MIRRORED_REPEAT:102,CLAMP_TO_EDGE:103,TEXTURE_2D:1,
TEXTURE_MIN_FILTER:2,LINEAR:3,TEXTURE_MAG_FILTER:4,TEXTURE_WRAP_S:5,
TEXTURE_WRAP_T:6,RGBA:7,UNSIGNED_BYTE:8,UNPACK_ALIGNMENT:9,
createTexture(){return{id:++nextId}},bindTexture(){},pixelStorei(){},texImage2D(){},
texParameteri(target,name,value){parameters.push([name,value])}};
const payload={name:'shared',width:1,height:1,rgbaBase64:'AAAAAA=='};
const mirrored=createTexture(payload,'base',{s:'mirror',t:'clamp'});
const mirroredAgain=createTexture(payload,'base',{s:'mirror',t:'clamp'});
const repeated=createTexture(payload,'base',{s:'repeat',t:'repeat'});
console.log(JSON.stringify({sameModeReusesTexture:mirrored===mirroredAgain,
differentModesUseDifferentTexture:mirrored!==repeated,
mirrorWraps:parameters.slice(2,4),repeatWraps:parameters.slice(6,8)}));
"""
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True,
                                text=True, encoding="utf-8")
        self.assertEqual(json.loads(result.stdout), {
            "sameModeReusesTexture": True,
            "differentModesUseDifferentTexture": True,
            "mirrorWraps": [[5, 102], [6, 103]],
            "repeatWraps": [[5, 101], [6, 101]],
        })

    def test_power_of_two_base_color_textures_use_mipmaps_only_for_base_maps(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise WebGL texture filtering")
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        helper_start = page.index("function gx2WrapToWebGL(gl,mode){")
        helper_end = page.index("\nfunction wireEdges", helper_start)
        helper = page[helper_start:helper_end]
        probe = helper + r"""
globalThis.atob=value=>Buffer.from(value,'base64').toString('binary');
const filters=[],mipmaps=[];let nextId=0;
const gl={REPEAT:101,MIRRORED_REPEAT:102,CLAMP_TO_EDGE:103,TEXTURE_2D:1,
TEXTURE_MIN_FILTER:2,LINEAR:3,LINEAR_MIPMAP_LINEAR:10,TEXTURE_MAG_FILTER:4,
TEXTURE_WRAP_S:5,TEXTURE_WRAP_T:6,RGBA:7,UNSIGNED_BYTE:8,UNPACK_ALIGNMENT:9,
createTexture(){return{id:++nextId}},bindTexture(){},pixelStorei(){},texImage2D(){},
generateMipmap(){mipmaps.push('generated')},
texParameteri(target,name,value){if(name===2)filters.push(value)}};
const data=(name,width,height)=>({name,width,height,rgbaBase64:Buffer.alloc(width*height*4).toString('base64')});
createTexture(data('pot',4,8),'base');
createTexture(data('npot',3,8),'base');
createTexture(data('diagnostic',4,8),'bc4');
console.log(JSON.stringify({mipmaps:mipmaps.length,filters}));
"""
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True,
                                text=True, encoding="utf-8")
        self.assertEqual(json.loads(result.stdout), {
            "mipmaps": 1,
            "filters": [10, 3, 3],
        })

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
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True,
                                text=True, encoding="utf-8")
        fit, zoomed_out, close, invalid = json.loads(result.stdout)
        for near, far in (fit, zoomed_out, close, invalid):
            self.assertTrue(0 < near < far)
            self.assertTrue(all(map(lambda value: value == value and abs(value) != float("inf"), (near, far))))
        self.assertLess(fit[1] / fit[0], 3)
        self.assertLess(zoomed_out[1] / zoomed_out[0], 1.2)
        self.assertLess(close[1] / close[0], 400)
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
        self.assertIn("modeS=wrap.s||'repeat'", page)
        self.assertIn("gx2WrapToWebGL(gl,modeS)", page)
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
        self.assertIn("mesh.normalTextureName+' '+mesh.diagnosticTextureName+' '+mesh.maskTextureName+' '+(mesh.textureWarning||'')).concat(' ',bc4Search,' ',samplerSearch).toLowerCase()", page)
        self.assertIn("shape.samplerTextures||{}", page)
        self.assertIn("scene.maskTextures?.[key]", page)
        self.assertIn("samplerPreviews[slot]=payload", page)

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
        self.assertIn('textureMapLabel(kind,payload,shader?.samplerSymbols)', page)
        self.assertIn('BC5 UNorm stored channels are shown for inspection; shader behavior is not evaluated.', page)
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
let focusedMesh=null,selectedEditorId='',rpcSelection=null;function focusMesh(mesh){focusedMesh=mesh}function selectEditorItem(id){selectedEditorId=id}globalThis.window={tkwry:{invoke:(name,payload)=>{rpcSelection={name,payload}}}}
""" + helper + r"""
const a={name:'Grass <test>',material:'mtGrass',color:[.2,.4,.6],textureName:'Grass_alb',normalTextureName:'Grass_nml',vertexCount:12,triangleCount:8,hasUvs:true,visible:true,boundBone:'W101',editorId:'point:0',submeshes:[{indexOffset:0,indexCount:18},{indexOffset:18,indexCount:6}]};
const b={name:'Rock',material:'mtRock',color:[.3,.3,.3],textureName:'',normalTextureName:'',vertexCount:9,triangleCount:4,hasUvs:false,visible:true};
a.shaderMetadata={archiveName:'shader',programName:'route',samplerSymbols:{_o0:'cTexMapRouteMask'},uniformNames:['texmtx0'],vertexSkinCount:0,variationCount:6,variationSelection:{candidate_index:2,candidate_count:6,selection_model:'AGL material-option lookup; shape variation unresolved',macro_values:[{name:'MODE',value:'1',source:'material-option'}],unresolved_macros:['NUM_SKINNING_VTX'],ignored_options:[]},attributeBindings:{_u4:{shader_name:'aTexCoordRouteMask',source_attribute:'_u2',present:true,format:0x80d,offset:24}}};
addShapeRow(a);addShapeRow(b);a.row.children[2].listeners.click();
if(!a.row.classList.contains('selected'))throw Error('selected row is not marked');
const first=registry.selection.children.map(x=>x.textContent).join('\n');
if(!first.includes('Grass <test>')||!first.includes('12 vertices / 8 triangles')||!first.includes('Grass_alb')||!first.includes('Grass_nml (BC5 SNORM map)')||!first.includes('Rigid rest-pose bone: W101')||!first.includes('BFRES index submeshes: 2'))throw Error(first);
const submeshPanel=registry.selection.children.find(x=>x.className==='submesh-interface');if(!submeshPanel||!submeshPanel.children.some(x=>x.textContent==='Part 2: indices 18–23 · 2 triangles'))throw Error('submesh index ranges are not visible');
const shaderPanel=registry.selection.children.find(x=>x.className==='shader-interface');if(!shaderPanel)throw Error('missing expandable shader inspector');
const shaderText=shaderPanel.children.map(x=>x.textContent).join('\n');
if(!shaderPanel.children[0].textContent.includes('AGL material-option candidate: 2 / 6')||!shaderText.includes('BFRES vertex skin count: 0; skinning macro value mapping remains unresolved')||!shaderText.includes('Unresolved shape-specific inputs: NUM_SKINNING_VTX')||!shaderText.includes('Vertex input _u4: aTexCoordRouteMask <- BFRES _u2 (format 0x80D at 24)')||!shaderText.includes('Samplers: _o0=cTexMapRouteMask'))throw Error(shaderText);
registry.selection.children.find(x=>x.className==='focus-mesh'&&x.textContent==='Focus mesh').listeners.click();if(focusedMesh!==a)throw Error('focus action is not linked to selection');const boundButton=registry.selection.children.find(x=>x.textContent==='Select bound bone in editor');if(!boundButton)throw Error('missing bound-bone editor action');boundButton.listeners.click();if(selectedEditorId!=='point:0'||rpcSelection?.name!=='select_item'||rpcSelection.payload.payload.editorId!=='point:0')throw Error('bound bone did not synchronize editor selection');
b.row.children[2].listeners.click();
if(a.row.classList.contains('selected')||!b.row.classList.contains('selected'))throw Error('selection did not move');
if(!registry.selection.children.map(x=>x.textContent).join('\n').includes('UV coordinates: absent'))throw Error('missing UV status');
if(a.row.children[2].tagName!=='button'||a.row.children[2].attributes['aria-label']!=='Inspect Grass <test>')throw Error('selection button is not accessible');
registry.selection.children.find(x=>x.className==='focus-mesh'&&x.textContent==='Focus mesh').listeners.click();if(focusedMesh!==b)throw Error('focus action did not follow selection');
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
        self.assertIn("Texture maps · stored format and dimensions", page)
        self.assertIn("textureMapLabel(kind,payload,shader?.samplerSymbols)", page)

    def test_material_texture_labels_show_dimensions_and_observed_formats(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise material inspector labels")
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        start = page.index("function textureMapLabel(kind,payload,samplerSymbols={}){")
        end = page.index("\nconst textureThumbnailCache", start)
        helper = page[start:end]
        probe = helper + r"""
const maps={
base:{name:'Albedo',width:256,height:128,format:0x33},
bc5:{name:'Normal',width:64,height:32,format:0x235},
diagnostic:{name:'Mask',width:4,height:8,format:0x35,samplerSlot:'_o0'},
bc4:{name:'RouteW1_msk',width:128,height:256,format:0x34,samplerSlot:'_o1'},
sampler:{name:'lmDifCSW1a',width:16,height:16,format:0x33,samplerSlot:'_x0'}
};
const symbols={_o0:'cTexMapRouteMask',_o1:'cTexMapEdgeMask',_x0:'cLightMap0'};
console.log(JSON.stringify(Object.entries(maps).map(([kind,payload])=>textureMapLabel(kind,payload,symbols))));
"""
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True,
                                text=True, encoding="utf-8")
        self.assertEqual(json.loads(result.stdout), [
            "Base color | Albedo | 256x128 | BC3 UNorm",
            "Normal map | Normal | 64x32 | BC5 SNORM",
            "Sampler _o0 · cTexMapRouteMask | Mask | 4x8 | BC5 UNorm",
            "Sampler _o1 · cTexMapEdgeMask | RouteW1_msk | 128x256 | BC4 UNorm",
            "Sampler _x0 · cLightMap0 | lmDifCSW1a | 16x16 | BC3 UNorm",
        ])

    def test_bc4_sampler_selector_orders_route_slot_and_lists_available_maps(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise the BC4 sampler selector")
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        self.assertIn('<select id="bc4-slot" aria-label="BC4 diagnostic sampler">', page)
        self.assertIn("bc4Button.textContent=`${selectedBc4Slot} BC4", page)
        self.assertIn("const activeBc4Texture=m.bc4Textures[selectedBc4Slot]||null", page)
        start = page.index("function uniqueBc4Slots(meshes){")
        end = page.index("\nconst textureThumbnailCache", start)
        helper = page[start:end]
        probe = helper + r"""
console.log(JSON.stringify([
uniqueBc4Slots([{bc4Textures:{_b0:{},_o1:{}}},{bc4Textures:{_s0:{},_o1:{}}}]),
uniqueBc4Slots([{bc4Textures:{_b0:{},_s0:{}}}]),
uniqueBc4Slots([])
]));
"""
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), [["_o1", "_b0", "_s0"], ["_b0", "_s0"], []])

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
        self.assertIn("texture2D(uTexture,vBaseUv).a<0.5", page)
        self.assertIn("aBaseUv", page)
        self.assertIn("gl.drawElements(gl.TRIANGLES,mesh.count,gl.UNSIGNED_SHORT,0)", page)
        self.assertIn("selectMesh(meshes[index])", page)
        self.assertIn("previous.button===0&&Math.hypot(e.clientX-previous.startX,e.clientY-previous.startY)<4", page)
        self.assertIn("Drag a native world point to move", page)
        self.assertIn("pickMeshAt", page)

    def test_route_base_texture_uvs_apply_supported_srt_and_reject_unsupported_modes(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise route texture transforms")
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        start = page.index("function routeBaseTextureUvs(")
        end = page.index("\nfunction vertexColorMetrics(", start)
        helper = page[start:end]
        probe = helper + r"""
const uv=new Float32Array([0.25,0.75,1,0]);
const shifted=routeBaseTextureUvs(uv,{mode:0,scale:[1,1],rotation:0,translation:[0,-29]},{s:'repeat',t:'repeat'});
const clamped=routeBaseTextureUvs(uv,{mode:0,scale:[1,1],rotation:0,translation:[0,-29]},{s:'repeat',t:'clamp'});
const unsupported=routeBaseTextureUvs(uv,{mode:1,scale:[1,1],rotation:0,translation:[0,-29]});
if(Array.from(shifted).join(',')!=='0.25,0.75,1,0')throw Error('repeat-safe route offset not applied');
if(Array.from(clamped).join(',')!=='0.25,-28.25,1,-29')throw Error('clamped route offset was incorrectly reduced');
if(unsupported!==uv)throw Error('unsupported SRT mode changed UVs');
console.log('ok');
"""
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), "ok")
        self.assertIn("shape.depthBias===true?shape.textureSrt?.texmtx0:null", page)
        self.assertIn("texture2D(uTexture,vBaseUv)", page)

    def test_focus_mesh_centers_the_camera_and_uses_mesh_radius(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise viewer camera focus")
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        start = page.index("const bounds=scene.bounds||")
        end = page.index("\nfunction cameraPreset", start)
        focus = re.search(r"function focusMesh\(mesh\)\{[^}]*\}", page)
        self.assertIsNotNone(focus)
        helper = page[start:end] + "\nfunction syncCameraTargetInputs(){}\n" + focus.group(0)
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

    def test_camera_target_inputs_update_preview_focus_and_reject_invalid_values(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise preview target controls")
        page = build_document({"shapes": [], "nodes": [], "routes": []})
        for control in ("target-x", "target-y", "target-z", "apply-camera-target"):
            self.assertIn(f'id="{control}"', page)
        self.assertIn("input.valueAsNumber", page)
        self.assertIn("syncCameraTargetInputs();clearCameraPreset()", page)
        start = page.index("function parseCameraTarget(values){")
        end = page.index("\nfunction syncCameraTargetInputs", start)
        helpers = page[start:end]
        probe = "let viewCenter=[1,2,3],target=[8,9,10];\n" + helpers + r"""
const valid=setCameraTarget([10,-4,2.5]);const validState=[viewCenter,target];
const badNaN=setCameraTarget([NaN,0,0]),badRange=setCameraTarget([1000001,0,0]),badBlank=setCameraTarget(['',0,0]);
console.log(JSON.stringify({valid,validState,badNaN,badRange,badBlank,afterInvalid:viewCenter}));
"""
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True, text=True)
        output = json.loads(result.stdout)
        self.assertTrue(output["valid"])
        self.assertEqual(output["validState"], [[10, -4, 2.5], [0, 0, 0]])
        self.assertFalse(output["badNaN"])
        self.assertFalse(output["badRange"])
        self.assertFalse(output["badBlank"])
        self.assertEqual(output["afterInvalid"], [10, -4, 2.5])

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
        page = build_document(scene, embedded=True)
        script = re.search(r"<script>(.*?)</script>", page, re.DOTALL).group(1)
        subprocess.run([node, "--check", "-"], input=script, check=True,
                       capture_output=True, text=True, encoding="utf-8")

    def test_texture_srt_values_are_read_only_inspector_metadata(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise the texture SRT label")
        srt = {"mode": 0, "scale": [1.0, 1.0], "rotation": 0.0,
               "translation": [0.0, -3.0]}
        scene = {"shapes": [{"name": "route", "material": "routeMat",
                             "textureSrt": {"texmtx0": srt}, "positions": [],
                             "normals": [], "indices": []}], "nodes": [], "routes": []}
        page = build_document(scene)
        packed = json.loads(re.search(r"const scene=(.*?);", page).group(1))
        self.assertEqual(packed["shapes"][0]["textureSrt"], {"texmtx0": srt})
        self.assertIn("mesh.textureSrt=metadata.textureSrt||{}", page)
        self.assertIn("mesh.boundBone=metadata.boundBone||''", page)
        self.assertIn("row.textContent=textureSrtLabel(name,srt)", page)
        self.assertIn("transform math and sampler association are unresolved.", page)
        self.assertIn("Assigned program declares ${matched.join(', ')}", page)
        start = page.index("function textureSrtLabel(name,srt){")
        end = page.index("\nfunction selectMesh", start)
        helper = page[start:end]
        result = subprocess.run(
            [node, "-e", helper + "\nconsole.log(textureSrtLabel('texmtx0'," + json.dumps(srt) + "))"],
            check=True, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.stdout.strip(),
                         "texmtx0 \u00b7 mode 0 \u00b7 scale (1.000, 1.000) \u00b7 rotation 0.000 \u00b7 translation (0.000, -3.000)")

    def test_raw_uv_diagnostic_reports_bounds_and_rejects_invalid_triangles(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise the UV diagnostic")
        page = build_document({"shapes": [{"name": "mesh", "material": "mat",
                                            "positions": [], "normals": [],
                                            "indices": [0, 1, 2],
                                            "uvs": [(0, 0), (1, 0), (2, -1)],
                                            "uvAttributes": {"_u0": [(0, 0), (1, 0), (2, -1)],
                                                             "_u1": [(0.25, 0.75), (0.5, 0.5), (1, 0)]},
                                            "vertexAttributes": {"_u0": {"format": 0x80d},
                                                                 "_u1": {"format": 0x7}}}],
                               "nodes": [], "routes": []})
        self.assertIn("uvsPacked:shape.uvsPacked||null", page)
        self.assertIn("uvAttributesPacked:shape.uvAttributesPacked||{}", page)
        self.assertIn("Raw BFRES ${name}${formatLabel} · untransformed", page)
        self.assertIn("no texture SRT or sampler transform is applied; shader input names do not establish sampler usage", page)
        self.assertIn("V increases upward", page)
        embedded = json.loads(re.search(r"const scene=(.*?);", page).group(1))
        shape = embedded["shapes"][0]
        self.assertEqual(base64.b64decode(shape["uvAttributesPacked"]["_u1"]),
                         struct.pack("<6f", 0.25, 0.75, 0.5, 0.5, 1, 0))
        self.assertNotIn("_u0", shape["uvAttributesPacked"])
        start = page.index("function uvChartMetrics(")
        end = page.index("\nfunction drawUvChart", start)
        metrics_helper = page[start:end]
        draw_start = page.index("function drawUvChart(")
        draw_end = page.index("\nfunction selectMesh", draw_start)
        draw_helper = page[draw_start:draw_end]
        probe = metrics_helper + "\n" + draw_helper + r'''
const uvs=new Float32Array([0,0,1,0,2,-1,NaN,0]);
const indices=new Uint16Array([0,1,2,0,2,99,0,1,3]);
const stats=uvChartMetrics(uvs,indices);
const noop=()=>{};
const context={clearRect:noop,fillRect:noop,beginPath:noop,moveTo:noop,lineTo:noop,
  stroke:noop,strokeRect:noop,closePath:noop,fillText:noop};
const canvas={width:360,height:203,getContext:()=>context};
console.log(JSON.stringify({stats,drawn:drawUvChart(canvas,uvs,indices,stats)}));
'''
        result = subprocess.run([node, "-e", probe], check=True, capture_output=True,
                                text=True, encoding="utf-8")
        output = json.loads(result.stdout)
        self.assertEqual(output["stats"], {
            "vertexCount": 4, "finiteUvCount": 3, "outOfRangeCount": 1,
            "triangleCount": 3, "validTriangleCount": 1,
            "invalidTriangleCount": 2, "bounds": [0, -1, 2, 0]})
        self.assertEqual(output["drawn"], 1)

        unpack_start = page.index("function unpackArray(")
        packed_helpers = page[unpack_start:page.index("\nif(gl)", unpack_start)]
        uv_diagnostic = page[page.index("function addUvDiagnostic("):page.index("\nfunction selectMesh")]
        u0 = base64.b64encode(struct.pack("<6f", 0, 0, 1, 0, 2, -1)).decode("ascii")
        u1 = base64.b64encode(struct.pack("<6f", .25, .75, .5, .5, 1, 0)).decode("ascii")
        triangle = base64.b64encode(struct.pack("<3H", 0, 1, 2)).decode("ascii")
        selector_probe = packed_helpers + "\n" + metrics_helper + "\n" + draw_helper + "\n" + uv_diagnostic + r'''
const context={clearRect(){},fillRect(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},
  strokeRect(){},closePath(){},fillText(){}};
function element(tag){return{tag,children:[],events:{},appendChild(child){this.children.push(child);if(this.tag==='select'&&this.children.length===1)this.value=child.value},
  setAttribute(){},addEventListener(name,callback){this.events[name]=callback},replaceChildren(...children){this.children=children},
  getContext(){return context}}}
global.document={createElement:element};
const panel=element('div'),mesh={uvsPacked:'U0',uvAttributesPacked:{_u1:'U1'},indicesPacked:'IDX',
  vertexAttributes:{_u0:{format:2061},_u1:{format:7}}};
global.atob=value=>Buffer.from(value==='U0'?'__U0__':value==='U1'?'__U1__':'__IDX__','base64').toString('binary');
addUvDiagnostic(panel,mesh);
const chartPanel=panel.children.find(item=>item.className==='uv-diagnostic');
if(!chartPanel)throw Error(panel.children.map(item=>item.textContent).join('|'));
const selector=chartPanel.children[1],title=chartPanel.children[0];
const initial={label:title.textContent,options:selector.children.map(item=>item.textContent)};
selector.value='_u1';selector.events.change();
console.log(JSON.stringify({initial,selected:title.textContent,stats:chartPanel.children[3].children.map(item=>item.textContent)}));
'''.replace('__U0__', u0).replace('__U1__', u1).replace('__IDX__', triangle)
        result = subprocess.run([node, "-e", selector_probe], capture_output=True,
                                text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        chart = json.loads(result.stdout)
        self.assertEqual(chart["initial"]["label"], "Raw BFRES _u0 · format 0x80D · untransformed")
        self.assertEqual(chart["initial"]["options"], ["_u0 · format 0x80D", "_u1 · format 0x7"])
        self.assertEqual(chart["selected"], "Raw BFRES _u1 · format 0x7 · untransformed")
        self.assertTrue(any(value.startswith("Bounds U 0.250…1.000") for value in chart["stats"]))

    def test_shader_option_candidate_is_embedded_and_labeled_as_unresolved(self):
        metadata = {
            "archiveName": "nw4f_cs_shader",
            "programName": "nw4f_cs_route_shader",
            "samplerSymbols": {"_o0": "cTexMapRouteMask"},
            "uniformNames": ["texmtx0"],
            "variationCount": 576,
            "variationSelection": {
                "candidate_index": 42,
                "candidate_count": 576,
                "macro_values": [{"name": "AO_TYPE", "value": "2"}],
            },
        }
        scene = {"shapes": [{"name": "route", "material": "routeMat",
                             "shaderMetadata": metadata, "positions": [],
                             "normals": [], "indices": []}], "nodes": [], "routes": []}
        page = build_document(scene)
        packed = json.loads(re.search(r"const scene=(.*?);", page).group(1))
        self.assertEqual(packed["shapes"][0]["shaderMetadata"]["variationSelection"],
                         metadata["variationSelection"])
        self.assertIn("AGL material-option candidate:", page)
        self.assertIn("shape-specific variation unresolved", page)
        self.assertIn("Candidate options:", page)

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
