"""Self-contained WebGL viewer for locally loaded world geometry."""
from __future__ import annotations

from array import array
import base64
import sys
import json
import tempfile
import uuid
import webbrowser
from pathlib import Path


_PAGE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NSMBU World Studio · 3D Preview</title>
<style>
:root{color-scheme:dark;font:14px/1.45 "Segoe UI",system-ui,sans-serif;background:#0b1119;color:#e9f0f7}
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#0b1119}
button,input{font:inherit}button{border:1px solid #344456;border-radius:8px;padding:8px 12px;color:#e6eef7;background:#172433;cursor:pointer;transition:.16s}
button:hover{background:#22384c;border-color:#4b708e}button.active{background:#1c4c50;border-color:#40b9a5;color:#d5fff5}
#stage{position:fixed;inset:0;background:radial-gradient(ellipse at 45% 40%,#1a2a39 0,#0d1721 58%,#090e15 100%)}
canvas{position:absolute;inset:0;width:100%;height:100%;display:block;touch-action:none}
.top{position:absolute;top:18px;left:20px;right:20px;display:flex;align-items:center;gap:14px;pointer-events:none}
.brand,.title,.actions,.badge{pointer-events:auto}.brand{display:flex;align-items:center;gap:9px;color:#9fb3c6;font-size:11px;letter-spacing:.12em;font-weight:700}
.mark{width:31px;height:31px;border-radius:10px;display:grid;place-items:center;color:#0c171b;background:linear-gradient(145deg,#7be1a7,#61bdd0);font-weight:900;letter-spacing:0}
.title{min-width:0}.title strong{display:block;font-size:16px;letter-spacing:.01em}.title span{color:#9db0c1;font-size:12px}
.badges{display:flex;gap:7px;margin-left:8px;flex-wrap:wrap}.badge{padding:5px 9px;border:1px solid #2b3b4c;border-radius:20px;color:#b8c9d8;background:#111d29;font-size:11px;white-space:nowrap}
.actions{display:flex;gap:7px;margin-left:auto}.actions button{font-size:12px}
.side{position:absolute;right:20px;top:80px;bottom:62px;width:286px;border:1px solid #2c3b4c;border-radius:14px;background:rgba(13,22,32,.91);box-shadow:0 18px 60px #0005;backdrop-filter:blur(14px);display:flex;flex-direction:column;overflow:hidden}
.sidehead{padding:15px 15px 11px;border-bottom:1px solid #293746}.sidehead strong{display:block;font-size:13px}.sidehead small{color:#91a4b6}
.search{width:100%;margin-top:11px;border:1px solid #2b3b4c;border-radius:8px;background:#101a25;color:#e9f0f7;padding:8px 10px;outline:none}.search:focus{border-color:#4e9ab2}
.shapes{overflow:auto;padding:6px 8px 10px}.shape{display:flex;align-items:center;gap:9px;padding:8px 7px;border-radius:8px;color:#d3deea;font-size:12px}.shape:hover{background:#1a2836}.shape input{accent-color:#54c99a}.swatch{width:10px;height:10px;border-radius:3px;flex:none;box-shadow:0 0 10px #fff2}.shape span:last-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bottom{position:absolute;bottom:16px;left:20px;right:20px;display:flex;align-items:flex-end;justify-content:space-between;gap:16px;pointer-events:none}.hint,.notice{padding:9px 12px;border:1px solid #293747;border-radius:9px;background:#0d1720d9;color:#a9bac9;font-size:11px;pointer-events:auto}.notice{max-width:480px;color:#c6d4e0}
.labels{position:absolute;inset:0 320px 0 0;pointer-events:none}.label{position:absolute;color:#f8e3a0;text-shadow:0 1px 7px #000,0 0 3px #000;font-size:11px;font-weight:700;white-space:nowrap;transform:translate(-50%,-125%)}
#error{display:none;position:absolute;inset:0;z-index:4;place-items:center;padding:24px;text-align:center;color:#ffe6b3;background:rgba(7,12,18,.94)}
@media(max-width:900px){.side{width:245px;right:12px;top:112px;bottom:58px}.top{left:12px;right:12px;align-items:flex-start;flex-wrap:wrap}.actions{margin-left:auto}.badges{display:none}.bottom{left:12px;right:12px}.labels{right:270px}}
</style>
</head>
<body>
<div id="stage"><canvas id="view"></canvas>
<div class="top"><div class="brand"><div class="mark">W</div><span>WORLD STUDIO</span></div>
<div class="title"><strong id="heading"></strong><span id="subtitle"></span></div>
<div class="badges" id="badges"></div>
<div class="actions"><button id="paths" class="active">Paths on</button><button id="fit">Fit view</button></div></div>
<aside class="side"><div class="sidehead"><strong>World model</strong><small id="model-info"></small><input id="filter" class="search" placeholder="Filter shapes…" autocomplete="off"></div><div id="shapes" class="shapes"></div></aside>
<div id="labels" class="labels"></div>
<div class="bottom"><div class="hint">Drag to orbit · right-drag to pan · wheel to zoom · use shape checkboxes to show or hide meshes</div><div id="notice" class="notice">Static BFRES geometry with approximate material colors and directional lighting. Only explicitly supported base textures are displayed.</div></div>
<div id="error"></div></div>
<script>
"use strict";
const scene=__SCENE__;
const heading=document.getElementById('heading'), subtitle=document.getElementById('subtitle');
heading.textContent=scene.title||'World preview'; subtitle.textContent=scene.model||'Imported mesh';
if(scene.textureNotice)document.getElementById('notice').textContent=scene.textureNotice;
document.getElementById('model-info').textContent=`${scene.shapes.length} shapes · ${scene.stats?.vertices||0} vertices · ${scene.stats?.triangles||0} triangles`;
const badges=document.getElementById('badges');
for(const text of scene.badges||[]){const el=document.createElement('span');el.className='badge';el.textContent=text;badges.appendChild(el)}
const error=document.getElementById('error');
function showError(message){error.textContent=message;error.style.display='grid'}
const canvas=document.getElementById('view');let gl=null;
try{gl=canvas.getContext('webgl',{antialias:true,alpha:false,powerPreference:'high-performance'})}catch(e){showError('Could not create the WebGL context: '+(e?.message||String(e)))}
if(!gl)showError('WebGL is unavailable in this browser. Enable hardware acceleration or open the preview in another browser.')
function shader(type,source){const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s}
function program(vs,fs){const p=gl.createProgram();gl.attachShader(p,shader(gl.VERTEX_SHADER,vs));gl.attachShader(p,shader(gl.FRAGMENT_SHADER,fs));gl.linkProgram(p);if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(p));return p}
let meshProgram=null,overlayProgram=null;
if(gl){try{meshProgram=program(`attribute vec3 aPosition;attribute vec3 aNormal;attribute vec2 aUv;uniform mat4 uMvp;uniform mat3 uNormal;varying vec3 vNormal;varying vec2 vUv;void main(){gl_Position=uMvp*vec4(aPosition,1.0);vNormal=normalize(uNormal*aNormal);vUv=aUv;}`,`precision mediump float;uniform vec3 uColor;uniform sampler2D uTexture;uniform float uHasTexture;varying vec3 vNormal;varying vec2 vUv;void main(){vec3 n=normalize(vNormal);float d=max(dot(n,normalize(vec3(-0.42,0.82,0.36))),0.0);float rim=pow(1.0-max(dot(n,vec3(0.0,0.0,1.0)),0.0),2.0)*0.08;vec4 texel=texture2D(uTexture,vUv);if(uHasTexture>0.5&&texel.a<0.5)discard;vec3 base=mix(uColor,texel.rgb,uHasTexture);vec3 c=base*(0.42+0.72*d)+rim;gl_FragColor=vec4(c,1.0);}`);
overlayProgram=program(`attribute vec3 aPosition;uniform mat4 uMvp;uniform float uPointSize;void main(){gl_Position=uMvp*vec4(aPosition,1.0);gl_PointSize=uPointSize;}`,`precision mediump float;uniform vec4 uColor;uniform float uRound;void main(){if(uRound>0.5&&distance(gl_PointCoord,vec2(0.5))>0.48)discard;gl_FragColor=uColor;}`);}catch(e){showError('Could not initialize the WebGL renderer: '+(e?.message||String(e)));gl=null}}
function loc(p,n){return gl.getAttribLocation(p,n)}
function buffer(data,target=gl.ARRAY_BUFFER,usage=gl.STATIC_DRAW){const b=gl.createBuffer();gl.bindBuffer(target,b);gl.bufferData(target,data,usage);return b}
function colorFor(name,index){const n=name.toLowerCase();if(/grass|kusa|leaf/.test(n))return[0.31,0.68,0.35];if(/water|mizu/.test(n))return[0.22,0.59,0.79];if(/snow|ice|yuki/.test(n))return[0.76,0.85,0.9];if(/sand|sunaba/.test(n))return[0.78,0.65,0.39];if(/rock|gake|stone/.test(n))return[0.48,0.53,0.53];if(/tree|wood|trunk|ki/.test(n))return[0.43,0.31,0.19];if(/castle|dokan|brick/.test(n))return[0.68,0.4,0.28];if(/route|road|path/.test(n))return[0.48,0.53,0.55];const h=[...name].reduce((a,c)=>(a*33+c.charCodeAt(0))>>>0,2166136261);return[0.38+(h&255)/850,0.4+((h>>>8)&255)/1100,0.42+((h>>>16)&255)/900]}
const textureCache=new Map();function createTexture(payload){if(textureCache.has(payload.name))return textureCache.get(payload.name);const binary=atob(payload.rgbaBase64),pixels=new Uint8Array(binary.length);for(let i=0;i<binary.length;i++)pixels[i]=binary.charCodeAt(i);if(pixels.length!==payload.width*payload.height*4)throw Error('Invalid decoded '+payload.name+' RGBA texture');const texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);gl.pixelStorei(gl.UNPACK_ALIGNMENT,1);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,payload.width,payload.height,0,gl.RGBA,gl.UNSIGNED_BYTE,pixels);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.REPEAT);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.REPEAT);textureCache.set(payload.name,texture);return texture}
let meshes=[];
function unpackArray(payload,Type,itemSize){const binary=atob(payload),bytes=new Uint8Array(binary.length);if(bytes.length%itemSize)throw Error('Invalid packed geometry array');for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);return new Type(bytes.buffer)}
if(gl){try{meshes=scene.shapes.map((shape,index)=>{const positions=shape.positionsPacked?unpackArray(shape.positionsPacked,Float32Array,4):new Float32Array(shape.positions.flat());const normals=shape.normalsPacked?unpackArray(shape.normalsPacked,Float32Array,4):new Float32Array(shape.normals.flat());const uvs=shape.uvsPacked?unpackArray(shape.uvsPacked,Float32Array,4):(shape.uvs?new Float32Array(shape.uvs.flat()):null);const indices=shape.indicesPacked?unpackArray(shape.indicesPacked,Uint16Array,2):new Uint16Array(shape.indices);const texturePayload=typeof shape.texture==='string'?scene.textures?.[shape.texture]:shape.texture;if(shape.texture&&!texturePayload)throw Error('Missing texture payload for '+shape.texture);return{name:shape.name,material:shape.material,textureName:typeof shape.texture==='string'?shape.texture:(shape.texture?.name||''),color:colorFor(shape.material,index),count:shape.indexCount??shape.indices.length,visible:true,pos:buffer(positions),normal:buffer(normals),uv:uvs?buffer(uvs):null,texture:texturePayload?createTexture(texturePayload):null,index:buffer(indices,gl.ELEMENT_ARRAY_BUFFER)}})}catch(e){showError('Could not build the 3D preview: '+(e?.message||String(e)))}}
const materials=new Map();for(const m of meshes)if(!materials.has(m.material))materials.set(m.material,m.color);
const list=document.getElementById('shapes');
function addShapeRow(mesh){const row=document.createElement('label');row.className='shape';const check=document.createElement('input');check.type='checkbox';check.checked=true;check.addEventListener('change',()=>{mesh.visible=check.checked});const sw=document.createElement('i');sw.className='swatch';sw.style.background=`rgb(${mesh.color.map(x=>Math.round(x*255)).join(',')})`;const name=document.createElement('span');name.textContent=mesh.name;name.title=`${mesh.name} · ${mesh.material}${mesh.textureName?' · '+mesh.textureName:''}`;row.append(check,sw,name);row.dataset.search=(mesh.name+' '+mesh.material+' '+mesh.textureName).toLowerCase();list.appendChild(row)}
for(const mesh of meshes)addShapeRow(mesh);
document.getElementById('filter').addEventListener('input',e=>{const q=e.target.value.toLowerCase();for(const row of list.children)row.hidden=!row.dataset.search.includes(q)});
document.getElementById('paths').addEventListener('click',e=>{scene.showPaths=!scene.showPaths;e.currentTarget.classList.toggle('active',scene.showPaths);e.currentTarget.textContent=scene.showPaths?'Paths on':'Paths off'});
const bounds=scene.bounds||{center:[0,0,0],radius:600};const sceneRadius=Number.isFinite(bounds.radius)&&bounds.radius>0?bounds.radius:600;let yaw=scene.camera?.yaw??-0.6,pitch=scene.camera?.pitch??0.65,distance=Math.max(20,sceneRadius*2.65);let target=[0,0,0];let drag=null;let mvp=null,normalMatrix=null;
function cameraPlanes(distance,radius){const r=Number.isFinite(radius)&&radius>0?radius:1;const d=Number.isFinite(distance)&&distance>0?distance:r*2;const padding=r*1.05;const near=Math.max(r*0.001,d-padding);const far=Math.max(d+padding,near+r*0.01);return[near,far]}
function mul(a,b){const o=new Float32Array(16);for(let c=0;c<4;c++)for(let r=0;r<4;r++)o[c*4+r]=a[r]*b[c*4]+a[4+r]*b[c*4+1]+a[8+r]*b[c*4+2]+a[12+r]*b[c*4+3];return o}
function perspective(fov,aspect,near,far){const f=1/Math.tan(fov/2),nf=1/(near-far);return new Float32Array([f/aspect,0,0,0,0,f,0,0,0,0,(far+near)*nf,-1,0,0,2*far*near*nf,0])}
function translate(x,y,z){return new Float32Array([1,0,0,0,0,1,0,0,0,0,1,0,x,y,z,1])}
function rotate(){const cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);const ry=new Float32Array([cy,0,sy,0,0,1,0,0,-sy,0,cy,0,0,0,0,1]);const rx=new Float32Array([1,0,0,0,0,cp,sp,0,0,-sp,cp,0,0,0,0,1]);return mul(rx,ry)}
function updateMatrices(){const aspect=canvas.width/Math.max(1,canvas.height),rot=rotate(),[near,far]=cameraPlanes(distance,sceneRadius),p=perspective(Math.PI/4,aspect,near,far);mvp=mul(p,mul(translate(-target[0],-target[1],-distance),mul(rot,translate(-bounds.center[0],-bounds.center[1],-bounds.center[2]))));normalMatrix=new Float32Array([rot[0],rot[1],rot[2],rot[4],rot[5],rot[6],rot[8],rot[9],rot[10]])}
function resize(){const dpr=Math.min(devicePixelRatio||1,2),w=Math.max(1,Math.floor(canvas.clientWidth*dpr)),h=Math.max(1,Math.floor(canvas.clientHeight*dpr));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h}gl?.viewport(0,0,w,h)}
const nodeMap=new Map((scene.nodes||[]).map(n=>[n.id,n])),normalLines=[],secretLines=[];
for(const r of scene.routes||[]){const a=nodeMap.get(r.start),b=nodeMap.get(r.end);if(a&&b)(r.kind==='secret'?secretLines:normalLines).push([a.x,a.y,a.z],[b.x,b.y,b.z])}
const overlays=gl?{normal:normalLines.length?{buffer:buffer(new Float32Array(normalLines.flat())),count:normalLines.length}:null,secret:secretLines.length?{buffer:buffer(new Float32Array(secretLines.flat())),count:secretLines.length}:null,nodes:scene.nodes?.length?{buffer:buffer(new Float32Array(scene.nodes.flatMap(n=>[n.x,n.y,n.z]))),count:scene.nodes.length}:null}:{normal:null,secret:null,nodes:null};
function drawOverlay(item,color,size,round){if(!item)return;gl.useProgram(overlayProgram);gl.bindBuffer(gl.ARRAY_BUFFER,item.buffer);gl.enableVertexAttribArray(loc(overlayProgram,'aPosition'));gl.vertexAttribPointer(loc(overlayProgram,'aPosition'),3,gl.FLOAT,false,0,0);gl.uniformMatrix4fv(gl.getUniformLocation(overlayProgram,'uMvp'),false,mvp);gl.uniform4fv(gl.getUniformLocation(overlayProgram,'uColor'),color);gl.uniform1f(gl.getUniformLocation(overlayProgram,'uPointSize'),size);gl.uniform1f(gl.getUniformLocation(overlayProgram,'uRound'),round);gl.drawArrays(round?gl.POINTS:gl.LINES,0,item.count)}
function project(point){const x=point[0],y=point[1],z=point[2],q=mvp;const cx=q[0]*x+q[4]*y+q[8]*z+q[12],cy=q[1]*x+q[5]*y+q[9]*z+q[13],cw=q[3]*x+q[7]*y+q[11]*z+q[15];if(cw<=0)return null;return[(cx/cw*.5+.5)*canvas.clientWidth,(.5-cy/cw*.5)*canvas.clientHeight]}
function frame(){if(!gl)return;resize();updateMatrices();gl.clearColor(.045,.075,.105,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);gl.disable(gl.CULL_FACE);gl.useProgram(meshProgram);gl.uniformMatrix4fv(gl.getUniformLocation(meshProgram,'uMvp'),false,mvp);gl.uniformMatrix3fv(gl.getUniformLocation(meshProgram,'uNormal'),false,normalMatrix);const pLoc=loc(meshProgram,'aPosition'),nLoc=loc(meshProgram,'aNormal'),uvLoc=loc(meshProgram,'aUv');gl.activeTexture(gl.TEXTURE0);gl.uniform1i(gl.getUniformLocation(meshProgram,'uTexture'),0);for(const m of meshes){if(!m.visible)continue;gl.bindBuffer(gl.ARRAY_BUFFER,m.pos);gl.enableVertexAttribArray(pLoc);gl.vertexAttribPointer(pLoc,3,gl.FLOAT,false,0,0);gl.bindBuffer(gl.ARRAY_BUFFER,m.normal);gl.enableVertexAttribArray(nLoc);gl.vertexAttribPointer(nLoc,3,gl.FLOAT,false,0,0);if(m.uv){gl.bindBuffer(gl.ARRAY_BUFFER,m.uv);gl.enableVertexAttribArray(uvLoc);gl.vertexAttribPointer(uvLoc,2,gl.FLOAT,false,0,0)}else{gl.disableVertexAttribArray(uvLoc);gl.vertexAttrib2f(uvLoc,0,0)}gl.bindTexture(gl.TEXTURE_2D,m.texture);gl.uniform1f(gl.getUniformLocation(meshProgram,'uHasTexture'),m.texture?1:0);gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,m.index);gl.uniform3fv(gl.getUniformLocation(meshProgram,'uColor'),m.color);gl.drawElements(gl.TRIANGLES,m.count,gl.UNSIGNED_SHORT,0)}
if(scene.showPaths!==false&&scene.nodes?.length){gl.disable(gl.DEPTH_TEST);drawOverlay(overlays.normal,[.98,.76,.31,1],2,0);drawOverlay(overlays.secret,[.75,.58,.92,1],2,0);drawOverlay(overlays.nodes,[.98,.86,.49,1],10,1);gl.enable(gl.DEPTH_TEST);const labels=document.getElementById('labels');labels.replaceChildren();for(const n of scene.nodes){const pos=project([n.x,n.y,n.z]);if(!pos||pos[0]<0||pos[0]>canvas.clientWidth||pos[1]<0||pos[1]>canvas.clientHeight)continue;const el=document.createElement('span');el.className='label';el.textContent=n.id;el.style.left=pos[0]+'px';el.style.top=pos[1]+'px';labels.appendChild(el)}}requestAnimationFrame(frame)}
canvas.addEventListener('pointerdown',e=>{canvas.setPointerCapture(e.pointerId);drag={x:e.clientX,y:e.clientY,button:e.button}});canvas.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(drag.button===2){const scale=distance*.0015;target[0]-=dx*scale;target[1]+=dy*scale}else{yaw-=dx*.008;pitch=Math.max(-1.35,Math.min(1.35,pitch+dy*.008))}drag.x=e.clientX;drag.y=e.clientY});canvas.addEventListener('pointerup',()=>drag=null);canvas.addEventListener('contextmenu',e=>e.preventDefault());canvas.addEventListener('wheel',e=>{e.preventDefault();distance=Math.max(sceneRadius*.2,Math.min(sceneRadius*16,distance*Math.exp(e.deltaY*.001)))},{passive:false});
document.getElementById('fit').addEventListener('click',()=>{target=[0,0,0];yaw=-.6;pitch=.65;distance=Math.max(20,sceneRadius*2.65)});
if(gl)requestAnimationFrame(frame);
</script>
</body></html>'''


def build_document(scene: dict) -> str:
    """Build an offline preview with escaped scene data and no remote scripts."""
    compact_scene = dict(scene)
    compact_shapes = []
    for original in scene.get("shapes", ()):
        shape = dict(original)
        for field, typecode in (("positions", "f"), ("normals", "f"), ("uvs", "f"), ("indices", "H")):
            if field not in shape:
                continue
            values = array(typecode)
            for item in shape[field]:
                if isinstance(item, (list, tuple)):
                    values.extend(item)
                else:
                    values.append(item)
            if values.itemsize != (4 if typecode == "f" else 2):
                raise ValueError(f"Platform array size is unsupported for {field}")
            if sys.byteorder != "little":
                values.byteswap()
            shape[f"{field}Packed"] = base64.b64encode(values.tobytes()).decode("ascii")
            if field == "indices":
                shape["indexCount"] = len(shape[field])
            del shape[field]
        compact_shapes.append(shape)
    compact_scene["shapes"] = compact_shapes
    payload = json.dumps(compact_scene, ensure_ascii=True, separators=(",", ":"))
    payload = payload.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return _PAGE.replace("__SCENE__", payload)


def open_preview(scene: dict) -> Path:
    """Write a local, non-repository preview page and open it in the browser."""
    destination = Path(tempfile.gettempdir()) / f"nsmbu-worldstudio-{uuid.uuid4().hex}.html"
    destination.write_text(build_document(scene), encoding="utf-8")
    if not webbrowser.open_new_tab(destination.as_uri()):
        raise OSError(f"Could not open browser for {destination}")
    return destination
