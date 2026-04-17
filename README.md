<p align="center">
  <img src="SplatPipe_Logo.png" alt="Splatpipe" width="180">
</p>

<h1 align="center">Splatpipe</h1>

<p align="center">
  <strong>CLI-first Gaussian splatting pipeline with web dashboard</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue?logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux-0078D4?logo=windows" alt="Windows / Linux">
  <img src="https://img.shields.io/badge/tests-439%20passed-brightgreen" alt="Tests">
</p>

---

Takes COLMAP photogrammetry data through a complete pipeline:
**auto-clean** &rarr; **training** (Postshot / LichtFeld Studio) &rarr; **SuperSplat review** &rarr; **viewer output (PlayCanvas chunked SOG OR Spark 2 streaming `.rad`)** &rarr; **export / deploy**

With **camera-path tours** (record waypoints in the editor, import from glTF, or lift from COLMAP capture cameras) and **annotations** that can highlight along the path.

Every operation is a CLI command. The web dashboard (FastAPI + HTMX + DaisyUI) sits on top and calls the same functions — so you can work from the terminal or the browser.

## Quick Start

```bash
git clone https://github.com/Geddart/Splatpipe.git
cd splatpipe
pip install -e ".[web]"
splatpipe web
```

Open **http://localhost:8000** — first-run setup guides you through:

1. **Set your projects folder** — where project data lives
2. **Auto-detect tools** — finds Postshot, COLMAP, LichtFeld Studio, splat-transform on your system
3. **Create your first project** — point it at a COLMAP export and go

> **CLI-only?** Skip the web dashboard and use `splatpipe init <colmap_dir>` instead.

## Pipeline

```
COLMAP data ──► Clean ──► Train ──► Review ──► Assemble ──► Deploy
                 │          │         │           │           │
            Outlier      Postshot  SuperSplat  splat-       Local
            removal +    or        manual      transform    folder or
            KD-tree      LichtFeld cleanup     LOD meta     Bunny CDN
            filtering    Studio                + SOG        upload
```

| Step | What it does |
|------|-------------|
| **Clean** | Remove outlier cameras, KD-tree point filtering, POINTS2D reference cleanup |
| **Train** | Gaussian splat training at multiple LOD levels (e.g. 20M, 10M, 5M, 3M, 1.5M) |
| **Review** | Open trained PLYs in SuperSplat for manual floater removal |
| **Assemble** | Build viewer output. Per-project renderer choice: PlayCanvas (chunked SOG via `splat-transform`) or Spark 2 (single `.rad` with HTTP-Range streaming via Rust `build-lod`) |
| **Export** | Export to local folder or upload to Bunny CDN with progress tracking |

## Camera path tours (v0.6+)

Both viewers can play smooth camera tours through annotated splat scenes. Open the **Scene Editor** for any project, switch to the **Paths** tab:

- **Create** a path, fly the camera, click **Record kf** to capture the current pose. Repeat.
- **Smoothness slider** (0..1) controls the cubic Hermite spline tension — `1.0` is full Catmull-Rom (cinematic), `0.0` is straight segments. Velocity is continuous through every keyframe (no stop-start at keys).
- **Speed slider** is log-scale — drag down for slow-motion (0.01×) or up for fast preview (5×).
- **Loop** + **default (autoplay)** toggles per path.
- Bind a keyframe to an annotation_id and that annotation marker glows while the camera passes through.

Author paths elsewhere and import:

```bash
# From Blender / Max via glTF (export with KHR_animations enabled)
splatpipe path-import scene.glb --project /path/to/project --sample-hz 24

# From COLMAP capture cameras (recreates the original scan path)
splatpipe path-import-colmap --project /path/to/project --every-nth 5
```

Paths play identically in both renderers (same `CubicSpline` ported from SuperSplat MIT).

### DCC bridge — round-trip authoring in 3ds Max + Blender (v0.6.1+)

Two ways to drive the splat into your DCC, animate against it, and post the camera back as a new path:

