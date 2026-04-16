"""Spark 2 viewer template — emits a self-contained index.html.

Loads a single ``scene.rad`` (from Spark's Rust build-lod) via
``new SplatMesh({url, paged: true})`` for HTTP-Range streaming.
Falls back to ``scene.sog`` if configured. Mirrors the PlayCanvas viewer's
feature set: annotations (CSS2DObject), camera-path HUD, foveation,
conditional audio + camera bounds, tone mapping.

Pinned versions (bump in lockstep):
  - @sparkjsdev/spark 2.0.0   (released)
  - three 0.180.0             (peer dep of @sparkjsdev/spark 2.0.0)
"""

from __future__ import annotations

import json
from pathlib import Path


SPARK_VERSION = "2.0.0"
THREE_VERSION = "0.180.0"


def html_for(project_name: str, *, primary_asset: str = "scene.rad", paged: bool = True) -> str:
    """Render the Spark viewer HTML for a given project.

    `primary_asset` is the filename the SplatMesh loads (relative to index.html).
    `paged=True` enables HTTP-Range streaming for `.rad`; should be False for `.sog`.
    """
    return _VIEWER_TEMPLATE.format(
        project_name=project_name,
        spark_version=SPARK_VERSION,
        three_version=THREE_VERSION,
        primary_asset=primary_asset,
        paged_json=json.dumps(bool(paged)),
    )


_VIEWER_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{project_name} — Splatpipe Viewer (Spark)</title>
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

    #stats {{
      position: absolute; bottom: 0; left: 0; right: 0; z-index: 10;
      text-align: center; padding: 16px; pointer-events: none;
      background: linear-gradient(0deg, rgba(0,0,0,0.7) 0%, rgba(0,0,0,0) 100%);
    }}
    #splat-count {{
      font-size: 28px; font-weight: 300; color: #fff;
      text-shadow: 0 2px 8px rgba(0,0,0,0.8);
    }}

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

    #css2d-root {{
      position: absolute; top: 0; left: 0; width: 100%; height: 100%;
      pointer-events: none; z-index: 15;
    }}
    .ann-marker {{ position: absolute; transform: translate(-50%, -100%); pointer-events: auto; cursor: pointer; }}
    .ann-dot {{
      width: 28px; height: 28px; border-radius: 50%; background: #ff6b35; color: white;
      display: flex; align-items: center; justify-content: center; font-size: 13px;
      font-weight: 700; border: 2px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.5);
    }}
    .ann-dot.path-active {{
      background: #ff3300; box-shadow: 0 0 14px rgba(255,80,30,0.9);
      transform: scale(1.15); transition: all 0.2s;
    }}
    .ann-tooltip {{
      display: none; position: absolute; bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%);
      background: rgba(0,0,0,0.9); color: white; padding: 8px 12px; border-radius: 8px;
      white-space: nowrap; font-size: 12px; line-height: 1.4; max-width: 200px; pointer-events: none;
    }}
    .ann-tooltip h4 {{ font-weight: 600; margin: 0 0 2px; }}
    .ann-tooltip p {{ margin: 0; opacity: 0.8; white-space: normal; }}
    .ann-marker:hover .ann-tooltip {{ display: block; }}

    #path-hud {{
      position: absolute; bottom: 60px; left: 50%; transform: translateX(-50%);
      z-index: 12; display: none; align-items: center; gap: 10px;
      background: rgba(0,0,0,0.75); border-radius: 8px; padding: 8px 14px;
      color: #ccc; font-size: 12px; pointer-events: auto;
    }}
    #path-hud.active {{ display: flex; }}
    #path-hud select {{
      background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.2);
      color: #ccc; border-radius: 4px; padding: 4px 6px; font-size: 12px;
    }}
    #path-hud button {{
      background: rgba(255,100,50,0.3); border: 1px solid rgba(255,100,50,0.5);
      color: #fff; border-radius: 4px; padding: 4px 10px; font-size: 12px; cursor: pointer;
    }}
    #path-hud button:hover {{ background: rgba(255,100,50,0.5); }}
    #path-hud .scrub {{ width: 200px; }}
    #path-hud .time {{ font-family: monospace; min-width: 60px; text-align: center; }}
  </style>
