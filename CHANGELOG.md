# Changelog

All notable changes to Splatpipe will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Geddart/Splatpipe/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Geddart/Splatpipe/compare/v0.1.5...v0.2.0
[0.1.5]: https://github.com/Geddart/Splatpipe/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/Geddart/Splatpipe/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/Geddart/Splatpipe/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/Geddart/Splatpipe/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Geddart/Splatpipe/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Geddart/Splatpipe/releases/tag/v0.1.0
