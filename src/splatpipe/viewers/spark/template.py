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


SPARK_VERSION = "2.0.0"  # upstream base the fork derives from
THREE_VERSION = "0.180.0"
# Patched Spark fork. Upstream @sparkjsdev/spark 2.0.0 has two --cluster-sh
# aborts that surface as a generic browser "Out of Memory" page:
#   1. RefCell re-entrancy in ChunkDecoder::push (BUFFER thread-local held
#      across the re-entrant receiver callback) — fixed in decoder.rs.
#   2. Chunk-0 codebook ordering race: a non-zero chunk decodes before
#      chunk 0's SH codebook arrives, so set_sh_labels indexes an empty
#      Vec ("index out of bounds: the len is 0") — fixed in SplatPager.ts
#      by gating non-zero cluster-sh chunks on chunk 0.
# Self-hosted, version-pinned path; never float and never reuse the path
# (Bunny edge-cache). Bump -rcfN whenever the fork changes.
SPARK_FORK_URL = "https://splatpipe-cdn.b-cdn.net/_sparkfork-rcf2/spark.module.min.js"


def html_for(
    project_name: str,
    *,
    primary_asset: str = "scene.rad",
    paged: bool = True,
    share_url: str | None = None,
    share_image: str | None = None,
    description: str | None = None,
) -> str:
    """Render the Spark viewer HTML for a given project.

    `primary_asset` is the filename the SplatMesh loads (relative to index.html).
    `paged=True` enables HTTP-Range streaming for `.rad`; should be False for `.sog`.

    Share-card (Open Graph + Twitter) so a pasted viewer link shows a rich
    preview in Telegram / WhatsApp / iMessage / Discord / Slack / Twitter:
      * `share_url`   — absolute URL of the deployed index.html. Optional;
                        when given it's emitted as `og:url`. Scrapers fall
                        back to the fetched URL when absent, so it's safe to
                        omit for the local dashboard preview.
      * `share_image` — preview image. Defaults to the relative
                        `"preview.jpg"` (a scraper resolves it against the
                        page URL); deploy scripts pass an ABSOLUTE Bunny URL
                        for maximum cross-platform compatibility. The image
                        itself is generated + uploaded separately
                        (`.codex-run/make_share_preview.py`).
      * `description` — card text; a sensible generic default otherwise.
    Backward-compatible: every arg is optional, so existing callers
    (`SparkAssembler`, older deploy scripts) keep working and still get a
    title/description card (plus the image card once `preview.jpg` exists).
    """
    import html as _h

    _title = f"{project_name} — interactive 3D scene"
    _desc = description or (
        "Explore this photogrammetry capture in 3D, right in your browser — "
        "a Gaussian-splat scene streamed with Splatpipe / Spark 2."
    )
    _img = share_image or "preview.jpg"

    def _e(s: object) -> str:
        return _h.escape(str(s), quote=True)

    _meta = [
        f'<meta name="description" content="{_e(_desc)}">',
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="Splatpipe">',
        f'<meta property="og:title" content="{_e(_title)}">',
        f'<meta property="og:description" content="{_e(_desc)}">',
        f'<meta property="og:image" content="{_e(_img)}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        f'<meta property="og:image:alt" content="{_e(_title)}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{_e(_title)}">',
        f'<meta name="twitter:description" content="{_e(_desc)}">',
        f'<meta name="twitter:image" content="{_e(_img)}">',
    ]
    if share_url:
        _meta.insert(5, f'<meta property="og:url" content="{_e(share_url)}">')
    # Joined value is substituted as a single {share_meta} field; .format()
    # does NOT re-scan substituted text, so no brace-doubling is needed here.
    share_meta = "\n  ".join(_meta)

    return _VIEWER_TEMPLATE.format(
        project_name=project_name,
        spark_version=SPARK_VERSION,
        three_version=THREE_VERSION,
        spark_fork_url=SPARK_FORK_URL,
        primary_asset=primary_asset,
        paged_json=json.dumps(bool(paged)),
        share_meta=share_meta,
    )


_VIEWER_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <!-- three loads cross-origin from jsdelivr and blocks first paint (the
       app can't boot until it arrives). Kicking off the DNS+TLS handshake
       here, before the importmap is discovered, saves ~1 RTT on the
       critical path. The patched @sparkjsdev/spark fork + scene.rad/.radc
       are same-origin as this HTML so that connection is already warm —
       no preconnect there would be redundant. -->
  <link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
  <link rel="dns-prefetch" href="https://cdn.jsdelivr.net">
  <title>{project_name} — Splatpipe Viewer (Spark)</title>
  {share_meta}
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    /* iOS Safari: a long-press anywhere will, by default, trigger
       text-selection / the magnifier loupe / the "Copy · Look up"
       callout. Our double-tap-and-hold gesture sits exactly in that
       window, so we have to opt out of all of it on the viewer
       surface. Setting these on <body> covers the canvas + all
       overlays (header, hint line, stats) without affecting the
       label inside the splat-budget <select> dropdown. */
    body {{
      overflow: hidden; background: #1a1a1a;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      user-select: none;
      -webkit-user-select: none;
      -webkit-touch-callout: none;          /* disable iOS long-press "Copy" callout */
      -webkit-tap-highlight-color: transparent;  /* no grey flash on tap */
    }}
    /* The <select> dropdown still needs to render its option list
       normally — re-enable selection on form controls. */
    select, option {{ user-select: auto; -webkit-user-select: auto; }}
    /* `touch-action: none` tells the browser we own all touch input
       on the canvas: no native double-tap-zoom, no panning, no
       pinch-zoom of the page. OrbitControls' pinch + our custom
       gestures handle everything. The iOS-specific opts (callout /
       user-select / tap-highlight) are repeated directly on the
       canvas because iOS 15+ has regressed the body-level rules on
       non-text elements — putting them on both is the only reliable
       cure (Apple Developer Forums threads 691021 + 808606). */
    canvas {{
      width: 100vw; height: 100vh; display: block;
      touch-action: none;
      user-select: none;
      -webkit-user-select: none;
      -webkit-touch-callout: none;
      -webkit-tap-highlight-color: transparent;
    }}

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
    #splat-count .fps {{
      font-size: 14px; opacity: 0.55; margin-left: 12px; vertical-align: middle;
      font-family: monospace; letter-spacing: 0.5px;
    }}

    #quality-buttons {{ display: flex; gap: 6px; align-items: center; }}
    .quality-btn {{
      padding: 8px 14px; border: 1px solid rgba(255,255,255,0.3);
      border-radius: 6px; background: rgba(0,0,0,0.5); color: #ccc;
      font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.15s;
    }}
    .quality-btn:hover {{ background: rgba(255,255,255,0.15); color: #fff; }}
    /* Make <select> visually consistent with the buttons — appearance:none
       turns off the native chrome that otherwise renders a white control on
       Chromium-Windows. The .quality-btn rule already provides the
       semi-transparent background; we just add a caret SVG on top. Note the
       `background:` shorthand below uses transparent fill so the .quality-btn
       rgba(0,0,0,0.5) shorthand isn't clobbered — we layer the caret image
       only, leaving background-color untouched. */
    select.quality-btn {{
      appearance: none; -webkit-appearance: none; -moz-appearance: none;
      padding-right: 26px;
      background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path d='M0 0l5 6 5-6z' fill='%23ccc'/></svg>");
      background-repeat: no-repeat;
      background-position: right 10px center;
    }}
    /* The popup (option list) itself can't be styled in Chromium — the OS
       renders it. Setting option colors at least helps in browsers that do. */
    select.quality-btn option {{ background: #1a1a1a; color: #ccc; }}
    /* Bench button: solid red pulse when actively recording so the user
       knows the trace is running and won't accidentally click away. */
    #bench-btn.recording {{
      background: rgba(220,40,40,0.85); border-color: rgba(255,80,80,0.9); color: #fff;
      animation: bench-pulse 1s ease-in-out infinite;
    }}
    @keyframes bench-pulse {{ 50% {{ opacity: 0.65; }} }}

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
    /* Front-load progress (pillar V): only visible during the initial chunk
       prefetch phase. Bar width is driven by pager.pageFreelist + time. */
    #loading-progress-bar {{
      width: 240px; height: 6px;
      background: rgba(255,255,255,0.15);
      border-radius: 3px;
      margin-top: 18px;
      overflow: hidden;
    }}
    #loading-progress-fill {{
      height: 100%; background: #fff;
      width: 0%; transition: width 200ms ease;
    }}
    #loading-progress-text {{
      margin-top: 8px !important; font-size: 12px !important;
      color: rgba(255,255,255,0.5) !important;
    }}

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

    /* Safari-on-Mac streaming hint (#78). Only ever shown on a Mac running a
       non-Safari (ANGLE→Metal) browser — see the detector JS for why. */
    #safari-hint {{
      position: absolute; top: 16px; left: 50%; transform: translateX(-50%);
      z-index: 16; display: none; align-items: center; gap: 12px;
      max-width: min(92vw, 580px);
      background: rgba(0,0,0,0.72); color: rgba(255,255,255,0.82);
      border: 1px solid rgba(255,255,255,0.16); border-radius: 8px;
      padding: 8px 10px 8px 14px; font-size: 12px; line-height: 1.35;
      backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px);
      box-shadow: 0 4px 18px rgba(0,0,0,0.45);
    }}
    #safari-hint.show {{ display: flex; }}
    #safari-hint b {{ color: #fff; font-weight: 600; }}
    #safari-hint-close {{
      flex: none; width: 20px; height: 20px; line-height: 18px; text-align: center;
      border: 1px solid rgba(255,255,255,0.22); border-radius: 50%;
      background: transparent; color: rgba(255,255,255,0.7);
      font-size: 11px; cursor: pointer; padding: 0;
    }}
    #safari-hint-close:hover {{ background: rgba(255,255,255,0.15); color: #fff; }}

    /* ?embed=1 — clean canvas-only mode for <iframe> embedding (portfolio
       sites). Hides every Splatpipe chrome element; the 3D scene,
       annotations and camera-path playback are untouched. */
    body.embed #header,
    body.embed #quality-buttons,
    body.embed #stats,
    body.embed #controls-hint,
    body.embed #safari-hint,
    body.embed #path-hud {{ display: none !important; }}
  </style>
