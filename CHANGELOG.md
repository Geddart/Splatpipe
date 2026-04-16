# Changelog

All notable changes to Splatpipe will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.0] - 2026-04-17

### Added
- **Camera path tours** — author smooth fly-through cameras in the scene editor or import them. Per-path keyframes carry `pos`/`quat`/`fov`/`hold_s` plus optional `annotation_id` for highlighting. Per-path `smoothness` slider (0..1, default 1.0 = full Catmull-Rom) and `play_speed` log-scale slider (0.01×..5×) work live during playback.
- **Smooth-pass-through spline playback** — ported SuperSplat's MIT cubic Hermite (`src/anim/spline.ts`) into both viewers. 8-D spline over `(pos.xyz, quat.xyzw, fov)`, quat renormalised per frame; `fromPointsLooping` for smooth loop wrap. C1 (velocity) continuity through every keyframe — no stop-start at keys. Same algorithm in PlayCanvas + Spark, byte-identical motion.
- **glTF camera importer** — `splatpipe path-import scene.glb` (or web upload) parses `KHR_animations` channels for the first perspective camera, walks parent transforms, samples to fixed-step keyframes, applies the 180°-X PLY-native → PC-displayed flip, appends as a new path.
- **COLMAP capture-camera importer** — `splatpipe path-import-colmap` reads `01_colmap_source/cameras.{txt,bin}` + `images.{txt,bin}`, computes camera-in-world from each image's pose, applies the 180°-X flip, emits a path with one keyframe per image (or every-Nth). Friendly error for passthrough projects with no COLMAP source. Algorithm references SuperSplat's `colmap-loader.ts` (MIT).
- **Spark 2 renderer** — per-project `renderer: "playcanvas" | "spark"` toggle in the Assemble settings panel. PlayCanvas remains default; switching to Spark emits a `.rad` streaming LoD viewer.
  - `splatpipe build-lod <project>` standalone CLI for warming the cache.
  - `viewers/spark/build_lod.py` wraps the Rust `build-lod` binary (sparkjsdev/spark MIT) — toolchain detection (cached binary → `$SPARK_REPO` release → `cargo run --manifest-path …` first-run), sha256+rev cache key in `~/.cache/splatpipe/rad/`, subprocess streaming with `ProgressEvent`-style callback, atomic move into the cache.
  - `viewers/spark/template.py` emits a self-contained THREE.js + `@sparkjsdev/spark@2.0.0` viewer pinned to `three@0.180.0` (peer dep). Loads `scene.rad` with `paged: true` for HTTP-Range streaming. CSS2DRenderer annotation markers, OrbitControls, conditional bounds clamp, conditional `THREE.AudioListener` only when audio sources exist, foveation knobs (`coneFov0`, `coneFov`, `coneFoveate`, `behindFoveate`).
  - Tone mapping mapped from PC names: `neutral`→Neutral, `aces`/`aces2`→ACESFilmic, `filmic`→AgX, `linear`→Linear.
  - Splat oriented with the same 180°-X flip as PC so annotations + camera-paths land in the same place across renderers.
- **Annotation `id` migration** — `Project.__init__` now runs `_migrate_state()` once, idempotently backfilling stable `id`s on existing annotations so `keyframe.annotation_id` references stay valid.
- **Cascade on annotation delete** — deleting an annotation clears any `keyframe.annotation_id` references to it across all paths.

### Changed
- `DEFAULT_SCENE_CONFIG` extended with `camera_paths`, `default_path_id`, `spark_render` (lod_splat_scale, lod_render_scale, foveation, ondemand_lod_fallback).
- New `pygltflib` runtime dependency (camera-path glTF import).
- `LodAssemblyStep.run() / run_streaming()` dispatch on `project.renderer`. PlayCanvas pipeline path (chunked SOG via `splat-transform`) is unchanged; Spark path delegates to the new `SparkAssembler`.
- `splatpipe assemble` summary print handles both renderer shapes (PlayCanvas: chunk count; Spark: `.rad` size, optional `.sog` fallback flag).

### Fixed
- Mid-drag DOM rebuild bug on per-path sliders — `updatePathSilent` saves to the server without triggering `loadPaths()`/re-render so the slider keeps its dragged value.
- `gotoKeyframe` in the scene editor — direct `camera.setPosition` was overridden by PlayCanvas's `CameraControls` on the next update tick. Now uses `cc.reset(focus, position)` (`camera-controls.mjs:697`) so the new pose sticks AND the user can keep orbiting from there. `stopPath` rebinds the controls the same way so playback ending doesn't snap back.

