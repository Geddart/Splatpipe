# CLI: Open and retrain existing .psht files with different parameters

Hi,

I'm working on an in-house pipeline where I first create and train a Postshot file (high splat count, e.g. 25M), review it visually, and once it looks good, have an automated pipeline generate different LOD levels from it (10M, 5M, 3M, 1M, 500K splats).

Unfortunately, Postshot CLI doesn't seem to support opening an existing .psht file, changing parameters (like max splat count), retraining, and exporting the result as PLY.

Using `--import <file.psht>` does work, but it always creates a second radiance field in the scene rather than modifying the existing one. And `--export-splat` then exports both fields combined into the PLY, with no way to select which one.

## Ideal workflow

```bash
# Step 1: Create the base file (already works)
postshot-cli train --import <colmap_dir> --max-num-splats 25000 -o base.psht

# Step 2: Generate LOD variants (this is what I'd love to have)
postshot-cli train -f base.psht --max-num-splats 5000 -o lod_5m.psht --export-splat lod_5m.ply
postshot-cli train -f base.psht --max-num-splats 1000 -o lod_1m.psht --export-splat lod_1m.ply
```

Where `-f` opens the existing project and retrains the existing radiance field with new parameters, rather than creating an additional one.

This would make Postshot really powerful for automated LOD pipelines — train once at high quality, then derive all lower LOD levels from the same base.

Thanks!