</head>
<body>
  <canvas id="app-canvas"></canvas>

  <div id="header">
    <div id="title">
      <h1>{project_name}</h1>
      <p>Splatpipe Viewer · Spark 2</p>
    </div>
    <div id="quality-buttons">
      <select id="splat-budget" class="quality-btn" title="Splat budget (lodSplatCount) — auto-picked from device tier on load, override here. Capped at the 6 M resident pool.">
        <option value="500000">500K</option>
        <option value="1000000">1M</option>
        <option value="1500000">1.5M</option>
        <option value="2000000">2M</option>
        <option value="3000000">3M</option>
        <option value="4000000">4M</option>
        <option value="6000000">6M</option>
      </select>
      <select id="bench-mode" class="quality-btn" title="Which benchmark the Bench button runs. Probe = teleport → time-to-loaded. Rotate = yaw at each pose while loading → frame-times-while-loading. Orbit/Dolly/Cold = motion-fps traces.">
        <option value="orbit">Bench: Orbit 360°</option>
        <option value="probe">Bench: Probe (load time)</option>
        <option value="rotate">Bench: Rotate (fps while loading)</option>
        <option value="dolly">Bench: Dolly-in</option>
        <option value="cold">Bench: Cold load</option>
      </select>
      <button id="bench-btn" class="quality-btn"
              title="Run the selected benchmark (dropdown at left). Click again to stop early; downloads a JSON trace (+ contact sheet for probe/rotate).">Bench</button>
      <button id="setstart-btn" class="quality-btn"
              title="Use the current camera as this scene's start view. Generates a token to send to Claude to save it for everyone.">Set start view</button>
    </div>
  </div>

  <div id="stats">
    <div id="splat-count">Loading…</div>
  </div>

  <div id="controls-hint">
    <b>Left-drag</b> orbit · <b>Right-drag</b> look · <b>Middle-drag</b> pan ·
    <b>Scroll</b> zoom · <b>WASD / Arrows</b> fly · <b>Q/E</b> up/down ·
    <b>Shift</b> sprint · <b>Double-click / double-tap</b> set pivot ·
    <b>Double-tap+drag</b> zoom (touch)
  </div>

  <div id="safari-hint" role="status">
    <span>For the smoothest playback on Mac, open this scene in <b>Safari</b> — other browsers can stutter while detail streams in.</span>
    <button id="safari-hint-close" title="Dismiss" aria-label="Dismiss">✕</button>
  </div>

  <div id="loading">
    <div class="spinner"></div>
    <p>Loading splats…</p>
    <div id="loading-progress-bar"><div id="loading-progress-fill"></div></div>
    <p id="loading-progress-text">Preparing…</p>
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
      "@sparkjsdev/spark": "{spark_fork_url}"
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

  // ?stock=1 in the URL strips all Splatpipe perf modifications (no DPR cap,
  // no mobile Spark-knob bundle, no maxSh cap, no processUploads throttle).
  // Useful for A/B visual comparisons against pure Spark defaults.
  const STOCK = new URLSearchParams(location.search).get('stock') === '1';
  if (STOCK) console.info('[Splatpipe] STOCK mode: all perf mods disabled');

  // ?embed=1 — clean canvas-only mode for <iframe> embedding (e.g. the
  // geddart.de portfolio): a <body> class hides all Splatpipe chrome via
  // CSS (header, budget/bench buttons, stats, hints, path HUD). The scene,
  // annotations and camera-path playback are unchanged. CSS-driven so
  // there's no per-element JS or layout flash.
  const EMBED = new URLSearchParams(location.search).get('embed') === '1';
  if (EMBED) {{ document.body.classList.add('embed'); console.info('[Splatpipe] EMBED mode (chrome hidden for iframe)'); }}

  // ?bench=<value> auto-triggers a benchmark recording.
  //   ?bench=1               → 30 s static recording (user drives the camera or
  //                            sits still — whatever they want measured)
  //   ?bench=<path-id>       → wait for splat init, snap to the path's first
  //                            keyframe, warm-load that view's pages, then play
  //                            the named camera path while recording. Stops
  //                            recording when the path ends. Reproducible
  //                            cross-device comparison.
  const BENCH_AUTO = new URLSearchParams(location.search).get('bench');

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
    start_view: null,
    spark_render: {{
      lod_splat_scale: 1.0,
      lod_render_scale: 1.0,
      clip_xy: 1.4,
      move_speed_mult: 1.0,
      foveation: {{ enabled: false, cone_fov0: 30, cone_fov: 90, cone_foveate: 2.0, behind_foveate: 4.0 }},
      ondemand_lod_fallback: true
    }}
  }};
  let cfg = _DEFAULTS;
  try {{
    // cache:'no-store' is REQUIRED: Bunny's pull zone serves this with a
    // 30-day max-age (its default override; "Honor Origin Cache-Control"
    // is off so .rad stays long-cached). Without no-store a browser that
    // already opened the viewer would keep a stale config for weeks —
    // breaking "saved for all" for start_view / any scene-config edit.
    // The file is a few KB; always revalidating it is free.
    const r = await fetch('viewer-config.json', {{ cache: 'no-store' }});
    if (r.ok) cfg = {{ ..._DEFAULTS, ...(await r.json()) }};
  }} catch (e) {{ /* defaults */ }}

  // Device tier (used by the renderer DPR cap below, by Spark construction
  // further down, and by the initial splat-budget pick later). The web
  // platform doesn't expose VRAM (privacy / fingerprinting), so we use
  // proxies: touch capability + short screen side, plus `navigator.deviceMemory`
  // (system RAM in GB, capped at 8 by browsers) as a coarse "is this a
  // beefy machine" hint.
  const _deviceProfile = (() => {{
    const isTouch = navigator.maxTouchPoints > 0;
    const isIPadDesktop = /MacIntel/.test(navigator.platform || '') &&
                          navigator.maxTouchPoints > 1;
    const shortSide = Math.min(screen.width || 0, screen.height || 0);
    let tier;
    if (isTouch || isIPadDesktop) {{
      tier = shortSide <= 600 ? 'phone' : 'tablet';
    }} else {{
      tier = 'desktop';
    }}
    return {{ tier, ramGB: navigator.deviceMemory || 4 }};
  }})();

  // ---- THREE + Spark setup ----
  // `antialias: false` — splats are pre-anti-aliased; MSAA is pure overdraw
  // on this primitive and is the dominant fill cost on iOS. Removing it
  // alone took Babylon scenes from 15 → 60 fps on iPhone (community-tested).
  //
  // DPR cap is tier-aware: phones/tablets get capped at 1.5 (iPhone's native
  // DPR=3 wastes 4× the fragment cost for sub-perceptible sharpness on a
  // small screen), but Retina laptops/desktops keep DPR=2 because the user
  // sits closer to a 14"+ screen and any softness shows immediately. We
  // claw back fragment cost on M1-class machines via the Spark knob set
  // (clipXY / minPixelRadius / maxStdDev) — see below.
  const renderer = new THREE.WebGLRenderer({{ canvas, antialias: false, powerPreference: 'high-performance' }});
  // Apple-Silicon detection. An M1/M2-class Mac has no touch → classed
  // 'desktop' and given the discrete-GPU profile, but its GPU fill rate is
  // far lower: measured on a real M1 Pro (IBUG_cs bench trace, 2026-05-16)
  // ~82 ms GPU/frame rasterising 2 M splats at Retina DPR=2 → ~24 fps, while
  // streaming/pool were perfectly healthy (pagesResident stable, 0 storm) —
  // i.e. pure rasterisation fill, NOT memory or streaming. Detect from the
  // GL renderer string and give it a lighter fill profile. Discrete-GPU
  // desktops, phones and tablets are byte-for-byte unchanged.
  (() => {{
    try {{
      const _glr = renderer.getContext();
      const _dbg = _glr.getExtension('WEBGL_debug_renderer_info');
      const _rs = String((_dbg ? _glr.getParameter(_dbg.UNMASKED_RENDERER_WEBGL)
                                : _glr.getParameter(_glr.RENDERER)) || '');
      _deviceProfile.gpuRenderer = _rs;
      _deviceProfile.appleSilicon =
        !STOCK && _deviceProfile.tier === 'desktop' && _rs.toLowerCase().includes('apple');
    }} catch (e) {{ _deviceProfile.appleSilicon = false; }}
  }})();
  const _AS = !!_deviceProfile.appleSilicon;
  if (_AS) console.info('[Splatpipe] Apple-Silicon desktop profile active:', _deviceProfile.gpuRenderer);

  // ---- Safari-on-Mac streaming hint (#78) ---------------------------------
  // Chromium/Firefox on macOS go WebGL→ANGLE→Metal, which does a SYNCHRONOUS
  // main-thread staged texture upload per streamed page; Safari (native
  // WebKit→Metal, no ANGLE) does not. On Apple-Silicon/Intel Macs that makes
  // every non-Safari browser visibly stutter while LoD pages stream, with no
  // in-app fix (exhaustively root-caused — 3 fork upload rewrites + WebGPU +
  // ANGLE's own alwaysPreferStagedTextureUploads off-switch all failed; see
  // memory project_spark_angle_metal_jitter). The only honest user-facing
  // mitigation: tell Mac visitors on a non-Safari browser that Safari is
  // smoother. Detector = the EXACT discriminator that proved the bug — a
  // WebGL renderer string with both "ANGLE" and "Metal" (Safari → "Apple
  // GPU", no ANGLE; Windows/Linux ANGLE → no "Metal"; iOS → all WebKit, no
  // ANGLE → all correctly excluded). Conservative UA fallback ONLY when the
  // renderer string is masked (Brave strict shields / Firefox RFP) and the UA
  // is unambiguously a Mac-desktop non-Safari engine. ?safariHint=1|0 forces
  // on/off (verify on non-Mac). localStorage so a dismissal sticks — no
  // nagging every load. STOCK opts out. Best-effort: never break the viewer.
  (() => {{
    try {{
      const _rsl = String(_deviceProfile.gpuRenderer || '').toLowerCase();
      _deviceProfile.angleMetal = _rsl.includes('angle') && _rsl.includes('metal');
      const _ua = navigator.userAgent || '';
      const _isMacDesktop =
        (/mac/i.test(navigator.platform || '') || /Macintosh/.test(_ua)) &&
        (navigator.maxTouchPoints || 0) <= 1 &&
        !/iPhone|iPad|iPod/.test(_ua);
      const _isNonSafariUA =
        _ua.includes('Chrome/') || _ua.includes('CriOS/') ||
        _ua.includes('Firefox/') || _ua.includes('FxiOS/') || _ua.includes('Edg/');
      const _rsMasked =
        !_rsl || !(_rsl.includes('angle') || _rsl.includes('apple') || _rsl.includes('metal'));
      const _q = new URLSearchParams(location.search).get('safariHint');
      let _show;
      if (_q === '1') _show = true;
      else if (_q === '0') _show = false;
      else _show = !STOCK && (_deviceProfile.angleMetal ||
                              (_rsMasked && _isMacDesktop && _isNonSafariUA));
      const _el = document.getElementById('safari-hint');
      let _dismissed = false;
      try {{ _dismissed = localStorage.getItem('splatpipe.safariHintDismissed') === '1'; }} catch (e) {{}}
      if (_el && _show && !_dismissed) {{
        _el.classList.add('show');
        const _c = document.getElementById('safari-hint-close');
        if (_c) _c.addEventListener('click', () => {{
          _el.classList.remove('show');
          try {{ localStorage.setItem('splatpipe.safariHintDismissed', '1'); }} catch (e) {{}}
        }});
        console.info('[Splatpipe] Safari-on-Mac hint shown (renderer:',
                     _deviceProfile.gpuRenderer, ')');
      }}
    }} catch (e) {{ /* hint is best-effort; must never break the viewer */ }}
  }})();
  // Frame-pace cap. NOT the rejected adaptive-quality loop — a FIXED render
  // cadence, zero runtime budget/quality change. Capping below the GPU's
  // unbounded rate leaves idle headroom every frame to absorb decode/upload
  // bursts, so frame-TIME variance (the "110 fps but still not smooth"
  // stutter the user diagnosed on M1) collapses into a steady beat. Apple-
  // Silicon default 60 (~6 ms slack after the M1's ~10 ms render — room to
  // swallow a burst without missing the deadline). ?fpsCap=N overrides
  // anywhere (N>0 sets it, 0 disables); discrete desktop stays uncapped.
  const _fpsCapQ = parseInt(new URLSearchParams(location.search).get('fpsCap') || '', 10);
  const _FPS_CAP = Number.isFinite(_fpsCapQ)
    ? (_fpsCapQ > 0 ? _fpsCapQ : 0)
    : ((!STOCK && _AS) ? 60 : 0);
  const _FRAME_MIN_MS = _FPS_CAP > 0 ? (1000 / _FPS_CAP) : 0;
  let _lastRenderMs = 0;
  if (_FPS_CAP) console.info('[Splatpipe] frame-pace cap:', _FPS_CAP, 'fps');
  // STOCK mode → no cap (let DPR be whatever the device reports, up to 2 for sanity).
  const _dprCap = STOCK ? 2 :
    ((_deviceProfile.tier === 'phone' || _deviceProfile.tier === 'tablet' || _AS) ? 1.5 : 2);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, _dprCap));
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
  // Pick a sensible initial camera position: an explicit saved start_view
  // wins over everything; then first kf of the default path, first kf of
  // any path, first annotation, otherwise (0, 2, 10). (start_view.target
  // is applied to controls.target where OrbitControls is created below.)
  (() => {{
    const sv = cfg.start_view;
    if (sv && Array.isArray(sv.pos)) {{
      camera.position.set(sv.pos[0], sv.pos[1], sv.pos[2]);
      if (Array.isArray(sv.quat)) camera.quaternion.set(sv.quat[0], sv.quat[1], sv.quat[2], sv.quat[3]);
      if (typeof sv.fov === 'number') {{ camera.fov = sv.fov; camera.updateProjectionMatrix(); }}
      console.info('[Splatpipe] start_view applied', sv.pos);
      return;
    }}
    const dp = (cfg.camera_paths || []).find(p => p.id === cfg.default_path_id);
    const anyPath = (cfg.camera_paths || [])[0];
    const kf = (dp && dp.keyframes && dp.keyframes[0]) || (anyPath && anyPath.keyframes && anyPath.keyframes[0]);
    if (kf && kf.pos) {{
      camera.position.set(kf.pos[0], kf.pos[1], kf.pos[2]);
      if (kf.quat) camera.quaternion.set(kf.quat[0], kf.quat[1], kf.quat[2], kf.quat[3]);
      if (typeof kf.fov === 'number') {{ camera.fov = kf.fov; camera.updateProjectionMatrix(); }}
      return;
    }}
    const ann = (cfg.annotations || [])[0];
    if (ann && ann.pos) {{
      camera.position.set(ann.pos[0] - 5, ann.pos[1] + 2, ann.pos[2] + 5);
      camera.lookAt(ann.pos[0], ann.pos[1], ann.pos[2]);
      return;
    }}
    camera.position.set(0, 2, 10);
  }})();

  const sparkOpts = {{
    renderer,
    // Parallel chunk fetchers. Spark's real default is 3 and it is NOT a hard
    // cap — verified in spark/src/SplatPager.ts (`numFetchers = options
    // .numFetchers ?? 3`; driveFetchers only gates `fetchers.length <
    // numFetchers`). The actual fixed cap of 4 is the *decode-worker* pool,
    // not the fetch count. On a CDN the dominant latency is the HTTP Range
    // round-trip, so more in-flight fetches hide it; decode is still bounded
    // by the 4 workers, hence diminishing returns past ~8. Now that the
    // root-chunk eviction guard no longer wastes slots re-confirming coarse
    // chunks every frame (2026-05-15), raise this so fine detail streams in
    // fast: desktop 8, tablet 6, phone 3 (small bump from 2 — keep iPhone
    // decode-buffer pressure modest given the documented memory fragility).
    numLodFetchers: _deviceProfile.tier === 'phone' ? 3
                  : _deviceProfile.tier === 'tablet' ? 6 : 8,
    // Inflate LoD-merged splats so their alpha caps at 1.0. The default
    // (false) makes merged "blob" splats render as sharp Gaussians that
    // overlap into a pinprick look at lower LoD levels — the "flimsy"
    // appearance the user complained about (2026-05-14). With it on, low-
    // LoD merges look softer and more cohesive (blobbier), matching the
    // pre-optimization look.
    lodInflate: true,
  }};
  // GPU page pool sizing — the total resident splat budget. LoD pulls
  // foreground detail from this pool; the user's call (2026-05-15) is that
  // 6 M total is plenty, cap there (was 32 M on desktop — needless memory
  // for a 1.5 M visible budget). Phone stays lower at 4 M (≈256 MB):
  // iPhone 13-class hits Safari's 256 MB canvas-memory pressure killer
  // well before 6 M — verified by a "crash spiral" reload loop on iPhone
  // 13 mini at low battery (2026-05-14). Headroom for the canvas
  // backbuffer + worker buffers + JS heap matters more than pool size.
  if (_deviceProfile.tier === 'phone') {{
    sparkOpts.maxPagedSplats = 4_194_304;  // 64 pages — iPhone Safari 256MB ceiling; do NOT raise
  }} else if (_deviceProfile.tier === 'tablet') {{
    sparkOpts.maxPagedSplats = 8_000_000;  // tablet: ~122 pages — covers the measured ~115-chunk working set at the 1 M tablet budget + headroom (no storm); iPad memory tolerates it
  }} else if (_AS) {{
    // Apple Silicon also gets the 1 M budget (below) → working set ≈ 115
    // chunks (measured sweep). 12 M = 183 pages covers that with generous
    // turnover headroom so the pager never evict/re-decode storms here
    // either, while saving ~250 MB of GPU textures vs the discrete-desktop
    // 16 M — important on M1's unified memory (JS heap peaked ~2 GB at 2 M).
    sparkOpts.maxPagedSplats = 12_000_000;
  }} else {{
    // Desktop: the GPU page pool MUST exceed the LoD working set, or the
    // pager evicts + RE-DECODES the overflow every frame. MEASURED on
    // IBUG_cs_v3 via Playwright (2026-05-16): at the 2 M desktop budget the
    // LoD traversal selects ~182 chunks, but the old 6 M cap = 92 pages, so
    // ~90 chunks were perpetually evicted and re-decoded in the WASM pool —
    // ~53–79 fetch+decode/s with a STATIC camera, 14× refetch over a 477-
    // chunk scene. Controlled A/B (live lodSplatCount sweep): 0.5 M → 79
    // chunks ≤ 92 → 0.3/s (storm gone); 2 M → 182 ≫ 92 → 79/s. This was the
    // real "detail loads slow / cluster-sh not faster" cause — not decode-
    // pool size, not network, not budget. Size the pool to cover the 2 M
    // working set plus camera-movement turnover headroom. 16 M = 244 pages
    // (~1.34× the static working set). Largest SH ArrayBuffer at 244 pages
    // ≈ 244 MB, well under V8's ~2 GiB cap (no OOM). Verified post-deploy.
    sparkOpts.maxPagedSplats = 16_000_000;
  }}
  // Mobile knob baseline (live-mutable, no hitch). Sources:
  //   • clipXY=1.05: tighter vertex-shader frustum cull → ~10–15% fewer
  //     fragments. Default 1.4 is generous; mobile can afford less slack.
  //   • minPixelRadius=1.5: discard splats smaller than 1.5 px on screen
  //     in vertex shader. Per Spark perf docs this is "the best mobile
  //     lever after lodSplatScale".
  //   • maxStdDev=√5 (≈2.24): tighter Gaussian footprint than the default
  //     √8 (≈2.83). Fewer shaded pixels per splat.
  //   • minSortIntervalMs=50: throttle the radix sort during slow camera
  //     moments. Sort cost is per-splat × per-frame; capping at 20Hz when
  //     the camera is barely moving costs no visible quality on mobile.
  if (!STOCK && (_deviceProfile.tier === 'phone' || _deviceProfile.tier === 'tablet')) {{
    sparkOpts.minSortIntervalMs = 50;
    sparkOpts.lodRenderScale = 1.3;
  }} else if (!STOCK) {{
    // Desktop: push lodRenderScale BELOW Spark's default 1.0 so the LoD
    // traversal keeps subdividing into sub-pixel detail until the
    // lodSplatCount budget — not the 1 px detail floor — is the binding
    // constraint. At the default 1.0, dense scenes (e.g. Speicher) stall
    // around ~4.5 M well under a 6 M budget because further subdivision
    // would yield < 1 px splats. 0.75 lets the visible count climb to the
    // budget the user actually picked. Costs some fragment work on
    // sub-pixel splats — acceptable on desktop GPUs, and exactly the
    // "use the budget" behaviour requested (2026-05-15).
    sparkOpts.lodRenderScale = 0.75;
  }}
  if (_AS) {{
    // Apple Silicon is fill-bound (measured ~82 ms GPU/frame at 2 M · DPR2).
    // Don't chase sub-pixel detail (0.75 → 1.0 = stop at the 1 px floor, far
    // less fragment work); discard < 1.5 px splats (Spark's "best lever
    // after lodSplatScale"); throttle the per-frame sort. Combined with the
    // 1 M budget + 1.5 DPR cap this targets a ~4-6× fill cut (→ smooth).
    sparkOpts.lodRenderScale = 1.0;
    sparkOpts.minPixelRadius = 1.5;
    sparkOpts.minSortIntervalMs = 50;
  }}
  // minAlpha — REVERTED to Spark default. Setting it to 0 introduced
  // visible vertical stripes in semi-transparent structures (tree trunks
  // etc.) on Stettiner Haff — classic alpha-sorting artifact when near-
  // invisible splats render unsorted. Speicher's disappearing is being
  // handled by switching that scene to PlayCanvas renderer instead.
  // clipXY = per-splat XY frustum-cull slack. Spark's default is 1.4 (40%
  // slack). This is now PER-SCENE config (spark_render.clip_xy) instead of
  // the old global 3.0 hack: most scenes only need 1.4 and the wider margin
  // is pure fragment cost for them. A scene whose .rad has giant outlier
  // splats (e.g. Speicher — ln-scale up to ~9 / raw ~8000 units from
  // training: Spark's 1.4 culls them when their centers are off-screen even
  // though their footprint would cover the camera → "scene goes blank")
  // sets clip_xy: 3.0 in its OWN viewer-config. Default 1.4; per-scene
  // override just below; ?clipXY=N forces it (A/B, with the other knobs).
  sparkOpts.clipXY = 1.4;
  const sr = cfg.spark_render || _DEFAULTS.spark_render;
  if (typeof sr.lod_splat_scale === 'number') sparkOpts.lodSplatScale = sr.lod_splat_scale;
  if (typeof sr.lod_render_scale === 'number') sparkOpts.lodRenderScale = sr.lod_render_scale;
  if (typeof sr.clip_xy === 'number' && sr.clip_xy > 0) sparkOpts.clipXY = sr.clip_xy;
  // ---- Detail-lever URL overrides (A/B tuning; same spirit as ?budget=) ----
  // SparkRenderer opts: ?lodRenderScale=N ?lodSplatScale=N ?lodInflate=0|1
  //   ?focalAdjustment=N ?blurAmount=N ?preBlurAmount=N ?maxStdDev=N
  // (mesh foveation ?coneFov0/?coneFov/?coneFoveate/?behindFoveate and
  //  ?maxSh applied further below; ?budget=N via the budget picker.)
  // All highest-priority, for visual A/B of "detail" knobs.
  {{
    const _Q = new URLSearchParams(location.search);
    const _qf = (k) => {{ const v = parseFloat(_Q.get(k)); return Number.isFinite(v) ? v : undefined; }};
    let _v;
    if ((_v = _qf('lodRenderScale')) !== undefined && _v > 0) sparkOpts.lodRenderScale = _v;
    if ((_v = _qf('lodSplatScale'))  !== undefined && _v > 0) sparkOpts.lodSplatScale = _v;
    if ((_v = _qf('clipXY'))         !== undefined && _v > 0) sparkOpts.clipXY = _v;
    if ((_v = _qf('focalAdjustment'))!== undefined && _v > 0) sparkOpts.focalAdjustment = _v;
    if ((_v = _qf('blurAmount'))     !== undefined && _v >= 0) sparkOpts.blurAmount = _v;
    if ((_v = _qf('preBlurAmount'))  !== undefined && _v >= 0) sparkOpts.preBlurAmount = _v;
    if ((_v = _qf('maxStdDev'))      !== undefined && _v > 0) sparkOpts.maxStdDev = _v;
    const _li = _Q.get('lodInflate');
    if (_li === '0' || _li === 'false') sparkOpts.lodInflate = false;
    if (_li === '1' || _li === 'true')  sparkOpts.lodInflate = true;
  }}
  const spark = new SparkRenderer(sparkOpts);
  scene.add(spark);

  // SplatMesh — load the primary asset (.rad with paged streaming by default).
  // Apply the 180°-X flip to match the PlayCanvas viewer's splat orientation,
  // so annotations and camera-paths stored in PC-displayed frame line up.
  // raycastable: true enables Spark's first-class pick API — standard
  // THREE.Raycaster.intersectObject(splat) returns world-space hit points,
  // which we use below for the double-click pivot.
  const splatMeshOpts = {{ url: PRIMARY_ASSET, raycastable: true }};
  if (PAGED) splatMeshOpts.paged = true;
  // Moderate cone foveation ON by default (2026-05-15): centre crisp,
  // edges softer but still "sharp enough" (NOT the aggressive global mush).
  // Pairs with the auto view-tracking focus below. Per-scene config and
  // ?coneFov0= URL params still override these.
  if (!STOCK) {{
    splatMeshOpts.coneFov0 = 55; splatMeshOpts.coneFov = 110;
    splatMeshOpts.coneFoveate = 0.5; splatMeshOpts.behindFoveate = 0.25;
  }}
  // Foveation (Spark-only):
  if (sr.foveation?.enabled) {{
    if (typeof sr.foveation.cone_fov0 === 'number') splatMeshOpts.coneFov0 = sr.foveation.cone_fov0;
    if (typeof sr.foveation.cone_fov === 'number') splatMeshOpts.coneFov = sr.foveation.cone_fov;
    if (typeof sr.foveation.cone_foveate === 'number') splatMeshOpts.coneFoveate = sr.foveation.cone_foveate;
    if (typeof sr.foveation.behind_foveate === 'number') splatMeshOpts.behindFoveate = sr.foveation.behind_foveate;
  }}
  // Foveation URL overrides (apply regardless of config, for A/B tuning).
  {{
    const _Q = new URLSearchParams(location.search);
    const _qf = (k) => {{ const v = parseFloat(_Q.get(k)); return Number.isFinite(v) ? v : undefined; }};
    let _v;
    if ((_v = _qf('coneFov0'))      !== undefined) splatMeshOpts.coneFov0 = _v;
    if ((_v = _qf('coneFov'))       !== undefined) splatMeshOpts.coneFov = _v;
    if ((_v = _qf('coneFoveate'))   !== undefined) splatMeshOpts.coneFoveate = _v;
    if ((_v = _qf('behindFoveate')) !== undefined) splatMeshOpts.behindFoveate = _v;
  }}
  // (maxSh cap for mobile is applied after construction, not as a ctor opt —
  // see below. Setting it as an opt didn't take effect in observed Spark
  // behaviour; the post-construction setter + updateGenerator() does.)

  // If .rad isn't available, tiny-lod fallback in-browser:
  if (!PAGED && sr.ondemand_lod_fallback) splatMeshOpts.lod = true;

  const splat = new SplatMesh(splatMeshOpts);
  // Debug handle — lets tooling (Playwright) read/mutate live detail levers
  // without a reload: window.__sp.spark.lodRenderScale = 0.5, .splat.maxSh,
  // .pager (lazy), etc. Harmless, always on; no secrets exposed.
  try {{ window.__sp = {{ get spark() {{ return spark; }}, get splat() {{ return splat; }}, get pager() {{ return spark.pager; }}, THREE }}; }} catch (e) {{}}
  // Cap spherical-harmonics degree to 1 on mobile (default 3 = SH0+SH1+SH2+SH3).
  // SH3 contributes view-dependent specular detail that's negligible on a small
  // phone screen, and the pager skips SH2/SH3 texture allocs entirely when
  // maxSh < 2 — big bandwidth + shader win on iPhone/Android. Per Spark's
  // own behaviour (verified via bench traces 2026-05-14: setting maxSh in the
  // constructor opts had no effect on splat.maxSh after init), the assignment
  // has to happen post-construction with updateGenerator() called.
  if (!STOCK && (_deviceProfile.tier === 'phone' || _deviceProfile.tier === 'tablet')) {{
    // maxSh=1 dropped both SH2 + SH3 texture allocs — saved bandwidth but
    // also stripped most view-dependent surface variation, giving a matte
    // "flimsy" look on iPhone. =2 keeps SH2 (lobed specular) and skips
    // only SH3 — the most expensive texture but the smallest perceptual
    // contribution on a phone-sized screen. Best quality/perf compromise.
    splat.maxSh = 2;
    if (typeof splat.updateGenerator === 'function') {{
      try {{ splat.updateGenerator(); }} catch (e) {{ console.warn('updateGenerator failed', e); }}
    }}
  }}
  splat.quaternion.setFromEuler(new THREE.Euler(Math.PI, 0, 0));
  scene.add(splat);

  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  // Orbit target: from start_view if set, else ~5m in front of the camera
  // so dragging feels natural. Set before the _orig* snapshot below so
  // Reset/Home and the orbit bench pivot return to the start view too.
  {{
    const sv = cfg.start_view;
    if (sv && Array.isArray(sv.target)) {{
      controls.target.set(sv.target[0], sv.target[1], sv.target[2]);
    }} else {{
      const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
      controls.target.copy(camera.position).addScaledVector(fwd, 5);
    }}
  }}
  controls.update();

  // Snapshot the initial camera + pivot so the programmatic-orbit bench can
  // always reproduce the same world-space circle on every run, regardless of
  // where the user has moved the view. Without this, every bench produced a
  // different orbit and cross-device comparisons were nonsense.
  // These get re-snapshotted post-init by the bbox-based camera framing
  // below (which knows where the splat actually is, not just (0, 2, 10)).
  const _origCamPos = camera.position.clone();
  const _origCamQuat = camera.quaternion.clone();
  let _origCamFov = camera.fov;
  const _origTarget = controls.target.clone();

  // ---- WASD / arrow-key fly navigation (layered on top of OrbitControls) ----
  // The principle: move both `camera.position` AND `controls.target` by the
  // same offset each frame. The orbit pivot follows the camera around, so the
  // user gets fly movement from keys + orbit-around-pivot from mouse drag.
  // Same pattern as PlayCanvas CameraControls' WASD + orbit hybrid.
  const _keys = {{}};
  const _isInputFocused = () => {{
    const a = document.activeElement;
    return a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || a.tagName === 'SELECT');
  }};
  window.addEventListener('keydown', (e) => {{
    if (_isInputFocused()) return;
    _keys[e.code] = true;
  }});
  window.addEventListener('keyup', (e) => {{ _keys[e.code] = false; }});
  window.addEventListener('blur', () => {{ for (const k in _keys) _keys[k] = false; }});

  // Speed in world units per second. Scaled loosely to the initial
  // camera-to-target distance — but that's the AUTHORED start-view framing,
  // not true scene size, so a scene whose start view sits far from its pivot
  // (e.g. Polygraf) flies too fast. A per-scene multiplier
  // (spark_render.move_speed_mult, default 1.0 = unchanged for every other
  // scene) corrects it; ?moveSpeed=N overrides live for A/B feel-tuning.
  const _initDist = camera.position.distanceTo(controls.target);
  const _msQ = parseFloat(new URLSearchParams(location.search).get('moveSpeed'));
  const _moveSpeedMult = (Number.isFinite(_msQ) && _msQ > 0)
    ? _msQ
    : ((typeof sr.move_speed_mult === 'number' && sr.move_speed_mult > 0) ? sr.move_speed_mult : 1.0);
  const MOVE_SPEED = Math.max(2, _initDist * 0.6) * _moveSpeedMult;   // base × per-scene feel
  const SPRINT_MULT = 4;                                     // Shift
  let _lastMoveTime = performance.now();

  function applyKeyMovement() {{
    const now = performance.now();
    const dt = Math.min(0.1, (now - _lastMoveTime) / 1000);  // cap dt to avoid jumps after tab switch
    _lastMoveTime = now;
    if (_player) return;  // camera-path playback owns the camera; ignore keys

    const intent = new THREE.Vector3(0, 0, 0);
    if (_keys.KeyW || _keys.ArrowUp)    intent.z -= 1;
    if (_keys.KeyS || _keys.ArrowDown)  intent.z += 1;
    if (_keys.KeyA || _keys.ArrowLeft)  intent.x -= 1;
    if (_keys.KeyD || _keys.ArrowRight) intent.x += 1;
    if (_keys.KeyQ) intent.y += 1;
    if (_keys.KeyE) intent.y -= 1;
    if (intent.lengthSq() === 0) return;

    intent.normalize();
    // Forward/right derived from camera basis; up is world-up so flying
    // doesn't tilt the pivot ring out of plane.
    const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion);
    const up = new THREE.Vector3(0, 1, 0);

    const sprint = (_keys.ShiftLeft || _keys.ShiftRight) ? SPRINT_MULT : 1;
    const step = MOVE_SPEED * sprint * dt;
    const offset = new THREE.Vector3()
      .addScaledVector(fwd, -intent.z * step)
      .addScaledVector(right, intent.x * step)
      .addScaledVector(up, intent.y * step);

    camera.position.add(offset);
    controls.target.add(offset);  // pivot follows
  }}

  // ---- Right-drag "look" (FPS yaw/pitch, replacing OrbitControls' pan) ----
  // Trick to coexist with OrbitControls: we don't rotate the camera directly
  // (the next controls.update() would clobber it). Instead we *move the
  // orbit target* around the camera by the mouse delta. controls.update()
  // then reorients the camera to look at the moved target, which is
  // equivalent to FPS look. Distance to target stays constant so the orbit
  // ring is preserved — subsequent left-drag orbits around the new gaze.
  // Pan is moved to middle-drag so it's still reachable.
  controls.mouseButtons = {{
    LEFT: THREE.MOUSE.ROTATE,
    MIDDLE: THREE.MOUSE.PAN,
    // RIGHT intentionally omitted — handled below.
  }};

  let _looking = false;
  let _lookLastX = 0, _lookLastY = 0;
  const LOOK_SENSITIVITY = 0.0035;  // radians per pixel

  canvas.addEventListener('contextmenu', (e) => e.preventDefault());

  canvas.addEventListener('pointerdown', (e) => {{
    if (e.button !== 2 || _player) return;
    _looking = true;
    _lookLastX = e.clientX; _lookLastY = e.clientY;
    try {{ canvas.setPointerCapture(e.pointerId); }} catch (err) {{ /* ignore */ }}
  }});
  canvas.addEventListener('pointermove', (e) => {{
    if (!_looking) return;
    const dx = e.clientX - _lookLastX;
    const dy = e.clientY - _lookLastY;
    _lookLastX = e.clientX; _lookLastY = e.clientY;

    const offset = new THREE.Vector3().subVectors(controls.target, camera.position);
    // Yaw around world Y
    offset.applyAxisAngle(new THREE.Vector3(0, 1, 0), -dx * LOOK_SENSITIVITY);
    // Pitch around camera-right (offset × worldUp, after yaw)
    const right = new THREE.Vector3()
      .crossVectors(offset, new THREE.Vector3(0, 1, 0)).normalize();
    if (right.lengthSq() > 0) {{
      offset.applyAxisAngle(right, -dy * LOOK_SENSITIVITY);
    }}
    // Pitch clamp — prevent over-the-top gimbal flip (±~89°)
    const len = offset.length();
    const maxY = len * 0.9998;
    if (offset.y >  maxY) offset.y =  maxY;
    if (offset.y < -maxY) offset.y = -maxY;

    controls.target.copy(camera.position).add(offset);
  }});
  const _endLook = (e) => {{
    if (!_looking) return;
    if (e && e.button !== undefined && e.button !== 2) return;
    _looking = false;
    if (e && e.pointerId !== undefined) {{
      try {{ canvas.releasePointerCapture(e.pointerId); }} catch (err) {{ /* ignore */ }}
    }}
  }};
  canvas.addEventListener('pointerup', _endLook);
  canvas.addEventListener('pointercancel', _endLook);
  window.addEventListener('blur', () => {{ _looking = false; }});

  // ---- Double-click / double-tap pivot (Spark first-class raycast) ----
  // SplatMesh implements three.js's raycast() hook with `raycastable: true`,
  // so a standard THREE.Raycaster against the splat returns world-space hit
  // points. We snap controls.target to the hit point, matching Postshot's
  // "click to set the orbit pivot" behaviour.
  //
  // Desktop: use the native `dblclick` event (mouse-only, reliable).
  // Touch: roll our own double-tap detector — mobile browsers do NOT
  // synthesize `dblclick` reliably from two quick taps (some never do).
  // A "tap" is a pointerdown+pointerup pair on the same finger where the
  // pointer barely moves (< 12 px) and the gesture is short (< 250 ms).
  // Two such taps within 350 ms and 40 px of each other count as a
  // double-tap. We ignore pinch / multi-finger gestures by tracking the
  // active touch pointer's id and bailing out if any other pointer is down.
  const _raycaster = new THREE.Raycaster();
  const _ndc = new THREE.Vector2();
  function _raycastAt(clientX, clientY) {{
    const rect = canvas.getBoundingClientRect();
    _ndc.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    _ndc.y = -((clientY - rect.top) / rect.height) * 2 + 1;
    _raycaster.setFromCamera(_ndc, camera);
    const hits = _raycaster.intersectObject(splat, false);
    return hits.length > 0 ? hits[0].point.clone() : null;
  }}
  function _setPivotAt(clientX, clientY) {{
    if (_player) return;  // ignore during path playback
    const p = _raycastAt(clientX, clientY);
    if (p) {{
      controls.target.copy(p);
      controls.update();
    }}
  }}
  canvas.addEventListener('dblclick', (event) => {{
    _setPivotAt(event.clientX, event.clientY);
  }});

  // ---- Auto view-tracking focus (2026-05-15) ----
  // Continuously drives spark.lodPosOverride/Quat to a virtual pose CLOSE
  // to whatever the camera centre is looking at, so the LoD selects the
  // fine leaves for that region even at a far framing (the only mechanism
  // that beats the distance ceiling — see the detail saga). No clicking:
  // turn the camera, the new centre sharpens by itself ~0.2 s later.
  // Gated to AFTER preload (so it doesn't fight the preload orbit-walk),
  // off during camera-path playback / bench. Off entirely in STOCK.
  let _afOn = !STOCK, _afReady = false, _afLast = 0, _afKey = '', _afSet = false;
  const _afPos = new THREE.Vector3(), _afDir = new THREE.Vector3();
  const FOCUS_NEAR_FRAC = 0.10;   // virtual cam sits 10% of the hit distance off the surface
  // #81: how far AHEAD of the real camera the virtual LoD origin may sit
  // (metres). DEFAULT 0 = origin pinned to the camera ⇒ near geometry always
  // gets finest LoD (the "always high-detail ~5 m around the viewer" goal).
  // History: a 3 m default was tried and REGRESSED the foreground — at a
  // ground-truth user pose, foliage ~1 m ahead had its LoD measured from a
  // point 3 m past it → coarse → "FG totally blurred" (reproduced on desktop
  // at 120 fps, A/B-proven: focusAhead=0 razor-sharp, =3 mush; coneFoveate
  // ruled out). ?focusAhead=N opts back into an ahead-bias if ever wanted.
  const FOCUS_MAX_AHEAD = (() => {{
    const _fa = parseFloat(new URLSearchParams(location.search).get('focusAhead'));
    return Number.isFinite(_fa) ? Math.min(Math.max(_fa, 0), 30) : 0.0;
  }})();
  function _afClear() {{
    if (_afSet) {{ spark.lodPosOverride = undefined; spark.lodQuatOverride = undefined; _afSet = false; }}
  }}
  function _autoFocusTick(now) {{
    // Path playback / bench own the camera+LoD → release focus.
    if (_player || BENCH_AUTO) {{ _afClear(); return; }}
    // User toggled focus off (F) → balanced LoD.
    if (!_afOn) {{ _afClear(); return; }}
    // Before the raycast can work (early load, !_afReady) we KEEP whatever
    // override is set — the initial centre override (from start_view) was
    // applied at frame 1 so the centre loads first; don't wipe it.
    if (!_afReady) return;
    if (now - _afLast < 180) return;          // throttle: ~5 Hz
    const k = camera.position.x.toFixed(2)+','+camera.position.y.toFixed(2)+','+camera.position.z.toFixed(2)
            +'|'+camera.quaternion.x.toFixed(3)+','+camera.quaternion.y.toFixed(3)+','+camera.quaternion.z.toFixed(3);
    if (k === _afKey && _afSet) return;        // camera unchanged & focus already applied
    _afLast = now; _afKey = k;
    _ndc.set(0, 0);
    _raycaster.setFromCamera(_ndc, camera);
    const hits = _raycaster.intersectObject(splat, false);
    if (!hits.length) return;  // transient miss → keep the last good focus (don't drop centre priority)
    const hp = hits[0].point;
    _afDir.subVectors(hp, camera.position);
    const D = _afDir.length();
    if (!(D > 1e-4)) return;
    _afDir.multiplyScalar(1 / D);
    // #81: place the virtual LoD origin AHEAD of the real camera by at most
    // FOCUS_MAX_AHEAD m (was: 0.9·D, i.e. teleported onto the far looked-at
    // surface — which starved near foliage off the centre ray to base LoD and
    // popped as the centre ray jumped between near/far). min() of two smooth
    // terms ⇒ no LoD pop; a near look (0.9·D < cap) keeps the original
    // surface-hugging focus, a far look keeps a high-detail bubble on the user.
    const ahead = Math.min(D * (1 - FOCUS_NEAR_FRAC), FOCUS_MAX_AHEAD);
    _afPos.copy(camera.position).addScaledVector(_afDir, Math.max(ahead, 1e-3));
    if (!spark.lodPosOverride) spark.lodPosOverride = new THREE.Vector3();
    if (!spark.lodQuatOverride) spark.lodQuatOverride = new THREE.Quaternion();
    spark.lodPosOverride.copy(_afPos);
    spark.lodQuatOverride.copy(camera.quaternion);
    _afSet = true;
  }}

  // ---- Toggleable on-screen settings HUD (press 'H') ----
  const _hud = document.createElement('div');
  _hud.id = 'sp-hud';
  _hud.style.cssText = 'position:fixed;left:10px;bottom:10px;z-index:9998;display:none;'
    + 'background:rgba(0,0,0,.72);color:#0f8;font:12px/1.5 monospace;padding:8px 11px;'
    + 'border-radius:7px;white-space:pre;pointer-events:none;';
  document.body.appendChild(_hud);
  let _hudOn = false, _hudF = 0, _hudT = performance.now(), _hudFps = 0;
  function _hudTick() {{
    if (_hudOn) {{
      _hudF++;
      const t = performance.now();
      if (t - _hudT >= 500) {{ _hudFps = Math.round(_hudF * 1000 / (t - _hudT)); _hudF = 0; _hudT = t; }}
      const fmt = n => n >= 1e6 ? (n/1e6).toFixed(2)+'M' : (n>=1e3?(n/1e3).toFixed(0)+'K':String(n|0));
      _hud.textContent =
        'budget       ' + fmt(spark.lodSplatCount) +
        '\\nactiveSplats ' + fmt(spark.activeSplats || 0) +
        '\\nfps          ' + _hudFps +
        '\\nfocus        ' + (_afSet ? 'auto (tracking view)' : (_afOn ? 'auto (idle)' : 'off')) +
        '\\nlodRenderScl ' + spark.lodRenderScale +
        '\\ndevice       ' + _deviceProfile.tier;
    }}
  }}
  window.addEventListener('keydown', (e) => {{
    if (e.key === 'h' || e.key === 'H') {{ _hudOn = !_hudOn; _hud.style.display = _hudOn ? 'block' : 'none'; }}
    if (e.key === 'f' || e.key === 'F') {{ _afOn = !_afOn; if (!_afOn) _afClear(); }}
  }});

  // ---- Touch gesture state machine ----
  //
  // Two coexisting gestures on touch, sharing the same first stage:
  //   • Quick double-tap            → set orbit pivot at hit point
  //   • Double-tap-and-hold-drag    → dolly camera toward/away from hit point
  //                                   (Google/Apple Maps "one-finger zoom")
  //
  // First stage = a regular tap on the same finger: short (<250 ms),
  // stationary (<12 px). At the *second* pointerdown that lands within the
  // double-tap window (≤350 ms, ≤40 px from the first tap), we raycast and
  // arm a zoom gesture *speculatively*. If the finger lifts quickly without
  // moving, we cancel the zoom and fire the pivot instead. If the finger
  // moves vertically more than 6 px, we commit the zoom and clear the pivot
  // candidate so it can't double-fire on lift.
  //
  // Zoom mapping (sources: Mapbox tap_drag_zoom.ts uses 128 px/level;
  // Leaflet.DoubleTapDragZoom uses ~139 px/level; we split at 150):
  //   scale = 2^(-dy / 150)
  // where dy is finger Y movement since the second touchdown. dy>0 (drag
  // down) → scale < 1 → camera closer to anchor (zoom IN). This matches
  // Google Maps; Apple Maps is the well-known outlier.
  //
  // Anchor handling: we raycast ONCE at the second touchdown and lock the
  // world-space point for the entire gesture. Re-raycasting per frame is
  // the #1 reported bug ("focal drift") on Mapbox / Apple Maps issue
  // trackers — don't do it.
  const TAP_MAX_MOVE = 12;            // px — finger jitter on a real "tap"
  const TAP_MAX_DURATION = 250;       // ms
  const DOUBLE_TAP_MAX_GAP = 350;     // ms between two taps
  const DOUBLE_TAP_MAX_DIST = 40;     // px between the two tap positions
  const ZOOM_PROMOTE_PX = 6;          // |dy| at which the gesture flips to zoom
  const ZOOM_PX_PER_2X = 150;         // px of vertical drag = 2× dolly
  const ZOOM_MIN_SCALE = 0.001;       // safety: don't pass through the anchor
  const ZOOM_MAX_SCALE = 1000;        // safety: don't fly to infinity
  let _touchDown = null;              // in-flight first tap: {{ id, x, y, t }}
  let _activeTouches = 0;             // current down-finger count
  let _lastTap = null;                // last completed first tap: {{ x, y, t }}
  let _zoom = null;                   // speculative-or-committed zoom gesture:
                                       // {{ id, startY, anchor: Vector3,
                                       //   initialOffset: Vector3, savedTarget,
                                       //   savedEnabled, savedDamping,
                                       //   committed: bool }}

  function _endZoom(restore) {{
    if (!_zoom) return;
    if (restore && _zoom.committed) {{
      controls.enabled = _zoom.savedEnabled;
      controls.enableDamping = _zoom.savedDamping;
    }}
    _zoom = null;
  }}
  function _commitZoom() {{
    // Promote a speculative zoom to active zoom: clear pivot/tap state
    // so the eventual pointerup doesn't also fire the pivot.
    _zoom.committed = true;
    _zoom.savedEnabled = controls.enabled;
    _zoom.savedDamping = controls.enableDamping;
    controls.enabled = false;       // suppress OrbitControls' single-finger orbit
    controls.enableDamping = false; // remove smoothing lag during drag
    _touchDown = null;
    _lastTap = null;
  }}

  // ---- iOS callout wedge (TouchEvent layer, must run BEFORE the OS gesture timer) ----
  //
  // iOS Safari dispatches TouchEvents *before* synthesizing PointerEvents,
  // and the long-press / loupe / selection-callout timer starts on
  // `touchstart` (~500 ms). By the time our `pointerdown` handler runs and
  // calls preventDefault on it, UIKit has already started its gesture
  // pipeline — and the synthesized PointerEvent's preventDefault does NOT
  // propagate back to the native recognizers. The CSS opt-outs above kill
  // the callout most of the time but the second tap of a double-tap-and-hold
  // still leaks through on iOS 15+ (Apple Developer Forums 691021, 808606).
  //
  // The fix is to listen to TouchEvents directly on the canvas with
  // {{passive: false}} and preventDefault the second tap of a potential
  // double-tap-and-hold-drag. Mapbox uses exactly this pattern in
  // tap_drag_zoom.ts. The wedge is gesture-aware: it only fires on what
  // looks like a second tap, so it doesn't break single-tap, scrolling, or
  // pinch (multi-finger).
  //
  // Note: element-level listeners are NOT forced passive by iOS (unlike
  // document/window-level ones), so `{{passive: false}}` is honored here.
  canvas.addEventListener('touchstart', (event) => {{
    if (event.touches.length !== 1) return;            // multi-finger → leave to OC pinch
    // Is this a potential second tap of a double-tap-and-hold?
    if (_lastTap) {{
      const now = event.timeStamp;
      const t = event.touches[0];
      if (now - _lastTap.t <= DOUBLE_TAP_MAX_GAP &&
          Math.hypot(t.clientX - _lastTap.x, t.clientY - _lastTap.y) <= DOUBLE_TAP_MAX_DIST) {{
        // Kill the iOS callout/loupe/selection pipeline BEFORE it starts.
        event.preventDefault();
      }}
    }}
  }}, {{ passive: false }});
  canvas.addEventListener('touchmove', (event) => {{
    // Once a zoom gesture is committed, preventDefault every touchmove so
    // iOS doesn't start mid-gesture text selection or scroll.
    if (_zoom?.committed) event.preventDefault();
  }}, {{ passive: false }});

  canvas.addEventListener('pointerdown', (event) => {{
    if (event.pointerType !== 'touch') return;
    _activeTouches++;
    if (_activeTouches > 1) {{
      // Multi-finger gesture — abort everything and let OrbitControls' pinch
      // handler take over. If we're mid-zoom, restore controls state.
      if (_zoom?.committed) _endZoom(true); else _zoom = null;
      _touchDown = null;
      _lastTap = null;
      return;
    }}

    const now = performance.now();
    // Is this potentially the second tap of a double-tap?
    const isSecondTap = _lastTap &&
      (now - _lastTap.t) <= DOUBLE_TAP_MAX_GAP &&
      Math.hypot(event.clientX - _lastTap.x, event.clientY - _lastTap.y)
        <= DOUBLE_TAP_MAX_DIST;
    if (isSecondTap && !_player) {{
      // Speculatively arm a zoom gesture by locking a world-space anchor at
      // this tap location. If the user lifts quickly, the regular tap-end
      // logic will turn this into a pivot-set instead.
      const anchor = _raycastAt(event.clientX, event.clientY);
      if (anchor) {{
        _zoom = {{
          id: event.pointerId,
          startY: event.clientY,
          anchor: anchor,
          initialOffset: camera.position.clone().sub(anchor),
          committed: false,
        }};
      }}
    }}

    _touchDown = {{
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      t: now,
    }};
  }});

  canvas.addEventListener('pointermove', (event) => {{
    if (event.pointerType !== 'touch') return;
    if (!_zoom || _zoom.id !== event.pointerId) return;

    const dy = event.clientY - _zoom.startY;
    if (!_zoom.committed) {{
      if (Math.abs(dy) < ZOOM_PROMOTE_PX) return;  // still might be a quick pivot
      _commitZoom();
    }}

    event.preventDefault();
    // Drag DOWN (dy > 0) = zoom IN: shrink camera→anchor offset toward anchor.
    let scale = Math.pow(2, -dy / ZOOM_PX_PER_2X);
    if (scale < ZOOM_MIN_SCALE) scale = ZOOM_MIN_SCALE;
    if (scale > ZOOM_MAX_SCALE) scale = ZOOM_MAX_SCALE;
    camera.position.copy(_zoom.anchor)
      .add(_zoom.initialOffset.clone().multiplyScalar(scale));
    controls.target.copy(_zoom.anchor);
    camera.lookAt(_zoom.anchor);
  }});

  canvas.addEventListener('pointerup', (event) => {{
    if (event.pointerType !== 'touch') return;
    _activeTouches = Math.max(0, _activeTouches - 1);

    if (_zoom && _zoom.id === event.pointerId) {{
      if (_zoom.committed) {{
        // Real zoom completed → restore controls, anchor becomes new pivot.
        controls.update();   // sync OrbitControls' internal spherical to new pose
        _endZoom(true);
        _touchDown = null;
        return;  // do NOT also fire pivot
      }}
      // Speculative zoom that never committed — discard, fall through to
      // standard tap logic (which will fire the pivot if it qualifies).
      _zoom = null;
    }}

    const down = _touchDown;
    _touchDown = null;
    if (!down || down.id !== event.pointerId) return;

    const dx = event.clientX - down.x;
    const dy = event.clientY - down.y;
    const moved = Math.hypot(dx, dy);
    const dur = performance.now() - down.t;
    if (moved > TAP_MAX_MOVE || dur > TAP_MAX_DURATION) {{
      _lastTap = null;
      return;
    }}

    const now = performance.now();
    if (_lastTap &&
        now - _lastTap.t <= DOUBLE_TAP_MAX_GAP &&
        Math.hypot(event.clientX - _lastTap.x, event.clientY - _lastTap.y)
          <= DOUBLE_TAP_MAX_DIST) {{
      _setPivotAt(event.clientX, event.clientY);
      _lastTap = null;
    }} else {{
      _lastTap = {{ x: event.clientX, y: event.clientY, t: now }};
    }}
  }});

  canvas.addEventListener('pointercancel', (event) => {{
    if (event.pointerType !== 'touch') return;
    _activeTouches = Math.max(0, _activeTouches - 1);
    if (_zoom?.committed) _endZoom(true); else _zoom = null;
    _touchDown = null;
  }});

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
    // If a path-driven bench was tied to this path, end its recording too.
    if (_benchActive && (_benchAutoMode === 'path' || _benchAutoMode === 'cold' || _benchAutoMode === 'probe' || _benchAutoMode === 'rotate')) _benchStop();
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

  // ---- Bench launchers (used by both the URL auto-trigger and the button) ----

  // Build a programmatic 360° orbit around controls.target. Reads the camera
  // pose at call time so re-runs from the button respect where the user is now.
  function _buildOrbitPath() {{
    // Spin the AUTHORED start-view pose around the vertical axis through the
    // orbit target — preserving its real radius, height AND look orientation
    // — so the orbit frames exactly what the user framed, just circling it.
    // The old max(8,horiz)/max(dy,5) floors + tmp.lookAt(center) synthesised
    // a far/high vantage with an assumed +Y up that ignored this scene's
    // rotated frame → camera ended up in the sky on close/level views like
    // IBUG (start_view: 3.6 m out, level). Confirmed from the live config +
    // a user screenshot. Anchored to _orig* (the authored start_view, since
    // IBUG hasAuthoredView=true so it is never re-snapshotted) → identical
    // world-space orbit every run.
    const center = _origTarget.clone();
    const off = _origCamPos.clone().sub(center);
    if (off.length() < 0.5) off.set(0, 1, -3);   // only the truly-degenerate cam≈target fallback
    const baseQ = _origCamQuat.clone();
    const upY = new THREE.Vector3(0, 1, 0);
    const N = 36, ORBIT_S = 30;
    const keyframes = [];
    for (let i = 0; i <= N; i++) {{
      const theta = (i / N) * Math.PI * 2;
      const rot = new THREE.Quaternion().setFromAxisAngle(upY, theta);
      const p = off.clone().applyQuaternion(rot).add(center);
      const q = rot.clone().multiply(baseQ);   // rotate the authored orientation by the same Y angle
      keyframes.push({{
        t: (i / N) * ORBIT_S,
        pos: [p.x, p.y, p.z],
        quat: [q.x, q.y, q.z, q.w],
        fov: _origCamFov,
      }});
    }}
    return {{
      id: 'orbit', name: 'Programmatic Orbit',
      loop: false, smoothness: 1.0, play_speed: 1.0,
      keyframes,
    }};
  }}

  async function _runOrbitBench() {{
    // Defensive cleanup — if a previous bench is still active or a previous
    // path-player is still ticking the camera, stop them cleanly first.
    // Without this, rapid re-clicks ran the new orbit's setup while the old
    // orbit was still driving the camera, sometimes producing what looked
    // like "no rotation" on subsequent presses.
    if (_benchActive) _benchStop();
    if (_player) stopPath();

    // Reset the camera to its initial pose so the orbit's first-keyframe
    // snap doesn't depend on where the user has flown off to.
    camera.position.copy(_origCamPos);
    camera.quaternion.copy(_origCamQuat);
    camera.fov = _origCamFov;
    camera.updateProjectionMatrix();
    controls.target.copy(_origTarget);
    controls.update();

    // Immediate visual feedback: light the button up *now* so the user knows
    // their click registered. We update to "Warming…" during the 2 s
    // pre-load, then _benchStart will flip it to "Stop" when recording
    // actually begins.
    benchBtn.classList.add('recording');
    benchBtn.textContent = 'Warming…';

    console.info('[bench] orbit launch');
    const orbitPath = _buildOrbitPath();
    // Snap to the first keyframe + give pages 2 s to warm-load that view.
    const player0 = buildPlayer(orbitPath);
    if (player0) {{
      const s = sampleAt(player0, 0);
      camera.position.set(s.pos[0], s.pos[1], s.pos[2]);
      camera.quaternion.set(s.quat[0], s.quat[1], s.quat[2], s.quat[3]);
      camera.fov = s.fov;
      camera.updateProjectionMatrix();
    }}
    await new Promise(r => setTimeout(r, 2000));
    // Start recorder + player using the same orbit path object (so the
    // recorder's snapshot captures the orbit params at the right time).
    _benchStart({{ mode: 'path', pathId: 'orbit', duration: Infinity }});
    _player = buildPlayer(orbitPath);
    _t0 = performance.now();
    _activePathId = 'orbit';
    controls.enabled = false;
  }}

  // Probe / teleport-load bench: snap to each authored probe_view, then WAIT
  // until streaming actually settles for that pose (fetchers idle + active
  // splat count + resident pages stable for SETTLE_WIN_MS), recording the
  // per-pose load-in time, then snap to the next. A max-wait cap means a pose
  // that never fully resolves (e.g. phone pool < working set) still records
  // (settled:false) and the run continues. Each pose is pinned via a constant
  // 2-keyframe hold player so it inherits every robust-bench guarantee
  // (camera ownership via _player, the controls.update() clobber-gate, the
  // monotonic recorder, the camera self-check). Poses from cfg.probe_views
  // (authored via Set-start-view); falls back to a 6-pose orbit-ring around
  // the start-view so it is never empty.
  function _probeViews() {{
    let views = Array.isArray(cfg.probe_views)
      ? cfg.probe_views.filter(v => v && Array.isArray(v.pos) && Array.isArray(v.quat) && v.quat.length === 4)
      : [];
    if (views.length < 1) {{
      const c = _origTarget.clone(), off = _origCamPos.clone().sub(c);
      if (off.length() < 0.5) off.set(0, 1, -3);
      const upY = new THREE.Vector3(0, 1, 0);
      views = [];
      for (let k = 0; k < 6; k++) {{
        const rot = new THREE.Quaternion().setFromAxisAngle(upY, (k / 6) * Math.PI * 2);
        const p = off.clone().applyQuaternion(rot).add(c);
        const q = rot.clone().multiply(_origCamQuat);
        views.push({{ pos: [p.x, p.y, p.z], quat: [q.x, q.y, q.z, q.w], fov: _origCamFov }});
      }}
      console.info('[bench] probe: no cfg.probe_views — using 6-pose orbit-ring fallback');
    }}
    return views.map(v => ({{
      pos: [v.pos[0], v.pos[1], v.pos[2]],
      quat: [v.quat[0], v.quat[1], v.quat[2], v.quat[3]],
      fov: (typeof v.fov === 'number' ? v.fov : _origCamFov),
    }}));
  }}

  // A constant 2-keyframe hold player: the spline of two identical endpoints
  // is a fixed pose, so the render loop pins the camera at `v`. The huge,
  // non-loop duration means it never auto-ends → no premature stopPath().
  function _probeHoldPlayer(v) {{
    return buildPlayer({{
      id: 'probe', name: 'Probe hold', loop: false, smoothness: 0.0, play_speed: 1.0,
      keyframes: [
        {{ t: 0,   pos: v.pos, quat: v.quat, fov: v.fov }},
        {{ t: 1e6, pos: v.pos, quat: v.quat, fov: v.fov }},
      ],
    }});
  }}

  // Resolve when the pager has been quiet (no active fetchers, active-splat
  // count and resident-page count both unchanged) for SETTLE_WIN_MS, or when
  // MAX_WAIT_MS elapses. MIN_LATENCY_MS ignores the first instants after a
  // teleport so the pre-reaction "looks quiet" window can't false-positive.
  // NOTE: fetchPriority.length is deliberately NOT a drain signal — it is the
  // desired LoD working-set size and stays ~150-200 (desktop) / ~76 (phone)
  // even when fully loaded (verified from real traces); the true done signal
  // is fetchers idle + activeSplats plateaued + pagesResident stable.
  // "Loaded" must mean VISUALLY converged, not "splat count hit budget":
  // Spark refines coarse→fine after a teleport and that swap is roughly
  // count-neutral, so activeSplats plateaus while the image is still
  // sharpening (user-reported: "moves on although the image is all blurry").
  // Gate on true quiescence: no active fetch, no decode backlog, and the LoD
  // working-set size + resident pages + active-splat count ALL unchanged,
  // held for SETTLE_WIN_MS. NOTE: spark.current.mappingVersion is deliberately
  // NOT in the gate — the v14 contact sheet proved it keeps ticking (minor
  // re-map / re-sort) even when the image is visually static, so gating on it
  // never settles (every pose hit MAX_WAIT while fully sharp). It is reported
  // (informational) only. The real done signal is fetch+decode idle while the
  // LoD selection (fetchPriority) and resident set have stopped moving.
  function _awaitPagerSettled() {{
    const SETTLE_WIN_MS = 1500, MAX_WAIT_MS = 16000, MIN_LATENCY_MS = 400;
    const EPS_SPLATS = 1500;
    const t0 = performance.now();
    return new Promise(resolve => {{
      let lSp = -1, lPr = -1, lFp = -1, stableSince = null;
      const iv = setInterval(() => {{
        const nowM = performance.now(), el = nowM - t0;
        const pager = spark.pager;
        const fa = pager ? (pager.fetchers?.length || 0) : 0;
        const fd = pager ? (pager.fetched?.length || 0) : 0;
        const fp = pager ? (pager.fetchPriority?.length || 0) : 0;
        const pr = pager ? (pager.maxPages - (pager.pageFreelist?.length || 0)) : 0;
        const spc = spark.activeSplats || 0;
        const mv = (spark.current && typeof spark.current.mappingVersion === 'number')
          ? spark.current.mappingVersion : -1;
        const quiet = fa === 0 && fd === 0 && lSp >= 0 &&
          Math.abs(spc - lSp) <= EPS_SPLATS && pr === lPr && fp === lFp;
        lSp = spc; lPr = pr; lFp = fp;
        const fin = (ms, settled) => {{
          clearInterval(iv);
          resolve({{ settled, loadInMs: Math.round(ms), splats: spc, pages: pr, mv: mv }});
        }};
        if (!_benchActive) return fin(el, false);            // user pressed Stop
        if (el >= MAX_WAIT_MS) return fin(MAX_WAIT_MS, false);
        if (el < MIN_LATENCY_MS) {{ stableSince = null; return; }}
        if (quiet) {{
          if (stableSince == null) stableSince = nowM;
          if (nowM - stableSince >= SETTLE_WIN_MS) return fin(stableSince - t0, true);
        }} else {{
          stableSince = null;
        }}
      }}, 100);
    }});
  }}

  // One-shot canvas grab, resolved INSIDE the render loop right after
  // renderer.render() in the same synchronous turn — the only way to read
  // valid pixels when the WebGLRenderer has preserveDrawingBuffer:false
  // (an async toDataURL() after the frame yields returns a blank canvas).
  let _capReq = null;
  function _captureFrame() {{
    return new Promise(res => {{
      let done = false;
      const to = setTimeout(() => {{ if (!done) {{ done = true; _capReq = null; res(null); }} }}, 1500);
      _capReq = (dataUrl) => {{ if (done) return; done = true; clearTimeout(to); res(dataUrl); }};
    }});
  }}

  // Assemble the per-pose screenshots into ONE contact-sheet JPEG (a grid,
  // each tile labelled pose# · load-in ms · splats, green=settled red=timed
  // out) and download it. Lets the user SEE what "loaded" looked like at
  // every pose — ground truth, independent of the settle heuristic.
  function _probeSheet(shots, per, labelFn, kind) {{
    kind = kind || 'probe';
    const valid = shots.map((s, i) => ({{ s: s, p: per[i] }})).filter(o => o.s);
    if (!valid.length) {{ console.warn('[bench] ' + kind + ': no screenshots captured'); return; }}
    const cols = Math.ceil(Math.sqrt(valid.length));
    const rows = Math.ceil(valid.length / cols);
    const TW = 520, pad = 8, lab = 26;
    const imgs = []; let loaded = 0;
    valid.forEach((o, k) => {{
      const im = new Image();
      im.onload = im.onerror = () => {{ loaded++; if (loaded === valid.length) _draw(); }};
      im.src = o.s; imgs[k] = im;
    }});
    function _draw() {{
      const i0 = imgs[0];
      const ar = (i0.naturalHeight && i0.naturalWidth) ? (i0.naturalHeight / i0.naturalWidth) : 0.5;
      const TH = Math.round(TW * ar);
      const cw = TW + pad * 2, ch = TH + lab + pad * 2;
      const cv = document.createElement('canvas');
      cv.width = cols * cw; cv.height = rows * ch;
      const g = cv.getContext('2d');
      g.fillStyle = '#111'; g.fillRect(0, 0, cv.width, cv.height);
      g.font = '14px monospace'; g.textBaseline = 'middle';
      valid.forEach((o, k) => {{
        const cx = (k % cols) * cw, cy = Math.floor(k / cols) * ch;
        try {{ g.drawImage(imgs[k], cx + pad, cy + pad, TW, TH); }} catch (e) {{}}
        const p = o.p;
        const L = labelFn ? labelFn(p) : {{
          text: 'P' + p.i + ' · ' + p.loadInMs + ' ms · ' + (p.splats / 1e6).toFixed(2) + 'M' +
            (p.settled ? '' : ' · TIMEOUT'),
          ok: !!p.settled,
        }};
        g.fillStyle = L.ok ? '#0a8f3c' : '#cc2b2b';
        g.fillRect(cx + pad, cy + pad + TH, TW, lab);
        g.fillStyle = '#fff';
        g.fillText(L.text, cx + pad + 6, cy + pad + TH + lab / 2);
      }});
      const fn = kind + '-sheet-' + _benchTrace.config.tier + '-' + Date.now() + '.jpg';
      cv.toBlob(b => {{
        if (!b) {{ console.warn('[bench] probe sheet toBlob failed'); return; }}
        const u = URL.createObjectURL(b);
        const a = document.createElement('a');
        a.href = u; a.download = fn; document.body.appendChild(a); a.click();
        setTimeout(() => {{ a.remove(); URL.revokeObjectURL(u); }}, 1000);
        console.info('[bench] probe contact sheet downloaded:', fn, valid.length, 'shots');
      }}, 'image/jpeg', 0.8);
    }}
  }}

  async function _runProbeBench() {{
    if (_benchActive) _benchStop();
    if (_player) stopPath();
    camera.position.copy(_origCamPos);
    camera.quaternion.copy(_origCamQuat);
    camera.fov = _origCamFov;
    camera.updateProjectionMatrix();
    controls.target.copy(_origTarget);
    controls.update();
    benchBtn.classList.add('recording');
    benchBtn.textContent = 'Warming…';
    const views = _probeViews();
    console.info('[bench] probe launch —', views.length, 'poses (adaptive wait-until-loaded)');
    // Pre-snap to pose 0 so the warmup loads the first pose, not the start view.
    const v0 = views[0];
    camera.position.set(v0.pos[0], v0.pos[1], v0.pos[2]);
    camera.quaternion.set(v0.quat[0], v0.quat[1], v0.quat[2], v0.quat[3]);
    camera.fov = v0.fov;
    camera.updateProjectionMatrix();
    await new Promise(r => setTimeout(r, 2000));
    _benchStart({{ mode: 'probe', pathId: 'probe', duration: Infinity }});
    _activePathId = 'probe';
    controls.enabled = false;
    const perPose = [], shots = [];
    for (let i = 0; i < views.length; i++) {{
      if (!_benchActive) break;                  // user pressed Stop mid-run
      _player = _probeHoldPlayer(views[i]);      // render loop pins camera here
      _t0 = performance.now();
      benchBtn.textContent = 'Probe ' + (i + 1) + '/' + views.length;
      const r = await _awaitPagerSettled();
      perPose.push({{ i: i, pos: views[i].pos, settled: r.settled,
        loadInMs: r.loadInMs, splats: r.splats, pages: r.pages }});
      // Grab the canvas at this pose (camera still pinned here) so the
      // contact sheet shows exactly what "loaded" looked like.
      let shot = null;
      try {{ shot = await _captureFrame(); }} catch (e) {{}}
      shots.push(shot);
      console.info('[bench] probe pose ' + (i + 1) + '/' + views.length +
        ' — load-in ' + r.loadInMs + ' ms' +
        (r.settled ? '' : ' (TIMED OUT — not fully resolved)') +
        ' @ ' + r.splats + ' splats' + (shot ? '' : ' [no screenshot]'));
    }}
    if (_benchActive) {{
      const got = perPose.filter(p => p.settled).map(p => p.loadInMs);
      _benchTrace.probe = {{
        poses: perPose.length,
        settled: perPose.filter(p => p.settled).length,
        timedOut: perPose.filter(p => !p.settled).length,
        loadInMs_mean: got.length ? Math.round(got.reduce((a, b) => a + b, 0) / got.length) : null,
        loadInMs_max: got.length ? Math.max(...got) : null,
        screenshots: shots.filter(Boolean).length,
        perPose: perPose,
      }};
      try {{
        window.__probeLoadIn = _benchTrace.probe;
        if (console.table) console.table(perPose);
      }} catch (e) {{}}
      _probeSheet(shots, perPose);   // builds + downloads the contact-sheet JPEG
      _benchStop();                  // downloads the JSON trace
    }}
  }}

  // Bench #2 — "rotate": teleport to each pose then OSCILLATE the look ±ROT_DEG
  // around world-Y for ROT_S s WHILE the new detail streams in, recording the
  // per-frame dt + longtasks + fetch state. Measures the *frame-time
  // experience while loading during motion* (the M1 14fps/82-longtask
  // scenario) — complements ?bench=probe (time-to-loaded). Looped path so it
  // never auto-stopPath()s between poses (start==end ⇒ seamless).
  function _buildRotatePath(v, ROT_S, ROT_DEG, N) {{
    const baseQ = new THREE.Quaternion(v.quat[0], v.quat[1], v.quat[2], v.quat[3]);
    const upY = new THREE.Vector3(0, 1, 0);
    const keyframes = [];
    for (let k = 0; k <= N; k++) {{
      const f = k / N;
      const deg = ROT_DEG * Math.sin(f * Math.PI * 2);   // 0 → +ROT → 0 → -ROT → 0
      const rot = new THREE.Quaternion().setFromAxisAngle(upY, deg * Math.PI / 180);
      const q = rot.clone().multiply(baseQ);
      keyframes.push({{ t: f * ROT_S, pos: [v.pos[0], v.pos[1], v.pos[2]],
        quat: [q.x, q.y, q.z, q.w], fov: v.fov }});
    }}
    return {{ id: 'rotate', name: 'Probe rotate (yaw-while-loading)',
      loop: true, smoothness: 1.0, play_speed: 1.0, keyframes }};
  }}

  async function _runRotateBench() {{
    if (_benchActive) _benchStop();
    if (_player) stopPath();
    camera.position.copy(_origCamPos);
    camera.quaternion.copy(_origCamQuat);
    camera.fov = _origCamFov;
    camera.updateProjectionMatrix();
    controls.target.copy(_origTarget);
    controls.update();
    benchBtn.classList.add('recording');
    benchBtn.textContent = 'Warming…';
    const views = _probeViews();
    const ROT_S = 6, ROT_DEG = 55, N = 24;
    console.info('[bench] rotate launch —', views.length, 'poses (yaw-while-loading, ' + ROT_S + ' s/pose)');
    const v0 = views[0];
    camera.position.set(v0.pos[0], v0.pos[1], v0.pos[2]);
    camera.quaternion.set(v0.quat[0], v0.quat[1], v0.quat[2], v0.quat[3]);
    camera.fov = v0.fov;
    camera.updateProjectionMatrix();
    await new Promise(r => setTimeout(r, 2000));
    _benchStart({{ mode: 'rotate', pathId: 'rotate', duration: Infinity }});
    _activePathId = 'rotate';
    controls.enabled = false;
    const perPose = [], shots = [];
    for (let i = 0; i < views.length; i++) {{
      if (!_benchActive) break;
      _player = buildPlayer(_buildRotatePath(views[i], ROT_S, ROT_DEG, N));
      _t0 = performance.now();
      const wStart = performance.now() - _benchT0;     // recorder-clock window
      benchBtn.textContent = 'Rotate ' + (i + 1) + '/' + views.length;
      await new Promise(r => setTimeout(r, ROT_S * 1000));
      const wEnd = performance.now() - _benchT0;
      let shot = null;
      try {{ shot = await _captureFrame(); }} catch (e) {{}}
      shots.push(shot);
      const fr = _benchTrace.frames.filter(f => f.t >= wStart && f.t <= wEnd && f.dt > 0 && f.dt < 5000);
      const dts = fr.map(f => f.dt).sort((a, b) => a - b);
      const nn = dts.length;
      const pct = q => nn ? dts[Math.min(nn - 1, Math.floor(nn * q))] : null;
      const lt = _benchTrace.longtasks.filter(t => t.t >= wStart && t.t <= wEnd).length;
      const jankFetch = fr.filter(f => f.dt > 50 && f.fetchersActive > 0).length;
      perPose.push({{
        i: i, pos: views[i].pos, frames: nn,
        fps_mean: nn ? Math.round(1000 / (dts.reduce((a, b) => a + b, 0) / nn)) : null,
        dt_p50: pct(0.50), dt_p95: pct(0.95), dt_p99: pct(0.99),
        dt_max: nn ? dts[nn - 1] : null, longtasks: lt, jankWhileFetching: jankFetch,
      }});
      const pp = perPose[i];
      console.info('[bench] rotate pose ' + (i + 1) + '/' + views.length +
        ' — ' + pp.fps_mean + ' fps · p99 ' + pp.dt_p99 + ' ms · ' + lt +
        ' longtasks · ' + jankFetch + ' jank-while-fetching' + (shot ? '' : ' [no screenshot]'));
    }}
    if (_benchActive) {{
      const fps = perPose.map(p => p.fps_mean).filter(x => x != null);
      _benchTrace.rotate = {{
        poses: perPose.length, rotS: ROT_S, rotDeg: ROT_DEG,
        fps_mean: fps.length ? Math.round(fps.reduce((a, b) => a + b, 0) / fps.length) : null,
        dt_p99_max: Math.max(...perPose.map(p => p.dt_p99 || 0)),
        longtasks_total: perPose.reduce((a, p) => a + (p.longtasks || 0), 0),
        jankWhileFetching_total: perPose.reduce((a, p) => a + (p.jankWhileFetching || 0), 0),
        screenshots: shots.filter(Boolean).length, perPose: perPose,
      }};
      try {{
        window.__rotateStats = _benchTrace.rotate;
        if (console.table) console.table(perPose);
      }} catch (e) {{}}
      _probeSheet(shots, perPose, p => ({{
        text: 'P' + p.i + ' · ' + p.fps_mean + ' fps · p99 ' + Math.round(p.dt_p99) + 'ms · ' +
          p.longtasks + 'LT · ' + p.jankWhileFetching + ' jank',
        ok: (p.fps_mean != null && p.fps_mean >= 50 && (p.dt_p99 || 0) < 100),
      }}), 'rotate');
      _benchStop();
    }}
  }}

  // Cold-load benchmark: start the recorder + longtask observer at the
  // EARLIEST point (no preload wait), capture the full cold fetch+decode+
  // upload fill — the phase the user reported as the worst stutter ("gets
  // better the longer it's open"), which the orbit/dolly benches miss
  // because they only start after preload — then auto-orbit on top, so one
  // trace = cold fill THEN motion with per-frame times + longtasks
  // throughout. This is the instrument that proves the stutter delta.
  async function _runColdBench() {{
    if (_benchActive) _benchStop();
    if (_player) stopPath();
    benchBtn.classList.add('recording');
    benchBtn.textContent = 'COLD…';
    console.info('[bench] cold launch — recording from load through the fill');
    _benchStart({{ mode: 'cold', duration: Infinity }});
    // Record the cold fetch+decode+upload fill, then exercise motion on top.
    await new Promise(r => setTimeout(r, 9000));
    if (!_benchActive) return;
    const orbitPath = _buildOrbitPath();
    _player = buildPlayer(orbitPath);
    _t0 = performance.now();
    _activePathId = 'orbit';
    controls.enabled = false;
  }}

  // Programmatic dolly-in: travel from the initial pose straight toward the
  // orbit target, ending close to a surface, so the LoD must resolve
  // progressively finer chunks. This is the "zoom in to fine detail" stress
  // (the literal "new detail loads in too slow" scenario) that the orbit
  // (fixed radius) does not exercise. Anchored to the initial pose so every
  // run is the identical world-space dolly.
  function _buildDollyPath() {{
    const center = _origTarget.clone();
    const start = _origCamPos.clone();
    const dir = start.clone().sub(center);
    const startDist = Math.max(dir.length(), 1e-3);
    dir.normalize();
    const endDist = Math.max(startDist * 0.12, 1.5);
    // Hold the AUTHORED look orientation. It already frames the subject for
    // THIS scene's coordinate frame; moving along the camera→target axis
    // keeps the subject centred as we close in. The old tmp.lookAt(center)
    // assumed +Y up and could point at sky on rotated-frame scenes.
    const q = _origCamQuat;
    const N = 36, DOLLY_S = 24;
    const keyframes = [];
    for (let i = 0; i <= N; i++) {{
      const f = i / N;
      const dist = startDist + (endDist - startDist) * f;
      const x = center.x + dir.x * dist;
      const y = center.y + dir.y * dist;
      const z = center.z + dir.z * dist;
      keyframes.push({{
        t: f * DOLLY_S,
        pos: [x, y, z],
        quat: [q.x, q.y, q.z, q.w],
        fov: _origCamFov,
      }});
    }}
    return {{ id: 'dolly', name: 'Programmatic Dolly-In',
      loop: false, smoothness: 1.0, play_speed: 1.0, keyframes }};
  }}

  async function _runDollyBench() {{
    if (_benchActive) _benchStop();
    if (_player) stopPath();
    camera.position.copy(_origCamPos);
    camera.quaternion.copy(_origCamQuat);
    camera.fov = _origCamFov;
    camera.updateProjectionMatrix();
    controls.target.copy(_origTarget);
    controls.update();
    benchBtn.classList.add('recording');
    benchBtn.textContent = 'Warming…';
    console.info('[bench] dolly launch');
    const dollyPath = _buildDollyPath();
    const player0 = buildPlayer(dollyPath);
    if (player0) {{
      const s = sampleAt(player0, 0);
      camera.position.set(s.pos[0], s.pos[1], s.pos[2]);
      camera.quaternion.set(s.quat[0], s.quat[1], s.quat[2], s.quat[3]);
      camera.fov = s.fov;
      camera.updateProjectionMatrix();
    }}
    await new Promise(r => setTimeout(r, 2000));
    _benchStart({{ mode: 'path', pathId: 'dolly', duration: Infinity }});
    _player = buildPlayer(dollyPath);
    _t0 = performance.now();
    _activePathId = 'dolly';
    controls.enabled = false;
  }}

  async function _runNamedPathBench(pathId) {{
    if (_benchActive) _benchStop();
    if (_player) stopPath();
    const p = cameraPaths.find(x => x.id === pathId);
    if (!p) {{
      console.warn('[bench] path "' + pathId + '" not found; running 30 s static instead');
      _benchStart({{ mode: 'static' }});
      return;
    }}
    benchBtn.classList.add('recording');
    benchBtn.textContent = 'Warming…';
    console.info('[bench] path launch: "' + pathId + '"');
    try {{
      const tmpPlayer = buildPlayer(p);
      if (tmpPlayer) {{
        const s = sampleAt(tmpPlayer, 0);
        camera.position.set(s.pos[0], s.pos[1], s.pos[2]);
        camera.quaternion.set(s.quat[0], s.quat[1], s.quat[2], s.quat[3]);
        camera.fov = s.fov;
        camera.updateProjectionMatrix();
      }}
    }} catch (e) {{ console.warn('[bench] could not pre-snap camera', e); }}
    await new Promise(r => setTimeout(r, 2000));
    _benchStart({{ mode: 'path', pathId: pathId, duration: Infinity }});
    startPath(pathId);
  }}

  // What the button does. Toggle: if recording → stop. Otherwise run the mode
  // implied by the URL (so a page loaded with ?bench=orbit re-runs the orbit
  // on every subsequent button press, not a static recorder).
  async function _benchButtonClick() {{
    if (_benchActive) return _benchStop();
    // Dispatch on the in-viewport dropdown (pre-synced to ?bench=); fall back
    // to the URL param, then orbit. ?bench=1 keeps the static recorder for the
    // "user drives the camera" case.
    const _mode = (benchModeSel && benchModeSel.value) ? benchModeSel.value : (BENCH_AUTO || 'orbit');
    if (_mode === 'orbit') return _runOrbitBench();
    if (_mode === 'dolly') return _runDollyBench();
    if (_mode === 'cold') return _runColdBench();
    if (_mode === 'probe') return _runProbeBench();
    if (_mode === 'rotate') return _runRotateBench();
    if (_mode === '1' || _mode === 'static') return _benchStart({{ mode: 'static' }});
    return _runNamedPathBench(_mode);   // a named camera-path id
  }}

  // ---- ?bench=<value> auto-trigger (one-shot on page load) ----
  if (BENCH_AUTO) {{
    (async () => {{
      if (splat.initialized && typeof splat.initialized.then === 'function') {{
        try {{ await splat.initialized; }} catch (e) {{}}
      }}
      // ?bench=cold: start recording NOW (spark/pager exist post-init),
      // BEFORE the preload wait, so the trace captures the cold
      // fetch+decode+upload fill — the worst-stutter phase the user flagged.
      if (BENCH_AUTO === 'cold') {{ _runColdBench(); return; }}
      // Wait for the front-load phase to finish hiding the loading panel —
      // otherwise the orbit fires while the canvas is still occluded and the
      // user just sees a "stuck" loading screen instead of rotation.
      // _preloadDonePromise is set up in the loading-hide IIFE below.
      if (typeof _preloadDonePromise !== 'undefined') {{
        try {{ await _preloadDonePromise; }} catch (e) {{}}
      }}
      // Small extra stabilization beat after preload (helps decode queue drain).
      await new Promise(r => setTimeout(r, 500));
      if (BENCH_AUTO === '1') {{
        console.info('[bench] auto-trigger: static 30 s');
        _benchStart({{ mode: 'static' }});
      }} else if (BENCH_AUTO === 'orbit') {{
        await _runOrbitBench();
      }} else if (BENCH_AUTO === 'dolly') {{
        await _runDollyBench();
      }} else if (BENCH_AUTO === 'probe') {{
        await _runProbeBench();
      }} else if (BENCH_AUTO === 'rotate') {{
        await _runRotateBench();
      }} else {{
        await _runNamedPathBench(BENCH_AUTO);
      }}
    }})();
  }}

  // ---- Splat budget dropdown ----
  // Spark exposes the budget as a live-mutable property on SparkRenderer:
  //   spark.lodSplatCount   - hard target for total visible splats
  // The default is auto-picked from device tier (see pickDefaultBudget below);
  // the user can override via the dropdown at runtime.
  const budgetEl = document.getElementById('splat-budget');
  function applySplatBudget(n) {{
    // n=0 → "No limit": pass a very large number so Spark stops capping.
    spark.lodSplatCount = (n > 0) ? n : 50_000_000;
    // Keep the on-screen <select> consistent with the ACTUAL budget no
    // matter who set it — device-tier pick, the Apple-Silicon profile,
    // ?budget=, or any future foveation/tiering code. selectClosestBudget
    // snaps the dropdown to the nearest option ≤ n (it's a hoisted function
    // decl; applySplatBudget is never called before it's defined). n=0
    // ("No limit") has no matching option, so leave the dropdown as-is.
    // Setting .value programmatically does NOT fire 'change' → no recursion
    // with the handler below. This makes applySplatBudget the single
    // source of truth for UI/screenshot self-consistency (#50).
    if (n > 0) selectClosestBudget(n);
  }}
  budgetEl.addEventListener('change', () => applySplatBudget(parseInt(budgetEl.value, 10)));

  // ---- Initial splat budget pick from device tier ----
  // Static, measured-comfort targets (2026-05-15, no adaptive controller):
  //   • phone   500 K — iPhone 13 mini ≈ 40 fps
  //   • tablet  1 M   — between phone and desktop
  //   • desktop 1.5 M — M1 Pro ≈ 30 fps (acceptable on 120 Hz ProMotion),
  //                     discrete GPUs comfortably 60 fps; dropdown for more.
  // This is spark.lodSplatCount: the LoD picks more detail in the
  // foreground and less behind to hit this visible-splat target, drawing
  // from the (separate) maxPagedSplats resident pool.
  function pickDefaultBudget() {{
    const {{ tier }} = _deviceProfile;
    const target = _deviceProfile.appleSilicon ? 1_000_000 :
                   tier === 'phone' ? 500_000 :
                   tier === 'tablet' ? 1_000_000 :
                   2_000_000;  // discrete-GPU desktop (auto-focus makes the
                               // total budget largely irrelevant for the
                               // focal region — verified 2026-05-15)
    console.info('[Splatpipe] device tier:', tier,
      '| splat budget:', target.toLocaleString());
    return target;
  }}

  // Snap the auto-picked target to the nearest dropdown option ≤ target
  // (conservative — never exceed what we picked for the device).
  function selectClosestBudget(target) {{
    const options = Array.from(budgetEl.options)
      .map(o => ({{ el: o, v: parseInt(o.value, 10) }}))
      .filter(o => o.v > 0)
      .sort((a, b) => a.v - b.v);
    let pick = options[0];
    for (const o of options) {{
      if (o.v <= target) pick = o;
      else break;
    }}
    budgetEl.value = pick.el.value;
    return parseInt(pick.el.value, 10);
  }}

  // ?budget=N URL override pins the splat budget for the session — useful
  // for prescribed A/B runs ("run 1M on iPhone and 2M on M1 Pro, same path").
  // Overrides both auto-pick AND the dropdown's snap-to-closest behavior.
  const URL_BUDGET = parseInt(new URLSearchParams(location.search).get('budget'), 10);

  // Initial apply
  let _initialBudget;
  if (Number.isFinite(URL_BUDGET) && URL_BUDGET >= 0) {{
    _initialBudget = URL_BUDGET;
    // Reflect the chosen value in the dropdown if a matching option exists.
    selectClosestBudget(URL_BUDGET);
    console.info('[Splatpipe] budget pinned from URL:', URL_BUDGET);
  }} else {{
    _initialBudget = selectClosestBudget(pickDefaultBudget());
  }}
  applySplatBudget(_initialBudget);

  // ---- Frame loop ----
  const cam = cfg.camera || _DEFAULTS.camera;
  const splatCountEl = document.getElementById('splat-count');

  // FPS counter — count frames over a sliding 1-second window so the number
  // is stable. Returns 0 until the first window completes.
  let _fpsFrames = 0, _fpsStart = performance.now(), _fpsLast = 0;
  function _fpsTick() {{
    _fpsFrames++;
    const now = performance.now();
    if (now - _fpsStart >= 1000) {{
      _fpsLast = Math.round(_fpsFrames * 1000 / (now - _fpsStart));
      _fpsFrames = 0;
      _fpsStart = now;
    }}
    return _fpsLast;
  }}

  // ---- Static splat budget (no adaptive controller) ----
  // We deliberately do NOT scale lodSplatScale at runtime. Research
  // (2026-05-15) confirmed no shipping splat viewer uses an adaptive FPS
  // loop — they ship fixed per-device budgets, and the runtime % display
  // was confusing without buying real quality. lodSplatScale stays at its
  // config / Spark default; the per-tier lodSplatCount picked above is the
  // only quality lever and it is set exactly once. Bench mode, orbit
  // prefetch and the preload bar below are unaffected.

  // ---- Benchmark recorder ----
  // Click "Bench" button → record 30 s of per-frame metrics + longtask events
  // → download a JSON trace. Per-frame: dt, splats, pages resident, fetchers
  // active, GPU time (if EXT_disjoint_timer_query_webgl2 is available). The
  // trace is self-describing — it carries device + viewer config so we can
  // compare runs across machines without extra metadata.
  const BENCH_DURATION_MS = 30_000;
  let _benchActive = false;
  let _benchEndTime = 0;
  let _benchTrace = null;
  let _benchLastT = 0;
  let _benchLongTaskObserver = null;
  let _benchAutoMode = null;     // 'static' | 'path' | null
  let _benchAutoPathId = null;   // path id when mode === 'path'
  let _benchT0 = 0;  // monotonic recorder clock base — fixes the -Infinity/null `t`
  // Camera-motion self-check (resilience). A bench that does not actually
  // move the camera (controls clobber, null player, degenerate path, race)
  // must NEVER pass silently again. Accumulated in the _player block, verdict
  // in _benchStop → trace.cameraMoved/cameraTravel + loud console.error +
  // window.__benchResult / 'bench:done' event for deterministic assertion.
  const _benchCam = {{
    armed: false, samples: 0, travel: 0,
    first: new THREE.Vector3(), firstQ: new THREE.Quaternion(),
    prev: new THREE.Vector3(), prevQ: new THREE.Quaternion(),
  }};
  function _benchCamArm() {{
    _benchCam.armed = true; _benchCam.samples = 0; _benchCam.travel = 0;
    _benchCam.first.copy(camera.position); _benchCam.firstQ.copy(camera.quaternion);
    _benchCam.prev.copy(camera.position); _benchCam.prevQ.copy(camera.quaternion);
  }}
  function _benchCamSample() {{
    if (!_benchCam.armed) return;
    const dp = camera.position.distanceTo(_benchCam.prev);
    const qd = Math.abs(
      camera.quaternion.x*_benchCam.prevQ.x + camera.quaternion.y*_benchCam.prevQ.y +
      camera.quaternion.z*_benchCam.prevQ.z + camera.quaternion.w*_benchCam.prevQ.w);
    _benchCam.travel += dp + 2 * Math.acos(Math.min(1, qd));
    _benchCam.samples++;
    _benchCam.prev.copy(camera.position); _benchCam.prevQ.copy(camera.quaternion);
  }}
  const benchBtn = document.getElementById('bench-btn');
  // Bench-mode dropdown: pre-select it from ?bench= so a deep-linked mode and
  // the button stay in sync; the button then runs whatever is selected.
  const benchModeSel = document.getElementById('bench-mode');
  if (benchModeSel && BENCH_AUTO && BENCH_AUTO !== '1') {{
    for (const o of benchModeSel.options) {{ if (o.value === BENCH_AUTO) {{ benchModeSel.value = BENCH_AUTO; break; }} }}
  }}

  // GPU timing: pooled EXT_disjoint_timer_query_webgl2 (4 in flight). Returns
  // null on browsers without the extension (iOS Safari with the flag off,
  // Brave hardened, etc.) — the rest of the trace is still useful.
  const _gl = renderer.getContext();
  const _gpuExt = _gl?.getExtension?.('EXT_disjoint_timer_query_webgl2');
  const _gpuPool = _gpuExt ? Array.from({{ length: 4 }}, () => _gl.createQuery()) : null;
  let _gpuFrame = 0;
  let _gpuLastNs = 0;
  function _gpuBeginFrame() {{
    if (!_gpuExt) return;
    _gl.beginQuery(_gpuExt.TIME_ELAPSED_EXT, _gpuPool[_gpuFrame % 4]);
  }}
  function _gpuEndFrame() {{
    if (!_gpuExt) return;
    _gl.endQuery(_gpuExt.TIME_ELAPSED_EXT);
    // Read a query that's been in flight for ~4 frames so the GPU has finished it.
    const readQ = _gpuPool[(_gpuFrame + 1) % 4];
    if (_gl.getQueryParameter(readQ, _gl.QUERY_RESULT_AVAILABLE)) {{
      const disjoint = _gl.getParameter(_gpuExt.GPU_DISJOINT_EXT);
      if (!disjoint) _gpuLastNs = _gl.getQueryParameter(readQ, _gl.QUERY_RESULT);
    }}
    _gpuFrame++;
  }}

  function _benchDeviceProfile() {{
    const dbg = _gl?.getExtension?.('WEBGL_debug_renderer_info');
    return {{
      ua: navigator.userAgent,
      platform: navigator.platform || '',
      cores: navigator.hardwareConcurrency ?? null,
      memGB: navigator.deviceMemory ?? null,
      dpr: window.devicePixelRatio,
      maxTouchPoints: navigator.maxTouchPoints,
      isBrave: !!navigator.brave,
      viewport: `${{window.innerWidth}}x${{window.innerHeight}}`,
      screen: `${{screen.width}}x${{screen.height}}`,
      webgl: _gl ? {{
        vendor: dbg ? _gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : _gl.getParameter(_gl.VENDOR),
        renderer: dbg ? _gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : _gl.getParameter(_gl.RENDERER),
        maxTexSize: _gl.getParameter(_gl.MAX_TEXTURE_SIZE),
        maxRbSize: _gl.getParameter(_gl.MAX_RENDERBUFFER_SIZE),
        maxVarying: _gl.getParameter(_gl.MAX_VARYING_VECTORS),
        gpuTiming: !!_gpuExt,
      }} : null,
    }};
  }}

  function _benchConfigSnapshot() {{
    return {{
      project: document.querySelector('#title h1')?.textContent || '',
      primaryAsset: PRIMARY_ASSET,
      stock: STOCK,
      paged: PAGED,
      tier: _deviceProfile.tier,
      benchAutoMode: _benchAutoMode,
      benchAutoPathId: _benchAutoPathId,
      adaptive: false,
      dprCap: _dprCap,
      shouldThrottleUploads: _shouldThrottleUploads,
      spark: {{
        lodSplatCount: spark.lodSplatCount,
        lodSplatScale: spark.lodSplatScale,
        lodRenderScale: spark.lodRenderScale,
        maxPagedSplats: spark.maxPagedSplats,
        numLodFetchers: spark.numLodFetchers,
        clipXY: spark.clipXY,
        minPixelRadius: spark.minPixelRadius,
        maxStdDev: spark.maxStdDev,
        minSortIntervalMs: spark.minSortIntervalMs,
      }},
      splat: {{
        maxSh: splat.maxSh,
      }},
    }};
  }}

  function _benchStart(opts) {{
    if (_benchActive) return _benchStop();
    opts = opts || {{}};
    _benchActive = true;
    _benchLastT = performance.now();
    _benchT0 = _benchLastT;          // monotonic clock base for per-frame `t`
    _benchCam.armed = false;          // re-arm fresh at motion start (in _player block)
    // Path-driven benches stop when the path ends (no auto-timer).
    _benchEndTime = opts.duration === Infinity
      ? Infinity
      : (_benchLastT + (opts.duration || BENCH_DURATION_MS));
    _benchAutoMode = opts.mode || null;
    _benchAutoPathId = opts.pathId || null;
    _benchTrace = {{
      createdAt: new Date().toISOString(),
      device: _benchDeviceProfile(),
      config: _benchConfigSnapshot(),
      durationS: BENCH_DURATION_MS / 1000,
      frames: [],
      longtasks: [],
      memory: {{
        startUsedMB: performance.memory ? (performance.memory.usedJSHeapSize / 1e6) : null,
        endUsedMB: null, peakUsedMB: null,
      }},
    }};
    // Long-task observer: fires for any main-thread block ≥ 50 ms (the canonical
    // jank threshold). Catches exactly the chunk-decode + upload spikes.
    try {{
      _benchLongTaskObserver = new PerformanceObserver((list) => {{
        for (const e of list.getEntries()) {{
          _benchTrace.longtasks.push({{ t: e.startTime - _benchT0, duration: e.duration, name: e.name }});
        }}
      }});
      _benchLongTaskObserver.observe({{ type: 'longtask', buffered: true }});
    }} catch (e) {{ /* Safari may throw on unknown types */ }}
    benchBtn.classList.add('recording');
    benchBtn.textContent = 'Stop';
    console.info('[bench] started, 30 s');
  }}

  function _benchTick(now) {{
    if (!_benchActive) return;
    const dt = now - _benchLastT;
    _benchLastT = now;
    const pager = spark.pager;
    _benchTrace.frames.push({{
      t: now - _benchT0,
      dt: dt,
      gpuMs: _gpuExt ? _gpuLastNs / 1e6 : null,
      splats: spark.activeSplats || 0,
      pagesResident: pager ? (pager.maxPages - (pager.pageFreelist?.length || 0)) : 0,
      fetchersActive: pager ? (pager.fetchers?.length || 0) : 0,
      fetchQueue: pager ? (pager.fetchPriority?.length || 0) : 0,
      lastTraverseMs: spark.lastTraverseTime || 0,
    }});
    if (performance.memory) {{
      const usedMB = performance.memory.usedJSHeapSize / 1e6;
      if (_benchTrace.memory.peakUsedMB == null || usedMB > _benchTrace.memory.peakUsedMB) _benchTrace.memory.peakUsedMB = usedMB;
    }}
    if (now >= _benchEndTime) _benchStop();
  }}

  function _benchStop() {{
    if (!_benchActive) return;
    _benchActive = false;
    const _hadPlayer = !!_player;
    if (_player) stopPath();   // camera halt ⇄ recorder stop ⇄ download coincide
    if (_benchLongTaskObserver) {{
      try {{ _benchLongTaskObserver.disconnect(); }} catch (e) {{}}
      _benchLongTaskObserver = null;
    }}
    if (performance.memory) {{
      _benchTrace.memory.endUsedMB = performance.memory.usedJSHeapSize / 1e6;
    }}
    // Compute a quick summary so the user (and we) see headline numbers in
    // the console without parsing the trace.
    const dts = _benchTrace.frames.map(f => f.dt).sort((a, b) => a - b);
    const n = dts.length;
    const summary = n ? {{
      frames: n,
      fps_mean: Math.round(1000 / (dts.reduce((a, b) => a + b, 0) / n)),
      ms_p50: dts[Math.floor(n * 0.50)],
      ms_p95: dts[Math.floor(n * 0.95)],
      ms_p99: dts[Math.min(n - 1, Math.floor(n * 0.99))],
      longtasks: _benchTrace.longtasks.length,
      splats_max: Math.max(..._benchTrace.frames.map(f => f.splats)),
    }} : {{ frames: 0 }};
    _benchTrace.summary = summary;
    console.info('[bench] done', summary);
    // ---- camera-motion self-check (resilience): never pass silently ----
    const _moving = (_benchAutoMode === 'path' || _benchAutoMode === 'cold' || _benchAutoMode === 'probe' || _benchAutoMode === 'rotate');
    const _net = _benchCam.samples ? camera.position.distanceTo(_benchCam.first) : 0;
    _benchTrace.cameraMoved = _moving ? (_benchCam.travel > 0.05 && _benchCam.samples > 5) : null;
    _benchTrace.cameraTravel = +(_benchCam.travel.toFixed(4));
    _benchTrace.cameraNetDisplacement = +(_net.toFixed(4));
    _benchTrace.cameraSamples = _benchCam.samples;
    _benchTrace.durationS = +(((performance.now() - _benchT0) / 1000).toFixed(2));
    _benchCam.armed = false;
    if (_moving && _benchTrace.cameraMoved === false) {{
      console.error('[bench] CAMERA DID NOT MOVE — bench INVALID. travel=' +
        _benchCam.travel.toFixed(4) + ' samples=' + _benchCam.samples + ' mode=' + _benchAutoMode +
        ' hadPlayer=' + _hadPlayer + ' controls.enabled=' + controls.enabled);
      try {{ benchBtn.classList.add('bench-error'); }} catch (e) {{}}
    }}
    try {{
      window.__benchResult = {{
        cameraMoved: _benchTrace.cameraMoved, cameraTravel: _benchTrace.cameraTravel,
        cameraNetDisplacement: _benchTrace.cameraNetDisplacement,
        frames: _benchTrace.frames.length,
        framesValidT: _benchTrace.frames.filter(f => Number.isFinite(f.t)).length,
        durationS: _benchTrace.durationS, mode: _benchAutoMode, fps_mean: summary.fps_mean || null,
        probe: _benchTrace.probe || null,
        rotate: _benchTrace.rotate || null,
      }};
      window.dispatchEvent(new CustomEvent('bench:done', {{ detail: window.__benchResult }}));
    }} catch (e) {{}}
    // Save: download as JSON.
    const fn = `bench-${{_benchTrace.config.tier}}-${{Date.now()}}.json`;
    const blob = new Blob([JSON.stringify(_benchTrace, null, 2)], {{ type: 'application/json' }});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = fn; document.body.appendChild(a); a.click();
    setTimeout(() => {{ a.remove(); URL.revokeObjectURL(url); }}, 1000);
    benchBtn.classList.remove('recording');
    benchBtn.textContent = 'Bench';
  }}
  benchBtn.addEventListener('click', _benchButtonClick);

  // ---- Set start view (Option A relay) ----
  // Capture the live camera as this scene's start view and emit a token
  // the user pastes to Claude, who runs `splatpipe set-start-view` to
  // write it into viewer-config.json on the CDN. No client-side secret;
  // the token carries only a camera pose. Round-trips cleanly because
  // the early camera block consumes start_view.pos/quat/fov/target the
  // same way it is captured here (same world frame as camera-paths).
  {{
    const _ssBtn = document.getElementById('setstart-btn');
    const _projName = (document.querySelector('#title h1') && document.querySelector('#title h1').textContent || 'scene').trim();
    const _slug = (_projName.replace(/[^A-Za-z0-9_-]+/g, '_').slice(0, 48)) || 'scene';
    const _esc = s => s.replace(/[&<>]/g, c => ({{ '&': '&amp;', '<': '&lt;', '>': '&gt;' }}[c]));
    function _b64url(obj) {{
      const b64 = btoa(unescape(encodeURIComponent(JSON.stringify(obj))));
      return b64.replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, '');
    }}
    const _r = n => Math.round(n * 1e5) / 1e5;
    function _ssClose() {{ const o = document.getElementById('ss-overlay'); if (o) o.remove(); }}
    _ssBtn.addEventListener('click', () => {{
      _ssClose();
      const pose = {{
        project: _projName,
        pos: [camera.position.x, camera.position.y, camera.position.z].map(_r),
        quat: [camera.quaternion.x, camera.quaternion.y, camera.quaternion.z, camera.quaternion.w].map(_r),
        target: [controls.target.x, controls.target.y, controls.target.z].map(_r),
        fov: _r(camera.fov),
      }};
      const token = 'SPV1:' + _slug + ':' + _b64url(pose);
      const ov = document.createElement('div');
      ov.id = 'ss-overlay';
      ov.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.55);font:14px system-ui,sans-serif;';
      const card = document.createElement('div');
      card.style.cssText = 'background:#1f1f24;color:#eee;max-width:520px;width:90%;padding:20px 22px;border-radius:12px;box-shadow:0 8px 40px rgba(0,0,0,.5);';
      card.innerHTML =
        '<div style="font-weight:600;font-size:16px;margin-bottom:6px;">Save this as the start view?</div>' +
        '<div style="opacity:.75;margin-bottom:14px;">The current camera becomes the opening shot for <b>' + _esc(_projName) +
        '</b> for everyone, once you send the token to Claude.</div>' +
        '<div style="display:flex;gap:10px;justify-content:flex-end;">' +
        '<button id="ss-cancel" class="quality-btn">Cancel</button>' +
        '<button id="ss-confirm" class="quality-btn" style="background:#2d6cdf;color:#fff;">Confirm</button></div>';
      ov.appendChild(card);
      document.body.appendChild(ov);
      ov.addEventListener('click', e => {{ if (e.target === ov) _ssClose(); }});
      card.querySelector('#ss-cancel').addEventListener('click', _ssClose);
      card.querySelector('#ss-confirm').addEventListener('click', () => {{
        let copied = false;
        try {{ if (navigator.clipboard && navigator.clipboard.writeText) {{ navigator.clipboard.writeText(token); copied = true; }} }} catch (e) {{}}
        card.innerHTML =
          '<div style="font-weight:600;font-size:16px;margin-bottom:6px;">' + (copied ? 'Copied to clipboard \\u2713' : 'Start-view token') + '</div>' +
          '<div style="opacity:.75;margin-bottom:10px;">Send this token to Claude on Telegram to save it for everyone:</div>' +
          '<textarea readonly style="width:100%;height:84px;box-sizing:border-box;background:#111;color:#9fd;border:1px solid #333;border-radius:8px;padding:8px;font:12px monospace;resize:none;"></textarea>' +
          '<div style="display:flex;gap:10px;justify-content:flex-end;margin-top:14px;">' +
          '<button id="ss-copy" class="quality-btn">Copy again</button>' +
          '<button id="ss-close" class="quality-btn" style="background:#2d6cdf;color:#fff;">Done</button></div>';
        const ta = card.querySelector('textarea');
        ta.value = token; ta.focus(); ta.select();
        card.querySelector('#ss-close').addEventListener('click', _ssClose);
        card.querySelector('#ss-copy').addEventListener('click', () => {{
          ta.focus(); ta.select();
          try {{ if (navigator.clipboard) navigator.clipboard.writeText(token); }} catch (e) {{}}
          try {{ document.execCommand('copy'); }} catch (e) {{}}
        }});
      }});
    }});
  }}

  function tick() {{
    requestAnimationFrame(tick);
    // Frame-pace cap: always reschedule, but skip this frame's render work
    // until the cap interval elapsed. -0.5 ms slack stops a 16.6 ms target
    // collapsing to 30 fps on sub-ms jitter. Off (==0) → original behaviour.
    // Frame-pace cap — but NEVER skip while a path/bench is driving: the
    // player advance + camera write + recorder live below this point, so a
    // skip would freeze the camera and drop bench samples (this is why the
    // bench "didn't rotate" on capped Apple-Silicon).
    if (_FRAME_MIN_MS && !_player && !_benchActive) {{
      const _tNow = performance.now();
      if (_tNow - _lastRenderMs < _FRAME_MIN_MS - 0.5) return;
      _lastRenderMs = _tNow;
    }}
    _gpuBeginFrame();

    // WASD movement (skipped during path playback inside applyKeyMovement)
    applyKeyMovement();

    // Benchmark per-frame sample (free when not recording).
    const _nowMs = performance.now();
    if (_benchActive) _benchTick(_nowMs);

    // Live gaussian count + FPS. spark.activeSplats is the post-LoD,
    // post-budget count actually rendered this frame (read-only, free).
    // FPS uses a 1-second rolling window so the number doesn't jitter.
    {{
      const dispM = ((spark.activeSplats || 0) / 1e6).toFixed(2);
      const fps = _fpsTick();
      const fpsHtml = fps > 0 ? ` <span class="fps">· ${{fps}} fps</span>` : '';
      splatCountEl.innerHTML = `Splats: ${{dispM}}M${{fpsHtml}}`;
    }}

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
        if (_benchActive) {{ if (!_benchCam.armed) _benchCamArm(); _benchCamSample(); }}
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

    // Auto view-tracking focus + HUD (both no-ops when disabled).
    _autoFocusTick(_nowMs);
    _hudTick();

    // Camera bounds clamp (conditional on cfg.camera.enabled)
    if (cam && cam.enabled === true) {{
      const p = camera.position;
      if (p.x < -cam.bounds_radius) p.x = -cam.bounds_radius;
      else if (p.x > cam.bounds_radius) p.x = cam.bounds_radius;
      if (p.z < -cam.bounds_radius) p.z = -cam.bounds_radius;
      else if (p.z > cam.bounds_radius) p.z = cam.bounds_radius;
      if (p.y < cam.ground_height) p.y = cam.ground_height;
    }}

    // Path/bench owns the camera. OrbitControls.update() re-derives the
    // camera from its internal spherical and OVERWRITES the player's
    // per-frame write (and forces lookAt(target)); controls.enabled=false
    // does NOT stop update() in three 0.180 (verified in the pinned
    // source — no enabled guard). So skip it entirely while a path/bench
    // drives; it resumes normally the moment _player is null again.
    if (!_player) controls.update();
    renderer.render(scene, camera);
    if (_capReq) {{
      const _cr = _capReq; _capReq = null;
      let _d = null;
      try {{ _d = renderer.domElement.toDataURL('image/jpeg', 0.82); }} catch (e) {{}}
      _cr(_d);
    }}
    css2d.render(scene, camera);
    _gpuEndFrame();
  }}

  // Hide loading once the splat is ready. The splat-count text itself
  // is updated every frame from spark.activeSplats in tick(), so we don't
  // overwrite it here (the previous one-shot "Streaming .rad" message
  // would have masked the live count).
  //
  // Also install the chunk-upload throttle on the SparkRenderer's pager
  // **only on phone/tablet tiers**. Spark's default `pager.processUploads()`
  // drains EVERY ready chunk per call, so when several chunks finish
  // decoding in the same frame all of them upload + texSubImage3D in that
  // one frame — a visible 100-250 ms stall on weak GPUs (mobile). On a
  // fast desktop the upload is cheap and the throttle just slows LoD
  // refinement, making the view look "flimsy" while it catches up. So we
  // skip the monkey-patch entirely on desktop and let Spark drain freely.
  // Bumped 2 → 8 because user reported splats vanishing during fast iPhone
  // navigation: with cap=2, new chunks for the freshly-rotated-into view
  // can't reach GPU before the LoD evicts old chunks → empty screen.
  // cap=8 means ~480 chunk-uploads per second at 60 Hz — enough to keep up
  // with any reasonable camera motion. Trade-off: occasional bigger frame
  // spikes on chunk-burst arrival, but rendering "something" is preferable
  // to rendering nothing.
  const PROCESS_UPLOADS_MAX_PER_FRAME = 8;
  // Apple Silicon also throttles: a burst of chunks finishing decode in one
  // frame all texSubImage that frame → the motion "stutter"/longtasks the
  // user felt on MacBook (worst during the cold fill, fades as the pool
  // warms — exactly a per-new-chunk-burst signature). Spreading the burst
  // (cap 8 ≈ 480 uploads/s @60 Hz) trades a touch of LoD-refine latency for
  // smooth pacing. Discrete desktop still drains free (it has no stutter).
  const _shouldThrottleUploads = !STOCK &&
    (_deviceProfile.tier === 'phone' || _deviceProfile.tier === 'tablet' || _AS);
  // ?preload=N caps the chunks we wait for (default heuristic below).
  // ?preload=0 disables the front-load phase entirely.
  const PRELOAD_OFF = new URLSearchParams(location.search).get('preload') === '0';
  // Resolved when the loading panel hides (preload phase complete). The auto
  // bench trigger awaits this so the orbit doesn't start under an occluded
  // canvas.
  // ---- Centre-first load (Luma-style) ----
  // Apply the focus override at the start-view CENTRE immediately — before
  // splat.initialized / preload — so Spark's very first LoD traversals
  // prioritise the chunks under the screen centre. Without this the centre
  // (what you look at) resolves LAST. From cfg.start_view (no raycast needed
  // — config is known now). Skipped for STOCK / bench (bench drives its own
  // orbit prefetch). Auto-focus takes over seamlessly once _afReady.
  if (!STOCK && !BENCH_AUTO && cfg.start_view
      && Array.isArray(cfg.start_view.pos) && Array.isArray(cfg.start_view.target)) {{
    const _sp = cfg.start_view.pos, _st = cfg.start_view.target;
    const _dx=_sp[0]-_st[0], _dy=_sp[1]-_st[1], _dz=_sp[2]-_st[2];
    const _q = Array.isArray(cfg.start_view.quat) ? cfg.start_view.quat : [0,0,0,1];
    spark.lodPosOverride  = new THREE.Vector3(
      _st[0]+_dx*FOCUS_NEAR_FRAC, _st[1]+_dy*FOCUS_NEAR_FRAC, _st[2]+_dz*FOCUS_NEAR_FRAC);
    spark.lodQuatOverride = new THREE.Quaternion(_q[0],_q[1],_q[2],_q[3]);
    _afSet = true;
    console.info('[Splatpipe] centre-first load: focus override set from frame 1');
  }}

  // ---- Early reveal (Luma-style) ----
  // Independent of `await splat.initialized` / the full preload. Show the
  // canvas as soon as a little COARSE coverage is resident, then let the
  // rest stream in *visibly*. Combined with centre-first ordering above,
  // the user sees the centre appear fast and sharpen first, edges after —
  // instead of staring at a spinner for ~15-27 s while everything loads
  // hidden. The root-chunk guard guarantees no blank gaps. The preload
  // IIFE below still runs (camera framing, prefetch, _afReady) behind the
  // now-visible canvas; its later .add('hidden') is an idempotent no-op.
  (async () => {{
    const _loadEl = document.getElementById('loading');
    const _t0 = performance.now();
    const REVEAL_MIN_PAGES = 6;     // a few coarse (centre-first) chunks = enough to show
    const REVEAL_HARD_MS   = 4000;  // never later than this
    while (true) {{
      const pgr = spark.pager;
      const resident = pgr ? (pgr.maxPages - (pgr.pageFreelist?.length || 0)) : 0;
      if (resident >= REVEAL_MIN_PAGES || (performance.now() - _t0) > REVEAL_HARD_MS) break;
      await new Promise(r => setTimeout(r, 100));
    }}
    _loadEl.classList.add('hidden');
    console.info('[Splatpipe] early reveal at', Math.round(performance.now()), 'ms');
  }})();

  let _preloadDoneResolve;
  const _preloadDonePromise = new Promise(r => {{ _preloadDoneResolve = r; }});
  (async () => {{
    if (splat.initialized && typeof splat.initialized.then === 'function') {{
      try {{ await splat.initialized; }} catch (e) {{ console.warn('splat init failed', e); }}
    }}

    // ---- Generic "outside-the-model" camera framing ----
    // Spark paged-splat scenes do NOT expose a usable bounding box:
    //   • THREE.Box3.setFromObject returns empty (no traversable geometry)
    //   • splat.getBoundingBox() throws "requires PackedSplats or ExtSplats"
    //   • raycast intersectObject returns 0 hits before chunks render
    // Since build-lod centers splats at the origin during assembly, place
    // the camera at a generous (0, 20, 40), looking at the origin. That's
    // outside the model for any scene up to ~30 m radius — i.e. the
    // typical photogrammetry capture footprint. For bigger scenes the user
    // can fly out with WASD or pinch-zoom; for precise framing per
    // project, author a camera path or drop an annotation and the viewer
    // will use that instead.
    const hasAuthoredView = (cfg.start_view && Array.isArray(cfg.start_view.pos)) ||
      (cfg.default_path_id) ||
      (Array.isArray(cfg.camera_paths) && cfg.camera_paths.length > 0) ||
      (Array.isArray(cfg.annotations) && cfg.annotations.length > 0);
    if (!hasAuthoredView) {{
      // Distance scaled with sqrt(numSplats): bigger scenes need bigger
      // setback. Empirical mapping from observed scenes:
      //   500 K splats → ~24 m setback (clamped to floor 40)
      //   2 M splats   → ~47 m
      //   10 M splats  → ~105 m
      //   20 M splats  → ~149 m (Speicher: needed at least this far out)
      //   30 M splats  → ~183 m (Stettiner Haff)
      const N = splat.numSplats || splat.paged?.numSplats || 1_000_000;
      const dist = Math.max(40, Math.sqrt(N) / 30);
      // Eye-level-ish camera height. Y = min(12, dist × 0.08) — never goes
      // above ~12 units high regardless of scene size, scales DOWN for
      // smaller scenes. For building captures this lands roughly at first-
      // floor / pedestrian eye level looking slightly down at the model.
      const yHeight = Math.min(12, dist * 0.08);
      camera.position.set(0, yHeight, dist);
      camera.lookAt(0, 0, 0);
      controls.target.set(0, 0, 0);
      camera.far = Math.max(5000, dist * 50);
      camera.updateProjectionMatrix();
      controls.update();
      _origCamPos.copy(camera.position);
      _origCamQuat.copy(camera.quaternion);
      _origCamFov = camera.fov;
      _origTarget.set(0, 0, 0);
      console.info('[Splatpipe] camera placed for', N, 'splats · dist=', dist.toFixed(0));
    }}

    // Pager is lazy-allocated on the SparkRenderer when the first paged mesh
    // is added; by the time `splat.initialized` resolves it exists.
    const pager = spark.pager;
    if (_shouldThrottleUploads && pager && typeof pager.processUploads === 'function' &&
        !pager.__spThrottled) {{
      const orig = pager.processUploads.bind(pager);
      pager.processUploads = function() {{
        const q = this.readyUploads;
        if (!q || q.length <= PROCESS_UPLOADS_MAX_PER_FRAME) return orig();
        const tail = q.splice(PROCESS_UPLOADS_MAX_PER_FRAME);
        try {{ return orig(); }}
        finally {{
          this.readyUploads = (this.readyUploads || []).concat(tail);
        }}
      }};
      pager.__spThrottled = true;
    }}

    // ---- LoD root-chunk eviction guard (anti-disappear, no fetch throttle) ----
    // Goal: keep coarse coverage (chunks 0..15, the top LoD levels) resident
    // so a not-yet-streamed region never renders as a blank gap — WITHOUT the
    // old approach of unshifting those 16 chunks to the FRONT of fetchPriority
    // on every driveFetchers() call. That old per-frame re-prepend made the
    // 3-4 fetch slots churn through coarse chunks before the camera-relevant
    // fine chunks, so detail "loaded in" very slowly and LoD transitions
    // (the "reshading") crawled visibly. New approach, two cleanly separated
    // concerns (verified against spark/src/SplatPager.ts):
    //   1. Queue a still-missing root chunk only ONCE, appended at the END of
    //      fetchPriority — Spark's own camera-priority ordering (built by the
    //      real driveFetchers) keeps full priority + all fetch slots for the
    //      fine chunks in view; the coarse roots fill in from spare capacity.
    //   2. After the real driveFetchers runs, drop any root-chunk page out of
    //      `freeablePages` so allocateFreeable() can never evict it. That is
    //      the actual anti-disappear guarantee, at zero fetch-priority cost.
    const PINNED_ROOT_CHUNK_COUNT = 16;
    if (pager && typeof pager.driveFetchers === 'function' && !pager.__spRootGuard) {{
      const origDrive = pager.driveFetchers.bind(pager);
      const _isRoot = (sc) => sc && sc.splats === splat.paged && sc.chunk < PINNED_ROOT_CHUNK_COUNT;
      pager.driveFetchers = function() {{
        if (!this.fetchPriority) this.fetchPriority = [];
        // (1) Ensure each not-yet-resident root chunk is queued exactly once,
        //     at the END so it never preempts in-view fine detail.
        for (let i = 0; i < PINNED_ROOT_CHUNK_COUNT; i++) {{
          if (this.getSplatsChunk(splat.paged, i)) continue;  // already resident
          const queued =
            this.fetchPriority.some(p => p.splats === splat.paged && p.chunk === i) ||
            (this.fetchers || []).some(f => f.splats === splat.paged && f.chunk === i) ||
            (this.fetched || []).some(f => f.splats === splat.paged && f.chunk === i);
          if (!queued) this.fetchPriority.push({{ splats: splat.paged, chunk: i }});
        }}
        origDrive();
        // (2) Make resident root pages non-evictable.
        if (this.freeablePages && this.freeablePages.length) {{
          this.freeablePages = this.freeablePages.filter(
            pg => !_isRoot(this.pageToSplatsChunk[pg])
          );
        }}
      }};
      pager.__spRootGuard = true;
      console.info('[Splatpipe] root-chunk eviction guard active (no per-frame re-pin)');
    }}

    // ---- Front-load phase (pillar V) ----
    // Hold the canvas behind the loading panel until Spark has finished its
    // initial chunk burst. The loading bar reflects (resident pages /
    // target) AND (elapsed / timeout) — whichever is further along — so the
    // user always sees forward motion even if Spark's burst stalls.
    //
    // Done condition: pager is idle (no in-flight fetches, no decoded-but-
    // not-uploaded chunks) AND ≥ minPages are resident. OR a hard timeout.
    //
    // This removes the cold-start FPS dip and the first-paint pop-in.
    if (!PRELOAD_OFF && pager) {{
      const fill = document.getElementById('loading-progress-fill');
      const txt  = document.getElementById('loading-progress-text');
      // Two-phase preload:
      //   Phase A: passive wait for initial chunk burst (~1.5 s, 16+ pages).
      //   Phase B (only when BENCH_AUTO === 'orbit'): walk through ORBIT_SAMPLES
      //     poses around the orbit, setting spark.lodPosOverride for each so
      //     Spark's LoD traversal demands chunks at those positions. Pre-warms
      //     the cache for the entire 360° orbit — fetchers grab chunks for
      //     positions the camera will visit, not just the start view.
      // Total budget: 12 s. Cancels early on done.
      const PHASE_A_TARGET_PAGES = 16;
      const PHASE_A_MIN_MS = 1500;
      const ORBIT_SAMPLES = 16;          // ≈ every 22.5° around the orbit
      const ORBIT_SAMPLE_DWELL_MS = 500; // wait per pose for fetchers to grab
      const MAX_WAIT_MS = 12000;         // orbit-prefetch (bench) budget / outer cap
      // Normal (non-orbit) reveal: show the scene as soon as COARSE coverage
      // is up, then let fine detail stream in visibly. The root-chunk pin
      // guarantees chunks 0..15 stay resident so there are never blank gaps,
      // and chunked .radc + auto-focus refine fast after reveal. Measured
      // (2026-05-15): the old resident/24-or-12s gate held the canvas hidden
      // ~12-15 s on a cold chunked load while it loaded ~the whole working
      // set; revealing on coarse coverage cuts time-to-first-image to a few
      // seconds (the dominant "feels slow" factor — user judges by when they
      // SEE it). Trade: first frame is coarse-but-complete, sharpens over the
      // next few seconds.
      const REVEAL_PAGES = 12;
      const REVEAL_MAX_MS = 3500;
      const t0 = performance.now();

      // Pre-build orbit player if needed; we'll re-sample at preload poses.
      let orbitPlayer = null;
      if (BENCH_AUTO === 'orbit') {{
        try {{ orbitPlayer = buildPlayer(_buildOrbitPath()); }}
        catch (e) {{ console.warn('[preload] orbit build failed', e); }}
      }}

      let phaseAdone = false;
      let orbitIdx = 0;
      let orbitNextAt = t0 + PHASE_A_MIN_MS;

      while (true) {{
        const now = performance.now();
        const elapsed = now - t0;
        const inFlight = pager.fetchers?.length || 0;
        const decoded  = (pager.fetched?.length || 0) +
                         (pager.newUploads?.length || 0) +
                         (pager.readyUploads?.length || 0);
        const resident = pager.maxPages - (pager.pageFreelist?.length || 0);

        // Phase A → B transition
        if (!phaseAdone && elapsed >= PHASE_A_MIN_MS && resident >= PHASE_A_TARGET_PAGES) {{
          phaseAdone = true;
          orbitNextAt = now;  // start orbit sampling immediately
        }}

        // Phase B: cycle through orbit poses to populate fetchPriority for each.
        if (orbitPlayer && phaseAdone && orbitIdx < ORBIT_SAMPLES && now >= orbitNextAt) {{
          const tOrbit = (orbitIdx / ORBIT_SAMPLES) * orbitPlayer.duration;
          const s = sampleAt(orbitPlayer, tOrbit);
          if (!spark.lodPosOverride) spark.lodPosOverride = new THREE.Vector3();
          if (!spark.lodQuatOverride) spark.lodQuatOverride = new THREE.Quaternion();
          spark.lodPosOverride.set(s.pos[0], s.pos[1], s.pos[2]);
          spark.lodQuatOverride.set(s.quat[0], s.quat[1], s.quat[2], s.quat[3]);
          orbitIdx++;
          orbitNextAt = now + ORBIT_SAMPLE_DWELL_MS;
        }}

        // Progress bar: based on what phase we're in.
        let pct;
        if (orbitPlayer) {{
          // 0-30%: phase A (resident pages or elapsed). 30-95%: phase B (orbit samples).
          const aPct = Math.min(1, Math.max(resident / PHASE_A_TARGET_PAGES, elapsed / PHASE_A_MIN_MS));
          const bPct = Math.min(1, orbitIdx / ORBIT_SAMPLES);
          pct = Math.max(aPct * 0.3 + bPct * 0.65,
                          Math.min(1, elapsed / MAX_WAIT_MS));
        }} else {{
          // Normal load: reveal on coarse coverage (≈REVEAL_PAGES pages) or
          // a short timeout — NOT the full working set.
          pct = Math.max(
            Math.min(1, resident / REVEAL_PAGES),
            Math.min(1, elapsed / REVEAL_MAX_MS),
          );
        }}

        const pctText = (pct * 100).toFixed(0) + '%';
        if (fill) fill.style.width = pctText;
        if (txt) {{
          if (orbitPlayer && phaseAdone) {{
            txt.textContent = `${{pctText}}  ·  orbit prefetch ${{orbitIdx}}/${{ORBIT_SAMPLES}}  ·  ${{resident}} cached`;
          }} else if (inFlight + decoded > 0) {{
            txt.textContent = `${{pctText}}  ·  ${{resident}} loaded · ${{inFlight}} fetching · ${{decoded}} decoding`;
          }} else {{
            txt.textContent = `${{pctText}}  ·  ${{resident}} chunks ready`;
          }}
        }}

        // Done conditions:
        //   Orbit mode: all samples done AND fetch/decode queues drained AND ≥1s margin
        //   Passive mode: bar full
        //   Always: hard timeout
        const orbitDrained = orbitPlayer && orbitIdx >= ORBIT_SAMPLES && inFlight === 0 && decoded === 0;
        const passiveDone = !orbitPlayer && pct >= 1.0;
        if (orbitDrained || passiveDone || elapsed > MAX_WAIT_MS) break;
        await new Promise(r => setTimeout(r, 100));
      }}

      // NOTE: do NOT clear lodPosOverride here. Centre-first load set it from
      // frame 1 and auto-focus owns it from now on (it re-tracks the view
      // centre every ~180 ms once _afReady). Clearing it would drop centre
      // priority for a beat and let the camera spread detail again.
      if (BENCH_AUTO === 'orbit') {{   // only the bench orbit-walk needs its prefetch override cleared
        spark.lodPosOverride = undefined;
        spark.lodQuatOverride = undefined;
      }}
      console.info('[preload] done',
        '· resident:', pager.maxPages - (pager.pageFreelist?.length || 0),
        '· orbit samples:', orbitIdx, '/', orbitPlayer ? ORBIT_SAMPLES : 'n/a',
        '· elapsed:', Math.round(performance.now() - t0), 'ms');
    }}
    document.getElementById('loading').classList.add('hidden');
    if (typeof _preloadDoneResolve === 'function') _preloadDoneResolve();
    _afReady = true;  // auto-focus may now own lodPosOverride (preload cleared its own)
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
  window._spDebug = {{ camera, scene, splat, controls, renderer, spark }};
  </script>
</body>
</html>
"""
