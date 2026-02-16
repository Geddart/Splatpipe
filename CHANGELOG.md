# Changelog

All notable changes to Splatpipe will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Geddart/Splatpipe/compare/v0.4.0...HEAD
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
