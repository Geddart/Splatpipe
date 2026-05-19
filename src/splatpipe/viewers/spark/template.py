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
    // A clip tour also owns the LoD origin for the WHOLE tour including
    // the single inter-clip cut-transition frame: stopPath() nulls
    // _player ONE frame before _clipLayer.update() starts the next clip,
    // so without this disjunct _autoFocusTick would raycast the stale
    // pose and write spark.lodPosOverride for ~1 frame, contending with
    // the clip layer's LoD ownership. The 6 live single-camera scenes
    // have no cameras/clips so _clipMode is false there (this disjunct
    // is always false) -> byte-runtime-identical to before for them.
    if (_player || BENCH_AUTO || (_clipMode && _clipState.active)) {{ _afClear(); return; }}
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

  // ============================================================
  //  End-user transport (Task 15 -- click-interrupt + bottom
  //  resume + per-shot idle auto-orbit; plan SS-A3 / D-Task-11)
  // ------------------------------------------------------------
  //  The cinematic end-user shell's interaction layer. END-USER
  //  MODE ONLY (ModeManager.is('user')): author (?author=1) +
  //  embed are byte-runtime-unchanged -- every entry point below
  //  bails immediately when not usermode, so the editor/iframe
  //  paths and the 6 live single-camera scenes (if they ever
  //  carry a default_path_id tour) are never perturbed by this.
  //  Reuses existing primitives, never reinvents:
  //    * stopTour()    = the existing stop path (stopPath() +
  //      the _clipUserStopped/_clipFinish teardown the Stop
  //      button already drives) -- NOT a new stop mechanism.
  //    * the orbit MATH = the SAME _buildOrbitPath() Y-spin,
  //      factored into _orbitPathAround(center,...) below and
  //      called by BOTH _buildOrbitPath (refactored to delegate,
  //      byte-behaviourally identical for the bench) and the
  //      idle auto-orbit (anchored to the active cut's authored
  //      orbit_pivot) -- ONE orbit implementation, not a copy.
  //    * buildPlayer/sampleAt = the SuperSplat cubic-Hermite
  //      spline, lockstep with the editor (no spline math here).
  //    * Task-0 scaffold: the idle CHECK fans out from the ONE
  //      OverlayScene.update() tick (no parallel rAF); pointer
  //      ownership goes through InteractionManager; the bottom
  //      play control lives in the Task-12 #user-transport root
  //      (CSS-gated to usermode already), styled inline like the
  //      existing #sp-hud (no new CSS region).
  //  Behaviour (spec, precise):
  //   1. INTERRUPT: a pointerdown/drag on the canvas while the
  //      auto tour is playing -> stopTour() (controls.enabled=
  //      true so the user free-looks) + reveal #user-play. Works
  //      in clip-mode AND the degenerate single default_path_id
  //      tour.
  //   2. RESUME: clicking #user-play resumes the tour from the
  //      NEAREST CUT <= the current playhead -- clip-mode: the
  //      clip whose clip_start is the greatest <= the playhead
  //      captured at interrupt; single-tour: that one implicit
  //      clip's start (= restart the default path; its only cut
  //      <= playhead is its start). #user-play re-hides while
  //      playing.
  //   3. PER-SHOT IDLE AUTO-ORBIT: an idle timer reset on ANY
  //      user input AND on every cut change (= per shot). If no
  //      input for IDLE_MS while parked on a shot, drive a slow
  //      LOOPING orbit (the reused math) around the active cut's
  //      camera's authored orbit_pivot. Any input cancels the
  //      orbit (and re-reveals #user-play to resume the tour).
  //      ONLY clip-mode (orbit_pivot is a per-camera field; a
  //      single-tour / the 6 live scenes have no cameras -> no
  //      pivot is ever invented, no idle orbit there).
  //  ?idleMs=N overrides IDLE_MS (TEST-ONLY shortened idle for
  //  the scene-less Playwright harness; same ?-override pattern
  //  as ?focusAhead= / ?prefetchLead=). Clamped >= 200 ms.
  // ============================================================
  const IDLE_MS = (() => {{
    const _im = parseFloat(
      new URLSearchParams(location.search).get('idleMs'));
    return Number.isFinite(_im) ? Math.max(_im, 200) : 12000;
  }})();

  // The SHARED programmatic-orbit builder. IDENTICAL math to the
  // bench _buildOrbitPath (which now delegates here): spin a base
  // camera pose around the world-vertical axis through `center`,
  // preserving the pose's real radius/height/orientation, N+1
  // keyframes over `secs` seconds. `loop` lets the idle orbit
  // keep circling until input; the bench passes loop:false.
  // Hoisted (function declaration) so the textually-later
  // _buildOrbitPath in the Bench-launchers block can call it
  // (same scope; same forward-reference-via-hoisting pattern the
  // existing _clipStart/_clipPrewarmRelease pair already uses).
  function _orbitPathAround(center, fromPos, fromQuat, fov,
                            opts) {{
    const o = opts || {{}};
    const N = (typeof o.n === 'number' && o.n > 0) ? o.n : 36;
    const secs = (typeof o.secs === 'number' && o.secs > 0)
      ? o.secs : 30;
    const loop = !!o.loop;
    const off = fromPos.clone().sub(center);
    // Only the truly-degenerate cam==center fallback (same 0.5 m
    // floor + (0,1,-3) offset the bench has always used).
    if (off.length() < 0.5) off.set(0, 1, -3);
    const baseQ = fromQuat.clone();
    const upY = new THREE.Vector3(0, 1, 0);
    const keyframes = [];
    for (let i = 0; i <= N; i++) {{
      const theta = (i / N) * Math.PI * 2;
      const rot = new THREE.Quaternion().setFromAxisAngle(upY, theta);
      const p = off.clone().applyQuaternion(rot).add(center);
      const q = rot.clone().multiply(baseQ);   // rotate the authored orientation by the same Y angle
      keyframes.push({{
        t: (i / N) * secs,
        pos: [p.x, p.y, p.z],
        quat: [q.x, q.y, q.z, q.w],
        fov: fov,
      }});
    }}
    return {{
      id: 'orbit', name: 'Programmatic Orbit',
      loop: loop, smoothness: 1.0, play_speed: 1.0,
      keyframes,
    }};
  }}

  // The shot the end-user is currently parked on (the clip/camera
  // that was playing when the tour was interrupted, kept fresh on
  // every cut while the tour plays). Drives WHICH camera's
  // orbit_pivot the idle auto-orbit circles. Cleared on resume /
  // when no tour context exists. clip-mode only.
  let _activeShot = null;     // {{ clip, camera, pivot:Vector3|null, playhead }}
  let _userInterrupted = false;   // true once the user broke the tour
  let _idleOrbiting = false;      // true while the idle auto-orbit drives
  let _lastInputMs = performance.now();

  // Resolve a clip -> its camera record -> that camera's
  // orbit_pivot (a world-space [x,y,z] or absent). Returns the
  // camera + a THREE.Vector3 pivot (or null when unauthored).
  function _shotFor(clip) {{
    if (!clip) return null;
    const cam = _clipCameras.find(c => c && c.id === clip.camera_id)
      || null;
    let pivot = null;
    if (cam && Array.isArray(cam.orbit_pivot) &&
        cam.orbit_pivot.length === 3) {{
      pivot = new THREE.Vector3(
        cam.orbit_pivot[0], cam.orbit_pivot[1], cam.orbit_pivot[2]);
    }}
    return {{ clip: clip, camera: cam, pivot: pivot }};
  }}
  // The global tour playhead RIGHT NOW (seconds). clip-mode: the
  // active clip's clip_start + elapsed within the clip (each
  // clip's _t0 is reset per clip, so (now-_t0) is clip-relative).
  // Single-tour: the player's own elapsed. 0 when nothing plays.
  function _tourPlayhead() {{
    if (!_player) return 0;
    const speed = _player.playSpeed || 1.0;
    const tRel = ((performance.now() - _t0) / 1000) * speed;
    if (_clipMode && _clipState.active && _clipState.clip) {{
      const cs = (typeof _clipState.clip.clip_start === 'number')
        ? _clipState.clip.clip_start : 0;
      return cs + Math.max(0, tRel);
    }}
    return Math.max(0, tRel);
  }}

  // The bottom resume control. Lives in the Task-12
  // #user-transport root (always in the DOM, CSS-gated to
  // usermode + embed-stripped already) so there is no new CSS
  // region; styled inline exactly like the existing #sp-hud.
  // Hidden until the user interrupts; click -> resume.
  const _userTransport = document.getElementById('user-transport');
  let _userPlayBtn = null;
  if (_userTransport) {{
    _userPlayBtn = document.createElement('button');
    _userPlayBtn.id = 'user-play';
    _userPlayBtn.type = 'button';
    _userPlayBtn.textContent = 'Resume tour';
    _userPlayBtn.setAttribute('aria-label', 'Resume tour');
    _userPlayBtn.style.cssText =
      'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);'
      + 'z-index:150;display:none;cursor:pointer;'
      + 'background:rgba(0,0,0,.62);color:#fff;'
      + 'font:600 14px/1 -apple-system,BlinkMacSystemFont,'
      + "'Segoe UI',sans-serif;"
      + 'padding:11px 22px;border:1px solid rgba(255,255,255,.28);'
      + 'border-radius:999px;backdrop-filter:blur(6px);';
    _userTransport.appendChild(_userPlayBtn);
    _userPlayBtn.addEventListener('click', (e) => {{
      e.preventDefault();
      e.stopPropagation();
      _resumeTour();
    }});
  }}
  function _showUserPlay(show) {{
    if (_userPlayBtn) _userPlayBtn.style.display = show ? '' : 'none';
  }}

  // Is the AUTO tour (not a bench, not the idle orbit) currently
  // driving the camera? = a player is live, no bench owns it, and
  // either a clip is active or the single default-path tour runs.
  function _tourPlaying() {{
    if (!_player || _benchActive) return false;
    if (_idleOrbiting) return false;
    if (_clipMode) return _clipState.active;
    return _activePathId === cfg.default_path_id &&
           !!cfg.default_path_id;
  }}

  // stopTour() -- the spec's named stop, built from the EXISTING
  // teardown (NOT a new mechanism). clip-mode: set the same
  // _clipUserStopped the Stop button sets (so the clip layer
  // finalises instead of advancing) then _clipFinish() (which
  // itself calls stopPath() -> controls.enabled=true, releases
  // the InteractionManager 'player' owner, immediate camera
  // halt). single-tour: stopPath() directly. Idempotent.
  function _stopTour(opts) {{
    const o = opts || {{}};
    if (!_player && !_clipState.active) return;
    // Snapshot the shot + playhead BEFORE teardown nulls them, so
    // resume can pick the nearest cut <= where we were and the
    // idle orbit knows which camera's pivot to circle.
    if (_clipMode && _clipState.active && _clipState.clip) {{
      _activeShot = _shotFor(_clipState.clip);
      if (_activeShot) _activeShot.playhead = _tourPlayhead();
    }}
    if (_clipMode) {{
      _clipUserStopped = true;
      _clipFinish();              // -> stopPath() if a clip player is live
    }} else if (_player) {{
      stopPath();
    }}
    // Pointer ownership: the user is taking the canvas back from
    // the 'player' owner. stopPath() already released it; mirror
    // the user's free-look intent through the single broker.
    InteractionManager.releasePointer('player');
    if (o.byUser !== false) _userInterrupted = true;
    _lastInputMs = performance.now();
    if (o.reveal !== false) _showUserPlay(true);
  }}

  // resumeTour() -- restart the tour from the NEAREST CUT <= the
  // playhead captured at interrupt. clip-mode: the clip whose
  // clip_start is the greatest <= that playhead (_clipSeq is
  // ascending by clip_start -- _orderedClips). single-tour: the
  // one implicit clip's start == restart the default path (its
  // only cut <= the playhead is its start). Re-hides #user-play.
  function _resumeTour() {{
    if (!ModeManager.is('user')) return;
    _cancelIdleOrbit({{ silent: true }});
    _userInterrupted = false;
    _showUserPlay(false);
    _lastInputMs = performance.now();
    if (_clipMode) {{
      const ph = (_activeShot && typeof _activeShot.playhead === 'number')
        ? _activeShot.playhead : 0;
      // greatest clip_start <= ph (nearest cut at-or-before the
      // playhead); fall back to clip 0 if ph precedes the first.
      let idx = 0;
      for (let j = 0; j < _clipSeq.length; j++) {{
        const cs = (_clipSeq[j] && typeof _clipSeq[j].clip_start === 'number')
          ? _clipSeq[j].clip_start : 0;
        if (cs <= ph) idx = j; else break;
      }}
      _clipUserStopped = false;
      _clipPrewarmRelease();
      _clipStart(idx);
    }} else if (cfg.default_path_id) {{
      _clipUserStopped = false;
      selEl.value = cfg.default_path_id;
      startPath(cfg.default_path_id);
    }}
  }}

  // Start the per-shot idle auto-orbit: a slow LOOPING orbit
  // (the SAME reused math) around the active shot camera's
  // authored orbit_pivot, from wherever the camera now sits.
  // clip-mode + an authored pivot only -- never invents a pivot.
  function _startIdleOrbit() {{
    if (_idleOrbiting || _player || _benchActive) return;
    if (!_clipMode) return;                 // no cameras => no pivot
    const shot = _activeShot ||
      (_clipState.clip ? _shotFor(_clipState.clip) : null);
    if (!shot || !shot.pivot) return;       // unauthored pivot => skip
    const path = _orbitPathAround(
      shot.pivot.clone(),
      camera.position.clone(),
      camera.quaternion.clone(),
      camera.fov,
      {{ secs: 30, loop: true }});          // gentle, keeps circling
    const pl = buildPlayer(path);
    if (!pl) return;
    _idleOrbiting = true;
    _player = pl;
    _t0 = performance.now();
    _activePathId = 'idle-orbit';
    _lastTriggeredAnnotation = null;
    controls.enabled = false;
    InteractionManager.requestPointer('player');
    // The orbit drives the camera but the user is NOT being
    // shown the tour -- keep #user-play up so a click resumes
    // the real cut tour, not the orbit.
    _showUserPlay(true);
  }}
  // Cancel the idle orbit (any user input). Restores free-look;
  // a non-silent cancel keeps #user-play visible so the user can
  // resume the tour. Idempotent / no-op when not orbiting.
  function _cancelIdleOrbit(opts) {{
    if (!_idleOrbiting) return;
    _idleOrbiting = false;
    if (_activePathId === 'idle-orbit' && _player) stopPath();
    _lastInputMs = performance.now();
    if (!(opts && opts.silent)) _showUserPlay(true);
  }}

  // Any user input: stamp the idle clock + cancel a running idle
  // orbit. Pure observation -- does NOT arbitrate the pointer
  // (InteractionManager still owns that); just resets the
  // per-shot idle timer the ONE overlay tick reads. usermode
  // only (inert in author/embed -> the editor + 6 live scenes
  // are unperturbed).
  function _noteUserInput() {{
    if (!ModeManager.is('user')) return;
    _lastInputMs = performance.now();
    if (_idleOrbiting) _cancelIdleOrbit();
  }}
  window.addEventListener('keydown', _noteUserInput, true);
  window.addEventListener('wheel', _noteUserInput,
    {{ capture: true, passive: true }});
  canvas.addEventListener('pointermove', (e) => {{
    // Only a held drag counts as "interacting" for the idle
    // reset (a hovering mouse with no button down should not
    // keep the scene awake forever).
    if (e.buttons) _noteUserInput();
  }}, true);

  // INTERRUPT: a pointerdown on the canvas while the auto tour
  // plays -> stop it, hand control back (controls.enabled=true
  // via stopPath inside _stopTour), reveal #user-play. Also
  // resets the idle clock. Registered IN ADDITION to the
  // existing canvas pointerdown handlers (addEventListener
  // stacks; capture phase so it runs before OrbitControls/look
  // see the same down). usermode only. Works in clip-mode AND
  // the single default-path tour (_tourPlaying covers both).
  canvas.addEventListener('pointerdown', (e) => {{
    if (!ModeManager.is('user')) return;
    if (_idleOrbiting) {{ _cancelIdleOrbit(); return; }}
    if (_tourPlaying()) {{
      _stopTour({{ byUser: true }});
      return;
    }}
    _noteUserInput();
  }}, true);

  // The per-shot idle watcher. Fans out from the ONE
  // OverlayScene.update() tick (Task 0) -- NO parallel rAF / no
  // separate timer. No `modes` (it owns transport logic, not
  // chrome) so OverlayScene never touches visibility; node-less
  // pure-logic layer (same shape as the Task-14 _clipLayer).
  let _idleCutKey = '';   // changes on every cut -> per-shot reset
  const _transportLayer = {{
    id: 'user-transport',
    update() {{
      if (!ModeManager.is('user')) return;       // usermode only
      // Keep _activeShot fresh while the tour plays AND reset the
      // idle clock on every cut change (a new clip == a new shot;
      // the spec's per-shot idle timer reset).
      if (_clipMode && _clipState.active && _clipState.clip) {{
        const ck = String(_clipState.idx) + ':' +
          String(_clipState.clip.id || '');
        if (ck !== _idleCutKey) {{
          _idleCutKey = ck;
          _activeShot = _shotFor(_clipState.clip);
          _lastInputMs = performance.now();      // per-shot reset
        }}
      }}
      // Idle only matters when nothing is driving the camera (the
      // tour was interrupted / a clip naturally ended and the
      // user is now free-looking on that shot). Never while the
      // tour, a bench, or the idle orbit itself is running.
      if (_player || _benchActive || _idleOrbiting) return;
      if (!_userInterrupted) return;             // only after an interrupt
      if (performance.now() - _lastInputMs < IDLE_MS) return;
      _startIdleOrbit();
    }},
  }};
  OverlayScene.register(_transportLayer);

  // TEST/extension surface (mirrors window.__sp / __sceneview /
  // __clip): lets the scene-less Playwright harness drive +
  // assert the interrupt/resume/idle-orbit contract under a
  // virtual clock. Harmless, always on. The `interrupt()` /
  // `idleNow()` helpers are TEST-ONLY deterministic drivers
  // (same convention as window.__clip.restart()).
  try {{
    window.__transport = {{
      get interrupted() {{ return _userInterrupted; }},
      get idleOrbiting() {{ return _idleOrbiting; }},
      get activeShot() {{
        return _activeShot ? {{
          clipId: _activeShot.clip ? _activeShot.clip.id : null,
          cameraId: _activeShot.camera ? _activeShot.camera.id : null,
          pivot: _activeShot.pivot ? [
            _activeShot.pivot.x, _activeShot.pivot.y,
            _activeShot.pivot.z] : null,
          playhead: (typeof _activeShot.playhead === 'number')
            ? _activeShot.playhead : null,
        }} : null;
      }},
      get userPlayVisible() {{
        return !!(_userPlayBtn &&
          _userPlayBtn.style.display !== 'none');
      }},
      get idleMs() {{ return IDLE_MS; }},
      get playhead() {{ return _tourPlayhead(); }},
      // TEST-ONLY: synthesise the interrupt (the harness drives
      // the live tour under a frozen clock; a real synthetic
      // pointerdown also works but this is the deterministic
      // path the Task-14 __clip.restart() convention mirrors).
      interrupt() {{ _stopTour({{ byUser: true }}); return true; }},
      resume() {{ _resumeTour(); return true; }},
      // TEST-ONLY: force the idle clock past IDLE_MS so the next
      // overlay tick starts the idle orbit (the scene-less
      // harness has a frozen virtual clock; this rebases the
      // last-input stamp rather than waiting real time).
      idleNow() {{ _lastInputMs = performance.now() - IDLE_MS - 1; }},
    }};
  }} catch (e) {{}}

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
    //
    // Task 15: the Y-spin math is now the shared _orbitPathAround()
    // helper (declared above in the end-user transport block, hoisted)
    // so the idle auto-orbit reuses the EXACT same orbit -- this is a
    // pure delegation: the same center (_origTarget), same base pose
    // (_origCamPos/_origCamQuat/_origCamFov), same N=36 / 30 s /
    // smoothness 1.0 / loop:false the bench has always produced, so
    // the generated orbit is byte-behaviourally identical for the 6
    // live scenes' Bench: Orbit. NOT a behaviour change -- a refactor.
    return _orbitPathAround(
      _origTarget.clone(),
      _origCamPos.clone(),
      _origCamQuat.clone(),
      _origCamFov,
      {{ n: 36, secs: 30, loop: false }});
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

  // ============================================================
  //  Author editor -- viewport trajectory + camera frustums +
  //  speed dots (Task 16 -- plan H2/Task-12; the FIRST author
  //  overlay)
  // ------------------------------------------------------------
  //  AUTHOR MODE ONLY (ModeManager.is('author')): user / embed
  //  and the 6 live single-camera scenes (which are NOT author
  //  mode) are byte-runtime-unchanged -- every code path below is
  //  gated by ModeManager and the OverlayScene layer is
  //  registered with modes:['author'] so its node is hidden AND
  //  its update() is skipped outside author mode (the Task-0
  //  OverlayScene contract). No parallel rAF / no parallel
  //  listener: the rebuild + active-key tracking fan out from the
  //  ONE OverlayScene.update() tick. Reuses, never reinvents:
  //    * buildPlayer / sampleAt = the SuperSplat cubic-Hermite
  //      spline (the single source of truth for path geometry --
  //      NO spline math here; the polyline + speed dots are read
  //      straight off sampleAt's time parameterization).
  //    * world / quat convention = IDENTICAL to the live player:
  //      tick() writes camera.position.set(s.pos) +
  //      camera.quaternion.set(s.quat), so a keyframe's pos/quat
  //      is the camera's world pose. The frustum is the THREE
  //      camera local basis (looks down -Z, +Y up, +X right)
  //      transformed by that same pos/quat -> it points exactly
  //      where the camera will fly (the splat's 180-X flip is on
  //      the SPLAT, not the camera/keyframes, so the overlay
  //      group's identity world transform is correct -- same as
  //      the annotation markers).
  //    * active path = the #path-select dropdown value (selEl) --
  //      the same authored path the live player plays; absent ->
  //      the first camera_paths entry (selEl's default option).
  //    * Task-0 scaffold: ONE OverlayScene layer (its node is the
  //      trajectory group); the "Show trajectory" toggle lives in
  //      the Task-12 #author-root (CSS-gated to authormode
  //      already), styled inline like #sp-hud (no new CSS region).
  //  window.__editor is a TEST-ONLY introspection surface
  //  (mirrors window.__clip / __transport: getters + deterministic
  //  hooks; no production reader; inert without the harness).
  // ============================================================
  const _EDITOR_AUTHOR = ModeManager.is('author');
  // ~96 samples per inter-keyframe SEGMENT for the polyline (the
  // spec's target resolution). Speed dots step the path at a FIXED
  // TIME interval so their on-path spacing = (speed * dt): dense
  // where the camera is slow, sparse where it is fast (a slower
  // segment of the SAME spatial length spans more time -> more
  // dots -- exactly the inverse-speed relationship the harness
  // asserts). dt is derived from the spline's OWN duration (a
  // fixed count of equal-time steps) so it scales with any path.
  const _TRAJ_SAMPLES_PER_SEG = 96;
  const _TRAJ_DOT_STEPS = 240;
  // Frustum size is SCENE-RELATIVE: a small fraction of the ACTIVE
  // path's OWN spatial scale (the bbox diagonal of its keyframe
  // positions), NOT a scene-independent constant and NOT the
  // start-view distance (_initDist is the camera->orbit-target
  // VIEWING distance for the resting pose -- unrelated to the path's
  // extent, so a real scene framed from far back made the old
  // _initDist*0.06 frustum scene-spanning: one pyramid covered ~40%
  // of the viewport and its always-on-top opaque wireframe read as a
  // solid orange mass). _TRAJ_FR_FRAC of the path diagonal makes each
  // little camera pyramid read at the PATH's scale; the absolute
  // clamp keeps a tiny OR a huge path usable. Recomputed per path in
  // _trajRebuild (set on _trajFrLen / _trajFrHalf below); a fallback
  // is used when the path is degenerate (all keyframes coincident).
  const _TRAJ_FR_FRAC = 0.025;   // frustum apex length = 2.5% of diag
  const _TRAJ_FR_MIN = 0.06;     // absolute floor (world units)
  const _TRAJ_FR_MAX = 4.0;      // absolute ceiling (world units)
  const _TRAJ_FR_FALLBACK = 0.4; // degenerate-path fallback length
  let _trajFrLen = _TRAJ_FR_FALLBACK;       // active-path frustum length
  let _trajFrHalf = _TRAJ_FR_FALLBACK * 0.6; // active-path image-plane half
  // Bbox-diagonal of a keyframe-position list (the active path's OWN
  // spatial scale). Empty / single / coincident -> 0 (caller falls
  // back). Pure geometry off the SAME k.pos the player flies; no
  // spline math here.
  function _trajPathScale(kfs) {{
    let lo = [Infinity, Infinity, Infinity];
    let hi = [-Infinity, -Infinity, -Infinity];
    let n = 0;
    for (const k of (kfs || [])) {{
      if (!k || !k.pos || k.pos.length < 3) continue;
      for (let a = 0; a < 3; a++) {{
        const v = +k.pos[a];
        if (!Number.isFinite(v)) continue;
        if (v < lo[a]) lo[a] = v;
        if (v > hi[a]) hi[a] = v;
      }}
      n++;
    }}
    if (n < 2) return 0;
    const dx = hi[0] - lo[0], dy = hi[1] - lo[1], dz = hi[2] - lo[2];
    const d = Math.sqrt(dx * dx + dy * dy + dz * dz);
    return Number.isFinite(d) ? d : 0;
  }}
  // Set _trajFrLen / _trajFrHalf from the active path's diagonal:
  // _TRAJ_FR_FRAC of it, clamped to [_TRAJ_FR_MIN, _TRAJ_FR_MAX], and
  // a fixed fallback for a degenerate path. Called once per rebuild.
  function _trajApplyScale(kfs) {{
    const diag = _trajPathScale(kfs);
    let len = (diag > 0)
      ? Math.min(_TRAJ_FR_MAX, Math.max(_TRAJ_FR_MIN, diag * _TRAJ_FR_FRAC))
      : _TRAJ_FR_FALLBACK;
    _trajFrLen = len;
    _trajFrHalf = len * 0.6;
  }}

  // The ONE trajectory group (the OverlayScene layer's node). Its
  // children are rebuilt whenever the active path / its keyframes
  // change; the active-key highlight is refreshed every tick from
  // the live playhead. Created always (cheap empty Group) but only
  // ever populated / ticked in author mode (the layer's modes gate
  // + the _EDITOR_AUTHOR guards below make it fully inert
  // otherwise: no geometry, no window.__editor render effect).
  const _trajGroup = new THREE.Group();
  _trajGroup.name = 'editor-trajectory';
  let _trajLine = null;          // THREE.Line polyline (sampleAt)
  let _trajDots = null;          // THREE.Points speed dots
  const _trajFrusta = [];        // [{{ mesh, kfIndex, baseQuat:[xyzw], pos:[xyz] }}]
  let _trajShow = true;          // "Show trajectory" toggle (default ON)
  let _trajBuiltPathId = null;   // active path id the geometry was built for
  let _trajBuiltSig = '';        // keyframe signature (rebuild on edit)
  let _trajActiveKf = -1;        // active/scrub keyframe index (-1 = none)
  let _trajDotPositions = [];    // [[x,y,z], ...] for window.__editor
  let _trajDotSegCounts = [];    // per-segment dot count (parallel to segments)

  // The colours: the resting trajectory is a calm orange (matches
  // the #path-hud accent -- still used for the per-keyframe camera
  // frustum wireframes); the active/scrub keyframe's frustum is a
  // bright cyan AND scaled up so it is unmistakably distinct.
  const _TRAJ_COL = 0xff8a3d;
  const _TRAJ_COL_ACTIVE = 0x35e0ff;
  const _TRAJ_ACTIVE_SCALE = 1.7;
  // Sample TICKS (the per-position dots): a 3ds-Max-style motion
  // path reads them as DELICATE WHITE ticks, one per sample, never
  // a solid mass. They are FIXED screen-space points (size in
  // pixels, sizeAttenuation OFF) so a tick stays ~2 px at ANY
  // viewing distance -- decoupled from the SCENE-RELATIVE frustum
  // size (the old code keyed dot size off _trajFrHalf, which on a
  // large path made every dot a fat orange blob that merged into
  // one solid orange band when framed from far back). Near-white,
  // modest opacity, thin.
  const _TRAJ_TICK_PX = 2.2;          // fixed point size, in px
  const _TRAJ_TICK_COL = 0xeaf0f6;    // near-white (cool, not pure)
  const _TRAJ_TICK_OPACITY = 0.7;     // delicate, not a hard mass
  // Motion LINE gradient: a THIN polyline (LineBasicMaterial
  // linewidth is 1 on most platforms -- that is the desired look,
  // never faked thick) with a SUBTLE per-vertex colour ramp along
  // its length. A restrained low-saturation cool->warm HSL sweep
  // (NOT a rainbow): hue glides over a narrow band, saturation /
  // lightness stay gentle so it reads as a tasteful gradient, not
  // a flat orange ribbon and not a saturated spectrum.
  const _TRAJ_LINE_HUE0 = 0.55;       // start hue (cool cyan-blue)
  const _TRAJ_LINE_HUE1 = 0.92;       // end hue (warm magenta-rose)
  const _TRAJ_LINE_SAT = 0.45;        // low saturation (restrained)
  const _TRAJ_LINE_LIT = 0.62;        // gentle, bright-ish lightness

  function _trajActivePath() {{
    // The dropdown's current value is the authored active path
    // (set to cfg.default_path_id at init, else the first option).
    // Fall back to the first camera_paths entry so the overlay
    // still shows something before any selection.
    const id = (selEl && selEl.value) ? selEl.value : null;
    let p = id ? cameraPaths.find(x => x && x.id === id) : null;
    if (!p && cameraPaths.length) p = cameraPaths[0];
    return p || null;
  }}

  function _trajKfSig(p) {{
    // Cheap structural signature so a live keyframe edit (the
    // editor mutates camera_paths in place in later tasks) forces
    // a geometry rebuild without deep-watching.
    if (!p || !p.keyframes) return '';
    let s = (p.id || '') + '|' + (p.loop ? 1 : 0) + '|' +
            (typeof p.smoothness === 'number' ? p.smoothness : 1) + '|' +
            (typeof p.play_speed === 'number' ? p.play_speed : 1) + '|' +
            p.keyframes.length + '|';
    for (const k of p.keyframes) {{
      s += (k.t || 0) + ',' +
           (k.pos ? k.pos.join(',') : '') + ';' +
           (k.quat ? k.quat.join(',') : '') + ';' +
           (typeof k.fov === 'number' ? k.fov : '') + ';' +
           (k.interp || '') + ';' + (k.hold_s || 0) + '|';
    }}
    return s;
  }}

  // Build a small wireframe camera frustum (apex at the camera
  // position, rectangular base one _trajFrLen ahead -- the
  // SCENE-RELATIVE, per-path length set by _trajApplyScale) in the
  // THREE camera local basis: -Z forward, +Y up, +X right -- the
  // EXACT basis the live player applies (camera.quaternion.set(
  // s.quat)). Returned at the origin with identity rotation; the
  // caller sets .position / .quaternion from the keyframe so it
  // lands precisely where the camera will be.
  function _trajMakeFrustum(col) {{
    const d = _trajFrLen, h = _trajFrHalf;
    // Apex (camera origin) + 4 image-plane corners at z = -d.
    const A = [0, 0, 0];
    const TL = [-h,  h, -d], TR = [ h,  h, -d];
    const BR = [ h, -h, -d], BL = [-h, -h, -d];
    // Apex->corners + the base rectangle + a small "up" tick on
    // the top edge so the roll (quat) is visually unambiguous.
    const UP = [0, h * 1.5, -d];
    const segs = [
      A, TL,  A, TR,  A, BR,  A, BL,
      TL, TR, TR, BR, BR, BL, BL, TL,
      TL, UP, UP, TR,
    ];
    const pos = new Float32Array(segs.length * 3);
    for (let i = 0; i < segs.length; i++) {{
      pos[i*3] = segs[i][0]; pos[i*3+1] = segs[i][1]; pos[i*3+2] = segs[i][2];
    }}
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const m = new THREE.LineBasicMaterial({{ color: col }});
    // Drawn always-on-top (depthTest off, renderOrder 11) so it is
    // never occluded by the splat; a modest opacity keeps the
    // wireframe a CLEAN THIN OUTLINE rather than a saturated
    // always-on-top fill (defense-in-depth: even a degenerate path
    // scaled to the clamp ceiling can no longer read as a solid
    // orange mass -- the old scene-spanning bug's visual signature).
    m.depthTest = false; m.depthWrite = false; m.transparent = true;
    m.opacity = 0.85;
    const seg = new THREE.LineSegments(g, m);
    seg.renderOrder = 11;
    return seg;
  }}

  function _trajClear() {{
    while (_trajGroup.children.length) {{
      const c = _trajGroup.children.pop();
      if (c.geometry) try {{ c.geometry.dispose(); }} catch (e) {{}}
      if (c.material) try {{ c.material.dispose(); }} catch (e) {{}}
    }}
    _trajLine = null; _trajDots = null;
    _trajFrusta.length = 0;
    _trajDotPositions = []; _trajDotSegCounts = [];
  }}

  function _trajRebuild(p) {{
    _trajClear();
    _trajBuiltPathId = p ? (p.id || null) : null;
    _trajBuiltSig = _trajKfSig(p);
    _trajActiveKf = -1;
    if (!p) return;
    const player = buildPlayer(p);
    if (!player) return;   // < 2 keyframes -> nothing to draw
    const times = player.times;
    const kfs = player.sortedKfs;
    const nSeg = times.length - 1;

    // ---- SCENE-RELATIVE sizing: derive the frustum / dot scale from
    //      THIS path's OWN keyframe-position bbox diagonal (NOT a
    //      scene-independent constant -- the my16-M1 fix). Set before
    //      any geometry below reads _trajFrLen / _trajFrHalf.
    _trajApplyScale(kfs);

    // ---- Polyline: ~_TRAJ_SAMPLES_PER_SEG samples per segment,
    //      sampled off the SAME spline the player flies (sampleAt).
    const pts = [];
    for (let si = 0; si < nSeg; si++) {{
      const t0 = times[si], t1 = times[si + 1];
      // Sample (0 .. SAMPLES) on this segment; skip the shared
      // start sample on every segment after the first so the
      // polyline has no duplicate vertices at the knots.
      const start = si === 0 ? 0 : 1;
      for (let k = start; k <= _TRAJ_SAMPLES_PER_SEG; k++) {{
        const t = t0 + (t1 - t0) * (k / _TRAJ_SAMPLES_PER_SEG);
        const s = sampleAt(player, t);
        pts.push(s.pos[0], s.pos[1], s.pos[2]);
      }}
    }}
    {{
      const arr = new Float32Array(pts);
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(arr, 3));
      // Subtle per-vertex gradient along the path length: walk the
      // vertices in path order (pts is already start->end) and ramp
      // a low-saturation HSL hue from _TRAJ_LINE_HUE0 to
      // _TRAJ_LINE_HUE1. Restrained -- a tasteful cool->warm sweep,
      // NOT a rainbow (saturation/lightness held gentle). The line
      // stays THIN (LineBasicMaterial linewidth is 1 on virtually
      // all platforms; that is the intended delicate look -- never
      // faked thick). vertexColors makes the ramp per-vertex.
      const nPts = (pts.length / 3) | 0;
      const cols = new Float32Array(nPts * 3);
      const _gc = new THREE.Color();
      for (let vi = 0; vi < nPts; vi++) {{
        const u = nPts > 1 ? vi / (nPts - 1) : 0;
        const hue = _TRAJ_LINE_HUE0 +
          (_TRAJ_LINE_HUE1 - _TRAJ_LINE_HUE0) * u;
        _gc.setHSL(hue, _TRAJ_LINE_SAT, _TRAJ_LINE_LIT);
        cols[vi * 3] = _gc.r;
        cols[vi * 3 + 1] = _gc.g;
        cols[vi * 3 + 2] = _gc.b;
      }}
      g.setAttribute('color', new THREE.BufferAttribute(cols, 3));
      const m = new THREE.LineBasicMaterial({{ vertexColors: true }});
      m.depthTest = false; m.depthWrite = false; m.transparent = true;
      _trajLine = new THREE.Line(g, m);
      _trajLine.renderOrder = 11;
      _trajGroup.add(_trajLine);
    }}

    // ---- Per-keyframe frustum, oriented by that keyframe's quat
    //      (the same world/quat convention the player applies).
    for (let i = 0; i < kfs.length; i++) {{
      const kf = kfs[i];
      if (!kf || !kf.pos) continue;
      const q = (kf.quat && kf.quat.length === 4)
        ? kf.quat : [0, 0, 0, 1];
      const fr = _trajMakeFrustum(_TRAJ_COL);
      fr.position.set(kf.pos[0], kf.pos[1], kf.pos[2]);
      fr.quaternion.set(q[0], q[1], q[2], q[3]);
      _trajGroup.add(fr);
      _trajFrusta.push({{ mesh: fr, kfIndex: i,
        baseQuat: [q[0], q[1], q[2], q[3]],
        pos: [kf.pos[0], kf.pos[1], kf.pos[2]] }});
    }}

    // ---- Speed dots: FIXED time step dt over the whole path so
    //      the on-path spacing = (local speed * dt). dt is a fixed
    //      fraction of the spline's own duration (a constant count
    //      of equal-TIME steps); per-segment dot count therefore
    //      scales with segment DURATION and the on-path density
    //      scales INVERSELY with segment speed (dense=slow,
    //      sparse=fast) -- read straight off sampleAt's time
    //      parameterization, never a spatial-arc heuristic.
    const dur = player.duration || 0;
    if (dur > 0) {{
      const dt = dur / _TRAJ_DOT_STEPS;
      const segCounts = new Array(nSeg).fill(0);
      const dpos = [];
      // Step strictly INSIDE the path (skip the exact endpoints so
      // a dot is unambiguously attributable to one segment).
      for (let t = dt; t < dur; t += dt) {{
        const s = sampleAt(player, t);
        dpos.push(s.pos[0], s.pos[1], s.pos[2]);
        _trajDotPositions.push([s.pos[0], s.pos[1], s.pos[2]]);
        // Attribute this dot to its segment (the spline time
        // parameterization -- which segment's [t0,t1] contains t).
        let sg = 0;
        while (sg < nSeg - 1 && times[sg + 1] <= t) sg++;
        segCounts[sg]++;
      }}
      _trajDotSegCounts = segCounts;
      if (dpos.length) {{
        const arr = new Float32Array(dpos);
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(arr, 3));
        // DELICATE WHITE sample ticks: a FIXED screen-space point
        // size (_TRAJ_TICK_PX px, sizeAttenuation OFF) so each tick
        // stays ~2 px at ANY viewing distance and never grows into a
        // solid mass when the path is framed from far back. Size is
        // FULLY DECOUPLED from _trajFrHalf / the scene-relative
        // frustum scale (the old `Math.max(2, _trajFrHalf * 0.5)`
        // with sizeAttenuation:true was the fat-orange-band bug --
        // on a large path _trajFrHalf is metres, so attenuated dots
        // overlapped into one band). Near-white, modest opacity,
        // thin. One tick per sample position, inverse-speed spacing
        // unchanged (this only restyles, never re-distributes).
        const m = new THREE.PointsMaterial({{
          color: _TRAJ_TICK_COL, size: _TRAJ_TICK_PX,
          sizeAttenuation: false, opacity: _TRAJ_TICK_OPACITY }});
        m.depthTest = false; m.depthWrite = false; m.transparent = true;
        _trajDots = new THREE.Points(g, m);
        _trajDots.renderOrder = 11;
        _trajGroup.add(_trajDots);
      }}
    }}
  }}

  // The current playhead (seconds, retimed spline time) the user
  // is parked at -- the live player clock while a path plays /
  // scrubs, else the #path-scrub slider position mapped through
  // the active path's duration. Drives WHICH keyframe frustum is
  // highlighted (the "active/scrub" key the spec requires).
  function _trajPlayhead(player) {{
    if (!player) return null;
    if (_player && _activePathId &&
        _activePathId === _trajBuiltPathId) {{
      // A path is actively driving the camera (Play or a scrub
      // grab) -- use its real clock, EXACT same formula as tick().
      const sp = _player.playSpeed || 1.0;
      let tn = ((performance.now() - _t0) / 1000) * sp;
      if (_player.loop && tn > _player.duration)
        tn = tn % _player.duration;
      return Math.max(0, Math.min(tn, player.duration));
    }}
    // Not playing: the scrub slider (0..1000) -> path time.
    if (scrubEl) {{
      const f = (parseFloat(scrubEl.value) || 0) / 1000;
      return Math.max(0, Math.min(f, 1)) * player.duration;
    }}
    return 0;
  }}

  // Refresh the active/scrub keyframe highlight from the current
  // playhead: the highlighted key is the one sampleAt maps the
  // playhead to (its _kfIndex -- the SAME source-keyframe index
  // the player uses for annotation triggers). Cheap; only touches
  // material colour + scale on a real change.
  let _trajPhPlayer = null;
  function _trajRefreshActive() {{
    if (!_trajPhPlayer) {{
      const ap = _trajActivePath();
      _trajPhPlayer = ap ? buildPlayer(ap) : null;
    }}
    let idx = -1;
    if (_trajPhPlayer) {{
      const ph = _trajPlayhead(_trajPhPlayer);
      if (ph !== null) {{
        const s = sampleAt(_trajPhPlayer, ph);
        idx = (typeof s._kfIndex === 'number') ? s._kfIndex : -1;
      }}
    }}
    if (idx === _trajActiveKf) return;
    _trajActiveKf = idx;
    for (const f of _trajFrusta) {{
      const on = f.kfIndex === idx;
      const col = on ? _TRAJ_COL_ACTIVE : _TRAJ_COL;
      if (f.mesh.material) f.mesh.material.color.setHex(col);
      const sc = on ? _TRAJ_ACTIVE_SCALE : 1.0;
      f.mesh.scale.setScalar(sc);
    }}
  }}

  // The "Show trajectory" toggle. Injected into the Task-12
  // #author-root (already CSS-gated to authormode -- no new CSS
  // region, inline-styled like #sp-hud, exactly the Task-15
  // #user-play approach). Default ON: an editor wants the path
  // visible. Only built in author mode.
  let _trajToggleEl = null;
  function _trajApplyShow() {{
    _trajGroup.visible = _trajShow &&
      ModeManager.is('author') && _trajGroup.children.length > 0;
  }}
  if (_EDITOR_AUTHOR) {{
    const root = document.getElementById('author-root');
    if (root) {{
      const wrap = document.createElement('label');
      wrap.id = 'editor-traj-toggle';
      wrap.style.cssText =
        'position:absolute;top:12px;left:12px;z-index:50;' +
        'display:flex;align-items:center;gap:7px;' +
        'padding:7px 11px;border-radius:7px;cursor:pointer;' +
        'font:13px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;' +
        'color:#eee;background:rgba(20,20,20,0.72);' +
        '-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);' +
        'user-select:none;';
      const cb = document.createElement('input');
      cb.type = 'checkbox'; cb.checked = _trajShow;
      cb.id = 'editor-traj-show';
      cb.style.cssText = 'cursor:pointer;margin:0;';
      const txt = document.createElement('span');
      txt.textContent = 'Show trajectory';
      wrap.appendChild(cb); wrap.appendChild(txt);
      root.appendChild(wrap);
      _trajToggleEl = cb;
      cb.addEventListener('change', () => {{
        _trajShow = !!cb.checked;
        _trajApplyShow();
      }});
    }}
  }}

  // ONE OverlayScene layer: node = the trajectory group; modes =
  // ['author'] so OverlayScene hides the node AND skips update()
  // outside author mode (Task-0 contract -> fully inert in user /
  // embed / the 6 live scenes). update() (a) rebuilds geometry
  // when the active path / its keyframes change, (b) refreshes the
  // active-key highlight from the live playhead. No parallel rAF.
  const _trajLayer = {{
    id: 'editor-trajectory',
    modes: ['author'],
    node: _trajGroup,
    update() {{
      if (!ModeManager.is('author')) return;
      const p = _trajActivePath();
      const pid = p ? (p.id || null) : null;
      const sig = _trajKfSig(p);
      if (pid !== _trajBuiltPathId || sig !== _trajBuiltSig) {{
        _trajRebuild(p);
        _trajPhPlayer = p ? buildPlayer(p) : null;
        _trajActiveKf = -1;
      }}
      _trajRefreshActive();
      _trajApplyShow();
    }},
  }};
  OverlayScene.register(_trajLayer);

  // TEST/extension surface (mirrors window.__sp / __sceneview /
  // __clip / __transport): lets the scene-less Playwright harness
  // assert the trajectory polyline / per-keyframe frusta / speed
  // dots / active-key highlight / toggle WITHOUT a real .rad (all
  // pure THREE geometry off sampleAt + the keyframes). Harmless,
  // always on; getters only (no production reader) + a couple of
  // TEST-ONLY deterministic hooks (same convention as
  // window.__clip.restart()). Inert in non-author mode (the layer
  // never builds geometry there -> empty/false everywhere).
  try {{
    window.__editor = {{
      get author() {{ return ModeManager.is('author'); }},
      get show() {{ return _trajShow; }},
      // Polyline vertex count (3 floats per point).
      get linePointCount() {{
        if (!_trajLine || !_trajLine.geometry) return 0;
        const a = _trajLine.geometry.getAttribute('position');
        return a ? a.count : 0;
      }},
      get samplesPerSeg() {{ return _TRAJ_SAMPLES_PER_SEG; }},
      // SCENE-RELATIVE sizing introspection (the my16-M1 fix). The
      // harness asserts the frustum size is a small fraction of the
      // ACTIVE path's OWN keyframe bbox diagonal -- it MUST scale
      // with the path extent, NOT be a scene-independent constant.
      // pathScale = the active path's diagonal; frustumLen / Half =
      // the clamped per-path frustum size actually built with;
      // frustumFrac / Min / Max = the fraction + absolute clamps;
      // frustumIsWireframe = the geometry is LineSegments with a
      // Line material (a thin outline, never a filled Mesh -- the
      // solid-orange-mass guard).
      get pathScale() {{ return _trajPathScale(
        (_trajFrusta.length ? _trajFrusta.map(
          f => ({{ pos: f.pos }})) : [])); }},
      get frustumLen() {{ return _trajFrLen; }},
      get frustumHalf() {{ return _trajFrHalf; }},
      get frustumFrac() {{ return _TRAJ_FR_FRAC; }},
      get frustumMin() {{ return _TRAJ_FR_MIN; }},
      get frustumMax() {{ return _TRAJ_FR_MAX; }},
      get frustumIsWireframe() {{
        const f = _trajFrusta[0];
        if (!f || !f.mesh) return false;
        const isLineSeg = !!(f.mesh.isLineSegments ||
          (f.mesh.type === 'LineSegments'));
        const m = f.mesh.material;
        const isLineMat = !!(m && (m.isLineBasicMaterial ||
          m.type === 'LineBasicMaterial'));
        const notMesh = !f.mesh.isMesh;
        return isLineSeg && isLineMat && notMesh;
      }},
      // One entry per keyframe frustum, with its world pose so the
      // harness can assert each is oriented by ITS keyframe quat.
      get frusta() {{
        return _trajFrusta.map(f => ({{
          kfIndex: f.kfIndex,
          pos: f.pos.slice(),
          quat: f.baseQuat.slice(),
          active: f.kfIndex === _trajActiveKf,
          scale: f.mesh ? f.mesh.scale.x : 1,
          color: (f.mesh && f.mesh.material)
            ? f.mesh.material.color.getHex() : 0,
          inGroup: !!(f.mesh && f.mesh.parent === _trajGroup),
        }}));
      }},
      get frustumCount() {{ return _trajFrusta.length; }},
      get activeKf() {{ return _trajActiveKf; }},
      // Speed-dot positions + per-segment counts (the inverse-speed
      // relationship: more dots in a slower / longer-duration
      // segment for the SAME fixed time step).
      get dotCount() {{ return _trajDotPositions.length; }},
      get dotPositions() {{
        return _trajDotPositions.map(d => d.slice());
      }},
      get dotSegCounts() {{ return _trajDotSegCounts.slice(); }},
      // Sample-TICK style introspection (the my16 "tiny white ticks"
      // fix). The harness asserts the ticks are SMALL + WHITE +
      // FIXED screen-space (not the old fat scene-relative orange
      // blobs that merged into a band): tickSize = the configured
      // px size (read off the live PointsMaterial); tickSizeIsFixed
      // = sizeAttenuation is OFF (px-constant at any distance, the
      // never-a-band guarantee); tickColor = the dot hex; the
      // tickColorIsWhite flag is true iff every channel is high
      // (a near-white tick, never orange); tickOpacity = its
      // modest alpha. All read off the actual built material so a
      // regression to the _trajFrHalf-keyed orange dots FAILS.
      get tickSize() {{
        return (_trajDots && _trajDots.material)
          ? _trajDots.material.size : 0;
      }},
      get tickSizeIsFixed() {{
        return !!(_trajDots && _trajDots.material &&
          _trajDots.material.sizeAttenuation === false);
      }},
      get tickColor() {{
        return (_trajDots && _trajDots.material)
          ? _trajDots.material.color.getHex() : 0;
      }},
      get tickColorIsWhite() {{
        // Read the sRGB hex (color-space-robust: THREE may store the
        // working colour LINEAR, so c.r/g/b would under-read a true
        // near-white; the hex bytes are the authored sRGB value).
        if (!_trajDots || !_trajDots.material) return false;
        const h = _trajDots.material.color.getHex();
        const r = (h >> 16) & 255, g = (h >> 8) & 255, b = h & 255;
        return r >= 0xCC && g >= 0xCC && b >= 0xCC;
      }},
      get tickOpacity() {{
        return (_trajDots && _trajDots.material)
          ? _trajDots.material.opacity : 0;
      }},
      // Motion-LINE gradient introspection (the my16 "subtle
      // gradient" fix). lineHasGradient = the line material renders
      // per-vertex colours (vertexColors ON) AND the geometry
      // actually carries a populated colour attribute -> a ramp,
      // not a flat orange ribbon. lineColorCount = that attribute's
      // vertex count (parallel to linePointCount). lineColorEndsDiffer
      // = the first vs last vertex colour differ (a real ramp along
      // the length, not a single constant baked per-vertex). A
      // regression to the flat ``LineBasicMaterial({{ color: _TRAJ_COL }})``
      // would make all three FALSE/0.
      get lineHasGradient() {{
        if (!_trajLine || !_trajLine.material ||
            !_trajLine.geometry) return false;
        const vc = _trajLine.material.vertexColors === true;
        const ca = _trajLine.geometry.getAttribute('color');
        return !!(vc && ca && ca.count > 1);
      }},
      get lineColorCount() {{
        if (!_trajLine || !_trajLine.geometry) return 0;
        const ca = _trajLine.geometry.getAttribute('color');
        return ca ? ca.count : 0;
      }},
      get lineColorEndsDiffer() {{
        if (!_trajLine || !_trajLine.geometry) return false;
        const ca = _trajLine.geometry.getAttribute('color');
        if (!ca || ca.count < 2) return false;
        const n = ca.count - 1;
        const dr = Math.abs(ca.getX(0) - ca.getX(n));
        const dg = Math.abs(ca.getY(0) - ca.getY(n));
        const db = Math.abs(ca.getZ(0) - ca.getZ(n));
        return (dr + dg + db) > 0.05;
      }},
      get activePathId() {{ return _trajBuiltPathId; }},
      get groupVisible() {{
        return !!(_trajGroup.visible &&
          _trajGroup.children.length > 0);
      }},
      get groupInScene() {{
        // The OverlayScene group is scene.add()-ed once (Task 0);
        // our node is parented under it ONLY in author mode.
        return !!(_trajGroup.parent &&
          _trajGroup.parent === OverlayScene.group);
      }},
      // TEST-ONLY: drive the "Show trajectory" toggle exactly as a
      // user click would (fires the same change handler).
      setShow(v) {{
        _trajShow = !!v;
        if (_trajToggleEl) _trajToggleEl.checked = _trajShow;
        _trajApplyShow();
        return _trajShow;
      }},
      // TEST-ONLY: force a geometry rebuild for the active path
      // (deterministic; same spirit as window.__clip.restart()).
      rebuild() {{
        const p = _trajActivePath();
        _trajRebuild(p);
        _trajPhPlayer = p ? buildPlayer(p) : null;
        _trajRefreshActive();
        _trajApplyShow();
        return _trajFrusta.length;
      }},
      // TEST-ONLY: set the scrub position (0..1) and refresh the
      // active-key highlight so the harness can assert the
      // active/scrub frustum tracks the playhead deterministically.
      // Drives the REAL scrub: set #path-scrub then dispatch its
      // actual 'input' event so the EXISTING production scrub handler
      // runs (it takes over `_player` for the selected path AND
      // rebases `_t0` so the live playhead == the scrubbed time --
      // exactly a user grabbing the scrub). This makes the
      // active-key deterministic even if the author-mode
      // default-path auto-tour is mid-playback (the scrub takes the
      // camera over, same as for a real user); we do NOT reimplement
      // the scrub math here (single source of truth).
      scrubTo(f) {{
        if (scrubEl) {{
          const v = Math.max(0, Math.min(1, +f || 0)) * 1000;
          scrubEl.value = v;
          try {{
            scrubEl.dispatchEvent(new Event('input', {{ bubbles: true }}));
          }} catch (e) {{}}
        }}
        _trajRefreshActive();
        return _trajActiveKf;
      }},
    }};
  }} catch (e) {{}}

  // ============================================================
  //  Author editor -- bottom timeline (Task 17 -- plan H2/Task-13)
  // ------------------------------------------------------------
  //  AUTHOR MODE ONLY (ModeManager.is('author')): user / embed and
  //  the 6 live single-camera scenes are byte-runtime-unchanged --
  //  every code path here is gated by the SAME _EDITOR_AUTHOR flag
  //  the Task-16 trajectory overlay uses, and the strip DOM is only
  //  ever built in author mode (so this whole section is inert in
  //  user/embed; the byte-lock proves the 6 live scenes' generated
  //  HTML is byte-identical -- this code sits strictly INSIDE the
  //  Task-16 T16-TRAJ region, recipe 2c, so it is absorbed by that
  //  region's existing excision and the moving-baseline remainder
  //  is unaffected by it).
  //  IN-MEMORY temporal edits ONLY (the Task-17 scope boundary):
  //    * a SECONDS ruler (the storage unit is ALWAYS seconds); an
  //      OPTIONAL author fps grid that ONLY relabels the ruler
  //      ticks (fps is a display relabel -- it NEVER mutates a
  //      stored kf.t).
  //    * a diamond per keyframe at its kf.t; dragging it
  //      horizontally edits THAT keyframe's t (a temporal edit) --
  //      mutates the in-memory active path (_trajActivePath(), the
  //      SAME object the live player + the Task-16 overlay read)
  //      and rebuilds the spline. The Task-16 overlay's
  //      sig-driven OverlayScene.update() rebuild reacts to the
  //      kf.t change automatically (its _trajKfSig includes
  //      (k.t||0)); we ALSO null _player so the live player picks
  //      up the new geometry on its next grab.
  //    * a live-scrub playhead: dragging it drives the camera LIVE
  //      via the EXISTING #path-scrub real 'input' mechanism (the
  //      single source of truth that takes `_player` over for the
  //      selected path AND rebases `_t0`) -- NOT only during play,
  //      and ROBUST to the author-mode default-path auto-tour
  //      (which auto-plays here because _cinematic is usermode-
  //      only): the real scrub takes the camera over deterministic-
  //      ally exactly as a user grabbing the slider would. We do
  //      NOT reimplement the scrub math (lockstep with the player).
  //    * transport play / pause / loop (reuse the existing
  //      #path-play / #path-stop handlers; loop toggles the active
  //      path's loop flag + rebuilds).
  //    * wheel zoom (time scale) about the cursor time; pan via
  //      scroll. Zoom/scroll change ONLY the px mapping, never a
  //      stored t.
  //    * box-select 2+ diamonds, then drag a SELECTION EDGE handle
  //      => proportionally rescale the selected keyframes' t span
  //      about the OPPOSITE edge anchor (ratio = newSpan/oldSpan;
  //      t' = anchor + (t-anchor)*ratio). X deletes the selected
  //      keyframes. Both mutate the in-memory path + rebuild.
  //  PERSISTENCE IS NOT TASK-17: nothing here writes/saves; edits
  //  mutate the in-memory active path + rebuild the spline (+ the
  //  Task-16 overlay consequently) and stop there. SAVE_MODE /
  //  SAVE_ENDPOINT / save_backends are deliberately untouched (a
  //  later task owns Record + Emit SPCP).
  //  Reuses, never reinvents: buildPlayer / sampleAt (the
  //  SuperSplat cubic-Hermite spline), the #path-scrub real input
  //  mechanism (camera takeover / _t0 rebase), _trajActivePath()
  //  (the in-memory active path), the Task-16 sig-driven overlay
  //  rebuild, the #author-root inline-style pattern, ModeManager.
  //  window.__editor is EXTENDED (TEST-ONLY: getters + deterministic
  //  hooks, same convention as window.__clip / __transport; no
  //  production reader; inert without the harness).
  // ============================================================
  (function _tlInit() {{
    if (!_EDITOR_AUTHOR) return;
    const root = document.getElementById('author-root');
    if (!root) return;

    // ---- View state (px mapping). Storage is ALWAYS seconds; zoom
    //      (px per second) + scroll (seconds of left-edge offset)
    //      are PURE DISPLAY -- they never touch a stored kf.t.
    const _TL_PAD = 8;             // left inset (px) inside the lane
    const _TL_H = 64;              // strip height (px)
    const _TL_RULER_H = 16;        // seconds-ruler band height (px)
    let _tlZoom = 80;              // px / second (wheel-tunable)
    let _tlScroll = 0;             // seconds at the lane's left edge
    const _TL_ZOOM_MIN = 2, _TL_ZOOM_MAX = 4000;
    let _tlFps = 0;                // 0 = OFF (seconds labels); >0 = fps grid
    let _tlSel = new Set();        // selected keyframe indices
    let _tlDragKf = -1;            // keyframe index being time-dragged
    let _tlDragMode = '';          // '' | 'kf' | 'play' | 'scale' | 'box'
    let _tlScaleEdge = '';         // 'left' | 'right' (which edge is grabbed)
    let _tlScaleAnchor = 0;        // the FIXED opposite-edge time (seconds)
    let _tlScaleBase = null;       // [{{i, t0}}] selected kf base times at grab
    let _tlBoxX0 = 0;              // marquee start x (lane px)
    let _tlBoxX1 = 0;
    let _tlScrubbing = false;      // playhead being live-dragged

    function _tlActivePath() {{
      // The SAME in-memory object the live player + the Task-16
      // overlay use (reuse, never a parallel copy).
      return (typeof _trajActivePath === 'function')
        ? _trajActivePath() : null;
    }}
    function _tlSortedKfs(p) {{
      if (!p || !p.keyframes) return [];
      // A stable index-tagged sort by t so a diamond keeps its
      // identity (the kf OBJECT) across a temporal edit even when
      // the order changes.
      return p.keyframes
        .map((k, i) => ({{ k: k, i: i, t: (k.t || 0) }}))
        .sort((a, b) => a.t - b.t);
    }}
    function _tlDuration(p) {{
      const sk = _tlSortedKfs(p);
      if (sk.length < 2) return sk.length ? (sk[0].t || 0) : 0;
      // Includes hold_s (mirrors buildPlayer's accumulated duration
      // so the playhead<->scrub mapping is consistent with the
      // player clock).
      let acc = 0;
      for (const e of sk) acc += (e.k.hold_s && e.k.hold_s > 0)
        ? e.k.hold_s : 0;
      return (sk[sk.length - 1].t || 0) + acc;
    }}
    // time (seconds) -> x within the lane (px); inverse for hit-test
    // / drag. Pure display math (zoom/scroll) -- never a stored t.
    function _tlT2X(t) {{ return _TL_PAD + (t - _tlScroll) * _tlZoom; }}
    function _tlX2T(x) {{ return _tlScroll + (x - _TL_PAD) / _tlZoom; }}

    // ---- DOM: a bottom strip injected into #author-root, inline-
    //      styled exactly like #sp-hud / the Task-16 toggle (no new
    //      CSS region). Pointer-events on the strip only; the strip
    //      never covers the whole canvas.
    const _tlStrip = document.createElement('div');
    _tlStrip.id = 'editor-timeline';
    _tlStrip.style.cssText =
      'position:absolute;left:0;right:0;bottom:0;height:' + _TL_H +
      'px;z-index:48;box-sizing:border-box;' +
      'background:rgba(16,16,16,0.82);' +
      '-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);' +
      'border-top:1px solid rgba(255,255,255,0.12);' +
      'font:11px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;' +
      'color:#ccc;user-select:none;touch-action:none;overflow:hidden;';

    // Transport cluster (left): play / pause / loop / fps. Reuses
    // the existing #path-play / #path-stop handlers (no new stop /
    // play mechanism).
    const _tlBar = document.createElement('div');
    _tlBar.style.cssText =
      'position:absolute;left:8px;top:6px;display:flex;gap:6px;' +
      'align-items:center;z-index:2;';
    function _tlBtn(txt, title) {{
      const b = document.createElement('button');
      b.type = 'button'; b.textContent = txt; b.title = title || '';
      b.style.cssText =
        'background:rgba(255,255,255,0.10);color:#eee;border:0;' +
        'border-radius:5px;padding:4px 9px;cursor:pointer;' +
        'font:12px monospace;line-height:1;';
      return b;
    }}
    const _tlPlay = _tlBtn('\\u25B6', 'Play');
    const _tlPause = _tlBtn('\\u23F8', 'Pause');
    const _tlLoop = _tlBtn('\\u21BB', 'Loop');
    const _tlFpsBtn = _tlBtn('fps', 'Toggle fps grid (relabels ruler only)');
    _tlBar.appendChild(_tlPlay); _tlBar.appendChild(_tlPause);
    _tlBar.appendChild(_tlLoop); _tlBar.appendChild(_tlFpsBtn);
    _tlStrip.appendChild(_tlBar);

    // The lane (ruler + diamonds + playhead). A canvas draws the
    // ruler + diamonds + selection box; a thin div is the playhead.
    const _tlLane = document.createElement('div');
    _tlLane.style.cssText =
      'position:absolute;left:0;right:0;bottom:0;height:' +
      (_TL_H - 24) + 'px;cursor:crosshair;';
    const _tlCanvas = document.createElement('canvas');
    _tlCanvas.style.cssText =
      'position:absolute;inset:0;width:100%;height:100%;display:block;';
    const _tlPlayhead = document.createElement('div');
    _tlPlayhead.style.cssText =
      'position:absolute;top:0;bottom:0;width:2px;left:0;' +
      'background:#35e0ff;box-shadow:0 0 4px #35e0ff;' +
      'pointer-events:none;will-change:left;';
    _tlLane.appendChild(_tlCanvas);
    _tlLane.appendChild(_tlPlayhead);
    _tlStrip.appendChild(_tlLane);
    root.appendChild(_tlStrip);

    const _tlCtx = _tlCanvas.getContext('2d');
    let _tlW = 0, _tlHpx = 0, _tlDpr = 1;
    function _tlResize() {{
      const r = _tlLane.getBoundingClientRect();
      _tlDpr = Math.max(1, window.devicePixelRatio || 1);
      _tlW = Math.max(1, Math.floor(r.width));
      _tlHpx = Math.max(1, Math.floor(r.height));
      _tlCanvas.width = Math.floor(_tlW * _tlDpr);
      _tlCanvas.height = Math.floor(_tlHpx * _tlDpr);
      _tlDraw();
    }}

    // ---- Diamond geometry (canvas-space hit test). Each keyframe
    //      is a diamond centred at (_tlT2X(kf.t), diamond-row-y).
    const _TL_DIAM = 7;            // half-size (px)
    function _tlDiamRowY() {{ return _TL_RULER_H + 14; }}
    function _tlHitKf(x, y) {{
      // Topmost keyframe whose diamond contains (x,y); -1 = none.
      const p = _tlActivePath();
      if (!p || !p.keyframes) return -1;
      const cy = _tlDiamRowY();
      let best = -1, bestd = 1e9;
      for (let i = 0; i < p.keyframes.length; i++) {{
        const k = p.keyframes[i];
        const cx = _tlT2X(k.t || 0);
        const d = Math.abs(x - cx) + Math.abs(y - cy);
        if (d <= _TL_DIAM + 4 && d < bestd) {{ best = i; bestd = d; }}
      }}
      return best;
    }}

    // ---- Ruler. SECONDS by default. The fps grid is a pure
    //      RELABEL: when _tlFps>0 the tick step + label switch to
    //      frame units (label = round(t*fps)) but the stored kf.t
    //      stays SECONDS -- toggling fps NEVER mutates any t.
    function _tlNiceStep(minPxPer) {{
      // Smallest "nice" seconds step whose on-screen spacing >=
      // minPxPer px (1,2,5 x 10^n).
      const raw = minPxPer / _tlZoom;
      const pow = Math.pow(10, Math.floor(Math.log10(raw <= 0 ? 1 : raw)));
      const cand = [1, 2, 5, 10];
      for (const c of cand) {{
        if (pow * c >= raw) return pow * c;
      }}
      return pow * 10;
    }}
    function _tlDraw() {{
      if (!_tlCtx) return;
      const ctx = _tlCtx;
      ctx.setTransform(_tlDpr, 0, 0, _tlDpr, 0, 0);
      ctx.clearRect(0, 0, _tlW, _tlHpx);
      const p = _tlActivePath();
      const dur = _tlDuration(p);

      // Ruler band background.
      ctx.fillStyle = 'rgba(255,255,255,0.04)';
      ctx.fillRect(0, 0, _tlW, _TL_RULER_H);

      // Tick + label step. fps grid only changes the LABEL/step
      // unit; positions are still computed from SECONDS via _tlT2X.
      const stepS = _tlNiceStep(56);
      const t0 = Math.max(0, Math.floor(_tlScroll / stepS) * stepS);
      const tEnd = _tlScroll + _tlW / _tlZoom;
      ctx.strokeStyle = 'rgba(255,255,255,0.16)';
      ctx.fillStyle = '#9aa';
      ctx.lineWidth = 1;
      ctx.font = '10px monospace';
      ctx.textBaseline = 'top';
      for (let t = t0; t <= tEnd + stepS; t += stepS) {{
        const x = _tlT2X(t);
        if (x < -40 || x > _tlW + 40) continue;
        ctx.beginPath();
        ctx.moveTo(x + 0.5, 0);
        ctx.lineTo(x + 0.5, _TL_RULER_H);
        ctx.stroke();
        let lbl;
        if (_tlFps > 0) {{
          // RELABEL ONLY: frame index = round(seconds * fps). The
          // stored t is unchanged; this is a display transform.
          lbl = 'f' + Math.round(t * _tlFps);
        }} else {{
          lbl = (Math.round(t * 1000) / 1000) + 's';
        }}
        ctx.fillText(lbl, x + 3, 2);
      }}

      // Selection marquee (box-select in progress).
      if (_tlDragMode === 'box') {{
        const bx = Math.min(_tlBoxX0, _tlBoxX1);
        const bw = Math.abs(_tlBoxX1 - _tlBoxX0);
        ctx.fillStyle = 'rgba(53,224,255,0.14)';
        ctx.strokeStyle = 'rgba(53,224,255,0.6)';
        ctx.fillRect(bx, _TL_RULER_H, bw, _tlHpx - _TL_RULER_H);
        ctx.strokeRect(bx + 0.5, _TL_RULER_H + 0.5,
          bw, _tlHpx - _TL_RULER_H - 1);
      }}

      if (!p || !p.keyframes || !p.keyframes.length) return;
      const cy = _tlDiamRowY();

      // Selection-span EDGE handles (only when 2+ selected): two
      // vertical grips at the min/max selected kf.t. Dragging one
      // scales the selected span about the OTHER (the opposite
      // anchor) -- proportional rescale.
      if (_tlSel.size >= 2) {{
        let lo = Infinity, hi = -Infinity;
        _tlSel.forEach((i) => {{
          const k = p.keyframes[i]; if (!k) return;
          const t = k.t || 0;
          if (t < lo) lo = t; if (t > hi) hi = t;
        }});
        if (isFinite(lo) && isFinite(hi)) {{
          const xL = _tlT2X(lo), xR = _tlT2X(hi);
          ctx.strokeStyle = 'rgba(53,224,255,0.5)';
          ctx.setLineDash([3, 3]);
          ctx.beginPath();
          ctx.moveTo(xL + 0.5, _TL_RULER_H);
          ctx.lineTo(xL + 0.5, _tlHpx);
          ctx.moveTo(xR + 0.5, _TL_RULER_H);
          ctx.lineTo(xR + 0.5, _tlHpx);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = '#35e0ff';
          ctx.fillRect(xL - 3, cy + _TL_DIAM + 3, 6, 8);
          ctx.fillRect(xR - 3, cy + _TL_DIAM + 3, 6, 8);
        }}
      }}

      // Diamonds (one per keyframe at its kf.t). Selected = cyan;
      // resting = orange (matches the Task-16 trajectory accent).
      for (let i = 0; i < p.keyframes.length; i++) {{
        const k = p.keyframes[i];
        const cx = _tlT2X(k.t || 0);
        if (cx < -20 || cx > _tlW + 20) continue;
        const on = _tlSel.has(i);
        ctx.beginPath();
        ctx.moveTo(cx, cy - _TL_DIAM);
        ctx.lineTo(cx + _TL_DIAM, cy);
        ctx.lineTo(cx, cy + _TL_DIAM);
        ctx.lineTo(cx - _TL_DIAM, cy);
        ctx.closePath();
        ctx.fillStyle = on ? '#35e0ff' : '#ff8a3d';
        ctx.fill();
        ctx.strokeStyle = 'rgba(0,0,0,0.6)';
        ctx.lineWidth = 1;
        ctx.stroke();
      }}
      void dur;
    }}

    // ---- Playhead position (px) from the live player clock if a
    //      path is driving the camera, else the #path-scrub slider.
    //      EXACT same source the Task-16 overlay highlight uses --
    //      single source of truth, no parallel clock.
    function _tlPlayheadT() {{
      const p = _tlActivePath();
      const dur = _tlDuration(p);
      if (dur <= 0) return 0;
      if (_player && _activePathId &&
          _trajBuiltPathId && _activePathId === _trajBuiltPathId) {{
        const sp = _player.playSpeed || 1.0;
        let tn = ((performance.now() - _t0) / 1000) * sp;
        if (_player.loop && tn > _player.duration)
          tn = tn % _player.duration;
        return Math.max(0, Math.min(tn, dur));
      }}
      if (scrubEl) {{
        const f = (parseFloat(scrubEl.value) || 0) / 1000;
        return Math.max(0, Math.min(1, f)) * dur;
      }}
      return 0;
    }}
    function _tlSyncPlayhead() {{
      const t = _tlPlayheadT();
      const x = _tlT2X(t);
      _tlPlayhead.style.left = x + 'px';
      _tlPlayhead.style.display =
        (x >= -2 && x <= _tlW + 2) ? 'block' : 'none';
    }}

    // ---- The SINGLE source of truth for live scrub: set the
    //      EXISTING #path-scrub slider value (0..1000 of the active
    //      path duration) and dispatch its REAL 'input' event so the
    //      production handler runs -- it takes `_player` over for the
    //      selected path AND rebases `_t0`, EXACTLY like a user
    //      grabbing the slider. This is what makes the live scrub
    //      robust to the author-mode default-path AUTO-TOUR (which
    //      auto-plays here): the real scrub deterministically takes
    //      the camera over from the auto-advancing tour, same as for
    //      a real user. We never reimplement the scrub math.
    function _tlScrubToTime(t) {{
      const p = _tlActivePath();
      const dur = _tlDuration(p);
      if (!scrubEl || dur <= 0) return;
      // Make sure the scrub handler binds to the path the timeline
      // is editing (it reads selEl.value when _player is null).
      if (p && p.id && selEl && selEl.value !== p.id &&
          !_player) {{
        try {{ selEl.value = p.id; }} catch (e) {{}}
      }}
      const f = Math.max(0, Math.min(1, t / dur));
      scrubEl.value = String(f * 1000);
      try {{
        scrubEl.dispatchEvent(new Event('input', {{ bubbles: true }}));
      }} catch (e) {{}}
      _tlSyncPlayhead();
    }}

    // ---- In-memory temporal edit + spline rebuild. Mutates the
    //      active path object in place (the SAME object the player +
    //      Task-16 overlay read), then rebuilds the spline. The
    //      Task-16 overlay's OverlayScene.update() sig check
    //      (_trajKfSig includes (k.t||0)) rebuilds its geometry on
    //      the next tick automatically; we ALSO null _player (if it
    //      is driving THIS path) so the live player re-derives the
    //      new geometry on its next grab. NO persistence -- this is
    //      the full Task-17 mutation scope.
    function _tlAfterEdit() {{
      const p = _tlActivePath();
      if (!p) return;
      // Clamp every kf.t to be finite + >= 0 (a temporal edit must
      // never produce a NaN/negative time the spline chokes on).
      if (p.keyframes) {{
        for (const k of p.keyframes) {{
          let t = +k.t;
          if (!isFinite(t)) t = 0;
          if (t < 0) t = 0;
          k.t = t;
        }}
      }}
      // Rebuild the spline off the mutated keyframes (reuse
      // buildPlayer -- the single spline implementation). If this
      // path is the one currently driving the camera, refresh
      // _player in place + rebase _t0 to hold the current playhead
      // so the edit does not teleport the camera.
      if (_player && _activePathId === (p.id || _activePathId) &&
          _trajBuiltPathId === (p.id || null)) {{
        const held = (function () {{
          const sp = _player.playSpeed || 1.0;
          let tn = ((performance.now() - _t0) / 1000) * sp;
          if (_player.loop && tn > _player.duration)
            tn = tn % _player.duration;
          return tn;
        }})();
        const np = buildPlayer(p);
        if (np) {{
          _player = np;
          const sp = np.playSpeed || 1.0;
          const ht = Math.max(0, Math.min(held, np.duration));
          _t0 = performance.now() - (ht / sp) * 1000;
        }} else {{
          // < 2 keyframes after a delete -> stop cleanly (reuse
          // the existing stop path, never a new mechanism).
          try {{ stopPath(); }} catch (e) {{}}
        }}
      }}
      // Force the Task-16 overlay + this timeline to re-read NOW
      // (its layer also rebuilds on the next OverlayScene tick via
      // the sig check; this just makes the harness deterministic).
      try {{
        if (window.__editor && typeof window.__editor.rebuild ===
            'function') window.__editor.rebuild();
      }} catch (e) {{}}
      _tlDraw();
      _tlSyncPlayhead();
    }}

    // ---- Pointer interaction on the lane. One pointerdown router:
    //      a diamond hit => temporal drag; an edge-handle hit (2+
    //      selected) => span scale; the ruler band => live scrub;
    //      empty lane => box-select marquee. pointermove/up are on
    //      window so a drag that leaves the strip still tracks.
    function _tlLaneXY(ev) {{
      const r = _tlLane.getBoundingClientRect();
      return {{ x: ev.clientX - r.left, y: ev.clientY - r.top }};
    }}
    function _tlHitEdge(x, y) {{
      // Returns 'left'|'right'|'' for the selection-span edge grips
      // (only when 2+ selected; the grip is the small rect below
      // the diamond row at the min/max selected kf.t).
      const p = _tlActivePath();
      if (!p || _tlSel.size < 2) return '';
      let lo = Infinity, hi = -Infinity, kLo = -1, kHi = -1;
      _tlSel.forEach((i) => {{
        const k = p.keyframes[i]; if (!k) return;
        const t = k.t || 0;
        if (t < lo) {{ lo = t; kLo = i; }}
        if (t > hi) {{ hi = t; kHi = i; }}
      }});
      if (kLo < 0 || kHi < 0 || lo === hi) return '';
      const cy = _tlDiamRowY();
      if (y < cy + _TL_DIAM + 1 || y > cy + _TL_DIAM + 13) return '';
      if (Math.abs(x - _tlT2X(lo)) <= 6) return 'left';
      if (Math.abs(x - _tlT2X(hi)) <= 6) return 'right';
      return '';
    }}
    function _tlOnDown(ev) {{
      if (ev.button !== undefined && ev.button !== 0) return;
      const xy = _tlLaneXY(ev);
      _tlLane.setPointerCapture && (() => {{
        try {{ _tlLane.setPointerCapture(ev.pointerId); }} catch (e) {{}}
      }})();
      ev.preventDefault();
      // (1) selection-span edge handle -> proportional scale.
      const edge = _tlHitEdge(xy.x, xy.y);
      if (edge) {{
        const p = _tlActivePath();
        let lo = Infinity, hi = -Infinity;
        _tlSel.forEach((i) => {{
          const k = p.keyframes[i]; if (!k) return;
          const t = k.t || 0;
          if (t < lo) lo = t; if (t > hi) hi = t;
        }});
        _tlDragMode = 'scale';
        _tlScaleEdge = edge;
        // The OPPOSITE edge time is the FIXED anchor the rescale
        // pivots about (drag 'right' -> anchor = lo; drag 'left' ->
        // anchor = hi). t' = anchor + (t-anchor)*ratio.
        _tlScaleAnchor = (edge === 'right') ? lo : hi;
        _tlScaleBase = [];
        _tlSel.forEach((i) => {{
          const k = p.keyframes[i];
          if (k) _tlScaleBase.push({{ i: i, t0: (k.t || 0) }});
        }});
        return;
      }}
      // (2) diamond -> temporal drag of THAT keyframe.
      const ki = _tlHitKf(xy.x, xy.y);
      if (ki >= 0) {{
        _tlDragMode = 'kf';
        _tlDragKf = ki;
        // Click selects just this kf unless shift-extends; a
        // pre-existing multi-selection that includes ki is kept so
        // a drag can move the whole selection if desired (here a
        // single-kf temporal edit -- the spec's "drag a diamond
        // horizontally -> its t changes").
        if (!ev.shiftKey) {{
          if (!_tlSel.has(ki)) {{ _tlSel.clear(); _tlSel.add(ki); }}
        }} else {{
          if (_tlSel.has(ki)) _tlSel.delete(ki); else _tlSel.add(ki);
        }}
        _tlDraw();
        return;
      }}
      // (3) ruler band -> live scrub (drag the playhead). Routes
      //     through the REAL #path-scrub mechanism.
      if (xy.y <= _TL_RULER_H + 6) {{
        _tlDragMode = 'play';
        _tlScrubbing = true;
        _tlScrubToTime(Math.max(0, _tlX2T(xy.x)));
        return;
      }}
      // (4) empty lane -> box-select marquee.
      _tlDragMode = 'box';
      _tlBoxX0 = xy.x; _tlBoxX1 = xy.x;
      if (!ev.shiftKey) _tlSel.clear();
      _tlDraw();
    }}
    function _tlOnMove(ev) {{
      if (!_tlDragMode) return;
      const xy = _tlLaneXY(ev);
      if (_tlDragMode === 'kf') {{
        const p = _tlActivePath();
        if (!p || !p.keyframes || _tlDragKf < 0) return;
        const k = p.keyframes[_tlDragKf];
        if (!k) return;
        let nt = _tlX2T(xy.x);
        if (!isFinite(nt)) return;
        if (nt < 0) nt = 0;
        k.t = nt;                       // the temporal edit
        _tlAfterEdit();
        return;
      }}
      if (_tlDragMode === 'scale') {{
        const p = _tlActivePath();
        if (!p || !_tlScaleBase) return;
        const a = _tlScaleAnchor;
        // Base span (grabbed edge - anchor) -> new span (cursor -
        // anchor). ratio = newSpan/oldSpan; proportional rescale of
        // EVERY selected kf about the fixed opposite anchor.
        let base0 = 0;
        for (const e of _tlScaleBase) {{
          const d = Math.abs(e.t0 - a);
          if (d > base0) base0 = d;
        }}
        if (base0 <= 1e-6) return;
        let cur = Math.abs(_tlX2T(xy.x) - a);
        // Keep the span strictly positive (do not let an edge cross
        // the anchor / collapse to zero).
        if (cur < 1e-4) cur = 1e-4;
        const ratio = cur / base0;
        for (const e of _tlScaleBase) {{
          const k = p.keyframes[e.i];
          if (!k) continue;
          let nt = a + (e.t0 - a) * ratio;
          if (nt < 0) nt = 0;
          k.t = nt;
        }}
        _tlAfterEdit();
        return;
      }}
      if (_tlDragMode === 'play') {{
        _tlScrubToTime(Math.max(0, _tlX2T(xy.x)));
        return;
      }}
      if (_tlDragMode === 'box') {{
        _tlBoxX1 = xy.x;
        // Live marquee selection: every keyframe whose diamond x is
        // inside the box (a fresh set unless shift-additive at down).
        const p = _tlActivePath();
        if (p && p.keyframes) {{
          const lo = Math.min(_tlBoxX0, _tlBoxX1);
          const hi = Math.max(_tlBoxX0, _tlBoxX1);
          for (let i = 0; i < p.keyframes.length; i++) {{
            const cx = _tlT2X(p.keyframes[i].t || 0);
            if (cx >= lo && cx <= hi) _tlSel.add(i);
          }}
        }}
        _tlDraw();
        return;
      }}
    }}
    function _tlOnUp() {{
      if (_tlDragMode === 'box') {{
        // Marquee finished; keep whatever fell inside it.
      }}
      _tlDragMode = '';
      _tlDragKf = -1;
      _tlScrubbing = false;
      _tlScaleBase = null;
      _tlDraw();
    }}
    _tlLane.addEventListener('pointerdown', _tlOnDown);
    window.addEventListener('pointermove', _tlOnMove);
    window.addEventListener('pointerup', _tlOnUp);

    // ---- Wheel zoom (time scale) about the cursor time. Storage
    //      stays SECONDS -- only the px mapping (zoom/scroll)
    //      changes; no stored t is touched.
    _tlLane.addEventListener('wheel', (ev) => {{
      ev.preventDefault();
      const xy = _tlLaneXY(ev);
      const tAt = _tlX2T(xy.x);            // time under the cursor
      const f = Math.exp(-ev.deltaY * 0.0016);
      const nz = Math.max(_TL_ZOOM_MIN,
        Math.min(_TL_ZOOM_MAX, _tlZoom * f));
      _tlZoom = nz;
      // Keep the time under the cursor pinned (zoom about cursor).
      _tlScroll = tAt - (xy.x - _TL_PAD) / _tlZoom;
      if (_tlScroll < 0) _tlScroll = 0;
      _tlDraw();
      _tlSyncPlayhead();
    }}, {{ passive: false }});

    // ---- Transport. Reuse the EXISTING #path-play / #path-stop
    //      handlers (no new play/stop). Loop toggles the active
    //      path's loop flag + rebuilds (a temporal-ish edit on the
    //      path object -- still in-memory, still no persistence).
    _tlPlay.addEventListener('click', () => {{
      const p = _tlActivePath();
      if (p && p.id && selEl) {{
        try {{ selEl.value = p.id; }} catch (e) {{}}
      }}
      try {{ startPath(selEl ? selEl.value : (p && p.id)); }}
      catch (e) {{}}
    }});
    _tlPause.addEventListener('click', () => {{
      try {{ stopPath(); }} catch (e) {{}}
      _tlSyncPlayhead();
    }});
    _tlLoop.addEventListener('click', () => {{
      const p = _tlActivePath();
      if (!p) return;
      p.loop = !p.loop;
      _tlLoop.style.background = p.loop
        ? 'rgba(53,224,255,0.32)' : 'rgba(255,255,255,0.10)';
      _tlAfterEdit();
    }});
    _tlFpsBtn.addEventListener('click', () => {{
      // Cycle OFF -> 24 -> 30 -> 60 -> OFF. PURE RELABEL of the
      // ruler -- it NEVER mutates a stored kf.t (the storage unit
      // is always seconds; this only changes tick labels).
      const cyc = [0, 24, 30, 60];
      const idx = cyc.indexOf(_tlFps);
      _tlFps = cyc[(idx + 1) % cyc.length];
      _tlFpsBtn.textContent = _tlFps > 0 ? (_tlFps + 'fps') : 'fps';
      _tlFpsBtn.style.background = _tlFps > 0
        ? 'rgba(53,224,255,0.32)' : 'rgba(255,255,255,0.10)';
      _tlDraw();                 // relabel only; NO _tlAfterEdit()
    }});

    // ---- X deletes the selected keyframes (in-memory mutation +
    //      spline rebuild; refuse to drop below 2 so the path stays
    //      a valid spline -- a sensible clamp, not a hidden mode).
    window.addEventListener('keydown', (ev) => {{
      if (!ModeManager.is('author')) return;
      if (ev.key !== 'x' && ev.key !== 'X' &&
          ev.key !== 'Delete') return;
      // Ignore when typing in an input (none here, but defensive).
      const ae = document.activeElement;
      if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' ||
          ae.tagName === 'SELECT')) return;
      if (!_tlSel.size) return;
      const p = _tlActivePath();
      if (!p || !p.keyframes) return;
      const keep = [];
      for (let i = 0; i < p.keyframes.length; i++) {{
        if (!_tlSel.has(i)) keep.push(p.keyframes[i]);
      }}
      if (keep.length < 2) {{
        // Clamp: a path needs >= 2 keyframes to be a spline; ignore
        // a delete that would invalidate it (do NOT silently break
        // the path).
        return;
      }}
      p.keyframes = keep;
      _tlSel.clear();
      _tlAfterEdit();
    }});

    // The strip + diamonds + playhead must follow window resize and
    // the splat canvas size (it is absolutely positioned over it).
    window.addEventListener('resize', _tlResize);
    // Initial layout once the strip has a measured size (next frame
    // so getBoundingClientRect is non-zero), then keep the playhead
    // synced from the ONE OverlayScene tick (no parallel rAF: we
    // fan a tiny per-frame playhead sync off the SAME tick the
    // Task-16 overlay already uses -- see the layer below).
    requestAnimationFrame(() => {{ _tlResize(); }});

    // Fan the per-frame playhead sync off the ONE OverlayScene
    // tick (Task-0 contract -- no parallel rAF). modes:['author']
    // so OverlayScene skips update() outside author mode (inert in
    // user/embed). node-less (it is pure DOM, not a 3D node) so
    // OverlayScene never touches a node's visibility for it.
    const _tlLayer = {{
      id: 'editor-timeline',
      modes: ['author'],
      update() {{
        if (!ModeManager.is('author')) return;
        if (!_tlScrubbing) _tlSyncPlayhead();
      }},
    }};
    OverlayScene.register(_tlLayer);

    // ---- TEST-ONLY surface extension (mirror window.__clip /
    //      __transport / the Task-16 window.__editor: getters +
    //      deterministic hooks; NO production reader; inert without
    //      the harness). Extends the EXISTING window.__editor object
    //      (created by the Task-16 block above) so the harness reads
    //      one surface. Every hook drives the REAL code path a user
    //      action would (the same convention as __editor.scrubTo /
    //      __clip.restart).
    try {{
      if (window.__editor) {{
        const _api = {{
          // ---- read state ----
          get tlPresent() {{ return !!_tlStrip.parentNode; }},
          get tlZoom() {{ return _tlZoom; }},
          get tlScroll() {{ return _tlScroll; }},
          get tlFps() {{ return _tlFps; }},
          get tlDuration() {{ return _tlDuration(_tlActivePath()); }},
          get tlSelection() {{
            return Array.from(_tlSel).sort((a, b) => a - b);
          }},
          // The stored keyframe times (SECONDS) of the active path,
          // in keyframe-array order (NOT sorted) so the harness can
          // assert a SPECIFIC kf's t changed / is byte-identical.
          get tlKfTimes() {{
            const p = _tlActivePath();
            return (p && p.keyframes)
              ? p.keyframes.map(k => (k.t || 0)) : [];
          }},
          // Diamond screen positions (px) + their kf.t, so the
          // harness can assert px == time->px under zoom/scroll.
          get tlDiamonds() {{
            const p = _tlActivePath();
            if (!p || !p.keyframes) return [];
            return p.keyframes.map((k, i) => ({{
              i: i, t: (k.t || 0), x: _tlT2X(k.t || 0),
              sel: _tlSel.has(i),
            }}));
          }},
          // Playhead time (seconds) + px -- the harness asserts a
          // playhead drag moves the CAMERA (read _spDebug.camera).
          get tlPlayheadT() {{ return _tlPlayheadT(); }},
          get tlPlayheadX() {{
            return parseFloat(_tlPlayhead.style.left) || 0;
          }},
          get tlActivePathId() {{
            const p = _tlActivePath();
            return p ? (p.id || null) : null;
          }},
          get tlLoop() {{
            const p = _tlActivePath();
            return !!(p && p.loop);
          }},
          // ---- deterministic hooks (drive the REAL handlers) ----
          // Live scrub: routes through the REAL #path-scrub input
          // mechanism (single source of truth -- takes _player over
          // + rebases _t0, robust to the auto-tour). frac in 0..1.
          tlScrub(frac) {{
            const dur = _tlDuration(_tlActivePath());
            _tlScrubToTime(Math.max(0, Math.min(1, +frac || 0)) * dur);
            return _tlPlayheadT();
          }},
          // Temporal edit: set keyframe[idx].t = newT (the SAME
          // mutation a diamond drag performs) + rebuild.
          tlDragKf(idx, newT) {{
            const p = _tlActivePath();
            if (!p || !p.keyframes || !p.keyframes[idx]) return false;
            let t = +newT;
            if (!isFinite(t)) return false;
            if (t < 0) t = 0;
            p.keyframes[idx].t = t;
            _tlAfterEdit();
            return true;
          }},
          // Selection set (by kf index) -- the SAME state a marquee
          // produces; lets the harness deterministically select 2+.
          tlSelect(idxs) {{
            _tlSel.clear();
            (idxs || []).forEach((i) => {{
              if (i >= 0) _tlSel.add(i | 0);
            }});
            _tlDraw();
            return Array.from(_tlSel).sort((a, b) => a - b);
          }},
          // Box-select by a time window [t0,t1] (drives the SAME
          // marquee selection math the pointer path uses).
          tlBoxSelect(t0, t1) {{
            const p = _tlActivePath();
            _tlSel.clear();
            if (p && p.keyframes) {{
              const lo = Math.min(+t0, +t1), hi = Math.max(+t0, +t1);
              for (let i = 0; i < p.keyframes.length; i++) {{
                const t = p.keyframes[i].t || 0;
                if (t >= lo && t <= hi) _tlSel.add(i);
              }}
            }}
            _tlDraw();
            return Array.from(_tlSel).sort((a, b) => a - b);
          }},
          // Scale the selected span by dragging an EDGE: move the
          // grabbed edge ('left'|'right') to newEdgeT; the opposite
          // edge is the fixed anchor; proportional rescale (the
          // SAME math _tlOnMove('scale') runs). Returns the post-
          // scale stored times of the selected kfs.
          tlScaleSelection(edge, newEdgeT) {{
            const p = _tlActivePath();
            if (!p || !p.keyframes || _tlSel.size < 2) return null;
            let lo = Infinity, hi = -Infinity;
            _tlSel.forEach((i) => {{
              const k = p.keyframes[i]; if (!k) return;
              const t = k.t || 0;
              if (t < lo) lo = t; if (t > hi) hi = t;
            }});
            if (!isFinite(lo) || !isFinite(hi) || lo === hi)
              return null;
            const anchor = (edge === 'right') ? lo : hi;
            let base0 = Math.abs(((edge === 'right') ? hi : lo) -
              anchor);
            if (base0 <= 1e-6) return null;
            let cur = Math.abs((+newEdgeT) - anchor);
            if (cur < 1e-4) cur = 1e-4;
            const ratio = cur / base0;
            const base = [];
            _tlSel.forEach((i) => {{
              base.push({{ i: i, t0: (p.keyframes[i].t || 0) }});
            }});
            for (const e of base) {{
              let nt = anchor + (e.t0 - anchor) * ratio;
              if (nt < 0) nt = 0;
              p.keyframes[e.i].t = nt;
            }}
            _tlAfterEdit();
            return {{ anchor: anchor, ratio: ratio,
              times: Array.from(_tlSel).sort((a, b) => a - b)
                .map(i => (p.keyframes[i].t || 0)) }};
          }},
          // X delete the current selection (the SAME mutation the
          // keydown handler performs; honours the >=2 clamp).
          tlDeleteSelection() {{
            const p = _tlActivePath();
            if (!p || !p.keyframes || !_tlSel.size) return false;
            const keep = [];
            for (let i = 0; i < p.keyframes.length; i++) {{
              if (!_tlSel.has(i)) keep.push(p.keyframes[i]);
            }}
            if (keep.length < 2) return false;
            p.keyframes = keep;
            _tlSel.clear();
            _tlAfterEdit();
            return true;
          }},
          // Transport (drive the REAL #path-play/#path-stop reuse).
          tlPlay() {{
            const p = _tlActivePath();
            if (p && p.id && selEl) {{
              try {{ selEl.value = p.id; }} catch (e) {{}}
            }}
            try {{ startPath(selEl ? selEl.value : (p && p.id)); }}
            catch (e) {{}}
            return !!_player;
          }},
          tlPause() {{
            try {{ stopPath(); }} catch (e) {{}}
            _tlSyncPlayhead();
            return !_player;
          }},
          tlToggleLoop() {{
            const p = _tlActivePath();
            if (!p) return null;
            p.loop = !p.loop;
            _tlAfterEdit();
            return !!p.loop;
          }},
          // Wheel zoom about a time (the SAME zoom math the wheel
          // handler runs); factor>1 zooms IN. Storage stays seconds.
          tlZoomAbout(tAt, factor) {{
            const xAt = _tlT2X(+tAt);
            _tlZoom = Math.max(_TL_ZOOM_MIN,
              Math.min(_TL_ZOOM_MAX, _tlZoom * (+factor || 1)));
            _tlScroll = (+tAt) - (xAt - _TL_PAD) / _tlZoom;
            if (_tlScroll < 0) _tlScroll = 0;
            _tlDraw();
            _tlSyncPlayhead();
            return _tlZoom;
          }},
          // fps grid toggle (RELABEL ONLY -- asserts stored t
          // unchanged before/after). Pass a specific fps or cycle.
          tlSetFps(v) {{
            _tlFps = (v && v > 0) ? (v | 0) : 0;
            _tlFpsBtn.textContent =
              _tlFps > 0 ? (_tlFps + 'fps') : 'fps';
            _tlDraw();
            return _tlFps;
          }},
          // The Task-16 trajectory overlay's current keyframe
          // signature -- so the harness can assert an in-memory
          // temporal edit actually triggered the overlay rebuild
          // (the sig CHANGED) without a save/network.
          get tlOverlaySig() {{
            try {{
              const p = _tlActivePath();
              return (typeof _trajKfSig === 'function')
                ? _trajKfSig(p) : '';
            }} catch (e) {{ return ''; }}
          }},
        }};
        // Copy onto the Task-16 window.__editor PRESERVING getters as
        // GETTERS (Object.assign would invoke each getter once and
        // freeze the RESULT as a static data property -- so a later
        // tlZoomAbout/tlSetFps/tlDragKf mutation would not be visible
        // through window.__editor.tlZoom/.tlFps/.tlKfTimes). Copy the
        // property DESCRIPTORS so the getters stay live (mirrors how
        // the Task-16 surface itself uses real getters).
        Object.defineProperties(
          window.__editor, Object.getOwnPropertyDescriptors(_api));
      }}
    }} catch (e) {{}}
  }})();

  // ============================================================
  //  Author editor -- select-key gizmo + interp popover +
  //  Record(K) + Save/Emit SPCP (Task 18 -- plan H2/Task-14)
  // ------------------------------------------------------------
  //  AUTHOR MODE ONLY (ModeManager.is('author')): user / embed and
  //  the 6 live single-camera scenes are byte-runtime-unchanged --
  //  every code path here is gated by the SAME _EDITOR_AUTHOR flag
  //  the Task-16 trajectory overlay + the Task-17 timeline use, and
  //  every DOM/listener/THREE object is only ever created in author
  //  mode (so this whole section is inert in user/embed; the
  //  byte-lock proves the 6 live scenes' generated HTML is
  //  byte-identical -- this code sits strictly INSIDE the Task-16
  //  T16-TRAJ region, recipe 2c, so it is absorbed by that region's
  //  EXISTING excision and the moving-baseline remainder is
  //  unaffected by it).
  //  The IMPORT: TransformControls is loaded via a DYNAMIC
  //  import('three/addons/controls/TransformControls.js') -- the
  //  ``three/addons/`` prefix ALREADY resolves through the existing
  //  importmap (the SAME mapping OrbitControls/CSS2DRenderer use),
  //  so there is NO new importmap entry and NO shared-HTML change:
  //  the import statement is region-interior author-gated code, not
  //  a top-level static import that would land OUTSIDE T16-TRAJ.
  //  WHAT IT DOES (the Task-18 scope):
  //    * click a trajectory frustum (the Task-16 _trajFrusta meshes)
  //      -> select that keyframe -> attach TransformControls to a
  //      proxy Object3D parked at the keyframe pose.
  //    * drag the gizmo -> write the proxy's pose back to THAT
  //      keyframe's kf.pos (translate) / kf.quat (rotate) IN MEMORY
  //      (the SAME object the live player + the Task-16 overlay +
  //      the Task-17 timeline read) -> _trajRebuild + sig bump so
  //      the Task-16 overlay + Task-17 diamonds rebuild. NO save.
  //    * SPACE toggles World <-> Screen (Screen = camera-aligned
  //      axes: TransformControls 'local' space on a proxy whose
  //      quaternion we keep == the camera's, so the gizmo axes
  //      track the screen). R / T toggle rotate / translate.
  //    * V opens a 5-type interp popover (a segmented control over
  //      the EXISTING _VALID_INTERP set) and writes the selected
  //      keyframe's kf.interp -> rebuild (the spline already honours
  //      per-keyframe interp via _kfMeta).
  //    * K records a keyframe = the LIVE camera pose + the REAL
  //      elapsed playhead t (the SAME single-source-of-truth clock
  //      _trajPlayhead() returns -- the live _player/_t0 clock while
  //      a tour plays, else the #path-scrub position; this is the
  //      in-viewer analogue of the Task-5 "recording uses real
  //      elapsed time" fix, NOT a reinvented timer) appended to the
  //      active path's keyframes -> rebuild.
  //    * Save: SAVE_MODE=="cli" (the decision-A DEFAULT) emits an
  //      SPCP1:<slug>:<b64url> token + the
  //      `splatpipe set-camera-path <token>` command in an
  //      on-screen textarea + copy-to-clipboard, MIRRORING the
  //      existing SPV1 "Set start view" relay UI (no client secret,
  //      identical trust model). SAVE_MODE=="http" (opt-in) POSTs
  //      the camera-scope patch JSON to SAVE_ENDPOINT with
  //      Authorization: Bearer <secret> where <secret> is read ONLY
  //      from the author URL fragment (#author=<secret>).
  //  AUTO-TOUR: in ?author=1 the default-path tour AUTO-PLAYS
  //  (_cinematic is usermode-only). Authoring while it auto-advances
  //  is disorienting, so the FIRST author interaction (gizmo attach
  //  / Record / interp open) does an EXPLICIT stopPath() -- the
  //  SAME single stop mechanism the Task-17 timeline's pause/scrub
  //  reuse (NOT a change to Task-13's _cinematic gate; an explicit
  //  interaction stop, exactly like the Task-15 end-user interrupt).
  //  The SPCP1 codec is a BYTE-IDENTICAL JS port of
  //  core/spcp_token.encode_spcp: compact JSON
  //  (separators (",",":"), ensure_ascii=True, key INSERTION order
  //  -- NO sort_keys) -> urlsafe base64 -> rstrip('='). The number
  //  formatter (_spcpNum) reproduces CPython json.dumps' float repr
  //  (integer-valued -> integer literal -> a json.loads/json.dumps
  //  fixed point; |x|<1e-4 -> zero-padded sci e[+-]NN like Python,
  //  NOT JS fixed-notation) so a Python decode_spcp(js_token)
  //  round-trips AND encode_spcp(slug, that payload) == js_token
  //  byte-for-byte (the spec's core correctness gate, asserted by a
  //  real pytest check on the harness-captured token).
  //  Payload = Contract-C / ALLOWED_PATCH_KEYS ONLY:
  //  start_view, camera_paths, clips, cameras, default_path_id,
  //  intro, titles3d, spark_render, annotations -- wrapped as
  //  {{ v:1, scope:'camera_paths', ...patch }}. NEVER primary_asset
  //  (the locked Speicher-blank invariant; merge_camera_scope
  //  force-keeps the live pointer and ALLOWED_PATCH_KEYS asserts it
  //  is excluded -- the emitted payload must respect that).
  //  window.__editor is EXTENDED (TEST-ONLY: getters + deterministic
  //  hooks, same convention as the Task-16/17 surface; no production
  //  reader; inert without the harness).
  //  Reuses, never reinvents: _trajActivePath/_trajPlayhead/
  //  _trajRebuild/_trajKfSig/_trajFrusta (Task-16), buildPlayer/
  //  sampleAt (the SuperSplat spline), the _raycaster (the existing
  //  scene raycaster), InteractionManager (pointer brokering vs
  //  OrbitControls/playback), stopPath (the single stop mechanism),
  //  the SPV1 relay-UI pattern, _VALID_INTERP, SAVE_MODE/
  //  SAVE_ENDPOINT (Task-8 -- consumed, NOT re-added).
  // ============================================================
  (function _gzInit() {{
    if (!_EDITOR_AUTHOR) return;

    // ---- Suppress the auto-tour in ?author=1 (the SECOND half of the
    //      "cannot move the keyframes" bug). The intro controller's
    //      cinematic gate is usermode-ONLY, so in author mode it falls
    //      into the immediate `_introStartTour()` path and the default
    //      cinematic plays on load -- ending with the camera PARKED
    //      inside the dense end-of-path keyframe cluster. From there
    //      every keyframe frustum projects centimetres from the camera
    //      (gizmo + frusta thousands of px off-screen) so NO keyframe
    //      is clickable / draggable. An author opens the editor to
    //      EDIT, not to watch the tour: keep the camera at the saved
    //      start_view (a sane authoring vantage where all keyframes
    //      are visible) by making `_introStartTour()` a guaranteed
    //      no-op -- it bails on `if (_introTourStarted) return;`, the
    //      SAME idempotency guard the fade/fallback paths already rely
    //      on. This is an author-mode-only behavior gate (NOT a
    //      _cinematic change) and is fully inert for the 6 live
    //      usermode scenes (this whole block is _EDITOR_AUTHOR-gated).
    //      `_introTourStarted` is a top-level `let` declared well
    //      above; this IIFE runs BEFORE the intro-controller IIFE so
    //      the flag is set in time. Belt-and-braces: if a tour is
    //      somehow already live (race / future reorder) stop it and
    //      restore the start_view so the authoring camera is stable.
    try {{ _introTourStarted = true; }} catch (e) {{}}
    if (_player) {{
      try {{ stopPath(); }} catch (e) {{}}
      try {{
        const _sv = cfg && cfg.start_view;
        if (_sv && Array.isArray(_sv.pos)) {{
          camera.position.set(_sv.pos[0], _sv.pos[1], _sv.pos[2]);
          if (Array.isArray(_sv.quat)) {{
            camera.quaternion.set(_sv.quat[0], _sv.quat[1],
              _sv.quat[2], _sv.quat[3]);
          }}
          if (typeof _sv.fov === 'number') {{
            camera.fov = _sv.fov; camera.updateProjectionMatrix();
          }}
          if (Array.isArray(_sv.target) && controls &&
              controls.target) {{
            controls.target.set(_sv.target[0], _sv.target[1],
              _sv.target[2]);
          }}
          camera.updateMatrixWorld(true);
        }}
      }} catch (e) {{}}
    }}

    // ---- Slug for the SPCP1 token (mirror the SPV1 relay block):
    //      the page <title> h1 text, sanitised to the kebab/word set
    //      encode_spcp accepts (it rejects a ':' in the slug -- our
    //      sanitiser strips it, so split(':',2) is safe both ways).
    const _gzProjName = (document.querySelector('#title h1') &&
      document.querySelector('#title h1').textContent || 'scene').trim();
    const _gzSlug = (_gzProjName.replace(/[^A-Za-z0-9_-]+/g, '_')
      .slice(0, 48)) || 'scene';

    // ---- BYTE-IDENTICAL JS port of core/spcp_token.encode_spcp ----
    // Python: json.dumps(payload, separators=(",",":")).encode()
    //         -> base64.urlsafe_b64encode(...).rstrip("=")
    //         -> "SPCP1:" + slug + ":" + that
    // json.dumps defaults: ensure_ascii=True, NO sort_keys (key
    // INSERTION order). We replicate ALL of that exactly.
    //
    // _spcpNum: reproduce CPython json/float repr so a value
    // round-trips through Python json.loads -> json.dumps unchanged
    // (the byte-identity gate). Key facts (verified against CPython):
    //   * 0 / -0  -> "0"   (json.loads("0") is int 0 -> "0": a fixed
    //                        point; JS String(-0) is "0" too).
    //   * integer-valued, |n| < 1e21 -> String(n) (e.g. "2","-40").
    //     json.loads parses it as an int and re-dumps the SAME
    //     literal -> fixed point (covers the >=1e16 case too: JS
    //     emits the integer literal, Python keeps it an int).
    //   * fractional, 1e-4 <= |n| < 1e16 -> String(n): JS shortest
    //     round-trip digits == CPython's, both fixed-notation ->
    //     byte-identical.
    //   * fractional, |n| < 1e-4 (CPython switches to sci here):
    //     mantissa from toExponential() + Python-style exponent
    //     "e" + sign + >=2-digit zero-padded magnitude (JS gives
    //     "1e-5", Python "1e-05"; we pad to match).
    //   * non-finite -> never valid JSON (the clean payload has
    //     none); throw so a bug is loud, never silently NaN.
    function _spcpNum(n) {{
      if (!isFinite(n)) throw new Error('non-finite number in payload');
      if (n === 0) return '0';                 // also -0 (=== 0)
      if (Number.isInteger(n) && Math.abs(n) < 1e21) return String(n);
      if (Math.abs(n) >= 1e-4) return String(n);
      // |n| < 1e-4, fractional -> CPython sci: mantissa + e[+-]NN.
      const e = n.toExponential();             // e.g. "1.23e-5"
      const m = e.indexOf('e');
      const mant = e.slice(0, m);
      let exp = parseInt(e.slice(m + 1), 10);   // negative here
      const sign = exp < 0 ? '-' : '+';
      let mag = String(Math.abs(exp));
      if (mag.length < 2) mag = '0' + mag;      // zero-pad to >=2
      return mant + 'e' + sign + mag;
    }}
    // Python json string escaping with ensure_ascii=True: the JSON
    // string escapes (\\" \\\\ \\b \\f \\n \\r \\t), other C0
    // controls AND every non-ASCII codepoint as \\uXXXX (surrogate
    // pairs preserved as two \\uXXXX -- exactly what CPython emits;
    // JS strings are already UTF-16 so iterating code UNITS yields
    // the same pair encoding).
    function _spcpStr(s) {{
      let out = '"';
      for (let i = 0; i < s.length; i++) {{
        const c = s.charCodeAt(i);
        const ch = s[i];
        if (ch === '"') out += '\\\\"';
        else if (ch === '\\\\') out += '\\\\\\\\';
        else if (c === 8) out += '\\\\b';
        else if (c === 9) out += '\\\\t';
        else if (c === 10) out += '\\\\n';
        else if (c === 12) out += '\\\\f';
        else if (c === 13) out += '\\\\r';
        else if (c < 0x20 || c > 0x7e) {{
          out += '\\\\u' + c.toString(16).padStart(4, '0');
        }} else {{
          out += ch;
        }}
      }}
      return out + '"';
    }}
    // Compact JSON, key INSERTION order (NO sort), separators
    // (",",":") -- byte-for-byte json.dumps(payload,
    // separators=(",",":")). Arrays/objects recurse; null/bool
    // exactly as Python; numbers via _spcpNum; strings via _spcpStr.
    // (The payload we build holds only JSON-safe primitives, arrays
    // and plain objects -- the SAME shape that came from the
    // viewer-config JSON -- so this total covers it.)
    function _spcpJson(v) {{
      if (v === null) return 'null';
      const t = typeof v;
      if (t === 'boolean') return v ? 'true' : 'false';
      if (t === 'number') return _spcpNum(v);
      if (t === 'string') return _spcpStr(v);
      if (Array.isArray(v)) {{
        let s = '[';
        for (let i = 0; i < v.length; i++) {{
          if (i) s += ',';
          // Python json renders array None/NaN slots as null; an
          // undefined/function slot cannot occur in our payload, map
          // it to null defensively (never throw mid-encode).
          const e = v[i];
          s += (e === undefined || typeof e === 'function')
            ? 'null' : _spcpJson(e);
        }}
        return s + ']';
      }}
      if (t === 'object') {{
        let s = '{{';
        let first = true;
        // Object.keys preserves insertion order for string keys
        // (the payload keys are all plain strings) -- the SAME order
        // Python dict iteration would use for an equivalently-built
        // dict; encode_spcp does NOT sort, so we must NOT either.
        for (const k of Object.keys(v)) {{
          const val = v[k];
          // Python json SKIPS no keys (it would serialise None);
          // our payload never holds undefined/function values, but
          // skip such a slot defensively rather than emit invalid
          // JSON (a value Python could not have produced anyway).
          if (val === undefined || typeof val === 'function') continue;
          if (!first) s += ',';
          first = false;
          s += _spcpStr(k) + ':' + _spcpJson(val);
        }}
        return s + '}}';
      }}
      // undefined / symbol: not representable -- our payload never
      // contains these at the top level (guarded above for slots).
      throw new Error('unserialisable value in payload');
    }}
    function _b64urlBytes(str) {{
      // str is already pure ASCII (ensure_ascii=True), so its UTF-8
      // == its byte values; btoa over it == Python
      // base64.urlsafe_b64encode of the same bytes, then '+/' ->
      // '-_' and strip '=' (encode_spcp's exact tail).
      const b64 = btoa(str);
      return b64.replace(/\\+/g, '-').replace(/\\//g, '_')
        .replace(/=+$/, '');
    }}
    function _encodeSpcp(slug, payload) {{
      if (String(slug).indexOf(':') !== -1) {{
        // Mirror encode_spcp's slug guard (a ':' would break the
        // cross-language split(':',2) decode). Our sanitiser already
        // strips ':' so this never fires in practice; defensive.
        throw new Error("slug must not contain ':'");
      }}
      const json = _spcpJson(payload);
      return 'SPCP1:' + slug + ':' + _b64urlBytes(json);
    }}

    // ---- Build the Contract-C camera-scope patch from the AUTHORED
    //      in-memory state. ONLY the locked allow-list keys
    //      (start_view, camera_paths, clips, cameras,
    //      default_path_id, intro, titles3d, spark_render,
    //      annotations) -- NEVER primary_asset (the Speicher-blank
    //      invariant: merge_camera_scope force-keeps the live
    //      pointer; emitting it here would be a critical breach).
    //      Values are taken from the LIVE cfg object (the same
    //      object the Task-16/17 in-memory edits + Record(K) + the
    //      gizmo mutate in place) so the author's edits are exactly
    //      what gets persisted. Missing keys are simply omitted (a
    //      whole-replace merge -- absent key == leave the live
    //      config's value untouched).
    const _PATCH_KEYS = ['start_view', 'camera_paths', 'clips',
      'cameras', 'default_path_id', 'intro', 'titles3d',
      'spark_render', 'annotations'];
    function _buildPatch() {{
      const patch = {{}};
      for (const k of _PATCH_KEYS) {{
        if (cfg && Object.prototype.hasOwnProperty.call(cfg, k) &&
            cfg[k] !== undefined && cfg[k] !== null) {{
          patch[k] = cfg[k];
        }}
      }}
      return patch;
    }}
    function _buildSpcpPayload() {{
      // Exactly decode_spcp's gate shape: v + scope FIRST (insertion
      // order), then the allow-listed camera-scope keys. (Python
      // round-trip: decode_spcp checks v==1 & scope=='camera_paths';
      // the cli backend's merge_camera_scope then ignores v/scope
      // and applies only ALLOWED_PATCH_KEYS -- so including them in
      // the token envelope is correct and required.)
      const p = {{ v: 1, scope: 'camera_paths' }};
      const patch = _buildPatch();
      for (const k of Object.keys(patch)) p[k] = patch[k];
      return p;
    }}

    // ---- Explicit auto-tour stop (single source of truth). In
    //      ?author=1 the default-path tour auto-plays; the first
    //      authoring gesture stops it via the EXISTING stopPath()
    //      (the SAME mechanism Task-17's pause uses) so the gizmo
    //      drag / Record happen against a still camera. This is an
    //      explicit interaction stop, NOT a _cinematic-gate change.
    let _gzTourStopped = false;
    function _gzStopTour() {{
      if (_player) {{
        try {{ stopPath(); }} catch (e) {{}}
        _gzTourStopped = true;
      }}
    }}

    // ---- Selection + gizmo state. _gzProxy is a bare Object3D the
    //      TransformControls drives; we mirror its pose to/from the
    //      selected keyframe. It is added to the scene ONLY while a
    //      key is selected and removed on deselect (no leak). The
    //      TransformControls 'helper' (its visible gizmo) is added/
    //      removed alongside.
    let _gzCtl = null;            // TransformControls instance (lazy)
    let _gzProxy = null;          // THREE.Object3D the gizmo drives
    let _gzSelKf = -1;            // selected keyframe index (-1 none)
    let _gzMode = 'translate';    // 'translate' | 'rotate'
    let _gzScreen = false;        // false = World, true = Screen
    let _gzDragging = false;
    let _gzImportPromise = null;  // memoised dynamic import
    let _gzPopEl = null;          // the interp popover element
    let _gzCtlHelper = null;      // the gizmo's visible helper object

    function _gzActivePath() {{
      return (typeof _trajActivePath === 'function')
        ? _trajActivePath() : null;
    }}
    // The keyframe OBJECT for the current selection (selection is by
    // the Task-16 frustum's kfIndex == the path's keyframes[] index;
    // _trajRebuild builds one frustum per keyframe IN ORDER).
    function _gzSelKfObj() {{
      const p = _gzActivePath();
      if (!p || !p.keyframes || _gzSelKf < 0 ||
          _gzSelKf >= p.keyframes.length) return null;
      return p.keyframes[_gzSelKf];
    }}

    // Push the selected keyframe's pose onto the proxy (so the gizmo
    // sits exactly where the camera will be for that key).
    const _GZ_TMPQ = new THREE.Quaternion();
    function _gzSyncProxyFromKf() {{
      const kf = _gzSelKfObj();
      if (!kf || !_gzProxy) return;
      const pos = (kf.pos && kf.pos.length === 3) ? kf.pos : [0, 0, 0];
      _gzProxy.position.set(pos[0], pos[1], pos[2]);
      const q = (kf.quat && kf.quat.length === 4)
        ? kf.quat : [0, 0, 0, 1];
      _gzProxy.quaternion.set(q[0], q[1], q[2], q[3]);
      _gzProxy.updateMatrixWorld(true);
    }}

    // Trigger the Task-16 overlay + the Task-17 timeline to re-read
    // the mutated keyframe NOW (deterministic for the harness; the
    // OverlayScene sig check would also rebuild on the next tick --
    // _trajKfSig includes pos/quat/interp). Also null _player if it
    // is driving THIS path so a later Play re-derives the geometry.
    function _gzAfterEdit() {{
      const p = _gzActivePath();
      if (!p) return;
      try {{
        _trajRebuild(p);
        _trajPhPlayer = p ? buildPlayer(p) : null;
      }} catch (e) {{}}
      // Bump the built-sig mismatch so the OverlayScene update()
      // path also rebuilds (belt-and-braces; _trajRebuild already
      // reset it -- this just guarantees a mismatch if a later
      // tick races).
      try {{
        if (window.__editor && typeof window.__editor.rebuild ===
            'function') window.__editor.rebuild();
      }} catch (e) {{}}
      if (_player && _activePathId === (p.id || _activePathId)) {{
        // A pose edit while the player drives this path: rebuild it
        // in place (reuse buildPlayer -- the one spline impl) so the
        // edit is not lost; if it cannot build, stop cleanly.
        const np = buildPlayer(p);
        if (np) _player = np;
        else {{ try {{ stopPath(); }} catch (e) {{}} }}
      }}
      // Re-place the bezier tangent handles after the rebuild: the
      // keyframe pos may have moved (main gizmo) and _trajApplyScale
      // may have re-derived _trajFrLen, so the handle distance/box
      // size + line endpoints must track. No-op when no handles are
      // shown (function declarations are hoisted in this IIFE so
      // calling _tanRefresh defined further below is valid).
      try {{ _tanRefresh(); }} catch (e) {{}}
    }}

    // Write the proxy's CURRENT pose back to the selected keyframe
    // (translate -> kf.pos; rotate -> kf.quat). Called on the
    // TransformControls 'objectChange' so the trajectory tracks the
    // drag live (the spec's "drag -> kf.pos changes + trajectory
    // rebuilds").
    function _gzWriteProxyToKf() {{
      const kf = _gzSelKfObj();
      if (!kf || !_gzProxy) return;
      kf.pos = [_gzProxy.position.x, _gzProxy.position.y,
        _gzProxy.position.z];
      _gzProxy.getWorldQuaternion(_GZ_TMPQ);
      kf.quat = [_GZ_TMPQ.x, _GZ_TMPQ.y, _GZ_TMPQ.z, _GZ_TMPQ.w];
      _gzAfterEdit();
    }}

    // Apply the World/Screen + translate/rotate mode to the live
    // control. Screen == camera-aligned axes: TransformControls'
    // 'local' space on a proxy whose rotation we keep equal to the
    // camera's, so the gizmo's axes follow the screen. World ==
    // 'world' space (the proxy keeps the keyframe's own rotation,
    // restored from the keyframe so a space round-trip is lossless).
    function _gzApplySpace() {{
      if (!_gzCtl) return;
      _gzCtl.setMode(_gzMode);
      if (_gzScreen) {{
        // Camera-aligned: drive the gizmo in the proxy's LOCAL
        // frame and make that frame == the camera orientation.
        _gzProxy.quaternion.copy(camera.quaternion);
        _gzProxy.updateMatrixWorld(true);
        _gzCtl.setSpace('local');
      }} else {{
        // World axes: restore the keyframe's own orientation onto
        // the proxy (so a rotate drag edits the real kf.quat) and
        // use world space.
        _gzSyncProxyFromKf();
        _gzCtl.setSpace('world');
      }}
    }}

    // Lazily import + construct TransformControls (dynamic import
    // via the EXISTING ``three/addons/`` importmap mapping -- no new
    // importmap entry; region-interior). Resolves to the control or
    // null (import failure must never throw into the author UI).
    function _gzEnsureControl() {{
      if (_gzCtl) return Promise.resolve(_gzCtl);
      if (!_gzImportPromise) {{
        _gzImportPromise = import(
          'three/addons/controls/TransformControls.js'
        ).then((mod) => {{
          const TC = mod && (mod.TransformControls ||
            (mod.default && mod.default.TransformControls) ||
            mod.default);
          if (!TC) return null;
          const ctl = new TC(camera, renderer.domElement);
          ctl.setSize(0.9);
          // The gizmo's visible part. r150+ exposes getHelper();
          // older builds ARE the Object3D. Add ONLY the helper (or
          // the control) to the scene -- never both -- so there is
          // exactly one gizmo in the graph.
          const helper = (typeof ctl.getHelper === 'function')
            ? ctl.getHelper() : ctl;
          _gzCtlHelper = helper;
          // While the gizmo is grabbed, OrbitControls must NOT also
          // move the camera. Broker through the ONE InteractionManager
          // (the Task-0 contract): take a NON-exclusive 'tool' owner
          // on drag-start, release on drag-end, and gate OrbitControls
          // off for the drag (mirrors how playback flips
          // controls.enabled). 'dragging-changed' is TransformControls'
          // canonical drag signal.
          ctl.addEventListener('dragging-changed', (ev) => {{
            _gzDragging = !!ev.value;
            if (_gzDragging) {{
              // A real handle grab is an authoring gesture: stop any
              // auto-tour FIRST so the render loop's `if (_player)`
              // block does not re-sample the OLD spline every frame
              // and stomp the live edit invisibly. _gzStopTour() is
              // idempotent (no-op when _player is null -- the normal
              // author-mode case now that the tour is suppressed);
              // this is the safety net for any race / future reorder.
              _gzStopTour();
              InteractionManager.requestPointer('tool');
              controls.enabled = false;
            }} else {{
              InteractionManager.releasePointer('tool');
              // Restore OrbitControls only if nothing exclusive
              // (a path/bench) is driving the camera.
              if (!InteractionManager.isCameraOwned()) {{
                controls.enabled = true;
              }}
            }}
          }});
          // Live write-back: every gizmo move edits the selected
          // keyframe + rebuilds the trajectory (the spec's
          // "drag -> kf.pos changes + trajectory rebuilds").
          ctl.addEventListener('objectChange', () => {{
            _gzWriteProxyToKf();
          }});
          _gzCtl = ctl;
          if (helper && helper.parent !== scene) scene.add(helper);
          return ctl;
        }}).catch(() => null);
      }}
      return _gzImportPromise;
    }}

    // Attach the gizmo to a keyframe (idx = the path keyframes[]
    // index, == the Task-16 frustum kfIndex). Creates the proxy if
    // needed, parks it at the keyframe, attaches TransformControls.
    function _gzAttach(idx) {{
      const p = _gzActivePath();
      if (!p || !p.keyframes || idx < 0 ||
          idx >= p.keyframes.length) return;
      // First authoring gesture: stop the auto-tour (explicit
      // interaction stop -- the SAME stopPath() Task-17 reuses).
      _gzStopTour();
      _gzSelKf = idx;
      if (!_gzProxy) {{
        _gzProxy = new THREE.Object3D();
        _gzProxy.name = 'editor-gizmo-proxy';
      }}
      if (_gzProxy.parent !== scene) scene.add(_gzProxy);
      _gzSyncProxyFromKf();
      // If this keyframe already carries explicit bezier tangents,
      // show its grab-able in/out handles immediately; otherwise
      // hide any handles from a previous selection (a non-bezier key
      // has none until the author presses B / the tangents button).
      if (_tanIsBezierSel()) _tanShow(); else _tanHide();
      _gzEnsureControl().then((ctl) => {{
        if (!ctl || _gzSelKf !== idx) return;
        ctl.attach(_gzProxy);
        _gzApplySpace();
        _trajRefreshActive();
      }});
    }}

    // Detach + hide the gizmo (deselect). Removes the proxy + the
    // helper from the scene so there is no orphan/leak; the
    // TransformControls instance itself is kept (memoised) for
    // re-attach -- attach/detach is its designed lifecycle.
    function _gzDetach() {{
      _gzSelKf = -1;
      if (_gzCtl) {{
        try {{ _gzCtl.detach(); }} catch (e) {{}}
      }}
      if (_gzProxy && _gzProxy.parent) {{
        _gzProxy.parent.remove(_gzProxy);
      }}
      _tanHide();
      controls.enabled = !InteractionManager.isCameraOwned();
    }}

    // ============================================================
    //  GRAB-ABLE BEZIER TANGENT HANDLES (the "Nice Tangents", 3ds-
    //  Max-style). For the SELECTED keyframe, when its interp is
    //  `bezier`, draw a small IN-handle + OUT-handle (little squares
    //  on thin tangent lines) the author DRAGS WITH A REAL MOUSE to
    //  reshape the curve. This is REAL, not cosmetic: the drag writes
    //  kf.in_tan / kf.out_tan (and pins kf.interp='bezier'); the
    //  EXISTING CubicSpline.calcKnots KF_BEZIER branch already maps
    //  km.in_tan[j]/km.out_tan[j] onto the pos.xyz Hermite tangents
    //  (mIn/mOut) -- so the trajectory polyline + the Task-17 timeline
    //  visibly reshape, and the SPCP camera_paths payload round-trips
    //  the tangents (they are plain number arrays inside a keyframe;
    //  merge_camera_scope whole-replaces camera_paths and the SPCP
    //  codec serialises arrays-of-numbers byte-identically -- proven
    //  by tests/test_spcp_js_port.py). NO spline-math change: the
    //  schema (path_io.KeyframeDict.in_tan/out_tan) + the spline's
    //  KF_BEZIER consumption already exist; this is purely the
    //  "draggable handles are a later phase" UI the spline comment
    //  anticipated.
    //  HANDLE <-> TANGENT MATH. The spline tangent for dim j is a
    //  WORLD-SPACE value-delta over the unit Hermite segment (see
    //  evaluateSegment: m0=knots[idx+2], m1=knots[idx+dim*3], basis
    //  p0(1+2t)(1-t)^2 + m0 t(1-t)^2 + p1 t^2(3-2t) + m1 t^2(t-1)).
    //  The OUT-handle world point = kf.pos + outTan * _TAN_FRAC; the
    //  IN-handle = kf.pos - inTan * _TAN_FRAC (drawn on the INCOMING
    //  side, the DCC convention). _TAN_FRAC scales the (time-scaled,
    //  possibly large) tangent down to a grab-able on-curve length;
    //  the inverse on drag is exact: tan = (handleWorld - kf.pos) /
    //  _TAN_FRAC  (out), = (kf.pos - handleWorld) / _TAN_FRAC (in).
    //  DEFAULT (no explicit tangents yet): derive EXACTLY what the
    //  spline's KF_BEZIER no-handle fallback uses (the `automatic`
    //  formula tangent*inScale / tangent*outScale, tangent =
    //  (pNext-pPrev)/(t_next-t_prev)) so converting a key to bezier
    //  produces ZERO visual jump (the handles start ON the curve).
    //  DRAG = a REAL trusted mouse: a DEDICATED translate-only
    //  TransformControls (the SAME proven addon pattern the keyframe
    //  gizmo uses -- synthetic pointer events do NOT drive it; only a
    //  trusted mouse does) attaches to whichever handle proxy the
    //  pointer grabs; its 'objectChange' recomputes the tangent +
    //  rebuilds. The pick integrates into the EXISTING
    //  _gzOnCanvasDown capture handler (yield to the handle TC when
    //  the pointer is over its gizmo, exactly like the keyframe
    //  gizmo) so a real handle drag is never starved. All region-
    //  interior to T16-TRAJ (recipe 2c) -- author-mode only, inert
    //  for the 6 live scenes.
    // ============================================================
    // On-curve handle length = a fraction of the active-path frustum
    // scale (_trajFrLen is itself scene-relative, set per rebuild by
    // _trajApplyScale) so handles read at the PATH's scale -- never
    // scene-spanning, never sub-pixel. The little square is a small
    // fraction of THAT, like the frustum image-plane.
    const _TAN_FRAC_OF_FR = 1.6;     // handle distance ~ 1.6x frustum len
    const _TAN_BOX_OF_FR = 0.34;     // handle square ~ 0.34x frustum len
    const _TAN_COL_OUT = 0x57ff8a;   // OUT handle: green (3ds-Max-ish)
    const _TAN_COL_IN = 0xff5d6b;    // IN handle: red
    const _TAN_LINE_OPACITY = 0.85;
    let _tanGroup = null;            // THREE.Group: lines + boxes
    let _tanInProxy = null;          // Object3D the handle-TC drives (IN)
    let _tanOutProxy = null;         // ... (OUT)
    let _tanInBox = null, _tanOutBox = null;     // visible squares
    let _tanInLine = null, _tanOutLine = null;   // kf->handle lines
    let _tanCtl = null;              // dedicated translate-only TC (lazy)
    let _tanCtlHelper = null;
    let _tanCtlImport = null;        // memoised dynamic import
    let _tanDragging = false;
    let _tanActiveSide = null;       // 'in' | 'out' while a drag is live
    const _TAN_TMP = new THREE.Vector3();

    // The world-space tangent length scale (>0). Recomputed off the
    // live _trajFrLen so it tracks the active path's scale.
    function _tanFrac() {{
      const fr = (typeof _trajFrLen === 'number' && _trajFrLen > 0)
        ? _trajFrLen : 0.4;
      return fr * _TAN_FRAC_OF_FR;
    }}
    function _tanBoxSize() {{
      const fr = (typeof _trajFrLen === 'number' && _trajFrLen > 0)
        ? _trajFrLen : 0.4;
      return fr * _TAN_BOX_OF_FR;
    }}

    // Is the selected keyframe in explicit-tangent (bezier) mode?
    function _tanIsBezierSel() {{
      const kf = _gzSelKfObj();
      return !!(kf && kf.interp === 'bezier');
    }}

    // The `automatic`-formula tangent (a world [x,y,z] value-delta)
    // for the selected keyframe -- IDENTICAL to what the spline's
    // KF_BEZIER no-handle fallback computes, so a derived default
    // produces no curve jump. Uses the SORTED keyframes (buildPlayer
    // order == the spline's knot order). `which` = 'in' | 'out'.
    function _tanAutoVec(which) {{
      const p = _gzActivePath();
      if (!p || !p.keyframes) return [0, 0, 0];
      const ks = p.keyframes.slice()
        .sort((a, b) => (a.t || 0) - (b.t || 0));
      const sel = _gzSelKfObj();
      let i = ks.indexOf(sel);
      if (i < 0) return [0, 0, 0];
      const n = ks.length;
      const t = (ks[i].t || 0);
      const tPrev = i > 0 ? (ks[i - 1].t || 0) : t;
      const tNext = i < n - 1 ? (ks[i + 1].t || 0) : t;
      const inScale = i > 0 ? (t - tPrev) : (n > 1
        ? ((ks[1].t || 0) - (ks[0].t || 0)) : 1);
      const outScale = i < n - 1 ? (tNext - t) : (i > 0
        ? (t - tPrev) : 1);
      const out = [0, 0, 0];
      for (let j = 0; j < 3; j++) {{
        const pj = (sel.pos && sel.pos.length === 3) ? sel.pos[j] : 0;
        const pPrev = (i > 0 && ks[i - 1].pos)
          ? ks[i - 1].pos[j] : pj;
        const pNext = (i < n - 1 && ks[i + 1].pos)
          ? ks[i + 1].pos[j] : pj;
        let tangent;
        if (i === 0) {{
          tangent = (tNext - t) ? (pNext - pj) / (tNext - t) : 0;
        }} else if (i === n - 1) {{
          tangent = (t - tPrev) ? (pj - pPrev) / (t - tPrev) : 0;
        }} else {{
          tangent = (tNext - tPrev)
            ? (pNext - pPrev) / (tNext - tPrev) : 0;
        }}
        out[j] = tangent * (which === 'in' ? inScale : outScale);
      }}
      return out;
    }}

    // Read the selected keyframe's effective in/out tangent vectors
    // (explicit kf.in_tan/out_tan when present + length 3, else the
    // `automatic` derived default). Returns {{ inv:[x,y,z],
    // outv:[x,y,z] }} or null.
    function _tanVecs() {{
      const kf = _gzSelKfObj();
      if (!kf || !kf.pos || kf.pos.length !== 3) return null;
      const inv = (Array.isArray(kf.in_tan) && kf.in_tan.length === 3)
        ? kf.in_tan.slice() : _tanAutoVec('in');
      const outv = (Array.isArray(kf.out_tan) && kf.out_tan.length === 3)
        ? kf.out_tan.slice() : _tanAutoVec('out');
      return {{ inv: inv, outv: outv }};
    }}

    // Build the handle geometry once (lazy). Two small boxes (the
    // grab-able squares) + two thin lines; positions are set every
    // refresh. Always-on-top (depthTest off) like the Task-16
    // overlay so a handle is never hidden behind the splat.
    function _tanBuild() {{
      if (_tanGroup) return;
      _tanGroup = new THREE.Group();
      _tanGroup.name = 'editor-tangent-handles';
      const _mkBox = (col) => {{
        const g = new THREE.BoxGeometry(1, 1, 1);
        const m = new THREE.MeshBasicMaterial({{
          color: col, transparent: true, opacity: 0.95 }});
        m.depthTest = false; m.depthWrite = false;
        const mesh = new THREE.Mesh(g, m);
        mesh.renderOrder = 13;   // above frusta (11)
        return mesh;
      }};
      const _mkLine = (col) => {{
        const g = new THREE.BufferGeometry();
        g.setAttribute('position',
          new THREE.BufferAttribute(new Float32Array(6), 3));
        const m = new THREE.LineBasicMaterial({{
          color: col, transparent: true,
          opacity: _TAN_LINE_OPACITY }});
        m.depthTest = false; m.depthWrite = false;
        const ln = new THREE.Line(g, m);
        ln.renderOrder = 12;
        return ln;
      }};
      _tanOutBox = _mkBox(_TAN_COL_OUT);
      _tanInBox = _mkBox(_TAN_COL_IN);
      _tanOutLine = _mkLine(_TAN_COL_OUT);
      _tanInLine = _mkLine(_TAN_COL_IN);
      _tanGroup.add(_tanOutLine);
      _tanGroup.add(_tanInLine);
      _tanGroup.add(_tanOutBox);
      _tanGroup.add(_tanInBox);
      if (!_tanOutProxy) {{
        _tanOutProxy = new THREE.Object3D();
        _tanOutProxy.name = 'editor-tan-out-proxy';
      }}
      if (!_tanInProxy) {{
        _tanInProxy = new THREE.Object3D();
        _tanInProxy.name = 'editor-tan-in-proxy';
      }}
    }}

    // Position the boxes/lines from the selected keyframe's tangents
    // (skip the side currently being dragged so the live TC pose is
    // authoritative for that frame). The proxies are parked at the
    // handle world points so the dedicated TC sits exactly on the
    // square. Box size + handle distance are scene-relative.
    function _tanRefresh() {{
      if (!_tanGroup || _gzSelKf < 0) return;
      const kf = _gzSelKfObj();
      const v = _tanVecs();
      if (!kf || !v) return;
      const fr = _tanFrac();
      const bs = _tanBoxSize();
      const px = kf.pos[0], py = kf.pos[1], pz = kf.pos[2];
      const outW = [px + v.outv[0] * fr, py + v.outv[1] * fr,
        pz + v.outv[2] * fr];
      const inW = [px - v.inv[0] * fr, py - v.inv[1] * fr,
        pz - v.inv[2] * fr];
      if (_tanActiveSide !== 'out') {{
        _tanOutBox.position.set(outW[0], outW[1], outW[2]);
        _tanOutBox.scale.setScalar(bs);
        if (_tanOutProxy) {{
          _tanOutProxy.position.set(outW[0], outW[1], outW[2]);
          _tanOutProxy.updateMatrixWorld(true);
        }}
      }} else if (_tanOutProxy) {{
        _tanOutBox.position.copy(_tanOutProxy.position);
        _tanOutBox.scale.setScalar(bs);
      }}
      if (_tanActiveSide !== 'in') {{
        _tanInBox.position.set(inW[0], inW[1], inW[2]);
        _tanInBox.scale.setScalar(bs);
        if (_tanInProxy) {{
          _tanInProxy.position.set(inW[0], inW[1], inW[2]);
          _tanInProxy.updateMatrixWorld(true);
        }}
      }} else if (_tanInProxy) {{
        _tanInBox.position.copy(_tanInProxy.position);
        _tanInBox.scale.setScalar(bs);
      }}
      const _setLine = (ln, bx) => {{
        const a = ln.geometry.getAttribute('position');
        a.setXYZ(0, px, py, pz);
        a.setXYZ(1, bx.position.x, bx.position.y, bx.position.z);
        a.needsUpdate = true;
      }};
      _setLine(_tanOutLine, _tanOutBox);
      _setLine(_tanInLine, _tanInBox);
    }}

    // Write a dragged handle proxy's world position back to the
    // selected keyframe's tangent (the inverse of _tanRefresh's
    // forward map) + PIN kf.interp='bezier' (so the spline's
    // KF_BEZIER branch consumes it) + rebuild the trajectory/
    // timeline (the spec's "drag -> curve reshapes"). Also seeds the
    // OTHER side from its current effective value so converting via a
    // drag does not snap the unedited side.
    const _TAN_R = (x) => Math.round(x * 1e5) / 1e5;
    function _tanWriteFromProxy(side) {{
      const kf = _gzSelKfObj();
      if (!kf || !kf.pos || kf.pos.length !== 3) return;
      const fr = _tanFrac() || 1;
      const before = _tanVecs();
      const proxy = side === 'out' ? _tanOutProxy : _tanInProxy;
      if (!proxy) return;
      const dx = proxy.position.x - kf.pos[0];
      const dy = proxy.position.y - kf.pos[1];
      const dz = proxy.position.z - kf.pos[2];
      // OUT handle is on the +tan side, IN handle on the -tan side.
      const s = side === 'out' ? 1 : -1;
      const tan = [_TAN_R(s * dx / fr), _TAN_R(s * dy / fr),
        _TAN_R(s * dz / fr)];
      if (side === 'out') {{
        kf.out_tan = tan;
        if (!(Array.isArray(kf.in_tan) && kf.in_tan.length === 3) &&
            before) kf.in_tan = before.inv.map(_TAN_R);
      }} else {{
        kf.in_tan = tan;
        if (!(Array.isArray(kf.out_tan) && kf.out_tan.length === 3) &&
            before) kf.out_tan = before.outv.map(_TAN_R);
      }}
      kf.interp = 'bezier';   // explicit tangents only bite as bezier
      _gzAfterEdit();
      _tanRefresh();
    }}

    // Lazily import + construct the DEDICATED handle TransformControls
    // (translate-only). SAME dynamic-import-through-the-existing-
    // importmap pattern as the keyframe gizmo (no new importmap
    // entry; region-interior). A REAL mouse drives it -- exactly the
    // proven pattern; synthetic events do not.
    function _tanEnsureCtl() {{
      if (_tanCtl) return Promise.resolve(_tanCtl);
      if (!_tanCtlImport) {{
        _tanCtlImport = import(
          'three/addons/controls/TransformControls.js'
        ).then((mod) => {{
          const TC = mod && (mod.TransformControls ||
            (mod.default && mod.default.TransformControls) ||
            mod.default);
          if (!TC) return null;
          const ctl = new TC(camera, renderer.domElement);
          ctl.setSize(0.62);
          ctl.setMode('translate');     // tangents are positional
          ctl.setSpace('world');
          const helper = (typeof ctl.getHelper === 'function')
            ? ctl.getHelper() : ctl;
          _tanCtlHelper = helper;
          ctl.addEventListener('dragging-changed', (ev) => {{
            _tanDragging = !!ev.value;
            if (_tanDragging) {{
              // A real handle grab is an authoring gesture: stop any
              // auto-tour FIRST (idempotent) so the render loop does
              // not re-sample the OLD spline and stomp the edit.
              _gzStopTour();
              InteractionManager.requestPointer('tool');
              controls.enabled = false;
            }} else {{
              _tanActiveSide = null;
              InteractionManager.releasePointer('tool');
              if (!InteractionManager.isCameraOwned()) {{
                controls.enabled = true;
              }}
            }}
          }});
          ctl.addEventListener('objectChange', () => {{
            // The proxy currently attached IS the active side.
            const side = (ctl.object === _tanOutProxy) ? 'out'
              : (ctl.object === _tanInProxy) ? 'in' : _tanActiveSide;
            if (side) {{ _tanActiveSide = side; _tanWriteFromProxy(side); }}
          }});
          _tanCtl = ctl;
          if (helper && helper.parent !== scene) scene.add(helper);
          return ctl;
        }}).catch(() => null);
      }}
      return _tanCtlImport;
    }}

    // Show the handles for the selected keyframe (only when it is in
    // bezier mode). Builds geometry + proxies lazily, parks them on
    // the current tangents, makes the group visible. The dedicated TC
    // is imported but NOT attached until the user actually grabs a
    // handle (attach-on-pick, like the keyframe gizmo).
    function _tanShow() {{
      if (_gzSelKf < 0 || !_tanIsBezierSel()) {{ _tanHide(); return; }}
      _tanBuild();
      if (_tanGroup.parent !== scene) scene.add(_tanGroup);
      _tanGroup.visible = true;
      _tanRefresh();
      _tanEnsureCtl();
    }}

    // Hide + detach the handles (deselect / non-bezier / Escape).
    // Removes the group + proxies from the scene (no leak); the TC
    // instance is memoised for re-attach (its designed lifecycle).
    function _tanHide() {{
      _tanActiveSide = null;
      if (_tanCtl) {{ try {{ _tanCtl.detach(); }} catch (e) {{}} }}
      if (_tanGroup && _tanGroup.parent) {{
        _tanGroup.parent.remove(_tanGroup);
      }}
      if (_tanGroup) _tanGroup.visible = false;
      if (_tanOutProxy && _tanOutProxy.parent) {{
        _tanOutProxy.parent.remove(_tanOutProxy);
      }}
      if (_tanInProxy && _tanInProxy.parent) {{
        _tanInProxy.parent.remove(_tanInProxy);
      }}
    }}

    // Convert the selected keyframe to explicit-tangent (bezier)
    // mode: set kf.interp='bezier' and SEED kf.in_tan/kf.out_tan from
    // the `automatic` derived defaults so the curve does NOT jump
    // (the handles appear exactly ON the existing spline). Idempotent
    // if already bezier with tangents. Then show the handles.
    function _tanEnableBezier() {{
      const kf = _gzSelKfObj();
      if (!kf) return false;
      _gzStopTour();
      if (kf.interp !== 'bezier' ||
          !(Array.isArray(kf.in_tan) && kf.in_tan.length === 3) ||
          !(Array.isArray(kf.out_tan) && kf.out_tan.length === 3)) {{
        const v = _tanVecs();   // derived defaults when absent
        if (v) {{
          if (!(Array.isArray(kf.in_tan) && kf.in_tan.length === 3)) {{
            kf.in_tan = v.inv.map(_TAN_R);
          }}
          if (!(Array.isArray(kf.out_tan) && kf.out_tan.length === 3)) {{
            kf.out_tan = v.outv.map(_TAN_R);
          }}
        }}
        kf.interp = 'bezier';
        _gzAfterEdit();
      }}
      _tanShow();
      return _tanIsBezierSel();
    }}

    // Attach the dedicated handle-TC to a handle proxy (the pointer
    // pick resolved which side). Parks the proxy on the current
    // handle world point first so the gizmo lands on the square.
    function _tanAttachSide(side) {{
      if (!_tanIsBezierSel()) return;
      _tanShow();
      _tanActiveSide = side;
      const proxy = side === 'out' ? _tanOutProxy : _tanInProxy;
      const box = side === 'out' ? _tanOutBox : _tanInBox;
      if (!proxy || !box) return;
      proxy.position.copy(box.position);
      proxy.updateMatrixWorld(true);
      if (proxy.parent !== scene) scene.add(proxy);
      _tanEnsureCtl().then((ctl) => {{
        if (!ctl || _tanActiveSide !== side) return;
        ctl.attach(proxy);
      }});
    }}

    // Is a real pointerdown over a HANDLE-gizmo axis? SAME capture-
    // phase contract the keyframe gizmo uses: refresh the handle TC's
    // hover axis from THIS pointer and report whether a handle is
    // under it -- when true the caller MUST yield the event to the
    // handle TC untouched (capture-phase stopPropagation would starve
    // its bubble-phase pointerDown and make a real drag impossible).
    const _TAN_NDC = new THREE.Vector2();
    function _tanPointerOnGizmo(clientX, clientY) {{
      if (!_tanCtl || _tanCtl.object == null) return false;
      if (_tanCtl.dragging) return true;
      const rect = renderer.domElement.getBoundingClientRect();
      _TAN_NDC.x = ((clientX - rect.left) / rect.width) * 2 - 1;
      _TAN_NDC.y = -((clientY - rect.top) / rect.height) * 2 + 1;
      try {{ _tanCtl.pointerHover(_TAN_NDC); }}
      catch (e) {{ return false; }}
      return _tanCtl.axis !== null && _tanCtl.axis !== undefined;
    }}

    // Raycast-pick a handle SQUARE at client px -> 'in' | 'out' |
    // null. Uses the EXISTING scene _raycaster (single source of
    // truth). Boxes are small so a generous nearest-hit wins.
    function _tanPickBox(clientX, clientY) {{
      if (!_tanGroup || !_tanGroup.visible ||
          !_tanIsBezierSel()) return null;
      const rect = renderer.domElement.getBoundingClientRect();
      _ndc.x = ((clientX - rect.left) / rect.width) * 2 - 1;
      _ndc.y = -((clientY - rect.top) / rect.height) * 2 + 1;
      _raycaster.setFromCamera(_ndc, camera);
      let best = null, bestD = Infinity;
      if (_tanOutBox) {{
        const h = _raycaster.intersectObject(_tanOutBox, false);
        if (h.length && h[0].distance < bestD) {{
          bestD = h[0].distance; best = 'out';
        }}
      }}
      if (_tanInBox) {{
        const h = _raycaster.intersectObject(_tanInBox, false);
        if (h.length && h[0].distance < bestD) {{
          bestD = h[0].distance; best = 'in';
        }}
      }}
      return best;
    }}

    // ---- Pointer pick: a left click on a trajectory frustum
    //      selects that keyframe (the Task-16 _trajFrusta meshes
    //      are the only pickables here). Uses the EXISTING scene
    //      _raycaster (single source of truth). A click that hits
    //      no frustum AND is not on the gizmo deselects. We ignore
    //      the click while the gizmo is being dragged (the gizmo
    //      owns the pointer then) and while OrbitControls is mid-
    //      gesture is naturally fine (a frustum hit is a discrete
    //      click, not a drag).
    function _gzPickFrustum(clientX, clientY) {{
      if (!_trajFrusta.length) return -1;
      const rect = renderer.domElement.getBoundingClientRect();
      _ndc.x = ((clientX - rect.left) / rect.width) * 2 - 1;
      _ndc.y = -((clientY - rect.top) / rect.height) * 2 + 1;
      _raycaster.setFromCamera(_ndc, camera);
      // LineSegments need a forgiving threshold; the frusta are
      // small wireframes. Pick the nearest hit frustum's kfIndex.
      const prevT = _raycaster.params.Line
        ? _raycaster.params.Line.threshold : 1;
      if (_raycaster.params.Line) {{
        _raycaster.params.Line.threshold =
          Math.max(prevT, _trajFrHalf * 0.6);
      }}
      let best = -1, bestDist = Infinity;
      for (const f of _trajFrusta) {{
        if (!f.mesh) continue;
        const hits = _raycaster.intersectObject(f.mesh, false);
        if (hits.length && hits[0].distance < bestDist) {{
          bestDist = hits[0].distance;
          best = f.kfIndex;
        }}
      }}
      if (_raycaster.params.Line) {{
        _raycaster.params.Line.threshold = prevT;
      }}
      return best;
    }}
    // Is the pointerdown (clientX/Y) over a TransformControls gizmo
    // HANDLE? We run in CAPTURE phase, BEFORE TransformControls' own
    // bubble-phase pointerdown listener; if we stopPropagation() a
    // pointerdown that landed on a gizmo axis, TC's pointerDown()
    // never fires and the gizmo can NEVER be dragged with a real
    // mouse (it only starts a drag when this.axis !== null, and axis
    // is set by its pointerHover raycast). So: refresh the control's
    // hover axis from THIS pointer (the SAME NDC->raycast TC's own
    // pointerHover does) and report whether a handle is under it.
    // When true the caller MUST yield the event to TC untouched.
    const _GZ_NDC = new THREE.Vector2();
    function _gzPointerOnGizmo(clientX, clientY) {{
      if (!_gzCtl || _gzCtl.object !== _gzProxy || _gzSelKf < 0) {{
        return false;
      }}
      if (_gzCtl.dragging) return true;   // already grabbed
      const rect = renderer.domElement.getBoundingClientRect();
      _GZ_NDC.x = ((clientX - rect.left) / rect.width) * 2 - 1;
      _GZ_NDC.y = -((clientY - rect.top) / rect.height) * 2 + 1;
      try {{
        // Updates _gzCtl.axis (null = not over a handle). Identical
        // to the raycast TC.pointerHover runs on its own pointermove
        // -- we just trigger it deterministically for THIS down.
        _gzCtl.pointerHover(_GZ_NDC);
      }} catch (e) {{ return false; }}
      return _gzCtl.axis !== null && _gzCtl.axis !== undefined;
    }}
    function _gzOnCanvasDown(ev) {{
      if (!ModeManager.is('author')) return;
      if (ev.button !== undefined && ev.button !== 0) return;
      if (_gzDragging || _tanDragging) return;   // a gizmo owns it
      // 1. The TANGENT-handle gizmo is visually TOPMOST -- if a real
      //    pointerdown is over its axis, yield it untouched (its own
      //    bubble-phase pointerDown drives the drag; capture-phase
      //    stopPropagation here would starve it -> "the handle would
      //    not move with a real mouse"). SAME contract as the
      //    keyframe gizmo below.
      if (_tanPointerOnGizmo(ev.clientX, ev.clientY)) return;
      // 2. If the keyframe gizmo's own axes were hit, TransformControls
      //    handles it (it has its own bubble-phase pointer listeners).
      //    We MUST NOT pick a frustum NOR stopPropagation() here --
      //    doing so starves TC's pointerDown() and the gizmo becomes
      //    undraggable by a real mouse (the long-standing reason a
      //    real handle drag "did not move the keyframe" -- only the
      //    programmatic test API ever moved it). Yield it untouched.
      if (_gzPointerOnGizmo(ev.clientX, ev.clientY)) return;
      // 3. A click on a tangent-handle SQUARE (for the selected
      //    bezier keyframe) grabs that handle: attach the dedicated
      //    handle-TC so the NEXT mouse move (a real trusted drag)
      //    reshapes the curve. Wins over the frustum pick (the
      //    handles belong to the already-selected keyframe and sit
      //    on top of it).
      const side = _tanPickBox(ev.clientX, ev.clientY);
      if (side) {{
        _tanAttachSide(side);
        ev.stopPropagation();
        return;
      }}
      // 4. Otherwise: a click on a trajectory frustum selects that
      //    keyframe (and shows its tangent handles if it is bezier).
      const idx = _gzPickFrustum(ev.clientX, ev.clientY);
      if (idx >= 0) {{
        _gzAttach(idx);
        // A frustum pick is an editing gesture, not an orbit: stop
        // the event so OrbitControls does not also start a drag
        // from the same pointerdown.
        ev.stopPropagation();
      }}
    }}
    // Capture phase so we see the pointerdown before OrbitControls'
    // own canvas listener (it is attached without capture); only
    // when we actually consume a frustum hit do we stopPropagation.
    // A pointerdown on a gizmo handle is yielded untouched (above)
    // so TransformControls' own bubble-phase listener drives the
    // drag -- capture-phase stopPropagation would otherwise kill it.
    renderer.domElement.addEventListener(
      'pointerdown', _gzOnCanvasDown, true);

    // ---- The 5-type interp popover (V). A segmented control over
    //      the EXISTING _VALID_INTERP set (auto_clamped / automatic
    //      / linear / bezier / stepped -- the real constant, not a
    //      hardcoded list). Selecting writes the SELECTED keyframe's
    //      kf.interp and rebuilds (the spline already honours
    //      per-keyframe interp via _kfMeta). Built lazily, injected
    //      into the Task-12 #author-root (CSS-gated to authormode --
    //      no new CSS region, inline-styled like #sp-hud / the
    //      Task-16 toggle), removed on close (no leak).
    const _GZ_INTERPS = Object.keys(_VALID_INTERP);
    function _gzClosePopover() {{
      if (_gzPopEl && _gzPopEl.parentNode) {{
        _gzPopEl.parentNode.removeChild(_gzPopEl);
      }}
      _gzPopEl = null;
    }}
    function _gzSelInterpVal() {{
      const kf = _gzSelKfObj();
      return (kf && kf.interp) ? kf.interp : null;
    }}
    function _gzSetInterp(val) {{
      const kf = _gzSelKfObj();
      if (!kf) return false;
      if (val && _VALID_INTERP[val]) kf.interp = val;
      // Picking `bezier` from the interp popover is the same
      // intent as the tangents button: seed the derived defaults
      // (no curve jump) + reveal the grab-able handles. Any other
      // mode hides them (explicit tangents only bite as bezier).
      if (kf.interp === 'bezier') {{
        _tanEnableBezier();
      }} else {{
        _gzAfterEdit();
        _tanHide();
      }}
      return kf.interp === val;
    }}
    function _gzOpenPopover() {{
      if (_gzSelKf < 0) return;       // need a selected keyframe
      _gzStopTour();
      _gzClosePopover();
      const root = document.getElementById('author-root');
      if (!root) return;
      const kf = _gzSelKfObj();
      const cur = (kf && typeof kf.interp === 'string' &&
        _VALID_INTERP[kf.interp]) ? kf.interp : '';
      const box = document.createElement('div');
      box.id = 'editor-interp-pop';
      box.style.cssText =
        'position:absolute;top:54px;left:12px;z-index:51;' +
        'display:flex;gap:4px;align-items:center;flex-wrap:wrap;' +
        'max-width:360px;padding:8px 10px;border-radius:8px;' +
        'background:rgba(20,20,20,0.86);' +
        '-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);' +
        'font:12px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;' +
        'color:#eee;user-select:none;';
      const lab = document.createElement('span');
      lab.textContent = 'interp:';
      lab.style.cssText = 'opacity:.7;margin-right:4px;';
      box.appendChild(lab);
      _GZ_INTERPS.forEach((nm) => {{
        const b = document.createElement('button');
        b.type = 'button';
        b.textContent = nm;
        b.setAttribute('data-interp', nm);
        b.style.cssText =
          'background:' + (nm === cur
            ? 'rgba(53,224,255,0.34)' : 'rgba(255,255,255,0.10)') +
          ';color:#eee;border:0;border-radius:5px;' +
          'padding:4px 8px;cursor:pointer;font:12px monospace;' +
          'line-height:1;';
        b.addEventListener('click', () => {{
          _gzSetInterp(nm);
          _gzClosePopover();
        }});
        box.appendChild(b);
      }});
      root.appendChild(box);
      _gzPopEl = box;
    }}

    // ---- Record(K): append a keyframe = the LIVE camera pose +
    //      the REAL elapsed playhead t. The playhead is taken from
    //      _trajPlayhead() (the SAME single-source-of-truth clock
    //      the Task-16 overlay + Task-17 timeline read: the live
    //      _player/_t0 clock while a tour plays, else the
    //      #path-scrub position) -- the in-viewer analogue of the
    //      Task-5 "recording uses real elapsed time" fix, NOT a
    //      reinvented timer. The new keyframe is inserted into the
    //      active path's keyframes[] (buildPlayer sorts by t, so a
    //      record at any playhead lands correctly) and the
    //      trajectory rebuilds. Recording also stops the auto-tour
    //      first (explicit interaction stop) so the captured pose is
    //      the user's, not a tour frame.
    const _GZ_R = (x) => Math.round(x * 1e5) / 1e5;
    function _gzRecordKeyframe() {{
      const p = _gzActivePath();
      if (!p) return null;
      if (!Array.isArray(p.keyframes)) p.keyframes = [];
      // Read the real elapsed playhead BEFORE stopping the tour
      // (stopPath() clears _player; we want the elapsed time the
      // user is parked at -- the same value _trajPlayhead returns).
      let t = 0;
      try {{
        const ph = buildPlayer(p);
        const v = ph ? _trajPlayhead(ph) : null;
        if (typeof v === 'number' && isFinite(v)) t = Math.max(0, v);
      }} catch (e) {{}}
      _gzStopTour();
      const kf = {{
        t: _GZ_R(t),
        pos: [_GZ_R(camera.position.x), _GZ_R(camera.position.y),
          _GZ_R(camera.position.z)],
        quat: [_GZ_R(camera.quaternion.x), _GZ_R(camera.quaternion.y),
          _GZ_R(camera.quaternion.z), _GZ_R(camera.quaternion.w)],
        fov: _GZ_R(camera.fov),
      }};
      p.keyframes.push(kf);
      _gzAfterEdit();
      return kf;
    }}

    // ---- Save / Emit. SAVE_MODE=="cli" (decision-A DEFAULT):
    //      emit the SPCP1 token + the `splatpipe set-camera-path
    //      <token>` command in an on-screen textarea + clipboard,
    //      MIRRORING the existing SPV1 "Set start view" relay UI
    //      (same overlay/card/textarea/copy pattern, same trust
    //      model -- no client secret). SAVE_MODE=="http" (opt-in):
    //      POST the camera-scope patch JSON to SAVE_ENDPOINT with
    //      Authorization: Bearer <secret> where <secret> is read
    //      ONLY from the author URL fragment (#author=<secret>) --
    //      never baked, never in viewer-config.json. Returns the
    //      token (cli) or a Promise (http) so the harness can
    //      deterministically assert both paths.
    function _gzEsc(s) {{
      return String(s).replace(/[&<>]/g, (c) =>
        ({{ '&': '&amp;', '<': '&lt;', '>': '&gt;' }}[c]));
    }}
    function _gzAuthorSecret() {{
      // The http-mode bearer lives ONLY in the URL fragment
      // (#author=<secret>), never baked / in config. Parse it
      // leniently (#author=... possibly among &-joined fields).
      try {{
        const h = (location.hash || '').replace(/^#/, '');
        for (const part of h.split('&')) {{
          const eq = part.indexOf('=');
          if (eq > 0 && part.slice(0, eq) === 'author') {{
            return decodeURIComponent(part.slice(eq + 1));
          }}
        }}
      }} catch (e) {{}}
      return '';
    }}
    let _gzLastToken = '';
    function _gzShowTokenCard(token) {{
      // Mirror the SPV1 relay overlay/card EXACTLY (same structure,
      // wording shape, textarea + copy-again + done).
      const old = document.getElementById('gz-save-overlay');
      if (old) old.remove();
      const cmd = 'splatpipe set-camera-path ' + token;
      const ov = document.createElement('div');
      ov.id = 'gz-save-overlay';
      ov.style.cssText =
        'position:fixed;inset:0;z-index:9999;display:flex;' +
        'align-items:center;justify-content:center;' +
        'background:rgba(0,0,0,.55);font:14px system-ui,sans-serif;';
      const card = document.createElement('div');
      card.style.cssText =
        'background:#1f1f24;color:#eee;max-width:560px;width:90%;' +
        'padding:20px 22px;border-radius:12px;' +
        'box-shadow:0 8px 40px rgba(0,0,0,.5);';
      let copied = false;
      try {{
        if (navigator.clipboard && navigator.clipboard.writeText) {{
          navigator.clipboard.writeText(token);
          copied = true;
        }}
      }} catch (e) {{}}
      card.innerHTML =
        '<div style="font-weight:600;font-size:16px;margin-bottom:6px;">' +
        (copied ? 'Copied to clipboard \\u2713'
                : 'Camera-path token') + '</div>' +
        '<div style="opacity:.75;margin-bottom:10px;">Send this ' +
        'token to Claude on Telegram, or run the command below, to ' +
        'save these camera paths for <b>' + _gzEsc(_gzProjName) +
        '</b> for everyone:</div>' +
        '<textarea id="gz-tok" readonly style="width:100%;height:84px;' +
        'box-sizing:border-box;background:#111;color:#9fd;' +
        'border:1px solid #333;border-radius:8px;padding:8px;' +
        'font:12px monospace;resize:none;"></textarea>' +
        '<div style="opacity:.6;margin:8px 0 4px;">CLI:</div>' +
        '<textarea id="gz-cmd" readonly style="width:100%;height:44px;' +
        'box-sizing:border-box;background:#111;color:#9fd;' +
        'border:1px solid #333;border-radius:8px;padding:8px;' +
        'font:12px monospace;resize:none;"></textarea>' +
        '<div style="display:flex;gap:10px;justify-content:flex-end;' +
        'margin-top:14px;">' +
        '<button id="gz-copy" class="quality-btn">Copy again</button>' +
        '<button id="gz-done" class="quality-btn" ' +
        'style="background:#2d6cdf;color:#fff;">Done</button></div>';
      ov.appendChild(card);
      document.body.appendChild(ov);
      const ta = card.querySelector('#gz-tok');
      ta.value = token;
      card.querySelector('#gz-cmd').value = cmd;
      ta.focus(); ta.select();
      ov.addEventListener('click', (e) => {{
        if (e.target === ov) ov.remove();
      }});
      card.querySelector('#gz-done').addEventListener('click', () => {{
        ov.remove();
      }});
      card.querySelector('#gz-copy').addEventListener('click', () => {{
        ta.focus(); ta.select();
        try {{
          if (navigator.clipboard) navigator.clipboard.writeText(token);
        }} catch (e) {{}}
        try {{ document.execCommand('copy'); }} catch (e) {{}}
      }});
    }}
    // The CLI-default Save: build the payload from the AUTHORED
    // in-memory state, encode the SPCP1 token (byte-identical port),
    // mirror the SPV1 relay UI. Returns the token string.
    function _gzSaveCli() {{
      const payload = _buildSpcpPayload();
      const token = _encodeSpcp(_gzSlug, payload);
      _gzLastToken = token;
      _gzShowTokenCard(token);
      return token;
    }}
    // The opt-in http Save: POST {{slug, patch}} (the allow-listed
    // camera-scope patch keys ONLY -- NEVER primary_asset)
    // to SAVE_ENDPOINT with Bearer <fragment secret>. The body is
    // the SAME allow-listed patch (NEVER primary_asset) -- mirrors
    // the Contract-C {{slug, patch}} body shape. Returns the fetch
    // Promise so the harness can assert the call (no real server).
    function _gzSaveHttp() {{
      const patch = _buildPatch();
      const secret = _gzAuthorSecret();
      const body = JSON.stringify({{ slug: _gzSlug, patch: patch }});
      const headers = {{ 'Content-Type': 'application/json' }};
      if (secret) headers['Authorization'] = 'Bearer ' + secret;
      return fetch(SAVE_ENDPOINT, {{
        method: 'POST', headers: headers, body: body,
      }});
    }}
    function _gzSave() {{
      if (SAVE_MODE === 'http' && SAVE_ENDPOINT) {{
        return _gzSaveHttp();
      }}
      return _gzSaveCli();
    }}

    // ---- The author HUD button cluster (Save + a hint). Injected
    //      into the Task-12 #author-root (CSS-gated to authormode;
    //      inline-styled like #sp-hud / the Task-16 toggle -- no new
    //      CSS region). The gizmo space/mode + interp + record are
    //      keyboard-driven (the spec's R/T/V/K); the Save button is
    //      the explicit persist action.
    {{
      const root = document.getElementById('author-root');
      if (root) {{
        const bar = document.createElement('div');
        bar.id = 'editor-gizmo-bar';
        bar.style.cssText =
          'position:absolute;top:12px;left:160px;z-index:50;' +
          'display:flex;gap:6px;align-items:center;' +
          'padding:6px 9px;border-radius:7px;' +
          'background:rgba(20,20,20,0.72);' +
          '-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);' +
          'font:12px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;' +
          'color:#eee;user-select:none;';
        const _mkBtn = (txt, title, id) => {{
          const b = document.createElement('button');
          b.type = 'button'; b.textContent = txt;
          b.title = title || ''; if (id) b.id = id;
          b.style.cssText =
            'background:rgba(255,255,255,0.10);color:#eee;border:0;' +
            'border-radius:5px;padding:4px 9px;cursor:pointer;' +
            'font:12px monospace;line-height:1;';
          return b;
        }};
        const recBtn = _mkBtn('\\u25CF Rec (K)',
          'Record a keyframe at the playhead from the live camera',
          'editor-rec-btn');
        const interpBtn = _mkBtn('interp (V)',
          'Set the selected keyframe interpolation', 'editor-interp-btn');
        const tanBtn = _mkBtn('tangents (B)',
          'Show grab-able bezier in/out tangent handles on the ' +
          'selected keyframe (drag them to shape the curve)',
          'editor-tan-btn');
        const saveBtn = _mkBtn('Save',
          'Save camera paths (cli: emit SPCP1 token; http: POST)',
          'editor-save-btn');
        recBtn.addEventListener('click', () => {{ _gzRecordKeyframe(); }});
        interpBtn.addEventListener('click', () => {{ _gzOpenPopover(); }});
        tanBtn.addEventListener('click', () => {{ _tanEnableBezier(); }});
        saveBtn.addEventListener('click', () => {{ _gzSave(); }});
        bar.appendChild(recBtn);
        bar.appendChild(interpBtn);
        bar.appendChild(tanBtn);
        bar.appendChild(saveBtn);
        root.appendChild(bar);
      }}
    }}

    // ---- Keyboard: R/T (translate/rotate), SPACE (World<->Screen),
    //      V (interp popover), B (bezier tangent handles), K
    //      (record). Author-mode only; ignored while typing in an
    //      input/textarea (the Save card's textareas) so copying the
    //      token does not trigger Record.
    window.addEventListener('keydown', (ev) => {{
      if (!ModeManager.is('author')) return;
      const ae = document.activeElement;
      if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' ||
          ae.tagName === 'SELECT')) return;
      const k = ev.key;
      if (k === 'r' || k === 'R') {{
        _gzMode = 'rotate'; _gzApplySpace();
      }} else if (k === 't' || k === 'T') {{
        _gzMode = 'translate'; _gzApplySpace();
      }} else if (k === ' ' || k === 'Spacebar' || ev.code === 'Space') {{
        _gzScreen = !_gzScreen; _gzApplySpace();
        ev.preventDefault();    // stop the page scrolling on Space
      }} else if (k === 'v' || k === 'V') {{
        if (_gzPopEl) _gzClosePopover(); else _gzOpenPopover();
      }} else if (k === 'b' || k === 'B') {{
        // Reveal (or, if already shown for a non-bezier key,
        // convert + reveal) the grab-able bezier tangent handles
        // on the selected keyframe. No-op without a selection.
        _tanEnableBezier();
      }} else if (k === 'k' || k === 'K') {{
        _gzRecordKeyframe();
      }} else if (k === 'Escape') {{
        _gzClosePopover();
        _tanHide();
        _gzDetach();
      }}
    }});

    // ---- TEST-ONLY surface extension (mirror window.__clip /
    //      __transport / the Task-16/17 window.__editor: getters +
    //      deterministic hooks; NO production reader; inert without
    //      the harness). Extends the EXISTING window.__editor object
    //      (created by the Task-16 block, extended by Task-17) so
    //      the harness reads ONE surface. Every hook drives the
    //      REAL code path a user action / keypress would (the same
    //      convention as __editor.scrubTo / tlDragKf).
    try {{
      if (window.__editor) {{
        const _gzApi = {{
          // ---- read state ----
          get gzMode() {{ return _gzMode; }},
          get gzSpace() {{ return _gzScreen ? 'screen' : 'world'; }},
          get gzSelKf() {{ return _gzSelKf; }},
          get gzAttached() {{
            return !!(_gzCtl && _gzCtl.object === _gzProxy &&
              _gzSelKf >= 0);
          }},
          get gzProxyInScene() {{
            return !!(_gzProxy && _gzProxy.parent === scene);
          }},
          get gzHelperInScene() {{
            return !!(_gzCtlHelper && _gzCtlHelper.parent === scene);
          }},
          get gzControlSpace() {{
            return _gzCtl ? _gzCtl.space : null;
          }},
          get gzControlMode() {{
            return _gzCtl ? _gzCtl.mode : null;
          }},
          get gzPopoverOpen() {{ return !!_gzPopEl; }},
          get gzInterpOptions() {{ return _GZ_INTERPS.slice(); }},
          get gzSelInterp() {{
            const kf = _gzSelKfObj();
            return (kf && kf.interp) ? kf.interp : null;
          }},
          get gzSaveMode() {{
            try {{ return SAVE_MODE; }} catch (e) {{ return '?'; }}
          }},
          get gzSlug() {{ return _gzSlug; }},
          get gzLastToken() {{ return _gzLastToken; }},
          get gzFrustumCount() {{ return _trajFrusta.length; }},
          // The selected keyframe's CURRENT stored pose (the SAME
          // in-memory object the player + overlay read) so the
          // harness can assert a gizmo drag changed kf.pos/kf.quat.
          get gzSelKfPose() {{
            const kf = _gzSelKfObj();
            if (!kf) return null;
            return {{
              t: kf.t,
              pos: (kf.pos || []).slice(),
              quat: (kf.quat || []).slice(),
              fov: kf.fov,
              interp: kf.interp || null,
            }};
          }},
          // The active path's keyframe times (array order) -- so the
          // harness can assert Record APPENDED a keyframe at the
          // real-elapsed playhead t.
          get gzKfTimes() {{
            const p = _gzActivePath();
            return (p && p.keyframes)
              ? p.keyframes.map(k => (k.t || 0)) : [];
          }},
          get gzKfCount() {{
            const p = _gzActivePath();
            return (p && p.keyframes) ? p.keyframes.length : 0;
          }},
          // The Task-16 overlay signature -- so the harness can
          // assert a gizmo/record/interp edit triggered the overlay
          // rebuild (the sig CHANGED) without a save/network.
          get gzOverlaySig() {{
            try {{
              const p = _gzActivePath();
              return (typeof _trajKfSig === 'function')
                ? _trajKfSig(p) : '';
            }} catch (e) {{ return ''; }}
          }},
          // ---- deterministic hooks (drive the REAL handlers) ----
          // Select a keyframe by index == clicking its frustum
          // (drives the SAME _gzAttach the pointer pick calls).
          // Returns a Promise resolving once the (lazily imported)
          // TransformControls has attached, so the harness can await.
          gzSelect(idx) {{
            _gzAttach(idx);
            return _gzEnsureControl().then(() => ({{
              attached: !!(_gzCtl && _gzCtl.object === _gzProxy),
              sel: _gzSelKf,
            }}));
          }},
          // Raycast-pick a frustum at NDC (-1..1) -> returns the kf
          // index a click there would select (drives the REAL
          // _gzPickFrustum off the live trajectory geometry; the
          // harness converts a frustum's world pos to NDC itself).
          gzPickAtNdc(ndcx, ndcy) {{
            const rect = renderer.domElement.getBoundingClientRect();
            const cx = rect.left + (ndcx + 1) * 0.5 * rect.width;
            const cy = rect.top + (1 - ndcy) * 0.5 * rect.height;
            return _gzPickFrustum(cx, cy);
          }},
          // TEST-ONLY: would a real pointerdown at these CLIENT px
          // yield the event to TransformControls (pointer over a
          // gizmo handle => the capture handler must NOT pick a
          // frustum / stopPropagation, so TC's own bubble-phase
          // pointerDown drives the drag)? Drives the EXACT
          // _gzPointerOnGizmo the real `_gzOnCanvasDown` calls -- so
          // the harness can assert the starvation bug is fixed
          // WITHOUT performing the drag through the API. Also
          // returns the resolved TC axis for diagnostics.
          gzPointerOnGizmoAt(clientX, clientY) {{
            const on = _gzPointerOnGizmo(clientX, clientY);
            return {{ onGizmo: !!on,
              axis: _gzCtl ? (_gzCtl.axis || null) : null,
              dragging: _gzCtl ? !!_gzCtl.dragging : false }};
          }},
          // TEST-ONLY: the live TransformControls drag state (the
          // canonical "is a real drag in progress" signal) so the
          // harness can assert a REAL mouse-drag actually entered
          // TC's drag (proves the event reached TC, not the API).
          get gzCtlDragging() {{
            return _gzCtl ? !!_gzCtl.dragging : false;
          }},
          get gzCtlAxis() {{
            return _gzCtl ? (_gzCtl.axis || null) : null;
          }},
          gzDetach() {{ _gzDetach(); return _gzSelKf; }},
          // Simulate a gizmo TRANSLATE drag: move the proxy by a
          // world delta + run the SAME objectChange write-back the
          // real drag fires (we cannot synthesise a pointer drag on
          // the addon's internal plane deterministically; this
          // drives the EXACT same _gzWriteProxyToKf the gizmo's
          // 'objectChange' listener calls).
          gzDragTranslate(dx, dy, dz) {{
            if (!_gzProxy || _gzSelKf < 0) return null;
            _gzProxy.position.x += (+dx || 0);
            _gzProxy.position.y += (+dy || 0);
            _gzProxy.position.z += (+dz || 0);
            _gzProxy.updateMatrixWorld(true);
            _gzWriteProxyToKf();
            const kf = _gzSelKfObj();
            return kf ? (kf.pos || []).slice() : null;
          }},
          // Simulate a gizmo ROTATE drag: rotate the proxy by a
          // quaternion (xyzw) + run the SAME write-back.
          gzDragRotate(qx, qy, qz, qw) {{
            if (!_gzProxy || _gzSelKf < 0) return null;
            const q = new THREE.Quaternion(qx, qy, qz, qw).normalize();
            _gzProxy.quaternion.premultiply(q);
            _gzProxy.updateMatrixWorld(true);
            _gzWriteProxyToKf();
            const kf = _gzSelKfObj();
            return kf ? (kf.quat || []).slice() : null;
          }},
          // R/T mode toggle (drives the SAME _gzApplySpace the
          // keydown handler runs).
          gzSetMode(m) {{
            _gzMode = (m === 'rotate') ? 'rotate' : 'translate';
            _gzApplySpace();
            return _gzCtl ? _gzCtl.mode : _gzMode;
          }},
          // SPACE World<->Screen toggle (drives the SAME path).
          gzToggleSpace() {{
            _gzScreen = !_gzScreen;
            _gzApplySpace();
            return {{ screen: _gzScreen,
              ctlSpace: _gzCtl ? _gzCtl.space : null }};
          }},
          gzSetSpace(s) {{
            _gzScreen = (s === 'screen');
            _gzApplySpace();
            return {{ screen: _gzScreen,
              ctlSpace: _gzCtl ? _gzCtl.space : null }};
          }},
          // V interp popover open + pick (drives the REAL popover
          // DOM + the REAL _gzSetInterp the buttons call).
          gzOpenInterp() {{ _gzOpenPopover(); return !!_gzPopEl; }},
          gzCloseInterp() {{ _gzClosePopover(); return !_gzPopEl; }},
          gzPickInterp(val) {{
            // Click the matching popover button if open (the REAL
            // DOM path); else fall back to the same _gzSetInterp.
            if (_gzPopEl) {{
              const b = _gzPopEl.querySelector(
                '[data-interp="' + val + '"]');
              if (b) {{ b.click(); return _gzSelInterpVal(); }}
            }}
            _gzSetInterp(val);
            _gzClosePopover();
            return _gzSelInterpVal();
          }},
          // K record (drives the REAL _gzRecordKeyframe -> live
          // camera pose + real-elapsed playhead t).
          gzRecord() {{
            const kf = _gzRecordKeyframe();
            return kf ? {{ t: kf.t, pos: kf.pos.slice(),
              quat: kf.quat.slice(), fov: kf.fov }} : null;
          }},
          get gzTourStopped() {{ return _gzTourStopped; }},
          // The real-elapsed playhead (the SAME _trajPlayhead the
          // overlay/timeline use) -- so the harness can assert
          // Record used it (not a +2.0 fallback).
          get gzPlayheadT() {{
            try {{
              const p = _gzActivePath();
              const ph = p ? buildPlayer(p) : null;
              const v = ph ? _trajPlayhead(ph) : 0;
              return (typeof v === 'number' && isFinite(v))
                ? Math.max(0, v) : 0;
            }} catch (e) {{ return 0; }}
          }},
          // ---- Save / SPCP emit ----
          // Build the Contract-C camera-scope patch (allow-list
          // ONLY; the harness asserts NO primary_asset).
          gzBuildPatch() {{ return _buildPatch(); }},
          gzBuildPayload() {{ return _buildSpcpPayload(); }},
          // The JS-ported encode_spcp over an ARBITRARY payload --
          // so the harness/pytest can assert byte-identity vs the
          // Python encode_spcp for the SAME payload (the spec's
          // core correctness gate).
          gzEncodeSpcp(slug, payload) {{
            return _encodeSpcp(slug, payload);
          }},
          // Drive the REAL cli Save (emit token + show the relay
          // card) and RETURN the emitted token so the harness can
          // capture it for the Python round-trip / byte-identity
          // pytest check (the spec mandates a real captured token,
          // not a hand-constructed one).
          gzSaveCliToken() {{
            return _gzSaveCli();
          }},
          // Drive the REAL Save dispatch (cli -> token string;
          // http -> the fetch Promise) -- so the harness can assert
          // the http path POSTs the right patch to SAVE_ENDPOINT.
          gzSave() {{ return _gzSave(); }},
          gzAuthorSecret() {{ return _gzAuthorSecret(); }},
          // Close the Save card if open (harness cleanup so its
          // textarea focus does not eat later key probes).
          gzCloseSaveCard() {{
            const o = document.getElementById('gz-save-overlay');
            if (o) {{ o.remove(); return true; }}
            return false;
          }},
          // ---- Bezier tangent-handle surface (TEST-ONLY) --------
          // Are the in/out tangent handles currently shown?
          get tanHandlesVisible() {{
            return !!(_tanGroup && _tanGroup.parent === scene &&
              _tanGroup.visible);
          }},
          get tanSelIsBezier() {{ return _tanIsBezierSel(); }},
          // The selected keyframe's STORED explicit tangents (the
          // SAME in-memory arrays the spline reads + Save emits) --
          // null until the key is bezier with handles. So the
          // harness can assert a drag CHANGED kf.in_tan/out_tan.
          get tanSelTans() {{
            const kf = _gzSelKfObj();
            if (!kf) return null;
            return {{
              interp: kf.interp || null,
              in_tan: (Array.isArray(kf.in_tan)
                && kf.in_tan.length === 3) ? kf.in_tan.slice() : null,
              out_tan: (Array.isArray(kf.out_tan)
                && kf.out_tan.length === 3)
                ? kf.out_tan.slice() : null,
            }};
          }},
          // The current handle SQUARE world positions (what the
          // harness converts to NDC to aim a REAL mouse at).
          get tanHandleWorld() {{
            if (!_tanGroup || !_tanOutBox || !_tanInBox) return null;
            return {{
              out: [_tanOutBox.position.x, _tanOutBox.position.y,
                _tanOutBox.position.z],
              in: [_tanInBox.position.x, _tanInBox.position.y,
                _tanInBox.position.z],
            }};
          }},
          // Convert the selected key to bezier + reveal handles
          // (drives the SAME _tanEnableBezier the B key / button
          // call). Returns whether it is now bezier.
          tanEnableBezier() {{ return _tanEnableBezier(); }},
          // Raycast-pick a handle square at NDC -> 'in'|'out'|null
          // (drives the REAL _tanPickBox off the live geometry).
          tanPickAtNdc(ndcx, ndcy) {{
            const rect = renderer.domElement.getBoundingClientRect();
            const cx = rect.left + (ndcx + 1) * 0.5 * rect.width;
            const cy = rect.top + (1 - ndcy) * 0.5 * rect.height;
            return _tanPickBox(cx, cy);
          }},
          // Would a real pointerdown at these CLIENT px yield to the
          // handle TC (pointer over a handle axis => the capture
          // handler must NOT consume it so TC's own bubble-phase
          // pointerDown drives the drag)? Drives the EXACT
          // _tanPointerOnGizmo the real _gzOnCanvasDown calls.
          tanPointerOnGizmoAt(clientX, clientY) {{
            const on = _tanPointerOnGizmo(clientX, clientY);
            return {{ onGizmo: !!on,
              axis: _tanCtl ? (_tanCtl.axis || null) : null,
              dragging: _tanCtl ? !!_tanCtl.dragging : false }};
          }},
          // The live handle-TC drag state (the canonical "a real
          // drag is in progress" signal) so the harness can assert a
          // REAL mouse-drag actually entered the handle TC.
          get tanCtlDragging() {{
            return _tanCtl ? !!_tanCtl.dragging : false;
          }},
          get tanCtlAxis() {{
            return _tanCtl ? (_tanCtl.axis || null) : null;
          }},
          get tanActiveSide() {{ return _tanActiveSide; }},
          // Attach the handle-TC to a side (drives the SAME
          // _tanAttachSide the pointer pick calls) -> resolves once
          // the lazily-imported TC has attached.
          tanAttach(side) {{
            _tanAttachSide(side);
            return _tanEnsureCtl().then(() => ({{
              attached: !!(_tanCtl && _tanCtl.object ===
                (side === 'out' ? _tanOutProxy : _tanInProxy)),
              side: _tanActiveSide,
            }}));
          }},
          // Simulate a handle drag by a WORLD delta + run the SAME
          // _tanWriteFromProxy the gizmo's 'objectChange' fires (we
          // cannot synthesise a pointer drag on the addon's internal
          // plane deterministically; the REAL trusted-mouse drag is
          // verified separately by Playwright -- this drives the
          // EXACT same write-back path for a deterministic check).
          tanDrag(side, dx, dy, dz) {{
            const proxy = side === 'out' ? _tanOutProxy : _tanInProxy;
            if (!proxy || !_tanIsBezierSel()) return null;
            _tanActiveSide = side;
            if (proxy.parent !== scene) scene.add(proxy);
            proxy.position.x += (+dx || 0);
            proxy.position.y += (+dy || 0);
            proxy.position.z += (+dz || 0);
            proxy.updateMatrixWorld(true);
            _tanWriteFromProxy(side);
            const kf = _gzSelKfObj();
            return kf ? {{
              in_tan: (kf.in_tan || []).slice(),
              out_tan: (kf.out_tan || []).slice(),
              interp: kf.interp || null,
            }} : null;
          }},
          // The effective (explicit OR derived-default) tangent
          // vectors for the selected key -- so the harness can
          // assert the derived default == the `automatic` formula
          // (handles appear ON the curve, no jump).
          tanEffectiveVecs() {{ return _tanVecs(); }},
          tanHide() {{
            _tanHide();
            return !(_tanGroup && _tanGroup.parent === scene &&
              _tanGroup.visible);
          }},
        }};
        // Preserve getters AS getters (Object.assign would freeze
        // them -- same reasoning as the Task-17 extension).
        Object.defineProperties(
          window.__editor, Object.getOwnPropertyDescriptors(_gzApi));
      }}
    }} catch (e) {{}}
  }})();

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
