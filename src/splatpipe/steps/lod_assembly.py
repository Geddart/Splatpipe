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
    pc.GSplatComponentSystem
  ];
  createOptions.resourceHandlers = [
    pc.TextureHandler, pc.ContainerHandler,
    pc.ScriptHandler, pc.GSplatHandler
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

  app.start();

  app.scene.exposure = 1.5;
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
    toneMapping: pc.TONEMAP_LINEAR
  }});
  camera.setLocalPosition(0, 2, -10);
  app.root.addChild(camera);
  camera.addComponent('script');
  const cc = camera.script.create(CameraControls);
  Object.assign(cc, {{
    sceneSize: 500,
    moveSpeed: 4,
    moveFastSpeed: 15,
    enableOrbit: true,
    enablePan: true,
    focusPoint: focusPoint
  }});

  // Quality preset buttons
  const buttons = document.querySelectorAll('.quality-btn');
  const isMobile = pc.platform.mobile;
  let currentPreset = isMobile ? 'medium' : 'high';

  function applyPreset(name) {{
    const preset = LOD_PRESETS[name];
    if (!preset) return;
    currentPreset = name;
    app.scene.gsplat.lodRangeMin = preset.range[0];
    app.scene.gsplat.lodRangeMax = preset.range[1];
    gs.lodDistances = preset.lodDistances;
    buttons.forEach(btn => {{
      btn.classList.toggle('active', btn.dataset.preset === name);
    }});
  }}

  buttons.forEach(btn => {{
    btn.addEventListener('click', () => applyPreset(btn.dataset.preset));
  }});
  applyPreset(currentPreset);

  // Splat budget control
  const budgetEl = document.getElementById('splat-budget');
  budgetEl.value = isMobile ? '1000000' : '4000000';
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

  // Live splat count
  const splatCountEl = document.getElementById('splat-count');
  app.on('update', () => {{
    const displayed = app.stats.frame.gsplats || 0;
    const displayedM = (displayed / 1_000_000).toFixed(2);
    splatCountEl.textContent = 'Splats: ' + displayedM + 'M';
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

        # Generate viewer HTML if assembly succeeded
        if lod_meta_result.get("returncode") == 0:
            distances = self.project.lod_distances[:len(reviewed_plys)]
            _write_viewer_html(output_dir, self.project.name, distances)

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

        # Generate viewer HTML if assembly succeeded
        if proc.returncode == 0:
            distances = self.project.lod_distances[:len(reviewed_plys)]
            _write_viewer_html(output_dir, self.project.name, distances)

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
