# Splatpipe

Automated photogrammetry-to-Gaussian-splatting pipeline.

Takes COLMAP data through: auto-clean, training (Postshot / LichtFeld Studio), SuperSplat review, PlayCanvas LOD output.

## Install

```bash
pip install -e ".[dev]"
```

## CLI

```bash
splatpipe init <colmap_dir> --name MyProject
splatpipe clean
splatpipe train
splatpipe assemble
splatpipe deploy --target bunny
splatpipe status
```
