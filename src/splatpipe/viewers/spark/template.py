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
    save_mode: str = "cli",
    save_endpoint: str | None = None,
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

    Save-backend plumbing (publish-time only; NO Save UI yet — a later task):
      * `save_mode`     — ``"cli"`` (default) or ``"http"``. Baked verbatim
                          as the ``SAVE_MODE`` JS const. With the default the
                          generated HTML is byte-identical to before apart
                          from the two new (inert) consts — existing scenes
                          are untouched. NOTHING reads these consts yet.
      * `save_endpoint` — POST URL for ``"http"`` mode (``None``/empty for
                          ``"cli"``); baked as ``SAVE_ENDPOINT``.
    The per-scene SECRET is intentionally NOT a parameter here and is never
    baked into the template nor written to viewer-config.json — in http mode
    it lives only in the author URL fragment (a later task).
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
        save_mode_json=json.dumps(save_mode),
        save_endpoint_json=json.dumps(save_endpoint or ""),
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
    body.embed #path-hud,
    body.embed #sp-hud,
    body.embed #author-root,
    body.embed #user-transport {{ display: none !important; }}

    /* Task 12 -- dual-UI gate (CSS-only; ModeManager sets the body class).
       #author-root (editor root) and #user-transport (end-user transport)
       are ALWAYS in the DOM and shown/hidden purely by the mode class, so
       there is no add/remove layout flash (same approach as the embed strip
       above, which also hides both). usermode = the default end-user view;
       authormode = ?author=1. Empty placeholders in Task 12 -- Tasks 16-18
       populate them. */
    body.usermode #author-root {{ display: none; }}
    body.authormode #user-transport {{ display: none; }}

    /* Task 13 -- cinematic loading-blur + intro fade (the END-USER shell,
       plan SS-A3). Same CSS-gating mechanism as the Task-12 dual-UI roots
       above: #loading-blur and #intro-fade are ALWAYS in the DOM and
       shown/hidden purely by the body mode class ModeManager sets -- no JS
       add/remove, no layout flash. They default to display:none and are
       un-hidden ONLY in usermode (the cinematic end-user path); embed
       strips them like all other chrome; authormode keeps the plain
       (pre-Task-13) loading screen + immediate tour so the editor (Tasks
       16-18) is never obstructed by an opaque fade. RATIONALE (do not
       regress): the fade overlay is the single worst thing to get wrong --
       a stuck opaque #intro-fade = the whole scene hidden. The JS makes it
       fail-safe (fades, then pointer-events:none AND display:none, plus a
       hard fallback); these rules only decide WHICH modes ever show it. */
    #loading-blur {{
      position: absolute; inset: 0; z-index: -1;
      background-position: center; background-size: cover;
      background-repeat: no-repeat;
      filter: blur(24px); transform: scale(1.08);
      display: none;
    }}
    #intro-fade {{
      position: fixed; inset: 0; z-index: 200;
      background: #1a1a1a; opacity: 1;
      transition: opacity var(--intro-ms, 900ms) ease;
      pointer-events: none;            /* never blocks input, even mid-fade */
      display: none;
    }}
    #intro-fade.faded {{ opacity: 0; }}
    /* usermode = the cinematic end-user view: show both. */
    body.usermode #loading-blur,
    body.usermode #intro-fade {{ display: block; }}
    /* embed strips the cinematic layer too (clean canvas-only iframe). The
       !important matches the embed strip above and beats the usermode rule
       even though embed bodies also carry `usermode`. */
    body.embed #loading-blur,
    body.embed #intro-fade {{ display: none !important; }}
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
      <select id="move-speed" class="quality-btn" title="Camera fly speed (WASD / arrows). Live — your choice is remembered on this device, no reload or redeploy. ?moveSpeed=N forces a value.">
        <option value="0.1">Speed: 0.1×</option>
        <option value="0.25">Speed: 0.25×</option>
        <option value="0.5">Speed: 0.5×</option>
        <option value="0.75">Speed: 0.75×</option>
        <option value="1">Speed: 1×</option>
        <option value="1.5">Speed: 1.5×</option>
        <option value="2">Speed: 2×</option>
        <option value="4">Speed: 4×</option>
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
    <!-- Task 13: blurred preview.jpg backdrop behind the spinner (the
         cinematic loading screen, plan SS-A3). preview.jpg is the scene's
         share-card image (same relative name html_for emits as og:image);
         a missing file just yields a plain dark backdrop -- never an
         error. usermode-only + embed-stripped via the body-class CSS
         above (mirrors the Task-12 dual-UI gating; no JS toggle). -->
    <div id="loading-blur" style="background-image: url('preview.jpg');"></div>
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

  <!-- Task 12 dual-UI roots. ALWAYS present, CSS-gated by the body mode
       class ModeManager sets (body.usermode / body.authormode / the embed
       strip) -- intentionally NOT JS add/removed so there is no layout
       flash, mirroring the embed chrome strip. Empty placeholders now;
       Tasks 16-18 populate them (#author-root = the in-viewer editor UI,
       #user-transport = the end-user cinematic transport). -->
  <div id="author-root"></div>
  <div id="user-transport"></div>

  <!-- Task 13: full-screen intro-fade overlay (the END-USER cinematic
       reveal, plan SS-A3). ALWAYS in the DOM + CSS-gated by the body mode
       class (usermode shows it, embed strips it, authormode keeps it
       hidden) -- same no-JS-toggle / no-layout-flash approach as the
       Task-12 roots above. The intro controller (JS, below) fades it
       opacity 1->0 on the REAL ready signal then makes it permanently
       non-blocking; a hard fallback guarantees it can NEVER trap the
       scene. type:"none" leaves it untouched (never shown). -->
  <div id="intro-fade"></div>

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
  // Save-backend plumbing (publish-time; see html_for). INERT - no code
  // reads these yet; the Save UI (a later task) will branch on SAVE_MODE
  // ('cli' = read-only; 'http' = POST edits to SAVE_ENDPOINT). The per-scene
  // SECRET is NEVER here / in viewer-config.json (http-mode: URL fragment).
  const SAVE_MODE = {save_mode_json};
  const SAVE_ENDPOINT = {save_endpoint_json};

  // ?stock=1 in the URL strips all Splatpipe perf modifications (no DPR cap,
  // no mobile Spark-knob bundle, no maxSh cap, no processUploads throttle).
  // Useful for A/B visual comparisons against pure Spark defaults.
  const STOCK = new URLSearchParams(location.search).get('stock') === '1';
  if (STOCK) console.info('[Splatpipe] STOCK mode: all perf mods disabled');

  // ============================================================
  //  Unified SceneView framework (Task 0 — FOUNDATION)
  // ------------------------------------------------------------
  //  ONE place that owns: which mode we're in, the single 3D
  //  overlay group, who owns the pointer/camera right now, and
  //  the 2D panel layout. Every current and future editor /
  //  cinematic feature (trajectory, frustums, gizmo, 3D titles,
  //  annotation anchors, ghost cam, cut-LOD-prefetch, …) plugs
  //  into THESE four objects — never its own ad-hoc DOM/handlers.
  //  User directive (msg 6477): "structure the 3D View from the
  //  top and unify — avoid similar-but-different solutions."
  //
  //  Task 0 is a PURE REFACTOR: no feature is added. The existing
  //  ?embed=1 body-class, the OrbitControls / _player / _looking
  //  pointer guards and the HUD / controls-hint are routed THROUGH
  //  these objects with byte-identical behavior. window.__sceneview
  //  is the test surface every later Playwright task asserts on.
  // ============================================================

  // ---- ModeManager: single source of truth for the view mode ----
  // Resolves user|author|embed from the URL ONCE. ?embed=1 wins
  // (clean iframe embed), then ?author=1 (the editor), else 'user'
  // (the default cinematic/end-user view). One <body> class switch
  // so every UI element can declare the modes it appears in via
  // CSS instead of scattering per-feature `if (author)` in JS.
  const ModeManager = (() => {{
    const _qs = new URLSearchParams(location.search);
    const _mode = (_qs.get('embed') === '1') ? 'embed'
                : (_qs.get('author') === '1') ? 'author'
                : 'user';
    const _subs = [];
    // ONE class switch. `mode-<x>` is the generic, declarative hook
    // for current+future CSS gating. The legacy `embed` class is
    // ALSO kept for embed mode so the existing `body.embed …` rules
    // (unchanged) keep hiding chrome byte-identically — pure-additive,
    // zero behavior change. (Task 8 layers usermode/authormode +
    // chrome gating on top of this; T0 only lands the resolver.)
    document.body.classList.add('mode-' + _mode);
    // Task 12 dual-UI gate, driven off THIS single resolved `_mode`
    // (NO second ?author parse -- A4-unify: ModeManager is the only
    // mode source). `authormode` only when ?author=1 won the ternary
    // above (=> _mode==='author'); every other case (default user,
    // and embed -- whose strip hides both dual-UI roots anyway) is
    // `usermode`. CSS-GATED, NOT JS-toggled: the #author-root /
    // #user-transport DOM is always present and shown/hidden purely
    // by this body class (same approach as `embed`) so there is no
    // add/remove layout flash. A future editor MUST keep this a
    // class switch -- do not "fix" it to JS branching.
    document.body.classList.add(
      _mode === 'author' ? 'authormode' : 'usermode');
    if (_mode === 'embed') {{
      document.body.classList.add('embed');
      console.info('[Splatpipe] EMBED mode (chrome hidden for iframe)');
    }}
    return {{
      get mode() {{ return _mode; }},
      is(m) {{ return _mode === m; }},
      // modes==undefined/empty → visible in ALL modes (today's default).
      matches(modes) {{
        return !modes || modes.length === 0 || modes.indexOf(_mode) !== -1;
      }},
      onChange(fn) {{ if (typeof fn === 'function') _subs.push(fn); }},
      // Mode is resolved once from the URL and never mutates in T0.
      // The change fan-out to `_subs` (used by OverlayScene/HudLayer
      // via onChange) stays internal — it is intentionally NOT exposed
      // on the public `window.__sceneview` surface; a future in-viewer
      // mode toggle wires its own internal path to it.
    }};
  }})();
  // Back-compat alias — `EMBED` was the old gate; some call sites and
  // future diffs read it. Derived from ModeManager so there's still
  // exactly one source of truth.
  const EMBED = ModeManager.is('embed');

  // ---- OverlayScene: the ONE 3D overlay group ----
  // A single THREE.Group added to the scene that holds ALL editor /
  // cinematic 3D overlays. Features call register(layer)/unregister
  // — they never add a parallel scene/group. One update(t) tick fans
  // out to layers; one show/hide registry keyed by ModeManager; one
  // depth/scale policy in one place. In Task 0 it has zero layers
  // (pure framework); Tasks 12/14/etc. add the trajectory, frustums,
  // gizmo, 3D titles, ghost cam, … as layers here.
  //
  //   layer = {{ id?, modes?:string[], node?:THREE.Object3D,
  //             update?(t), onShow?(), onHide?() }}
  // `node` (if given) is parented under the overlay group; `modes`
  // (if given) restricts the layer to those modes (absent = all).
  const OverlayScene = (() => {{
    const group = new THREE.Group();
    group.name = 'sceneview-overlay';
    // One depth/scale policy lives HERE so no feature re-decides it:
    // overlays draw on top of the splat (renderOrder) and are NOT
    // raycast by the scene-content raycaster (InteractionManager owns
    // overlay picking later). Identity transform — overlays author in
    // world space. Centralised so Tasks 12/14 don't each reinvent it.
    group.renderOrder = 10;
    const _layers = [];
    function _applyVisibility(layer) {{
      const vis = ModeManager.matches(layer.modes);
      const wasVis = layer._lastVis;
      layer._lastVis = vis;
      if (layer.node) layer.node.visible = vis;
      // Fire onShow/onHide ONLY on a real transition. _lastVis starts
      // undefined, so: first register-while-visible fires onShow once
      // (undefined !== true), first register-while-hidden fires NOTHING
      // (undefined === true is false), a true shown->hidden fires onHide,
      // hidden->shown fires onShow, same-state never fires, and a mode
      // round-trip never double-fires onShow.
      if (vis && wasVis !== true && typeof layer.onShow === 'function') {{ try {{ layer.onShow(); }} catch (e) {{}} }}
      if (!vis && wasVis === true && typeof layer.onHide === 'function') {{ try {{ layer.onHide(); }} catch (e) {{}} }}
    }}
    ModeManager.onChange(() => {{ for (const l of _layers) _applyVisibility(l); }});
    return {{
      group,
      register(layer) {{
        if (!layer || _layers.indexOf(layer) !== -1) return layer;
        _layers.push(layer);
        if (layer.node && layer.node.parent !== group) group.add(layer.node);
        _applyVisibility(layer);
        return layer;
      }},
      unregister(layer) {{
        const i = _layers.indexOf(layer);
        if (i === -1) return;
        _layers.splice(i, 1);
        if (layer.node && layer.node.parent === group) group.remove(layer.node);
      }},
      // ONE tick — called once per frame from the render loop; fans
      // out to every registered, mode-visible layer.
      update(t) {{
        for (const l of _layers) {{
          if (typeof l.update === 'function' && ModeManager.matches(l.modes)) {{
            try {{ l.update(t); }} catch (e) {{}}
          }}
        }}
      }},
      layers() {{ return _layers.slice(); }},
    }};
  }})();

  // ---- InteractionManager: ONE pointer/camera arbitration layer ----
  // Brokers WHO owns the canvas pointer + camera right now. Today
  // that ownership is scattered across OrbitControls-vs-`_player`-vs-
  // `_looking`-vs-touch-zoom guards. Task 0 centralises the *query*:
  // path playback / bench acquire 'player'; the existing `_player` /
  // `_looking` variables remain the actual per-handler gates (so
  // behavior is byte-identical), but the manager mirrors them and is
  // the single point future tools (TransformControls, annotation
  // place, click-interrupt) ask "can I take the pointer?". Priority:
  // the path/bench owner ('player') is exclusive — it wins over
  // free-look/orbit, exactly as the existing `if (_player) return`
  // guards already enforce.
  const InteractionManager = (() => {{
    let _owner = null;          // null = free (OrbitControls/look/zoom)
    const EXCLUSIVE = {{ player: true }};  // owners that lock out others
    return {{
      // Returns true if granted. While an *exclusive* owner (path/
      // bench 'player') holds it, any other owner is refused — mirrors
      // today's hard rule that nothing preempts an active path/bench
      // (the `if (_player) return` guards). A non-exclusive owner
      // (look/orbit/future tools) freely takes it when nothing
      // exclusive is active. NOTE: in T0 nothing READS this — the live
      // gates are still `_player`/`_looking` — so this arbitration is
      // inert for behavior; it defines the contract later tasks query.
      requestPointer(owner) {{
        if (!owner) return false;
        if (_owner && _owner !== owner && EXCLUSIVE[_owner]) {{
          return false;
        }}
        _owner = owner;
        return true;
      }},
      releasePointer(owner) {{
        if (_owner === owner || owner == null) _owner = null;
      }},
      currentOwner() {{ return _owner; }},
      // Convenience the ported guards use instead of bare `_player`:
      // "is some exclusive owner (path/bench) driving the camera?"
      isCameraOwned() {{ return !!(_owner && EXCLUSIVE[_owner]); }},
    }};
  }})();

  // ---- HudLayer: ONE declarative 2D panel container ----
  // Registered 2D panels (HUDs, transports, popovers, hints). The
  // layer tracks them and applies ModeManager visibility; panels
  // keep their own CSS positioning for now (migrating the existing
  // settings-HUD + controls-hint changes nothing visually — they
  // register with no `modes` so they show in every mode exactly as
  // today). Tasks 11/13/14 register the user transport + timeline +
  // popovers HERE rather than each doing bespoke DOM/positioning.
  //
  //   panel = {{ id?, el:HTMLElement, modes?:string[] }}
  const HudLayer = (() => {{
    const _panels = [];
    function _apply(p) {{
      if (!p.el) return;
      // T0: panels register with no `modes` → matches() is true in
      // every mode → we never touch their display, so the existing
      // HUD/controls-hint render byte-identically. A future moded
      // panel gets show/hidden here, in ONE place.
      if (p.modes && p.modes.length) {{
        p.el.style.display = ModeManager.matches(p.modes) ? '' : 'none';
      }}
    }}
    ModeManager.onChange(() => {{ for (const p of _panels) _apply(p); }});
    return {{
      register(panel) {{
        if (!panel || !panel.el || _panels.indexOf(panel) !== -1) return panel;
        _panels.push(panel);
        _apply(panel);
        return panel;
      }},
      unregister(panel) {{
        const i = _panels.indexOf(panel);
        if (i !== -1) _panels.splice(i, 1);
      }},
      panels() {{ return _panels.slice(); }},
    }};
  }})();

  // ---- window.__sceneview: the test/extension surface ----
  // Every later Playwright task asserts on this; later feature code
  // also reaches the four managers through it. Mirrors the existing
  // window.__sp / window._spDebug convention. Harmless, always on.
  try {{
    window.__sceneview = {{
      get mode() {{ return ModeManager.mode; }},
      modes: ModeManager,
      overlay: OverlayScene,
      interaction: InteractionManager,
      hud: HudLayer,
    }};
  }} catch (e) {{}}

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

  // Effective splat asset. Bunny serves index.html with a 30-day edge
  // cache and its purge is unreliable, so a re-deployed stable-slug URL
  // would keep serving a STALE index.html that hardcodes an old build
  // subfolder → 404 → blank. Fix: index.html stays build-AGNOSTIC; the
  // current build's path lives in viewer-config.json (fetched no-store
  // above = always fresh) as `primary_asset`. So a redeploy only updates
  // the always-fresh config + adds an immutable new subfolder; the
  // permanent URL never goes stale. Falls back to the baked PRIMARY_ASSET
  // for single-file / legacy deploys that don't set cfg.primary_asset.
  const _PRIMARY = (typeof cfg.primary_asset === 'string' && cfg.primary_asset)
    ? cfg.primary_asset : PRIMARY_ASSET;

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
  // The ONE overlay group (Task 0). Empty in T0 — no layers added yet
  // — so adding it is a pure no-op visually; later features register
  // layers into OverlayScene rather than scene.add()-ing their own.
  scene.add(OverlayScene.group);
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
  const splatMeshOpts = {{ url: _PRIMARY, raycastable: true }};
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

  // Camera fly speed = sceneBase × a LIVE multiplier. sceneBase scales to the
  // initial camera→target distance (authored start-view framing — an
  // imperfect scene-size proxy, which is why a far-framed scene like Polygraf
  // wants a lower multiplier). The multiplier is tunable with NO redeploy:
  //   • in-viewer "Speed" dropdown — primary control, persisted per device
  //     in localStorage (your pick sticks across reloads & scenes);
  //   • ?moveSpeed=N — forces a value, wins over all (A/B / deep link);
  //   • spark_render.move_speed_mult — per-scene default for first visitors.
  const _initDist = camera.position.distanceTo(controls.target);
  const _moveBase = Math.max(2, _initDist * 0.6);
  const _msQ = parseFloat(new URLSearchParams(location.search).get('moveSpeed'));
  const _msFromUrl = Number.isFinite(_msQ) && _msQ > 0;
  const _msCfg = (typeof sr.move_speed_mult === 'number' && sr.move_speed_mult > 0) ? sr.move_speed_mult : 1.0;
  let _msLS = null;
  try {{ const _v = parseFloat(localStorage.getItem('splatpipe.moveSpeedMult')); if (Number.isFinite(_v) && _v > 0) _msLS = _v; }} catch (e) {{}}
  let _moveSpeedMult = _msFromUrl ? _msQ : (_msLS != null ? _msLS : _msCfg);
  const _speedSel = document.getElementById('move-speed');
  if (_speedSel) {{
    const _opts = Array.from(_speedSel.options).map(o => parseFloat(o.value));
    let _best = _opts[0];
    for (const o of _opts) if (Math.abs(o - _moveSpeedMult) < Math.abs(_best - _moveSpeedMult)) _best = o;
    _speedSel.value = String(_best);
    _speedSel.addEventListener('change', () => {{
      const m = parseFloat(_speedSel.value);
      if (Number.isFinite(m) && m > 0) {{
        _moveSpeedMult = m;
        try {{ localStorage.setItem('splatpipe.moveSpeedMult', String(m)); }} catch (e) {{}}
        console.info('[Splatpipe] move speed ×' + m + ' (saved on this device)');
      }}
    }});
  }}
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
    const step = _moveBase * _moveSpeedMult * sprint * dt;   // live multiplier
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
    // Mirror right-drag look ownership into the single broker (Task 0).
    // `_looking` stays the live gate (this handler + the moves read it),
    // so behavior is byte-identical; 'look' is non-exclusive so the
    // call never blocks — it just makes ownership queryable.
    InteractionManager.requestPointer('look');
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
    InteractionManager.releasePointer('look');
    if (e && e.pointerId !== undefined) {{
      try {{ canvas.releasePointerCapture(e.pointerId); }} catch (err) {{ /* ignore */ }}
    }}
  }};
  canvas.addEventListener('pointerup', _endLook);
  canvas.addEventListener('pointercancel', _endLook);
  window.addEventListener('blur', () => {{ _looking = false; InteractionManager.releasePointer('look'); }});

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
    // Stamp the throttle NOW (so a persistent miss retries at ~5 Hz, not
    // every frame) but DO NOT commit _afKey here — committing the pose
    // before the raycast means a centre-ray miss (common right after a
    // fast move: centre over still-coarse geometry / a gap / sky) marks
    // the resting pose "handled", and since the camera is now stopped the
    // guard above latches forever → focus frozen at the last in-motion
    // point, resting-view chunks never demanded. _afKey is committed only
    // after a focus is actually applied (below), so a miss/degenerate
    // return leaves _afKey stale and the next tick retries until it hits.
    _afLast = now;
    _ndc.set(0, 0);
    _raycaster.setFromCamera(_ndc, camera);
    const hits = _raycaster.intersectObject(splat, false);
    if (!hits.length) return;  // miss → keep last good focus; _afKey NOT yet committed so the next tick re-tries (until the rest view is hit)
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
    _afKey = k;   // commit "pose handled" ONLY now (a focus was applied); any
                  // miss/degenerate return above leaves _afKey stale so the
                  // next tick re-tries — fixes fast-move→stop "chunks don't LOD in"
  }}

  // ---- Toggleable on-screen settings HUD (press 'H') ----
  const _hud = document.createElement('div');
  _hud.id = 'sp-hud';
  _hud.style.cssText = 'position:fixed;left:10px;bottom:10px;z-index:9998;display:none;'
    + 'background:rgba(0,0,0,.72);color:#0f8;font:12px/1.5 monospace;padding:8px 11px;'
    + 'border-radius:7px;white-space:pre;pointer-events:none;';
  document.body.appendChild(_hud);
  // Register the existing 2D panels through the ONE HudLayer (Task 0).
  // No `modes` ⇒ HudLayer never touches their display ⇒ byte-identical
  // to today (the settings HUD's own H-toggle still owns its
  // visibility; #controls-hint keeps its CSS; embed still hides them
  // via the unchanged `body.embed` rules). This just makes them part
  // of the single panel registry future panels also join.
  HudLayer.register({{ id: 'settings-hud', el: _hud }});
  {{
    const _ch = document.getElementById('controls-hint');
    if (_ch) HudLayer.register({{ id: 'controls-hint', el: _ch }});
  }}
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
  // LOCKSTEP: the CubicSpline + buildPlayer logic below is kept byte-identical with
  //   src/splatpipe/web/templates/scene_editor.html -- edit BOTH files together.
  //   (tests/test_html_for_save_mode.py + _gen_harness_viewer.py enforce this.)
  // Per-keyframe interp modes (Task-1 schema; CONVENTION only — never
  // schema-enforced in JS). Absent OR any unknown/invalid string falls
  // through to the EXISTING global-`smoothness` path, byte-for-byte
  // unchanged (the live scenes carry no `interp` → behaviorally identical).
  const KF_LINEAR = 'linear', KF_STEPPED = 'stepped',
        KF_AUTOMATIC = 'automatic', KF_AUTO_CLAMPED = 'auto_clamped',
        KF_BEZIER = 'bezier';
  class CubicSpline {{
    constructor(times, knots, meta) {{
      this.times = times; this.knots = knots;
      this.dim = knots.length / times.length / 3;
      // `meta` is a per-spline-knot array (parallel to `times`) of the
      // source keyframe's {{interp,in_tan,out_tan}} (or null = legacy
      // global-smoothness knot). calcKnots already baked the tangents;
      // evaluate() only needs it for the `stepped`/`linear` SEGMENT
      // overrides. null/absent ⇒ the unchanged cubic-Hermite path.
      this.meta = meta || null;
    }}
    evaluate(time, result) {{
      const times = this.times; const last = times.length - 1;
      if (time <= times[0]) {{ this.getKnot(0, result); return; }}
      if (time >= times[last]) {{ this.getKnot(last, result); return; }}
      let seg = 0;
      while (time >= times[seg + 1]) seg++;
      // Per-keyframe SEGMENT override, keyed on the segment's SOURCE knot
      // (`seg`). `stepped` holds that knot's value flat for the whole
      // outgoing segment (a step until the next t). `linear` makes the
      // outgoing segment the straight p0→p1 LERP (a true corner — colinear,
      // no spline bulge) regardless of the next knot's mode. Both are
      // segment-source overrides so the behavior matches DCC f-curves.
      // Absent/unknown ⇒ the cubic Hermite below (legacy path, unchanged).
      const sm = this.meta ? this.meta[seg] : null;
      const mode = sm ? sm.interp : null;
      if (mode === KF_STEPPED || mode === KF_LINEAR) {{
        const dim = this.dim; const i0 = seg * 3 * dim;
        if (mode === KF_STEPPED) {{
          for (let i = 0; i < dim; i++) result[i] = this.knots[i0 + i * 3 + 1];
        }} else {{
          const u = (time - times[seg]) / (times[seg + 1] - times[seg]);
          const i1 = (seg + 1) * 3 * dim;
          for (let i = 0; i < dim; i++) {{
            const a = this.knots[i0 + i * 3 + 1];
            const b = this.knots[i1 + i * 3 + 1];
            result[i] = a + (b - a) * u;
          }}
        }}
        return;
      }}
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
    static calcKnots(times, points, smoothness, meta) {{
      const n = times.length; const dim = points.length / n;
      const knots = new Array(n * dim * 3);
      for (let i = 0; i < n; i++) {{
        const t = times[i];
        // This knot's per-keyframe mode (or null ⇒ legacy global path).
        const km = meta ? meta[i] : null;
        const mode = km ? km.interp : null;
        for (let j = 0; j < dim; j++) {{
          const idx = i * dim + j;
          const p = points[idx];
          let tangent;
          if (i === 0) tangent = (points[idx + dim] - p) / (times[i + 1] - t);
          else if (i === n - 1) tangent = (p - points[idx - dim]) / (t - times[i - 1]);
          else tangent = (points[idx + dim] - points[idx - dim]) / (times[i + 1] - times[i - 1]);
          const inScale = i > 0 ? (times[i] - times[i - 1]) : (times[1] - times[0]);
          const outScale = i < n - 1 ? (times[i + 1] - times[i]) : (times[i] - times[i - 1]);
          // EXISTING global-smoothness tangents (unchanged default path).
          let mIn = tangent * inScale * smoothness;
          let mOut = tangent * outScale * smoothness;
          // ── Per-keyframe tangent override (Task-11) ──────────────────
          // ONLY for the 5 known modes; absent/unknown leaves mIn/mOut
          // EXACTLY as the global-smoothness path computed them above
          // (the 6 live scenes have no `interp` ⇒ byte-identical result).
          if (mode === KF_LINEAR) {{
            // Corner: straight secants toward each neighbor (zero spline
            // curvature into/out of this knot). The OUTGOING segment is
            // additionally LERP-locked in evaluate() so it stays colinear
            // regardless of the next knot's mode.
            const pPrev = (i > 0) ? points[idx - dim] : p;
            const pNext = (i < n - 1) ? points[idx + dim] : p;
            mIn = (p - pPrev);
            mOut = (pNext - p);
          }} else if (mode === KF_STEPPED) {{
            // Hold: zero tangents; the outgoing segment value is held flat
            // at p0 by evaluate()'s stepped branch (a step until next t).
            mIn = 0; mOut = 0;
          }} else if (mode === KF_AUTOMATIC) {{
            // Catmull at FULL smoothness regardless of the path's global
            // smoothness slider (an explicit per-key "smooth" choice).
            mIn = tangent * inScale;
            mOut = tangent * outScale;
          }} else if (mode === KF_AUTO_CLAMPED) {{
            // Catmull (full smoothness) but clamp so the segment can't
            // overshoot the adjacent knot value range (kills the bulge —
            // the editor default). Local extremum (this knot is above OR
            // below BOTH neighbors) ⇒ flatten (Blender auto-clamped);
            // otherwise cap each tangent at 3× the nearer secant so
            // neither half-segment overshoots its end value.
            mIn = tangent * inScale;
            mOut = tangent * outScale;
            const pPrev = (i > 0) ? points[idx - dim] : p;
            const pNext = (i < n - 1) ? points[idx + dim] : p;
            if ((p - pPrev) * (pNext - p) <= 0) {{
              mIn = 0; mOut = 0;
            }} else {{
              const lim = 3 * Math.min(Math.abs(p - pPrev), Math.abs(pNext - p));
              if (Math.abs(mIn) > lim) mIn = (mIn < 0 ? -lim : lim);
              if (Math.abs(mOut) > lim) mOut = (mOut < 0 ? -lim : lim);
            }}
          }} else if (mode === KF_BEZIER) {{
            // Draggable handles are a later phase. With explicit world-space
            // in_tan/out_tan, map them onto the pos.xyz tangents (dims 0-2;
            // the spline tangent convention IS a value-delta, so the handle
            // vector components ARE the tangents); quat/fov + the no-handle
            // case fall back to `automatic`.
            mIn = tangent * inScale;
            mOut = tangent * outScale;
            if (j < 3 && km && km.in_tan && km.in_tan.length === 3) mIn = km.in_tan[j];
            if (j < 3 && km && km.out_tan && km.out_tan.length === 3) mOut = km.out_tan[j];
          }}
          knots[idx * 3] = mIn;
          knots[idx * 3 + 1] = p;
          knots[idx * 3 + 2] = mOut;
        }}
      }}
      return knots;
    }}
    static fromPoints(times, points, smoothness = 1, meta) {{
      return new CubicSpline(times, CubicSpline.calcKnots(times, points, smoothness, meta), meta);
    }}
    static fromPointsLooping(length, times, points, smoothness = 1, meta) {{
      if (times.length < 2) return CubicSpline.fromPoints(times, points, smoothness, meta);
      const dim = points.length / times.length;
      const newTimes = times.slice();
      const newPoints = points.slice();
      // `meta` is reordered EXACTLY parallel to times/points so the phantom
      // wrap knots inherit their real keyframe's interp mode (loop C1).
      const newMeta = meta ? meta.slice() : null;
      newTimes.push(length + times[0], length + times[1]);
      newPoints.push(...points.slice(0, dim * 2));
      if (newMeta) newMeta.push(meta[0], meta[1]);
      newTimes.splice(0, 0, times[times.length - 2] - length, times[times.length - 1] - length);
      newPoints.splice(0, 0, ...points.slice(points.length - dim * 2));
      if (newMeta) newMeta.splice(0, 0, meta[meta.length - 2], meta[meta.length - 1]);
      return CubicSpline.fromPoints(newTimes, newPoints, smoothness, newMeta);
    }}
  }}

  // Per-keyframe interp metadata for one spline knot, or null when the
  // keyframe carries no (recognised) `interp` ⇒ the spline uses the
  // EXISTING global-smoothness path for that knot, byte-for-byte
  // unchanged. ABSENT and any unknown/invalid string both map to null
  // (defensive: never throws, never NaN; schema membership is convention
  // only, never enforced in JS).
  const _VALID_INTERP = {{ auto_clamped: 1, automatic: 1, linear: 1,
                          bezier: 1, stepped: 1 }};
  function _kfMeta(kf) {{
    const m = (kf && typeof kf.interp === 'string'
               && _VALID_INTERP[kf.interp]) ? kf.interp : null;
    if (!m) return null;
    return {{ interp: m,
             in_tan: (Array.isArray(kf.in_tan) && kf.in_tan.length === 3)
               ? kf.in_tan : null,
             out_tan: (Array.isArray(kf.out_tan) && kf.out_tan.length === 3)
               ? kf.out_tan : null }};
  }}

  function buildPlayer(p) {{
    const sortedKfs = (p.keyframes || []).slice().sort((a, b) => (a.t || 0) - (b.t || 0));
    if (sortedKfs.length < 2) return null;
    const times = []; const points = []; const sourceKf = []; const meta = [];
    let acc = 0;
    let anyMeta = false;
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
      const km = _kfMeta(kf);
      if (km) anyMeta = true;
      times.push(tBase);
      points.push(kf.pos[0], kf.pos[1], kf.pos[2], q[0], q[1], q[2], q[3], fov);
      sourceKf.push(i); meta.push(km);
      if (kf.hold_s && kf.hold_s > 0) {{
        times.push(tBase + kf.hold_s);
        points.push(kf.pos[0], kf.pos[1], kf.pos[2], q[0], q[1], q[2], q[3], fov);
        sourceKf.push(i);
        // Hold tail re-uses the SAME interp as its source knot so the held
        // segment behaves consistently (e.g. a stepped+hold stays stepped).
        meta.push(km);
        acc += kf.hold_s;
      }}
    }}
    const smoothness = (typeof p.smoothness === 'number') ? p.smoothness : 1.0;
    const playSpeed = (typeof p.play_speed === 'number' && p.play_speed > 0) ? p.play_speed : 1.0;
    const duration = times[times.length - 1];
    // Pass `meta` ONLY when at least one keyframe has a recognised interp;
    // otherwise pass undefined so the spline takes the byte-identical legacy
    // path (no behavior change for the existing scenes).
    const sMeta = anyMeta ? meta : undefined;
    const spline = p.loop
      ? CubicSpline.fromPointsLooping(duration, times, points, smoothness, sMeta)
      : CubicSpline.fromPoints(times, points, smoothness, sMeta);
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
  // Tab-background pause: timestamp the path-player clock was frozen at
  // (0 = not currently hidden). The per-frame advance is raw
  // `performance.now() - _t0`, which keeps marching while the tab is
  // backgrounded and rAF is paused; without rebasing _t0 the camera would
  // TELEPORT the whole hidden interval down the spline on return. See the
  // visibilitychange handler below.
  let _hidAt = 0;

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
    // Route the existing camera-ownership through InteractionManager
    // (Task 0). `_player` stays the live per-handler gate so every
    // `if (_player) return` is byte-identical; this just mirrors the
    // same ownership into the single queryable broker.
    InteractionManager.requestPointer('player');
  }}
  function stopPath() {{
    _player = null; _activePathId = null; _lastTriggeredAnnotation = null;
    controls.enabled = true;
    InteractionManager.releasePointer('player');
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
  // Pause (don't teleport) the path player when the tab is backgrounded.
  // The per-frame advance is `(performance.now() - _t0)/1000 * speed`;
  // performance.now() keeps advancing while the tab is hidden but rAF
  // (and thus the tick() camera write) is paused, so on return the raw
  // delta would have grown by the whole hidden interval and the camera
  // would jump that many seconds down the spline. Rebasing _t0 by the
  // hidden duration cancels exactly that gap → playback RESUMES where it
  // paused. Scoped strictly to the path-player clock: it only adjusts
  // _t0, only while a path is actually playing (`_player` truthy — the
  // same gate every `if (_player)` reads); bench/scrub/free-look clocks
  // are untouched. A no-op when nothing is playing. No existing
  // visibilitychange listener to unify with (the only document/window
  // visibility hooks are the `blur` key/look resets, a different
  // concern), so this is the single owner of this event.
  document.addEventListener('visibilitychange', () => {{
    if (!_player) {{ _hidAt = 0; return; }}  // not playing → harmless no-op
    if (document.hidden) {{
      // Going hidden: freeze the clock reference (only the first hidden
      // event in a hidden streak counts; later ones keep the original).
      if (!_hidAt) _hidAt = performance.now();
    }} else if (_hidAt) {{
      // Becoming visible again: advance _t0 by exactly the time spent
      // hidden so (performance.now() - _t0) is unchanged across the gap.
      _t0 += performance.now() - _hidAt;
      _hidAt = 0;
    }}
  }});
  if (cfg.default_path_id) {{
    // Task 13: the default-path tour used to auto-start HERE, synchronously
    // at init (so the camera flew while still hidden behind the loading
    // screen). It is now deferred into _introStartTour() (just below) and
    // OWNED by the intro controller: in the cinematic end-user path it runs
    // AFTER the intro fade-out; for intro.type="none" / non-usermode it
    // runs straight away (same timing as before for those modes). This
    // `if` is kept (anchor-stable, intentionally inert now) so the byte-
    // lock region START stays on a line that pre-exists unchanged.
    selEl.value = cfg.default_path_id;
  }}

  // ============================================================
  //  ClipPlayer (Task 14 -- multi-camera Camera-Cuts tour)
  // ------------------------------------------------------------
  //  Generalises the single deferred default-path tour into an
  //  ORDERED clip sequence over virtual cameras. Data model
  //  (core/scene_cuts.py, plan SS-C):
  //    cfg.cameras = [{{ id, name, path_id, orbit_pivot? }}]
  //    cfg.clips   = [{{ id, camera_id, clip_start, duration, in }}]
  //  Each clip plays its camera's `path_id` sampled from `clip.in`
  //  for `clip.duration`, then HARD-CUTS (instant pose snap, no
  //  blend) to the next clip. NO cfg.clips  ->  EXACT pre-Task-14
  //  behaviour: one implicit clip == startPath(cfg.default_path_id)
  //  (today's single-tour autostart, byte-behaviourally identical;
  //  a hard-required regression). Reuses buildPlayer/sampleAt (the
  //  SuperSplat cubic-Hermite spline, lockstep with the editor) --
  //  no spline math is reimplemented here. Registers as an
  //  OverlayScene layer + an InteractionManager 'player' owner
  //  (Task 0): the layer's update() is the SOLE clip-boundary
  //  authority (it does NOT add a parallel render hook). Clip
  //  ordering consumes the JS mirror of scene_cuts.ordered_clips
  //  (ascending clip_start, stable, input not mutated).
  //
  //  Hard-cut mechanics (no render-loop edit, no stopPath wrap):
  //  per clip a clip-bounded RETIMED path is synthesised from the
  //  camera's path keyframes (slice [clip.in, clip.in+duration],
  //  retimed to start at t=0) and fed to the existing buildPlayer,
  //  so its `.duration` == clip.duration and the existing render
  //  loop auto-ends it (`tNow > _player.duration`) at exactly the
  //  clip boundary -- showing clip A's final pose for that one
  //  frame. The OverlayScene update() (runs every frame, AFTER the
  //  render-loop _player block) detects that auto-stop transition
  //  (_player went null while a sequence is active) and starts the
  //  NEXT clip the same frame, so clip B's start pose is written on
  //  the very next frame. That <=1-frame hold of A's last pose IS
  //  the hard cut (a discontinuous pose snap with zero tween) -- it
  //  is instantaneous and intentionally NOT blended. Gated by
  //  `!_benchActive` (a bench fully owns the camera -> no advance)
  //  and `_clipUserStopped` (the Stop button ends the tour, it does
  //  not advance) so only the natural clip-end advances.
  // ============================================================
  // JS mirror of core.scene_cuts.ordered_clips: ascending
  // clip_start, input list NOT mutated (slice() first).
  function _orderedClips(clips) {{
    return (clips || []).slice().sort(
      (a, b) => ((a && a.clip_start) || 0) - ((b && b.clip_start) || 0));
  }}
  const _clipCameras = Array.isArray(cfg.cameras) ? cfg.cameras : [];
  const _clipSeq = _orderedClips(
    Array.isArray(cfg.clips) ? cfg.clips : []);
  // A scene is multi-clip only when BOTH cameras and >=1 clip are
  // present; otherwise the degenerate single-tour path runs (the 6
  // live scenes have neither -> byte-behaviourally unchanged).
  const _clipMode = _clipCameras.length > 0 && _clipSeq.length > 0;
  let _clipState = {{ active: false, idx: -1, clip: null }};
  let _clipUserStopped = false;
  // Test/extension surface (mirrors window.__sp / __sceneview): lets
  // the harness assert clip scheduling + prewarm/guard lifecycle.
  // Harmless, always on.
  try {{
    window.__clip = {{
      get mode() {{ return _clipMode; }},
      get state() {{ return _clipState; }},
      clips: _clipSeq,
      cameras: _clipCameras,
      get prewarm() {{ return _clipPrewarm; }},
      // TEST-ONLY deterministic restart (Playwright drives the live
      // ClipPlayer under a virtual clock -- the auto-started tour may
      // already be mid/-past-sequence by the time the harness attaches,
      // which is non-deterministic w.r.t. CDN load time). Re-runs the
      // sequence from clip 0 NOW so the harness gets a controlled t=0
      // start under the frozen clock. No-op when not in clip mode.
      // _clipStart is a hoisted function declaration so it is callable
      // here even though it is defined textually below.
      restart() {{
        if (!_clipMode) return false;
        _clipUserStopped = false;
        _clipPrewarmRelease();
        _clipStart(0);
        return true;
      }},
    }};
  }} catch (e) {{}}

  // Resolve a clip -> its camera -> that camera's camera_paths entry.
  function _clipPath(clip) {{
    if (!clip) return null;
    const cam = _clipCameras.find(c => c && c.id === clip.camera_id);
    if (!cam) return null;
    return (cfg.camera_paths || []).find(p => p && p.id === cam.path_id)
           || null;
  }}
  // Synthesise a clip-bounded, retimed sub-path: keep only the
  // keyframes inside [in, in+duration] (plus the bracketing keys so
  // the spline still has its surrounding control points) and shift
  // them so the clip starts at t=0. `buildPlayer` then yields a
  // player whose `.duration` == clip.duration with correct spline /
  // times / sourceKf so sampleAt(player, 0-based tNow) and the
  // annotation trigger work exactly like a normal path. If the
  // window has < 2 keys we synthesise a 2-key hold at the boundary
  // so a degenerate clip still snaps cleanly (never extrapolates).
  function _buildClipPlayer(clip) {{
    const path = _clipPath(clip);
    if (!path) return null;
    const inT = (typeof clip.in === 'number' && clip.in > 0) ? clip.in : 0;
    const dur = (typeof clip.duration === 'number' && clip.duration > 0)
      ? clip.duration : 0;
    if (dur <= 0) return null;
    // Build the SOURCE path's player once (the real SuperSplat cubic-
    // Hermite spline over the full path), then RESAMPLE it uniformly
    // across the clip window [in, in+duration] into a dense retimed
    // keyframe set whose own t runs 0..duration. This guarantees the
    // returned player's `.duration` is EXACTLY clip.duration (so the
    // existing render-loop auto-stop fires at precisely the clip
    // boundary regardless of where the source keyframes sit) and the
    // pose at clip-relative t == the source path's pose at (in + t)
    // -- the spline math is reused verbatim, never reimplemented. The
    // hold-tail copy in buildPlayer is harmless here (we feed plain
    // dense keys, no hold_s). ~24 samples/s keeps the resampled curve
    // visually indistinguishable from the source spline for any sane
    // clip while staying cheap (a short clip => few keys).
    const srcPlayer = buildPlayer(path);
    let player = null;
    if (srcPlayer) {{
      const SAMPLES_PER_S = 24;
      const n = Math.max(2, Math.ceil(dur * SAMPLES_PER_S));
      const keys = [];
      for (let i = 0; i <= n; i++) {{
        const ct = (i / n) * dur;            // clip-relative time
        const s = sampleAt(srcPlayer, inT + ct);
        keys.push({{
          t: ct,
          pos: [s.pos[0], s.pos[1], s.pos[2]],
          quat: [s.quat[0], s.quat[1], s.quat[2], s.quat[3]],
          fov: s.fov,
        }});
      }}
      player = buildPlayer({{
        id: 'clip:' + (clip.id || '?'), name: 'clip', loop: false,
        // The dense resample already encodes the curve shape; a
        // straight (smoothness 0) re-spline through it reproduces it
        // faithfully and avoids double-smoothing overshoot.
        smoothness: 0.0, play_speed: 1.0,
        keyframes: keys,
      }});
    }}
    if (!player) {{
      // Source path unbuildable (< 2 keys): hold the camera's first
      // pose for the clip duration so the clip still hard-cuts cleanly
      // (a constant 2-key player; never extrapolates).
      const k0 = ((path.keyframes || [])[0]) ||
        {{ pos: [0, 0, 0], quat: [0, 0, 0, 1], fov: 60 }};
      const q0 = (k0.quat && k0.quat.length === 4)
        ? k0.quat : [0, 0, 0, 1];
      const f0 = (typeof k0.fov === 'number') ? k0.fov : 60;
      player = buildPlayer({{
        id: 'clip:' + (clip.id || '?'), name: 'clip', loop: false,
        smoothness: 0.0, play_speed: 1.0,
        keyframes: [
          {{ t: 0, pos: k0.pos, quat: q0, fov: f0 }},
          {{ t: dur, pos: k0.pos, quat: q0, fov: f0 }},
        ],
      }});
    }}
    return player;
  }}
  // Start clip `idx` (drives the same _player/_t0/controls path the
  // bench launchers use directly -- NOT startPath, which is hard-
  // wired to cfg.camera_paths/cfg.default_path_id). On a missing /
  // unbuildable clip, skip forward so one bad clip can't wedge the
  // whole tour; if none remain, finalise.
  function _clipStart(idx) {{
    while (idx < _clipSeq.length) {{
      const clip = _clipSeq[idx];
      const player = _buildClipPlayer(clip);
      if (player) {{
        _player = player;
        _t0 = performance.now();
        _activePathId = 'clip:' + (clip.id || idx);
        _lastTriggeredAnnotation = null;
        controls.enabled = false;
        InteractionManager.requestPointer('player');
        _clipState = {{ active: true, idx: idx, clip: clip }};
        // A new clip just became current -> the previous clip's
        // prewarm pin is no longer needed: RELEASE immediately so
        // only ever ONE next-cut set is pinned at a time.
        _clipPrewarmRelease();
        console.info('[Splatpipe] clip', idx + 1, '/', _clipSeq.length,
          '- camera', clip && clip.camera_id, '- dur',
          clip && clip.duration);
        return;
      }}
      console.warn('[Splatpipe] clip', idx, 'unresolvable -- skipping');
      idx++;
    }}
    _clipFinish();
  }}
  function _clipFinish() {{
    _clipState = {{ active: false, idx: -1, clip: null }};
    _clipPrewarmRelease();
    if (_player) stopPath();   // last clip ended -> normal teardown
  }}

  // ---- Next-cut LOD pre-warm (Task 14 Step B) ----
  // PREFETCH_LEAD_S before the current clip ends, pick the next
  // NOT-yet-resident clip (NOT strictly idx+1 -- a clip shorter than
  // the lead may already be resident; we want the next one whose
  // start-pose chunks are still missing), build its player, and on a
  // throttled ~400 ms cadence (mirrors the orbit-walk's
  // ORBIT_SAMPLE_DWELL_MS) set spark.lodPosOverride/Quat to
  // sampleAt(nextPlayer, 0) for a single LoD traversal so Spark's
  // own driveFetchers enqueues that pose's chunks. The live tour
  // camera still drives EVERY other frame (the player tick never
  // sets the override -> no contention; _autoFocusTick already self-
  // clears the override while _player is active). The chunks are
  // RETAINED by the driveFetchers-wrap guard-twin installed beside
  // the root-chunk guard (look for __spClipPrewarmGuard); this just
  // declares the pose + the chunk set to pin. Released immediately
  // after the cut by _clipStart (only one next-cut set ever pinned).
  // ?prefetchLead=N overrides the lead (same pattern as ?focusAhead=
  // / ?budget=). _clipTier lets ?tier=phone exercise the mobile
  // path in Playwright without a real device (scoped to clip
  // prewarm only -- it does NOT override the global _deviceProfile).
  const _clipTier =
    new URLSearchParams(location.search).get('tier') ||
    _deviceProfile.tier;
  const _clipIsPhone = _clipTier === 'phone';
  const PREFETCH_LEAD_S = (() => {{
    const _pl = parseFloat(
      new URLSearchParams(location.search).get('prefetchLead'));
    if (Number.isFinite(_pl)) return Math.min(Math.max(_pl, 0), 30);
    return _clipIsPhone ? 1.5 : 2.5;   // shorter lead on phone
  }})();
  // Mobile mitigation: allow disabling prewarm on phone entirely if
  // an empirical real-scene Playwright phone-tier run shows pool
  // pressure (the project_spark_refetch_storm methodology). Until
  // that run, phone uses the bounded short-lead path; ?clipPrewarm=0
  // is the kill switch the empirical decision will pin if needed.
  const _clipPrewarmOff =
    new URLSearchParams(location.search).get('clipPrewarm') === '0';
  // Prewarm bookkeeping. `pose` (when non-null) is the next-cut
  // start-pose the override is parked at; `chunks` is the set the
  // guard-twin pins (snapshotted from fetchPriority while parked);
  // `phoneShallow` tells the guard-twin to pin only a coarse/root-
  // tier slice on phone (shallow traversal, mandatory mobile
  // mitigation). All cleared on release.
  let _clipPrewarm = {{
    active: false, pose: null, quat: null, nextIdx: -1,
    chunks: [], lastSampleMs: 0, phoneShallow: _clipIsPhone,
  }};
  function _clipPrewarmRelease() {{
    if (!_clipPrewarm.active && _clipPrewarm.pose === null) return;
    _clipPrewarm = {{
      active: false, pose: null, quat: null, nextIdx: -1,
      chunks: [], lastSampleMs: 0, phoneShallow: _clipIsPhone,
    }};
    // Stop driving the LoD override for the (now consumed) next cut.
    // _autoFocusTick re-owns the override once _player keeps driving;
    // we only clear OUR prewarm parking, never the live focus.
    if (_clipPrewarmDroveOverride) {{
      try {{ spark.lodPosOverride = undefined;
             spark.lodQuatOverride = undefined; }} catch (e) {{}}
      _clipPrewarmDroveOverride = false;
    }}
  }}
  let _clipPrewarmDroveOverride = false;
  let _clipNextPlayer = null;
  // True when the next not-yet-resident clip's start-pose chunks are
  // all already resident -> nothing to prewarm (handles a clip
  // shorter than the lead whose chunks the live camera already
  // fetched). Best-effort: if the pager surface is unavailable
  // (scene-less harness) we DON'T claim resident (return false) so
  // the scheduling path is still exercised + observable.
  function _clipPoseResident(pl) {{
    try {{
      const pager = spark.pager;
      if (!pager || !splat.paged || !pl) return false;
      // We cannot cheaply map an arbitrary pose -> its chunk ids
      // without Spark internals; treat "the next clip already had
      // its prewarm pin satisfied this cycle" as the resident
      // signal (the guard-twin sets _clipPrewarm.chunks once Spark
      // has enqueued them). Conservative: only true after a full
      // cadence parked on this pose with a non-empty pinned set all
      // resident.
      if (!_clipPrewarm.chunks.length) return false;
      return _clipPrewarm.chunks.every(c =>
        pager.getSplatsChunk &&
        pager.getSplatsChunk(splat.paged, c.chunk));
    }} catch (e) {{ return false; }}
  }}
  // Pick the next clip AFTER `fromIdx` whose start-pose is not yet
  // resident (NOT strictly fromIdx+1). Returns {{ idx, player }} or
  // null when there is no further clip to prewarm.
  function _clipPickNext(fromIdx) {{
    for (let j = fromIdx + 1; j < _clipSeq.length; j++) {{
      const pl = _buildClipPlayer(_clipSeq[j]);
      if (!pl) continue;
      if (_clipPoseResident(pl)) continue;   // already in cache -> skip
      return {{ idx: j, player: pl }};
    }}
    return null;
  }}
  // The clip-boundary authority + prewarm scheduler, fanned out from
  // the ONE OverlayScene.update() tick (Task 0) -- no parallel rAF.
  // No `modes` (it owns playback, not chrome) so OverlayScene never
  // touches visibility; node-less (pure logic layer).
  const _clipLayer = {{
    id: 'clip-player',
    update() {{
      if (!_clipMode || !_clipState.active) return;
      // (1) Detect the render loop's natural clip-end auto-stop.
      //     The render-loop _player block runs BEFORE this update();
      //     at the boundary it called stopPath() -> _player === null.
      //     A bench takeover / Stop button also nulls _player, but
      //     those must END the tour, not advance: gate on
      //     !_benchActive && !_clipUserStopped.
      if (!_player) {{
        if (_benchActive || _clipUserStopped) {{ _clipFinish(); return; }}
        // Natural clip end -> HARD CUT to the next clip (or finish).
        _clipStart(_clipState.idx + 1);
        return;
      }}
      // (2) Pre-warm scheduling. tNow is the SAME clock the render
      //     loop uses for this clip (_t0 reset per clip).
      if (_clipPrewarmOff) return;
      const clip = _clipState.clip;
      const dur = (clip && typeof clip.duration === 'number')
        ? clip.duration : 0;
      if (dur <= 0) return;
      const tNow = (performance.now() - _t0) / 1000;
      const remaining = dur - tNow;
      if (remaining > PREFETCH_LEAD_S) {{
        // Not in the lead window yet -> ensure no stale pin lingers.
        if (_clipPrewarm.active) _clipPrewarmRelease();
        return;
      }}
      // In the lead window: lock onto the next not-yet-resident clip.
      if (!_clipPrewarm.active) {{
        const pick = _clipPickNext(_clipState.idx);
        if (!pick) return;            // nothing further to prewarm
        _clipNextPlayer = pick.player;
        const s0 = sampleAt(_clipNextPlayer, 0);
        _clipPrewarm = {{
          active: true,
          pose: [s0.pos[0], s0.pos[1], s0.pos[2]],
          quat: [s0.quat[0], s0.quat[1], s0.quat[2], s0.quat[3]],
          nextIdx: pick.idx, chunks: [], lastSampleMs: 0,
          phoneShallow: _clipIsPhone,
        }};
      }}
      // Throttled ~400 ms cadence (mirrors ORBIT_SAMPLE_DWELL_MS):
      // park the LoD override at the next-cut start pose for a
      // single traversal so Spark's driveFetchers enqueues its
      // chunks. The player tick NEVER sets the override (no
      // contention); we only touch it here, briefly, for the next
      // cut. The guard-twin retains the resulting chunk set.
      const CLIP_PREWARM_DWELL_MS = 400;
      const nowMs = performance.now();
      if (nowMs - _clipPrewarm.lastSampleMs >= CLIP_PREWARM_DWELL_MS &&
          _clipPrewarm.pose) {{
        try {{
          if (!spark.lodPosOverride)
            spark.lodPosOverride = new THREE.Vector3();
          if (!spark.lodQuatOverride)
            spark.lodQuatOverride = new THREE.Quaternion();
          spark.lodPosOverride.set(
            _clipPrewarm.pose[0], _clipPrewarm.pose[1],
            _clipPrewarm.pose[2]);
          spark.lodQuatOverride.set(
            _clipPrewarm.quat[0], _clipPrewarm.quat[1],
            _clipPrewarm.quat[2], _clipPrewarm.quat[3]);
          _clipPrewarmDroveOverride = true;
        }} catch (e) {{}}
        _clipPrewarm.lastSampleMs = nowMs;
      }}
    }},
  }};
  OverlayScene.register(_clipLayer);

  // SAME autostart logic, called exactly once -- the `_introTourStarted`
  // guard makes any double-invoke a harmless no-op (e.g. the fade-done
  // path AND the hard-fallback timer both firing). There is NO second
  // autostart path: one function, one owner (the intro controller).
  // Task 14: when the scene declares cameras + clips it auto-starts
  // the CLIP SEQUENCE; otherwise it is the EXACT pre-Task-14 single
  // default-path tour (byte-behaviourally identical -- the hard-
  // required no-clips regression).
  let _introTourStarted = false;
  function _introStartTour() {{
    if (_introTourStarted) return;
    if (_clipMode) {{
      _introTourStarted = true;
      _clipUserStopped = false;
      _clipStart(0);
      return;
    }}
    if (!cfg.default_path_id) return;
    _introTourStarted = true;
    selEl.value = cfg.default_path_id;
    startPath(cfg.default_path_id);
  }}
  // The Stop button must END a clip tour (not advance to the next
  // clip). stopPath() nulls _player; without this the clip layer's
  // update() would treat that as a natural clip-end and resume. An
  // ADDITIONAL listener (addEventListener stacks; this runs after the
  // pre-existing `stopBtn -> stopPath` binding) records the user
  // intent so the next update() finalises instead of advancing.
  if (typeof stopBtn !== 'undefined' && stopBtn) {{
    stopBtn.addEventListener('click', () => {{
      if (_clipMode) {{ _clipUserStopped = true; }}
    }});
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
    const tierPick = _deviceProfile.appleSilicon ? 1_000_000 :
                     tier === 'phone' ? 500_000 :
                     tier === 'tablet' ? 1_000_000 :
                     2_000_000;  // discrete-GPU desktop default
    // Per-scene preferred budget (viewer-config `splat_budget`, default 0 =
    // unset). Some scenes (large-extent aerial captures like Polygraf) only
    // resolve well at a higher budget. Honored on a capable discrete-GPU
    // desktop ONLY — phones / tablets / Apple-Silicon keep their
    // measured-safe tier value (a 3 M scene tanks a phone), so a per-scene
    // bump never regresses constrained devices. The runtime dropdown +
    // ?budget= still override either way.
    const sceneWant = (typeof cfg.splat_budget === 'number' && cfg.splat_budget > 0)
      ? cfg.splat_budget : 0;
    const useScene = sceneWant > 0 && tier === 'desktop' && !_deviceProfile.appleSilicon;
    const target = useScene ? sceneWant : tierPick;
    console.info('[Splatpipe] device tier:', tier,
      '| splat budget:', target.toLocaleString(),
      useScene ? '(per-scene)' : '(tier default)');
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
      primaryAsset: _PRIMARY,
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

    // Keep InteractionManager's pointer-owner in sync with `_player`
    // for ALL camera-driving paths (the bench launchers + scrub set
    // `_player` directly, not via startPath). `_player` stays the one
    // live gate every `if (_player)` reads — this only mirrors the
    // same fact into the single queryable broker (nothing reads it in
    // T0, so behavior is byte-identical). One chokepoint instead of
    // touching every bench function.
    if (_player && InteractionManager.currentOwner() !== 'player') {{
      InteractionManager.requestPointer('player');
    }} else if (!_player && InteractionManager.currentOwner() === 'player') {{
      InteractionManager.releasePointer('player');
    }}

    // The ONE overlay tick (Task 0). No-op in T0 (no layers); later
    // features' per-frame overlay work fans out from here, not from
    // bespoke hooks in this loop.
    OverlayScene.update(_nowMs);

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

    // ---- Next-cut LOD pre-warm retention guard (Task 14 Step B) ----
    // A TWIN of the root-chunk eviction guard above, scoped to the
    // ClipPlayer's next-cut prewarm window. While _clipPrewarm.active
    // (the clip scheduler has parked spark.lodPosOverride at the next
    // cut's start pose -- see the ClipPlayer block), Spark's own
    // driveFetchers enqueues that pose's chunks; this wrap RETAINS
    // them so they cannot be evicted before the cut fires:
    //   1. Snapshot the chunks Spark is currently fetching for the
    //      paged splat into _clipPrewarm.chunks (the "next-cut chunk
    //      set"), capped on phone (shallow / coarse-tier only --
    //      mandatory mobile mitigation) so the 64-page phone pool is
    //      never overcommitted.
    //   2. Re-append any of that set still missing to the END of
    //      fetchPriority (END so it never preempts the LIVE tour
    //      camera's in-view detail -- identical policy to the root
    //      guard) so a transient drop is re-requested.
    //   3. After the real driveFetchers, drop those resident pages
    //      out of freeablePages so allocateFreeable() can't evict
    //      them before the cut.
    // Inert whenever _clipPrewarm.active is false (released the
    // instant the cut fires -> only ever ONE next-cut set pinned).
    // Single chained wrap (the root guard already rebound
    // driveFetchers; we wrap THAT) -- no second monkey-patch race.
    if (pager && typeof pager.driveFetchers === 'function' &&
        !pager.__spClipPrewarmGuard) {{
      const _prevDrive = pager.driveFetchers.bind(pager);
      // Phone shallow cap: pin at most this many prewarm chunks on
      // the phone tier (coarse coverage only) so the next-cut set
      // can never pressure the small mobile pool. Desktop/tablet
      // pin the full demanded set (ample pool).
      const CLIP_PREWARM_PHONE_MAX = 16;
      pager.driveFetchers = function() {{
        const pw = (typeof _clipPrewarm !== 'undefined') ? _clipPrewarm
                                                          : null;
        if (!pw || !pw.active || !splat.paged) {{ _prevDrive(); return; }}
        if (!this.fetchPriority) this.fetchPriority = [];
        // (1) Snapshot the next-cut chunk set: whatever Spark is
        //     currently fetching / has queued for the paged splat
        //     because the override is parked at the next-cut pose.
        const want = [];
        const seen = {{}};
        const _add = (sc) => {{
          if (!sc || sc.splats !== splat.paged) return;
          if (seen[sc.chunk]) return;
          seen[sc.chunk] = 1;
          want.push({{ splats: splat.paged, chunk: sc.chunk }});
        }};
        (this.fetchers || []).forEach(_add);
        (this.fetchPriority || []).forEach(_add);
        (this.fetched || []).forEach(_add);
        let pinSet = want;
        if (pw.phoneShallow && want.length > CLIP_PREWARM_PHONE_MAX) {{
          // Coarse/root-tier slice only (lowest chunk ids == top LoD
          // levels) -> shallow traversal retained on phone.
          pinSet = want.slice()
            .sort((a, b) => a.chunk - b.chunk)
            .slice(0, CLIP_PREWARM_PHONE_MAX);
        }}
        pw.chunks = pinSet;
        // (2) Re-append still-missing pinned chunks at the END so the
        //     LIVE tour camera keeps full priority + all fetch slots.
        for (let i = 0; i < pinSet.length; i++) {{
          const ch = pinSet[i].chunk;
          if (this.getSplatsChunk &&
              this.getSplatsChunk(splat.paged, ch)) continue;
          const queued =
            this.fetchPriority.some(
              p => p.splats === splat.paged && p.chunk === ch) ||
            (this.fetchers || []).some(
              f => f.splats === splat.paged && f.chunk === ch) ||
            (this.fetched || []).some(
              f => f.splats === splat.paged && f.chunk === ch);
          if (!queued)
            this.fetchPriority.push({{ splats: splat.paged, chunk: ch }});
        }}
        _prevDrive();
        // (3) Make resident pinned pages non-evictable until the cut.
        if (this.freeablePages && this.freeablePages.length &&
            pinSet.length) {{
          const pin = {{}};
          for (let i = 0; i < pinSet.length; i++)
            pin[pinSet[i].chunk] = 1;
          this.freeablePages = this.freeablePages.filter(pg => {{
            const sc = this.pageToSplatsChunk[pg];
            return !(sc && sc.splats === splat.paged && pin[sc.chunk]);
          }});
        }}
      }};
      pager.__spClipPrewarmGuard = true;
      console.info('[Splatpipe] next-cut prewarm retention guard active');
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

  // ============================================================
  //  Intro controller (Task 13 -- cinematic loading-blur + fade)
  // ------------------------------------------------------------
  //  The END-USER reveal (plan SS-A3). Integrates through the
  //  EXISTING scaffold, NOT a parallel mechanism:
  //   * mode gate = ModeManager (Task 0): the cinematic fade runs
  //     ONLY in usermode; embed/author keep the plain pre-Task-13
  //     loading screen + immediate tour (CSS already hides
  //     #loading-blur / #intro-fade outside usermode -- same
  //     body-class gating as the Task-12 dual-UI roots).
  //   * ready signal = the REAL one already in this viewer: the
  //     loading panel hides by `#loading` gaining the `hidden`
  //     class (set by the early-reveal IIFE on coarse coverage or
  //     its ~4 s hard cap, and again by the preload IIFE). We do
  //     NOT invent a splat-count threshold -- we observe that
  //     exact existing signal (MutationObserver + an initial
  //     check in case it already fired).
  //   * tour auto-start = the SAME _introStartTour() the old
  //     synchronous autostart became -- called once, here, after
  //     the fade (or immediately when there is no fade). No
  //     duplicate autostart path.
  //
  //  FAIL-SAFE (the single most important property -- a stuck
  //  opaque #intro-fade would hide the whole scene, the worst
  //  possible regression): the overlay is pointer-events:none in
  //  CSS from the start (never blocks input even mid-fade); after
  //  the fade it is ALSO set display:none; and a HARD FALLBACK
  //  timer clears it + starts the tour even if the ready signal
  //  never arrives. It can therefore NEVER permanently cover the
  //  scene. Defensive config parse: cfg.intro absent ->
  //  DEFAULT_INTRO {{type:'fade',ms:900}}; ms not a positive
  //  finite number -> 900; any unknown type -> behave as 'fade';
  //  type==='none' -> no fade, never show #intro-fade.
  // ============================================================
  (() => {{
    // --- defensive cfg.intro parse (mirrors core/scene_cuts.DEFAULT_INTRO)
    const _intro = (cfg && cfg.intro && typeof cfg.intro === 'object')
      ? cfg.intro : {{}};
    const _introType = (_intro.type === 'none') ? 'none' : 'fade';
    let _introMs = Number(_intro.ms);
    if (!isFinite(_introMs) || _introMs <= 0) _introMs = 900;  // DEFAULT_INTRO
    const _fadeEl = document.getElementById('intro-fade');
    const _loadEl = document.getElementById('loading');
    // The cinematic fade is the usermode-only end-user path. embed/author
    // keep the pre-Task-13 behaviour: no fade, tour starts immediately
    // (the CSS already keeps #intro-fade / #loading-blur hidden there).
    const _cinematic = ModeManager.is('user') && _introType !== 'none' && !!_fadeEl;

    if (!_cinematic) {{
      // No cinematic intro: belt-and-braces hide the overlay (type:'none'
      // or non-usermode) and start the tour straight away -- exactly the
      // old synchronous autostart timing for these modes.
      if (_fadeEl) {{ _fadeEl.classList.remove('faded'); _fadeEl.style.display = 'none'; }}
      _introStartTour();
      return;
    }}

    // Match the CSS transition duration to cfg.intro.ms.
    _fadeEl.style.setProperty('--intro-ms', _introMs + 'ms');

    let _done = false;
    // Clear the overlay so it can NEVER trap the scene, then start the
    // tour. Idempotent (guarded) -- safe to call from transitionend, the
    // post-fade timer AND the hard fallback.
    function _finish() {{
      if (_done) return;
      _done = true;
      // pointer-events:none is already set in CSS; display:none fully
      // removes it from hit-testing + paint. Both = unconditionally safe.
      _fadeEl.style.pointerEvents = 'none';
      _fadeEl.style.display = 'none';
      _introStartTour();
    }}

    // Begin the fade once the REAL ready signal has fired, then finish
    // after the fade completes.
    let _fadeStarted = false;
    function _beginFade() {{
      if (_fadeStarted || _done) return;
      _fadeStarted = true;
      // Trigger the CSS opacity 1->0 transition.
      _fadeEl.classList.add('faded');
      // Finish on transitionend OR a timer (transitionend can be missed
      // if the tab is backgrounded mid-fade / the property is coalesced);
      // +120 ms slack over _introMs so the visual fade fully completes
      // before we display:none it.
      const _onEnd = (e) => {{
        if (e && e.propertyName && e.propertyName !== 'opacity') return;
        _fadeEl.removeEventListener('transitionend', _onEnd);
        _finish();
      }};
      _fadeEl.addEventListener('transitionend', _onEnd);
      setTimeout(_finish, _introMs + 120);
    }}

    // The ready signal == `#loading` gaining the `hidden` class (the
    // existing, real signal -- not invented). Observe it; also check
    // immediately in case it already fired before this ran.
    const _isReady = () =>
      !_loadEl || _loadEl.classList.contains('hidden');
    if (_isReady()) {{
      _beginFade();
    }} else {{
      const _obs = new MutationObserver(() => {{
        if (_isReady()) {{ _obs.disconnect(); _beginFade(); }}
      }});
      _obs.observe(_loadEl, {{ attributes: true, attributeFilter: ['class'] }});
    }}

    // HARD FALLBACK -- the absolute guarantee. If the ready signal never
    // arrives (e.g. an upstream stall), clear the overlay + start the
    // tour anyway so the scene is NEVER permanently covered. Generous
    // (the loading panel's own hard cap is ~4 s; the preload outer cap
    // ~12 s) -- this only fires on a genuine failure of the normal path.
    setTimeout(() => {{
      if (!_done) {{
        console.warn('[Splatpipe] intro: hard fallback -- forcing fade clear');
        _finish();
      }}
    }}, 20000);
  }})();

  tick();

  // Debug hook for Playwright smoke tests (same pattern as PC viewer)
  window._spDebug = {{ camera, scene, splat, controls, renderer, spark }};
  </script>
</body>
</html>
"""
