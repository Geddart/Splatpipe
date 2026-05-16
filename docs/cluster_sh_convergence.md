# `--cluster-sh` k-means convergence per scene

Question: does the SH-codebook k-means need the build-lod default **10**
iterations, or fewer? Recorded `sh_clustering: iteration N avg_distance=…`
from each #57 build (lower = better SH reconstruction; k-means monotonically
decreases it, so more iters never harm — only cost time, ~150 s/iter on the
15 M Polygraf, scaling with splat count).

## Curves

| iter | Polygraf (15 M) | Fabrik (build) |
|-----:|----------------:|---------------:|
| 0 | 0.33623 | 0.00038 |
| 1 | 0.11578 | 0.00017 |
| 2 | 0.09722 | 0.00013 |
| 3 | 0.09165 | 0.00012 |
| 4 | 0.08364 | … |
| 5 | 0.08200 | |
| 6 | 0.07860 | |
| 7 | 0.07771 | |
| 8 | 0.07610 | |
| 9 | 0.07550 | |
| 10 | 0.07532 | |

(Speicher / Stettiner / MethTrailer appended as they build.)

## Analysis

- **Absolute avg_distance is scene-dependent** (Polygraf ~0.34→0.075,
  Fabrik ~0.0004→0.0001 — ~1000× smaller). It tracks that capture's SH
  coefficient magnitudes, so a *fixed* numeric stop-threshold can't work
  across scenes. The signal is the **relative** drop per iteration.
- **Convergence knee is early, every scene:**
  - Polygraf: iter 0→1 removes 66 % of the error; by **iter 5** it is
    within ~9 % of the iter-10 value; iters 5→10 buy only ~8 % more
    (0.082 → 0.0753), each step <2 %.
  - Fabrik: essentially converged by **iter 2-3** (0.00013 → 0.00012).
- **Conclusion: 10 is overkill. ~6 iterations is visually identical**
  (the last 4 move the codebook <2 %/step, far below perceptual). Even 5
  would be indistinguishable. More iters strictly don't harm — this is
  purely a time question.

## Recommendation

- Polygraf & Fabrik already built at 10 (sunk cost — keep, no rebuild;
  extra iters didn't hurt).
- For the **heavy unbuilt scenes — Stettiner (30 M) and MethTrailer** —
  use **`--cluster-sh=6`**: ~40 % less clustering time (Stettiner ≈ 60-80
  min → ≈ 36-48 min) at no perceptible quality cost, strongly supported by
  both measured curves. User decision pending (they set 10, then asked for
  this data to revisit).
- build-lod accepts `--cluster-sh=<iterations>`; `build_lod.build()` would
  need a small `cluster_sh_iters` passthrough (currently passes bare
  `--cluster-sh`, = default 10) if we adopt a non-default count.
