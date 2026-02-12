# Splatpipe

Automated photogrammetry-to-Gaussian-splatting pipeline.

Takes COLMAP data through: auto-clean, training (Postshot / LichtFeld Studio), SuperSplat review, PlayCanvas LOD output. Every operation works as a CLI command, with a web dashboard on top.

## Quick Start

```bash
git clone <repo-url>
cd Splatpipe
pip install -e ".[web]"
splatpipe web
```

Open http://localhost:8000 — you'll be guided through first-time setup:

1. **Set projects folder** — where your project data lives
2. **Auto-detect tools** — finds Postshot, COLMAP, LichtFeld Studio, splat-transform
3. **Create a project** — point it at a COLMAP export directory

## Requirements

- Python 3.11+
- **Postshot CLI** — `C:\Program Files\Jawset Postshot\bin\postshot-cli.exe` (jawset.com)
- **COLMAP** — `C:\Program Files\Colmap\bin\colmap.exe` (colmap.github.io)
- **LichtFeld Studio** (optional) — open-source trainer by MrNeRF
- **Node.js** — for `npx @playcanvas/splat-transform` LOD assembly

## CLI

```bash
splatpipe init <colmap_dir> --name MyProject
splatpipe clean
splatpipe train
splatpipe assemble
splatpipe deploy --target bunny
splatpipe status
splatpipe web               # Launch web dashboard
```

## Web Dashboard

The dashboard lets you do everything from the browser:

- **Settings** — configure tool paths, auto-detect installed tools, system check
- **Projects** — create projects, enable/disable pipeline steps, run steps with live progress
- **Step toggles** — skip steps like COLMAP clean if your data is already clean

## Pipeline Steps

| Step | What it does |
|------|-------------|
| **Clean** | Remove outlier cameras + KD-tree point filtering + POINTS2D cleanup |
| **Train** | Run Gaussian splat training at multiple LOD levels |
| **Review** | Open PLYs in SuperSplat for manual floater cleanup |
| **Assemble** | Build PlayCanvas LOD streaming format (lod-meta.json + SOG chunks) |
| **Deploy** | Upload to Bunny CDN |

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```
