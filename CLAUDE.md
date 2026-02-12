# Splatpipe — CLAUDE.md

## What This Is

CLI-first Gaussian splatting pipeline. Takes COLMAP data through: auto-clean → training (Postshot / LichtFeld Studio) → SuperSplat review → PlayCanvas LOD output. Every operation is a CLI command; web dashboard (FastAPI + HTMX) on top.

## Quick Start

```bash
cd H:\001_ProjectCache\1000_Coding\Splatpipe
pip install -e ".[dev]"
pytest tests/ -v                    # Run tests (70 tests, ~1s)
splatpipe --help                    # CLI commands
splatpipe web                       # Launch dashboard
```

## Architecture

### CLI-first, web on top
Every operation is a Typer CLI command. The web dashboard calls the same underlying functions. Long operations yield `ProgressEvent` objects — CLI shows Rich progress bars, web streams them via SSE.

### Trainer abstraction
Pluggable backends: `PostshotTrainer`, `LichtfeldTrainer`. Each implements `train_lod()` as a generator yielding `ProgressEvent`, returning `TrainResult`. Registry for discovery.

### No fixed pipeline
No linear stage ordering. Each CLI command checks its own prerequisites and updates `state.json` independently.

## Package Layout

```
splatpipe/                    # repo root
  pyproject.toml              # hatchling, CLI entry points
  README.md
  .gitignore
  config/defaults.toml
  src/splatpipe/
    __init__.py
    cli/                      # Typer commands
      main.py                 # App with all commands registered
      init_cmd.py             # splatpipe init <colmap_dir>
      clean_cmd.py            # splatpipe clean
      train_cmd.py            # splatpipe train [--trainer postshot|lichtfeld]
      assemble_cmd.py         # splatpipe assemble
      deploy_cmd.py           # splatpipe deploy --target bunny
      serve_cmd.py            # splatpipe serve [--port 8080]
      run_cmd.py              # splatpipe run (full pipeline)
      web_cmd.py              # splatpipe web [--port 8000]
      status_cmd.py           # splatpipe status
    core/                     # Project, config, constants, events
      project.py              # Project class: folder scaffold, state.json CRUD
      config.py               # TOML config loader (defaults + per-project merge)
      constants.py            # Folder names, LOD defaults, step names
      events.py               # ProgressEvent, StepResult dataclasses
    colmap/                   # COLMAP utilities (ported verbatim from v1)
      ply_io.py               # Binary PLY reader (numpy structured arrays)
      parsers.py              # Streaming generators for cameras/images/points3D.txt
      filters.py              # Camera outlier, KD-tree, POINTS2D cleaner
    trainers/                 # Abstract + implementations
      base.py                 # Abstract Trainer, TrainResult dataclass
      postshot.py             # PostshotTrainer (Popen + progress parsing)
      lichtfeld.py            # LichtfeldTrainer (--max-cap uses actual count)
      registry.py             # {"postshot": PostshotTrainer, "lichtfeld": LichtfeldTrainer}
    steps/                    # Clean, assemble, deploy
      base.py                 # Abstract PipelineStep (debug JSON, env capture)
      colmap_clean.py         # COLMAP cleaning step (outliers + KD-tree + POINTS2D)
      lod_assembly.py         # splat-transform LOD meta + SOG compression
      deploy.py               # Bunny CDN upload with progress events
    web/                      # FastAPI + HTMX dashboard
      app.py                  # FastAPI app
      routes/projects.py      # Project list + detail
      routes/training.py      # SSE training progress
      routes/settings.py      # Config display
      templates/              # Jinja2 templates (DaisyUI + HTMX via CDN)
      static/viewer.html      # SuperSplat viewer embed
  tests/
    test_data/                # tiny_cameras.txt, tiny_images.txt, etc.
    conftest.py               # Shared fixtures
    test_colmap_*.py          # COLMAP module tests
    test_config.py            # Config loading tests
    test_project.py           # Project CRUD tests
    test_integration.py       # End-to-end COLMAP clean test
    test_lod_assembly.py      # LOD assembly mock tests
    test_trainers.py          # Trainer abstraction tests
    test_cli.py               # CLI command tests via CliRunner
```

## Key Design Decisions

### Debug Data over Fallbacks
**No try/except.** Every step writes a `_debug.json` with full command, stdin/stdout/stderr, file stats, metrics, timing, environment. When something fails, the debug JSON tells you exactly why. This is the MOST IMPORTANT design principle.

### Streaming COLMAP Parsers
COLMAP files are multi-GB. Never load fully. All parsers are generators that yield one record at a time.

### ProgressEvent Protocol
Shared between CLI (Rich progress bars) and web (SSE). Training uses `Popen` (not `run`) for real-time stdout parsing.

