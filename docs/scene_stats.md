# Per-scene stats — #57 chunked cluster-sh rebuilds

Appended as each scene builds + deploys. Source PLYs per
`memory/project_scene_source_plys`. Build = `--quality --rad-chunked
--cluster-sh` (default 10 iters unless noted). cluster-sh convergence
curves: see `cluster_sh_convergence.md`.

| Scene | Splats | SH | Source PLY (GB) | Chunks | Deployed (.rad+.radc) | Upload | cluster-sh final avg_dist | Per-scene cfg | Live folder | Verified |
|-------|-------:|---:|----------------:|-------:|----------------------:|-------:|--------------------------:|---------------|-------------|----------|
| **IBUG** (ref) | ~23.0 M | 3 | (`.radchunk_cs` cache) | 477 | 661 MB | ~22 s | — | clip_xy 1.4 | `IBUG_cs_v26` | ✅ 2 M/120 fps, embed ✓, card ✓ |
| **Polygraf** | 14.98 M | 3 | 3.54 | 313 | 441 MB | ~19 s | 0.0753 (10 it) | move_speed 0.25 → **splat_budget 3 M** (v4) | `Polygraf_Leutzsch_cs_v3` → v4 | ✅ 0 err; muddy→3 M fix in v4 |
| **Fabrik** | 15.06 M | 3 | 3.55 | building | building | — | ~0.0001 (flat by it 3) | (default) | `Fabrik_Leutzsch_cs_v1` (pending) | ⏳ building |
| **Speicher** | — | — | 3.55 (COLMAP4.ply) | — | — | — | — | **clip_xy 3.0** | (pending) | ⏳ queued |
| **Stettiner** | — | — | 7.05 (30 M Postshot) | — | — | — | — | (default) — `--cluster-sh=6`? | (pending) | ⏳ queued |
| **MethTrailer** | — | — | 6.90 (v03.ply) | — | — | — | — | (default) — `--cluster-sh=6`? | (pending) | ⏳ queued (new project) |

## Notes

- **Splat count** from build-lod `Read: num_splats: N with sh_degree: D`.
- **Compression**: Polygraf 3.54 GB PLY → 441 MB chunked cluster-sh ≈ **8×**
  smaller (the cluster-sh + LoD win that makes these deployable).
- **Polygraf** needed a higher budget to not look muddy at its aerial start
  view (user-confirmed "good at 3 M") → `splat_budget: 3 M` baked in v4
  (honored on capable desktop only; mobile/M1 keep their safe tier value).
  Camera-speed now a live in-viewer control (no redeploy) + per-scene
  `move_speed_mult` default 0.25 for Polygraf.
- **Stettiner / MethTrailer** are the heavy ones; `--cluster-sh=6` proposed
  (see convergence doc) — ~40 % faster, no perceptible loss; user decision
  pending.
- Verified = Playwright render check (splats, fps, 0 console errors) +
  share-card scraper check + `?embed=1` chrome-hidden.
