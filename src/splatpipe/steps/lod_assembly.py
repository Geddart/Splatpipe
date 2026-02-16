"""LOD assembly step: uses splat-transform to build LOD streaming format.

Takes reviewed PLY files from 04_review/ and produces PlayCanvas-ready
LOD streaming output (lod-meta.json + SOG chunk files + index.html viewer)
in 05_output/.

CLI syntax (splat-transform v1.7+):
  splat-transform lod0.ply -l 0 lod1.ply -l 1 ... --filter-nan output/lod-meta.json

Output structure (per chunk):
  {lod}_{chunk}/meta.json, means_l.webp, means_u.webp, quats.webp,
  scales.webp, sh0.webp, shN_centroids.webp, shN_labels.webp

splat-transform stderr progress:
  [1/8] Generating morton order
  [2/8] Writing positions
  ... (8 steps per chunk, 6 if no SH bands)
"""

import json
import math
import re
import shutil
import subprocess
import time
from pathlib import Path

from ..core.constants import FOLDER_REVIEW, FOLDER_OUTPUT
from ..core.events import ProgressEvent
from .base import PipelineStep

# Self-contained PlayCanvas engine viewer with LOD streaming.
# Ported from the proven SpeicherLindenau_01 viewer on CDN.
# Works on any origin: CDN, local HTTP server, etc.
_VIEWER_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{project_name} — Splatpipe Viewer</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ overflow: hidden; background: #1a1a1a;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
    canvas {{ width: 100vw; height: 100vh; display: block; }}
    #header {{
      position: absolute; top: 0; left: 0; right: 0; z-index: 10;
      display: flex; align-items: center; justify-content: space-between;
      padding: 12px 20px; pointer-events: none;
      background: linear-gradient(180deg, rgba(0,0,0,0.7) 0%, rgba(0,0,0,0) 100%);
    }}
    #header > * {{ pointer-events: auto; }}
    #title {{ color: #fff; }}
    #title h1 {{ font-size: 18px; font-weight: 600; }}
    #title p {{ font-size: 12px; color: #aaa; margin-top: 2px; }}
    #quality-buttons {{ display: flex; gap: 6px; align-items: center; }}
    .quality-btn {{
      padding: 8px 16px; border: 1px solid rgba(255,255,255,0.3);
      border-radius: 6px; background: rgba(0,0,0,0.5); color: #ccc;
      font-size: 14px; font-weight: 500; cursor: pointer; transition: all 0.2s;
    }}
    .quality-btn:hover {{ background: rgba(255,255,255,0.15); color: #fff; }}
    .quality-btn.active {{
      background: rgba(255,255,255,0.25); color: #fff;
      border-color: rgba(255,255,255,0.6); font-weight: 700;
    }}
    #stats {{
      position: absolute; bottom: 0; left: 0; right: 0; z-index: 10;
      text-align: center; padding: 16px; pointer-events: none;
      background: linear-gradient(0deg, rgba(0,0,0,0.7) 0%, rgba(0,0,0,0) 100%);
    }}
    #splat-count {{
      font-size: 28px; font-weight: 300; color: #fff;
      text-shadow: 0 2px 8px rgba(0,0,0,0.8);
    }}
    #debug-panel {{
      position: absolute; top: 60px; right: 20px; z-index: 10;
      background: rgba(0,0,0,0.6); border-radius: 8px;
      padding: 10px 14px; color: #ccc; font-size: 12px;
    }}
    #debug-panel label {{
      display: flex; align-items: center; gap: 6px; cursor: pointer; margin: 4px 0;
    }}
    #debug-panel input[type="checkbox"] {{ cursor: pointer; }}
    #loading {{
      position: absolute; inset: 0; z-index: 100;
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      background: #1a1a1a; transition: opacity 0.5s;
    }}
    #loading.hidden {{ opacity: 0; pointer-events: none; }}
    #loading p {{ color: #aaa; font-size: 16px; margin-top: 16px; }}
    .spinner {{
      width: 40px; height: 40px;
      border: 3px solid rgba(255,255,255,0.1); border-top-color: #fff;
      border-radius: 50%; animation: spin 1s linear infinite;
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    #controls-hint {{
      position: absolute; bottom: 60px; left: 20px; z-index: 10;
      color: rgba(255,255,255,0.4); font-size: 11px; pointer-events: none;
    }}
    #lod-sliders input[type="range"] {{ cursor: pointer; }}
    #annotation-markers {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 15; }}
    .ann-marker {{ position: absolute; transform: translate(-50%, -100%); pointer-events: auto; cursor: pointer; transition: opacity 0.2s; }}
    .ann-dot {{
      width: 28px; height: 28px; border-radius: 50%; background: #ff6b35; color: white;
      display: flex; align-items: center; justify-content: center; font-size: 13px;
      font-weight: 700; border: 2px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.5);
    }}
    .ann-tooltip {{
      display: none; position: absolute; bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%);
      background: rgba(0,0,0,0.9); color: white; padding: 8px 12px; border-radius: 8px;
      white-space: nowrap; font-size: 12px; line-height: 1.4; max-width: 200px; pointer-events: none;
    }}
    .ann-tooltip h4 {{ font-weight: 600; margin: 0 0 2px; }}
    .ann-tooltip p {{ margin: 0; opacity: 0.8; white-space: normal; }}
    .ann-marker:hover .ann-tooltip {{ display: block; }}
  </style>