</head>
<body>
  <canvas id="app-canvas"></canvas>

  <div id="header">
    <div id="title">
      <h1>{project_name}</h1>
      <p>Splatpipe Viewer · Spark 2</p>
    </div>
  </div>

  <div id="stats">
    <div id="splat-count">Loading…</div>
  </div>

  <div id="controls-hint">
    Left-drag to orbit · Right-drag to pan · Scroll to zoom
  </div>

  <div id="loading">
    <div class="spinner"></div>
    <p>Loading splats…</p>
  </div>

  <div id="css2d-root"></div>

  <div id="path-hud">
    <select id="path-select"></select>
    <button id="path-play">▶ Play</button>
    <button id="path-stop">⏹</button>
    <input type="range" class="scrub" id="path-scrub" min="0" max="1000" value="0">
    <span class="time" id="path-time">0.00s</span>
  </div>

  <script type="importmap">
  {{
    "imports": {{
      "three": "https://cdn.jsdelivr.net/npm/three@{three_version}/build/three.module.js",
      "three/addons/": "https://cdn.jsdelivr.net/npm/three@{three_version}/examples/jsm/",
      "@sparkjsdev/spark": "https://cdn.jsdelivr.net/npm/@sparkjsdev/spark@{spark_version}/dist/spark.module.js"
    }}
  }}
  </script>
  <script type="module">
  import * as THREE from 'three';
  import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';
  import {{ CSS2DRenderer, CSS2DObject }} from 'three/addons/renderers/CSS2DRenderer.js';
  import {{ SparkRenderer, SplatMesh }} from '@sparkjsdev/spark';

  const canvas = document.getElementById('app-canvas');
  const PRIMARY_ASSET = '{primary_asset}';
  const PAGED = {paged_json};

  // ---- Viewer config ----
  const _DEFAULTS = {{
    camera: {{ enabled: false, pitch_min: -89, pitch_max: 89, zoom_min: 1, zoom_max: 200,
              ground_height: 0.3, bounds_radius: 150 }},
    splat_budget: 0,
    annotations: [],
    background: {{ type: 'color', color: '#1a1a1a' }},
    postprocessing: {{ tonemapping: 'neutral', exposure: 1.5 }},
    audio: [],
    camera_paths: [],
    default_path_id: null,
    spark_render: {{
      lod_splat_scale: 1.0,
      lod_render_scale: 1.0,
      foveation: {{ enabled: false, cone_fov0: 30, cone_fov: 90, cone_foveate: 2.0, behind_foveate: 4.0 }},
      ondemand_lod_fallback: true
    }}
  }};
  let cfg = _DEFAULTS;
  try {{
    const r = await fetch('viewer-config.json');
    if (r.ok) cfg = {{ ..._DEFAULTS, ...(await r.json()) }};
  }} catch (e) {{ /* defaults */ }}

  // ---- THREE + Spark setup ----
  const renderer = new THREE.WebGLRenderer({{ canvas, antialias: false, powerPreference: 'high-performance' }});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);

  const _TONEMAP = {{
    linear: THREE.LinearToneMapping,
    neutral: THREE.NeutralToneMapping ?? THREE.NoToneMapping,
    aces: THREE.ACESFilmicToneMapping,
    aces2: THREE.ACESFilmicToneMapping,
    filmic: THREE.AgXToneMapping ?? THREE.ACESFilmicToneMapping,
  }};
  renderer.toneMapping = _TONEMAP[cfg.postprocessing?.tonemapping] ?? THREE.NeutralToneMapping;
  renderer.toneMappingExposure = cfg.postprocessing?.exposure ?? 1.5;
  const bg = cfg.background || _DEFAULTS.background;
  if (bg.type === 'color' && bg.color) {{
    renderer.setClearColor(new THREE.Color(bg.color), 1);
    document.body.style.background = bg.color;
  }}

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.01, 1000);
  camera.position.set(0, 2, 10);

  const sparkOpts = {{ renderer }};
  const sr = cfg.spark_render || _DEFAULTS.spark_render;
  if (typeof sr.lod_splat_scale === 'number') sparkOpts.lodSplatScale = sr.lod_splat_scale;
  if (typeof sr.lod_render_scale === 'number') sparkOpts.lodRenderScale = sr.lod_render_scale;
  const spark = new SparkRenderer(sparkOpts);
  scene.add(spark);

  // SplatMesh — load the primary asset (.rad with paged streaming by default).
  // Apply the 180°-X flip to match the PlayCanvas viewer's splat orientation,
  // so annotations and camera-paths stored in PC-displayed frame line up.
  const splatMeshOpts = {{ url: PRIMARY_ASSET }};
  if (PAGED) splatMeshOpts.paged = true;
  // Foveation (Spark-only):
  if (sr.foveation?.enabled) {{
    if (typeof sr.foveation.cone_fov0 === 'number') splatMeshOpts.coneFov0 = sr.foveation.cone_fov0;
    if (typeof sr.foveation.cone_fov === 'number') splatMeshOpts.coneFov = sr.foveation.cone_fov;
    if (typeof sr.foveation.cone_foveate === 'number') splatMeshOpts.coneFoveate = sr.foveation.cone_foveate;
    if (typeof sr.foveation.behind_foveate === 'number') splatMeshOpts.behindFoveate = sr.foveation.behind_foveate;
  }}
  // If .rad isn't available, tiny-lod fallback in-browser:
  if (!PAGED && sr.ondemand_lod_fallback) splatMeshOpts.lod = true;

  const splat = new SplatMesh(splatMeshOpts);
  splat.quaternion.setFromEuler(new THREE.Euler(Math.PI, 0, 0));
  scene.add(splat);

  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.target.set(0, 1, 0);
  controls.update();

  // CSS2D layer for DOM annotations
  const css2d = new CSS2DRenderer({{ element: document.getElementById('css2d-root') }});
  css2d.setSize(window.innerWidth, window.innerHeight);

  // Audio (conditional on config having audio sources — matches PC viewer)
  let audioListener = null;
  if ((cfg.audio || []).length > 0) {{
    audioListener = new THREE.AudioListener();
    camera.add(audioListener);
    const audioLoader = new THREE.AudioLoader();
    for (const src of cfg.audio) {{
      const isPositional = !!src.positional;
      const sound = isPositional ? new THREE.PositionalAudio(audioListener) : new THREE.Audio(audioListener);
      audioLoader.load(src.file, (buffer) => {{
        sound.setBuffer(buffer);
        sound.setLoop(src.loop !== false);
        sound.setVolume(typeof src.volume === 'number' ? src.volume : 0.5);
        if (isPositional) {{
          sound.setRefDistance(5);
          sound.setMaxDistance(100);
        }}
        if (src.pos && isPositional) {{
          const holder = new THREE.Object3D();
          holder.position.set(src.pos[0], src.pos[1], src.pos[2]);
          holder.add(sound);
          scene.add(holder);
        }}
        sound.play();
      }});
    }}
  }}

  // ---- Annotations (CSS2DObject) ----
  const annotationsData = cfg.annotations || [];
  const markerObjs = [];  // index-aligned with annotationsData
  for (const a of annotationsData) {{
    const el = document.createElement('div');
    el.className = 'ann-marker';
    const lbl = (a.label || '?').replace(/</g, '&lt;');
    const title = (a.title || '').replace(/</g, '&lt;');
    const text = (a.text || '').replace(/</g, '&lt;');
    el.innerHTML = '<div class="ann-dot">' + lbl + '</div>' +
      '<div class="ann-tooltip">' + (title ? '<h4>' + title + '</h4>' : '') + (text ? '<p>' + text + '</p>' : '') + '</div>';
    const obj = new CSS2DObject(el);
    obj.position.fromArray(a.pos);
    scene.add(obj);
    markerObjs.push({{ el, obj }});
  }}

  // ---- Camera-path playback ----
  // Same CubicSpline + buildPlayer + sampleAt algorithm as the PlayCanvas viewer
  // — ported from SuperSplat (PlayCanvas Ltd, MIT). 8-D spline over
  // (pos.xyz, quat.xyzw, fov). Runs identically in both renderers so the same
  // camera_paths JSON plays back byte-for-byte in either.
  class CubicSpline {{
    constructor(times, knots) {{
      this.times = times; this.knots = knots;
      this.dim = knots.length / times.length / 3;
    }}
    evaluate(time, result) {{
      const times = this.times; const last = times.length - 1;
      if (time <= times[0]) {{ this.getKnot(0, result); return; }}
      if (time >= times[last]) {{ this.getKnot(last, result); return; }}
      let seg = 0;
      while (time >= times[seg + 1]) seg++;
      this.evaluateSegment(seg, (time - times[seg]) / (times[seg + 1] - times[seg]), result);
    }}
    getKnot(index, result) {{
      const dim = this.dim; const idx = index * 3 * dim;
      for (let i = 0; i < dim; i++) result[i] = this.knots[idx + i * 3 + 1];
    }}
    evaluateSegment(segment, t, result) {{
      const knots = this.knots; const dim = this.dim;
      const t2 = t * t; const twot = t + t; const omt = 1 - t; const omt2 = omt * omt;
      let idx = segment * dim * 3;
      for (let i = 0; i < dim; i++) {{
        const p0 = knots[idx + 1];
        const m0 = knots[idx + 2];
        const m1 = knots[idx + dim * 3];
        const p1 = knots[idx + dim * 3 + 1];
        idx += 3;
        result[i] =
          p0 * ((1 + twot) * omt2) +
          m0 * (t * omt2) +
          p1 * (t2 * (3 - twot)) +
          m1 * (t2 * (t - 1));
      }}
    }}
    static calcKnots(times, points, smoothness) {{
      const n = times.length; const dim = points.length / n;
      const knots = new Array(n * dim * 3);
      for (let i = 0; i < n; i++) {{
        const t = times[i];
        for (let j = 0; j < dim; j++) {{
          const idx = i * dim + j;
          const p = points[idx];
          let tangent;
          if (i === 0) tangent = (points[idx + dim] - p) / (times[i + 1] - t);
          else if (i === n - 1) tangent = (p - points[idx - dim]) / (t - times[i - 1]);
          else tangent = (points[idx + dim] - points[idx - dim]) / (times[i + 1] - times[i - 1]);
          const inScale = i > 0 ? (times[i] - times[i - 1]) : (times[1] - times[0]);
          const outScale = i < n - 1 ? (times[i + 1] - times[i]) : (times[i] - times[i - 1]);
          knots[idx * 3] = tangent * inScale * smoothness;
          knots[idx * 3 + 1] = p;
          knots[idx * 3 + 2] = tangent * outScale * smoothness;
        }}
      }}
      return knots;
    }}
    static fromPoints(times, points, smoothness = 1) {{
      return new CubicSpline(times, CubicSpline.calcKnots(times, points, smoothness));
    }}
    static fromPointsLooping(length, times, points, smoothness = 1) {{
      if (times.length < 2) return CubicSpline.fromPoints(times, points, smoothness);
      const dim = points.length / times.length;
      const newTimes = times.slice();
      const newPoints = points.slice();
      newTimes.push(length + times[0], length + times[1]);
      newPoints.push(...points.slice(0, dim * 2));
      newTimes.splice(0, 0, times[times.length - 2] - length, times[times.length - 1] - length);
      newPoints.splice(0, 0, ...points.slice(points.length - dim * 2));
      return CubicSpline.fromPoints(newTimes, newPoints, smoothness);
    }}
  }}

  function buildPlayer(p) {{
    const sortedKfs = (p.keyframes || []).slice().sort((a, b) => (a.t || 0) - (b.t || 0));
    if (sortedKfs.length < 2) return null;
    const times = []; const points = []; const sourceKf = [];
    let acc = 0;
    const lastDef = {{ quat: [0, 0, 0, 1], fov: 60 }};
    for (let i = 0; i < sortedKfs.length; i++) {{
      const kf = sortedKfs[i];
      const tBase = (kf.t || 0) + acc;
      const quat = (kf.quat && kf.quat.length === 4) ? kf.quat : lastDef.quat;
      const fov = (typeof kf.fov === 'number') ? kf.fov : lastDef.fov;
      lastDef.quat = quat; lastDef.fov = fov;
      let q = quat;
      if (sourceKf.length > 0) {{
        const prev = points.slice(-5, -1);
        const dot = prev[0]*q[0] + prev[1]*q[1] + prev[2]*q[2] + prev[3]*q[3];
        if (dot < 0) q = [-q[0], -q[1], -q[2], -q[3]];
      }}
      times.push(tBase);
      points.push(kf.pos[0], kf.pos[1], kf.pos[2], q[0], q[1], q[2], q[3], fov);
      sourceKf.push(i);
      if (kf.hold_s && kf.hold_s > 0) {{
        times.push(tBase + kf.hold_s);
        points.push(kf.pos[0], kf.pos[1], kf.pos[2], q[0], q[1], q[2], q[3], fov);
        sourceKf.push(i);
        acc += kf.hold_s;
      }}
    }}
    const smoothness = (typeof p.smoothness === 'number') ? p.smoothness : 1.0;
    const playSpeed = (typeof p.play_speed === 'number' && p.play_speed > 0) ? p.play_speed : 1.0;
    const duration = times[times.length - 1];
    const spline = p.loop
      ? CubicSpline.fromPointsLooping(duration, times, points, smoothness)
      : CubicSpline.fromPoints(times, points, smoothness);
    return {{ spline, times, sortedKfs, sourceKf, duration, loop: !!p.loop, playSpeed }};
  }}

  const _splineOut = new Array(8);
  function sampleAt(player, t) {{
    if (player.loop && t > player.duration) t = t % player.duration;
    player.spline.evaluate(t, _splineOut);
    const qx = _splineOut[3], qy = _splineOut[4], qz = _splineOut[5], qw = _splineOut[6];
    const n = Math.hypot(qx, qy, qz, qw) || 1;
    const times = player.times;
    let seg = 0;
    while (seg < times.length - 1 && times[seg + 1] < t) seg++;
    return {{
      pos: [_splineOut[0], _splineOut[1], _splineOut[2]],
      quat: [qx/n, qy/n, qz/n, qw/n],
      fov: _splineOut[7],
      _kfIndex: player.sourceKf[seg],
    }};
  }}

  let _player = null, _t0 = 0, _activePathId = null, _lastTriggeredAnnotation = null;

  const hud = document.getElementById('path-hud');
  const selEl = document.getElementById('path-select');
  const playBtn = document.getElementById('path-play');
  const stopBtn = document.getElementById('path-stop');
  const scrubEl = document.getElementById('path-scrub');
  const timeEl = document.getElementById('path-time');

  const cameraPaths = cfg.camera_paths || [];
  if (cameraPaths.length > 0) {{
    hud.classList.add('active');
    for (const p of cameraPaths) {{
      const opt = document.createElement('option');
      opt.value = p.id; opt.textContent = p.name || p.id;
      selEl.appendChild(opt);
    }}
  }}

  function startPath(pathId) {{
    const p = cameraPaths.find(x => x.id === pathId);
    if (!p) return;
    _player = buildPlayer(p);
    if (!_player) {{ alert('Path needs at least 2 keyframes.'); return; }}
    _t0 = performance.now();
    _activePathId = pathId;
    controls.enabled = false;
  }}
  function stopPath() {{
    _player = null; _activePathId = null; _lastTriggeredAnnotation = null;
    controls.enabled = true;
    markerObjs.forEach(m => m.el.querySelector('.ann-dot').classList.remove('path-active'));
  }}
  playBtn.addEventListener('click', () => startPath(selEl.value));
  stopBtn.addEventListener('click', stopPath);
  scrubEl.addEventListener('input', () => {{
    if (!_player) {{
      const p = cameraPaths.find(x => x.id === selEl.value);
      if (!p) return;
      _player = buildPlayer(p);
      if (!_player) return;
      controls.enabled = false;
    }}
    const t = (parseFloat(scrubEl.value) / 1000) * _player.duration;
    _t0 = performance.now() - (t / (_player.playSpeed || 1.0)) * 1000;
  }});
  if (cfg.default_path_id) {{
    selEl.value = cfg.default_path_id;
    startPath(cfg.default_path_id);
  }}

  // ---- Frame loop ----
  const cam = cfg.camera || _DEFAULTS.camera;
  function tick() {{
    requestAnimationFrame(tick);

    // Path playback (when active)
    if (_player) {{
      const speed = _player.playSpeed || 1.0;
      const tNow = ((performance.now() - _t0) / 1000) * speed;
      if (tNow > _player.duration && !_player.loop) {{
        stopPath();
      }} else {{
        const s = sampleAt(_player, tNow);
        camera.position.set(s.pos[0], s.pos[1], s.pos[2]);
        camera.quaternion.set(s.quat[0], s.quat[1], s.quat[2], s.quat[3]);
        camera.fov = s.fov;
        camera.updateProjectionMatrix();
        const pct = Math.min(1000, Math.max(0, (tNow / _player.duration) * 1000));
        scrubEl.value = pct;
        timeEl.textContent = tNow.toFixed(2) + 's';
        const tk = _player.sortedKfs[s._kfIndex];
        const triggerId = (tk && tk.annotation_id) || null;
        if (triggerId !== _lastTriggeredAnnotation) {{
          markerObjs.forEach(m => m.el.querySelector('.ann-dot').classList.remove('path-active'));
          if (triggerId) {{
            const idx = annotationsData.findIndex(a => a.id === triggerId);
            if (idx >= 0 && markerObjs[idx]) markerObjs[idx].el.querySelector('.ann-dot').classList.add('path-active');
          }}
          _lastTriggeredAnnotation = triggerId;
        }}
      }}
    }}

    // Camera bounds clamp (conditional on cfg.camera.enabled)
    if (cam && cam.enabled === true) {{
      const p = camera.position;
      if (p.x < -cam.bounds_radius) p.x = -cam.bounds_radius;
      else if (p.x > cam.bounds_radius) p.x = cam.bounds_radius;
      if (p.z < -cam.bounds_radius) p.z = -cam.bounds_radius;
      else if (p.z > cam.bounds_radius) p.z = cam.bounds_radius;
      if (p.y < cam.ground_height) p.y = cam.ground_height;
    }}

    controls.update();
    renderer.render(scene, camera);
    css2d.render(scene, camera);
  }}

  // Hide loading once the splat is ready
  (async () => {{
    if (splat.initialized && typeof splat.initialized.then === 'function') {{
      try {{ await splat.initialized; }} catch (e) {{ console.warn('splat init failed', e); }}
    }}
    document.getElementById('loading').classList.add('hidden');
    document.getElementById('splat-count').textContent = PAGED ? 'Streaming .rad' : 'Loaded';
  }})();

  // Resize
  window.addEventListener('resize', () => {{
    const w = window.innerWidth, h = window.innerHeight;
    renderer.setSize(w, h);
    css2d.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }});

  tick();

  // Debug hook for Playwright smoke tests (same pattern as PC viewer)
  window._spDebug = {{ camera, scene, splat, controls, renderer }};
  </script>
</body>
</html>
"""
