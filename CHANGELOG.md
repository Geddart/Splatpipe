# Changelog

All notable changes to Splatpipe will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Geddart/Splatpipe/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/Geddart/Splatpipe/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Geddart/Splatpipe/releases/tag/v0.1.0