</head>
<body>
  <canvas id="app-canvas"></canvas>

  <div id="header">
    <div id="title">
      <h1>{project_name}</h1>
      <p>Splatpipe Viewer</p>
    </div>
    <div id="quality-buttons">
      <button class="quality-btn" data-preset="low">Low</button>
      <button class="quality-btn" data-preset="medium">Medium</button>
      <button class="quality-btn" data-preset="high">High</button>
      <button class="quality-btn" data-preset="ultra">Ultra</button>
      <button class="quality-btn" data-preset="custom">Custom</button>
      <select id="splat-budget" class="quality-btn" style="appearance:auto">
        <option value="0">No limit</option>
        <option value="1000000">1M</option>
        <option value="2000000">2M</option>
        <option value="3000000">3M</option>
        <option value="4000000">4M</option>
        <option value="6000000">6M</option>
      </select>
    </div>
  </div>

  <div id="lod-sliders" style="display:none; position:absolute; top:60px; left:20px; z-index:10;
       background:rgba(0,0,0,0.8); border-radius:8px; padding:12px 16px; color:#ccc; font-size:12px;">
    <div style="font-weight:600; margin-bottom:8px;">LOD Distances</div>
  </div>

  <div id="debug-panel">
    <label><input type="checkbox" id="debug-lod"> Colorize LOD</label>
    <label><input type="checkbox" id="debug-sh"> Colorize SH updates</label>
  </div>

  <div id="stats">
    <div id="splat-count">Splats: 0.00M</div>
  </div>

  <div id="controls-hint">
    WASD / Arrow keys to move &middot; Mouse drag to look &middot; Scroll to zoom &middot; Shift for fast
  </div>

  <div id="loading">
    <div class="spinner"></div>
    <p>Loading splats...</p>
  </div>

  <div id="annotation-markers"></div>

  <script type="importmap">
  {{
    "imports": {{
      "playcanvas": "https://cdn.jsdelivr.net/npm/playcanvas@2.16/+esm"
    }}
  }}
  </script>
  <script type="module">
  import * as pc from 'playcanvas';

  const CAMERA_CONTROLS_URL =
    'https://cdn.jsdelivr.net/npm/playcanvas/scripts/esm/camera-controls.mjs';
  const {{ CameraControls }} = await import(CAMERA_CONTROLS_URL);

  const canvas = document.getElementById('app-canvas');
  window.focus();

  const SPLAT_URL = 'lod-meta.json';
  const PROJECT_NAME = '{project_name}';

  // LOD distances baked from project config
  const lodDistances = {lod_distances_json};
  const numLods = lodDistances.length;

  // Build LOD presets from project distances
  const LOD_PRESETS = {{
    ultra: {{ range: [0, Math.min(numLods - 1, Math.floor(numLods * 0.7))],
              lodDistances: lodDistances }},
    high:  {{ range: [0, numLods - 1],
              lodDistances: lodDistances }},
    medium: {{ range: [Math.min(1, numLods - 1), numLods - 1],
               lodDistances: lodDistances }},
    low:    {{ range: [Math.max(0, numLods - 2), numLods - 1],
               lodDistances: lodDistances }}
  }};

  const gfxOptions = {{ deviceTypes: ['webgpu', 'webgl2'], antialias: false }};
  const device = await pc.createGraphicsDevice(canvas, gfxOptions);
  const createOptions = new pc.AppOptions();
  createOptions.graphicsDevice = device;
  createOptions.mouse = new pc.Mouse(document.body);
  createOptions.touch = new pc.TouchDevice(document.body);
  createOptions.keyboard = new pc.Keyboard(document.body);
  createOptions.componentSystems = [
    pc.RenderComponentSystem, pc.CameraComponentSystem,
    pc.LightComponentSystem, pc.ScriptComponentSystem,
    pc.GSplatComponentSystem,
    pc.SoundComponentSystem, pc.AudioListenerComponentSystem
  ];
  createOptions.resourceHandlers = [
    pc.TextureHandler, pc.ContainerHandler,
    pc.ScriptHandler, pc.GSplatHandler, pc.AudioHandler
  ];

  const app = new pc.AppBase(canvas);
  app.init(createOptions);
  app.setCanvasFillMode(pc.FILLMODE_FILL_WINDOW);
  app.setCanvasResolution(pc.RESOLUTION_AUTO);

  const dpr = window.devicePixelRatio || 1;
  device.maxPixelRatio = dpr >= 2 ? dpr * 0.5 : dpr;

  const onResize = () => app.resizeCanvas();
  window.addEventListener('resize', onResize);
  app.on('destroy', () => window.removeEventListener('resize', onResize));

  const splatAsset = new pc.Asset('gsplat', 'gsplat', {{ url: SPLAT_URL }});
  app.assets.add(splatAsset);
  await new Promise((resolve, reject) => {{
    splatAsset.on('load', resolve);
    splatAsset.on('error', err => reject(new Error(err)));
    app.assets.load(splatAsset);
  }});

  // --- Load viewer config ---
  const _DEFAULTS = {{
    camera: {{ pitch_min: -89, pitch_max: 89, zoom_min: 1, zoom_max: 200,
              ground_height: 0.3, bounds_radius: 150 }},
    splat_budget: 0,
    annotations: [],
    background: {{ type: 'color', color: '#1a1a1a' }},
    postprocessing: {{ tonemapping: 'neutral', exposure: 1.5,
                      bloom: false, vignette: false }},
    audio: []
  }};
  let viewerConfig = _DEFAULTS;
  try {{
    const cfgResp = await fetch('viewer-config.json');
    if (cfgResp.ok) viewerConfig = {{ ..._DEFAULTS, ...await cfgResp.json() }};
  }} catch (e) {{ /* use defaults */ }}

  app.start();

  // --- Apply post-processing from config ---
  const pp = viewerConfig.postprocessing || _DEFAULTS.postprocessing;
  app.scene.exposure = pp.exposure ?? 1.5;

  const TONEMAP = {{
    linear: pc.TONEMAP_LINEAR, neutral: pc.TONEMAP_NEUTRAL,
    aces: pc.TONEMAP_ACES, aces2: pc.TONEMAP_ACES2, filmic: pc.TONEMAP_FILMIC
  }};

  app.scene.gsplat.lodUpdateAngle = 90;
  app.scene.gsplat.lodBehindPenalty = 2;
  app.scene.gsplat.radialSorting = true;
  app.scene.gsplat.lodUpdateDistance = 1;
  app.scene.gsplat.lodUnderfillLimit = 10;
  app.scene.gsplat.colorUpdateDistance = 1;
  app.scene.gsplat.colorUpdateAngle = 4;
  app.scene.gsplat.colorUpdateDistanceLodScale = 2;
  app.scene.gsplat.colorUpdateAngleLodScale = 2;

  const splatEntity = new pc.Entity(PROJECT_NAME);
  splatEntity.addComponent('gsplat', {{ asset: splatAsset, unified: true }});
  splatEntity.setLocalEulerAngles(180, 0, 0);
  app.root.addChild(splatEntity);
  const gs = splatEntity.gsplat;

  const focusPoint = new pc.Vec3(0, 1, 0);
  const camera = new pc.Entity('camera');
  camera.addComponent('camera', {{
    clearColor: new pc.Color(0.15, 0.15, 0.15),
    fov: 75,
    toneMapping: TONEMAP[pp.tonemapping] ?? pc.TONEMAP_NEUTRAL
  }});

  // --- Apply background from config ---
  const bg = viewerConfig.background || _DEFAULTS.background;
  if (bg.type === 'color' && bg.color) {{
    camera.camera.clearColor = new pc.Color().fromString(bg.color);
    document.body.style.background = bg.color;
  }}

  camera.setLocalPosition(0, 2, -10);
  app.root.addChild(camera);
  camera.addComponent('script');
  camera.addComponent('audiolistener');
  const cc = camera.script.create(CameraControls);
  Object.assign(cc, {{
    sceneSize: 500,
    moveSpeed: 4,
    moveFastSpeed: 15,
    enableOrbit: true,
    enablePan: true,
    focusPoint: focusPoint
  }});

  // --- Apply camera constraints from config ---
  const cam = viewerConfig.camera || _DEFAULTS.camera;
  cc.pitchRange = new pc.Vec2(cam.pitch_min, cam.pitch_max);
  cc.zoomRange = new pc.Vec2(cam.zoom_min, cam.zoom_max);

  // Quality preset buttons
  const buttons = document.querySelectorAll('.quality-btn');
  const isMobile = pc.platform.mobile;
  let currentPreset = isMobile ? 'medium' : 'high';

  // --- Custom LOD distance sliders ---
  // Colors match PlayCanvas engine's colorizeLod exactly (gsplat-manager.js _lodColorsRaw)
  const LOD_COLORS = [
    'rgb(255,0,0)', 'rgb(0,255,0)', 'rgb(0,0,255)', 'rgb(255,255,0)',
    'rgb(255,0,255)', 'rgb(0,255,255)', 'rgb(255,128,0)', 'rgb(128,0,255)'
  ];
  const LOD_NAMES = ['Highest', 'High', 'Medium', 'Low', 'Lower', 'Lowest', 'Min', 'Tiny'];
  const sliderPanel = document.getElementById('lod-sliders');
  const customDistances = [...lodDistances];

  for (let i = 0; i < numLods; i++) {{
    const color = LOD_COLORS[i % LOD_COLORS.length];
    const row = document.createElement('div');
    row.style.cssText = 'display:flex; align-items:center; gap:8px; margin:4px 0;';
    const dot = document.createElement('span');
    dot.style.cssText = 'width:8px; height:8px; border-radius:50%; flex-shrink:0; background:' + color;
    const label = document.createElement('span');
    label.textContent = (LOD_NAMES[i] || 'LOD ' + i);
    label.style.cssText = 'width:52px; font-size:11px; color:' + color + '; font-weight:600;';
    const slider = document.createElement('input');
    slider.type = 'range'; slider.min = '1'; slider.max = '300';
    slider.value = String(lodDistances[i]);
    slider.style.cssText = 'flex:1; height:4px; accent-color:' + color + ';';
    const val = document.createElement('span');
    val.textContent = lodDistances[i] + 'm';
    val.style.cssText = 'width:44px; text-align:right; font-size:11px; font-family:monospace; color:' + color + ';';
    slider.addEventListener('input', () => {{
      customDistances[i] = parseInt(slider.value);
      val.textContent = slider.value + 'm';
      gs.lodDistances = customDistances;
    }});
    row.append(dot, label, slider, val);
    sliderPanel.appendChild(row);
  }}

  function applyPreset(name) {{
    currentPreset = name;
    if (name === 'custom') {{
      sliderPanel.style.display = 'block';
      app.scene.gsplat.lodRangeMin = 0;
      app.scene.gsplat.lodRangeMax = numLods - 1;
      gs.lodDistances = customDistances;
    }} else {{
      const preset = LOD_PRESETS[name];
      if (!preset) return;
      sliderPanel.style.display = 'none';
      app.scene.gsplat.lodRangeMin = preset.range[0];
      app.scene.gsplat.lodRangeMax = preset.range[1];
      gs.lodDistances = preset.lodDistances;
    }}
    buttons.forEach(btn => {{
      btn.classList.toggle('active', btn.dataset.preset === name);
    }});
  }}

  buttons.forEach(btn => {{
    btn.addEventListener('click', () => applyPreset(btn.dataset.preset));
  }});
  applyPreset(currentPreset);

  // --- Splat budget from config ---
  const budgetEl = document.getElementById('splat-budget');
  const cfgBudget = viewerConfig.splat_budget || 0;
  if (cfgBudget > 0) {{
    if (!budgetEl.querySelector('option[value="' + cfgBudget + '"]')) {{
      const opt = document.createElement('option');
      opt.value = String(cfgBudget);
      opt.textContent = (cfgBudget / 1_000_000).toFixed(1) + 'M';
      budgetEl.appendChild(opt);
    }}
    budgetEl.value = String(cfgBudget);
  }} else {{
    budgetEl.value = isMobile ? '1000000' : '4000000';
  }}
  app.scene.gsplat.splatBudget = parseInt(budgetEl.value);
  budgetEl.addEventListener('change', () => {{
    app.scene.gsplat.splatBudget = parseInt(budgetEl.value);
  }});

  // Debug visualization checkboxes
  document.getElementById('debug-lod').addEventListener('change', e => {{
    app.scene.gsplat.colorizeLod = e.target.checked;
  }});
  document.getElementById('debug-sh').addEventListener('change', e => {{
    app.scene.gsplat.colorizeColorUpdate = e.target.checked;
  }});

  document.getElementById('loading').classList.add('hidden');

  // --- Annotation markers ---
  const annotationsData = viewerConfig.annotations || [];
  const markersContainer = document.getElementById('annotation-markers');
  const markerEls = [];
  annotationsData.forEach((ann, i) => {{
    const marker = document.createElement('div');
    marker.className = 'ann-marker';
    const label = (ann.label || String(i + 1)).replace(/</g, '&lt;');
    const title = (ann.title || '').replace(/</g, '&lt;');
    const text = (ann.text || '').replace(/</g, '&lt;');
    marker.innerHTML = '<div class="ann-dot">' + label + '</div><div class="ann-tooltip">' +
      (title ? '<h4>' + title + '</h4>' : '') + (text ? '<p>' + text + '</p>' : '') + '</div>';
    markersContainer.appendChild(marker);
    markerEls.push({{ el: marker, pos: new pc.Vec3(ann.pos[0], ann.pos[1], ann.pos[2]) }});
  }});

  // Live splat count + camera constraints + annotation markers
  const splatCountEl = document.getElementById('splat-count');
  app.on('update', () => {{
    const displayed = app.stats.frame.gsplats || 0;
    const displayedM = (displayed / 1_000_000).toFixed(2);
    splatCountEl.textContent = 'Splats: ' + displayedM + 'M';
    // Clamp camera position: ground + bounds
    const pos = camera.getLocalPosition();
    const cx = pc.math.clamp(pos.x, -cam.bounds_radius, cam.bounds_radius);
    const cy = Math.max(pos.y, cam.ground_height);
    const cz = pc.math.clamp(pos.z, -cam.bounds_radius, cam.bounds_radius);
    if (cx !== pos.x || cy !== pos.y || cz !== pos.z) {{
      camera.setLocalPosition(cx, cy, cz);
    }}
    // Update annotation marker screen positions
    const _sp = new pc.Vec3();
    markerEls.forEach(m => {{
      camera.camera.worldToScreen(m.pos, _sp);
      const _tp = new pc.Vec3().sub2(m.pos, camera.getPosition());
      if (_tp.dot(camera.forward) < 0) {{
        m.el.style.display = 'none';
      }} else {{
        m.el.style.display = '';
        m.el.style.left = _sp.x + 'px';
        m.el.style.top = _sp.y + 'px';
      }}
    }});
  }});

  // --- Audio sources from config ---
  (viewerConfig.audio || []).forEach(src => {{
    const audioAsset = new pc.Asset('audio', 'audio', {{ url: src.file }});
    app.assets.add(audioAsset);
    app.assets.load(audioAsset);
    audioAsset.on('load', () => {{
      const ent = new pc.Entity('audio-source');
      ent.addComponent('sound', {{
        positional: src.positional ?? false,
        volume: src.volume ?? 0.5,
        refDistance: 5, maxDistance: 100
      }});
      ent.sound.addSlot('main', {{ asset: audioAsset, loop: src.loop ?? true, autoPlay: true }});
      if (src.pos) ent.setLocalPosition(src.pos[0], src.pos[1], src.pos[2]);
      app.root.addChild(ent);
      ent.sound.play('main');
    }});
  }});
  </script>