### Notes
- Spark output requires the Rust toolchain + a sibling clone of [sparkjsdev/spark](https://github.com/sparkjsdev/spark) (or `SPARK_REPO` env var). First-time `cargo build --release` of the workspace takes ~2 min; subsequent runs use the cached `build-lod` binary.
- PlayCanvas pin remains `2.17.0` (2.17.1+ has a regression — see 0.5.0 notes). Spark pin is `2.0.0`.

## [0.5.0] - 2026-04-16

### Security
- Bumped minimum `python-multipart` to 0.0.22 (CVE-2026-24486)
- Bumped minimum `pytest` to 9.0.3 (CVE-2025-71176)

### Fixed
- **LichtFeld Studio no longer risks a buffer-deadlock hang**: the trainer was opening `stderr=subprocess.PIPE` and only reading it after the stdout loop, so a LichtFeld run that emitted more than ~64 KB of stderr could block the subprocess indefinitely. Merged stderr into stdout (same pattern the Postshot trainer already uses); the stderr tail is still surfaced on failure via `TrainResult.stderr`.
- **`state.json` corruption surfaces a readable error instead of a JSONDecodeError traceback**: `Project._load_state` now raises `RuntimeError("state.json is corrupted at ...")` so the runner's failure path records something the user can act on.
- **`state.json` writes are now atomic**: `Project._save_state` writes to `state.json.tmp` and then `os.replace`s it into place, so a crash or kill mid-write no longer leaves a truncated state file behind.
- **Passthrough cancel takes effect during extraction, not after**: `PassthroughTrainer` no longer blocks the generator with `Popen.communicate()` during `.psht` export. It now uses a reader thread + 2s heartbeat yields (same pattern as `PostshotTrainer`), so cancel clicks kill the process within a couple of seconds instead of waiting for the full export to finish.
- **Manual review approval is preserved under a tight race with the runner**: `_execute_review` now re-reads state one more time right before recording `waiting`, so an approval that lands between the initial check and the write short-circuits cleanly instead of getting clobbered.
- **Camera Constraints toggle now actually turns off**: the `Enabled` checkbox was missing a hidden `enabled=false` sibling input, so unchecking sent nothing and the merge preserved the previous `enabled=true`. Added the hidden input; also added regression tests for both the on and off transitions.
- **Passthrough review step preserves existing completed summary**: when a user had already approved the review step (manually or in a prior run), `_execute_review` now short-circuits to the "already approved" branch before the passthrough auto-approve branch, so prior summary data isn't clobbered.
- **Viewer no longer hangs on PlayCanvas 2.17.x patch releases**: pinned the viewer's PlayCanvas import to `2.17.0` (was `2.17`, which floated to 2.17.2). Patches 2.17.1 and 2.17.2 introduced a regression that fired `Cannot read properties of undefined (reading 'listener')` every frame in the engine update loop and prevented splat rendering (splat count stuck at 0.00M, loading spinner never hides). Camera-controls.mjs is now version-pinned the same way to keep them in lockstep.
- `audiolistener` component is now only attached when `viewer-config.json` actually has audio sources — saves the engine some idle work in the common no-audio case.

### Added
- **Camera constraints toggle**: new `Enabled` checkbox in the Camera Constraints panel. Default is OFF — the viewer lets the user fly anywhere with no pitch/zoom/ground/bounds clamping. Turning it on applies the existing constraint values. Fixed a related state bug where partial scene-config saves (e.g. one number field) wiped sibling fields; `Project.set_scene_config_section()` now merges dict updates instead of replacing them.
- **Passthrough trainer**: publish a finished `.psht` or `.ply` to Bunny CDN without retraining. Selected from the trainer dropdown — extracts the embedded splat (`.psht` via `postshot-cli export`) or copies the file (`.ply`), then runs assemble + export. Auto-skips `clean` and `review` steps.
- **Standalone `.ply` source format**: `splatpipe init scene.ply` and the web "+ New Project" form now accept raw `.ply` files. Auto-defaults to passthrough trainer.
- **Smart trainer default**: projects created from `.psht` or `.ply` sources auto-select the passthrough trainer; COLMAP sources still default to postshot.
- **Step info tooltips**: every pipeline step in the project detail view now shows a hover info icon explaining what the step does.
- **Passthrough mode banner** on the project detail page when trainer is passthrough, with a one-line summary of what runs.
- Postshot 1.0.331 `--pose-quality` support (1=Fast, 4=Best, default 3)
- Postshot 1.0.287 support: Splat ADC/MCMC profiles, GPU selection, SH degree control, no-recenter, image selection mode
- LichtFeld Studio v0.5.1 support: PPISP per-camera appearance modeling (`--ppisp`, `--ppisp-controller`)
- LichtFeld headless training mode (`--headless --train` flags, always enabled for CLI/pipeline)
- LichtFeld quality options: SH degree, mip filter (anti-aliasing), bilateral grid, image downscaling, tile mode for VRAM management
- LichtFeld sparsity optimization and undistort support
- New config options for both trainers exposed in web settings page

### Changed
- LichtFeld CLI command now always includes `--headless` and `--train` for pipeline use
- Bumped `@playcanvas/splat-transform` to ^1.10.2 (from ^1.7.0)
- Bumped PlayCanvas CDN from 2.16 to 2.17 (viewer, scene_editor, and assembled LOD viewer)
- Migrated LOD distance API from `lodDistances` array to `lodBaseDistance` + `lodMultiplier` (geometric progression; required by PlayCanvas 2.17)
- Replaced per-LOD distance sliders in assembled viewer with base + multiplier sliders plus live per-LOD distance preview

### Removed
- "Headless mode uncertain" caveat from LichtFeld known limitations

## [0.4.1] - 2026-02-15

### Fixed
- Unused imports flagged by ruff lint in CI

## [0.4.0] - 2026-02-15

### Added
- Postshot `.psht` file as direct input source: create projects from `.psht` files, Splatpipe copies the file and trains each LOD from it
- Splat count warning: after each LOD training, compares exported PLY vertex count to target and warns if over budget
- Review re-export: checkbox on "Approve & Continue" to re-export PLYs from edited `.psht` files via `postshot-cli export`
- `detect_source_type()` in parsers: handles both files (`.psht`) and directories (COLMAP, Bundler, etc.)
- `source_type` and `source_file()` on Project model for .psht source tracking
- CLI `splatpipe init` accepts `.psht` files as input (copies to project, never modifies original)
- CLI `splatpipe train` handles `.psht` source projects
- Scene authoring: `viewer-config.json` carries camera constraints, splat budget, and future scene settings from dashboard to viewer
- Camera constraints in production viewer: configurable pitch limits, zoom range, ground height, and bounds radius
- Per-project default splat budget: set initial budget in dashboard, viewer reads from config at startup
- Custom LOD distance sliders: color-coded sliders matching PlayCanvas engine's colorizeLod debug view
- Dashboard UI: Camera Constraints and Default Splat Budget controls in Assemble settings
- `splatpipe serve` auto-generates `viewer-config.json` fallback if missing
- Assembly copies project `assets/` folder to output (for future audio/media support)
- Scene editor: visual click-to-place annotation tool with full 3D viewer, annotation sidebar, and ray-based ground-plane placement
- Annotation markers in production and preview viewers: numbered orange pins with hover tooltips, projected from 3D world positions
- Annotation CRUD routes: add, update, delete annotations with automatic re-labeling
- Audio support in viewer: ambient and positional audio from `viewer-config.json` with PlayCanvas SoundComponent
- Audio management in dashboard: upload audio files, configure volume/loop/positional per track
- Audio CRUD routes: add, update, delete audio sources with file upload to project assets
- Global pipeline queue: enqueue runs for multiple projects from the dashboard, see pending jobs, reorder, pause, and cancel
- Queue panel on projects page with live progress for the current job and management controls for pending jobs
- Background color setting in dashboard and viewer: configurable clear color applied to canvas and page body
- Post-processing settings: tonemapping (linear/neutral/aces/aces2/filmic), exposure, bloom, and vignette controls in dashboard
- Multi-format alignment import: detect COLMAP (.txt/.bin), Bundler, RealityScan, and BlocksExchange formats
- Binary COLMAP support: clean step auto-converts `.bin` files to text before filtering
- Format detection on project creation: shows detected format, never blocks (unknown formats allowed)

### Changed
- "COLMAP Source" label renamed to "Source (Postshot, COLMAP, etc.)" in dashboard
- "Alignment Data Directory" renamed to "Source (Postshot file, COLMAP folder, etc.)" on project creation form
- Browse buttons split into "Folder" and "File" for source path selection
- Clean step auto-skips for `.psht` input projects (no COLMAP data to clean)
- Project creation form simplified: removed Training and Pipeline Steps sections (configurable on project detail page after creation)
- `splatpipe init` warns on unknown alignment format instead of blocking
- `splatpipe clean` accepts binary COLMAP input (converts to text internally)

### Fixed
- PLY header reader no longer hangs on invalid/truncated PLY files (infinite loop on missing `end_header`)

## [0.3.1] - 2026-02-14

### Changed
- SH bands default changed from 0 (no SH) to 3 (full SH) for better visual quality out of the box

## [0.3.0] - 2026-02-14

### Added
- SH bands setting: configurable spherical harmonics filter (0–3) on Assemble step, defaults to 0 (no SH, smallest files)
- Inline LOD splat count editing in Train step settings (accepts M/K format)

### Changed
- LOD folder names simplified from `lod0_20000k` to `lod0` (decoupled from splat count)
- Default LOD0 bumped from 20M to 25M for new projects

### Fixed
- LOD renumbering now preserves per-LOD settings (enabled, train steps)

## [0.2.0] - 2026-02-13

### Added
- CDN folder name setting: configurable remote path for Bunny CDN exports (defaults to project name)
- CDN model browser: "Refresh" button lists existing folders on Bunny CDN, click to select
- Local preview: serve `05_output/` files through the dashboard for HTTP-based PlayCanvas viewer preview
- Splat budget dropdown in viewer (No limit, 1M, 2M, 3M, 4M, 6M) — defaults to 4M desktop, 1M mobile
- Bunny CDN credentials UI: editable on Settings page, status indicator on Export step panel
- Project history log: all step runs recorded with timestamp, duration, and summary (collapsible section on project detail page)
- Persistent export URL: CDN viewer/folder links survive page reload on Export step card

### Changed
- Viewer HTML now uses PlayCanvas engine with LOD streaming instead of SuperSplat iframe embed
- Viewer supports fly + orbit camera controls (WASD + mouse) and respects project LOD distances
- COLMAP clean step disabled by default for new projects

## [0.1.5] - 2026-02-13

### Fixed
- Cross-platform test fix: `test_open_folder_nonexistent` used Windows-only path that resolved differently on Linux CI

## [0.1.4] - 2026-02-13

### Fixed
- Python 3.11 compatibility: guarded all `Path.is_junction()` calls (added in 3.12)
- Added `python-multipart` to web dependencies (required by FastAPI for form parsing)

## [0.1.3] - 2026-02-13

### Fixed
- Added `httpx` to dev dependencies (required by `starlette.testclient` but not pulled in automatically)
- Removed COLMAP from README requirements table (Splatpipe reads COLMAP output, doesn't require COLMAP installed)

## [0.1.2] - 2026-02-13

### Fixed
- CI workflow now installs web dependencies (`.[dev,web]`) so web route tests pass on GitHub Actions

### Removed
- Unused logo variants (`SplatPipe_Logo_01.png`, `SplatPipe_Logo_02.png`)

## [0.1.1] - 2026-02-13

### Removed
- COLMAP tool path setting and GUI launch button (Splatpipe reads COLMAP output files but never calls the COLMAP executable)

## [0.1.0] - 2026-02-13

### Added
- CLI-first pipeline: `init`, `clean`, `train`, `assemble`, `export`, `serve`, `status`, `run`
- Pluggable trainer backends: Postshot and LichtFeld Studio with shared `train_lod()` generator protocol
- COLMAP streaming parsers for multi-GB `cameras.txt`, `images.txt`, `points3D.txt`
- COLMAP cleaning: camera outlier removal, KD-tree point filtering, POINTS2D reference cleanup
- LOD assembly via `splat-transform` producing PlayCanvas SOG streaming format
- Export to local folder or Bunny CDN (parallel uploads with progress)
- Web dashboard with FastAPI + HTMX + DaisyUI (project list, detail, settings, first-run wizard)
- Background pipeline runner: daemon-thread execution, SSE progress streaming, cancel support
- Manual review step: human gate between training and assembly with PLY/PSHT inspection
- Auto-generated `index.html` viewer using SuperSplat iframe (works on any hosting origin)
- File/folder browser dialogs for all path input fields
- Per-project config overrides via `project.toml` (deep-merged over `defaults.toml`)
- Debug JSON output with full command, stdout/stderr, timing, and environment for every step
- CI pipeline: ruff lint + pytest across Python 3.11/3.12/3.13

### Fixed
- Sequential LOD indices for splat-transform (sparse indices created empty LOD gaps on CDN)
- LOD directory cleanup before training (stale `.psht` caused duplicate radiance fields)
- Windows path normalization for runner lookup (URL forward-slash vs `Path()` backslash)
- Postshot progress parser matched real v1.0.185 output format

[Unreleased]: https://github.com/Geddart/Splatpipe/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/Geddart/Splatpipe/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/Geddart/Splatpipe/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/Geddart/Splatpipe/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/Geddart/Splatpipe/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Geddart/Splatpipe/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Geddart/Splatpipe/compare/v0.1.5...v0.2.0
[0.1.5]: https://github.com/Geddart/Splatpipe/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/Geddart/Splatpipe/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/Geddart/Splatpipe/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/Geddart/Splatpipe/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Geddart/Splatpipe/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Geddart/Splatpipe/releases/tag/v0.1.0