- **Tier 1 — Claude + MCP** (no install). The scene-editor's **Author camera in Max/Blender via Claude** button gives a copyable prompt. With `3dsmax-mcp` (and optionally the community `blender-mcp`) in your MCP config, Claude pulls the splat, sets up the [Stand-Up Parent](docs/dcc-bridge.md), waits for you to animate, then samples + posts.
- **Tier 2 — In-DCC plugin buttons.** `python tools/dcc-bridge/build.py` produces `splatpipe_bridge.zip` (Blender) and `splatpipe_bridge.mzp` (3ds Max — drag-drop install). Sidebar panel / toolbar dialog with **Pull splat** and **Send camera** buttons.

Both tiers speak HTTP to the same three endpoints (`/dcc/manifest`, `/dcc/splat.ply`, `/dcc/import-camera`) and use the same coordinate-system contract — paths land identically in both renderers regardless of authoring path. See [`docs/dcc-bridge.md`](docs/dcc-bridge.md) for the math + worked example.

## Spark 2 renderer (v0.6+)

PlayCanvas remains the default. To use Spark instead:

1. Install Rust (rustup.rs) and clone the Spark repo as a sibling:
   ```bash
   git clone https://github.com/sparkjsdev/spark
   # Or set SPARK_REPO=/your/path/to/spark in env
   ```
2. In the project detail page, set **Output Renderer** → **Spark 2**.
3. Run `splatpipe assemble`. First build of the Rust `build-lod` workspace takes ~2 min; subsequent runs use the cached binary.
4. The output `05_output/` contains `scene.rad` + `index.html` + `viewer-config.json`. Serve via `splatpipe serve` or any HTTP-Range-capable host (Bunny CDN, FastAPI StaticFiles).

Spark 2 features exposed: foveation (per-cone splat scaling), on-the-fly LoD fallback, hardware-accelerated streaming via HTTP Range requests on the `.rad`. The viewer is `@sparkjsdev/spark@2.0.0` on `three@0.180.0` (its peer dep).

Each step is independent — skip what you don't need with per-project **step toggles**.

## Web Dashboard

The dashboard lets you manage everything from the browser:

- **Settings** — editable config form, auto-detect tool paths, system dependency check
- **Projects** — create projects with COLMAP validation, choose trainer & LOD levels
- **Step toggles** — enable/disable pipeline steps per project (e.g. skip clean for pre-cleaned data)
- **Live execution** — run any step with real-time SSE progress streaming
- **First-run wizard** — guided setup on fresh install

## CLI Reference

```bash
splatpipe init <colmap_dir>     # Create project from COLMAP data
splatpipe clean                 # Clean COLMAP data (outliers + KD-tree)
splatpipe train                 # Train splats at all LOD levels
splatpipe assemble              # Build LOD streaming output
splatpipe export --mode folder  # Export to local folder (or --mode cdn)
splatpipe status                # Show project state
splatpipe run                   # Run full pipeline
splatpipe web                   # Launch web dashboard
```

## Requirements

| Tool | Purpose | Install |
|------|---------|---------|
| **Python 3.12+** | Runtime | python.org |
| **Postshot CLI** | Gaussian splat training | [jawset.com](https://jawset.com) |
| **LichtFeld Studio** | Alternative open-source trainer | [github.com/MrNeRF](https://github.com/MrNeRF/LichtFeld-Studio) |
| **Node.js** | For `splat-transform` LOD assembly | [nodejs.org](https://nodejs.org) |

> **Input data:** Splatpipe expects COLMAP export folders as input. You need to run photogrammetry (e.g. with [COLMAP](https://colmap.github.io) or Reality Capture) before using Splatpipe.

> The web dashboard auto-detects tool paths on first run — no manual config needed if tools are installed in default locations.

## Project Structure

Each project gets a clean folder layout:

```
MyProject/
├── state.json              # Project state & step results
├── project.toml            # Per-project config overrides
├── 01_colmap_source/       # Link to COLMAP data
├── 02_colmap_clean/        # Cleaned COLMAP + debug JSON
├── 03_training/            # Per-LOD training outputs
├── 04_review/              # Human-cleaned PLYs
└── 05_output/              # Final LOD output (lod-meta.json + SOG chunks)
```

## Development

```bash
pip install -e ".[dev]"     # Install with dev dependencies
pytest tests/ -v            # Run all 417 tests (~22s)
```

Key design principle: **debug data over fallbacks**. No try/except — every step writes a `_debug.json` with full command, stdout/stderr, file stats, metrics, timing, and environment. When something fails, the debug JSON tells you exactly why.