</body>
</html>
"""


def _write_viewer_html(
    output_dir: Path, project_name: str, lod_distances: list[float]
) -> None:
    """Generate index.html PlayCanvas viewer alongside lod-meta.json."""
    html = _VIEWER_TEMPLATE.format(
        project_name=project_name,
        lod_distances_json=json.dumps(lod_distances),
    )
    (output_dir / "index.html").write_text(html, encoding="utf-8")


def _write_viewer_config(output_dir: Path, scene_config: dict) -> None:
    """Write viewer-config.json alongside lod-meta.json."""
    (output_dir / "viewer-config.json").write_text(
        json.dumps(scene_config, indent=2), encoding="utf-8"
    )


def _copy_project_assets(project_root: Path, output_dir: Path) -> None:
    """Copy project assets/ folder to output if it exists."""
    assets_src = project_root / "assets"
    assets_dst = output_dir / "assets"
    if assets_src.is_dir():
        if assets_dst.exists():
            shutil.rmtree(assets_dst)
        shutil.copytree(assets_src, assets_dst)


# splat-transform defaults: --lod-chunk-count 512 -> binSize = 512 * 1024
_DEFAULT_BIN_SIZE = 512 * 1024  # 524,288 splats per output chunk
_FILES_PER_CHUNK = 8  # 7 webp + 1 meta.json


def _count_ply_vertices(ply_path: Path) -> int:
    """Read vertex count from PLY header without loading the full file."""
    with open(ply_path, "rb") as f:
        for raw in f:
            line = raw.decode("ascii", errors="replace").strip()
            if line.startswith("element vertex"):
                return int(line.split()[-1])
            if line == "end_header":
                break
    return 0


def _estimate_total_chunks(reviewed_plys: list[dict]) -> int:
    """Estimate total output chunks from PLY vertex counts."""
    total = 0
    for ply_info in reviewed_plys:
        verts = _count_ply_vertices(Path(ply_info["ply_path"]))
        total += math.ceil(verts / _DEFAULT_BIN_SIZE) if verts > 0 else 1
    return total


class LodAssemblyStep(PipelineStep):
    step_name = "assemble"
    output_folder = FOLDER_OUTPUT

    def run(self, output_dir: Path) -> dict:
        review_dir = self.project.get_folder(FOLDER_REVIEW)
        lod_levels = self.project.lod_levels

        # Find reviewed PLY files — use sequential lod_index for splat-transform
        # (passing -l 2 -l 3 -l 5 creates 6 LOD levels with empty gaps at 0,1,4)
        reviewed_plys = []
        for i, lod in enumerate(lod_levels):
            lod_name = lod["name"]
            ply_name = f"lod{i}_reviewed.ply"
            ply_path = review_dir / ply_name
            if ply_path.exists():
                reviewed_plys.append({
                    "lod_index": len(reviewed_plys),
                    "lod_name": lod_name,
                    "ply_path": str(ply_path),
                    "stats": self.file_stats(ply_path),
                })

        if not reviewed_plys:
            raise FileNotFoundError(
                f"No reviewed PLY files found in {review_dir}. "
                f"Expected files like lod0_reviewed.ply, lod1_reviewed.ply, etc."
            )

        result = {"input_plys": reviewed_plys}

        # Run splat-transform to generate LOD streaming format
        lod_meta_result = self._build_lod_streaming(output_dir, reviewed_plys)
        result["lod_streaming"] = lod_meta_result

        # Check output files (chunks are in subdirectories: {lod}_{idx}/*.webp)
        lod_meta_path = output_dir / "lod-meta.json"
        chunk_files = sorted(output_dir.rglob("*.webp"))
        chunk_dirs = [d for d in output_dir.iterdir() if d.is_dir()]
        result["output"] = {
            "lod_meta": self.file_stats(lod_meta_path),
            "chunk_files": [self.file_stats(f) for f in chunk_files],
        }

        result["summary"] = {
            "lod_count": len(reviewed_plys),
            "lod_meta_generated": lod_meta_path.exists(),
            "chunk_count": len(chunk_dirs),
            "file_count": len(chunk_files),
            "success": lod_meta_result.get("returncode") == 0,
        }

        # Generate viewer HTML + config if assembly succeeded
        if lod_meta_result.get("returncode") == 0:
            distances = self.project.lod_distances[:len(reviewed_plys)]
            _write_viewer_html(output_dir, self.project.name, distances)
            _write_viewer_config(output_dir, self.project.scene_config)
            _copy_project_assets(self.project.root, output_dir)

        return result

    def run_streaming(self, output_dir: Path):
        """Generator yielding ProgressEvent during assembly, returns result dict.

        Reads splat-transform stderr line-by-line for per-chunk step progress
        ([1/8] Writing positions, etc.) and counts output files recursively.
        Estimates total chunks from PLY vertex counts for percentage progress.
        Result is returned via StopIteration.value (use _next_or_sentinel).
        """
        review_dir = self.project.get_folder(FOLDER_REVIEW)
        lod_levels = self.project.lod_levels

        # Find reviewed PLY files — use sequential lod_index for splat-transform
        reviewed_plys = []
        for i, lod in enumerate(lod_levels):
            lod_name = lod["name"]
            ply_name = f"lod{i}_reviewed.ply"
            ply_path = review_dir / ply_name
            if ply_path.exists():
                reviewed_plys.append({
                    "lod_index": len(reviewed_plys),
                    "lod_name": lod_name,
                    "ply_path": str(ply_path),
                    "stats": self.file_stats(ply_path),
                })

        if not reviewed_plys:
            raise FileNotFoundError(
                f"No reviewed PLY files found in {review_dir}. "
                f"Expected files like lod0_reviewed.ply, lod1_reviewed.ply, etc."
            )

        # Estimate total chunks from PLY vertex counts
        est_chunks = _estimate_total_chunks(reviewed_plys)
        est_total_files = est_chunks * _FILES_PER_CHUNK + 1  # +1 for lod-meta.json

        # Build command
        input_args = []
        for ply_info in reviewed_plys:
            input_args.extend([
                ply_info["ply_path"],
                "-l", str(ply_info["lod_index"]),
            ])

        lod_meta_path = output_dir / "lod-meta.json"
        splat_transform_mjs = (
            Path("node_modules/@playcanvas/splat-transform/bin/cli.mjs").resolve()
        )
        assemble_settings = self.project.step_settings.get("assemble", {})
        sh_bands = int(assemble_settings.get("sh_bands", 3))
        cmd = [
            "node", "--max-old-space-size=32000",
            str(splat_transform_mjs),
        ] + input_args + [
            "--filter-nan",
            "--filter-harmonics", str(sh_bands),
            str(lod_meta_path),
        ]

        # Clear old output completely (subdirs + root files)
        for item in list(output_dir.iterdir()):
            if item.is_dir():
                shutil.rmtree(item)
            elif item.is_file():
                item.unlink()

        t0 = time.time()
        # Read stderr line-by-line for per-chunk step progress
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        stderr_lines = []
        step_re = re.compile(r"\[(\d+)/(\d+)\]\s*(.*)")
        chunks_done = 0
        last_step_msg = ""

        import threading
        import queue

        stderr_q: queue.Queue[str | None] = queue.Queue()

        def _read_stderr():
            assert proc.stderr is not None
            for raw in proc.stderr:
                line = raw.decode("utf-8", errors="replace").rstrip()
                stderr_q.put(line)
            stderr_q.put(None)  # sentinel

        reader = threading.Thread(target=_read_stderr, daemon=True)
        reader.start()

        while True:
            # Drain all available stderr lines
            while True:
                try:
                    line = stderr_q.get_nowait()
                except queue.Empty:
                    break
                if line is None:
                    break
                stderr_lines.append(line)
                m = step_re.match(line)
                if m:
                    step_num, total_steps, step_name = m.group(1), m.group(2), m.group(3)
                    last_step_msg = f"[{step_num}/{total_steps}] {step_name}"
                    if step_num == total_steps:
                        chunks_done += 1
                elif "done" in line:
                    pass  # final completion marker

            # Count actual files recursively
            file_count = sum(1 for _ in output_dir.rglob("*") if _.is_file())
            elapsed = time.time() - t0

            # Progress: use chunks_done / est_chunks for percentage
            pct = min(chunks_done / est_chunks, 0.99) if est_chunks > 0 else 0

            yield ProgressEvent(
                step="assemble",
                progress=pct,
                sub_progress=file_count,
                message=last_step_msg or "Starting...",
                detail=f"{file_count}/~{est_total_files} files | "
                       f"{chunks_done}/~{est_chunks} chunks | "
                       f"{elapsed:.0f}s",
            )

            if proc.poll() is not None:
                break
            time.sleep(0.5)

        reader.join(timeout=5)
        duration = time.time() - t0
        stdout = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
        stderr_full = "\n".join(stderr_lines)

        chunk_files = sorted(output_dir.rglob("*.webp"))
        chunk_dirs = [d for d in output_dir.iterdir() if d.is_dir()]

        # Generate viewer HTML + config if assembly succeeded
        if proc.returncode == 0:
            distances = self.project.lod_distances[:len(reviewed_plys)]
            _write_viewer_html(output_dir, self.project.name, distances)
            _write_viewer_config(output_dir, self.project.scene_config)
            _copy_project_assets(self.project.root, output_dir)

        result = {
            "input_plys": reviewed_plys,
            "lod_streaming": {
                "command": cmd,
                "returncode": proc.returncode,
                "stdout": stdout,
                "stderr": stderr_full,
                "duration_s": round(duration, 2),
            },
            "output": {
                "lod_meta": self.file_stats(lod_meta_path),
                "chunk_files": [self.file_stats(f) for f in chunk_files],
            },
            "summary": {
                "lod_count": len(reviewed_plys),
                "lod_meta_generated": lod_meta_path.exists(),
                "chunk_count": len(chunk_dirs),
                "file_count": len(chunk_files),
                "success": proc.returncode == 0,
            },
        }
        return result

    def _build_lod_streaming(self, output_dir: Path, reviewed_plys: list[dict]) -> dict:
        """Run splat-transform to generate lod-meta.json + SOG chunks."""
        # Build interleaved input args: file.ply -l N file.ply -l N ...
        input_args = []
        for ply_info in reviewed_plys:
            input_args.extend([
                ply_info["ply_path"],
                "-l", str(ply_info["lod_index"]),
            ])

        lod_meta_path = output_dir / "lod-meta.json"

        # Use node with extra memory for large splat files
        splat_transform_mjs = (
            Path("node_modules/@playcanvas/splat-transform/bin/cli.mjs").resolve()
        )
        assemble_settings = self.project.step_settings.get("assemble", {})
        sh_bands = int(assemble_settings.get("sh_bands", 3))
        cmd = [
            "node", "--max-old-space-size=32000",
            str(splat_transform_mjs),
        ] + input_args + [
            "--filter-nan",
            "--filter-harmonics", str(sh_bands),
            str(lod_meta_path),
        ]

        t0 = time.time()
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=3600,
        )
        duration = time.time() - t0

        return {
            "command": cmd,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "duration_s": round(duration, 2),
        }