### Trainer Abstraction
```python
class Trainer(ABC):
    def train_lod(self, source_dir, output_dir, lod_name, max_splats, **kwargs) -> Generator[ProgressEvent, None, TrainResult]
    def validate_environment(self) -> tuple[bool, str]
    def parse_progress(self, line: str) -> float | None
```
Key difference: Postshot uses kSplats (`--max-num-splats 3000`), LichtFeld uses actual count (`--max-cap 3000000`).

## Project Folder Convention

```
<project>/
├── state.json              # Project state (steps, config)
├── project.toml            # Per-project config overrides
├── 01_colmap_source/       # Symlink/junction to COLMAP data
├── 02_colmap_clean/        # Cleaned COLMAP + *_debug.json
├── 03_training/            # Per-LOD training outputs
├── 04_review/              # Human-cleaned PLYs (lod0_reviewed.ply, etc.)
└── 05_output/              # Final LOD output (lod-meta.json + SOG chunks)
```

## Critical Code Patterns

### COLMAP Files — Never Load Fully
```python
# WRONG — will crash on multi-GB files
data = open("points3D.txt").read()

# RIGHT — stream line by line
with open("points3D.txt", "r") as f:
    for line in f:
        if line.startswith("#"): continue
        parts = line.split(maxsplit=4)
        ...
```

### Coordinate Transform: PLY → COLMAP
```python
# PLY is Z-up, COLMAP is Y-down Z-forward
# Transform: COLMAP(X,Y,Z) = PLY(X, -Z, Y)
colmap_coords = np.column_stack([px, -pz, py])
```

### KD-tree Filtering
```python
dist, _ = tree.query([x, y, z], distance_upper_bound=threshold)
if dist <= threshold:
    # Point matches cleaned PLY
```

### images.txt Format — Always Read Both Lines
```python
for line in f:
    if line.startswith("#"): continue
    parts = line.split()
    name = parts[9]
    pts2d_line = next(f, "\n")  # POINTS2D line
```

## Tool Chain

| Tool | Path | Purpose |
|------|------|---------|
| Postshot CLI | `C:\Program Files\Jawset Postshot\bin\postshot-cli.exe` | `train --import <folder> --max-num-splats N` (kSplats) |
| LichtFeld Studio | (configure in defaults.toml) | `-d <data> -o <out> --strategy mcmc --max-cap <N>` (actual count) |
| splat-transform | `npx @playcanvas/splat-transform` | LOD assembly + SOG compression |
| SuperSplat | Browser: superspl.at/editor | Manual floater cleanup |

## Config System

`config/defaults.toml` has global tool paths and settings. Each project can override with `project.toml`. Config is loaded with `load_project_config(project.config_path)` which deep-merges project overrides over defaults.

Key config sections: `[tools]`, `[colmap_clean]`, `[postshot]`, `[lichtfeld]`, `[paths]`

## Tests

```bash
pytest tests/ -v              # All 70 tests
pytest tests/ -k colmap       # Just COLMAP tests
pytest tests/ -k integration  # End-to-end with tiny data
pytest tests/ -k trainers     # Trainer abstraction tests
pytest tests/ -k cli          # CLI command tests
```

Test fixtures in `tests/test_data/`:
- `tiny_cameras.txt` (3 cameras), `tiny_images.txt` (5 cameras, 2 outliers)
- `tiny_points3d.txt` (50 points, 20 near + 30 far)
- `tiny_cloud.ply` (20-vertex binary PLY matching the near points)

## Source Scripts (Refactored From)

The COLMAP cleaning code was refactored from standalone scripts at:
- `H:\001_ProjectCache\660 Drone\_Photogrammetry\150_IBUG_2025\Export\fix_colmap_export.py`
- `...\FromRCtoPS_v09_distort\step1_filter_points3d.py`
- `...\FromRCtoPS_v09_distort\step2_clean_images.py`
- `...\FromRCtoPS_v09_distort\step3_remove_outlier_cams.py`

## Path Context

The photogrammetry projects live at:
- Local: `H:\001_ProjectCache\660 Drone\_Photogrammetry`
- Sync target: `Z:\Projekte\660 Drone\_Photogrammetry` (via Resilio Sync)

## LichtFeld Studio Details
- Free, GPL-3.0, open-source (by Janusch Patas / MrNeRF)
- CLI: `LichtFeld-Studio -d <data> -o <output> --strategy mcmc --max-cap <N> -i <iters>`
- Accepts COLMAP input, outputs PLY + SOG + SPZ
- Native SOG export could skip splat-transform in future
- Headless mode uncertain — document as limitation
- CUDA 12.8+ / driver 570+ required

## Known Limitations / TODO

- Settings page is read-only (edit defaults.toml directly)
- Auto-threshold doesn't work with <10 cameras (use fixed threshold in project.toml)
- `splat-transform` CLI args may need updating when PlayCanvas updates the tool
- LichtFeld headless mode uncertain (may need display)
- Postshot CLI args need verification against actual `postshot-cli.exe --help` output
- Web dashboard training SSE not yet tested with real training runs
